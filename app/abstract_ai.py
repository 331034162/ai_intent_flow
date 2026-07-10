"""
抽象AI基类模块

定义所有AI处理类必须实现的抽象接口
"""
from abc import ABC, abstractmethod
from typing import AsyncGenerator, Dict, Any, List, Literal
from .context.chat_context import ChatContext
import time

from .db_connection_pool.zb_conversation_nodes_util import ZbConversationNode
from .db_connection_pool.zb_conversation_messages_util import ZbConversationMessagesUtil
from .db_connection_pool.conversation_db_helper import ConversationDBHelper
from .db_connection_pool.zb_node_prompt_util import NodePromptCache
from .db_connection_pool.zb_node_model_util import ZbNodeModelUtil
from .core.logger import app_logger
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
import json
from .db_connection_pool.zb_log_tokens import ZbLogTokens
from langgraph.checkpoint.base import BaseCheckpointSaver
from .db_connection_pool.zb_conversation_business_state_util import ZbConversationBusinessStateUtil
class AbstractAI(ABC):
    """抽象AI基类"""

    # 类级别变量，标记 checkpointer 是否已初始化，默认已经初始化过
    _checkpointer_initialized = True

    def __init__(self):
        """初始化基本属性"""
        pass

    @abstractmethod
    async def _get_prompt_friendly_response(self,context: ChatContext = None) -> str:
        """
        子类实现：获取友好回应提示词

        Returns:
            友好回应提示词
        """
        pass

    @abstractmethod
    async def _ensure_initialized(self, context: ChatContext = None) -> None:
        """
        子类实现：确保已异步初始化

        Args:
            context: 对话上下文（可选）
        """
        pass

    @abstractmethod
    async def process_user_input(
        self,
        user_input: str,
        context: ChatContext
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        处理用户输入（流式输出）

        Args:
            user_input: 用户输入
            context: 对话上下文

        Yields:
            Dict[str, Any]: 流式输出的字典
        """
        pass

    async def log_token_usage(
        self,
        context: ChatContext,
        node: ZbConversationNode,
        usage_metadata: Dict[str, Any],
        latency_ms: int = 0,
        status: int = 1,
        error_msg: str = None,
        remark: str = None
    ) -> None:
        """
        记录 token 使用数据到数据库

        Args:
            context: 对话上下文
            node: 节点信息
            usage_metadata: token 使用量元数据
            latency_ms: 调用耗时(毫秒)
            status: 状态，1=成功 2=失败
            error_msg: 错误信息
            remark: 备注
        """
        await ZbLogTokens.token_usage_2_db(
            context=context,
            node=node,
            usage_metadata=usage_metadata,
            latency_ms=latency_ms,
            status=status,
            error_msg=error_msg,
            remark=remark
        )
    @staticmethod
    async def get_chat_history_from_db(
        conversation_id: str,
        message_status: int = None,
        node_id: str = None,
        max: int = 10,
        is_human_generated: int = None
    ) -> List[Dict]:
        """从数据库获取聊天历史

        Args:
            conversation_id: 会话ID
            message_status: 消息状态（可选）：0-处理中、1-成功、-1（失败）
            node_id: 节点ID（可选）
            max: 返回最近的记录数，默认10
            is_human_generated: 是否人工生成（可选）：0-非人工、1-人工，默认0

        Returns:
            聊天历史列表
        """
        chat_history = []
        result_db_message = await ZbConversationMessagesUtil.load_messages_by_conversation_and_node(
            conversation_id=conversation_id,
            node_id=node_id,
            message_status=message_status,
            is_human_generated=is_human_generated,
            limit=max
        )

        if result_db_message:
            for message in reversed(result_db_message):
                question = message.question
                answer = message.answer
                file_id_list = message.file_id_list if hasattr(message, 'file_id_list') else None
                task_type = message.task_type if hasattr(message, 'task_type') else None
                if question:
                    chat_history.append({
                        "role": "user",
                        "content": question,
                        "node_id": message.node_id,
                        "file_id_list": file_id_list,
                        "task_type": task_type,
                        "message_id": message.message_id
                    })
                if answer:
                    chat_history.append({
                        "role": "assistant",
                        "content": answer,
                        "node_id": message.node_id,
                        "file_id_list": file_id_list,
                        "task_type": task_type,
                        "message_id": message.message_id
                    })

        return chat_history

    def _parse_json_response(self, response: str) -> Dict[str, Any]:
        """解析 JSON 响应

        Args:
            response: LLM 返回的响应字符串，可能包含 JSON

        Returns:
            解析后的字典，如果解析失败则返回 None
        """
        try:
            # 查找 JSON 部分
            start_idx = response.find("{")
            end_idx = response.rfind("}") + 1

            if start_idx != -1 and end_idx > start_idx:
                json_str = response[start_idx:end_idx]
                parsed = json.loads(json_str)
                # 验证必要字段存在
                if isinstance(parsed, dict) and "intent" in parsed:
                    return parsed
        except Exception as e:
            app_logger.error(f"JSON 解析错误: {e}, 原始响应: {response}")
        return None

    async def generate_friendly_response_stream(
        self,
        user_input: str,
        chat_history: List[Dict] = None,
        context: ChatContext = None,
        node: ZbConversationNode = None
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        生成友好回应（流式输出）

        Args:
            user_input: 用户输入的字符串
            chat_history: 聊天历史
            context: 对话上下文
            node: 节点信息

        Yields:
            流式输出的消息字典
        """
        full_msg = ""
        conversation_id = context.conversation_id if context else ""
        
        try:
            # 确保已初始化
            await self._ensure_initialized(context)

            system_prompt = await self._get_prompt_friendly_response(context)
            app_logger.info(f"friendly system_prompt: {system_prompt}")
            messages = [
                SystemMessage(content=system_prompt)
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
            usage_metadata = None
            start_time = time.time()
            llm = (await self.resolve_prompt_model(self.node_id, "friendly_response_prompt")) or self.llm
            async for chunk in llm.astream(messages):
                if hasattr(chunk, 'usage_metadata') and chunk.usage_metadata:
                    usage_metadata = chunk.usage_metadata
                content = getattr(chunk, 'content', str(chunk)) if hasattr(chunk, 'content') else str(chunk)
                if content:
                    full_msg += content
                    yield self.create_stream_message(content, 'model', is_last=False, conversation_id=conversation_id)
            latency_ms = int((time.time() - start_time) * 1000)

            # 记录token使用
            if usage_metadata and context and node:
                await self.log_token_usage(context, node, usage_metadata, latency_ms=latency_ms)

            # 保存对话记录到数据库
            if context:
                await ConversationDBHelper.save_conversation_record(
                    conversation_id=context.conversation_id,
                    conversation_name=context.conversation_name,
                    employee_id=context.user_id,
                    question=user_input,
                    answer=full_msg,
                    model_name=node.model_name if node else None,
                    model_provider=node.model_provider if node else "zbank",
                    model_url=node.model_url if node else None,
                    model_ext_param=node.model_ext_param if node else None,
                    status_description="用户意图未知，已生成友好回应",
                    node_id=node.node_id if node else "",
                    workflow_id=context.workflow.workflow_id if context.workflow else None,
                    is_human_generated=0,
                    message_status=1,
                    seq_no=context.seq_no,
                    conversation_type=context.conversation_type
                )

            # 发送结束消息
            yield self.create_stream_message("", 'model', is_last=True, is_over=True, conversation_id=conversation_id)

        except Exception as e:
            app_logger.error(f"生成友好回应出错: {e}")
            error_msg = "抱歉，我没有完全理解您的意思。请告诉我您具体需要什么帮助。"
            full_msg = error_msg
            yield self.create_stream_message(error_msg, 'model', is_last=False, conversation_id=conversation_id)

            # 即使出错也尝试保存对话记录
            if context:
                try:
                    await ConversationDBHelper.save_conversation_record(
                        conversation_id=context.conversation_id,
                        conversation_name=context.conversation_name,
                        employee_id=context.user_id,
                        question=user_input,
                        answer=full_msg,
                        model_name=node.model_name if node else None,
                        model_provider=node.model_provider if node else "zbank",
                        model_url=node.model_url if node else None,
                        model_ext_param=node.model_ext_param if node else None,
                        status_description=f"生成友好回应出错: {str(e)}",
                        node_id=node.node_id if node else "",
                        workflow_id=context.workflow.workflow_id if context.workflow else None,
                        is_human_generated=0,
                        message_status=1,
                        seq_no=context.seq_no,
                        conversation_type=context.conversation_type
                    )
                except Exception as save_error:
                    app_logger.error(f"保存对话记录出错: {save_error}")

            # 发送结束消息
            yield self.create_stream_message("", 'model', is_last=True, is_over=True, conversation_id=conversation_id)

    def create_stream_message(
        self,
        content: str,
        message_type: Literal["model", "tool", "interrupt", "knowledge_base"] = "model",
        is_last: bool = False,
        is_over: bool = False,
        conversation_id: str = ""
    ) -> Dict[str, Any]:
        """创建流式消息字典

        Args:
            content: 响应内容
            message_type: 消息类型，可选值：model（大模型响应）、tool（工具响应）、interrupt（人机交互中断）、knowledge_base（知识库响应）
            is_last: 是否流式响应的最后一个字符
            is_over: 代表整个业务逻辑是否结束
            conversation_id: 会话ID

        Returns:
            流式消息字典
        """
        return {
            "message_type": message_type,
            "content": content,
            "is_last": is_last,
            "is_over": is_over,
            "conversation_id": conversation_id
        }

    async def format_prompt(
        self,
        node_id: str,
        prompt_key: str,
        var_values: Dict[str, str] = None,
        head_prompt: str = None,
        tail_prompt: str = None
    ) -> str:
        """
        根据node_id+prompt_key获取提示词模板，使用变量值插值，并在前后拼接额外的提示词

        Args:
            node_id: 节点ID
            prompt_key: 提示词key
            var_values: 变量值字典，key为prompt_var_name，value为对应的值
            head_prompt: 拼接在提示词前面的内容（可选）
            tail_prompt: 拼接在提示词后面的内容（可选）

        Returns:
            str: 拼接后的提示词内容，未找到时返回空字符串
        """
        prompt_cache = NodePromptCache.get_instance()
        result = await prompt_cache.format_prompt(node_id, prompt_key, var_values or {})
        if result is None:
            return ""
        if head_prompt:
            result = head_prompt + result
        if tail_prompt:
            result = result + tail_prompt
        return result

    async def resolve_prompt_model(self, node_id: str, prompt_key: str):
        """
        根据 prompt 的 model_id 解析模型实例。
        如果 zb_node_prompt 中该 prompt 指定了 model_id，则查询 zb_llm_models
        构建对应的 ChatOpenAI 实例并返回，用于覆盖节点级默认模型。
        如果没有指定 model_id，返回 None。

        Args:
            node_id: 节点ID
            prompt_key: 提示词key

        Returns:
            ChatOpenAI 或 None（表示没有 prompt 级模型覆盖，应使用节点级 self.llm）
        """
        try:
            prompt_cache = NodePromptCache.get_instance()
            prompt = await prompt_cache.get_prompt(node_id, prompt_key)
            if not prompt or not prompt.model_id:
                return None

            app_logger.info(
                f"[prompt model override] node_id={node_id}, prompt_key={prompt_key}, "
                f"model_id={prompt.model_id}"
            )

            # model_ext_param 在 NodePrompt.from_dict 中已处理（str→dict），
            # 此处做防御性解析，与 _init_llm 行为一致：失败回退到 {}
            extra = prompt.model_ext_param
            if extra and isinstance(extra, str):
                import json
                try:
                    extra = json.loads(extra)
                except (json.JSONDecodeError, TypeError):
                    extra = {}

            return await ZbNodeModelUtil.build_llm_by_model_id(prompt.model_id, extra)
        except Exception as e:
            app_logger.error(f"解析 prompt 模型失败: {e}")
            return None

    async def setup(self,checkpointer:BaseCheckpointSaver) -> None:
        """安全创建表和索引，避免重复创建"""
        if AbstractAI._checkpointer_initialized:
            return
        try:
            if hasattr(checkpointer, 'setup') and callable(getattr(checkpointer, 'setup')):
                await checkpointer.setup()
            AbstractAI._checkpointer_initialized = True
        except Exception as e:
            if "Duplicate key name" in str(e) or "Table 'checkpoints' already exists" in str(e):
                # 忽略已存在错误，标记为已初始化
                AbstractAI._checkpointer_initialized = True
                return
            raise
    
    async def end_business(self, context: ChatContext) -> None:
        """结束当前业务，将业务状态标记为 completed
        
        Args:
            context: 对话上下文
        """
        if context.context_info and context.context_info.get("end_business", False):
            await ZbConversationBusinessStateUtil.mark_completed(
                conversation_id=context.conversation_id,
                node_id=self.node_id,
                thread_id=context.thread_id,
            )

    @staticmethod
    async def load_completed_thread_messages(context: ChatContext, node_id: str, agent) -> list:
        """从已完成的旧 thread 快照中加载历史消息

        当业务结束产生新 thread_id 后，新 thread 没有历史消息。
        此方法查找已完成的旧 thread_id，通过 graph.aget_state 读取快照中的 messages，
        用于补充新 thread 的历史上下文。

        Args:
            context: 对话上下文
            node_id: 节点ID
            agent: 已创建的 LangGraph agent（需带 checkpointer）

        Returns:
            旧 thread 快照中的 BaseMessage 列表（可能为空）
        """
        try:
            completed_thread_ids = await ZbConversationBusinessStateUtil.get_thread_ids(
                conversation_id=context.conversation_id,
                node_id=node_id,
                business_state="completed",
            )
            if not completed_thread_ids:
                return []

            for old_thread_id in completed_thread_ids:
                config = {"configurable": {"thread_id": old_thread_id}}
                snapshot = await agent.aget_state(config)
                if snapshot and snapshot.values:
                    messages = snapshot.values.get("messages", [])
                    if messages:
                        app_logger.info(
                            f"[历史恢复] 从已完成 thread={old_thread_id} 加载了 {len(messages)} 条历史消息"
                        )
                        return messages

            return []
        except Exception as e:
            app_logger.error(f"[历史恢复] 加载旧 thread 快照失败: {str(e)}")
            return []