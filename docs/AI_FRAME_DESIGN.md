# AI Frame 架构设计文档

## 一、模块概述

`ai_frame` 是一个基于 LangChain 构建的企业级 AI 对话框架，采用**分层架构**设计，实现了从意图识别、智能体分发到工具执行的完整对话流程管理。

### 核心设计目标

1. **模块化设计**：通过抽象基类定义统一接口，支持灵活扩展
2. **异步并发**：全面支持异步操作，高并发场景下表现优异
3. **流式输出**：所有对话响应支持流式传输，提升用户体验
4. **动态配置**：通过数据库配置节点、模型、工作流，实现运行时动态加载

---

## 二、目录结构与文件组织

```
ai_frame/
├── __init__.py                    # 模块初始化
├── abstract_ai.py                 # 抽象AI基类 (顶层抽象)
├── context/
│   └── chat_context.py            # 对话上下文数据类
├── db_connection_pool/            # 数据库连接层
│   ├── async_mysql_connection.py  # 异步MySQL连接池(单例)
│   ├── conversation_db_helper.py  # 对话记录保存助手
│   ├── zb_ai_workflow_util.py     # 工作流配置缓存
│   ├── zb_conversation_messages_util.py  # 消息历史查询
│   ├── zb_conversation_nodes_util.py     # 节点配置缓存+动态实例化
│   ├── zb_conversation_util.py    # 会话信息查询
│   └── zb_node_model_util.py      # 模型配置
├── db_scripts/
│   └── user_conversation_tables.sql # 数据库建表脚本
├── intent/                        # 意图识别层
│   ├── abstract_intent.py         # 抽象意图分类器基类
│   └── intent_classifier.py       # 具体意图分类器实现
├── agent/                         # 智能体层
│   ├── abstract_agent.py          # 抽象智能体基类
│   ├── agent_bangong.py           # 办公智能体
│   └── agent_yanfa.py             # 研发智能体
├── tool/                          # 工具执行层
│   ├── abstract_tool.py           # 抽象工具基类
│   ├── tool_book_meeting_room.py  # 会议室预订工具
│   ├── tool_research_dev.py       # 研发计算工具
│   ├── tool_gen_api_doc.py        # API文档生成工具
│   └── util/                      # 工具辅助类
│       ├── __init__.py            # 模块初始化
│       ├── tool_call_aware.py     # 工具调用中间件
│       └── tool_response_message.py # 响应消息封装
└── workflow/
    └── zb_xiaobang_workflow.py    # 工作流入口(对外API)
```

---

## 三、类继承关系图

```
                    ┌─────────────────┐
                    │   AbstractAI    │  ← 顶层抽象基类
                    │   (abstract_ai) │
                    └────────┬────────┘
                             │
         ┌───────────────────┼───────────────────┐
         │                   │                   │
         ▼                   ▼                   ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│ AbstractIntent  │ │ AbstractAgent   │ │ AbstractTool    │
│ (意图分类器)     │ │ (智能体)        │ │ (工具执行器)     │
└────────┬────────┘ └────────┬────────┘ └────────┬────────┘
         │                   │                   │
         ▼                   │                   │
┌─────────────────┐          │                   │
│IntentClassifier │          ├───────────────────┤
│(意图分类实现)    │          │                   │
└─────────────────┘          ▼                   ▼
                   ┌─────────────────┐ ┌─────────────────┐
                   │ AgentBanGong    │ │ToolBookMeeting  │
                   │ AgentYanFa      │ │ToolResearchDev  │
                   │ (具体智能体)     │ │ (具体工具)       │
                   └─────────────────┘ └─────────────────┘
```

---

## 四、各层职责详解

### 4.1 抽象层 (Abstract Layer)

#### AbstractAI - 顶层抽象基类

**文件**: `abstract_ai.py`

