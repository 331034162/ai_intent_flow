from .abstract_agent import AbstractAgent
from ..context.chat_context import ChatContext
from ..core.logger import app_logger as logger
from ..db_connection_pool.zb_node_prompt_util import _default_cache


class AgentBanGong(AbstractAgent):
    """办公助手Agent"""

    def __init__(self):
        """初始化，设置node_id"""
        super().__init__(node_id="agent_bangong")

    async def _get_prompt_classification(self, context: ChatContext = None) -> str:
        """
        获取意图分类提示词

        Returns:
            意图分类提示词
        """
        logger.info(f"当前用户{context.user_id if context else 'unknown'}")

        # 从数据库加载意图分类提示词
        prompt = await _default_cache.format_prompt(
            node_id=self.node_id,
            prompt_key="classification_prompt",
            var_values={
                "tool_count": len(self.tool_list) + 1,
                "func_desc_str": self.func_desc_str
            }
        )

        return prompt

    async def _get_prompt_friendly_response(self, context: ChatContext = None) -> str:
        """
        获取友好回应提示词

        Args:
            context: 对话上下文（可选）

        Returns:
            友好回应提示词
        """
        logger.info(f"当前用户{context.user_id if context else 'unknown'}")

        # 从数据库加载友好回应提示词
        prompt = await _default_cache.format_prompt(
            node_id=self.node_id,
            prompt_key="friendly_response_prompt",
            var_values={
                "node_name": self.node.node_name if self.node else "办公助手",
                "func_desc_str": self.func_desc_str
            }
        )

        return prompt