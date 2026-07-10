"""
MCP 客户端快速入门示例

这是一个简化的MCP客户端示例，适合快速上手使用。

使用前准备:
1. 在终端1启动MCP服务器: python tests/fastmcp_http_weather_server.py
2. 在终端2运行本脚本: python tests/mcp_client_quickstart.py
"""

import asyncio
import os

from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI


async def main():
    print("🚀 MCP 客户端快速入门\n")
    
    # 1️⃣ 配置MCP服务器
    print("📡 步骤1: 连接到MCP服务器...")
    client = MultiServerMCPClient({
        "my_server": {
            "transport": "streamable_http",
            "url": "http://localhost:8000/mcp"
        }
    })
    
    # 2️⃣ 获取所有可用工具
    print("🔧 步骤2: 加载工具...")
    tools = await client.get_tools()
    print(f"✅ 成功加载 {len(tools)} 个工具:")
    for tool in tools:
        print(f"   - {tool.name}: {tool.description}")
    
    # 3️⃣ 直接调用工具（可选）
    print("\n🎯 步骤3: 直接调用工具示例...")
    add_tool = next((t for t in tools if t.name == "add"), None)
    if add_tool:
        result = await add_tool.ainvoke({"a": 10, "b": 20})
        print(f"   10 + 20 = {result}")
    
    # 4️⃣ 创建Agent并使用工具
    print("\n🤖 步骤4: 创建智能Agent...")
    model = ChatOpenAI(
        model="deepseek-v4-pro",
        base_url="https://api.deepseek.com",
        api_key=os.getenv("DEEPSEEK_API_KEY", "your-api-key-here"),
        extra_body={"thinking": {"type": "disabled"}},
    )
    
    agent = create_agent(model, tools)
    
    # 5️⃣ 向Agent提问
    print("\n💬 步骤5: 向Agent提问...")
    questions = [
        "what's 7 + 8?",
        "what is the weather in Beijing?",
    ]
    
    for question in questions:
        print(f"\n   问题: {question}")
        response = await agent.ainvoke({
            "messages": [{"role": "user", "content": question}]
        })
        print(f"   回答: {response['messages'][-1].content}")
    
    print("\n✅ 完成！")


if __name__ == "__main__":
    asyncio.run(main())
