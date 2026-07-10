# AbstractTool LangGraph 工作流逻辑梳理

## 一、整体架构

`AbstractTool` 是基于 LangGraph 构建的多 Agent 工作流框架。核心思想是：

- **一个父图**：包含意图识别、路由、业务 Agent、切换话题等节点
- **多个业务 Agent**：每个 Agent 是一个 `chatbot ↔ tool_executor` 的 ReAct 循环，作为父图中的节点
- **所有 Agent 共享同一个 StateGraph**（非子图），流式输出天然可用
- **友好回应/结束业务**不在图内处理，而是由 `process_user_input` 在图执行完后根据最终 `intent_type` 后置处理，避免重复数据库记录

### 类继承关系

```
AbstractAI
    ↑
AbstractTool
    ↑
具体业务工具类（子类实现）
```

---

## 二、State 状态定义

所有节点共享同一个 `State`（TypedDict）：

| 字段 | 类型 | 说明 |
|------|------|------|
| `messages` | `List[WarappedMessage]` | 所有消息列表，带 `agent_name` 标识归属，使用 `add_wrapped_messages` reducer（按 message.id 去重追加） |
| `pending_tool_calls` | `list` | 待执行的工具调用列表 |
| `current_input` | `str` | 用户当前输入 |
| `exe_step` | `int` | 当前轮次执行步数，每次 process_user_input 重置为 0 |
| `_return_direct_tracker` | `dict` | `{tool_call_id: return_direct_bool}`，追踪工具是否直接返回 |
| `business_type` | `Optional[str]` | 业务类型（意图识别后设置） |
| `intent_type` | `Optional[str]` | 意图类型（意图识别后设置） |
| `friendly_response` | `Optional[str]` | 友好回应文本 |

`WarappedMessage` 结构：
```python
@dataclass
class WarappedMessage:
    message: BaseMessage   # 实际的 LangChain 消息
    agent_name: str        # 消息所属的 Agent 名称
    create_at: datetime    # 创建时间
```

---

## 三、LangGraph 工作流图结构

### 3.1 图的构建（`_build_graph`）

```
START → _intent_identify_node_ → [条件路由]
                                      │
                    ┌─────────────────┼─────────────────┐
                    ▼                 ▼                 ▼
          {business}_chatbot   _change_topic_     END (兜底)
          ↔ tool_executor      node_ → END      (friendly_response,
                (循环)                            end_business, 未知意图)
```

### 3.2 节点清单

| 节点名 | 功能 | 说明 |
|--------|------|------|
| `START` | 入口 | → `_intent_identify_node_` |
| `_intent_identify_node_` | 意图识别 | 调用 LLM 分析用户意图，返回 4 种意图之一 |
| `{business_type}_chatbot` | 业务 Agent 对话 | 调用 LLM + tools，生成回复或工具调用 |
| `{business_type}_tool_executor` | 工具执行器 | 执行 chatbot 产生的工具调用（支持串行/并行） |
| `_change_topic_node_` | 切换话题 | 保存切换话题日志 → END |
| `END` | 结束 | |

> **注意**：`_generate_friendly_response_node_` 已从图中移除。`friendly_response` 和 `end_business` 意图直接在路由中返回 `END`，由 `process_user_input` 后置处理。

### 3.3 边（Edge）清单

| 源节点 | 目标节点 | 类型 |
|--------|----------|------|
| `START` | `_intent_identify_node_` | 固定边 |
| `_intent_identify_node_` | 条件路由 | 条件边（`_route_from_intent_node_`） |
| `_change_topic_node_` | `END` | 固定边 |
| `{business_type}_chatbot` | `{business_type}_tool_executor` | 条件边（有待调用工具时） |
| `{business_type}_chatbot` | `END` | 条件边（无待调用工具时） |
| `{business_type}_tool_executor` | `{business_type}_chatbot` | 固定边（循环回 chatbot） |

---

## 四、核心节点详解

### 4.1 意图识别节点（`_intent_identify_node_`）

**功能**：调用 LLM 分析用户输入，识别出 4 种意图之一：