```python
class AbstractAI(ABC):
    """所有AI处理类的根抽象类"""
    
    # 核心抽象方法
    @abstractmethod
    def _get_prompt_friendly_response(self) -> str  # 获取友好回应提示词
    @abstractmethod
    async def _ensure_initialized(self, context)    # 异步初始化
    @abstractmethod
    async def process_user_input(user_input, context)  # 处理用户输入(流式)
    
    # 公共能力
    - log_token_usage()           # Token使用统计
    - get_chat_history_from_db()  # 从数据库获取聊天历史
    - generate_friendly_response_stream()  # 生成友好回应(流式)
    - create_stream_message()     # 创建流式消息字典
```

**设计亮点**：
- 采用异步工厂方法模式 `create()` 支持异步初始化
- 统一的流式消息格式 `{message_type, content, is_last, is_over, conversation_id}`

---

### 4.2 意图识别层 (Intent Layer)

#### AbstractIntent - 意图分类器基类

**文件**: `intent/abstract_intent.py`

```python
class AbstractIntent(AbstractAI):
    # 核心流程
    async def process_user_input(user_input, context):
        1. 执行步数检查 - 超过最大步数则跳过处理
        2. 获取聊天历史
        3. 调用 classify_intent() 进行意图识别
        4. 如果识别成功 → _dispatch_intent() 分发到Agent
        5. 如果识别失败 → generate_friendly_response_stream()

    async def classify_intent(user_input, chat_history, context):
        """使用LLM识别用户意图，返回JSON格式"""
        return {"intent": "agent_bangong", "confidence": 0.9}

    @abstractmethod
    async def _dispatch_intent(intent, user_input, context)  # 分发意图
```

#### IntentClassifier - 具体意图分类器

**文件**: `intent/intent_classifier.py`

```python
class IntentClassifier(AbstractIntent):
    node_id = "intent_classification"
    
    # 从数据库动态加载子节点描述
    async def _prepare_descriptions():
        self.children_list = await node_cache.get_children("intent_classification")
        # 构建意图描述字符串供LLM识别
```

---

### 4.3 智能体层 (Agent Layer)

#### AbstractAgent - 智能体基类

**文件**: `agent/abstract_agent.py`

```python
class AbstractAgent(AbstractAI):
    def __init__(self, node_id: str):
        self.node_id = node_id
        self.tool_list = []      # 子工具节点列表
        self.llm = None          # 大模型实例
        self._init_lock = asyncio.Lock()  # 并发初始化锁

    async def _ensure_initialized(context):
        """双重检查锁定模式，确保线程安全"""
        if self._initialized: return
        async with self._init_lock:
            if self._initialized: return
            # 加载节点配置、模型、子工具列表
            self.tool_list = await node_cache.get_node_list(parent_node_id=self.node_id)
            self.llm = await node_cache.get_llm_by_node_id(self.node_id)

    async def classify_intent(user_input, chat_history, context):
        """识别具体业务意图（工具级别）"""

    async def process_user_input(user_input, context):
        1. 执行步数检查 - 超过最大步数则跳过处理
        2. 意图识别 → 获取具体tool节点ID
        3. 如果识别成功 → 实例化Tool并执行
        4. 如果识别失败 → 生成友好回应
```

#### 具体智能体实现

| 类名 | 文件 | node_id | 子工具 |
|------|------|---------|--------|
| AgentBanGong | `agent_bangong.py` | `agent_bangong` | tool_meeting_room 等 |
| AgentYanFa | `agent_yanfa.py` | `agent_yanfa` | tool_research_dev 等 |

---

### 4.4 工具执行层 (Tool Layer)

#### AbstractTool - 工具基类

**文件**: `tool/abstract_tool.py`

