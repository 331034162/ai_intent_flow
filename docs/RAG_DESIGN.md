# 基于文档和知识库的写作助手框架设计

## 一、概述

本文档描述了一个智能写作助手框架的设计。该框架基于 RAG（Retrieval-Augmented Generation）技术，能够智能判断用户写作需求，从上传文档和知识库中获取参考资料，并根据任务类型生成相应风格的写作内容。

### 核心入口

`DocKnowledgeRAG.process_user_input()` 是整个写作助手框架的主入口方法，负责协调整个写作流程。

## 二、系统架构

### 2.1 类继承关系

```
AbstractAI (抽象基类)
    │
    ├── 提供基础能力：流式输出、Token 记录、对话保存
    │
    └── AbstractRAG (抽象路由器)
            │
            ├── 路由决策能力
            ├── 意图识别能力
            ├── 提示词构建能力
            │
            └── DocKnowledgeRAG (文档知识路由器实现)
                    │
                    └── 完整的 RAG 处理流程实现
```

### 2.2 核心组件

| 组件 | 文件路径 | 职责 |
|------|----------|------|
| `DocKnowledgeRAG` | `rag/doc_knowledge_rag.py` | RAG 完整实现，入口类 |
| `AbstractRAG` | `rag/abstract_rag.py` | 路由决策、意图识别、提示词构建 |
| `AbstractAI` | `abstract_ai.py` | 流式输出、Token 记录、数据库操作 |
| `FileLoad2DB` | `db_connection_pool/file_load_2_db.py` | 文件加载、清洗、入库 |
| `ChatContext` | `context/chat_context.py` | 对话上下文数据结构 |

## 三、处理流程详解

### 3.1 流程总览

```
用户输入 (user_input)
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│  1. 初始化阶段                                                │
│     ├── 确保节点已加载 (_ensure_initialized)                  │
│     └── 获取聊天历史 (get_chat_history_from_db)              │
└─────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│  2. 文件准备阶段                                              │
│     ├── 解析 file_id 列表                                     │
│     └── 批量获取上传文件信息 (FileLoad2DB.get_files_by_ids)   │
└─────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│  3. 历史文档判断阶段                                          │
│     ├── 调用 classify_use_history_intent()                   │
│     ├── 判断是否需要引用历史文档                              │
│     └── 如需要，获取历史文件并合并                            │
└─────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│  4. 路由决策阶段                                              │
│     ├── 调用 route() 方法                                     │
│     ├── 确定任务类型 (TaskType)                               │
│     ├── 判断是否使用文件 (use_file)                           │
│     ├── 判断是否查询知识库 (use_knowledge_base)               │
│     └── 生成检索问题列表 (search_queries)                     │
└─────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│  5. 内容获取阶段                                              │
│     ├── 获取文件内容 (_get_file_content)                      │
│     └── 获取知识库内容 (_get_knowledge_content)               │
└─────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│  6. 提示词构建阶段                                            │
│     ├── 构建最终指令 (build_final_instruction)                │
│     └── 构建生成提示词 (build_generate_prompt)                │
└─────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│  7. 大模型调用阶段                                            │
│     ├── 流式生成回答 (llm.astream)                            │
│     └── 实时输出内容                                          │
└─────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│  8. 后处理阶段                                                │
│     ├── 记录 Token 使用 (log_token_usage)                     │
│     └── 保存对话记录 (_save_conversation_to_db)               │
└─────────────────────────────────────────────────────────────┘
        │
        ▼
    返回流式响应
```

### 3.2 各阶段详细说明

#### 阶段 1：初始化

```python
# 确保节点配置已加载
await self._ensure_initialized()

# 获取聊天历史
chat_history = context.chat_history or []
if not chat_history and context.is_query_history_node_id:
    chat_history = await AbstractAI.get_chat_history_from_db(
        context.conversation_id,
        message_status=1,
        node_id=self.node_id,
        max=context.history_max_records
    )
```

**说明**：
- 从数据库加载节点配置（模型名称、URL、参数等）
- 按需从数据库加载聊天历史记录

#### 阶段 2：文件准备

