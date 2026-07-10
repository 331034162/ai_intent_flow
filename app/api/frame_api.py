"""
独立对外 API 服务：frame_api
流式 SSE 接口：/frame/run/sse
请求格式：POST JSON Body
"""
import json
import random
from datetime import datetime

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..core.logger import get_trace_id, set_trace_id, app_logger as logger
from ..workflow.zb_xiaobang_workflow import ZBXiaoBangWorkflow
from fastapi import Request
router = APIRouter()

# ====================== JSON 请求体模型 ======================
class RunWorkflowRequest(BaseModel):
    user_id: str = Field(..., description="用户ID 必填")
    user_input: str = Field(..., description="用户输入内容 必填")
    user_name: str = Field(..., description="用户名称 必填")
    workflow_id: str = Field("xiaobang_all", description="工作流ID 默认值 xiaobang_all")
    conversation_id: str = Field("", description="会话ID，首次不传")
    seq_no: str = Field(..., description="序列号 必填")
    file_list: str = Field("", description="文件ID列表，逗号分隔")
    history_max_records: int = Field(12, description="最大历史记录数")
    conversation_type: int = Field(1, description="会话类型")
    use_history: str = Field("true", description="是否使用历史记录")
    is_user_input_interrupt_ack: bool = Field(False, description="是否为用户中断确认")

# ====================== SSE 流式接口（JSON Body） ======================
@router.post("/frame/run/sse", summary="流式执行工作流")
async def frame_run_sse(
    request: Request,
    body: RunWorkflowRequest  # 直接使用 JSON 模型
):
    # 从 body 取参
    user_id = body.user_id
    user_input = body.user_input
    user_name = body.user_name
    workflow_id = body.workflow_id
    conversation_id = body.conversation_id
    seq_no = body.seq_no
    file_list = body.file_list
    history_max_records = body.history_max_records
    conversation_type = body.conversation_type
    use_history = body.use_history.lower() == 'true' if body.use_history is not None else True
    is_user_input_interrupt_ack = body.is_user_input_interrupt_ack

    # 日志记录请求参数
    logger.info(f"[frame_api] 收到工作流请求 | "
                f"user_id={user_id}, user_name={user_name}, workflow_id={workflow_id}, "
                f"conversation_id={conversation_id}, seq_no={seq_no}, "
                f"is_interrupt_ack={is_user_input_interrupt_ack}, "
                f"use_history={use_history}, history_max_records={history_max_records}, "
                f"user_input={user_input[:200] if len(user_input) > 200 else user_input}")

    # 必填参数校验
    if not all([user_id, user_input, user_name, seq_no]):
        async def error_gen():
            yield json.dumps({
                "content": "缺少必填参数：user_id / user_input / user_name / seq_no",
                "status": "done",
                "conversation_id": conversation_id,
                "content_type": "model",
                "seq_no": seq_no
            }, ensure_ascii=False) + "\n\n"
        return StreamingResponse(error_gen(), media_type="text/plain; charset=utf-8")

    # 设置 trace_id
    if get_trace_id() == "N/A":
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S") + f"{datetime.now().microsecond // 1000:03d}"
        random_suffix = f"{random.randint(0, 999999):06d}"
        trace_id = f"{timestamp}-{random_suffix}-{seq_no}"
        set_trace_id(trace_id)
        logger.info(f"[frame_api] 生成 trace_id={trace_id}")

    return StreamingResponse(
        ZBXiaoBangWorkflow._event_generator(
            user_id, user_input, conversation_id, workflow_id, seq_no,
            file_list, history_max_records, conversation_type, user_name, use_history,
            is_user_input_interrupt_ack
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )