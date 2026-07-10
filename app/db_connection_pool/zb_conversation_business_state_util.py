"""
会话业务状态数据库操作工具类
用于管理 zb_conversation_business_state 表数据

核心用途：跨轮对话保持同一个 thread_id，使 LangGraph 的状态（如查询缓存）在多轮对话中不丢失。

工作流程：
1. 用户发起业务对话 → 查询是否有 processing 状态的记录
2. 有 → 复用该 thread_id（延续上下文状态）
3. 无 → 生成新 thread_id 并写入记录
4. 业务完成（如预订成功）→ 更新状态为 completed
"""
import traceback
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import text

from .async_mysql_connection import get_async_pool_instance, AsyncMySQLConnection
from ..core.logger import app_logger


# ---------- 业务状态常量 ----------
BUSINESS_STATE_PROCESSING = "processing"   # 处理中
BUSINESS_STATE_COMPLETED = "completed"     # 已完成


@dataclass
class ZbConversationBusinessState:
    """会话业务状态数据类"""
    id: int = 0
    conversation_id: str = ""
    node_id: str = ""
    thread_id: str = ""
    business_state: str = BUSINESS_STATE_PROCESSING
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @classmethod
    def from_dict(cls, data: dict) -> "ZbConversationBusinessState":
        return cls(
            id=data.get("id", 0),
            conversation_id=data.get("conversation_id", ""),
            node_id=data.get("node_id", ""),
            thread_id=data.get("thread_id", ""),
            business_state=data.get("business_state", BUSINESS_STATE_PROCESSING),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )


class ZbConversationBusinessStateUtil:
    """会话业务状态数据库操作助手"""

    @staticmethod
    async def get_processing_thread_id(
        conversation_id: str,
        node_id: str,
    ) -> Optional[str]:
        """
        获取当前会话+节点下处于 processing 状态的 thread_id。

        Args:
            conversation_id: 会话ID
            node_id: 节点ID

        Returns:
            thread_id 字符串，没有则返回 None
        """
        try:
            db_conn = await get_async_pool_instance()
            session = await db_conn.get_session()

            query = (
                "SELECT thread_id FROM zb_conversation_business_state "
                "WHERE conversation_id = :conversation_id "
                "AND node_id = :node_id "
                "AND business_state = :business_state "
                "ORDER BY created_at DESC LIMIT 1"
            )
            params = {
                "conversation_id": conversation_id,
                "node_id": node_id,
                "business_state": BUSINESS_STATE_PROCESSING,
            }

            async with session:
                async with session.begin():
                    result = AsyncMySQLConnection.one(
                        await session.execute(text(query), params)
                    )

            if result:
                app_logger.info(
                    f"[业务状态] 找到 processing 记录, conversation_id={conversation_id}, "
                    f"node_id={node_id}, thread_id={result['thread_id']}"
                )
                return result["thread_id"]
            return None

        except Exception as e:
            app_logger.error(f"[业务状态] 查询失败: {str(e)}\n{traceback.format_exc()}")
            return None

    @staticmethod
    async def create_record(
        conversation_id: str,
        node_id: str,
        thread_id: str,
    ) -> bool:
        """
        创建一条新的业务状态记录（状态为 processing）。

        Args:
            conversation_id: 会话ID
            node_id: 节点ID
            thread_id: LangGraph 线程ID

        Returns:
            是否创建成功
        """
        try:
            db_conn = await get_async_pool_instance()
            session = await db_conn.get_session()

            query = (
                "INSERT INTO zb_conversation_business_state "
                "(conversation_id, node_id, thread_id, business_state) "
                "VALUES (:conversation_id, :node_id, :thread_id, :business_state)"
            )
            params = {
                "conversation_id": conversation_id,
                "node_id": node_id,
                "thread_id": thread_id,
                "business_state": BUSINESS_STATE_PROCESSING,
            }

            async with session:
                async with session.begin():
                    await session.execute(text(query), params)

            app_logger.info(
                f"[业务状态] 创建记录, conversation_id={conversation_id}, "
                f"node_id={node_id}, thread_id={thread_id}"
            )
            return True

        except Exception as e:
            app_logger.error(f"[业务状态] 创建记录失败: {str(e)}\n{traceback.format_exc()}")
            return False

    @staticmethod
    async def mark_completed(
        conversation_id: str,
        node_id: str,
        thread_id: str,
    ) -> bool:
        """
        将指定的业务状态记录标记为 completed。

        Args:
            conversation_id: 会话ID
            node_id: 节点ID
            thread_id: LangGraph 线程ID

        Returns:
            是否更新成功
        """
        try:
            db_conn = await get_async_pool_instance()
            session = await db_conn.get_session()

            query = (
                "UPDATE zb_conversation_business_state "
                "SET business_state = :business_state "
                "WHERE conversation_id = :conversation_id "
                "AND node_id = :node_id "
                "AND thread_id = :thread_id "
                "AND business_state = :current_state"
            )
            params = {
                "business_state": BUSINESS_STATE_COMPLETED,
                "conversation_id": conversation_id,
                "node_id": node_id,
                "thread_id": thread_id,
                "current_state": BUSINESS_STATE_PROCESSING,
            }

            async with session:
                async with session.begin():
                    result = await session.execute(text(query), params)
                    affected = result.rowcount

            app_logger.info(
                f"[业务状态] 标记完成, conversation_id={conversation_id}, "
                f"node_id={node_id}, thread_id={thread_id}, affected={affected}"
            )
            return affected > 0

        except Exception as e:
            app_logger.error(f"[业务状态] 标记完成失败: {str(e)}\n{traceback.format_exc()}")
            return False

    @staticmethod
    async def get_thread_ids(
        conversation_id: str,
        node_id: str,
        business_state: str | None = None,
    ) -> list[str]:
        """
        获取指定会话+节点下的 thread_id 列表。

        Args:
            conversation_id: 会话ID
            node_id: 节点ID
            business_state: 业务状态过滤（可选），不传则返回所有状态

        Returns:
            thread_id 列表，按创建时间倒序
        """
        try:
            db_conn = await get_async_pool_instance()
            session = await db_conn.get_session()

            query = (
                "SELECT thread_id FROM zb_conversation_business_state "
                "WHERE conversation_id = :conversation_id "
                "AND node_id = :node_id "
            )
            params = {
                "conversation_id": conversation_id,
                "node_id": node_id,
            }
            if business_state:
                query += "AND business_state = :business_state "
                params["business_state"] = business_state

            query += "ORDER BY created_at DESC"

            async with session:
                async with session.begin():
                    result = await session.execute(text(query), params)

            rows = AsyncMySQLConnection.all(result)
            thread_ids = [row["thread_id"] for row in rows] if rows else []

            app_logger.info(
                f"[业务状态] 查询 thread_ids, conversation_id={conversation_id}, "
                f"node_id={node_id}, state={business_state}, count={len(thread_ids)}"
            )
            return thread_ids

        except Exception as e:
            app_logger.error(f"[业务状态] 查询 thread_ids 失败: {str(e)}\n{traceback.format_exc()}")
            return []

    @staticmethod
    async def get_or_create_thread_id(
        conversation_id: str,
        node_id: str,
    ) -> str:
        """
        获取当前 processing 状态的 thread_id，没有则生成新的并写入。

        这是主要入口方法，用于替代每次生成新 thread_id 的逻辑。

        Args:
            conversation_id: 会话ID
            node_id: 节点ID

        Returns:
            可用的 thread_id
        """
        import uuid

        # 1. 先查是否有 processing 的记录
        existing_thread_id = await ZbConversationBusinessStateUtil.get_processing_thread_id(
            conversation_id, node_id
        )
        if existing_thread_id:
            return existing_thread_id

        # 2. 没有，生成新的
        new_thread_id = uuid.uuid4().hex

        # 3. 写入数据库
        await ZbConversationBusinessStateUtil.create_record(
            conversation_id, node_id, new_thread_id
        )

        return new_thread_id