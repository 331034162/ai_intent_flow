import asyncio
import os

from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI


async def main():
    model = ChatOpenAI(
        model="deepseek-v4-pro",
        base_url="https://api.deepseek.com",
        api_key=os.getenv("DEEPSEEK_API_KEY", "your-api-key-here"),
        extra_body={"thinking": {"type": "disabled"}},
    )

    client = MultiServerMCPClient({
        "all_tools": {"transport": "streamable_http", "url": "http://localhost:8000/mcp"}
    })
    all_tools = await client.get_tools()
    print(f"Loaded tools: {[t.name for t in all_tools]}")

    # 手动搜索 math 工具
    search_tool = next(t for t in all_tools if t.name == "search_tools")
    math_result = await search_tool.ainvoke({"pattern": "add|multiply"})
    print(f"Math tools found: {math_result}")

    # 手动搜索 weather 工具
    weather_result = await search_tool.ainvoke({"pattern": "weather"})
    print(f"Weather tools found: {weather_result}")


    # Agent 使用所有工具
    agent = create_agent(model, all_tools)

    math_response = await agent.ainvoke(
        {"messages": [{"role": "user", "content": "what's (3 + 5) x 12?"}]}
    )
    weather_response = await agent.ainvoke(
        {"messages": [{"role": "user", "content": "what is the weather in nyc?"}]}
    )
    print(f"Math: {math_response['messages'][-1].content}")
    print(f"Weather: {weather_response['messages'][-1].content}")

if __name__ == "__main__":
    asyncio.run(main())