```python
class AbstractTool(AbstractAI):
    # 意图类型常量
    INTENT_CONTINUE_BUSINESS = "continue_business"  # 继续办理业务
    INTENT_FRIENDLY_RESPONSE = "friendly_response"  # 友好回应
    INTENT_CHANGE_TOPIC = "change_topic"            # 切换话题
    INTENT_END_BUSINESS = "end_business"            # 结束业务

    async def process_user_input(user_input, context):
        1. 执行步数检查 - 超过最大步数则跳过处理
        2. is_in_topic_range() - 判断用户意图类型
        3. 根据意图类型路由：
           - CONTINUE_BUSINESS → _stream_process_user_input() 执行业务
           - FRIENDLY_RESPONSE → generate_friendly_response_stream()
           - CHANGE_TOPIC → 转发到意图分类器
           - END_BUSINESS → 结束对话

    async def _ensure_initialized(context):
        """初始化Agent（支持无工具模式）"""
        # 如果 tool 为空，创建不带工具的 agent，仅进行大模型对话
        self.agent = create_agent(
            model=self.llm,
            tools=self.tool if self.tool else [],  # 支持空工具列表
            system_prompt=self.prompt_tool_call,
            ...
        )

    async def is_in_topic_range(history_messages, current_question, context):
        """两级意图判断机制"""
        # 第一级：快速规则判断（无LLM调用）
        quick_result = self._is_in_topic_quick_check(current_question)
        if quick_result: return quick_result

        # 第二级：LLM深度分析
        return await self.llm.ainvoke(...)

    async def _stream_process_user_input(chat_history, user_input, context):
        """使用LangGraph Agent流式执行工具调用"""
        async for node, chunk in self.agent.astream(...):
            yield ToolResponseMessage(...)
```

**设计亮点**：
- **两级意图判断**：快速规则 + LLM深度分析，兼顾性能与准确性
- **关键词库设计**：寒暄词、礼貌词、结束词、确认词等分类管理
- **动态话题切换**：支持中途切换话题，无缝转接到其他智能体
- **无工具模式**：支持只调用大模型不调用工具，适用于纯对话场景
- **执行步数控制**：防止意图识别问题导致无限制循环执行

#### 具体工具实现示例

**文件**: `tool/tool_book_meeting_room.py`

```python
@tool(parse_docstring=True)
async def book_meeting_room(meeting_room_id: str, run_time: ToolRuntime[ChatContext]) -> str:
    """预订指定的会议室"""
    context = run_time.context
    return f"已成功预订会议室（ID: {meeting_room_id}）"

@tool(parse_docstring=True)
async def get_available_meeting_room(address: str, start_time: str, end_time: str, 
                                      run_time: ToolRuntime[ChatContext]) -> str:
    """查询可用会议室"""
    return json.dumps([...])

class ToolBookMeetingRoom(AbstractTool):
    node_id = "tool_meeting_room"
    
    async def _initialize_tool(self):
        self.tool = [get_available_meeting_room, book_meeting_room]
        self.prompt_tool_call = """你是专业的会议室管理员..."""
        # Agent由父类统一创建
```

#### 无工具模式（纯大模型对话）

适用于只需要大模型对话而不需要调用工具的场景：

```python
class ToolPureChat(AbstractTool):
    """纯对话工具 - 只调用大模型，不调用任何工具"""
    node_id = "tool_pure_chat"
    
    async def _initialize_tool(self):
        self.tool = []  # 空列表 = 无工具模式
        self.prompt_tool_call = """你是一个友好的AI助手..."""
        # 父类会创建不带工具的 Agent，仅进行大模型对话
```

---

### 4.5 工作流层 (Workflow Layer)

#### ZBXiaoBangWorkflow - 对外入口

**文件**: `workflow/zb_xiaobang_workflow.py`

```python
class ZBXiaoBangWorkflow:
    @staticmethod
    async def process_user_input(user_id, user_input, conversation_id, workflow_id, seq_no):
        """主入口方法"""
        1. 加载工作流配置
        2. 确定当前节点（新会话用entry_node，续传用conversation记录的node）
        3. 创建ChatContext上下文
        4. 调用节点的process_user_input()
    
    @staticmethod
    async def ai_brain_stream_endpoint(request: Request):
        """FastAPI流式接口，返回SSE格式响应"""
        return StreamingResponse(
            _event_generator(...),
            media_type="text/event-stream"
        )
```

