# LangGraph Agent 设计文档

## 概述

本设计文档详细描述了 `LangGraphAgent` 类的架构设计，特别是**消息流转机制**。该 Agent 基于 LangGraph v2 API 实现，采用两节点架构（chatbot + tool_executor），支持流式输出和人工中断（HITL）机制。

## 核心架构

### 1. 图结构

```
START → chatbot ──┬→ tool_executor → chatbot
                  └→ END
```

- **chatbot 节点**：LLM 决策节点，负责生成响应或工具调用
- **tool_executor 节点**：工具执行节点，负责执行工具调用并返回结果
- **条件路由**：根据是否存在 `pending_tool_calls` 决定流向

### 2. State 定义

```python
class State(TypedDict):
    messages: Annotated[list, add_messages]  # 通过 add_messages 合并策略管理对话历史
    pending_tool_calls: list  # 存储待执行的工具调用
```

- `messages`：采用 `add_messages` 合并策略，自动处理消息追加
- `pending_tool_calls`：显式存储待执行的工具调用信息

## 消息流转详解

### 1. 初始状态

| 字段 | 值 |
|------|-----|
| `messages` | `[system_prompt, ...history, {"role": "user", "content": "用户输入"}]` |
| `pending_tool_calls` | `[]`（初始为空） |

### 2. chatbot 节点处理流程

1. **输入**：当前 `State`（包含完整 `messages` 和空 `pending_tool_calls`）
2. **LLM 调用**：
   ```python
   async for chunk in llm_with_tools.astream(state["messages"]):
       chunks.append(chunk)
   ```
3. **响应处理**：
   - **无工具调用**：直接返回 `AIMessage`，`messages` 增加 AI 响应
   - **有工具调用**：
     ```python
     update = {"messages": [response]}
     if response.tool_calls:
         update["pending_tool_calls"] = response.tool_calls
     ```
     → `pending_tool_calls` 被填充，`messages` 仅包含 LLM 的 `AIMessage`（含 tool_calls）

### 3. 路由决策

```python
@staticmethod
def _route_from_chatbot(state: State) -> Literal["tool_executor", "__end__"]:
    if state.get("pending_tool_calls"):
        return "tool_executor"
    return END
```

- **存在 pending_tool_calls** → 跳转至 `tool_executor`
- **无 pending_tool_calls** → 直接结束流程

### 4. tool_executor 节点处理流程

1. **输入**：当前 `State`（包含 `pending_tool_calls`）
2. **工具执行**：
   ```python
   for tool_call in pending:
       result = func(**tool_args, state=state)
       results.append({
           "role": "tool",
           "tool_call_id": tool_call_id,
           "content": result,
       })
   ```
3. **状态更新**：
   ```python
   return {
       "messages": results,  # 添加工具执行结果
       "pending_tool_calls": []  # 清空待执行列表
   }
   ```

### 5. 消息流转完整示例（查询天气）

| 步骤 | messages 结构 | pending_tool_calls | 说明 |
|------|---------------|---------------------|------|
| 初始 | `[system, {"user": "北京天气"}]` | `[]` | 用户输入触发流程 |
| chatbot | `[system, {"user": "北京天气"}, {"ai": "我来帮您查询北京的天气情况。", tool_calls=[{name: "get_weather"}]}]` | `[{"name": "get_weather", "args": {"location": "北京"}}]` | LLM **同时生成**自然语言说明（"我来帮您查询..."）和工具调用指令 |
| 路由 | 同上 | `[{"name": "get_weather", "args": {"location": "北京"}}]` | 检测到 pending_tool_calls → 跳转至 tool_executor |
| tool_executor | `[system, {"user": "北京天气"}, {"ai": "我来帮您查询北京的天气情况。", tool_calls=[...]}, {"tool": "北京25℃，晴天"}]` | `[]` | 执行工具并返回详细天气信息 |
| 返回 chatbot | 同上 | `[]` | 无 pending → 生成最终回复 |
| 结束 | `[system, {"user": "北京天气"}, {"ai": "我来帮您查询北京的天气情况。", tool_calls=[...]}, {"tool": "北京25℃，晴天"}, {"ai": "北京今天是晴天，气温25℃，天气很不错！"}]` | `[]` | LLM基于工具结果生成最终自然语言回复 |

### 6. 流式输出机制

- **stream_mode="messages"**：自动拦截 `astream` token，实现打字机效果
- **中断检测**：通过 `stream_mode=["messages", "updates"]` 捕获中断事件
  ```python
  if chunk["type"] == "updates":
      if node_name == "__interrupt__":
          interrupted = True
  ```

## 中断与恢复机制

### 1. 中断触发

当工具内部调用 `interrupt()` 时：
- 生成 `__interrupt__` 事件
- 暂停流程并等待人工决策

### 2. 恢复执行

``python
async for chunk in self._graph.astream(
    Command(resume=decision),  # 必须使用 Command 对象
    config=config,
    ...
):
```

- **决策类型**：`approve`（继续执行）、`reject`（取消执行）
- **关键规范**：必须使用 `langgraph.types.Command` 恢复，而非直接传入状态

## 资源管理规范

### 1. 异步 Checkpointer 初始化

``python
async with AIOMySQLSaver.from_conn_string(self.mysql_dsn) as checkpointer:
    await checkpointer.setup()
    self._graph = self._build_graph(checkpointer)
```

- **必须顺序**：实例化 → `__aenter__` → `setup()` → 编译 Graph
- **避免错误**："No checkpointer set" 错误通常因初始化顺序错误导致

### 2. 双重检查锁定模式

为确保 Graph 只初始化一次：
1. 检查资源是否存在
2. 获取 `asyncio.Lock`
3. 锁内二次检查
4. 初始化资源

## 关键方法说明

### `chat()` 方法流程

1. **初始化**：设置 `thread_id` 和回调函数
2. **Checkpointer 准备**：建立数据库连接并初始化
3. **首次执行**：处理用户输入，可能触发中断
4. **中断恢复**：根据用户决策继续执行
5. **结果提取**：从最终状态中获取 AI 响应

### `_extract_final_response()`

```python
for msg in reversed(messages):
    if isinstance(msg, AIMessage) and msg.content and not msg.tool_calls:
        return msg.content
```

- **提取规则**：倒序查找首个无工具调用的 `AIMessage` 内容
- **确保**：返回的是最终人类可读的回复文本