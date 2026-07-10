from ..context.chat_context import ChatContext
from typing import Dict, Any, Optional
from .zb_conversation_nodes_util import ZbConversationNode
from .async_mysql_connection import get_async_pool_instance
from ..core.logger import app_logger
from datetime import datetime
from sqlalchemy import text


class ZbLogTokens:
    """大模型调用 Token 记录工具类"""

    # 默认应用编号
    DEFAULT_APP_CODE = "xiaobang"

    def __init__(self):
        pass

    @staticmethod
    async def token_usage_2_db(
        context: ChatContext,
        node: ZbConversationNode,
        usage_metadata: Dict[str, Any],
        latency_ms: int = 0,
        status: int = 1,
        error_msg: Optional[str] = None,
        remark: Optional[str] = None
    ):
        """
        记录 token 使用数据到数据库表 zb_llm_call_detail

        Args:
            context: 对话上下文，包含 user_id、conversation_id 等信息
            node: 节点信息，包含模型配置
            usage_metadata: token 使用量元数据，格式如:
                {
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "total_tokens": 150
                }
            latency_ms: 调用耗时(毫秒)，默认 0
            status: 状态，1=成功 2=失败，默认 1
            error_msg: 错误信息，默认 None
            remark: 备注，默认 None
        """
        if not usage_metadata:
            app_logger.info("usage_metadata 为空，跳过记录")
            return

        if not node:
            app_logger.warning("node 为空，跳过记录")
            return

        try:
            # 构建 INSERT SQL
            insert_sql = text("""
                INSERT INTO zb_llm_call_detail (
                    node_id, conversation_id, employee_id, user_name,
                    app_code, agent_key, llm_url, llm_using_type, llm_type,
                    llm_model_provider, llm_model_name,
                    prompt_tokens, prompt_unit_price, prompt_price,
                    completion_tokens, completion_unit_price, completion_price,
                    total_tokens, total_price, currency,
                    latency_ms, status, error_msg, remark,
                    create_time
                ) VALUES (
                    :node_id, :conversation_id, :employee_id, :user_name,
                    :app_code, :agent_key, :llm_url, :llm_using_type, :llm_type,
                    :llm_model_provider, :llm_model_name,
                    :prompt_tokens, :prompt_unit_price, :prompt_price,
                    :completion_tokens, :completion_unit_price, :completion_price,
                    :total_tokens, :total_price, :currency,
                    :latency_ms, :status, :error_msg, :remark,
                    :create_time
                )
            """)

            # 提取 token 数据
            prompt_tokens = usage_metadata.get('input_tokens', 0) or 0
            completion_tokens = usage_metadata.get('output_tokens', 0) or 0
            total_tokens = usage_metadata.get('total_tokens', 0) or 0

            # 模型类型映射: model_is_out (0=行内, 1=行外)
            llm_type = "outside" if node.model_is_out == 1 else "zbank"

            # 获取 app_code（优先从 workflow 获取，否则使用默认值）
            app_code = context.workflow.workflow_id if context.workflow else ZbLogTokens.DEFAULT_APP_CODE

            # 构建参数
            params = {
                "node_id": node.node_id or "",
                "conversation_id": context.conversation_id or "",
                "employee_id": context.user_id or "",
                "user_name": context.user_name or "",
                "app_code": app_code,
                "agent_key": "",
                "llm_url": node.model_url or "",
                "llm_using_type": "direct",  # 直连模式
                "llm_type": llm_type,
                "llm_model_provider": node.model_provider or "",
                "llm_model_name": node.model_name or "",
                "prompt_tokens": prompt_tokens,
                "prompt_unit_price": 0.0,
                "prompt_price": 0.0,
                "completion_tokens": completion_tokens,
                "completion_unit_price": 0.0,
                "completion_price": 0.0,
                "total_tokens": total_tokens,
                "total_price": 0.0,
                "currency": "RMB",
                "latency_ms": latency_ms,
                "status": status,
                "error_msg": error_msg or None,
                "remark": remark or f"app_code={app_code}, conversation_id={context.conversation_id}, node_id={node.node_id}, user_id={context.user_id}",
                "create_time": datetime.now()
            }
            # 获取数据库连接池
            db_conn = await get_async_pool_instance()
            session = await db_conn.get_session()
            async with session:
                async with session.begin():
                    await session.execute(insert_sql, params)

            app_logger.info(
                f"Token 使用记录已入库 | "
                f"conversation_id={context.conversation_id} | "
                f"node_id={node.node_id} | "
                f"model={node.model_name} | "
                f"prompt_tokens={prompt_tokens} | "
                f"completion_tokens={completion_tokens} | "
                f"total_tokens={total_tokens} | "
                f"latency_ms={latency_ms}ms"
            )

        except Exception as e:
            app_logger.error(f"Token 使用记录入库失败: {e}")
            # 即使入库失败，也打印日志信息
            log_info = (
                f"Token使用统计(入库失败) | "
                f"conversation_id={context.conversation_id} | "
                f"node_id={node.node_id} | "
                f"model_name={node.model_name} | "
                f"model_provider={node.model_provider} | "
                f"user_id={context.user_id} | "
                f"model_url={node.model_url} | "
                f"llm_type={llm_type} | "
                f"input_tokens={prompt_tokens} | "
                f"output_tokens={completion_tokens} | "
                f"total_tokens={total_tokens}"
            )
            app_logger.info(log_info)