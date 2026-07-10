"""
对话记录数据库操作工具类
用于保存和更新对话记录到数据库
"""
from typing import Any
from sqlalchemy import text
from .async_mysql_connection import get_async_pool_instance, AsyncMySQLConnection
from ..core.logger import app_logger


class ConversationDBHelper:
    """对话记录数据库操作助手"""
    
    @staticmethod
    async def save_conversation_record(
        conversation_id: str,
        conversation_name: str,
        employee_id: str,
        question: str,
        answer: str,
        model_name: str,
        model_provider: str = "zbank",
        model_url: str = None,
        model_ext_param: Any = None,
        status_description: str = "",
        node_id: str = "",
        workflow_id: str = None,
        is_human_generated: int = 0,
        message_status: int = 1,
        seq_no: str = None,
        conversation_type: int = 1,
        file_id_list: str = None,
        task_type: str = None,
        knowledge_conversation_id: str = None,
        thread_id: str = None,
        interrupt_id : str = None
    ) -> bool:
        """
        保存对话记录到数据库

        Args:
            conversation_id: 会话ID（必填）
            conversation_name: 会话名称（必填）
            employee_id: 员工ID（必填）
            question: 用户问题（必填）
            answer: AI回答（必填）
            model_name: 使用的模型名称（必填）
            model_provider: 模型提供商（可选，默认zbank）
            model_url: 模型的访问地址（可选）
            model_ext_param: 模型扩展参数（可选，JSON格式）
            status_description: 状态描述（必填）
            node_id: 节点ID（必填）
            workflow_id: 工作流ID（可选）
            is_human_generated: 是否为人类生成（可选，默认0-否，1-是）
            message_status: 消息状态（可选，默认1-成功）：0-处理中、1-成功、-1-失败
            seq_no: 对话流水号（可选，唯一标识用户的每一次对话）
            conversation_type: 会话类型（可选，默认1-模型会话，2-知识库会话）
            file_id_list: 对话用到的file_id列表（可选，用逗号分隔）
            task_type: 任务类型（可选，如：summary/report/rewrite等）
            knowledge_conversation_id: 知识库会话ID（可选）
            thread_id: checkpoint的thread_id
            interrupt_id : 中断id

        Returns:
            bool: 是否保存成功
        """
        try:
            # 必填参数校验
            required_params = {
                "conversation_id": conversation_id,
                "conversation_name": conversation_name,
                "employee_id": employee_id,
                "question": question,
                "answer": answer,
                "model_name": model_name,
                "status_description": status_description,
                "node_id": node_id
            }

            for param_name, param_value in required_params.items():
                if param_value is None or (isinstance(param_value, str) and param_value.strip() == ""):
                    app_logger.error(f"保存对话记录失败: 参数 {param_name} 不能为空")
                    return False

            db_conn = await get_async_pool_instance()
            session = await db_conn.get_session()
            
            async with session:
                async with session.begin():
                    # 查询会话是否存在
                    query = "SELECT * FROM zb_conversations WHERE conversation_id = :conversation_id"
                    result_db = AsyncMySQLConnection.all(
                        await session.execute(text(query), {"conversation_id": conversation_id})
                    )
                    
                    if not result_db or len(result_db) == 0:
                        # 如果不存在，创建新记录
                        insert_sql = """
                            INSERT INTO zb_conversations
                            (conversation_id, conversation_name, employee_id, node_id, conversation_type, knowledge_conversation_id)
                            VALUES
                            (:conversation_id, :conversation_name, :employee_id, :node_id, :conversation_type, :knowledge_conversation_id)
                        """
                        await session.execute(text(insert_sql), {
                            "conversation_id": conversation_id,
                            "conversation_name": conversation_name,
                            "employee_id": employee_id,
                            "node_id": node_id,
                            "conversation_type": conversation_type,
                            "knowledge_conversation_id": knowledge_conversation_id
                        })
                    else:
                        # 如果存在则更新会话记录
                        if knowledge_conversation_id is not None:
                            update_sql = """
                                UPDATE zb_conversations
                                SET node_id = :node_id, knowledge_conversation_id = :knowledge_conversation_id
                                WHERE conversation_id = :conversation_id
                            """
                            await session.execute(text(update_sql), {
                                "node_id": node_id,
                                "knowledge_conversation_id": knowledge_conversation_id,
                                "conversation_id": conversation_id
                            })
                        else:
                            update_sql = """
                                UPDATE zb_conversations
                                SET node_id = :node_id
                                WHERE conversation_id = :conversation_id
                            """
                            await session.execute(text(update_sql), {
                                "node_id": node_id,
                                "conversation_id": conversation_id
                            })
                    
                    # 插入消息记录
                    insert_msg_sql = """
                        INSERT INTO zb_conversation_messages
                        (conversation_id, seq_no, question, answer, message_status, model_name, model_provider, model_url, model_ext_param, status_description, node_id, workflow_id, is_human_generated, file_id_list, task_type, thread_id, interrupt_id)
                        VALUES
                        (:conversation_id, :seq_no, :question, :answer, :message_status, :model_name, :model_provider, :model_url, :model_ext_param, :status_description, :node_id, :workflow_id, :is_human_generated, :file_id_list, :task_type, :thread_id, :interrupt_id)
                    """
                    await session.execute(text(insert_msg_sql), {
                        "conversation_id": conversation_id,
                        "seq_no": seq_no,
                        "question": question,
                        "answer": answer,
                        "message_status": message_status,
                        "model_name": model_name,
                        "model_provider": model_provider,
                        "model_url": model_url,
                        "model_ext_param": model_ext_param,
                        "status_description": status_description,
                        "node_id": node_id,
                        "workflow_id": workflow_id,
                        "is_human_generated": is_human_generated,
                        "file_id_list": file_id_list,
                        "task_type": task_type,
                        "thread_id": thread_id,
                        "interrupt_id": interrupt_id
                    })
            
            app_logger.info(f"对话记录保存成功: conversation_id={conversation_id}")
            return True
            
        except Exception as e:
            app_logger.error(f"保存对话记录失败: {str(e)}")
            return False
    
    @staticmethod
    async def update_conversation_node(
        conversation_id: str,
        node_id: str
    ) -> bool:
        """
        更新会话节点
        
        Args:
            conversation_id: 会话ID
            node_id: 节点ID
            
        Returns:
            bool: 是否更新成功
        """
        try:
            db_conn = await get_async_pool_instance()
            session = await db_conn.get_session()
            
            async with session:
                async with session.begin():
                    update_sql = """
                        UPDATE zb_conversations 
                        SET node_id = :node_id 
                        WHERE conversation_id = :conversation_id
                    """
                    await session.execute(text(update_sql), {
                        "node_id": node_id,
                        "conversation_id": conversation_id
                    })
            
            app_logger.info(f"会话节点更新成功: conversation_id={conversation_id}, node_id={node_id}")
            return True
            
        except Exception as e:
            app_logger.error(f"更新会话节点失败: {str(e)}")
            return False