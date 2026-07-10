"""
会话数据库操作工具类
用于加载和查询 zb_conversations 表数据
"""
import traceback
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict, List
from sqlalchemy import text
from .async_mysql_connection import get_async_pool_instance, AsyncMySQLConnection
from ..core.logger import app_logger


@dataclass
class ZbConversation:
    """会话数据类"""
    id: int
    conversation_id: str
    knowledge_conversation_id: str = ""
    conversation_name: str = ""
    employee_id: str = ""
    user_name: Optional[str] = None
    is_deleted: int = 0
    node_id: str = ""
    conversation_type: int = 1  # 会话类型：1-模型会话，2-知识库会话
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @classmethod
    def from_dict(cls, data: Dict) -> 'ZbConversation':
        """从字典创建实例"""
        return cls(
            id=data.get('id', 0),
            conversation_id=data.get('conversation_id', ''),
            knowledge_conversation_id=data.get('knowledge_conversation_id', ''),
            conversation_name=data.get('conversation_name', ''),
            employee_id=data.get('employee_id', ''),
            user_name=data.get('user_name'),
            is_deleted=data.get('is_deleted', 0),
            node_id=data.get('node_id', ''),
            conversation_type=data.get('conversation_type', 1),
            created_at=data.get('created_at'),
            updated_at=data.get('updated_at')
        )


class ZbConversationUtil:
    """会话数据库操作助手"""
    
    @staticmethod
    async def load_conversations_by_employee(
        employee_id: str,
        limit: int = 20,
        is_deleted: int = 0
    ) -> List[ZbConversation]:
        """
        根据员工ID查询会话列表（按更新时间倒序）
        
        Args:
            employee_id: 员工ID
            limit: 返回条数上限，默认20
            is_deleted: 是否删除，默认为0（未删除）
            
        Returns:
            ZbConversation 列表
        """
        try:
            db_conn = await get_async_pool_instance()
            session = await db_conn.get_session()
            
            async with session:
                async with session.begin():
                    query = """
                        SELECT * FROM zb_conversations
                        WHERE employee_id = :employee_id
                        AND is_deleted = :is_deleted
                        ORDER BY updated_at DESC
                        LIMIT :limit
                    """
                    result = AsyncMySQLConnection.all(
                        await session.execute(
                            text(query),
                            {
                                "employee_id": employee_id,
                                "is_deleted": is_deleted,
                                "limit": limit
                            }
                        )
                    )
                    
                    conversations = []
                    if result:
                        for row in result:
                            conversations.append(ZbConversation.from_dict(row))
                        app_logger.info(f"成功加载会话列表: employee_id={employee_id}, count={len(conversations)}")
                    return conversations
                    
        except Exception as e:
            app_logger.error(f"加载会话列表失败: {str(e)}\n{traceback.format_exc()}")
            return []

    @staticmethod
    async def load_conversation(
        conversation_id: str,
        employee_id: str,
        is_deleted: int = 0
    ) -> Optional[ZbConversation]:
        """
        根据会话ID和员工ID获取会话信息
        
        Args:
            conversation_id: 会话ID
            employee_id: 员工ID
            is_deleted: 是否删除，默认为0（未删除）
            
        Returns:
            ZbConversation 对象，如果未找到则返回 None
        """
        try:
            db_conn = await get_async_pool_instance()
            session = await db_conn.get_session()
            
            async with session:
                async with session.begin():
                    query = """
                        SELECT * FROM zb_conversations
                        WHERE conversation_id = :conversation_id
                        AND employee_id = :employee_id
                        AND is_deleted = :is_deleted
                        LIMIT 1
                    """
                    result = AsyncMySQLConnection.all(
                        await session.execute(
                            text(query),
                            {
                                "conversation_id": conversation_id,
                                "employee_id": employee_id,
                                "is_deleted": is_deleted
                            }
                        )
                    )
                    
                    if result and len(result) > 0:
                        conversation = ZbConversation.from_dict(result[0])
                        app_logger.info(f"成功加载会话: conversation_id={conversation_id}, employee_id={employee_id}")
                        return conversation
                        
            return None
            
        except Exception as e:
            app_logger.error(f"加载会话记录失败: {str(e)}\n{traceback.format_exc()}")
            return None

    @staticmethod
    async def update_knowledge_conversation_id(
        conversation_id: str,
        knowledge_conversation_id: str
    ) -> bool:
        """
        根据会话ID更新知识库会话ID
        
        Args:
            conversation_id: 会话ID
            knowledge_conversation_id: 知识库会话ID
            
        Returns:
            更新成功返回 True，否则返回 False
        """
        try:
            db_conn = await get_async_pool_instance()
            session = await db_conn.get_session()
            
            async with session:
                async with session.begin():
                    query = """
                        UPDATE zb_conversations
                        SET knowledge_conversation_id = :knowledge_conversation_id,
                            updated_at = NOW()
                        WHERE conversation_id = :conversation_id
                    """
                    result = await session.execute(
                        text(query),
                        {
                            "conversation_id": conversation_id,
                            "knowledge_conversation_id": knowledge_conversation_id
                        }
                    )
                    
                    if result.rowcount > 0:
                        app_logger.info(f"成功更新知识库会话ID: conversation_id={conversation_id}, knowledge_conversation_id={knowledge_conversation_id}")
                        return True
                    else:
                        app_logger.warning(f"未找到会话记录，更新失败: conversation_id={conversation_id}")
                        return False
                        
        except Exception as e:
            app_logger.error(f"更新知识库会话ID失败: {str(e)}\n{traceback.format_exc()}")
            return False