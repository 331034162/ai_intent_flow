"""
抽象意图分类器基类模块

定义所有意图分类器类必须实现的抽象接口
"""
from abc import abstractmethod
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
import asyncio
import time
from typing import AsyncGenerator, List, Dict, Any
from ..context.chat_context import ChatContext
from ..core.logger import app_logger
from ..db_connection_pool.zb_conversation_nodes_util import _default_cache as node_cache, ZbConversationNode
from ..abstract_ai import AbstractAI
from langchain_openai import ChatOpenAI
from ..agent.abstract_agent import AbstractAgent

class Config:
    """配置类，用于管理应用配置"""

    DEFAULT_CONFIDENCE_THRESHOLD = 0.5
    # 意图分类常量（数字编码）
    UNKNOWN_INTENT = "__unknown"     # 未知


class AbstractIntent(AbstractAI):
    """抽象意图分类器基类"""

    def __init__(self, node_id: str):
        """
        初始化基本属性

        Args:
            node_id: 节点ID，必填项
        """
        if not node_id:
            raise ValueError(f"{self.__class__.__name__}: node_id 是必填项")

        self.node_id: str = node_id
        # 这些属性将在异步初始化方法中设置
        self.tool_list: List[ZbConversationNode] = []
        self.node: ZbConversationNode = None
        self.llm: ChatOpenAI = None
        self.prompt_classification = ""
        self.func_desc_str = ""  # 功能描述字符串，供子类使用
        self._initialized = False
        self._init_lock = asyncio.Lock()  # 并发控制锁

    @abstractmethod
    async def _prepare_descriptions(self,context: ChatContext = None):
        """
        子类实现：准备功能描述等数据（在初始化时调用）

        用于获取构建提示词所需的异步数据
        """
        pass

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
            self.tool_list = await node_cache.get_node_list(self.node_id, "tool", is_recursive=True)
            self.node = await node_cache.get_node_by_id(self.node_id)
            self.llm = await node_cache.get_llm_by_node_id(self.node_id)

            # 调用子类方法准备描述数据
            await self._prepare_descriptions(context)

            # 调用子类方法获取提示词
            self.prompt_classification = await self._get_prompt_classification(context)

            app_logger.info(f"intent classify prompt:\n{self.prompt_classification}")
            self._initialized = True


    async def classify_intent(self, user_input: str, chat_history: List[Dict] = None, context: ChatContext = None) -> Dict[str, Any]:
        """
        使用LangChain识别用户意图（仅返回意图数字）
        :param user_input: 用户输入的字符串
        :param chat_history: 用户与AI的聊天历史列表
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

            # 解析完整响应
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

    @abstractmethod
    async def _dispatch_intent(
        self,
        intent: int,
        user_input: str,
        context: ChatContext
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        子类实现：根据意图分发处理

        Args:
            intent: 意图编码
            user_input: 用户输入
            context: 对话上下文

        Yields:
            流式输出的字典
        """
        pass

    async def process_user_input(
        self,
        user_input: str,
        context: ChatContext
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        处理用户输入并管理多轮对话（流式输出）
        :param user_input: 用户输入
        :param context: 聊天上下文
        :yield: 流式输出的字典
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

        if context.is_query_history_node_id and context.use_history:
            chat_history = await AbstractAI.get_chat_history_from_db(conversation_id, message_status=1, node_id=self.node_id, max=context.history_max_records)
            """
            ##如果是开始的入口节点则不限制 node_id，获取完整对话历史(但不能包含is_human_generated=1)用于意图识别，否则只查询跟当前节点相关的信息，强化意图识别
            if context.workflow.entry_node_id != self.node_id:
                chat_history = await AbstractAI.get_chat_history_from_db(conversation_id, message_status=1, node_id=self.node_id, max=context.history_max_records)
            else:
                chat_history = await AbstractAI.get_chat_history_from_db(conversation_id, message_status=1, node_id=None,is_human_generated=0)
            """
            context.chat_history = chat_history
        else:
            chat_history = context.chat_history

        # 第一步：进行意图识别，只获取意图数字
        # 修复：确保 chat_history 不为空时才切片
        history_for_classification = chat_history[:-1] if len(chat_history) > 1 else chat_history
        result = await self.classify_intent(user_input, history_for_classification, context)
        intent = result.get('intent', Config.UNKNOWN_INTENT)
        confidence = result.get('confidence', 0.0)

        app_logger.info(f"意图识别结果：intent={intent}, confidence={confidence}")

        # 第二步：根据意图分发处理
        if intent != Config.UNKNOWN_INTENT:
            yield self.create_stream_message(f"用户想办理{(await node_cache.get_node_by_id(intent)).node_business_range}",message_type="tool", is_last=False,is_over=False,conversation_id=conversation_id)
            # 有明确意图，调用子类分发方法
            async for item in self._dispatch_intent(intent, user_input, context):
                yield item
            return
        else:
            async for msg in self.generate_friendly_response_stream(user_input, chat_history, context, self.node):
                yield msg

    async def _dispatch_intent(
        self,
        intent: int,
        user_input: str,
        context: ChatContext
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        根据意图分发处理

        Args:
            intent: 意图编码
            user_input: 用户输入
            context: 对话上下文

        Yields:
            流式输出的字典
        """
        if intent != Config.UNKNOWN_INTENT:
            node : ZbConversationNode = await node_cache.get_node_by_id(intent)
            app_logger.info(node.node_description)
            agent:AbstractAgent = await node_cache.instantiate_node(node.node_id)
            async for item in agent.process_user_input(user_input, context):
                yield item
        else:
            yield self.create_stream_message('大模型意图识别有误，请重试', message_type="model", is_last=True, is_over=True,conversation_id=context.conversation_id)