# AbstractTool（LangGraph 版）使用指南

> 对应代码：`app/tool/abstract_tool_lang_graph.py`
> 相关文档：`docs/abstract_tool_lang_graph_analysis.md`（内部工作流逻辑梳理）

## 一、类体系

```
AbstractAI (app/abstract_ai.py)                          ← 顶层抽象基类
  └── AbstractTool (app/tool/abstract_tool_lang_graph.py) ← 工具基类（多业务 Agent 版）
        └── 具体业务工具子类
```

注意：项目中存在**两个** `AbstractTool`：

| 版本 | 文件 | 架构 |
|------|------|------|
| 旧版 | `app/tool/abstract_tool.py` | 单 Agent（一组 tools + 一个 prompt），用 `create_agent` 构建 |
| 新版 | `app/tool/abstract_tool_lang_graph.py` | 多业务 Agent，用 `StateGraph` 手工构建 |

新版是重构版本，基类接管了全部工作流逻辑，子类只需专注业务配置。

## 二、运行机制（基类全部接管，子类无需关心）

### 2.1 父图结构

`_build_graph` 构建如下父图：

```
START → _intent_identify_node_ (LLM 意图识别)
         ├─ continue_business → {business_type}_chatbot ↔ {business_type}_tool_executor 循环 (ReAct)
         ├─ change_topic      → _change_topic_node_ → END
         └─ friendly_response / end_business → END
```

- 每个业务 Agent 通过 `LangGraphAgentBuilder.add_to_graph` 以**节点**（非子图）形式加入父图，流式输出天然可用。
- 所有消息统一存入 `State.messages`（`WarappedMessage` 列表，带 `agent_name` 标识归属）。
- 意图路由依赖 `_agent_node_map`（`business_type → chatbot 节点名`）跳转到对应业务 Agent。

### 2.2 process_user_input 接管的事项

| 事项 | 说明 |
|------|------|
| 惰性初始化 | `_ensure_initialized` 双重检查锁，首次调用时从 DB 加载 node/llm 并调用子类 `_initialize_tool` |
| 步数限制 | `run_steps > run_steps_max` 时拒绝处理 |
| 历史加载 | 按配置从 DB 拉取聊天历史；业务结束后新 thread 可从旧 thread 快照恢复历史 |
| 持久化 | MySQL checkpointer（`AIOMySQLSaver`），`thread_id` 由 `ZbConversationBusinessStateUtil` 管理 |
| HITL 中断/恢复 | 工具内 `interrupt()` → 打包 `{thread_id}:{interrupt_id}` JSON 推给前端并落库；用户回复后经 `Command(resume=...)` 恢复 |
| 话题切换/友好回应 | 图执行完后根据最终 `intent_type` 后置处理，必要时移交给意图分类节点 |
| 落库与统计 | 对话记录、token 用量、延迟统计 |

## 三、子类写法（完整示例）

只需实现 3 个抽象方法 + 传 `node_id`。下面以会议室预订场景为例（对照 `app/tool/xb_bangong/tool_book_meeting_room.py`，按新版多业务 Agent 架构改写）。

**本节示例完全自包含**：为了便于理解，示例**不依赖数据库**，三个提示词直接用 Python 字符串常量内联在子类文件里。

生产环境推荐把提示词存到 `zb_node_prompt` 表，再用 `_default_cache.format_prompt(node_id, prompt_key, var_values)` 读取。它的核心实现只有一句 `prompt_content.format(**merged_values)`（见 `app/db_connection_pool/zb_node_prompt_util.py:444`），**与「内联模板 + `str.format()`」的效果完全等价**——区别仅在于模板从数据库来、还是写在代码里。

两者可以随时互换：

```python
# 内联版（本文档采用，便于阅读）
text = PROMPT_TOOL_CALL.format(
    node_name="小邦会议室助手", user_name="张三", current_time="2026-09-17 10:00:00",
)

# 数据库版（生产用法）
text = await _default_cache.format_prompt(
    "tool_meeting_room", "prompt_tool_call",
    {"node_name": "小邦会议室助手", "user_name": "张三", "current_time": "2026-09-17 10:00:00"},
)
```

> 注意 `format_prompt` 的取值优先级是 **`zb_node_prompt_var` 表里的 `prompt_var_value` > 代码传入的 `var_values`**。

### 3.1 定义工具