| 意图类型 | 常量 | 含义 | 路由目标 |
|----------|------|------|----------|
| `continue_business` | `INTENT_CONTINUE_BUSINESS` | 继续办理业务 | 对应业务 Agent 的 `chatbot` 节点 |
| `friendly_response` | `INTENT_FRIENDLY_RESPONSE` | 需要友好回应 | `END`（由 `process_user_input` 处理） |
| `change_topic` | `INTENT_CHANGE_TOPIC` | 切换话题 | `_change_topic_node_` |
| `end_business` | `INTENT_END_BUSINESS` | 结束办理 | `END`（由 `process_user_input` 处理） |

**流程**：
1. 构建系统提示词（调用子类 `_build_intent_analysis_prompt`）
2. 拼接历史对话 + 当前用户输入
3. 调用 `llm.ainvoke()` 获取意图分析结果
4. 解析 JSON 响应，提取 `intent_type`、`business_type`、`friendly_response`
5. 返回 `Command(update={...})` 更新 State
6. 无法解析或异常时：通过 writer 推送错误提示 → `goto=END`

### 4.2 意图路由（`_route_from_intent_node_`）

根据 State 中的 `intent_type` 决定下一步：

```python
if intent_type == "continue_business":
    return self._agent_node_map[business_type]  # → {business_type}_chatbot
if intent_type == "change_topic":
    return "_change_topic_node_"
# friendly_response、end_business 及未知意图：直接结束工作流，由 process_user_input 处理
return END
```

### 4.3 业务 Agent 内部循环（LangGraphAgentBuilder）

每个业务 Agent 内部是一个 **ReAct 循环**：

```
chatbot 节点 → [有待调用工具?] → tool_executor 节点 → chatbot 节点 (循环)
                   │(无)
                   ▼
                  END
```

#### chatbot 节点流程

1. **检查 return_direct**：如果上一轮所有工具都是 `return_direct=True`，跳过 LLM 直接结束
2. **构建消息列表**：
   - `use_all_messages=True`：从全局 messages 获取所有历史 + 快照消息
   - `use_all_messages=False`：按 `agent_name` 筛选私有历史
   - `exe_step==0` 时追加当前用户输入
3. **消息裁剪**：按 `history_max_records` 裁剪，确保第一条是 HumanMessage
4. **添加 SystemMessage**
5. **流式调用 LLM**：`llm_with_tools.astream()` → 通过 `get_stream_writer()` 推送每个 token
6. **合并 chunks** 为完整 AIMessage
7. **包装为 WarappedMessage** 更新到 State

#### tool_executor 节点流程

1. 获取 `pending_tool_calls` 列表
2. 对每个工具调用执行 `_execute_one`：
   - 查找工具函数
   - 注入 `ToolRuntime` 和 `context`（根据函数签名自动检测）
   - 执行工具（同步或异步）
   - 构建 `ToolMessage`
   - 如果 `return_direct=True`：构建 `AIMessageChunk` 并通过 writer 推送
3. **执行方式**：
   - `use_paraller=True`：`asyncio.gather()` 并行执行
   - `use_paraller=False`：顺序执行
4. 收集结果，更新 State（ToolMessage + return_direct tracker）

### 4.4 切换话题节点（`_change_topic_node_`）

1. 获取意图分类节点 ID（`intent_classify_node_id` 或 `entry_node_id`）
2. 如果当前节点 **不是** 入口节点：
   - 保存切换话题日志到数据库（用于大模型后续分析）
3. 返回 `Command(update=None)` → 固定边流转到 `END`

> 切换话题的用户输入委托处理不在图内，而在 `process_user_input` 后置处理。

---

## 五、主流程：process_user_input

```
1. _ensure_initialized() → 初始化 node、llm、business_agents
2. 检查 run_steps 是否超限
3. 加载聊天历史（从 DB 或 context）
4. 构建 input_data 和 config
5. 创建 AIOMySQLSaver checkpointer（MySQL 持久化）
6. _build_graph() 构建图
7. 加载历史线程消息（快照）
8. agent.astream() 流式执行，处理 chunk：
   - type="updates"：处理节点更新（含中断）
   - type="custom"：处理自定义流式消息（AIMessageChunk）
9. 获取最终状态快照，读取 intent_type
10. 根据 intent_type 后置处理：
    a. change_topic 且非入口节点 → 委托给 intent_node.process_user_input() → return
    b. change_topic 且是入口节点 → generate_friendly_response_stream() → return
    c. friendly_response / end_business → generate_friendly_response_stream() → return
    d. 其他（continue_business 正常完成） → 走正常业务流程
11. end_business() 清理
12. 处理中断消息（interrupt_messages）或正常响应
13. 保存对话记录到数据库
14. 记录 token 使用量
15. 输出最终结束标记
```