**统一响应格式**：

```json
{
  "content": "消息内容",
  "status": "processing|done",
  "conversation_id": "会话ID",
  "content_type": "model|tool"
}
```

---

### 4.6 数据持久层 (Data Layer)

#### 异步连接池

**文件**: `db_connection_pool/async_mysql_connection.py`

```python
# 单例模式 + 异步锁保护
_global_db_instance = None
_init_lock = asyncio.Lock()

async def get_async_pool_instance():
    if _global_db_instance is None:
        async with _init_lock:
            if _global_db_instance is None:
                _global_db_instance = AsyncMySQLConnection(...)
                await _global_db_instance.init_pool(minsize=1, maxsize=100)
    return _global_db_instance
```

#### 节点缓存 (ZbConversationNodeCache)

**文件**: `db_connection_pool/zb_conversation_nodes_util.py`

```python
class ZbConversationNodeCache:
    """节点配置缓存（单例 + 懒加载 + 定时刷新）"""
    
    REFRESH_INTERVAL = 60  # 60秒刷新一次
    
    async def instantiate_node(node_id: str) -> AbstractAI:
        """动态实例化节点"""
        node = self._cache.node_map.get(node_id)
        module_path, class_name = node.node_func_path.rsplit('.', 1)
        module = importlib.import_module(module_path)
        cls = getattr(module, class_name)
        return cls()
    
    async def get_llm_by_node_id(node_id: str) -> ChatOpenAI:
        """获取节点关联的LLM实例"""
        node = self._cache.node_map.get(node_id)
        return node.llm  # LLM在加载时已初始化
```

#### 工作流缓存 (ZbAiWorkflowCache)

**文件**: `db_connection_pool/zb_ai_workflow_util.py`

```python
class ZbAiWorkflowCache:
    """工作流配置缓存"""
    REFRESH_INTERVAL = 5  # 5秒刷新
```

---

## 五、数据流向与处理流程

### 5.1 完整对话处理流程

```
┌──────────────────────────────────────────────────────────────────────┐
│                         用户请求入口                                   │
│                    ZBXiaoBangWorkflow.process_user_input()            │
└───────────────────────────────┬──────────────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│ 1. 加载工作流配置 (zb_ai_workflow_util)                                │
│    - entry_node_id: 入口节点                                          │
│    - intent_classify_node_id: 意图识别节点                            │
└───────────────────────────────┬──────────────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│ 2. 确定当前执行节点                                                    │
│    - 新会话: 使用 entry_node_id                                       │
│    - 续传: 从 zb_conversations 表读取 node_id                         │
└───────────────────────────────┬──────────────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│ 3. 动态实例化节点                                                      │
│    node_cache.instantiate_node(node_id)                               │
│    → 根据 node_func_path 动态导入模块并实例化                          │
└───────────────────────────────┬──────────────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│ 4. 执行节点处理 (node.process_user_input)                             │
│    每层都会检查执行步数 (run_steps > run_steps_max 则跳过)             │
│    ├─ IntentClassifier: 执行步数检查 → 意图识别 → 分发到Agent         │
│    ├─ Agent: 执行步数检查 → 业务意图识别 → 分发到Tool                 │
│    └─ Tool: 执行步数检查 → 意图类型判断 → 执行业务                    │
└───────────────────────────────┬──────────────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│ 5. 流式返回响应                                                        │
│    yield {message_type, content, is_last, is_over, conversation_id}  │
└───────────────────────────────┬──────────────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│ 6. 保存对话记录                                                        │
│    ConversationDBHelper.save_conversation_record()                    │
│    - zb_conversations: 更新会话信息                                    │
│    - zb_conversation_messages: 插入消息记录                           │
└──────────────────────────────────────────────────────────────────────┘
```