```python
from pydantic import BaseModel, Field
from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime
from langgraph.types import interrupt
from ..util.interrupt_message import InterruptMessage
from ..util.resume_message import ResumeMessage


# ========== 参数 Schema ==========

class BookMeetingRoomArgs(BaseModel):
    """预订会议室的参数"""
    meeting_room_name: str = Field(title="会议室名称",
        description="预订的会议室名称（从 get_meeting_room_available_time_periods 返回的 name 字段获取）")
    begintime: str = Field(title="开始时间", description="预订开始时间，格式为 %Y-%m-%d %H:%M:%S")
    endtime: str = Field(title="结束时间", description="预订结束时间，格式为 %Y-%m-%d %H:%M:%S")


class GetMeetingRoomAvailableTimePeriodsArgs(BaseModel):
    """查询会议室可用时间段的参数"""
    begintime: str = Field(default=None, title="查询开始时间", description="查询开始时间，格式为 %Y-%m-%d %H:%M:%S")
    endtime: str = Field(default=None, title="查询结束时间", description="查询结束时间，格式为 %Y-%m-%d %H:%M:%S")


# ========== 工具函数 ==========

@tool(args_schema=GetMeetingRoomAvailableTimePeriodsArgs,
      description="查询指定时间段内会议室的可用（空闲）时间段，便于用户选择合适的预订时间")
async def get_meeting_room_available_time_periods(
    begintime: str = None,
    endtime: str = None,
    run_time: ToolRuntime[ChatContext] = None,
) -> str:
    """查询会议室可用时间段 — 安全操作，直接执行"""
    context = run_time.context      # ToolRuntime 参数由 tool_executor 自动注入，模型不会生成它
    # ... 调用查询接口、计算可用时间段 ...
    return f"查询时间段：{begintime} 至 {endtime}\n会议室可用时间段：{result_json}"


@tool(args_schema=BookMeetingRoomArgs,
      description="预订指定的会议室（需人工确认）", return_direct=True)
async def book_meeting_room(
    meeting_room_name: str,
    begintime: str,
    endtime: str,
    run_time: ToolRuntime[ChatContext],
) -> str:
    """预订会议室 — 需人工确认，工具内部自行 interrupt"""
    context: ChatContext = run_time.context
    user_name = context.user_name if context and context.user_name else "未知用户"

    # ... 业务校验（时间格式、是否早于当前时间、跨天、时长不超过1小时等），失败直接 return 错误说明 ...

    # HITL 中断：向用户确认预订信息，图在此暂停并持久化，等待用户回复后恢复
    interrupt_msg = (f"以下是您要预定的会议室信息：\n- 会议室：{meeting_room_name}\n"
                    f"- 开始时间：{begintime}\n- 结束时间：{endtime}\n- 预订人：{user_name}\n\n确认要预定吗？")
    interrupt_message = InterruptMessage(
        interrupt_bisiness_type="book_meeting_room",
        interrupt_message=interrupt_msg,
        extra_info={}
    )
    resume_value = interrupt(interrupt_message.to_json_str())   # ← 恢复执行时，此处返回用户回复

    # 使用 ResumeMessage 解析用户恢复输入
    resume_message: ResumeMessage = ResumeMessage.from_json_str(resume_value)
    if resume_message.resume_message != '确认':
        return f"用户 {user_name} 取消预定。"

    # 用户确认后，调用 API 执行预订（略）...
    context.set_business_state_completed()   # 标记业务完成，下轮生成新 thread_id
    return f"已成功预订会议室（会议室名称: {meeting_room_name}）。"
```

工具定义要点：

- `run_time: ToolRuntime[ChatContext]`（或名为 `context` 的 `ChatContext` 参数）由 `tool_executor` 自动注入，**不会**出现在模型的工具参数中。
- `return_direct=True`：工具结果直接通过流式推送给用户，不回 chatbot 让 LLM 总结；`False` 则结果回 LLM 继续推理。
- 工具返回 `str` 即可，框架自动包装为 `ToolMessage` 存入 `messages`。
- 需要人工确认的工具，用 `interrupt()` + `InterruptMessage`/`ResumeMessage` 协议（见第四节第 4 条）。

### 3.2 三个提示词模板（内联在代码里，便于理解）

三个提示词的作用：

| 常量 | 对应 prompt_key | 用途 | 可用变量 |
|------|-----------------|------|----------|
| `PROMPT_TOOL_CALL` | `prompt_tool_call` | 业务 Agent 的 `system_prompt`（决定它怎么干活、用哪些工具） | `{node_name}` `{user_name}` `{current_time}` |
| `PROMPT_FRIENDLY_RESPONSE` | `prompt_friendly_response` | 寒暄闲聊时的友好回应 | `{node_name}` |
| `PROMPT_INTENT_ANALYSIS` | `prompt_intent_analysis` | 意图识别节点的 `system_prompt`（决定路由到哪个业务） | 4 个 `{INTENT_*}` + `{business_scope}` |

