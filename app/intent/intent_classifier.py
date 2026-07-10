from .abstract_intent import AbstractIntent
from ..db_connection_pool.zb_conversation_nodes_util import _default_cache as node_cache
from ..db_connection_pool.zb_node_prompt_util import _default_cache as prompt_cache
from typing import List
from ..db_connection_pool.zb_conversation_nodes_util import ZbConversationNode
from ..context.chat_context import ChatContext
from ..core.logger import app_logger as logger


class IntentClassifier(AbstractIntent):
    """多轮对话意图分类器"""

    def __init__(self):
        """初始化，设置node_id"""
        super().__init__(node_id="intent_classification")

    async def _prepare_descriptions(self, context: ChatContext):
        """准备功能描述数据"""
        self.children_list: List[ZbConversationNode] = await node_cache.get_children("intent_classification")
        desc_parts = []
        for child in self.children_list:
            child_desc = await node_cache.get_node_desc_str_by_type('tool', child.node_id)
            desc_parts.append(f"{child.node_id}: {child.node_business_range}")
            if child_desc:
                for line in child_desc.strip().split('\n'):
                    desc_parts.append(f"  - {line.strip()}")
        self.clssify_desc = "\n".join(desc_parts)

    async def _get_prompt_classification(self, context: ChatContext = None) -> str:
        """
        获取意图分类提示词

        Returns:
            意图分类提示词
        """
        logger.info(f"当前用户{context.user_id if context else 'unknown'}")

        # 从数据库加载意图分类提示词
        prompt = await prompt_cache.format_prompt(
            node_id=self.node_id,
            prompt_key="classification_prompt",
            var_values={
                "children_count": len(self.children_list) + 1,
                "classify_desc": self.clssify_desc
            }
        )

        return prompt

    async def _get_prompt_friendly_response(self, context: ChatContext = None) -> str:
        """
        获取友好回应提示词

        Returns:
            友好回应提示词
        """
        logger.info(f"当前用户{context.user_id if context else 'unknown'}")

        # 从数据库加载友好回应提示词
        prompt = await prompt_cache.format_prompt(
            node_id=self.node_id,
            prompt_key="friendly_response_prompt",
            var_values={
                "node_name": self.node.node_name if self.node else "意图识别助手",
                "classify_desc": self.clssify_desc
            }
        )

        return prompt