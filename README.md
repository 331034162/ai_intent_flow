# AI Intent Flow

基于 **LangGraph** 的多 Agent 智能对话框架，支持意图识别、多级路由分发、工具调用（ReAct 循环）、人机交互中断（HITL）和流式 SSE 输出，通过数据库驱动的配置实现节点、提示词、模型的热更新。

---

## 目录

- [快速开始](#快速开始)
- [架构设计](#架构设计)
- [核心功能](#核心功能)
- [技术栈](#技术栈)
- [项目结构](#项目结构)
- [API 接口](#api-接口)
- [类层次关系](#类层次关系)
- [关键设计](#关键设计)
  - [对话历史双维度智能剪裁](#6-对话历史双维度智能剪裁)

---

## 快速开始

### 1. 环境要求

- Python >= 3.10
- MySQL 8.0+

### 2. 安装配置

```bash
# 克隆项目
git clone <repo-url>
cd ai_intent_flow

# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env，填写实际的 MySQL 连接信息等
```

### 3. 初始化数据库

执行 `app/db_scripts/schema_unified.sql` 创建表结构和种子数据。

### 4. 启动服务

```bash
# 开发模式（热重载）
python -m app.main --reload

# 指定端口
python -m app.main --host 0.0.0.0 --port 8000

# 生产模式
python -m app.main
```

### 5. 访问

| 地址 | 说明 |
|------|------|
| `http://localhost:8000/` | 管理后台首页，支持对话测试和信息配置 |
| `http://localhost:8000/docs` | Swagger API 文档（DEBUG=true 时） |
| `http://localhost:8000/health` | 健康检查 |
| `http://localhost:8000/health/detail` | 详细健康检查（含数据库） |

---

## 架构设计

### 整体架构

```
┌────────────────────────────────────────────────────────┐
│                   HTTP Layer (FastAPI)                  │
│  /frame/run/sse  |  /api/*  |  /health  |  /static     │
├────────────────────────────────────────────────────────┤
│                    Workflow Layer                       │
│  ZBXiaoBangWorkflow / ZBXiaoBangRAG                    │
│  └── 节点实例化、路由分发、流式输出编排                    │
├────────────────────────────────────────────────────────┤
│               Multi-Agent Layer (LangGraph)             │
│  ┌──────────────────┬──────────────────────────┐       │
│  │  IntentClassifier│  Agent  →  Tool (ReAct)  │       │
│  │     (一级意图)    │  (二级意图)  (最终执行)   │       │
│  └──────────────────┴──────────────────────────┘       │
│  LangGraphAgent / LangGraphAgentBuilder                │
├────────────────────────────────────────────────────────┤
│                Infrastructure Layer                    │
│  Config | Logger | Cache | DB Pool | File Loader       │
├────────────────────────────────────────────────────────┤
│                   Data Layer (MySQL)                   │
│  workflows | nodes | prompts | models | conversations  │
└────────────────────────────────────────────────────────┘
```

### 执行流程

```
用户输入 → /frame/run/sse
  └→ ZBXiaoBangWorkflow.process_user_input()
       ├── 从 DB 加载 ZbAiWorkflow 配置
       ├── 创建/查询会话信息
       ├── 按 entry_node_id 实例化入口节点
       └→ node.process_user_input()  ← 多态分发
            │
            ├── IntentClassifier (入口节点)
            │   └── LLM 意图识别 → 分发到对应 Agent
            │
            ├── AbstractAgent (中间节点)
            │   └── LLM 二次意图识别 → 分发到对应 Tool
            │
            └── AbstractTool (叶子节点)
                └── LangGraph StateGraph ReAct 循环
                    chatbot ↔ tool_executor (支持 HITL 中断)
                    └── SSE 流式输出
```

### LangGraph 工作流图

```
START → intent_identify_node → [条件路由]
                                    │
                 ┌──────────────────┼──────────────────┐
                 ▼                  ▼                  ▼
        {business}_chatbot   change_topic_node     END (兜底)
        ↔ tool_executor            │           (friendly_response/
             (ReAct 循环)           ▼            end_business)
                                   END
```

---

## 核心功能

### 1. 多级意图分类链

- **一级意图**（`IntentClassifier`）：根据 `business_range` 将用户请求分发到对应业务 Agent
- **二级意图**（`AbstractAgent`）：在业务范围内进一步识别 4 种意图：
  | 意图类型 | 含义 | 路由目标 |
  |----------|------|----------|
  | `continue_business` | 继续办理业务 | 对应 Tool 的 chatbot 节点 |
  | `friendly_response` | 友好回应 | 后置处理生成回复 |
  | `change_topic` | 切换话题 | 委托给入口节点重新识别 |
  | `end_business` | 结束办理 | 后置处理生成告别语 |

### 2. ReAct Tool 执行

每个 `AbstractTool` 子类内部是一个 LangGraph StateGraph，包含：
- **chatbot 节点**：LLM + tools 绑定，决定调用哪个工具
- **tool_executor 节点**：执行工具函数，支持串行/并行
- **return_direct 机制**：标记工具是否跳过 LLM 总结直接返回
- **消息裁剪**：按 `history_max_records` 自动裁剪上下文

### 3. 人机交互中断（HITL）

- 工具执行中通过 `GraphInterrupt` 暂停等待用户确认
- 如会议室预订：用户选择 → 验证 → 确认 → 执行
- 中断状态持久化到 MySQL，支持跨请求恢复

### 4. NodePromptCache 提示词版本管理

- 提示词支持**版本发布/暂存**状态流转
- 发布操作在事务内原子切换生效表 + 降级旧版本
- 缓存 60 秒自动刷新 + 发布后主动刷新，实现热更新
- 支持 `{变量}` 插值（库内默认值 + 运行时动态值）

### 5. 数据库驱动的热配置

所有核心配置从 MySQL 读取，无需重启即可更新：

| 配置对象 | 表名 | 缓存间隔 |
|----------|------|----------|
| 工作流 | `zb_ai_workflow` | 60s |
| 节点 | `zb_conversation_nodes` | 60s |
| 提示词 | `zb_node_prompt` | 60s |
| 模型 | `zb_llm_models` | 60s |

### 6. 流式 SSE 输出

统一响应结构：
```json
{
  "content": "生成的文本片段",
  "status": "streaming",
  "conversation_id": "xxx",
  "content_type": "text",
  "seq_no": "xxx"
}
```

### 7. 管理后台面板

访问 `http://localhost:8000/` 进入管理后台，左侧导航栏提供 5 个功能模块（`app/static/`）：

####   LLM 模型管理 (`llm_model_manager/`)
- 大模型信息全生命周期管理（CRUD + 启禁用）
- 配置项：模型名称、Provider、API Key、Base URL、上下文长度、价格（输入/输出）
- 能力标签：是否支持流式/函数调用/视觉/联网搜索/JSON 模式
- 模型分组：按 category、group、tags 归类
- 所有模型配置存储在 `zb_llm_models` 表，60s 缓存热更新

####   AI 工作流管理 (`ai_workflow_manager/`)
- 工作流定义与编辑（CRUD + 启禁用）
- 配置项：workflow_id、描述、入口节点 `entry_node_id`、意图分类节点 `intent_classify_node_id`
- 支持"增强意图识别"开关（`enhance_intent_classify`）
- 数据存储在 `zb_ai_workflow` 表

####   会话节点管理 (`conversation_node_manager/`)
- 智能体节点的增删改查
- 配置项：node_id、节点名称、节点类型（Intent/Agent/Tool）、业务范围（`node_business_range`）、类路径（`node_func_path`）、父节点
- 可为每个节点独立挂载 LLM 模型（`model_id` + `model_ext_param`）
- 数据存储在 `zb_conversation_nodes` 表，操作后自动刷新缓存

####   提示词版本管理 (`node_config_manager/`)

一个完整的**提示词版本生命周期管理**系统：

```
                    save_draft
暂存 (status=0)                暂存 (status=0, version+1)
     │       ←              │
     │  publish              │
     ▼                      │
发布 (status=1) ──────────────┘
     │
     └→ 同步 upsert 到 zb_node_prompt 生效表
        旧发布记录降级为暂存 (status→0)
        自动刷新 NodePromptCache 缓存
```

- **暂存/发布**：提示词可反复修改暂存，确认无误后一键发布
- **版本链路**：发布后编辑自动新增子版本（`parent_id` 追溯），保留完整修改历史（`prompt_content_before_modify`）
- **原子发布**：同一事务内完成"当前暂存→发布 + 旧发布→降级 + 同步生效表"，保证一致性
- **提示词级模型覆盖**：每个 prompt 可指定独立的 model_id，运行时通过 `resolve_prompt_model()` 动态解析

####   聊天测试页 (`chat.html`)
- 即时对话调试，支持选择工作流、输入 conversation_id
- 实时 SSE 流式输出，展示完整对话链路
- 便于开发和测试阶段快速验证节点配置和提示词效果

### 8. RAG 知识库写作助手

基于路由决策的智能写作框架（`ZbDocKnowledgeRAG`）：
- 自动识别 12 种任务类型（总结/报告/大纲/文章/问答/对比/提取/翻译/改写/演讲/汇报/写总结）
- 多源知识路由（上传文件 + 知识库检索）
- 历史文档引用判断
- 支持 PDF/DOCX/XLSX/CSV/MD 等格式文件解析

---

## 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| Web 框架 | FastAPI + Uvicorn | 异步 HTTP 服务 |
| AI 编排 | LangChain + LangGraph | StateGraph + ReAct 循环 |
| LLM 接入 | langchain-openai | 通过 OpenAI 兼容 API 统一调用 |
| 数据库 | MySQL + aiomysql | 异步连接池，checkpoint 持久化 |
| 配置 | pydantic-settings | `.env` 驱动 + Settings 代理模式 |
| 日志 | Loguru | 结构化日志 |
| 序列化 | ormsgpack | 高性能序列化 |
| 文档解析 | pypdf/pdfplumber/python-docx/openpyxl | 多格式文件解析 |

---

## 项目结构

```
ai_intent_flow/
├── app/
│   ├── main.py                          # FastAPI 入口
│   ├── api/                             # API 路由层
│   │   ├── router.py                    # 路由聚合
│   │   ├── frame_api.py                 # 核心 SSE 接口 /frame/run/sse
│   │   ├── chat_api.py                  # 会话历史查询
│   │   ├── manage_api.py                # 管理后台 CRUD
│   │   └── health.py                    # 健康检查
│   │
│   ├── core/                            # 基础设施
│   │   ├── config.py                    # 配置管理（代理模式）
│   │   └── logger.py                    # Loguru 封装
│   │
│   ├── context/
│   │   └── chat_context.py              # ChatContext 数据类
│   │
│   ├── intent/                          # 一级意图识别
│   │   ├── abstract_intent.py           # 意图基类
│   │   └── intent_classifier.py         # 意图分类器
│   │
│   ├── agent/                           # 二级 Agent 路由
│   │   ├── abstract_agent.py            # Agent 基类
│   │   └── agent_bangong.py             # 办公助手
│   │
│   ├── tool/                            # 工具层（最终执行）
│   │   ├── abstract_tool.py             # create_agent 版
│   │   ├── abstract_tool_lang_graph.py  # StateGraph 版（推荐）
│   │   ├── abstract_tool_hitl.py        # HITL 版
│   │   ├── xb_bangong/                  # 办公业务工具
│   │   └── util/                        # 工具辅助类
│   │
│   ├── langgraph_agent/                 # LangGraph Agent 封装
│   │   ├── langgraph_agent.py           # 独立 ReAct Agent
│   │   └── langgraph_agent_builder.py   # 多 Agent 图构建器
│   │
│   ├── workflow/                        # 工作流编排
│   │   ├── zb_xiaobang_workflow.py      # 通用对话工作流
│   │   └── zb_xiaobang_rag.py           # RAG 知识库工作流
│   │
│   ├── db_connection_pool/              # 数据库连接与工具类
│   ├── db_scripts/                      # SQL 脚本
│   └── static/                          # 管理前端页面
│
├── docs/                                # 设计文档
│   ├── AI_FRAME_DESIGN.md               # 框架设计总览
│   ├── AI_FRAME_DEV_GUIDE.md            # 开发指南
│   ├── RAG_DESIGN.md                    # RAG 写作助手设计
│   ├── abstract_tool_lang_graph_analysis.md  # LangGraph 工具链路分析
│   ├── TOOL_BOOK_MEETING_ROOM_GUIDE.md      # 会议室预订业务规则
│   └── 节点提示词版本管理设计文档.md
│
├── tests/                               # 测试
├── pyproject.toml
├── requirements.txt
├── .env.example                         # 配置模板
└── .gitignore
```

---

## API 接口

### 核心业务

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/frame/run/sse` | 流式 SSE 工作流执行（JSON Body → text/event-stream） |

### 健康检查

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 基础健康检查 |
| GET | `/health/detail` | 含 MySQL 检测 |
| GET | `/health/config` | 查看全部配置 |

### 对话查询

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/conversations/list` | 用户会话列表 |
| GET | `/api/conversations/messages` | 会话历史消息 |
| GET | `/api/workflows` | 可用工作流列表 |

### 管理接口（完整 CRUD）

| 域 | 路径 |
|----|------|
| 会话节点 | `/api/conversation-nodes` |
| AI 工作流 | `/api/ai-workflows` |
| 大模型 | `/api/llm-models` |
| 提示词版本 | `/api/node-prompts` + `/api/node-configs` |
| 节点/提示词查询 | `/api/nodes` + `/api/prompts` |

---

## 类层次关系

```
AbstractAI                              ← 最顶层抽象基类
├── 定义: process_user_input() 流式处理入口
│         create_stream_message() SSE 消息构造
│         log_token_usage() Token 记录
│         resolve_prompt_model() 提示词+模型解析
│
├── AbstractIntent                      ← 一级意图基类
│   └── IntentClassifier               ← node_id="intent_classification"
│
├── AbstractAgent                       ← 二级 Agent 基类
│   └── AgentBanGong                   ← node_id="agent_bangong"
│
└── AbstractTool                        ← 工具基类
    └── (具基于 LangGraph StateGraph)
        └── tool_book_meeting_room 等

独立组件：
├── LangGraphAgent                      ← 通用 ReAct Agent
├── LangGraphAgentBuilder               ← 多 Agent StateGraph 构建器
├── ZBXiaoBangWorkflow                  ← 工作流编排（静态方法类）
├── ZBXiaoBangRAG                       ← RAG 工作流（静态方法类）
└── ChatContext                         ← 对话上下文（@dataclass）
```

---

## 关键设计

### 1. 消息隔离与去重

- 使用 `WarappedMessage` 包装消息，带 `agent_name` 标识归属
- `use_all_messages` 控制 Agent 间历史消息可见性
- 自定义 `add_wrapped_messages` reducer 按 `message.id` 去重

### 2. 状态持久化

- LangGraph checkpoint 使用 `AIOMySQLSaver` 持久化到 MySQL
- `JsonPlusSerializer` 支持自定义类型序列化
- `thread_id` 关联会话与节点，支持跨请求上下文恢复

### 3. 并发安全

- `asyncio.Lock` + 双重检查锁定（DCL）防止重复初始化
- `_initialized` 标志 + 懒加载实例化

### 4. 图内外职责分离

| 范围 | 职责 |
|------|------|
| 图内 | 意图识别、业务 Agent 对话循环、切换话题日志、工具执行 |
| 图外 | 友好回应生成、切换话题委托、数据库保存、token 记录 |

设计原因：避免图节点内生成友好回应导致与 `process_user_input` 末尾的数据库保存重复。

### 5. 配置代理模式

`Settings` 通过 `_SettingsProxy` 代理类对外暴露，每次访问属性时动态获取最新配置，避免模块 import 时固定配置对象。同时支持 Apollo 热更新。

### 6. 对话历史双维度智能剪裁

本项目在对话历史处理上有独特的双维度剪裁优势，确保 LLM 上下文始终精炼、聚焦：

#### 智能体维度剪裁（Agent-Dimension）

每次查询对话历史时，按 `node_id` 过滤，只获取与当前智能体节点相关的历史记录：

```
abstract_tool.py:143-144
chat_history = await AbstractAI.get_chat_history_from_db(
    conversation_id, message_status=1,
    node_id=self.node_id,           # ← 只查询本节点的历史
    max=context.history_max_records
)
```

不同业务节点（会议预订、办公助手等）各自只获取自己的历史上下文，**避免无关业务的对话污染当前智能体的判断**，让 LLM 更精准地理解用户在当前业务中的意图。

#### 业务维度剪裁（Business-Dimension）

同一智能体内，通过 `thread_id` 实现业务边界的历史隔离：

```
每个 (conversation_id, node_id) → 独立 thread_id
业务结束 → 标记 completed → 下次进入创建新 thread_id
```

- **已完成的旧 thread**：历史消息通过 `load_completed_thread_messages()` 快照归档，存入 `context.snapshot_messages`
- **新 thread**：从干净状态开始，快照消息由 `MessageTrimMiddleware` 在 LLM 调用时临时拼接，不写入 state，避免堆积
- **`MessageTrimMiddleware`**：在每次 LLM 调用前，自动裁剪超长上下文（`trim_messages`，`strategy="last"`，`start_on="human"`）

```
用户发起新业务
    └→ 创建新 thread_id（干净状态）
         └→ LLM 调用前，MessageTrimMiddleware 自动：
              ├── 拼接 snapshot_messages（旧 thread 参考上下文）
              ├── 裁剪超出 history_max_records * 2 的消息
              └── 不修改 state（零副作用）
```

#### 双层保障

| 层级 | 裁剪方式 | 触发时机 |
|------|----------|----------|
| 数据库层 | `get_chat_history_from_db(node_id=...)` | 查询历史时按节点隔离 |
| 中间件层 | `MessageTrimMiddleware` + `trim_messages` | 每次 LLM 调用前自动裁剪 |

#### 业务完整性保留（Business-Completeness Preservation）

除了剪裁，框架还通过 `set_business_state_completed()` 实现了**上一轮完整业务对话的保留**，确保 LLM 理解完整的业务上下文：

```
book_meeting_room() 工具执行流程:
  ├── 查询可用会议室
  ├── 用户选择时段
  ├── 中断确认 (HITL)
  ├── 用户确认 → 执行预订
  └── finally: context.set_business_state_completed()  ← 标记业务完成

_gen_response() 结束后:
  └→ end_business() → DB 标记 thread 为 "completed"

下一次用户对话:
  ├── get_or_create_thread_id() → 发现旧 thread 已完成 → 创建新 thread_id
  ├── load_completed_thread_messages() → 加载上一轮完整对话快照
  └→ MessageTrimMiddleware 临时拼接到 LLM 上下文
```

**核心价值**：当用户再次对话时，LLM 看到的是**上一轮完整业务处理的所有交互**（从查询到预订的完整链路），而不是被截断的碎片化消息。这让 LLM 能准确理解"上次预订了什么会议室、什么时间、结果如何"，从而做出更精准的后续判断。

对比传统方案：传统做法只保留最近 N 条消息，一旦对话轮次超过阈值，早期关键信息就会被丢弃。本框架以**业务边界**为粒度保留历史——一整轮业务作为一个整体快照存下来，新对话时完整呈现，信息零丢失。

> **对比总结**：本项目的三层历史管理机制（智能体维度隔离 → 业务维度裁剪 → 业务完整性保留），确保了 LLM 上下文既**精炼**（不膨胀）又**完整**（不丢信息），在 token 效率和语义理解之间取得了最佳平衡。

对比传统方案：传统做法往往把所有对话历史一股脑塞给 LLM，导致上下文膨胀、token 浪费、意图判断模糊。本项目的双维度剪裁机制从源头保证了上下文的精准性。

### 7. 扩展性

- **新增业务模块**：只需实现 `AbstractTool` 子类的 `_initialize_tool()` 和 `_build_intent_analysis_prompt()` 两个方法
- **新增 Agent**：继承 `AbstractAgent`，实现 `_get_prompt_classification()`
- **新增工具**：注册普通函数，框架自动检测签名并注入 `ToolRuntime` 和 `Context`

---

## License

MIT