### 5.2 意图识别流程（Tool层）

```
用户输入 → process_user_input()
              │
              ▼
    ┌─────────────────────┐
    │ 0. 执行步数检查      │
    │ run_steps > max ?   │
    └─────────┬───────────┘
              │
    ┌─────────┴───────────┐
    │                     │
    ▼                     ▼
  超过限制            未超过限制
    │                     │
    │                     ▼
    │         ┌─────────────────────┐
    │         │ 1. 意图类型判断      │
    │         │ is_in_topic_range() │
    │         └─────────┬───────────┘
    │                   │
    │         ┌─────────┴───────────┐
    │         │                     │
    │         ▼                     ▼
    │     有结果                无结果
    │         │                     │
    │         │                     ▼
    │         │         ┌─────────────────────┐
    │         │         │ 2. LLM深度分析       │
    │         │         │ 构建prompt → 调用LLM │
    │         │         └─────────┬───────────┘
    │         │                   │
    │         └───────────────────┘
    │                   │
    │                   ▼
    │         ┌─────────────────────┐
    │         │ 根据意图类型路由:    │
    │         │ - CONTINUE → 执行业务│
    │         │ - FRIENDLY → 友好回应│
    │         │ - CHANGE → 切换话题 │
    │         │ - END → 结束对话    │
    │         └─────────────────────┘
    │
    ▼
返回提示消息并跳过处理
```

---

## 六、数据库设计

### 核心表结构

| 表名 | 用途 | 关键字段 |
|------|------|----------|
| `zb_conversation_nodes` | 节点配置 | node_id, node_type, node_func_path, node_business_range, parent_node_id, model_id, model_ext_param |
| `zb_node_model` | 模型配置 | model_id, model_provider, model_name, model_url, model_api_key, model_is_out, status |
| `zb_ai_workflow` | 工作流配置 | workflow_id, entry_node_id, intent_classify_node_id, status, enhance_intent_classify |
| `zb_conversations` | 会话记录 | conversation_id, conversation_name, employee_id, user_name, is_deleted, node_id |
| `zb_conversation_messages` | 消息记录 | conversation_id, question, answer, node_id, model_name, model_provider, model_url |

### 表字段详解

#### zb_conversation_nodes (对话流程节点表)

| 字段名 | 类型 | 说明 |
|--------|------|------|
| id | bigint | 主键ID，自增 |
| node_id | varchar(64) | 节点ID，唯一标识 |
| node_name | varchar(128) | 节点名称 |
| node_type | varchar(64) | 节点类型：intent/agent/tool |
| node_description | varchar(512) | 节点描述，用于意图识别提示词 |
| node_func_path | varchar(256) | 节点实现类的完整路径 |
| node_business_range | varchar(128) | 节点处理的业务范围（如：办公类业务、研发类业务） |
| status | tinyint | 节点状态：0-禁用，1-启用 |
| parent_node_id | varchar(64) | 父节点ID |
| model_id | varchar(64) | 关联的模型ID |
| model_ext_param | json | 模型扩展参数（temperature、max_tokens等） |
| created_at | timestamp | 创建时间 |
| updated_at | timestamp | 更新时间 |

#### zb_ai_workflow (AI工作流表)

| 字段名 | 类型 | 说明 |
|--------|------|------|
| id | bigint | 主键ID，自增 |
| workflow_id | varchar(64) | 工作流ID |
| workflow_desc | varchar(256) | 工作流描述 |
| entry_node_id | varchar(64) | 入口节点 |
| app_id | varchar(64) | 应用ID |
| intent_classify_node_id | varchar(64) | 意图识别节点 |
| status | tinyint | 工作流状态：0-不可用，1-可用 |
| enhance_intent_classify | tinyint | 是否开启增强意图识别：0-不开启，1-开启 |
| created_at | timestamp | 创建时间 |
| updated_at | timestamp | 更新时间 |

