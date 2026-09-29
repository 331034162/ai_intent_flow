# AI Frame 开发手册

> 本手册面向开发人员，介绍如何基于 ai_frame 框架开发智能对话系统。

---

## 一、概念介绍

### 1.1 Intent（意图识别）

**Intent** 是意图识别模块，位于对话流程的最顶层，负责识别用户的问题属于哪个智能体的处理范围。

- **职责**：识别用户想办理的业务类型，不处理具体业务
- **位置**：对话流程入口，作为路由分发器
- **特点**：
  - 不执行具体业务逻辑
  - 只进行意图分类，将用户引导到对应的 Agent
  - 通常作为工作流的入口节点（entry_node）

**示例场景**：
```
用户输入："我想预订会议室"
Intent 识别 → 属于"办公业务" → 分发到 AgentBanGong
```

### 1.2 Agent（智能体）

**Agent** 是业务领域代理，本质上也进行意图识别，用于识别用户的问题属于哪个工具的处理范围。

- **职责**：作为某个业务领域的代理，管理该领域下的工具
- **位置**：Intent 和 Tool 之间的中间层
- **特点**：
  - 进行二级意图识别
  - 每个智能体负责一个业务领域（如办公、研发、销售等）
  - 将用户请求分发给具体的工具执行

**示例场景**：
```
AgentBanGong（办公助手）管理以下工具：
- tool_meeting_room（会议室预订）
- tool_schedule（日程管理）
- tool_approval（审批流程）
```

### 1.3 Tool（工具/技能）

**Tool** 是实际处理用户问题的智能模块，执行具体的业务逻辑。

- **职责**：处理用户的具体业务需求，与用户进行多轮对话
- **位置**：对话流程的最底层，实际执行层
- **特点**：
  - 支持工具调用（Function Calling）
  - 支持话题切换检测
  - 支持友好回应生成
  - 保存对话记录到数据库

**示例场景**：
```
ToolBookMeetingRoom（会议室助手）：
- 查询可用会议室
- 预订会议室
- 取消预订
```

---

## 二、Intent、Agent、Tool 的关系

### 2.1 层级结构

```
                    ┌─────────────────┐
                    │     Intent      │  入口意图识别
                    │ (IntentClassifier)│
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
              ▼              ▼              ▼
       ┌──────────┐   ┌──────────┐   ┌──────────┐
       │  Agent   │   │  Agent   │   │  Agent   │
       │ (办公)   │   │ (研发)   │   │ (销售)   │
       └────┬─────┘   └────┬─────┘   └────┬─────┘
            │              │              │
       ┌────┴────┐    ┌────┴────┐    ┌────┴────┐
       │         │    │         │    │         │
       ▼         ▼    ▼         ▼    ▼         ▼
    ┌─────┐  ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐
    │Tool │  │Tool │ │Tool │ │Tool │ │Tool │ │Tool │
    └─────┘  └─────┘ └─────┘ └─────┘ └─────┘ └─────┘
```

### 2.2 调用流程

```
用户输入
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│  1. Intent 层                                            │
│     - 识别业务类型（办公/研发/销售...）                    │
│     - 分发到对应 Agent                                    │
└─────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│  2. Agent 层                                             │
│     - 识别具体业务场景（会议室预订/API文档生成...）        │
│     - 分发到对应 Tool                                     │
└─────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│  3. Tool 层                                              │
│     - 检测话题范围（继续业务/切换话题/友好回应/结束）       │
│     - 执行具体业务逻辑                                     │
│     - 调用工具函数                                         │
│     - 生成回复并保存对话记录                               │
└─────────────────────────────────────────────────────────┘
    │
    ▼
用户输出（流式）
```

### 2.3 继承关系

所有类都继承自 `AbstractAI` 基类：

```python
AbstractAI (abstract_ai.py)
    │
    ├── AbstractIntent (abstract_intent.py)
    │       └── IntentClassifier (intent_classifier.py)
    │
    ├── AbstractAgent (abstract_agent.py)
    │       ├── AgentBanGong (agent_bangong.py)
    │       └── AgentYanFa (agent_yanfa.py)
    │
    └── AbstractTool (abstract_tool.py)
            ├── ToolBookMeetingRoom (tool_book_meeting_room.py)
            ├── ToolGenApiDoc (tool_gen_api_doc.py)
            └── ToolResearchDev (tool_research_dev.py)
```

### 2.4 层级关系在数据库中的体现