```python
# ============================================================
# 提示词模板（示例内联；生产环境可存 zb_node_prompt 表，用 _default_cache.format_prompt 读取）
# 用法：str.format(**变量) 替换 {xxx}；模板里出现的 JSON 花括号必须写成 {{ }}
# ============================================================

PROMPT_TOOL_CALL = """你是 {node_name}，专门帮助用户查询和预订会议室的智能助手。
当前用户：{user_name}
当前时间：{current_time}

你可以使用以下工具：
1. get_meeting_room_available_time_periods - 查询指定时间段内会议室的空闲时间段
2. book_meeting_room - 预订指定的会议室（需用户确认）

工作流程：
- 如果用户想查看会议室空闲情况，先调用查询工具
- 如果用户想预订会议室，需要先确认会议室名称、开始时间和结束时间
- 5001 会议室不可预订，请提醒用户选择其他会议室

注意事项：
- 预订时间不能跨天，不能超过1小时
- 不能预订已经过去的时间段
- 会议室开放时间为每天 08:00-20:00
"""

PROMPT_FRIENDLY_RESPONSE = """你是 {node_name}，一个帮助用户预订会议室的智能助手。
请用友好、自然的语气回复用户的寒暄或闲聊，并引导用户说明会议室预订需求。
"""

PROMPT_INTENT_ANALYSIS = """你是一个意图分析助手，用于判断用户输入的意图类型。

背景：用户当前正在使用会议室预订服务。请根据用户最新输入，判断其意图属于以下哪种类型：

1. {INTENT_CONTINUE_BUSINESS}：用户想继续办理会议室预订相关业务
2. {INTENT_FRIENDLY_RESPONSE}：用户只是在闲聊、寒暄、问候或询问与你相关的问题
3. {INTENT_CHANGE_TOPIC}：用户想切换到其他业务话题
4. {INTENT_END_BUSINESS}：用户想结束当前业务

当意图为 {INTENT_CONTINUE_BUSINESS} 时，请进一步判断用户要办理哪项业务。
可选业务类型（business_type 的合法取值）：
{business_scope}

请以 JSON 格式返回结果：
{{"intent_type": "<意图类型>", "business_type": "<意图为 continue_business 时填写上述可选业务类型之一，其他情况为空字符串>", "friendly_response": "<切换话题时的友好回应文本，其他情况为空字符串>"}}

注意：仅在 intent_type 为 {INTENT_CHANGE_TOPIC} 时需要填写友好的回应文本。
"""
```

**渲染结果示例**。假设 `node_name="小邦会议室助手"`、`user_name="张三"`、`current_time="2026-09-17 10:00:00"`，节点只有 `meeting_room` 一项业务时：

`PROMPT_TOOL_CALL.format(...)` →（只展示前几行，其余略）

```text
你是 小邦会议室助手，专门帮助用户查询和预订会议室的智能助手。
当前用户：张三
当前时间：2026-09-17 10:00:00
...
```

`PROMPT_INTENT_ANALYSIS.format(...)` →（关键片段）

```text
1. continue_business：用户想继续办理会议室预订相关业务
2. friendly_response：用户只是在闲聊、寒暄、问候或询问与你相关的问题
3. change_topic：用户想切换到其他业务话题
4. end_business：用户想结束当前业务

当意图为 continue_business 时，请进一步判断用户要办理哪项业务。
可选业务类型（business_type 的合法取值）：
1. meeting_room

请以 JSON 格式返回结果：
{"intent_type": "<意图类型>", "business_type": "...", "friendly_response": "..."}
```

可见 `{{...}}` 被渲染成了 `{...}`（这正是提示词里 JSON 示例应有的样子）。

若节点提供多项业务（会议室预订 + 访客预约），`{business_scope}` 会渲染成：

```text
1. meeting_room
2. visitor_appointment
```

> `business_scope` 由子类在 `_build_intent_analysis_prompt` 中从 `self.business_agents` **动态拼接**（见 3.3），因此新增业务时提示词会自动跟着变，不会漏改。

### 3.3 子类实现（完整示例）

