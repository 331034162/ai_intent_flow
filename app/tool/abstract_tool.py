from __future__ import annotations

from abc import abstractmethod
from typing import AsyncGenerator, Dict, Optional, Any, List
from ..context.chat_context import ChatContext
from ..abstract_ai import AbstractAI
from langchain_openai import ChatOpenAI
from langchain.agents import create_agent
from langgraph.types import Command
from ..db_connection_pool.conversation_db_helper import ConversationDBHelper
from ..db_connection_pool.zb_conversation_nodes_util import _default_cache as node_cache
from ..db_connection_pool.zb_conversation_nodes_util import ZbConversationNode
from .util.tool_call_aware import async_tool_call_aware
from ..core.logger import app_logger
import asyncio
import time
import json
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, AIMessageChunk, ToolMessage
from .util.tool_response_message import ToolResponseMessage
from ..core.config import settings
from langgraph.checkpoint.mysql.aio import AIOMySQLSaver
from .util.interrupt_message import InterruptMessage
from .util.resume_message import ResumeMessage
from ..db_connection_pool.zb_conversation_business_state_util import ZbConversationBusinessStateUtil
from .util.messsage_trim_middleware import MessageTrimMiddleware
from langchain.agents.middleware import ToolCallLimitMiddleware
class AbstractTool(AbstractAI):
    """抽象工具基类"""

    # 意图类型常量定义
    INTENT_CONTINUE_BUSINESS = "continue_business"  # 继续办理业务
    INTENT_FRIENDLY_RESPONSE = "friendly_response"  # 友好回应
    INTENT_CHANGE_TOPIC = "change_topic"  # 切换话题
    INTENT_END_BUSINESS = "end_business"  # 结束办理业务

    # 所有意图类型列表
    ALL_INTENT_TYPES = [INTENT_CONTINUE_BUSINESS, INTENT_FRIENDLY_RESPONSE, INTENT_CHANGE_TOPIC, INTENT_END_BUSINESS]

    # 意图类型描述字典
    INTENT_DESCRIPTIONS = {
        INTENT_CONTINUE_BUSINESS: "继续办理业务",
        INTENT_FRIENDLY_RESPONSE: "友好回应",
        INTENT_CHANGE_TOPIC: "切换话题",
        INTENT_END_BUSINESS: "结束办理业务"
    }

    def __init__(self, node_id: str = ""):
        """初始化基本属性，不包含异步操作

        Args:
            node_id: 节点ID，子类应传入
        """
        if not node_id:
            raise ValueError(f"{self.__class__.__name__}: node_id 是必填项")
        self.node_id: str = node_id
        # 这些属性将在异步初始化方法中设置
        self.node: ZbConversationNode = None
        self.llm: ChatOpenAI = None
        self.agent = None
        self._initialized = False
        self._init_lock = asyncio.Lock()  # 并发控制锁
        self.tool = []
        self.prompt_tool_call = ""
        ##是否使用checkpointer
        self.use_checkpointer = False
        self.user_parallel_tool_call = True
        ##控制工具并发调用的中间件
        self.tool_limit_awares: List[ToolCallLimitMiddleware] = []
        ##是否跳过话题意图识别
        self.skip_topic_classific = False
        
        # 初始化意图识别关键词
        self._init_keywords()

    async def _ensure_initialized(self, context: ChatContext = None) -> None:
        """确保已异步初始化（并发安全）

        Args:
            context: 对话上下文（保留参数以保持接口兼容性）
        """
        # 双重检查锁定模式：先快速检查
        if self._initialized:
            return

        # 使用锁保护初始化过程
        async with self._init_lock:
            # 获取锁后再次检查，防止其他协程已经初始化
            if self._initialized:
                return

            try:
                # 异步获取节点和LLM
                self.node = await node_cache.get_node_by_id(self.node_id)
                self.llm = await node_cache.get_llm_by_node_id(self.node_id)
                self.model_name = self.node.model_name

                # 调用子类的初始化方法（子类负责设置 prompt_tool_call 和 tool）
                await self._initialize_tool(context=context)

                # 必输项校验
                if not self.prompt_tool_call:
                    raise ValueError(f"{self.__class__.__name__}: prompt_tool_call 是必填项，子类必须在 _initialize_tool 中设置 prompt_tool_call")

                self._initialized = True
                app_logger.info(f"{self.__class__.__name__} (node_id={self.node_id}) 初始化完成")

            except Exception as e:
                app_logger.error(f"{self.__class__.__name__} 初始化失败: {str(e)}")
                raise

    @abstractmethod
    async def _initialize_tool(self,context: ChatContext = None) -> None:
        """子类实现的初始化方法，用于设置 prompt_tool_call、tool 和 agent"""
        pass

    async def process_user_input(
        self, user_input: str, context: ChatContext
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        处理用户输入，支持随时切换话题

        主要流程：
        1. 确保已异步初始化
        2. 检测用户是否想切换话题
        3. 如果切换话题，转到意图分类器处理
        4. 如果不切换，继续处理业务
        5. 支持在业务处理中途切换话题
        """
        # 确保已异步初始化
        await self._ensure_initialized(context)
        conversation_id = context.conversation_id
        conversation_name = context.conversation_name
        employee_id = context.user_id

        context.run_steps += 1
        app_logger.info(f"当前执行步数：{context.run_steps}")
        if context.run_steps > context.run_steps_max:
            app_logger.info(f"执行步数超过最大允许执行步数{context.run_steps_max}次，跳过处理")
            yield self.create_stream_message("您的问题我目前还无法处理，请换一个问题吧。",message_type="model", is_last=True,is_over=True,conversation_id=conversation_id)
            return

        # 从数据库获取聊天历史
        if context.is_query_history_node_id and context.use_history:
            chat_history = await AbstractAI.get_chat_history_from_db(conversation_id, message_status=1, node_id=self.node_id, max=context.history_max_records)
            """
            ##如果是开始的入口节点则不限制 node_id，获取完整对话历史(但不能包含is_human_generated=1)用于意图识别，否则只查询跟当前节点相关的信息，强化意图识别
            if context.workflow.entry_node_id != self.node_id:
                chat_history = await AbstractAI.get_chat_history_from_db(conversation_id, message_status=1, node_id=self.node_id, max=context.history_max_records)
            else:
                chat_history = await AbstractAI.get_chat_history_from_db(conversation_id, message_status=1, node_id=None, is_human_generated=0)
            """
            context.chat_history = chat_history
        else:
            chat_history = context.chat_history
        
        if context.is_user_input_interrupt_ack:
            app_logger.info("检测到用户响应中断")
            async for msg in self._gen_response(context,"用户响应中断"):
                yield msg
            return

        # 第一步：检测是否在话题范围内
        topic_classific_result = await self.is_in_topic_range(chat_history, user_input, context)
        yield self.create_stream_message(f"话题范围({self.node.node_business_range})识别：用户想要{self.INTENT_DESCRIPTIONS[topic_classific_result['intent_type']]}",message_type="tool", is_last=True,is_over=False,conversation_id=conversation_id)

        status_description = ""  # 初始化状态描述
        if topic_classific_result["intent_type"] == self.INTENT_FRIENDLY_RESPONSE:
            app_logger.info("检测到用户问了需要友好回应的问题")
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
                async for msg in self.generate_friendly_response_stream(user_input, chat_history, context,self.node):
                    yield msg
        elif topic_classific_result["intent_type"] == self.INTENT_END_BUSINESS:
            app_logger.info("检测到用户要结束对话")
            async for msg in self.generate_friendly_response_stream(user_input, chat_history, context,self.node):
                    yield msg
        elif topic_classific_result["intent_type"] == self.INTENT_CHANGE_TOPIC:
            app_logger.info("检测到用户要切换话题")
            # 使用意图分类器处理
            intent_classicfic_node_id = context.workflow.intent_classify_node_id
            if not intent_classicfic_node_id or intent_classicfic_node_id == "":
                intent_classicfic_node_id = context.workflow.entry_node_id
            ##如果当前节点不是entry_node则交给entry_node处理，否则生成友好回应
            if intent_classicfic_node_id != self.node_id:
                await ConversationDBHelper.save_conversation_record(
                    conversation_id=conversation_id,
                    conversation_name=conversation_name,
                    employee_id=employee_id,
                    question=user_input,
                    answer=topic_classific_result["friendly_response"],
                    model_name=self.node.model_name,
                    model_provider=self.node.model_provider if self.node.model_provider else "zbank",
                    model_url=self.node.model_url if self.node.model_url else None,
                    model_ext_param=self.node.model_ext_param,
                    status_description="用户切换话题",
                    node_id=self.node_id,
                    workflow_id=context.workflow.workflow_id if context.workflow else None,
                    is_human_generated=1,
                    message_status=1,
                    seq_no=context.seq_no,
                    conversation_type=context.conversation_type
                )
                intent_node : AbstractAI = await node_cache.instantiate_node(intent_classicfic_node_id)
                intent_node_info = await node_cache.get_node_by_id(intent_classicfic_node_id)
                async for msg in intent_node.process_user_input(user_input, context):
                   yield msg
            else:
                async for msg in self.generate_friendly_response_stream(user_input, chat_history, context,self.node):
                    yield msg
        else:
            # 在话题范围内，正常处理业务
            status_description = f'用户的{self.__class__.__name__}业务正在进行中'
            app_logger.info(f"用户在话题范围内，继续{self.__class__.__name__}业务")
            async for msg in self._gen_response(context=context,status_description=status_description):
               yield msg
    

    async def _gen_response(self, context: ChatContext,status_description:str) -> AsyncGenerator[Dict[str, Any], None]:
        full_msg = ""
        message_type = "model"
        # 用于收集多个 interrupt 消息
        interrupt_messages: list = []
        # 流式处理业务
        async for chunk in self._stream_process_user_input(context.chat_history, context.user_input, context):
            message_type = chunk.message_type
            if chunk.message_type == 'tool':
                # tool 消息
                yield self.create_stream_message(chunk.message, message_type, is_last=True, conversation_id=context.conversation_id)
            elif chunk.message_type == 'interrupt':
                #interrupt消息，收集到列表中
                if chunk.message:
                    interrupt_messages.append(chunk.message)
            elif chunk.message_type == 'knowledge_base':
                is_last = (chunk.chunk_position == "last")
                yield self.create_stream_message(chunk.message,message_type, is_last=is_last, conversation_id=context.conversation_id)
                if chunk.message:
                    # 1. 去掉前面的 "data: "
                    json_str = chunk.message.replace("data: ", "", 1)
                    # 2. 解析 JSON
                    data = json.loads(json_str)
                    full_msg += data["data"]["answer"]
            else:
                # model 消息
                full_msg += chunk.message
                is_last = (chunk.chunk_position == "last")
                yield self.create_stream_message(chunk.message,message_type, is_last=is_last, conversation_id=context.conversation_id)
                
        await self.end_business(context)
        
        # interrupt 分支：interrupt 消息是一次性的，有值时直接保存并结束，无值时说明是恢复后的第二次调用，直接返回
        if message_type == "interrupt":
            if interrupt_messages and len(interrupt_messages) > 0:
                merged_map: dict = {}
                value_2_db: str = ""
                interrupt_id_list: list = []
                total_count = len(interrupt_messages)
                # 遍历所有中断消息
                for item in interrupt_messages:
                    interrupt_map: dict = json.loads(item)
                    # 取唯一的 key & value
                    thread_interrupt_id, interrupt_value = next(iter(interrupt_map.items()))
                    # 提取 interrupt_id
                    one_interrupt_id = str(thread_interrupt_id).split(":")[1]
                    interrupt_id_list.append(one_interrupt_id)
                    # 拼接显示文本
                    interrupt_value_text = InterruptMessage.from_str_or_dict(interrupt_value).to_text()
                    value_2_db += f"编号【{thread_interrupt_id}】待确认信息如下\n：{interrupt_value_text}\n\n\n" if total_count > 1 else interrupt_value_text
                    # 合并到大字典
                    merged_map.update(interrupt_map)

                # 拼接中断ID
                interrupt_id = ",".join(interrupt_id_list)

                # 返回前端
                yield self.create_stream_message(json.dumps(merged_map, ensure_ascii=False), message_type, is_last=True, conversation_id=context.conversation_id)

                # 保存数据库
                status_description = "发生中断，需用户响应"
                thread_id = context.thread_id
                knowledge_conversation_id = context.context_info.get("knowledge_conversation_id", None)
                context.knowledge_conversation_id = knowledge_conversation_id

                await ConversationDBHelper.save_conversation_record(
                    conversation_id=context.conversation_id,
                    conversation_name=context.conversation_name,
                    employee_id=context.user_id,
                    question=context.user_input,
                    answer=value_2_db,
                    model_name=self.node.model_name,
                    model_provider=self.node.model_provider or "zbank",
                    model_url=self.node.model_url,
                    model_ext_param=self.node.model_ext_param,
                    status_description=status_description,
                    node_id=self.node_id,
                    workflow_id=context.workflow.workflow_id if context.workflow else None,
                    is_human_generated=0,
                    message_status=1,
                    seq_no=context.seq_no,
                    conversation_type=context.conversation_type,
                    knowledge_conversation_id=knowledge_conversation_id,
                    thread_id=thread_id,
                    interrupt_id=interrupt_id
                )
                yield self.create_stream_message("", message_type=message_type, is_last=True, is_over=True, conversation_id=context.conversation_id)
                return


        # model 分支：保存正常的 model 消息
        if full_msg:
            value_2_db = ""
            thread_id = context.thread_id
            interrupt_id_list: list = []
            
            if context.is_user_input_interrupt_ack:
                resume_map:dict = json.loads(context.user_input)
                total_count = len(resume_map)  # 先获取总条数
                for key, value in resume_map.items():
                    value = ResumeMessage.from_str_or_dict(value).to_text()
                    value_2_db += f"用户回复 -> 编号【{key}】:{value}\n" if total_count > 1 else value
                    one_interrupt_id = str(key).split(":")[1]
                    interrupt_id_list.append(one_interrupt_id)
            interrupt_id = ",".join(interrupt_id_list)
            knowledge_conversation_id = context.context_info.get("knowledge_conversation_id", None)
            context.knowledge_conversation_id = knowledge_conversation_id
            await ConversationDBHelper.save_conversation_record(
                conversation_id=context.conversation_id,
                conversation_name=context.conversation_name,
                employee_id=context.user_id,
                question=value_2_db if context.is_user_input_interrupt_ack else context.user_input,
                answer=full_msg,
                model_name=self.node.model_name,
                model_provider=self.node.model_provider if self.node.model_provider else "zbank",
                model_url=self.node.model_url if self.node.model_url else None,
                model_ext_param=self.node.model_ext_param,
                status_description=status_description,
                node_id=self.node_id,
                workflow_id=context.workflow.workflow_id if context.workflow else None,
                is_human_generated=0,
                message_status=1,
                seq_no=context.seq_no,
                conversation_type=context.conversation_type,
                knowledge_conversation_id=knowledge_conversation_id,
                thread_id = thread_id,
                interrupt_id=interrupt_id
            )

        # 发送最终结束消息
        yield self.create_stream_message("", message_type=message_type, is_last=True, is_over=True, conversation_id=context.conversation_id)     

    async def _stream_process_user_input(self, chat_history: list, user_input: str, context: ChatContext) -> AsyncGenerator[ToolResponseMessage,None]:
        """
        流式处理用户输入（通用实现）
        
        主要流程：
        1. 构建消息列表（包含历史对话）
        2. 调用 agent.astream 进行流式处理
        3. 处理 AIMessageChunk 类型的响应
        4. 记录 token 使用
        
        Args:
            chat_history: 聊天历史
            user_input: 用户输入
            context: 对话上下文
            
        Yields:
            ToolResponseMessage: 工具响应消息
        """
        input_messages = None
        config = None
        # 构建 config（thread_id 用于 checkpointer 区分会话）
        if context and context.is_user_input_interrupt_ack:
            # 中断恢复时不需要构建消息列表，直接使用 Command(resume=...) 传递用户输入
            # 解析用户输入
            resume_map_origin = json.loads(context.user_input)
            resume_map = {}
            # 遍历所有中断
            for key, value in resume_map_origin.items():
                thread_id, interrupt_id = key.split(":")
                # 因为 thread_id 全部相同，直接赋值即可
                context.thread_id = thread_id
                # 收集所有 {中断ID: 值}
                resume_map[interrupt_id] = value
            # 配置（只用一次，因为线程唯一）
            config = {"configurable": {"thread_id": context.thread_id}}
            # 一次性恢复所有中断 ✅ LangGraph 支持
            input_messages = Command(resume=resume_map)
        else:
            messages = []
            if chat_history and self.use_checkpointer == False:
                for msg in chat_history:
                    if msg.get("role") == "user":
                        messages.append(HumanMessage(content=msg.get("content", "")))
                    elif msg.get("role") == "assistant":
                        messages.append(AIMessage(content=msg.get("content", "")))
            messages.append(HumanMessage(content=user_input))
            ##新一轮的对话，则直接创建新的thread_id
            context.thread_id = await ZbConversationBusinessStateUtil.get_or_create_thread_id(
                conversation_id=context.conversation_id,
                node_id=self.node_id,
            )
            # 构建 config（thread_id 用于 checkpointer 区分会话，context 用于工具获取上下文）
            config = {"configurable": {"thread_id": context.thread_id}}
            input_messages = {"messages": messages}

        if self.use_checkpointer:
            # 设置摘要 LLM 供 middleware 使用
            context.summary_llm = self.llm
            # 创建 checkpointer 用于保存中断状态
            async with AIOMySQLSaver.from_conn_string(f"mysql+aiomysql://{settings.MYSQL_USER}:{settings.MYSQL_PASSWORD}@{settings.MYSQL_HOST}/{settings.MYSQL_DB}") as checkpointer:
                await self.setup(checkpointer)
                # 如果 tool 为空，创建不带工具的 agent，仅进行大模型对话
                middlewares = [MessageTrimMiddleware(context), async_tool_call_aware] + self.tool_limit_awares
                self.agent = create_agent(
                    model=self.llm,
                    tools=self.tool if self.tool else [],
                    system_prompt=self.prompt_tool_call,
                    debug=False,
                    middleware=middlewares,
                    checkpointer=checkpointer
                )

                # 从已完成的旧 thread 加载历史消息，存到 context 由 middleware 临时拼接，不存入 state
                if not context.is_user_input_interrupt_ack:
                    old_messages = await AbstractAI.load_completed_thread_messages(context, self.node_id, self.agent)
                    if old_messages:
                        context.snapshot_messages = old_messages

                start_time = time.time()
                accumulated_usage = None

                async for chunk in self.agent.astream(input_messages, context=context, config=config, stream_mode=["updates", "messages"], version="v2"):
                    if chunk["type"] == "messages":
                        token, _ = chunk["data"]
                        if isinstance(token, AIMessageChunk):
                            # 跳过空 content 的 chunk（如纯 metadata 或结束标记）
                            if not token.content and not token.tool_call_chunks:
                                # 仍然记录 usage_metadata
                                if hasattr(token, 'usage_metadata') and token.usage_metadata:
                                    accumulated_usage = token.usage_metadata
                                continue
                            tool_message = ToolResponseMessage()
                            tool_message.langraph_info = _
                            tool_message.message_type = "model"
                            tool_message.message = token.content
                            tool_message.chunk_position = getattr(token, 'chunk_position', "middle")
                            tool_message.response_metadata = getattr(token, 'response_metadata', {})
                            tool_message.finish_reason = tool_message.response_metadata.get('finish_reason')
                            if hasattr(token, 'usage_metadata') and token.usage_metadata:
                                tool_message.usage_metadata = token.usage_metadata
                                accumulated_usage = token.usage_metadata
                            yield tool_message
                        elif isinstance(token, ToolMessage):
                            tool_message = ToolResponseMessage()
                            # return_direct=True 时，ToolMessage 即最终响应（不经过 LLM 总结），
                            # 此时应使用 model 类型避免被前端过滤掉
                            tool_message.message_type = "model" if context.is_user_input_interrupt_ack else "tool"
                            tool_message.message = token.content
                            tool_message.chunk_position = "last"
                            yield tool_message
                    elif chunk["type"] == "updates":
                        for node_name, state_update in chunk["data"].items():
                            if node_name == "__interrupt__":
                                # interrupt 事件，通知上层
                                # state_update 是 Interrupt 对象的元组，如 (Interrupt(value='...'),)
                                # 取最后一个 Interrupt 的 value
                                tool_message = ToolResponseMessage()
                                tool_message.message_type = "interrupt"
                                last_interrupt = state_update[-1] if isinstance(state_update, (tuple, list)) else state_update
                                interrupt_value = getattr(last_interrupt, 'value', str(last_interrupt))
                                interrupt_id = getattr(last_interrupt, 'id', None)
                                interrupt_value_return ={f"{context.thread_id}:{interrupt_id}":interrupt_value}
                                # 确保 message 为 str（interrupt 值可能是 dict 等类型）
                                tool_message.message = json.dumps(interrupt_value_return, ensure_ascii=False) 
                                tool_message.chunk_position = "last"
                                yield tool_message

                # 记录 token 使用（流式结束后统一记录）
                if accumulated_usage and context and self.node:
                    latency_ms = int((time.time() - start_time) * 1000)
                    await self.log_token_usage(context, self.node, accumulated_usage, latency_ms=latency_ms)
        else:
            # 设置摘要 LLM 供 middleware 使用
            context.summary_llm = self.llm
            # 如果 tool 为空，创建不带工具的 agent，仅进行大模型对话
            # 对于不需要进行中断的业务，可以不创建 checkpointer，以减少对数据库的调用
            middlewares = [async_tool_call_aware] + self.tool_limit_awares
            self.agent = create_agent(
                model=self.llm,
                tools=self.tool if self.tool else [],
                system_prompt=self.prompt_tool_call,
                debug=False,
                middleware=middlewares
            )

            start_time = time.time()
            accumulated_usage = None

            async for chunk in self.agent.astream(input_messages, context=context, stream_mode=["updates", "messages"], version="v2"):
                if chunk["type"] == "messages":
                    token, _ = chunk["data"]
                    if isinstance(token, AIMessageChunk):
                        # 跳过空 content 的 chunk（如纯 metadata 或结束标记）
                        if not token.content and not token.tool_call_chunks:
                            # 仍然记录 usage_metadata
                            if hasattr(token, 'usage_metadata') and token.usage_metadata:
                                accumulated_usage = token.usage_metadata
                            continue
                        tool_message = ToolResponseMessage()
                        tool_message.langraph_info = _
                        tool_message.message_type = "model"
                        tool_message.message = token.content
                        tool_message.chunk_position = getattr(token, 'chunk_position', "middle")
                        tool_message.response_metadata = getattr(token, 'response_metadata', {})
                        tool_message.finish_reason = tool_message.response_metadata.get('finish_reason')
                        if hasattr(token, 'usage_metadata') and token.usage_metadata:
                            tool_message.usage_metadata = token.usage_metadata
                            accumulated_usage = token.usage_metadata
                        yield tool_message
                    elif isinstance(token, ToolMessage):
                        tool_message = ToolResponseMessage()
                        # return_direct=True 时，ToolMessage 即最终响应（不经过 LLM 总结），
                        # 此时应使用 model 类型避免被前端过滤掉
                        tool_message.message_type = "model" if context.is_user_input_interrupt_ack else "tool"
                        tool_message.message = token.content
                        tool_message.chunk_position = "last"
                        yield tool_message
                elif chunk["type"] == "updates":
                    for node_name, state_update in chunk["data"].items():
                        if node_name == "__interrupt__":
                            # interrupt 事件，通知上层
                            # state_update 是 Interrupt 对象的元组，如 (Interrupt(value='...'),)
                            # 取最后一个 Interrupt 的 value
                            tool_message = ToolResponseMessage()
                            tool_message.message_type = "interrupt"
                            last_interrupt = state_update[-1] if isinstance(state_update, (tuple, list)) else state_update
                            interrupt_value = getattr(last_interrupt, 'value', str(last_interrupt))
                            interrupt_id = getattr(last_interrupt, 'id', None)
                            interrupt_value_return ={f"{context.thread_id}:{interrupt_id}":interrupt_value}
                            # 确保 message 为 str（interrupt 值可能是 dict 等类型）
                            tool_message.message = json.dumps(interrupt_value_return, ensure_ascii=False) 
                            tool_message.chunk_position = "last"
                            yield tool_message

            # 记录 token 使用（流式结束后统一记录）
            if accumulated_usage and context and self.node:
                latency_ms = int((time.time() - start_time) * 1000)
                await self.log_token_usage(context, self.node, accumulated_usage, latency_ms=latency_ms)
    
    async def _clear_interrupt(self, config,context:ChatContext):
        # 正常启动前，检查并清除当前线程残留的中断，没什么用，放在这里便于以后学习使用
        try:
            if context.is_user_input_interrupt_ack == False:
                snapshot = await self.agent.aget_state(config)
                if snapshot and snapshot.tasks:
                    has_interrupt = False
                    for task in snapshot.tasks:
                        if task.interrupts:
                            has_interrupt = True
                            break
                    if has_interrupt:
                        app_logger.info(f"检测到线程 {config.get('configurable', {}).get('thread_id')} 存在残留中断")
                        self.agent.aupdate_state(config,None,None)
                        # 关键修复：不主动清除中断状态或删除消息
                        # 原因：
                        # 1. 工具内部的 interrupt() 是业务需求，应该被尊重
                        # 2. 删除所有消息会导致 tool_calls 和 ToolMessage 不匹配，引发 400 错误
                        # 3. 正确的做法是让 LangGraph 自然处理中断状态
                        # 4. 如果用户想开始新对话，应该在 workflow 层生成新的 conversation_id
                        app_logger.info(f"保留中断状态，等待用户确认或重新开始新对话")
        except Exception as e:
            app_logger.warning(f"检查中断状态时出错: {e}")

    def _init_keywords(self):
        """初始化意图识别关键词列表"""
        # 1. 友好回应 - 寒暄类
        self.greeting_keywords = {
            '你好', '您好', '早上好', '下午好', '晚上好', 'hi', 'hello', 'hey',
            '嗨', '哈喽', 'hello there', 'good morning', 'good afternoon',
            '在吗', '在不在', '有人吗', '有人在吗'
        }

        # 2. 继续办理业务 - 礼貌类
        self.politeness_keywords = {
            '谢谢', '感谢', '多谢', '非常感谢', '不好意思', '抱歉', '对不起',
            '打扰了', '麻烦了', '劳驾', '辛苦了'
        }

        # 3. 结束业务 - 结束类
        self.ending_keywords = {
            '不用了', '算了', '我不想办理了', '不想办了', '算了不用了',
            '不需要', '不需要了', '不用了', '拜拜', '再见', '下次见',
            '回聊', '那先这样', '那就这样', '结束', '退出', 'quit', 'exit',
            'bye', 'goodbye', '不用麻烦了', '那就算了', '先不办了'
        }

        # 4. 友好回应 - 自我介绍类（询问AI）
        self.self_intro_keywords = {
            '你是谁', '你是', '介绍一下你自己', '说说你自己', '你能做什么',
            '你能做啥', '你能做什么业务', '你会什么', '你的功能', '你的能力',
            '你可以干什么', '你可以做些什么', '你会什么业务', '你有什么功能','说说你自己','你能干啥','你能做什么'
        }

        # 5. 继续办理业务 - 确认语
        self.confirm_keywords = {
            '好的', '知道了', '明白了', '懂了', '清楚了', '收到了', '确认',
            '了解', 'ok', '行', '可以', '嗯嗯', '嗯', '是', '对', '是的','对的'
        }

        # 6. 继续办理业务 - 语气词
        self.mood_words = {
            '啊', '哦', '嗯', '呃', '哎呀', '哇', '噢', '额', 'emmm', 'em'
        }

    def _is_in_topic_quick_check(self, text: str) -> Optional[str]:
        """
        快速检测文本的意图类型（不调用LLM）

        快速识别只处理明确的友好回应、继续办理业务和结束办理业务的情况，切换话题交由LLM进行更准确的判断

        Args:
            text: 用户输入文本

        Returns:
            Optional[str]: 'continue_business'-继续办理业务, 'friendly_response'-友好回应,
                          'end_business'-结束办理业务, None-无法快速判断（切换话题也返回None，交由LLM判断）
        """
        import re
        
        text_lower = text.lower().strip()

        # 移除常见的语气助词
        text_clean = text_lower.rstrip('啊呀吧嘛呢')
        
        # 移除标点符号，用于全词匹配
        text_no_punct = re.sub(r'[，。！？、；：""''（）【】《》\.,!?;:\'\"\(\)\[\]<>]', '', text_clean)

        # 优先检查结束办理业务（全词匹配：只有关键词或关键词+标点）
        for keyword in self.ending_keywords:
            if text_clean == keyword or text_no_punct == keyword:
                return self.INTENT_END_BUSINESS

        # 检查友好回应 - 自我介绍类（全词匹配：只有关键词或关键词+标点）
        for keyword in self.self_intro_keywords:
            if text_clean == keyword or text_no_punct == keyword:
                return self.INTENT_FRIENDLY_RESPONSE

        # 检查友好回应 - 寒暄类（全词匹配）
        if text_clean in self.greeting_keywords or text_no_punct in self.greeting_keywords:
            return self.INTENT_FRIENDLY_RESPONSE

        # 检查继续办理业务 - 礼貌类（全词匹配）
        if text_clean in self.politeness_keywords or text_no_punct in self.politeness_keywords:
            return self.INTENT_CONTINUE_BUSINESS

        # 检查继续办理业务 - 确认语（全词匹配）
        if text_clean in self.confirm_keywords or text_no_punct in self.confirm_keywords:
            return self.INTENT_CONTINUE_BUSINESS

        # 检查继续办理业务 - 语气词（全词匹配）
        if text_clean in self.mood_words or text_no_punct in self.mood_words:
            return self.INTENT_CONTINUE_BUSINESS

        # 检查长度（通常寒暄语较短）
        if len(text_clean) <= 3:
            # 短文本，检查是否只包含语气词
            if all(char in '啊哦嗯呃呀' for char in text_clean):
                return self.INTENT_CONTINUE_BUSINESS

        # 无法快速判断
        return None

    async def is_in_topic_range(self, history_messages: list, current_question: str, context: ChatContext = None) -> Dict[str, str]:
        """
        判断用户的意图类型

        判断四种意图类型：
        1. continue_business: 继续办理业务
        2. friendly_response: 友好回应（寒暄类、礼貌类、自我介绍类）
        3. change_topic: 切换话题
        4. end_business: 结束办理业务

        Args:
            history_messages: 历史聊天记录，每个消息包含role和content字段
            current_question: 当前用户提出的问题
            context: 对话上下文（用于记录token使用）

        Returns:
            Dict[str, str]: 包含意图判断结果的字典：
                - intent_type: 意图类型（continue_business/friendly_response/change_topic/end_business）
                - friendly_response: 友好的回应文本（仅在切换话题时生成，其他情况为空字符串）
        """
        if self.skip_topic_classific:
            return {
                "intent_type": self.INTENT_CONTINUE_BUSINESS,
                "friendly_response": ""
            }
        # 第一步：快速规则判断（不调用LLM，提高性能）
        quick_result = self._is_in_topic_quick_check(current_question)
        if quick_result is not None:
            app_logger.info(f"快速识别意图类型：{quick_result} - {current_question}")
            # 快速判断时，友好回应为空
            return {
                "intent_type": quick_result,
                "friendly_response": ""
            }

        # 第二步：使用LLM进行深度分析（规则无法确定时）
        app_logger.info(f"调用LLM进行深度意图分析")

        # 获取意图分析的 system prompt（子类可重写此方法来自定义）
        system_prompt_content = await self._build_intent_analysis_prompt(context)

        # 构建消息列表
        conversation_messages = [SystemMessage(content=system_prompt_content)]

        # 只取最近5轮对话，避免上下文过长
        recent_history = history_messages[-10:] if len(history_messages) > 10 else history_messages

        for msg in recent_history:
            if isinstance(msg, dict):
                role = msg.get('role', '')
                content = msg.get('content', '')
            else:
                role = getattr(msg, 'role', getattr(msg, 'type', ''))
                content = getattr(msg, 'content', str(msg))

            if role.lower() in ['user', 'human']:
                conversation_messages.append(HumanMessage(content=content))
            elif role.lower() in ['assistant', 'ai', 'bot']:
                conversation_messages.append(AIMessage(content=content))

        # 添加当前问题
        conversation_messages.append(HumanMessage(content=f"用户当前输入：{current_question}\n\n请分析用户的意图类型："))

        try:
            # 调用大语言模型进行判断 —— 优先使用 prompt 级模型覆盖
            start_time = time.time()
            llm = (await self.resolve_prompt_model(self.node_id, "prompt_intent_analysis")) or self.llm
            response = await llm.ainvoke(conversation_messages)
            latency_ms = int((time.time() - start_time) * 1000)
            response_text = response.content.strip()

            # 记录token使用
            if hasattr(response, 'usage_metadata') and response.usage_metadata and context:
                await self.log_token_usage(context, self.node, response.usage_metadata, latency_ms=latency_ms)

            # 尝试解析响应
            result = self._parse_json_response(response_text)
            if result:
                intent_type = result["intent_type"]
                friendly_response = result["friendly_response"]
                if friendly_response:
                    app_logger.info(f"LLM识别意图类型：{intent_type}, 友好回应：{friendly_response}")
                else:
                    app_logger.info(f"LLM识别意图类型：{intent_type}")
                return result

            # 无法识别，返回默认值
            app_logger.error(f"无法解析响应: {response_text}")
            return self._get_default_result()

        except Exception as e:
            app_logger.error(f"意图分析出错: {str(e)}")
            return self._get_default_result()

    @abstractmethod
    async def _build_intent_analysis_prompt(self, context: ChatContext = None) -> str:
        """构建意图分析的 system prompt

        Args:
            context: 对话上下文（可选）

        Returns:
            意图分析提示词
        """
        pass

    def _get_default_result(self) -> Dict[str, str]:
        """返回默认结果"""
        return {
            "intent_type": self.INTENT_CONTINUE_BUSINESS,  # 默认认为继续办理业务
            "friendly_response": ""
        }

    def _parse_json_response(self, response: str) -> Optional[Dict[str, str]]:
        """解析 JSON 响应，提取意图类型

        Args:
            response: LLM 返回的响应字符串

        Returns:
            包含 intent_type 和 friendly_response 的字典，失败返回 None
        """
        response_text = response.strip()

        try:
            # 查找 JSON 部分
            start_idx = response_text.find("{")
            end_idx = response_text.rfind("}") + 1

            if start_idx != -1 and end_idx > start_idx:
                json_str = response_text[start_idx:end_idx]
                result = json.loads(json_str)

                intent_type = result.get("intent_type", "").strip().lower()
                friendly_response = result.get("friendly_response", "").strip()

                # 验证意图类型是否有效
                if intent_type in self.ALL_INTENT_TYPES:
                    return {
                        "intent_type": intent_type,
                        "friendly_response": friendly_response
                    }
        except Exception as e:
            app_logger.error(f"JSON 解析错误: {e}, 原始响应: {response}")

        # JSON解析失败或意图类型无效，尝试从文本提取意图
        for intent in self.ALL_INTENT_TYPES:
            if intent in response_text.lower():
                app_logger.info(f"从文本中提取意图类型：{intent}")
                return {
                    "intent_type": intent,
                    "friendly_response": ""
                }

        return None