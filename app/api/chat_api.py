"""
对话 API：会话列表查询、历史消息查询
"""
import traceback
from typing import List

from fastapi import APIRouter, Query
from pydantic import BaseModel

from ..db_connection_pool.zb_conversation_util import ZbConversationUtil, ZbConversation
from ..db_connection_pool.zb_conversation_messages_util import (
    ZbConversationMessagesUtil, ZbConversationMessage
)
from ..core.logger import app_logger

router = APIRouter()


class ConversationListItem(BaseModel):
    conversation_id: str
    conversation_name: str
    created_at: str
    updated_at: str
    node_id: str = ""


class MessageItem(BaseModel):
    message_id: int
    question: str | None = None
    answer: str | None = None
    created_at: str
    message_status: int = 0


@router.get("/api/conversations/list", summary="获取用户会话列表")
async def get_conversations_list(
    employee_id: str = Query(..., description="员工ID/用户ID"),
    limit: int = Query(20, ge=1, le=100, description="返回条数上限")
):
    """
    根据 employee_id 查询该用户的历史会话列表，按更新时间倒序排列。
    """
    try:
        conversations: List[ZbConversation] = await ZbConversationUtil.load_conversations_by_employee(
            employee_id=employee_id, limit=limit
        )
        return {
            "code": 0,
            "message": "success",
            "data": [
                ConversationListItem(
                    conversation_id=c.conversation_id,
                    conversation_name=c.conversation_name or "新会话",
                    created_at=str(c.created_at) if c.created_at else "",
                    updated_at=str(c.updated_at) if c.updated_at else "",
                    node_id=c.node_id or "",
                ) for c in conversations
            ]
        }
    except Exception as e:
        app_logger.error(f"获取会话列表失败: {str(e)}\n{traceback.format_exc()}")
        return {"code": -1, "message": f"获取失败: {str(e)}", "data": []}


@router.get("/api/workflows", summary="获取可用工作流列表")
async def get_workflows():
    """
    从 zb_ai_workflow 表读取已启用（status=1）的工作流列表，供对话页底部选择条使用。
    """
    try:
        from ..db_connection_pool.zb_ai_workflow_util import _default_cache
        workflows = await _default_cache.get_all_workflows()
        return {
            "code": 0,
            "message": "success",
            "data": [
                {
                    "workflow_id": w.workflow_id,
                    "workflow_desc": w.workflow_desc or w.workflow_id,
                } for w in workflows
            ]
        }
    except Exception as e:
        app_logger.error(f"获取工作流列表失败: {str(e)}\n{traceback.format_exc()}")
        return {"code": -1, "message": f"获取失败: {str(e)}", "data": []}


@router.get("/api/conversations/messages", summary="获取会话历史消息")
async def get_conversation_messages(
    conversation_id: str = Query(..., description="会话ID"),
    node_id: str = Query("", description="节点ID，可选"),
    limit: int = Query(50, ge=1, le=200, description="返回条数上限")
):
    """
    根据 conversation_id 查询会话历史消息，按时间正序排列。
    """
    try:
        messages: List[ZbConversationMessage] = await ZbConversationMessagesUtil.load_messages_by_conversation_and_node(
            conversation_id=conversation_id,
            node_id=node_id if node_id else None,
            message_status=1,  # 只取成功消息
            is_human_generated=0,
            limit=limit
        )
        # load_messages_by_conversation_and_node 按 created_at DESC 返回，需反转
        messages = list(reversed(messages))
        return {
            "code": 0,
            "message": "success",
            "data": [
                MessageItem(
                    message_id=m.message_id,
                    question=m.question or "",
                    answer=m.answer or "",
                    created_at=str(m.created_at) if m.created_at else "",
                    message_status=m.message_status,
                ) for m in messages
            ]
        }
    except Exception as e:
        app_logger.error(f"获取会话消息失败: {str(e)}\n{traceback.format_exc()}")
        return {"code": -1, "message": f"获取失败: {str(e)}", "data": []}