层级关系通过 `zb_conversation_nodes` 表的 `parent_node_id` 字段建立：

```
zb_conversation_nodes 表结构（关键字段）：
┌─────────────────┬──────────────────────────────────────────────────┐
│ 字段            │ 说明                                              │
├─────────────────┼──────────────────────────────────────────────────┤
│ node_id         │ 节点唯一标识                                      │
│ node_type       │ 节点类型：intent / agent / tool                   │
│ parent_node_id  │ 父节点ID，用于建立层级关系                        │
│ node_func_path  │ 实现类的完整路径                                  │
│ model_id        │ 关联的模型ID                                      │
└─────────────────┴──────────────────────────────────────────────────┘
```

**层级关系示例**（基于实际数据）：

```
node_id              node_type   parent_node_id        层级
─────────────────────────────────────────────────────────────
intent_classification  intent      NULL                 第1层（顶层）
  └─ agent_bangong     agent       intent_classification 第2层
       └─ tool_meeting_room  tool  agent_bangong         第3层
  └─ agent_yanfa       agent       intent_classification 第2层
       └─ tool_research_dev   tool agent_yanfa           第3层
       └─ tool_gen_api_doc    tool agent_yanfa           第3层
```

**数据库配置示例**：

```sql
-- Intent 层（parent_node_id 为 NULL，表示顶层）
INSERT INTO zb_conversation_nodes 
(node_id, node_name, node_type, parent_node_id, ...)
VALUES 
('intent_classification', '小邦全能助手', 'intent', NULL, ...);

-- Agent 层（parent_node_id 指向 Intent）
INSERT INTO zb_conversation_nodes 
(node_id, node_name, node_type, parent_node_id, ...)
VALUES 
('agent_bangong', '小邦办公助手', 'agent', 'intent_classification', ...),
('agent_yanfa', '小邦研发助手', 'agent', 'intent_classification', ...);

-- Tool 层（parent_node_id 指向 Agent）
INSERT INTO zb_conversation_nodes 
(node_id, node_name, node_type, parent_node_id, ...)
VALUES 
('tool_meeting_room', '小邦会议室助手', 'tool', 'agent_bangong', ...),
('tool_research_dev', '小邦计算助手', 'tool', 'agent_yanfa', ...);
```

### 2.5 节点作为 Workflow 入口

**重要特性**：Intent、Agent、Tool 都可以作为 Workflow 的入口节点（entry_node），每个节点都可以独立运行作为一个完整的 Workflow。

```
zb_ai_workflow 表配置示例：

┌──────────────────────────┬─────────────────────┬────────────────────┐
│ workflow_id              │ entry_node_id       │ 说明               │
├──────────────────────────┼─────────────────────┼────────────────────┤
│ xiaobang_all             │ intent_classification│ Intent 作为入口   │
│ xiaobang_bangong         │ agent_bangong       │ Agent 作为入口     │
│ xiaobang_book_meeting    │ tool_meeting_room   │ Tool 作为入口      │
└──────────────────────────┴─────────────────────┴────────────────────┘
```

**三种入口场景说明**：

| 入口类型 | workflow_id | entry_node_id | 使用场景 |
|---------|-------------|---------------|---------|
| **Intent 入口** | xiaobang_all | intent_classification | 完整流程，从顶层意图识别开始，逐级分发 |
| **Agent 入口** | xiaobang_bangong | agent_bangong | 跳过顶层意图识别，直接进入某个业务领域 |
| **Tool 入口** | xiaobang_book_meeting | tool_meeting_room | 直接使用特定工具，无需意图识别 |

**Workflow 配置代码**：

```sql
-- 1. Intent 作为入口（完整流程）
INSERT INTO zb_ai_workflow 
(workflow_id, workflow_desc, entry_node_id, app_id, intent_classify_node_id)
VALUES 
('xiaobang_all', '小邦全能助手', 'intent_classification', 'xiaobang', 'intent_classification');

-- 2. Agent 作为入口（办公业务专用）
INSERT INTO zb_ai_workflow 
(workflow_id, workflow_desc, entry_node_id, app_id, intent_classify_node_id)
VALUES 
('xiaobang_bangong', '小邦办公助手', 'agent_bangong', 'xiaobang', 'agent_bangong');

-- 3. Tool 作为入口（会议室专用）
INSERT INTO zb_ai_workflow 
(workflow_id, workflow_desc, entry_node_id, app_id, intent_classify_node_id)
VALUES 
('xiaobang_book_meeting_room', '小邦会议室管理员', 'tool_meeting_room', 'xiaobang', 'tool_meeting_room');
```

**执行流程对比**：

```
场景1：Intent 作为入口（xiaobang_all）
用户输入 → Intent(识别业务类型) → Agent(识别具体工具) → Tool(执行业务)

场景2：Agent 作为入口（xiaobang_bangong）
用户输入 → Agent(识别具体工具) → Tool(执行业务)

场景3：Tool 作为入口（xiaobang_book_meeting）
用户输入 → Tool(直接执行业务)
```

**设计意义**：
- **灵活性**：可以根据业务需求选择不同粒度的入口
- **性能优化**：已知业务类型时可跳过上级意图识别
- **复用性**：同一个节点可以被多个 Workflow 使用
- **隔离性**：不同入口的 Workflow 可以独立部署和扩展

---

## 三、如何开发一个 Intent

### 3.1 创建 Intent 类

在 `app/ai_frame/intent/` 目录下创建新的意图分类器：

```python
# app/ai_frame/intent/intent_classifier.py

from app.ai_frame.intent.abstract_intent import AbstractIntent
from app.ai_frame.db_connection_pool.zb_conversation_nodes_util import _default_cache as node_cache

class IntentClassifier(AbstractIntent):
    """入口意图分类器"""
    
    def __init__(self):
        super().__init__(node_id="intent_classification")
    
    async def _prepare_descriptions(self):
        """准备功能描述数据"""
        # 获取所有子节点（Agent列表）
        self.tool_list = await node_cache.get_node_list(
            self.node_id, 
            "agent", 
            is_recursive=False
        )
        # 构建功能描述字符串
        self.func_desc_str = "\n".join([
            f"{node.node_id}:{node.node_description}" 
            for node in self.tool_list
        ])
    
    def _get_prompt_classification(self) -> str:
        """获取意图分类提示词"""
        return f"""你是一个意图分类器，负责识别用户的业务意图。

可用的智能体列表：
{self.func_desc_str}

请分析用户输入，返回JSON格式：
{{
    "intent": "智能体node_id",
    "confidence": 0.95
}}"""
```

### 3.2 必须实现的方法

| 方法 | 说明 |
|------|------|
| `__init__()` | 调用 `super().__init__(node_id="xxx")` |
| `_prepare_descriptions()` | 准备功能描述等异步数据 |
| `_get_prompt_classification()` | 返回意图分类的提示词 |

### 3.3 数据库配置

> **重要**：Intent 开发完成后，**必须**在 `zb_conversation_nodes` 表中配置节点信息，否则框架无法识别和加载该 Intent。

**配置示例**：

```sql
INSERT INTO zb_conversation_nodes 
(node_id, node_name, node_type, node_description, node_func_path, node_business_range, parent_node_id, model_id)
VALUES 
('intent_classification', '小邦全能助手', 'intent', '识别业务属于哪个智能体', 
 'app.ai_frame.intent.intent_classifier.IntentClassifier', '全部业务', NULL, 'deepseek_chat');
```

**字段说明**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `node_id` | varchar(64) | **是** | 节点唯一标识，需与代码中 `__init__` 传入的 `node_id` 一致 |
| `node_name` | varchar(128) | **是** | 节点名称，用于展示和日志 |
| `node_type` | varchar(64) | **是** | 节点类型，Intent 固定填 `intent` |
| `node_description` | varchar(512) | **是** | 节点描述，**会加入意图识别提示词，务必准确描述功能** |
| `node_func_path` | varchar(256) | **是** | 实现类的完整路径，格式：`模块路径.类名` |
| `node_business_range` | varchar(128) | **是** | 业务范围描述，**会加入意图识别提示词，用于分类说明，务必准确** |
| `parent_node_id` | varchar(64) | 否 | 父节点ID，Intent 层通常为 `NULL`（顶层）；也可以不指定，不指定则代表自己是顶层节点 |
| `model_id` | varchar(64) | **是** | 关联的模型ID，引用 `zb_node_model` 表 |
| `model_ext_param` | json | 否 | 模型扩展参数，如：`{"temperature": 0.7, "max_tokens": 4096}` |
| `status` | tinyint | 否 | 节点状态：1-启用（默认），0-禁用 |