### 后置处理逻辑详解

| 意图类型 | 是否入口节点 | 处理方式 |
|----------|-------------|----------|
| `change_topic` | 否 | 委托给 `intent_node.process_user_input()`，由该节点自身工作流处理响应和数据库记录 |
| `change_topic` | 是 | 调用 `self.generate_friendly_response_stream()` 生成友好回应 |
| `friendly_response` | 否 | 委托给 `intent_node.generate_friendly_response_stream()` |
| `friendly_response` | 是 | 调用 `self.generate_friendly_response_stream()` |
| `end_business` | 否 | 委托给 `intent_node.generate_friendly_response_stream()` |
| `end_business` | 是 | 调用 `self.generate_friendly_response_stream()` |

> **设计原因**：`generate_friendly_response_stream` 内部会自动保存数据库记录。如果在图节点内调用，会导致与 `process_user_input` 末尾的数据库保存逻辑重复。因此将友好回应生成移到图外，由 `process_user_input` 统一调度。

### 流式处理（`_process_stream_chunk`）

| chunk type | 处理逻辑 |
|------------|----------|
| `updates` | 检查 `__interrupt__`，收集中断信息 |
| `custom` + `AIMessageChunk` | 提取 content，构建流式消息推送 |
| `custom` + `dict` | 直接作为流式消息推送 |

### 中断机制

1. 工具执行时抛出 `GraphInterrupt` → LangGraph 自动捕获
2. 收集 `interrupt_messages`（含 thread_id 和 interrupt_id）
3. 将中断信息序列化保存到数据库
4. 下次用户输入时，设置 `context.is_user_input_interrupt_ack=True`
5. 解析用户输入为 `Command(resume=resume_map)` 恢复执行

---

## 六、子类需实现的抽象方法

| 方法 | 说明 |
|------|------|
| `_initialize_tool(context)` | 初始化业务 Agent 列表，返回 `List[BusinessAgentInfo]` |
| `_build_intent_analysis_prompt(context)` | 构建意图分析的系统提示词 |

`BusinessAgentInfo` 结构：
```python
@dataclass
class BusinessAgentInfo:
    business_type: str       # 业务类型标识
    tools: List[BaseTool]    # 工具列表
    system_prompt: str       # 系统提示词
```

---

## 七、关键设计要点

### 7.1 消息管理
- **统一存储**：所有消息用 `WarappedMessage` 包装，带 `agent_name` 标识
- **全局 vs 私有**：`use_all_messages` 控制 Agent 是否能看到其他 Agent 的历史
- **快照机制**：从数据库加载已完成的线程消息作为 `snapshot_messages`，拼接到当前会话前
- **Reducer 去重**：`add_wrapped_messages` 按 `message.id` 去重，避免重复追加

### 7.2 流式输出
- 所有 Agent 在同一图中（非子图），流式输出天然可用
- chatbot 节点通过 `get_stream_writer()` 推送 LLM token
- tool_executor 对 `return_direct` 工具直接推送结果

### 7.3 工具执行
- **return_direct**：标记工具是否直接返回，跳过 LLM 总结
  - 全部 `return_direct=True` → 直接结束，不调用 LLM
  - 否则 → 回到 chatbot 让 LLM 总结工具结果
- **并行/串行**：`use_paraller` 控制，并行用 `asyncio.gather`
- **自动注入**：根据函数签名自动注入 `ToolRuntime` 和 `context`

### 7.4 状态持久化
- 使用 `AIOMySQLSaver` 将 State 持久化到 MySQL
- `JsonPlusSerializer` 支持自定义类型序列化（`WarappedMessage`）
- `thread_id` 关联会话和节点

### 7.5 并发安全
- 初始化使用 `asyncio.Lock` 防止重复初始化
- `_initialized` 标志 + 双重检查锁定模式

### 7.6 图内外职责分离
- **图内**：意图识别、业务 Agent 对话循环、切换话题日志记录
- **图外**（`process_user_input`）：根据最终 `intent_type` 后置处理友好回应生成、切换话题委托、数据库保存
- **优势**：避免图节点内调用 `generate_friendly_response_stream` 导致重复数据库记录
