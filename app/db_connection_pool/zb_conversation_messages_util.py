"""
会话消息数据库操作工具类
用于加载和查询 zb_conversation_messages 表数据
"""
import traceback
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List, Dict, Any
from sqlalchemy import text
from .async_mysql_connection import get_async_pool_instance, AsyncMySQLConnection
from ..core.logger import app_logger


@dataclass
class ZbConversationMessage:
    """会话消息数据类"""
    message_id: int
    conversation_id: str
    seq_no: Optional[str] = None
    question: Optional[str] = None
    answer: Optional[str] = None
    message_status: int = 0
    status_description: Optional[str] = None
    is_human_generated: Optional[int] = None
    model_name: Optional[str] = None
    model_provider: str = "zbank"
    model_url: Optional[str] = None
    extra_info: Optional[Dict[str, Any]] = None
    node_id: Optional[str] = None
    workflow_id: Optional[str] = None
    file_id_list: Optional[str] = None
    task_type: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @classmethod
    def from_dict(cls, data: Dict) -> 'ZbConversationMessage':
        """从字典创建实例"""
        return cls(
            message_id=data.get('message_id', 0),
            conversation_id=data.get('conversation_id', ''),
            seq_no=data.get('seq_no'),
            question=data.get('question'),
            answer=data.get('answer'),
            message_status=data.get('message_status', 0),
            status_description=data.get('status_description'),
            is_human_generated=data.get('is_human_generated'),
            model_name=data.get('model_name'),
            model_provider=data.get('model_provider', 'zbank'),
            model_url=data.get('model_url'),
            extra_info=data.get('extra_info'),
            node_id=data.get('node_id'),
            workflow_id=data.get('workflow_id'),
            file_id_list=data.get('file_id_list'),
            task_type=data.get('task_type'),
            created_at=data.get('created_at'),
            updated_at=data.get('updated_at')
        )


class ZbConversationMessagesUtil:
    """会话消息数据库操作助手"""
    
    @staticmethod
    async def load_messages_by_conversation_and_node(
        conversation_id: str,
        node_id: str,
        message_status: Optional[int] = None,
        is_human_generated: Optional[int] = 0,
        limit: Optional[int] = None
    ) -> List[ZbConversationMessage]:
        """
        根据会话ID和节点ID获取会话消息列表

        Args:
            conversation_id: 会话ID
            node_id: 节点ID
            message_status: 消息状态过滤（可选）：0（处理中）、1（成功）、-1（失败）
            is_human_generated: 是否为人类生成（可选）：0-否，1-是，默认0
            limit: 限制返回的记录数（可选）

        Returns:
            List[ZbConversationMessage]: 消息列表
        """
        try:
            db_conn = await get_async_pool_instance()
            session = await db_conn.get_session()
            
            # 构建查询条件
            query_parts = [
                "SELECT * FROM zb_conversation_messages",
                "WHERE conversation_id = :conversation_id"
            ]
            params = {
                "conversation_id": conversation_id
            }

            if node_id:
                query_parts.append("AND node_id = :node_id")
                params["node_id"] = node_id

            # 添加消息状态过滤
            if message_status is not None:
                query_parts.append("AND message_status = :message_status")
                params["message_status"] = message_status

            # 添加是否为人类生成过滤
            if is_human_generated is not None:
                query_parts.append("AND is_human_generated = :is_human_generated")
                params["is_human_generated"] = is_human_generated

            # 添加排序和限制
            query_parts.append("ORDER BY created_at DESC")
            if limit is not None:
                query_parts.append("LIMIT :limit")
                params["limit"] = limit
            
            query = " ".join(query_parts)
            
            async with session:
                async with session.begin():
                    result = AsyncMySQLConnection.all(
                        await session.execute(text(query), params)
                    )
                    
                    messages = [ZbConversationMessage.from_dict(row) for row in result] if result else []
                
            app_logger.info(f"成功加载 {len(messages)} 条消息记录, conversation_id={conversation_id}, node_id={node_id}, is_human_generated={is_human_generated}")
            return messages
            
        except Exception as e:
            app_logger.error(f"加载消息记录失败: {str(e)}\n{traceback.format_exc()}")
            return []

    @staticmethod
    async def load_message_by_id(message_id: int) -> Optional[ZbConversationMessage]:
        """
        根据 message_id 获取单条消息

        Args:
            message_id: 消息ID

        Returns:
            ZbConversationMessage: 消息对象，未找到返回 None
        """
        try:
            db_conn = await get_async_pool_instance()
            session = await db_conn.get_session()
            
            query = "SELECT * FROM zb_conversation_messages WHERE message_id = :message_id"
            params = {"message_id": message_id}
            
            async with session:
                async with session.begin():
                    result = AsyncMySQLConnection.one(
                        await session.execute(text(query), params)
                    )
                    
                    if result:
                        return ZbConversationMessage.from_dict(result)
                    return None
                
        except Exception as e:
            app_logger.error(f"加载消息记录失败: {str(e)}\n{traceback.format_exc()}")
            return None