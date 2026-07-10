from langchain.agents.middleware import wrap_tool_call
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.errors import GraphInterrupt
from ...core.logger import app_logger

@wrap_tool_call
def sync_tool_call_aware(request: ToolCallRequest, handler):
    """返回正确的ToolMessage格式，避免协议错误。"""
    try:
        if request.tool_call["id"]:  # 兼容tool_call_id
            tool_call_id = request.tool_call["id"]
        else:
            tool_call_id = request.runtime.tool_call_id
        app_logger.info(f"工具调用: {request.tool_call['name']}, tool_call_id: {tool_call_id}")
        result = handler(request)
        return result  # 正常ToolMessage
    except GraphInterrupt as e:
        raise e
    except Exception as e:
        if isinstance(e,GraphInterrupt) :
            pass
        else:
            # 返回格式正确的ToolMessage！
            msg = f"❌ 工具{request.tool_call['name']}失败: {str(e)}。请重试。"
            app_logger.error(msg)
            if request.tool_call["id"]:  # 兼容tool_call_id
                tool_call_id = request.tool_call["id"]
            else:
                tool_call_id = request.runtime.tool_call_id
            return ToolMessage(
                content=msg,
                tool_call_id=tool_call_id,  # 关键：匹配tool_call_id！
            )
@wrap_tool_call
async def async_tool_call_aware(request: ToolCallRequest, handler):
    """返回正确的ToolMessage格式，避免协议错误。"""
    try:
        if request.tool_call["id"]:  # 兼容tool_call_id
            tool_call_id = request.tool_call["id"]
        else:
            tool_call_id = request.runtime.tool_call_id
        app_logger.info(f"工具调用: {request.tool_call['name']}, tool_call_id: {tool_call_id}")
        result = await handler(request)
        return result  # 正常ToolMessage
    except GraphInterrupt as e:
        raise e
    except Exception as e:
        if isinstance(e,GraphInterrupt) :
            pass
        else:
            # 返回格式正确的ToolMessage！
            msg = f"❌ 工具{request.tool_call['name']}失败: {str(e)}。请重试。"
            app_logger.error(msg)
            if request.tool_call["id"]:  # 兼容tool_call_id
                tool_call_id = request.tool_call["id"]
            else:
                tool_call_id = request.runtime.tool_call_id
            return ToolMessage(
                content=msg,
                tool_call_id=tool_call_id,  # 关键：匹配tool_call_id！
            )