**注意事项**：
- `node_id` 必须与代码中 `super().__init__(node_id="xxx")` 传入的值完全一致
- `node_description` 会直接用于构建意图识别的提示词，描述不准确会导致意图识别效果差
- Intent 作为顶层节点，`parent_node_id` 通常为 `NULL`

---

## 四、如何开发一个 Agent

### 4.1 创建 Agent 类

在 `app/ai_frame/agent/` 目录下创建新的智能体：

```python
# app/ai_frame/agent/agent_bangong.py

from app.ai_frame.agent.abstract_agent import AbstractAgent
from app.ai_frame.db_connection_pool.zb_conversation_nodes_util import _default_cache as node_cache

class AgentBanGong(AbstractAgent):
    """办公助手智能体"""
    
    def __init__(self):
        super().__init__(node_id="agent_bangong")
    
    async def _prepare_descriptions(self):
        """准备工具描述数据"""
        # 获取该智能体下的所有工具
        self.tool_list = await node_cache.get_node_list(
            self.node_id, 
            "tool", 
            is_recursive=False
        )
        # 构建工具描述字符串
        self.func_desc_str = "\n".join([
            f"{node.node_id}:{node.node_description}" 
            for node in self.tool_list
        ])
    
    def _get_prompt_classification(self) -> str:
        """获取意图分类提示词"""
        return f"""你是办公助手，负责识别用户的具体需求。

可用的工具列表：
{self.func_desc_str}

请分析用户输入，返回JSON格式：
{{
    "intent": "工具node_id",
    "confidence": 0.95
}}"""
```

### 4.2 必须实现的方法

| 方法 | 说明 |
|------|------|
| `__init__()` | 调用 `super().__init__(node_id="xxx")` |
| `_prepare_descriptions()` | 获取该 Agent 管理的工具列表 |
| `_get_prompt_classification()` | 返回意图分类的提示词 |

### 4.3 数据库配置

> **重要**：Agent 开发完成后，**必须**在 `zb_conversation_nodes` 表中配置节点信息（包括设置 `parent_node_id`），否则框架无法识别和加载该 Agent。

**配置示例**：

```sql
INSERT INTO zb_conversation_nodes 
(node_id, node_name, node_type, node_description, node_func_path, node_business_range, parent_node_id, model_id)
VALUES 
('agent_bangong', '小邦办公助手', 'agent', '办公类业务意图识别智能体', 
 'app.ai_frame.agent.agent_bangong.AgentBanGong', '办公类业务', 'intent_classification', 'deepseek_chat');
```

**字段说明**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `node_id` | varchar(64) | **是** | 节点唯一标识，需与代码中 `__init__` 传入的 `node_id` 一致 |
| `node_name` | varchar(128) | **是** | 节点名称，用于展示和日志 |
| `node_type` | varchar(64) | **是** | 节点类型，Agent 固定填 `agent` |
| `node_description` | varchar(512) | **是** | 节点描述，**会加入意图识别提示词，务必准确描述功能** |
| `node_func_path` | varchar(256) | **是** | 实现类的完整路径，格式：`模块路径.类名` |
| `node_business_range` | varchar(128) | **是** | 业务范围描述，**会加入意图识别提示词，用于分类说明，务必准确** |
| `parent_node_id` | varchar(64) | **是** | 父节点ID，**必须指向所属的 Intent 节点**；也可以不指定，不指定则代表自己是顶层节点 |
| `model_id` | varchar(64) | **是** | 关联的模型ID，引用 `zb_node_model` 表 |
| `model_ext_param` | json | 否 | 模型扩展参数，如：`{"temperature": 0.7, "max_tokens": 8192}` |
| `status` | tinyint | 否 | 节点状态：1-启用（默认），0-禁用 |

**注意事项**：
- `node_id` 必须与代码中 `super().__init__(node_id="xxx")` 传入的值完全一致
- `parent_node_id` **必须正确指向父节点**，否则框架无法建立层级关系
- `node_description` 会直接用于构建意图识别的提示词，描述不准确会导致意图识别效果差

---

## 五、如何开发一个 Tool

### 5.1 创建 Tool 类

在 `app/ai_frame/tool/` 目录下创建新的工具：

