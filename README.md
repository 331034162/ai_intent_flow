# AI Intent Flow

基于 LangGraph 的 AI 意图流式框架。

## 快速开始

### 1. 配置

```bash
cp .env.example .env
# 编辑 .env，填写实际的 MySQL、LLM 等配置
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 启动

```bash
# 开发模式（热重载）
python -m app.main --reload

# 指定端口
python -m app.main --host 0.0.0.0 --port 8000

# 生产模式
python -m app.main
```

### 4. 访问

- API 文档：http://localhost:8000/docs（DEBUG=true 时启用）
- 核心接口：POST `/frame/run/sse`（SSE 流式响应）

## 项目结构

```
app/
├── main.py                 # 启动入口（FastAPI + uvicorn）
├── api/
│   ├── router.py           # 路由聚合
│   └── frame_api.py        # /frame/run/sse 接口定义
├── core/
│   ├── config.py           # 配置管理（pydantic-settings）
│   └── logger.py           # 日志
├── workflow/               # LangGraph 工作流
├── tool/                   # 工具集
├── db_connection_pool/     # 数据库连接池
└── intent/                 # 意图分类
```

## 接口说明

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 健康检查 |
| POST | `/frame/run/sse` | 意图流式推理（SSE） |
| GET | `/docs` | Swagger 文档（DEBUG 模式） |
