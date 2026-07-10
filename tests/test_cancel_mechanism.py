"""
测试取消机制的脚本

测试场景：
1. 正常流式返回（无取消）
2. 客户端主动断开（模拟用户停止）
3. 网络中断（模拟连接中断）
"""

import asyncio
import aiohttp
import json
from typing import Optional


async def test_normal_stream():
    """测试正常的流式返回（无取消）"""
    print("\n" + "="*50)
    print("测试 1: 正常流式返回（无取消）")
    print("="*50)

    url = "http://localhost:8000/api/v1/workflow/run/sse"
    payload = {
        "user_query": "你好",
        "employee_id": "test_001",
        "user_name": "test_user",
        "conversation_id": "test_conversation_001",
        "app_code": "XIAOBANG",
        "conversation_type": "model"
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as response:
                if response.status == 200:
                    print("✓ 连接成功")
                    async for line in response.content:
                        line_text = line.decode('utf-8').strip()
                        if line_text.startswith('data: '):
                            data = json.loads(line_text[6:])
                            print(f"收到数据: {data.get('content', '')[:50]}...")

                            if data.get('status') == 'done':
                                print("✓ 流式返回完成")
                                break
                else:
                    print(f"✗ 连接失败: {response.status}")
    except Exception as e:
        print(f"✗ 测试失败: {e}")


async def test_client_disconnect():
    """测试客户端主动断开"""
    print("\n" + "="*50)
    print("测试 2: 客户端主动断开（模拟用户停止）")
    print("="*50)

    url = "http://localhost:8000/api/v1/workflow/run/sse"
    payload = {
        "user_query": "帮我写一首关于春天的诗，要求包含至少10个自然段",
        "employee_id": "test_002",
        "user_name": "test_user",
        "conversation_id": "test_conversation_002",
        "app_code": "XIAOBANG",
        "conversation_type": "model"
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as response:
                if response.status == 200:
                    print("✓ 连接成功")
                    chunk_count = 0
                    max_chunks = 3  # 只接收3个chunk后就断开

                    async for line in response.content:
                        line_text = line.decode('utf-8').strip()
                        if line_text.startswith('data: '):
                            data = json.loads(line_text[6:])
                            chunk_count += 1
                            print(f"收到数据块 {chunk_count}: {data.get('content', '')[:50]}...")

                            if chunk_count >= max_chunks:
                                print(f"✓ 模拟客户端在第 {max_chunks} 个数据块后主动断开")
                                # 主动关闭连接
                                break

                    print("✓ 客户端已断开连接")
                    print("✓ 检查服务端日志，确认LLM调用是否被取消")
                else:
                    print(f"✗ 连接失败: {response.status}")
    except Exception as e:
        print(f"✗ 测试失败: {e}")


async def test_network_timeout():
    """测试网络超时"""
    print("\n" + "="*50)
    print("测试 3: 网络超时（模拟连接中断）")
    print("="*50)

    url = "http://localhost:8000/api/v1/workflow/run/sse"
    payload = {
        "user_query": "帮我分析一下人工智能的发展历程，从1950年到2024年",
        "employee_id": "test_003",
        "user_name": "test_user",
        "conversation_id": "test_conversation_003",
        "app_code": "XIAOBANG",
        "conversation_type": "model"
    }

    try:
        # 设置较短的超时时间
        timeout = aiohttp.ClientTimeout(total=2)  # 2秒后超时

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload) as response:
                if response.status == 200:
                    print("✓ 连接成功")
                    chunk_count = 0

                    async for line in response.content:
                        line_text = line.decode('utf-8').strip()
                        if line_text.startswith('data: '):
                            data = json.loads(line_text[6:])
                            chunk_count += 1
                            print(f"收到数据块 {chunk_count}: {data.get('content', '')[:50]}...")

                else:
                    print(f"✗ 连接失败: {response.status}")
    except asyncio.TimeoutError:
        print("✓ 连接超时（模拟网络中断）")
        print("✓ 检查服务端日志，确认LLM调用是否被取消")
    except Exception as e:
        print(f"异常: {e}")


async def run_all_tests():
    """运行所有测试"""
    print("\n" + "="*70)
    print("开始测试取消机制")
    print("="*70)
    print("\n提示：请同时观察服务端日志，确认以下内容：")
    print("1. 取消时是否输出 'Request cancelled' 日志")
    print("2. LLM调用是否被中断")
    print("3. 是否出现 'Workflow execution cancelled' 日志")
    print("\n按回车键开始测试...")
    input()

    await test_normal_stream()
    print("\n等待3秒...")
    await asyncio.sleep(3)

    await test_client_disconnect()
    print("\n等待3秒...")
    await asyncio.sleep(3)

    await test_network_timeout()

    print("\n" + "="*70)
    print("所有测试完成")
    print("="*70)
    print("\n请检查服务端日志，确认：")
    print("✓ 客户端断开时，LLM调用是否被及时取消")
    print("✓ 是否输出了 'Request cancelled' 和 'Workflow execution cancelled' 日志")
    print("✓ 资源是否被正确释放")


if __name__ == "__main__":
    print("""
取消机制测试工具

此工具将测试以下场景：
1. 正常流式返回（无取消）
2. 客户端主动断开（模拟用户停止）
3. 网络超时（模拟连接中断）

请确保：
1. 服务端已启动（python -m app.main）
2. 服务端地址为 http://localhost:8000
3. 已安装测试依赖：pip install aiohttp
    """)

    asyncio.run(run_all_tests())
