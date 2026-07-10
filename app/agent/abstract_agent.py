"""
抽象代理（Agent）基类模块

定义所有 Agent 类必须实现的抽象接口
"""
from abc import abstractmethod
from typing import AsyncGenerator, Dict, List, Any
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
import asyncio
import time
from ..context.chat_context import ChatContext
from ..core.logger import app_logger
from ..tool.abstract_tool import AbstractTool
from ..db_connection_pool.conversation_db_helper import ConversationDBHelper
from ..db_connection_pool.zb_conversation_nodes_util import _default_cache as node_cache, ZbConversationNode
from ..abstract_ai import AbstractAI
from langchain_openai import ChatOpenAI


class Config:
    """配置类，用于管理应用配置"""
    DEFAULT_CONFIDENCE_THRESHOLD = 0.5
    # 意图分类常量 - 未识别意图的统一标识
    UNKNOWN_INTENT = "__unknown"


class AbstractAgent(AbstractAI):
    """抽象代理基类"""

    def __init__(self, node_id: str):
        """
        初始化基本属性

        Args:
            node_id: 节点ID，必填项
            prompt_classification: 意图分类提示词
        """
        if not node_id:
            raise ValueError(f"{self.__class__.__name__}: node_id 是必填项")

        self.node_id: str = node_id
        # 这些属性将在异步初始化方法中设置
        self.tool_list: List[ZbConversationNode] = []
        self.func_desc_str = ""
        self.node: ZbConversationNode = None
        self.llm: ChatOpenAI = None
        self.prompt_classification = None
        self._initialized = False
        self._init_lock = asyncio.Lock()  # 并发控制锁

    @abstractmethod
    async def _get_prompt_classification(self,context: ChatContext = None) -> str:
        """
        子类实现：获取意图分类提示词

        Returns:
            意图分类提示词
        """
        pass

    async def _ensure_initialized(self, context: ChatContext = None):
        """确保已异步初始化"""
        # 双重检查锁定模式：先快速检查
        if self._initialized:
            return

        # 使用锁保护初始化过程
        async with self._init_lock:
            # 获取锁后再次检查，防止其他协程已经初始化
            if self._initialized:
                return

            # 执行初始化
            self.tool_list = await node_cache.get_node_list(parent_node_id=self.node_id)
            self.func_desc_str = await node_cache.get_node_desc_str(self.node_id)
            self.node = await node_cache.get_node_by_id(self.node_id)
            self.llm = await node_cache.get_llm_by_node_id(self.node_id)

            # 调用子类方法获取提示词
            self.prompt_classification = await self._get_prompt_classification(context=context)

            app_logger.info(f"agent prompt:\n{self.prompt_classification}")
            self._initialized = True

    async def classify_intent(self, user_input: str, chat_history: List[Dict] = None, context: ChatContext = None) -> Dict[str, Any]:
        """
        使用LangChain识别用户意图（仅返回意图数字）
        :param user_input: 用户输入的字符串
        :param chat_history: 用户与AI的聊天历史列表，格式为 [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]
        :param context: 对话上下文（可选，用于记录token使用）
        :return: 包含意图分类结果的字典（intent为数字）
        """
        try:
            messages = [
                SystemMessage(content=self.prompt_classification)
            ]
            # 添加聊天历史（如果存在）
            if chat_history:
                for msg in chat_history:
                    if msg.get("role") == "user":
                        messages.append(HumanMessage(content=msg.get("content", "")))
                    elif msg.get("role") == "assistant":
                        messages.append(AIMessage(content=msg.get("content", "")))

            # 添加当前用户输入
            messages.append(HumanMessage(content=user_input))

            # 调用语言模型（流式）—— 优先使用 prompt 级模型覆盖
            full_response = ""
            usage_metadata = None
            start_time = time.time()
            llm = (await self.resolve_prompt_model(self.node_id, "classification_prompt")) or self.llm
            async for chunk in llm.astream(messages):
                if hasattr(chunk, 'usage_metadata') and chunk.usage_metadata:
                    usage_metadata = chunk.usage_metadata
                content = getattr(chunk, 'content', str(chunk)) if hasattr(chunk, 'content') else str(chunk)
                if content:
                    full_response += content
            latency_ms = int((time.time() - start_time) * 1000)

            # 记录token使用
            if usage_metadata and context and self.node:
                await self.log_token_usage(context, self.node, usage_metadata, latency_ms=latency_ms)

            parsed_response = self._parse_json_response(full_response)
            app_logger.info(f"意图识别结果: {parsed_response}")

            if parsed_response:
                intent = parsed_response.get("intent", Config.UNKNOWN_INTENT)
                confidence = parsed_response.get("confidence", 0.5)
                return {
                    "intent": intent,
                    "confidence": confidence,
                }
            else:
                # 如果没有解析到JSON，则返回未知意图
                return {
                    "intent": Config.UNKNOWN_INTENT,
                    "confidence": 0.0,
                }

        except Exception as e:
            app_logger.error(f"意图识别出错: {e}")
            return {
                "intent": Config.UNKNOWN_INTENT,
                "confidence": 0.0,
            }

    async def process_user_input(
        self,
        user_input: str,
        context: ChatContext
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        处理用户输入并管理多轮对话（流式输出）

        Args:
            user_input: 用户输入
            context: 对话上下文

        Yields:
            Dict[str, Any]: 流式输出的字典
        """
        # 确保已异步初始化
        await self._ensure_initialized(context=context)
        conversation_id = context.conversation_id
        
        context.run_steps += 1
        app_logger.info(f"当前执行步数：{context.run_steps}")
        if context.run_steps > context.run_steps_max:
            app_logger.info(f"执行步数超过最大允许执行步数{context.run_steps_max}次，跳过处理")
            yield self.create_stream_message("您的问题我目前还无法处理，请换一个问题吧。",message_type="model", is_last=True,is_over=True,conversation_id=conversation_id)
            return
    
        # 从数据库获取聊天历史
        if context.is_query_history_node_id and context.use_history:
            chat_history = await AbstractAI.get_chat_history_from_db(conversation_id, message_status=1, node_id=self.node_id,max=context.history_max_records)
            """
            ##如果是开始的入口节点则不限制 node_id，获取完整对话历史(但不能包含is_human_generated=1)用于意图识别，否则只查询跟当前节点相关的信息，强化意图识别
            if context.workflow.entry_node_id != self.node_id:
                chat_history = await AbstractAI.get_chat_history_from_db(conversation_id, message_status=1, node_id=self.node_id)
            else:
                chat_history = await AbstractAI.get_chat_history_from_db(conversation_id, message_status=1, node_id=None, is_human_generated=0)
            """
            context.chat_history = chat_history
        else:
            chat_history = context.chat_history

        # 第一步：进行意图识别，只获取意图数字
        result = await self.classify_intent(user_input, chat_history, context)
        intent = result.get('intent', Config.UNKNOWN_INTENT)
        confidence = result.get('confidence', 0.0)

        app_logger.info(f"意图识别结果: intent={intent}, confidence={confidence}")

        # 简化为两类：识别成功（跳转工具节点）或识别失败（生成友好回应）
        if intent != Config.UNKNOWN_INTENT:
            yield self.create_stream_message(f"用户想办理{(await node_cache.get_node_by_id(intent)).node_business_range}",message_type="tool", is_last=True,is_over=False,conversation_id=conversation_id)
            # 识别成功，跳转到对应的工具节点
            tool: AbstractTool = await node_cache.instantiate_node(node_id=intent)
            if tool:
                async for msg in tool.process_user_input(user_input, context):
                    yield msg
            else:
                app_logger.error(f"意图识别有误，但对应的工具节点不存在: intent={intent}")
                yield self.create_stream_message('大模型意图识别有误，请重试', message_type="model", is_last=True, is_over=True,conversation_id=conversation_id)
            return
        

        intent_classicfic_node_id = context.workflow.intent_classify_node_id
        if not intent_classicfic_node_id or intent_classicfic_node_id == "":
            intent_classicfic_node_id = context.workflow.entry_node_id
        ##生成友好回应
        if intent_classicfic_node_id != self.node_id:
            intent_node : AbstractAI = await node_cache.instantiate_node(intent_classicfic_node_id)
            intent_node_info = await node_cache.get_node_by_id(intent_classicfic_node_id)
            async for msg in intent_node.generate_friendly_response_stream(user_input, chat_history, context, intent_node_info):
                yield msg
        else:
            async for msg in self.generate_friendly_response_stream(user_input, chat_history, context, self.node):
                yield msg