```python
if context.file_list:
    file_id_arr = context.file_list.split(",")
    current_files = await FileLoad2DB.get_files_by_ids(file_id_arr)
    upload_files = current_files
    file_name_list = [f.file_name for f in current_files]
```

**说明**：
- 解析 `context.file_list`（逗号分隔的 file_id）
- 批量从数据库获取文件信息（包含文件内容）

#### 阶段 3：历史文档判断

```python
use_history_result = await self.classify_use_history_intent(
    user_input, file_name_list, chat_history, context
)

if use_history_result.intent == UseHistoryDocumentIntent.NEED_HISTORY:
    # 获取历史文件并合并
    info_his = await self.extract_original_content_from_history(chat_history)
    # ... 合并文件
```

**判断逻辑**：
| 条件 | 结果 |
|------|------|
| 用户说"重写"且当前无上传文件 | `NEED_HISTORY` |
| 用户上传了文件 | `NO_HISTORY` |
| 用户说"修改"、"润色"、"优化" | `NO_HISTORY` |
| 其他情况 | `NO_HISTORY` |

#### 阶段 4：路由决策

```python
route_result = await self.route(
    user_query=user_input,
    file_name_list=file_name_list,
    history_messages=history_messages,
    context=context
)
```

**路由结果结构**：

```python
@dataclass
class RouteResult:
    use_file: bool                    # 是否使用上传文件
    use_knowledge_base: bool          # 是否查询知识库
    search_queries: List[str]         # 知识库检索问题列表
    task_type: TaskType               # 任务类型
    generate_prompt: List[str]        # 生成指令列表
```

**任务类型枚举**：

| TaskType | 说明 | 适用场景 |
|----------|------|----------|
| `SUMMARY` | 总结概括 | 总结文档、提炼要点、核心内容、摘要 |
| `REPORT` | 分析报告 | 撰写报告、分析评估、调研分析 |
| `OUTLINE` | 大纲框架 | 生成目录、大纲、框架、结构规划 |
| `ARTICLE` | 文章撰写 | 撰写文章、论文、文案、公文 |
| `QA` | 问答回复 | 问题解答、信息查询、概念解释 |
| `COMPARE` | 对比分析 | 对比文件、核对差异、检查合规 |
| `EXTRACT` | 信息提取 | 提取数据、关键信息、结构化输出 |
| `TRANSLATE` | 翻译转换 | 文档翻译、语言转换 |
| `REWRITE` | 改写润色 | 优化文字、润色文档、改写内容 |
| `SPEECH` | 演讲稿撰写 | 撰写演讲稿、发言稿、致辞稿 |
| `BRIEFING` | 汇报撰写 | 撰写工作汇报、项目汇报 |
| `WRITE_SUMMARY` | 写总结 | 撰写工作总结、学习总结 |
| `NORMAL` | 普通闲聊 | 日常问候、闲聊对话 |

#### 阶段 5：内容获取

```python
# 获取文件内容
if route_result.use_file:
    file_content = self._get_file_content(upload_files)

# 获取知识库内容
if route_result.use_knowledge_base:
    knowledge_content = await self._get_knowledge_content(
        route_result.search_queries
    )
```

#### 阶段 6：提示词构建

```python
# 构建最终指令
final_instruction = self.build_final_instruction(route_result, user_input)

# 构建生成提示词
generate_prompt = self.build_generate_prompt(
    final_instruction=final_instruction,
    task_type=route_result.task_type,
    use_file=route_result.use_file,
    use_knowledge_base=route_result.use_knowledge_base,
    file_content=file_content,
    knowledge_content=knowledge_content
)
```

**最终 System Prompt 结构**：

```
你是一个专业的智能助手。请根据提供的参考资料，完成用户的任务要求。

【用户上传文件内容】
{file_content}

【系统知识库内容】
{knowledge_content}

【需要完成的任务】
{final_instruction}

【输出风格要求】
{task_type_desc}
具体要求：{task_style_detail}

请输出一份完整、连贯、结构清晰的内容。
```

#### 阶段 7：大模型调用

```python
messages = [SystemMessage(content=generate_prompt)]
messages.extend(history_messages)
messages.append(HumanMessage(content=user_input))

async for chunk in self.llm.astream(messages):
    # 流式输出
    yield self.create_stream_message(
        content=content,
        message_type="model",
        is_last=False,
        is_over=False,
        conversation_id=context.conversation_id
    )
```