```python
# app/ai_frame/tool/tool_book_meeting_room.py

from app.ai_frame.tool.abstract_tool import AbstractTool
from langchain_core.tools import tool

class ToolBookMeetingRoom(AbstractTool):
    """会议室预订工具"""
    
    def __init__(self):
        super().__init__(node_id="tool_meeting_room")
    
    async def _initialize_tool(self) -> None:
        """初始化工具"""
        # 设置提示词
        self.prompt_tool_call = """你是会议室预订助手，帮助用户查询和预订会议室。

你可以使用以下工具：
- get_available_meeting_room: 查询可用会议室
- book_meeting_room: 预订会议室

请根据用户需求，调用相应工具完成操作。"""
        
        # 定义工具函数
        self.tool = [self._get_available_meeting_room, self._book_meeting_room]
    
    def _build_intent_analysis_prompt(self) -> str:
        """构建意图分析提示词（话题切换检测）"""
        return """分析用户意图，判断用户是否想切换话题或继续当前业务。

返回JSON格式：
{
    "intent_type": "continue_business|change_topic|friendly_response|end_business",
    "friendly_response": "如果是切换话题，给出友好的过渡回复"
}"""
    
    # 定义工具函数（使用 @tool 装饰器）
    @tool
    def _get_available_meeting_room(date: str, time_slot: str) -> str:
        """查询可用会议室
        
        Args:
            date: 日期，格式如 2026-03-26
            time_slot: 时间段，格式如 09:00-10:00
        
        Returns:
            可用会议室列表
        """
        # 实现查询逻辑
        return "会议室A、会议室B、会议室C 当前可用"
    
    @tool
    def _book_meeting_room(room_name: str, date: str, time_slot: str) -> str:
        """预订会议室
        
        Args:
            room_name: 会议室名称
            date: 日期
            time_slot: 时间段
        
        Returns:
            预订结果
        """
        # 实现预订逻辑
        return f"已成功预订 {room_name}，时间：{date} {time_slot}"
```

### 5.2 必须实现的方法

| 方法 | 说明 |
|------|------|
| `__init__()` | 调用 `super().__init__(node_id="xxx")` |
| `_initialize_tool()` | 设置 `prompt_tool_call` 和 `tool` 列表 |
| `_build_intent_analysis_prompt()` | 返回话题切换检测的提示词 |

### 5.3 Tool 的四种意图类型

Tool 层会检测用户的四种意图：

| 意图类型 | 常量 | 说明 | 处理方式 |
|----------|------|------|----------|
| 继续办理业务 | `INTENT_CONTINUE_BUSINESS` | 用户继续当前业务 | 调用 LLM + 工具处理 |
| 友好回应 | `INTENT_FRIENDLY_RESPONSE` | 用户进行寒暄、礼貌用语 | 生成友好回应 |
| 切换话题 | `INTENT_CHANGE_TOPIC` | 用户想切换到其他业务 | 保存记录，跳转到 Intent |
| 结束业务 | `INTENT_END_BUSINESS` | 用户想结束对话 | 生成结束回应 |

### 5.4 数据库配置

> **重要**：Tool 开发完成后，**必须**在 `zb_conversation_nodes` 表中配置节点信息（包括设置 `parent_node_id`），否则框架无法识别和加载该 Tool。

**配置示例**：

```sql
INSERT INTO zb_conversation_nodes 
(node_id, node_name, node_type, node_description, node_func_path, node_business_range, parent_node_id, model_id, model_ext_param)
VALUES 
('tool_meeting_room', '小邦会议室助手', 'tool', 
 '会议室预定/查询 - 查询会议室使用情况、预定会议室', 
 'app.ai_frame.tool.tool_book_meeting_room.ToolBookMeetingRoom', 
 '会议室类业务', 'agent_bangong', 'deepseek_chat', 
 '{"temperature": 0.7, "max_tokens": 8192}');
```

**字段说明**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `node_id` | varchar(64) | **是** | 节点唯一标识，需与代码中 `__init__` 传入的 `node_id` 一致 |
| `node_name` | varchar(128) | **是** | 节点名称，用于展示和日志 |
| `node_type` | varchar(64) | **是** | 节点类型，Tool 固定填 `tool` |
| `node_description` | varchar(512) | **是** | 节点描述，**会加入意图识别提示词，务必准确描述功能** |
| `node_func_path` | varchar(256) | **是** | 实现类的完整路径，格式：`模块路径.类名` |
| `node_business_range` | varchar(128) | **是** | 业务范围描述，**会加入意图识别提示词，用于分类说明，务必准确** |
| `parent_node_id` | varchar(64) | **是** | 父节点ID，**必须指向所属的 Agent 节点**；也可以不指定，不指定则代表自己是顶层节点 |
| `model_id` | varchar(64) | **是** | 关联的模型ID，引用 `zb_node_model` 表 |
| `model_ext_param` | json | 否 | 模型扩展参数，如：`{"temperature": 0.7, "max_tokens": 8192}` |
| `status` | tinyint | 否 | 节点状态：1-启用（默认），0-禁用 |