#### zb_conversation_messages (对话消息表)

| 字段名 | 类型 | 说明 |
|--------|------|------|
| message_id | bigint | 消息唯一标识，自增主键 |
| conversation_id | varchar(64) | 会话ID |
| seq_no | varchar(128) | 对话流水号 |
| question | text | 用户问题 |
| answer | text | AI回答 |
| message_status | tinyint | 消息状态：0-处理中，1-成功，-1-失败 |
| status_description | text | 状态描述，记录请求的实际状况，如错误信息或处理详情 |
| is_human_generated | tinyint | 当前信息是否为人类生成的：0-否，1-是 |
| model_name | varchar(128) | 模型名称 |
| model_provider | varchar(128) | 模型提供商 |
| model_url | varchar(256) | 模型访问地址 |
| extra_info | json | 额外信息，JSON格式，如客户端类型、设备IP等 |
| node_id | varchar(64) | 对话处理的节点 |
| workflow_id | varchar(64) | 对话处理的工作流 |
| created_at | timestamp | 创建时间 |
| updated_at | timestamp | 更新时间 |

#### zb_conversations (会话记录表)

| 字段名 | 类型 | 说明 |
|--------|------|------|
| id | bigint | 主键ID，自增 |
| conversation_id | varchar(64) | 会话唯一标识 |
| conversation_name | varchar(256) | 会话名称（默认为第一个问题的前256字符） |
| employee_id | varchar(256) | 员工编号 |
| user_name | varchar(100) | 用户名称 |
| is_deleted | tinyint | 是否删除：0-未删除，1-已删除 |
| node_id | varchar(64) | 当前会话所处节点 |
| created_at | timestamp | 创建时间 |
| updated_at | timestamp | 更新时间 |

#### zb_node_model (节点模型表)

| 字段名 | 类型 | 说明 |
|--------|------|------|
| id | bigint | 主键ID，自增 |
| model_id | varchar(64) | 模型ID |
| model_provider | varchar(128) | 模型提供商 |
| model_name | varchar(128) | 模型名称 |
| model_url | varchar(256) | 模型访问地址 |
| model_api_key | varchar(128) | 模型API密钥 |
| model_is_out | tinyint | 是否外部大模型：0-否，1-是 |
| status | tinyint | 状态：0-禁用，1-启用 |
| created_at | timestamp | 创建时间 |
| updated_at | timestamp | 更新时间 |

### 节点层级关系（示例）

```
|intent_classification (意图识别节点) - 全部业务
├── agent_bangong (办公智能体) - 办公类业务
│   └── tool_meeting_room (会议室工具) - 会议室类业务
└── agent_yanfa (研发智能体) - 研发类业务
    ├── tool_research_dev (计算工具) - 计算类业务
    └── tool_gen_api_doc (API文档生成工具) - API文档生成类业务
```

---

## 七、设计模式与架构特点

### 7.1 使用的设计模式

| 模式 | 应用位置 | 说明 |
|------|----------|------|
| **抽象工厂模式** | AbstractAI及其子类 | 统一的异步创建接口 `create()` |
| **模板方法模式** | process_user_input流程 | 父类定义骨架，子类实现细节 |
| **单例模式** | 数据库连接池、节点缓存、工作流缓存 | 全局唯一实例，异步锁保护 |
| **策略模式** | 意图类型路由 | 不同意图类型执行不同策略 |
| **代理模式** | tool_call_aware中间件 | 包装工具调用，处理异常 |
| **双重检查锁定** | _ensure_initialized | 并发安全的延迟初始化 |

### 7.2 架构亮点

#### 1. 动态节点加载

- 节点配置存储在数据库，通过 `node_func_path` 动态实例化
- 支持热更新，缓存定时刷新（60秒）

#### 2. LLM实例复用