```python
from typing import List

from ..abstract_tool_lang_graph import AbstractTool, BusinessAgentInfo
from ..context.chat_context import ChatContext
from ..core.logger import app_logger as logger

# 三个 PROMPT_* 常量见 3.2，与本类位于同一个模块


class ToolBookMeetingRoom(AbstractTool):
    """会议室预订工具节点"""

    def __init__(self):
        super().__init__(node_id="tool_meeting_room")   # 必填，须在 zb_conversation_nodes 表中存在
        self.use_all_messages = True    # True=所有业务Agent共享全局历史；False=按 agent_name 隔离私有历史
        self.use_paraller = False       # False=同一轮的多个工具串行执行；True=asyncio.gather 并发

    # ---------- 抽象方法 1：声明本节点有哪些业务 Agent ----------
    async def _initialize_tool(self, context: ChatContext = None) -> List[BusinessAgentInfo]:
        """初始化：返回业务 Agent 列表（每个元素 = 一个独立的 ReAct 循环）"""
        logger.info(f"[会议室预订工具] 初始化工具，当前用户: {context.user_id}")

        # 把动态值填进模板，得到该业务的系统提示词
        meeting_room_prompt = PROMPT_TOOL_CALL.format(
            node_name=self.node.node_name,      # 如"小邦会议室助手"
            user_name=context.user_name,        # 当前用户姓名
            current_time=get_current_time(),    # 当前时间，注入给模型
        )

        return [
            BusinessAgentInfo(
                business_type="meeting_room",   # 路由键，必须与意图识别提示词中的标识严格一致
                tools=[get_meeting_room_available_time_periods, book_meeting_room],
                system_prompt=meeting_room_prompt,
            ),
        ]

    # ---------- 抽象方法 2：意图识别节点的 system prompt ----------
    async def _build_intent_analysis_prompt(self, context: ChatContext = None) -> str:
        """构建意图分析提示词（新版需约束 LLM 额外输出 business_type）"""
        # 动态拼接合法取值清单，与 _initialize_tool 返回的 BusinessAgentInfo 保持一致，
        # 避免提示词硬编码导致与代码不同步（LLM 填了不存在的 business_type 会导致路由失败）
        business_scope = "\n".join(
            f"{i}. {agent.business_type}" for i, agent in enumerate(self.business_agents, start=1)
        )
        return PROMPT_INTENT_ANALYSIS.format(
            INTENT_CONTINUE_BUSINESS=self.INTENT_CONTINUE_BUSINESS,   # "continue_business"
            INTENT_FRIENDLY_RESPONSE=self.INTENT_FRIENDLY_RESPONSE,   # "friendly_response"
            INTENT_CHANGE_TOPIC=self.INTENT_CHANGE_TOPIC,             # "change_topic"
            INTENT_END_BUSINESS=self.INTENT_END_BUSINESS,             # "end_business"
            business_scope=business_scope,                            # ← 关键：注入合法值清单
        )

    # ---------- 抽象方法 3：友好回应提示词 ----------
    async def _get_prompt_friendly_response(self, context: ChatContext = None) -> str:
        """获取友好回应提示词"""
        return PROMPT_FRIENDLY_RESPONSE.format(node_name=self.node.node_name)
```

若一个工具节点提供多个业务（如会议室预订 + 访客预约），`_initialize_tool` 返回多个 `BusinessAgentInfo`，各自独立的工具集和系统提示词，意图识别的 `business_type` 决定路由到哪个（见 5.6 场景 B）。

> **改用数据库版**：把 `PROMPT_XXX.format(**kw)` 换成 `await _default_cache.format_prompt(node_id, "prompt_xxx", kw)` 即可，其余逻辑完全不变。

### 3.4 与数据库现存提示词的差异（迁移必读）

以上三个提示词模板与 `zb_node_prompt` 表中现存内容的差异在于：

| 提示词 | 数据库现状（`init_data.sql`） | 新版要求 |
|--------|------------------------------|----------|
| `prompt_tool_call` | 已有 | 一致，无需改动 |
| `prompt_friendly_response` | 已有 | 一致，无需改动 |
| `prompt_intent_analysis` | **只约束输出 `intent_type` / `friendly_response`，且未枚举业务类型** | 必须补 `business_type` 输出字段，并枚举合法取值 |

**接入新版基类时 `prompt_intent_analysis` 必须做两处调整**：

1. 补上 `business_type` 输出字段（见 3.2 的 `PROMPT_INTENT_ANALYSIS`）；
2. 显式枚举合法取值——推荐由子类从 `self.business_agents` 动态拼接注入 `{business_scope}`（见 3.3），否则 LLM 只能凭空编造标识，`_route_from_intent_node_` 查不到映射时会路由到不存在的节点导致报错。

