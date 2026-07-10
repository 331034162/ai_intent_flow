"""
MCP (Model Context Protocol) 客户端示例

本示例展示了如何使用 langchain-mcp-adapters 连接和使用 MCP 服务器提供的工具。

支持的传输方式:
1. STDIO - 标准输入输出（适合本地进程）
2. Streamable HTTP - HTTP流式传输（适合远程服务）

使用前准备:
1. 启动MCP服务器（参考 fastmcp_stdio_math_server.py 或 fastmcp_http_weather_server.py）
2. 运行本示例脚本

使用方法:
    python tests/mcp_client_example.py
"""

import asyncio
import os
from typing import List

from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI


# ==================== 配置区域 ====================

# OpenAI API 配置（可根据实际情况修改）
LLM_CONFIG = {
    "model": "deepseek-v4-pro",
    "base_url": "https://api.deepseek.com",
    "api_key": os.getenv("DEEPSEEK_API_KEY", "your-api-key-here"),
    "extra_body": {"thinking": {"type": "disabled"}},
}

# MCP 服务器配置
MCP_SERVERS = {
    # HTTP 服务器示例（需要先启动 fastmcp_http_weather_server.py）
    "http_server": {
        "transport": "streamable_http",
        "url": "http://localhost:8000/mcp"
    },
    
    # STDIO 服务器示例（需要先启动 fastmcp_stdio_math_server.py）
    # "stdio_server": {
    #     "transport": "stdio",
    #     "command": "python",
    #     "args": ["tests/fastmcp_stdio_math_server.py"]
    # }
}


# ==================== 基础示例 ====================

async def example_1_basic_connection():
    """
    示例1: 基础连接 - 连接到MCP服务器并列出所有可用工具
    """
    print("\n" + "="*60)
    print("示例1: 基础连接 - 列出所有可用工具")
    print("="*60)
    
    try:
        # 创建多服务器客户端
        client = MultiServerMCPClient(MCP_SERVERS)
        
        # 获取所有工具
        all_tools = await client.get_tools()
        
        print(f"\n✅ 成功连接到 {len(MCP_SERVERS)} 个MCP服务器")
        print(f"📦 加载的工具数量: {len(all_tools)}")
        print(f"\n工具列表:")
        for i, tool in enumerate(all_tools, 1):
            print(f"  {i}. {tool.name}: {tool.description}")
        
        return all_tools
        
    except Exception as e:
        print(f"❌ 连接失败: {e}")
        print(f"💡 提示: 请确保MCP服务器已启动")
        return []


async def example_2_tool_search(all_tools: List):
    """
    示例2: 工具搜索 - 使用 search_tools 查找特定工具
    """
    print("\n" + "="*60)
    print("示例2: 工具搜索 - 查找数学和天气工具")
    print("="*60)
    
    if not all_tools:
        print("⚠️ 没有可用的工具，跳过此示例")
        return
    
    try:
        # 查找搜索工具
        search_tool = next((t for t in all_tools if t.name == "search_tools"), None)
        
        if search_tool:
            print("\n🔍 搜索数学相关工具...")
            math_result = await search_tool.ainvoke({"pattern": "add|multiply"})
            print(f"   结果: {math_result}")
            
            print("\n🔍 搜索天气相关工具...")
            weather_result = await search_tool.ainvoke({"pattern": "weather"})
            print(f"   结果: {weather_result}")
        else:
            print("⚠️ 未找到 search_tools 工具")
            
    except Exception as e:
        print(f"❌ 搜索失败: {e}")


async def example_3_direct_tool_call(all_tools: List):
    """
    示例3: 直接调用工具 - 不通过Agent，直接调用MCP工具
    """
    print("\n" + "="*60)
    print("示例3: 直接调用工具 - 执行加法运算")
    print("="*60)
    
    if not all_tools:
        print("⚠️ 没有可用的工具，跳过此示例")
        return
    
    try:
        # 查找 add 工具
        add_tool = next((t for t in all_tools if t.name == "add"), None)
        
        if add_tool:
            print("\n➕ 调用 add(3, 5)...")
            result = await add_tool.ainvoke({"a": 3, "b": 5})
            print(f"   结果: 3 + 5 = {result}")
        else:
            print("⚠️ 未找到 add 工具")
            
    except Exception as e:
        print(f"❌ 调用失败: {e}")