**注意事项**：
- `node_id` 必须与代码中 `super().__init__(node_id="xxx")` 传入的值完全一致
- `parent_node_id` **必须正确指向所属 Agent**，否则框架无法建立层级关系
- `node_description` 会直接用于构建意图识别的提示词，描述不准确会导致意图识别效果差
- Tool 可以配置 `model_ext_param` 来覆盖模型的默认参数

---

## 六、如何配置一个 Workflow

### 6.1 Workflow 配置表结构

Workflow 在 `zb_ai_workflow` 表中配置：

```sql
CREATE TABLE `zb_ai_workflow` (
  `workflow_id` varchar(64) NOT NULL COMMENT '工作流ID',
  `workflow_desc` varchar(256) DEFAULT NULL COMMENT '工作流描述',
  `entry_node_id` varchar(64) NOT NULL COMMENT '入口节点',
  `app_id` varchar(64) NOT NULL COMMENT '应用ID',
  `intent_classify_node_id` varchar(64) DEFAULT NULL COMMENT '意图识别节点',
  `status` tinyint DEFAULT '1' COMMENT '状态：0-不可用，1-可用',
  `enhance_intent_classify` TINYINT DEFAULT '0' COMMENT '是否开启增强意图识别',
  PRIMARY KEY (`id`),
  UNIQUE KEY `idx_workflow_id` (`workflow_id`)
);
```

### 6.2 配置示例

```sql
-- 配置一个完整的工作流
INSERT INTO zb_ai_workflow 
(workflow_id, workflow_desc, entry_node_id, app_id, intent_classify_node_id, enhance_intent_classify)
VALUES 
('xiaobang_all', '小邦全能助手', 'intent_classification', 'xiaobang', 'intent_classification', 1);
```

**字段说明**：

| 字段 | 说明 |
|------|------|
| `workflow_id` | 工作流唯一标识 |
| `entry_node_id` | 入口节点，通常是 Intent 节点 |
| `intent_classify_node_id` | 意图识别节点，用于话题切换时的重定向 |
| `enhance_intent_classify` | 开启后，每个节点只查询与自己相关的历史消息 |

### 6.3 节点层级配置

完整的工作流需要配置所有节点及其父子关系：

```sql
-- 1. Intent 层
INSERT INTO zb_conversation_nodes VALUES
('intent_classification', '小邦全能助手', 'intent', ..., NULL, ...);

-- 2. Agent 层（parent_node_id 指向 Intent）
INSERT INTO zb_conversation_nodes VALUES
('agent_bangong', '小邦办公助手', 'agent', ..., 'intent_classification', ...);

-- 3. Tool 层（parent_node_id 指向 Agent）
INSERT INTO zb_conversation_nodes VALUES
('tool_meeting_room', '小邦会议室助手', 'tool', ..., 'agent_bangong', ...);
```

### 6.4 工作流执行流程

```python
# 1. 获取工作流配置
workflow = await ZbAiWorkflowUtil.load_workflow_by_id("xiaobang_all")

# 2. 获取入口节点
entry_node_id = workflow.entry_node_id  # "intent_classification"

# 3. 实例化入口节点
intent_node = await node_cache.instantiate_node(entry_node_id)

# 4. 处理用户输入
async for response in intent_node.process_user_input(user_input, context):
    yield response
```

---

## 七、架构设计要点

### 7.1 异步初始化

所有节点类都采用**延迟初始化**模式，确保线程安全：

```python
async def _ensure_initialized(self, context: ChatContext = None) -> None:
    # 双重检查锁定模式
    if self._initialized:
        return
    
    async with self._init_lock:
        if self._initialized:
            return
        
        # 执行初始化
        self.node = await node_cache.get_node_by_id(self.node_id)
        self.llm = await node_cache.get_llm_by_node_id(self.node_id)
        # ...
        
        self._initialized = True
```

**注意**：不要在 `__init__` 中执行异步操作！

### 7.2 流式输出

所有 `process_user_input()` 方法返回 `AsyncGenerator`：