- 每个节点关联一个模型配置，在缓存加载时初始化 `ChatOpenAI` 实例
- 避免重复创建，提升性能

#### 3. 流式响应架构

- 全链路异步生成器 `AsyncGenerator`
- 统一消息格式，支持SSE实时推送

#### 4. 多级意图识别

```
L1: IntentClassifier → 识别Agent
L2: Agent → 识别Tool
L3: Tool → 识别用户操作意图(继续/切换/结束)
```

#### 5. 上下文传递机制

- `ChatContext` 贯穿整个处理链
- 工具函数通过 `ToolRuntime[ChatContext]` 获取上下文
- 支持执行步数控制，防止无限循环

```python
@dataclass
class ChatContext:
    context_info: dict[str, Any]      # 上下文信息
    user_id: str                      # 用户ID
    conversation_id: str              # 会话ID
    conversation_name: str            # 会话名称
    workflow: ZbAiWorkflow = None     # 工作流配置
    seq_no: str = None                # 对话流水号
    chat_history: list[dict] = None   # 聊天历史
    is_query_history_node_id: bool = False  # 是否按节点查询历史
    run_steps: int = 0                # 当前执行步数
    run_steps_max: int = 5            # 最大执行步数（防止无限循环）
```

#### 6. 话题切换支持

- Tool层实时检测用户是否想切换话题
- 无缝转接到意图分类器重新识别

---

## 八、关键配置示例

### 节点配置

```sql
INSERT INTO zb_conversation_nodes (node_id, node_name, node_type, node_description, node_func_path, node_business_range, status, parent_node_id, model_id, model_ext_param) VALUES
('intent_classification', '小邦全能助手', 'intent', '识别业务属于哪个智能体', 
 'app.ai_frame.intent.intent_classifier.IntentClassifier', '全部业务', 1, NULL, 'deepseek_chat', '{"temperature": 0.7, "max_tokens": 4096}'),
('agent_bangong', '小邦办公助手', 'agent', '办公类业务意图识别智能体',
 'app.ai_frame.agent.agent_bangong.AgentBanGong', '办公类业务', 1, 'intent_classification', 'deepseek_chat', '{"temperature": 0.7, "max_tokens": 8192}'),
('agent_yanfa', '小邦研发助手', 'agent', '研发类业务意图识别智能体',
 'app.ai_frame.agent.agent_yanfa.AgentYanFa', '研发类业务', 1, 'intent_classification', 'deepseek_chat', '{"temperature": 0.7, "max_tokens": 8192}'),
('tool_meeting_room', '小邦会议室助手', 'tool', '会议室预定/查询 - 查询会议室使用情况、预定会议室、查询会议室（可用的、空闲的、使用中的会议室等）',
 'app.ai_frame.tool.tool_book_meeting_room.ToolBookMeetingRoom', '会议室类业务', 1, 'agent_bangong', 'deepseek_chat', '{"temperature": 0.7, "max_tokens": 8192}'),
('tool_research_dev', '小邦计算助手', 'tool', '帮助用户进行数学计算（比如1*8=？或者1+1、一加一等诸如此类的问题）',
 'app.ai_frame.tool.tool_research_dev.ToolResearchDev', '计算类业务', 1, 'agent_yanfa', 'deepseek_chat', '{"temperature": 0.7, "max_tokens": 8192}'),
('tool_gen_api_doc', '小邦API文档生成助手', 'tool', '帮助研发人员生成标准的api文档',
 'app.ai_frame.tool.tool_gen_api_doc.ToolGenApiDoc', 'API文档生成类业务', 1, 'agent_yanfa', 'deepseek_chat', '{"temperature": 0.7, "max_tokens": 8192}');
```

### 工作流配置

