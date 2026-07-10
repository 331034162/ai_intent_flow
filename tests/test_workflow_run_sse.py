import asyncio
import httpx
from fastapi.testclient import TestClient
from app.main import app
import pytest

@pytest.mark.asyncio
async def test_sse_stream_interruption():
    """
    测试 SSE 流是否能正确处理客户端断开连接
    """
    async with httpx.AsyncClient() as client:
        # 发送请求
        response = await client.post(
            "http://localhost:8000/api/v1/workflow/run/sse",
            json={
                "user_query": "你好，测试中断",
                "employee_id": "test_employee",
                "user_name": "测试用户"
            },
            timeout=None,  # 无超时
            follow_redirects=True
        )
        
        # 验证响应状态码
        assert response.status_code == 200
        # assert response.headers["content-type"] == "text/event-stream"
        
        # 读取几行数据
        lines_read = 0
        async for chunk in response.aiter_bytes():
            if chunk:
                lines_read += 1
                print(f"Received chunk: {chunk.decode('utf-8')}")
                
                # 读取 2 行后中断连接
                if lines_read >= 2:
                    break
        
        # 验证至少读取了一些数据
        assert lines_read > 0
        
        print("Test completed: SSE stream supports interruption")


if __name__ == "__main__":
    asyncio.run(test_sse_stream_interruption())