```python
async def process_user_input(
    self, 
    user_input: str, 
    context: ChatContext
) -> AsyncGenerator[Dict[str, Any], None]:
    # 使用 yield 返回流式消息
    yield self.create_stream_message(
        content="回复内容",
        message_type="model",  # 或 "tool"
        is_last=False,
        conversation_id=context.conversation_id
    )
```

### 7.3 消息格式

统一使用 `create_stream_message()` 创建消息：

```python
{
    "message_type": "model",  # "model" 或 "tool"
    "content": "消息内容",
    "is_last": False,  # 是否是流式输出的最后一个字符
    "is_over": False,  # 整个业务逻辑是否结束
    "conversation_id": "xxx"
}
```

### 7.4 数据库字段说明

**zb_conversation_nodes 表关键字段**：

| 字段 | 说明 | 重要性 |
|------|------|--------|
| `node_id` | 节点唯一标识 | 必填 |
| `node_type` | 节点类型：intent/agent/tool | 必填 |
| `node_description` | 节点描述（会加入意图识别提示词） | 必填，需准确 |
| `node_func_path` | 实现类的完整路径 | 必填 |
| `node_business_range` | 业务范围描述 | 必填 |
| `parent_node_id` | 父节点ID | Agent/Tool 必填 |
| `model_id` | 关联的模型ID | 必填 |
| `model_ext_param` | 模型扩展参数（JSON） | 可选 |

### 7.5 节点缓存

框架使用 `ZbConversationNodeCache` 缓存节点配置，默认 60 秒刷新：

```python
from app.ai_frame.db_connection_pool.zb_conversation_nodes_util import _default_cache as node_cache

# 获取节点
node = await node_cache.get_node_by_id("tool_meeting_room")

# 获取 LLM 实例
llm = await node_cache.get_llm_by_node_id("tool_meeting_room")

# 实例化节点
instance = await node_cache.instantiate_node("tool_meeting_room")
```

### 7.6 对话历史查询

开启 `enhance_intent_classify` 后，每个节点只查询与自己相关的历史消息：

```python
# 在 ChatContext 中设置
context.is_query_history_node_id = True  # 是否按 node_id 过滤历史
context.history_max_records = 10  # 最大历史记录数
```

### 7.7 工具函数定义规范

使用 `@tool` 装饰器定义工具函数：

```python
from langchain_core.tools import tool

@tool
def my_tool(param1: str, param2: int) -> str:
    """工具函数描述（会传递给 LLM）
    
    Args:
        param1: 参数1说明
        param2: 参数2说明
    
    Returns:
        返回值说明
    """
    # 实现逻辑
    return "结果"
```

**注意**：函数的 docstring 会作为工具描述传递给 LLM，请务必准确编写！

### 7.8 错误处理

所有层级的 `process_user_input()` 都应该有异常处理：

```python
try:
    # 业务逻辑
    async for chunk in self._stream_process_user_input(...):
        yield chunk
except Exception as e:
    app_logger.error(f"处理出错: {str(e)}")
    yield self.create_stream_message("抱歉，处理过程中出现错误", message_type="model")
finally:
    yield self.create_stream_message("", is_last=True, is_over=True)
```

---

## 附录：快速开发清单

### 新建 Intent 清单

- [ ] 创建类文件 `app/ai_frame/intent/xxx_intent.py`
- [ ] 继承 `AbstractIntent`
- [ ] 实现 `_prepare_descriptions()`
- [ ] 实现 `_get_prompt_classification()`
- [ ] 在数据库添加节点配置

### 新建 Agent 清单

- [ ] 创建类文件 `app/ai_frame/agent/xxx_agent.py`
- [ ] 继承 `AbstractAgent`
- [ ] 实现 `_prepare_descriptions()`
- [ ] 实现 `_get_prompt_classification()`
- [ ] 在数据库添加节点配置（设置 parent_node_id）

### 新建 Tool 清单

- [ ] 创建类文件 `app/ai_frame/tool/xxx_tool.py`
- [ ] 继承 `AbstractTool`
- [ ] 实现 `_initialize_tool()`（设置 prompt_tool_call 和 tool）
- [ ] 实现 `_build_intent_analysis_prompt()`
- [ ] 定义工具函数（使用 @tool 装饰器）
- [ ] 在数据库添加节点配置（设置 parent_node_id）

---

> 文档版本：v1.0  
> 更新时间：2026-03-26