async def example_4_agent_with_tools(all_tools: List):
    """
    示例4: Agent使用工具 - 创建智能Agent自动选择工具
    """
    print("\n" + "="*60)
    print("示例4: Agent使用工具 - 智能问答")
    print("="*60)
    
    if not all_tools:
        print("⚠️ 没有可用的工具，跳过此示例")
        return
    
    try:
        # 初始化LLM
        model = ChatOpenAI(**LLM_CONFIG)
        
        # 创建Agent
        agent = create_agent(model, all_tools)
        
        # 测试问题1: 数学计算
        print("\n🤖 问题1: 计算 (3 + 5) × 12")
        math_response = await agent.ainvoke({
            "messages": [{"role": "user", "content": "what's (3 + 5) x 12?"}]
        })
        print(f"   回答: {math_response['messages'][-1].content}")
        
        # 测试问题2: 天气查询
        print("\n🤖 问题2: 纽约的天气如何？")
        weather_response = await agent.ainvoke({
            "messages": [{"role": "user", "content": "what is the weather in nyc?"}]
        })
        print(f"   回答: {weather_response['messages'][-1].content}")
        
    except Exception as e:
        print(f"❌ Agent执行失败: {e}")


async def example_5_custom_server_connection():
    """
    示例5: 自定义服务器连接 - 演示如何连接不同类型的MCP服务器
    """
    print("\n" + "="*60)
    print("示例5: 自定义服务器连接配置")
    print("="*60)
    
    # 不同的服务器配置示例
    custom_configs = {
        # HTTP流式传输
        "http_streamable": {
            "transport": "streamable_http",
            "url": "http://localhost:8000/mcp",
            "headers": {"Authorization": "Bearer your-token"}  # 可选：添加认证头
        },
        
        # STDIO本地进程
        "stdio_local": {
            "transport": "stdio",
            "command": "python",
            "args": ["path/to/your/server.py"],
            "env": {"KEY": "value"}  # 可选：环境变量
        },
        
        # SSE (Server-Sent Events)
        "sse_server": {
            "transport": "sse",
            "url": "http://localhost:8001/sse"
        }
    }
    
    print("\n📋 支持的MCP服务器配置类型:")
    for name, config in custom_configs.items():
        print(f"\n  • {name}:")
        for key, value in config.items():
            print(f"      {key}: {value}")
    
    print("\n💡 提示: 根据实际服务器类型选择合适的配置")


async def example_6_error_handling():
    """
    示例6: 错误处理 - 展示如何处理常见的MCP连接错误
    """
    print("\n" + "="*60)
    print("示例6: 错误处理最佳实践")
    print("="*60)
    
    # 模拟错误的服务器配置
    bad_config = {
        "invalid_server": {
            "transport": "streamable_http",
            "url": "http://localhost:9999/mcp"  # 不存在的端口
        }
    }
    
    try:
        print("\n🔄 尝试连接到不存在的服务器...")
        client = MultiServerMCPClient(bad_config)
        tools = await client.get_tools()
        print(f"✅ 意外成功: {tools}")
        
    except ConnectionError as e:
        print(f"❌ 连接错误: {e}")
        print("💡 解决方案: 检查服务器是否启动，URL是否正确")
        
    except TimeoutError as e:
        print(f"❌ 超时错误: {e}")
        print("💡 解决方案: 增加超时时间或检查网络")
        
    except Exception as e:
        print(f"❌ 未知错误: {type(e).__name__}: {e}")
        print("💡 解决方案: 查看详细错误信息并排查")


# ==================== 主函数 ====================

async def main():
    """
    主函数 - 运行所有示例
    """
    print("\n" + "🚀"*30)
    print("MCP 客户端完整示例")
    print("🚀"*30)
    
    # 运行所有示例
    all_tools = await example_1_basic_connection()
    await example_2_tool_search(all_tools)
    await example_3_direct_tool_call(all_tools)
    await example_4_agent_with_tools(all_tools)
    await example_5_custom_server_connection()
    await example_6_error_handling()
    
    print("\n" + "="*60)
    print("✅ 所有示例执行完毕")
    print("="*60 + "\n")


if __name__ == "__main__":
    # 运行主函数
    asyncio.run(main())