### 3.5 三个抽象方法一览

| 方法 | 职责 |
|------|------|
| `_initialize_tool` | 构造并返回 `List[BusinessAgentInfo]`，定义有哪些业务 Agent、各自的工具和系统提示词 |
| `_build_intent_analysis_prompt` | 意图识别节点的 system prompt，约束 LLM 输出含 `intent_type`/`business_type`/`friendly_response` 的 JSON |
| `_get_prompt_friendly_response` | 友好回应提示词（继承自 `AbstractAI`） |

### 3.6 构造函数可选配置

| 属性 | 默认值 | 说明 |
|------|--------|------|
| `use_all_messages` | `True` | `True`：chatbot 使用全局 `messages` 历史；`False`：按 `agent_name` 筛选各 Agent 私有历史 |
| `use_paraller` | `False` | `True` 时 `tool_executor` 用 `asyncio.gather` 并发执行同一轮的所有工具 |

## 四、关键约定

1. **node_id 必须配置到数据库**
   `zb_conversation_nodes` 表中该节点的 `node_func_path` 需指向子类（如 `app.tool.xxx.MyTool`），由 `ZbConversationNodesUtil.instantiate_node` 动态导入实例化；节点同时提供默认 LLM（`get_llm_by_node_id`）。

2. **prompt key 约定与模型覆盖**
   意图识别优先使用 `prompt_intent_analysis` 指定的 model_id 覆盖节点级 LLM（`resolve_prompt_model`）；未指定则回退 `self.llm`。

3. **business_type 是路由键**
   `business_type` 是**单个工具节点内部**的业务路由键，必须与 `BusinessAgentInfo.business_type` 及意图识别提示词中的标识**严格一致**。
   ⚠️ 这是最容易用错的地方，已单独拆到 **第五节** 详解（含流转链路、取值规范、单/多业务写法、报错排查表）。

4. **HITL 中断/恢复协议**
   - 工具内调用 `interrupt(InterruptMessage(...).to_json_str())` 触发中断；
   - 基类将中断信息打包为 `{thread_id}:{interrupt_id}` 的 JSON 推给前端并落库；
   - 用户下次回复时（`context.is_user_input_interrupt_ack`）解析为 `Command(resume=...)` 恢复执行，工具内 `interrupt()` 的返回值即用户回复。

5. **初始化是惰性的**
   `_ensure_initialized` 使用双重检查锁，首次 `process_user_input` 时才从 DB 加载 node/llm 并调用 `_initialize_tool`，并发安全。

6. **意图类型常量**（子类提示词需引用）
   - `INTENT_CONTINUE_BUSINESS`：继续办理业务
   - `INTENT_FRIENDLY_RESPONSE`：友好回应
   - `INTENT_CHANGE_TOPIC`：切换话题
   - `INTENT_END_BUSINESS`：结束办理业务

## 五、business_type 专题（最容易用错的地方）

### 5.1 一句话定义

`business_type` 是**单个工具节点内部**的「业务路由键」，用来回答一句话：

> 用户这次要办的，是**这个节点里的哪一项业务**？

它**不是** `node_id`（DB 里的节点 ID），**不是**给用户看的文案，也**不是** HITL 中断里的 `interrupt_bisiness_type`（见 5.10）。它只是框架内部用来「选一个业务 Agent」的标识。

### 5.2 为什么需要它

一个 tool 节点（`zb_conversation_nodes` 里的一行，例如 `tool_bangong`）可能同时承载多个**互不相干**的业务。基类会给每一项业务各开一个独立的 ReAct 循环（`{business_type}_chatbot` ↔ `{business_type}_tool_executor`），它们需要各自独立的：

- 工具集（`tools`）
- 系统提示词（`system_prompt`）
- 消息历史隔离（当 `use_all_messages=False` 时按 `agent_name` 筛选）

`business_type` 就是这个循环的**名字**，也是它的**主键**。

> **重要**：如果节点只有一项业务，**依然必须写 `business_type`**，因为基类的路由是无条件的（见 5.7）。

### 5.3 定义在哪、被谁消费