#### 阶段 8：后处理

```python
# 记录 Token 使用
await self.log_token_usage(context, node, usage_metadata, latency_ms)

# 保存对话记录
await self._save_conversation_to_db(
    context=context,
    question=user_input,
    answer=full_content,
    status_description="处理成功",
    message_status=1,
    file_id_list=final_file_id_list,
    task_type=route_result.task_type.value
)
```

## 四、数据结构

### 4.1 ChatContext 对话上下文

```python
@dataclass
class ChatContext:
    context_info: dict[str, Any]      # 上下文信息
    user_id: str                       # 用户ID
    conversation_id: str               # 会话ID
    conversation_name: str             # 会话名称
    workflow: ZbAiWorkflow             # 工作流信息
    seq_no: str                        # 序列号
    chat_history: list[dict]           # 聊天历史
    is_query_history_node_id: bool     # 是否按节点查询历史
    run_steps: int                     # 执行步数
    run_steps_max: int                 # 最大执行步数
    history_max_records: int           # 历史消息最大条数
    conversation_type: int             # 对话类型（1:模型对话 2:知识库对话）
    file_list: str                     # 文件ID列表（逗号分隔）
```

### 4.2 UploadFile 上传文件

```python
@dataclass
class UploadFile:
    file_id: str          # 文件ID
    user_id: str          # 用户ID
    file_name: str        # 文件名
    file_type: str        # 文件类型
    file_size: int        # 文件大小
    file_path: str        # 文件路径
    file_content: str     # 文件内容（已清洗）
    status: int           # 状态（1:有效 0:已删除）
```

### 4.3 RouteResult 路由结果

```python
@dataclass
class RouteResult:
    use_file: bool                    # 是否使用上传文件
    use_knowledge_base: bool          # 是否查询知识库
    search_queries: List[str]         # 知识库检索问题列表
    task_type: TaskType               # 任务类型
    generate_prompt: List[str]        # 生成指令列表
```

### 4.4 UseHistoryDocumentResult 历史文档意图

```python
@dataclass
class UseHistoryDocumentResult:
    intent: UseHistoryDocumentIntent  # 意图类型
    reason: str                        # 判断理由
```

## 五、文件处理模块

### 5.1 支持的文件类型

| 扩展名 | 类型标识 | 处理方式 |
|--------|----------|----------|
| `.txt` | txt | 直接读取 |
| `.md`, `.markdown` | markdown | 直接读取 |
| `.csv` | csv | csv 模块解析 |
| `.pdf` | pdf | PyPDFLoader / pdfplumber |
| `.doc`, `.docx`, `.docm` | word | Docx2txtLoader / python-docx |
| `.xls`, `.xlsx` | excel | UnstructuredExcelLoader / pandas |

### 5.2 文件内容清洗流程

```
原始内容
    │
    ├── 1. 去除 BOM 字符
    │
    ├── 2. 统一换行符 (\r\n → \n)
    │
    ├── 3. 压缩多余空行（超过2个连续空行压缩为2个）
    │
    ├── 4. 去除行首行尾空白
    │
    ├── 5. 去除全角空格和特殊空白字符
    │
    └── 6. 压缩多个连续空格为单个
    │
清洗后内容
```

### 5.3 文件入库流程

```python
file_id = await FileLoad2DB.load_and_save(
    user_id="user123",
    file_path="/path/to/file.pdf"
)
```

## 六、提示词配置

### 6.1 RAGPrompts 配置类

集中管理所有 RAG 相关提示词：

- `ROUTE_SYSTEM_PROMPT`: 路由决策 System Prompt
- `ROUTE_USER_TEMPLATE_WITH_FILE`: 带文件的用户问题模板
- `ROUTE_USER_TEMPLATE_NO_FILE`: 不带文件的用户问题模板
- `TASK_TYPE_DESC`: 任务类型描述映射
- `TASK_STYLE_DETAIL`: 任务风格详细说明映射

### 6.2 路由决策 Prompt 结构