```sql
INSERT INTO zb_ai_workflow (workflow_id, workflow_desc, entry_node_id, app_id, intent_classify_node_id, enhance_intent_classify) VALUES
('xiaobang_all', '小邦全能助手', 'intent_classification', 'xiaobang', 'intent_classification', 1),
('xiaobang_book_meeting_room', '小邦会议室管理员', 'tool_meeting_room', 'xiaobang', 'tool_meeting_room', 1),
('xiaobang_bangong', '小邦办公助手', 'agent_bangong', 'xiaobang', 'agent_bangong', 1);
```

### 模型配置

```sql
INSERT INTO zb_node_model (model_id, model_provider, model_name, model_url, model_api_key, model_is_out, status) VALUES
('deepseek_chat', 'deepseek', 'deepseek-chat', 'https://api.deepseek.com/v1', 'sk-xxx', 1, 1);
```

---

## 九、扩展指南

### 9.1 新增工具 (Tool)

1. 创建工具文件 `tool_xxx.py`

```python
from langchain.tools import tool
from langchain.tools import ToolRuntime
from app.ai_frame.context.chat_context import ChatContext
from app.ai_frame.tool.abstract_tool import AbstractTool

@tool(parse_docstring=True)
async def my_tool_func(param: str, run_time: ToolRuntime[ChatContext]) -> str:
    """工具功能描述
    
    Args:
        param: 参数说明
        run_time: 工具运行时上下文
    Returns:
        返回结果说明
    """
    context = run_time.context
    # 实现业务逻辑
    return "结果"

class ToolXxx(AbstractTool):
    def __init__(self):
        super().__init__(node_id="tool_xxx")
    
    async def _initialize_tool(self) -> None:
        self.tool = [my_tool_func]
        self.prompt_tool_call = """系统提示词..."""
    
    def _get_prompt_friendly_response(self) -> str:
        return """友好回应提示词..."""
    
    def _build_intent_analysis_prompt(self) -> str:
        return """意图分析提示词..."""
```

2. 在数据库添加节点配置

```sql
INSERT INTO zb_conversation_nodes (node_id, node_name, node_type, node_description, node_func_path, node_business_range, status, parent_node_id, model_id, model_ext_param) VALUES
('tool_xxx', '工具名称', 'tool', '工具描述',
 'app.ai_frame.tool.tool_xxx.ToolXxx', '业务范围', 1, 'parent_agent_id', 'model_id', '{"temperature": 0.7, "max_tokens": 8192}');
```

### 9.2 新增智能体 (Agent)

1. 创建智能体文件 `agent_xxx.py`

```python
from app.ai_frame.agent.abstract_agent import AbstractAgent

class AgentXxx(AbstractAgent):
    def __init__(self):
        super().__init__(node_id="agent_xxx")
    
    def _get_prompt_friendly_response(self) -> str:
        return """友好回应提示词..."""
```

2. 在数据库添加节点配置

```sql
INSERT INTO zb_conversation_nodes (node_id, node_name, node_type, node_description, node_func_path, node_business_range, status, parent_node_id, model_id, model_ext_param) VALUES
('agent_xxx', '智能体名称', 'agent', '智能体描述',
 'app.ai_frame.agent.agent_xxx.AgentXxx', '业务范围', 1, 'intent_classification', 'model_id', '{"temperature": 0.7, "max_tokens": 8192}');
```

---

## 十、总结

`ai_frame` 是一个设计精良的企业级AI对话框架，其核心优势在于：

1. **高度可配置**：通过数据库配置节点、模型、工作流，无需修改代码即可调整业务逻辑
2. **优秀的扩展性**：抽象基类定义清晰接口，新增Agent/Tool只需继承并实现少量方法
3. **并发安全**：异步锁保护关键资源，双重检查锁定防止重复初始化
4. **用户体验优先**：全链路流式响应，快速规则+LLM两级意图识别兼顾效率与准确性
5. **灵活的话题切换**：支持用户随时切换业务场景，无缝转接

该架构适合构建企业级智能客服、办公助手等需要多业务场景切换的AI应用。
