# MCP 客户端使用指南

## 📖 概述

本目录包含了 Model Context Protocol (MCP) 客户端的完整示例，展示了如何连接和使用 MCP 服务器提供的工具。

## 📁 文件说明

- **mcp_client_example.py** - 完整的MCP客户端示例，包含6个不同场景
- **mcp_client_quickstart.py** - 简化版快速入门示例
- **langchain_mcp_client_test.py** - 原有的测试文件
- **fastmcp_http_weather_server.py** - HTTP传输方式的MCP服务器示例
- **fastmcp_stdio_math_server.py** - STDIO传输方式的MCP服务器示例

## 🚀 快速开始

### 1. 确保依赖已安装

项目已包含所需依赖：
```bash
pip install langchain-mcp-adapters==0.2.2
```

### 2. 启动MCP服务器

在终端1中启动HTTP MCP服务器：
```bash
python tests/fastmcp_http_weather_server.py
```

服务器将在 `http://localhost:8000/mcp` 上运行。

### 3. 运行客户端示例

#### 方式A：快速入门（推荐新手）

在终端2中运行：
```bash
python tests/mcp_client_quickstart.py
```

#### 方式B：完整示例（学习所有功能）

在终端2中运行：
```bash
python tests/mcp_client_example.py
```

## 📋 示例功能

### mcp_client_example.py 包含以下示例：

1. **示例1: 基础连接** - 连接到MCP服务器并列出所有可用工具
2. **示例2: 工具搜索** - 使用 search_tools 查找特定工具
3. **示例3: 直接调用** - 不通过Agent，直接调用MCP工具
4. **示例4: Agent集成** - 创建智能Agent自动选择和使用工具
5. **示例5: 自定义配置** - 演示不同类型的MCP服务器连接配置
6. **示例6: 错误处理** - 展示如何处理常见的连接错误

### mcp_client_quickstart.py 包含：

- 简化的5步流程：连接 → 加载工具 → 直接调用 → 创建Agent → 提问

## 🔧 支持的传输方式

### 1. Streamable HTTP（推荐用于生产环境）

```python
client = MultiServerMCPClient({
    "my_server": {
        "transport": "streamable_http",
        "url": "http://localhost:8000/mcp"
    }
})
```

**优点：**
- 支持远程连接
- 可以添加认证头
- 适合微服务架构

### 2. STDIO（适合本地开发）

```python
client = MultiServerMCPClient({
    "my_server": {
        "transport": "stdio",
        "command": "python",
        "args": ["path/to/server.py"]
    }
})
```

**优点：**
- 无需额外端口
- 进程生命周期管理简单
- 适合嵌入式场景

### 3. SSE (Server-Sent Events)

```python
client = MultiServerMCPClient({
    "my_server": {
        "transport": "sse",
        "url": "http://localhost:8001/sse"
    }
})
```

## 💡 使用场景

### 场景1：直接使用工具

```python
from langchain_mcp_adapters.client import MultiServerMCPClient

client = MultiServerMCPClient({
    "server": {"transport": "streamable_http", "url": "http://localhost:8000/mcp"}
})

tools = await client.get_tools()
add_tool = next(t for t in tools if t.name == "add")
result = await add_tool.ainvoke({"a": 5, "b": 3})
print(result)  # 输出: 8
```

### 场景2：与LangChain Agent集成

```python
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI

model = ChatOpenAI(model="gpt-4", api_key="your-key")
agent = create_agent(model, tools)

response = await agent.ainvoke({
    "messages": [{"role": "user", "content": "计算 10 + 20"}]
})
```

### 场景3：多服务器连接

```python
client = MultiServerMCPClient({
    "math_server": {
        "transport": "stdio",
        "command": "python",
        "args": ["math_server.py"]
    },
    "weather_server": {
        "transport": "streamable_http",
        "url": "http://localhost:8000/mcp"
    }
})

# 获取所有服务器的工具
all_tools = await client.get_tools()
```

## ⚠️ 常见问题

### Q1: 连接失败怎么办？

**检查清单：**
1. MCP服务器是否已启动？
2. URL/端口是否正确？
3. 防火墙是否阻止了连接？
4. 查看服务器日志确认状态

### Q2: 工具未找到？

**解决方案：**
1. 确认服务器提供了该工具
2. 检查工具名称拼写
3. 使用 `search_tools` 工具搜索可用工具
4. 查看服务器端的工具注册代码

### Q3: 如何调试？

**调试技巧：**
```python
# 打印所有可用工具
tools = await client.get_tools()
for tool in tools:
    print(f"{tool.name}: {tool.description}")

# 启用详细日志
import logging
logging.basicConfig(level=logging.DEBUG)
```

## 📚 相关资源

- [MCP 官方文档](https://modelcontextprotocol.io/)
- [langchain-mcp-adapters GitHub](https://github.com/langchain-ai/langchain-mcp-adapters)
- [FastMCP 文档](https://github.com/jlowin/fastmcp)

## 🎯 下一步

1. 运行示例代码熟悉基本用法
2. 创建自己的MCP服务器
3. 将MCP工具集成到你的应用中
4. 探索更多高级功能（认证、流式响应等）

---

**祝你使用愉快！** 🎉