| 环节 | 代码位置 | 做了什么 |
|------|----------|----------|
| ① 声明（**唯一真源**） | 子类 `_initialize_tool` 返回的 `BusinessAgentInfo.business_type` | 由开发者写死的字符串 |
| ② 建图 | `_build_graph`（`abstract_tool_lang_graph.py` 中遍历 `self.business_agents`） | `agent_name = agent_info.business_type`；据此注册节点 `{business_type}_chatbot`、`{business_type}_tool_executor`；并缓存 `_agent_node_map[business_type] = "{business_type}_chatbot"` |
| ③ LLM 产出 | `_intent_identify_node_` → `_parse_json_response` | 从 LLM 返回的 JSON 里读 `business_type`（仅 `.strip()`），写进 State |
| ④ 路由 | `_route_from_intent_node_` | `self._agent_node_map.get(business_type, f"{business_type}_chatbot")`，返回值即下一个节点名 |

数据流向：

```
_initialize_tool()                         ← ① 你写的：BusinessAgentInfo(business_type="meeting_room")
        │
        ▼
_build_graph()                             ← ② 生成 "meeting_room_chatbot" / "meeting_room_tool_executor"
        │                                      并记录 _agent_node_map["meeting_room"] = "meeting_room_chatbot"
        ▼
_intent_identify_node_()                   ← ③ LLM 按 prompt_intent_analysis 输出 {"business_type": "meeting_room"}
        │  Command(update={"business_type": ...})
        ▼
_route_from_intent_node_()                 ← ④ _agent_node_map["meeting_room"] → 跳转到 "meeting_room_chatbot"
        │
        ▼
meeting_room_chatbot ↔ meeting_room_tool_executor
```

### 5.4 必须保持一致的三处（核心）

| # | 位置 | 归属 | 说明 |
|---|------|------|------|
| 1 | `BusinessAgentInfo.business_type` | 代码（子类） | 唯一真源，其他两处都以它为准 |
| 2 | `prompt_intent_analysis` 的**输出字段 + 合法值清单** | 提示词（DB / 代码） | 必须显式告诉 LLM 有哪些合法取值 |
| 3 | 运行期 LLM 实际返回的取值 | 运行时 | 必须能命中 `_agent_node_map` |

**关键认知：基类不会把合法取值告诉 LLM。** `abstract_tool_lang_graph.py` 中没有任何把 `self.business_agents` 注入提示词的逻辑——这件事**只能由子类在 `_build_intent_analysis_prompt` 里做**。

因此正确做法是：在 `_build_intent_analysis_prompt` 中从 `self.business_agents` **动态拼接**合法值清单，而不是在提示词里手写（手写必然随代码演进而失同步）。

模板里要预留一个 `{business_scope}` 占位（见 3.2 的 `PROMPT_INTENT_ANALYSIS`）：

```text
当意图为 {INTENT_CONTINUE_BUSINESS} 时，请进一步判断用户要办理哪项业务。
可选业务类型（business_type 的合法取值）：
{business_scope}
```

然后在子类里把 `self.business_agents` 拼成清单填进去（此处为内联版，等价于 `await _default_cache.format_prompt(...)`）：

```python
async def _build_intent_analysis_prompt(self, context: ChatContext = None) -> str:
    # 从 self.business_agents 动态生成合法值清单，保证与代码永远一致
    business_scope = "\n".join(
        f"{i}. {agent.business_type}" for i, agent in enumerate(self.business_agents, start=1)
    )
    return PROMPT_INTENT_ANALYSIS.format(
        INTENT_CONTINUE_BUSINESS=self.INTENT_CONTINUE_BUSINESS,   # "continue_business"
        INTENT_FRIENDLY_RESPONSE=self.INTENT_FRIENDLY_RESPONSE,   # "friendly_response"
        INTENT_END_BUSINESS=self.INTENT_END_BUSINESS,             # "end_business"
        INTENT_CHANGE_TOPIC=self.INTENT_CHANGE_TOPIC,             # "change_topic"
        business_scope=business_scope,   # ← 关键：注入合法值清单
    )
```

> 安全性说明：`_build_intent_analysis_prompt` 在图内被调用时，`self.business_agents` 一定已就绪——因为 `process_user_input` 开头就 `await self._ensure_initialized(context)`，而 `_initialize_tool` 正是在其中完成的。所以动态拼接是安全且推荐的。

### 5.5 取值规范