```
System: 你是一个专业的多源知识路由助手。请分析用户需求，输出合法JSON。

输出JSON格式：
{
    "use_file": true/false,
    "use_knowledge_base": true/false,
    "search_queries": ["检索问题1", "检索问题2"],
    "task_type": "summary|report|...",
    "generate_prompt": ["指令1", "指令2"]
}

[字段详细说明...]

Human: 【用户当前问题】
{user_query}

【用户本次上传文件列表】
{file_list}
```

## 七、异常处理

### 7.1 流式输出错误处理

```python
try:
    # 处理流程...
except Exception as e:
    app_logger.error(f"处理用户输入失败: {e}")
    error_message = f"抱歉，处理您的请求时出现错误: {str(e)}"
    
    # 保存失败的对话记录
    await self._save_conversation_to_db(
        context=context,
        question=user_input,
        answer=error_message,
        status_description=f"处理失败: {str(e)}",
        message_status=-1,
        ...
    )
    
    # 发送错误消息
    yield self.create_stream_message(...)
```

### 7.2 JSON 解析失败处理

当路由决策的 JSON 解析失败时，返回默认结果：

```python
def _get_default_result(self, file_name_list: List[str]) -> RouteResult:
    return RouteResult(
        use_file=len(file_name_list) > 0,
        use_knowledge_base=False,
        search_queries=[],
        task_type=TaskType.NORMAL,
        generate_prompt=[]
    )
```

## 八、使用示例

### 8.1 基本使用

```python
from app.ai_frame.rag.doc_knowledge_rag import DocKnowledgeRAG
from app.ai_frame.context.chat_context import ChatContext

# 创建路由器实例
router = DocKnowledgeRAG(node_id="doc_knowledge_rag")

# 准备上下文
context = ChatContext(
    context_info={},
    user_id="user123",
    conversation_id="conv_001",
    conversation_name="测试对话",
    file_list="file_id_1,file_id_2"
)

# 处理用户输入（流式）
async for chunk in router.process_user_input("请帮我总结这两个文件的主要内容", context):
    print(chunk["content"], end="", flush=True)
```

### 8.2 文件上传入库

```python
from app.ai_frame.db_connection_pool.file_load_2_db import FileLoad2DB

# 上传并入库文件
file_id = await FileLoad2DB.load_and_save(
    user_id="user123",
    file_path="/path/to/document.pdf"
)

# 获取文件信息
file_info = await FileLoad2DB.get_file_by_id(file_id)
print(f"文件名: {file_info.file_name}")
print(f"内容长度: {len(file_info.file_content)}")
```

## 九、数据库表结构

### 9.1 zb_conversation_upload_files 上传文件表

| 字段 | 类型 | 说明 |
|------|------|------|
| file_id | varchar(36) | 文件ID（UUID） |
| user_id | varchar(50) | 用户ID |
| file_name | varchar(255) | 文件名 |
| file_type | varchar(20) | 文件类型 |
| file_size | bigint | 文件大小 |
| file_path | varchar(500) | 文件存储路径 |
| file_content | text | 文件内容（已清洗） |
| status | int | 状态（1:有效 0:已删除） |
| create_time | datetime | 创建时间 |
| update_time | datetime | 更新时间 |

### 9.2 zb_conversation_messages 对话消息表

存储对话记录，包含：
- conversation_id: 会话ID
- question: 用户问题
- answer: AI回答
- file_id_list: 对话用到的文件ID列表
- task_type: 任务类型
- message_status: 消息状态（1:成功 -1:失败）

## 十、扩展说明

### 10.1 自定义知识库检索

当前 `_get_knowledge_content()` 方法为占位实现，可扩展对接向量数据库：

```python
async def _get_knowledge_content(self, search_queries: list) -> str:
    knowledge_parts = []
    for query in search_queries:
        # TODO: 对接向量数据库检索
        results = await vector_db.search(query, top_k=5)
        knowledge_parts.append(f"【检索: {query}】\n{results}")
    return "\n\n".join(knowledge_parts)
```

### 10.2 自定义任务类型

可在 `TaskType` 枚举中添加新的任务类型，并在 `RAGPrompts` 中配置对应的描述和风格说明。

---

**文档版本**: v1.0  
**最后更新**: 2026-04-01