| 要求 | 说明 |
|------|------|
| 格式 | 自定义字符串，**建议英文小写 + 下划线**，如 `meeting_room`、`visitor_appointment` |
| 不要用 `node_id` | 它是节点**内部**的路由键，跟 DB 节点 ID 是两回事，别把 `tool_meeting_room` 直接当 `business_type` 用（能用，但会把两层概念搅在一起） |
| 唯一性 | 同一个节点内不可重复；重复会导致 `_agent_node_map` 被后者覆盖 |
| 命名 | 它会直接拼进 LangGraph 节点名，避免空格、`:`、中文等；**不要以 `__` 开头**（LangGraph 内部保留，如 `__interrupt__`） |
| 大小写 | 路由是**精确 dict 匹配**，不做 `lower()`；`Meeting_Room` ≠ `meeting_room` |
| 持久化 | 不落库、不展示给用户，纯内部标识 |

### 5.6 两种场景的写法

下面都用**内联提示词**（不查数据库），把注意力集中在 `business_type` 上。

#### 场景 A：单业务（也必须写）

节点只有一项业务时，仍然要有一个唯一的 `business_type`，并且提示词必须让 LLM 输出它。

```python
# 该业务自己的系统提示词（内联；完整版见 3.2）
PROMPT_TOOL_CALL = """你是 {node_name}，专门帮助用户查询和预订会议室的智能助手。
当前用户：{user_name}
当前时间：{current_time}
...
"""

async def _initialize_tool(self, context: ChatContext = None) -> List[BusinessAgentInfo]:
    prompt = PROMPT_TOOL_CALL.format(
        node_name=self.node.node_name,
        user_name=context.user_name,
        current_time=get_current_time(),
    )
    return [
        BusinessAgentInfo(
            business_type="meeting_room",   # ← 仍需填，且必须与提示词里的取值一致
            tools=[get_meeting_room_available_time_periods, book_meeting_room],
            system_prompt=prompt,
        ),
    ]
```

此时 `_build_intent_analysis_prompt` 会把 `{business_scope}` 渲染成：

```text
可选业务类型（business_type 的合法取值）：
1. meeting_room
```

LLM 因此只会返回 `"business_type": "meeting_room"`，路由到 `meeting_room_chatbot`。

#### 场景 B：多业务（真正发挥分流作用）

两项业务各有**内容不同**的系统提示词，各有**互不相干**的工具：

```python
# 业务 1：会议室预订
PROMPT_MEETING_ROOM = """你是 {node_name}，负责会议室查询与预订。
当前用户：{user_name}
当前时间：{current_time}
可用工具：get_meeting_room_available_time_periods、book_meeting_room
规则：预订不能跨天、不超过 1 小时；5001 会议室不可预订。
"""

# 业务 2：访客预约
PROMPT_VISITOR_APPOINTMENT = """你是 {node_name}，负责访客来访预约登记。
当前用户：{user_name}
当前时间：{current_time}
可用工具：query_visitor_slots、book_visitor_appointment
规则：需登记来访人姓名、联系方式与到访时段；最多提前 7 天预约。
"""

async def _initialize_tool(self, context: ChatContext = None) -> List[BusinessAgentInfo]:
    fmt = {
        "node_name": self.node.node_name,
        "user_name": context.user_name,
        "current_time": get_current_time(),
    }
    return [
        BusinessAgentInfo(
            business_type="meeting_room",
            tools=[get_meeting_room_available_time_periods, book_meeting_room],
            system_prompt=PROMPT_MEETING_ROOM.format(**fmt),
        ),
        BusinessAgentInfo(
            business_type="visitor_appointment",
            tools=[query_visitor_slots, book_visitor_appointment],
            system_prompt=PROMPT_VISITOR_APPOINTMENT.format(**fmt),
        ),
    ]
```

此时 `_build_intent_analysis_prompt` 渲染出的 `{business_scope}` 是：

```text
可选业务类型（business_type 的合法取值）：
1. meeting_room
2. visitor_appointment
```

LLM 返回哪个值，就走哪一套工具与提示词。

此时 `_build_graph` 会注册 4 个节点：`meeting_room_chatbot`、`meeting_room_tool_executor`、`visitor_appointment_chatbot`、`visitor_appointment_tool_executor`；`_agent_node_map` 为：

```python
{"meeting_room": "meeting_room_chatbot", "visitor_appointment": "visitor_appointment_chatbot"}
```

意图识别若返回 `business_type="visitor_appointment"`，就跳到 `visitor_appointment_chatbot`，用的是访客工具 + 访客提示词；返回 `meeting_room` 则走会议室那一套。**（可选）** `use_all_messages=False` 时，两个业务的对话历史还会按 `agent_name` 自动隔离。

### 5.7 为什么「只有一个业务」也必须输出 business_type

因为 `_route_from_intent_node_` 是**无条件**使用 `business_type` 的：

```python
business_type = state.get("business_type")
chatbot_name = self._agent_node_map.get(business_type, f"{business_type}_chatbot")
```

即使只有一个 Agent，LLM 也必须返回非空的、等于那个唯一 `business_type` 的值，否则 `_agent_node_map.get("")` 落空 → 返回兜底名 `"_chatbot"` → 该节点不存在 → 报错。

所以单业务场景下，提示词里仍然要**加 `business_type` 输出字段并枚举这唯一取值**。

### 5.8 出错排查表

| 现象 | 根因 | 定位 |
|------|------|------|
| 图运行报错，提示找不到节点 / `KeyError` / Invalid update | 提示词没让 LLM 输出 `business_type` → 解析得到 `""` → 路由到不存在的 `"_chatbot"` | 检查 `prompt_intent_analysis` 是否有 `business_type` 输出字段 |
| LLM 编造了一个不存在的 `business_type` | 提示词未**枚举合法取值** | 改为从 `self.business_agents` 动态拼接 |
| 路由到了错误业务的 Agent | 提示词枚举清单与 `BusinessAgentInfo` 不同步 | 同上，消除手写清单 |
| 明明只有一个业务还是报错 | 误以为单业务可以不输出 `business_type` | 见 5.7 |
| 偶发匹配不上 | LLM 返回了 `Meeting_Room` / 带空格 | 提示词中写清取值范围与格式；必要时在解析处 normalize |

> 注意 `_agent_node_map.get(business_type, f"{business_type}_chatbot")` 的**兜底分支**：它并不会救场，只会把「值不合法」这个根因，延后成「节点不存在」的报错，排查时容易看偏方向。

### 5.9 与 `interrupt_bisiness_type` 的区别（同名不同物）

| 名称 | 所属 | 作用 | 出现位置 |
|------|------|------|----------|
| `business_type` | 新版 `AbstractTool` 路由 | 决定跳转到哪个业务 Agent 子循环 | `BusinessAgentInfo` / `State` / 意图识别 JSON |
| `interrupt_bisiness_type` | HITL 中断协议 | 标记「这条中断/恢复属于哪项业务」，供前端与 resume 配对 | `InterruptMessage` / `ResumeMessage` |

两者名字相近但**毫无关系**，排查时别混。

### 5.10 落地自检清单

- [ ] 每个 `BusinessAgentInfo` 都填了 `business_type`，且节点内唯一
- [ ] `business_type` 与 `prompt_intent_analysis` 里的合法值清单**完全一致**（大小写、空格、下划线）
- [ ] 提示词的 JSON 输出模板里**包含** `business_type` 字段
- [ ] 合法值清单由 `self.business_agents` **动态生成**，而非手写
- [ ] 即使是单业务节点，也返回了非空的 `business_type`
- [ ] 命名可直接作为 LangGraph 节点名（英文小写 + 下划线，不以 `__` 开头）

---

## 六、从旧版迁移

完整实例参考旧版子类 `app/tool/xb_bangong/tool_book_meeting_room.py`（含 `@tool` + `ToolRuntime` + `interrupt` 全套用法），迁移后的新版写法见本文第三节。迁移要点：

1. import 从 `..abstract_tool` 改为 `..abstract_tool_lang_graph`；
2. `_initialize_tool` 返回值从设置 `self.tool` / `self.prompt_tool_call` 改为返回 `List[BusinessAgentInfo]`（每项都要有 `business_type`）；
3. `__init__` 中如需配置 `use_all_messages` / `use_paraller`，在调用 `super().__init__(node_id=...)` 之后设置；
4. **`prompt_intent_analysis` 提示词需补充 `business_type` 输出字段并枚举合法取值**（见 3.4 节与第五节），否则新版路由查不到映射；
5. 工具定义（`@tool`、`ToolRuntime` 注入、`interrupt`）无需改动。

> **迁移前必读的实际情况**：当前仓库中 `init_data.sql` 的 `tool_meeting_room.prompt_intent_analysis`（id=7）**只约束输出 `intent_type` / `friendly_response`，完全没有 `business_type`**，且 `ToolBookMeetingRoom._build_intent_analysis_prompt` 也未注入 `{business_scope}`。如果只把 import 换成新版基类而不同步改这两处，运行时会得到 `business_type=""`，路由到不存在的 `"_chatbot"` 节点并报错。也就是说 **第 4 点是必改项，不是可选项**。