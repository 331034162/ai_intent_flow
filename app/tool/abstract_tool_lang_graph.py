from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from typing import AsyncGenerator, Dict, Optional, Any, List

from ..context.chat_context import ChatContext
from ..abstract_ai import AbstractAI
from langchain_openai import ChatOpenAI
from langgraph.types import Command
from ..db_connection_pool.conversation_db_helper import ConversationDBHelper
from ..db_connection_pool.zb_conversation_nodes_util import _default_cache as node_cache
from ..db_connection_pool.zb_conversation_nodes_util import ZbConversationNode
from ..core.logger import app_logger
import asyncio
import time
import json
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, AIMessageChunk
from ..core.config import settings
from langgraph.checkpoint.mysql.aio import AIOMySQLSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from .util.interrupt_message import InterruptMessage
from .util.resume_message import ResumeMessage
from ..db_connection_pool.zb_conversation_business_state_util import ZbConversationBusinessStateUtil
from langgraph.graph import StateGraph, START, END
from langgraph.config import RunnableConfig
from langchain_core.tools import BaseTool
from langgraph.config import get_stream_writer

from ..langgraph_agent.langgraph_agent_builder import (
    State, AgentConfig, LangGraphAgentBuilder, WarappedMessage
)


@dataclass
class BusinessAgentInfo:
    """业务智能体的信息"""

    """业务类型，需要跟业务范围意图识别提示词里面的标识保持一致"""
    business_type: str

    """工具列表"""
    tools: List[BaseTool]

    """系统提示词"""
    system_prompt: str


class AbstractTool(AbstractAI):
    """抽象工具基类

    不再使用 create_agent，直接用 StateGraph 构建 ReAct 循环子图。
    每个业务 Agent 是父图中的一个节点，内部含 chatbot → tool_executor 循环。
    统一使用 messages（WarappedMessage 列表）存储所有消息，按 agent_name 筛选各 Agent 私有历史。
    因为是同一图中的节点（非子图），流式输出天然可用。
    """

    INTENT_CONTINUE_BUSINESS = "continue_business"
    INTENT_FRIENDLY_RESPONSE = "friendly_response"
    INTENT_CHANGE_TOPIC = "change_topic"
    INTENT_END_BUSINESS = "end_business"

    ALL_INTENT_TYPES = [INTENT_CONTINUE_BUSINESS, INTENT_FRIENDLY_RESPONSE, INTENT_CHANGE_TOPIC, INTENT_END_BUSINESS]

    INTENT_DESCRIPTIONS = {
        INTENT_CONTINUE_BUSINESS: "继续办理业务",
        INTENT_FRIENDLY_RESPONSE: "友好回应",
        INTENT_CHANGE_TOPIC: "切换话题",
        INTENT_END_BUSINESS: "结束办理业务",
    }

    def __init__(self, node_id: str = ""):
        if not node_id:
            raise ValueError(f"{self.__class__.__name__}: node_id 是必填项")
        self.node_id: str = node_id
        self.node: ZbConversationNode = None
        self.llm: ChatOpenAI = None
        self.agent = None
        self._initialized = False
        self._init_lock = asyncio.Lock()
        self.business_agents: List[BusinessAgentInfo] = []
        self.use_all_messages: bool = True
        # 每个 agent 的节点名映射（运行时构建）
        self._agent_node_map: Dict[str, str] = {}
        self.use_paraller: bool = False

    def _build_graph(self, checkpointer=None, context: ChatContext = None):
        builder = StateGraph(State)
        builder.add_node("_intent_identify_node_", self._intent_identify_node_)
        builder.add_node("_change_topic_node_", self._change_topic_node_)

        for agent_info in self.business_agents:
            agent_name = agent_info.business_type
            agent_config = AgentConfig(
                agent_name=agent_name,
                system_prompt=agent_info.system_prompt,
                tools=agent_info.tools,
                llm=self.llm,
                use_all_messages=self.use_all_messages,
                use_paraller=self.use_paraller,
            )
            graph_builder = LangGraphAgentBuilder(agent_config)
            node_names = graph_builder.add_to_graph(builder, name_prefix=agent_name)
            # 缓存 agent_name → chatbot 节点名 的映射，供意图路由使用
            self._agent_node_map[agent_name] = node_names["chatbot_name"]

        builder.add_edge(START, "_intent_identify_node_")
        builder.add_conditional_edges("_intent_identify_node_", self._route_from_intent_node_)
        builder.add_edge("_change_topic_node_", END)
        return builder.compile(checkpointer=checkpointer)

    async def _route_from_intent_node_(self, state: State, config: RunnableConfig) -> str:
        if state.get("intent_type") == self.INTENT_CONTINUE_BUSINESS:
            business_type = state.get("business_type")
            # 从映射中获取 chatbot 节点名
            chatbot_name = self._agent_node_map.get(business_type, f"{business_type}_chatbot")
            return chatbot_name
        if state.get("intent_type") == self.INTENT_CHANGE_TOPIC:
            return "_change_topic_node_"
        # friendly_response、end_business 及未知意图：直接结束工作流，由 process_user_input 处理
        return END

    async def _change_topic_node_(self, state: State, config: RunnableConfig):
        app_logger.info("检测到用户要切换话题")
        context: ChatContext | None = config.get("configurable", {}).get("context")
        intent_classicfic_node_id = context.workflow.intent_classify_node_id
        if not intent_classicfic_node_id or intent_classicfic_node_id == "":
            intent_classicfic_node_id = context.workflow.entry_node_id
        if intent_classicfic_node_id != self.node_id:
            await ConversationDBHelper.save_conversation_record(
                conversation_id=context.conversation_id,
                conversation_name=context.conversation_name,
                employee_id=context.user_id,
                question=context.user_input,
                answer=state.get("friendly_response"),
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
        return Command(update=None)

    async def _intent_identify_node_(self, state: State, config: RunnableConfig) -> Command:
        context: ChatContext | None = config.get("configurable", {}).get("context")
        app_logger.info(f"调用LLM进行深度意图分析")

        system_prompt_content = await self._build_intent_analysis_prompt(context)

        conversation_messages = [SystemMessage(content=system_prompt_content)]

        for msg in context.chat_history:
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

        conversation_messages.append(HumanMessage(content=f"用户当前输入：{context.user_input}\n\n请分析用户的意图类型："))

        try:
            start_time = time.time()
            llm = (await self.resolve_prompt_model(self.node_id, "prompt_intent_analysis")) or self.llm
            response = await llm.ainvoke(conversation_messages)
            latency_ms = int((time.time() - start_time) * 1000)
            response_text = response.content.strip()

            if hasattr(response, 'usage_metadata') and response.usage_metadata and context:
                await self.log_token_usage(context, self.node, response.usage_metadata, latency_ms=latency_ms)

            result = self._parse_json_response(response_text)
            app_logger.info(f"LLM识别意图类型：{result}")   
            if result:
                intent_type = result["intent_type"]
                business_type = result["business_type"]
                friendly_response = result["friendly_response"]
                if friendly_response:
                    app_logger.info(f"LLM识别意图类型：{intent_type}, 友好回应：{friendly_response}")
                else:
                    app_logger.info(f"LLM识别意图类型：{intent_type}")
                return Command(
                    update={
                        "intent_type": intent_type,
                        "business_type": business_type,
                        "friendly_response": friendly_response,
                        "current_input": context.user_input,
                        "exe_step": 0,
                        "pending_tool_calls": [],
                    }
                )

            app_logger.error(f"无法解析响应: {response_text}")
            writer = get_stream_writer()
            writer(self.create_stream_message(content="抱歉，我没有理解您的意思，请将问题描述的更清晰一点，可以吗？", message_type="model", is_last=True, is_over=True, conversation_id=context.conversation_id))
            return Command(update=None, goto=END)

        except Exception as e:
            app_logger.error(f"意图分析出错: {str(e)}")
            writer = get_stream_writer()
            writer(self.create_stream_message(content="抱歉，我没有理解您的意思，请将问题描述的更清晰一点，可以吗？", message_type="model", is_last=True, is_over=True, conversation_id=context.conversation_id))
            return Command(update=None, goto=END)

    async def _ensure_initialized(self, context: ChatContext = None) -> None:
        if self._initialized:
            return
        async with self._init_lock:
            if self._initialized:
                return
            try:
                self.node = await node_cache.get_node_by_id(self.node_id)
                self.llm = await node_cache.get_llm_by_node_id(self.node_id)
                self.model_name = self.node.model_name
                self.business_agents = await self._initialize_tool(context)
                self._initialized = True
                app_logger.info(f"{self.__class__.__name__} (node_id={self.node_id}) 初始化完成")
            except Exception as e:
                app_logger.error(f"{self.__class__.__name__} 初始化失败: {str(e)}")
                raise

    async def process_user_input(
        self, user_input: str, context: ChatContext
    ) -> AsyncGenerator[Dict[str, Any], None]:
        await self._ensure_initialized(context)
        conversation_id = context.conversation_id
        app_logger.info(f"使用 LangGraph 图处理用户输入，当前用户: {context.user_id}")

        context.run_steps += 1
        if context.run_steps > context.run_steps_max:
            app_logger.info(f"执行步数超过最大允许执行步数{context.run_steps_max}次，跳过处理")
            yield self.create_stream_message(
                "您的问题我目前还无法处理，请换一个问题吧。",
                message_type="model", is_last=True, is_over=True, conversation_id=conversation_id
            )
            return

        if context.is_query_history_node_id and context.use_history:
            chat_history = await AbstractAI.get_chat_history_from_db(
                conversation_id, message_status=1, node_id=self.node_id, max=context.history_max_records
            )
            context.chat_history = chat_history
        else:
            chat_history = context.chat_history

        context.summary_llm = self.llm

        if context.is_user_input_interrupt_ack:
            resume_map_origin = json.loads(context.user_input)
            resume_map = {}
            for key, value in resume_map_origin.items():
                thread_id, interrupt_id = key.split(":")
                context.thread_id = thread_id
                resume_map[interrupt_id] = value
            input_data = Command(resume=resume_map)
        else:
            input_data = {"messages": [], "pending_tool_calls": [], "current_input": user_input, "exe_step": 0}
            context.thread_id = await ZbConversationBusinessStateUtil.get_or_create_thread_id(
                conversation_id=context.conversation_id,
                node_id=self.node_id,
            )

        config = {"configurable": {"thread_id": context.thread_id, "context": context}}

        full_msg = ""
        message_type = "model"
        interrupt_messages: list = []
        start_time = time.time()
        accumulated_usage = None

        async with AIOMySQLSaver.from_conn_string(
            f"mysql+aiomysql://{settings.MYSQL_USER}:{settings.MYSQL_PASSWORD}@{settings.MYSQL_HOST}/{settings.MYSQL_DB}",
            serde=JsonPlusSerializer(allowed_msgpack_modules=[
                ('app.langgraph_agent.langgraph_agent_builder', 'WarappedMessage')
            ])
        ) as checkpointer:
            await checkpointer.setup()
            self.agent = self._build_graph(checkpointer=checkpointer, context=context)
            if not context.is_user_input_interrupt_ack:
                old_messages = await AbstractAI.load_completed_thread_messages(context, self.node_id, self.agent)
                if old_messages:
                    context.snapshot_messages = old_messages

            async for chunk in self.agent.astream(
                input_data, config=config,
                stream_mode=["updates", "custom"], version="v2"
            ):
                result = self._process_stream_chunk(chunk, context, conversation_id, interrupt_messages)
                if result["stream_msg"] is not None:
                    yield result["stream_msg"]
                full_msg += result["full_msg_add"]
                if result["message_type"]:
                    message_type = result["message_type"]
                if result["accumulated_usage"]:
                    accumulated_usage = result["accumulated_usage"]
            # 获取最新的状态快照
            snapshot = await self.agent.aget_state(config)
            current_state = snapshot.values if snapshot else None
            _current_intent_ = current_state.get("intent_type", None) if current_state else None

        ##需要切换话题，并且当前节点不是entry节点，则需要将当前用户的问题交付到意图分类节点处理
        if _current_intent_ == self.INTENT_CHANGE_TOPIC:
            intent_classicfic_node_id = context.workflow.intent_classify_node_id
            if not intent_classicfic_node_id or intent_classicfic_node_id == "":
                intent_classicfic_node_id = context.workflow.entry_node_id
            if intent_classicfic_node_id != self.node_id:
                intent_node: AbstractAI = await node_cache.instantiate_node(intent_classicfic_node_id)
                async for msg in intent_node.process_user_input(context.user_input, context):
                    yield msg
            else:
                async for msg in self.generate_friendly_response_stream(user_input, chat_history, context,self.node):
                    yield msg
            return

        ## 友好回应或结束业务：调用 generate_friendly_response_stream 生成响应并自然记录到数据库
        if _current_intent_ in (self.INTENT_FRIENDLY_RESPONSE, self.INTENT_END_BUSINESS):
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
            return

        await self.end_business(context)

        if message_type == "interrupt" and interrupt_messages:
            merged_map = {}
            value_2_db = ""
            interrupt_id_list = []
            total_count = len(interrupt_messages)
            for item in interrupt_messages:
                interrupt_map = json.loads(item)
                thread_interrupt_id, interrupt_value = next(iter(interrupt_map.items()))
                one_interrupt_id = str(thread_interrupt_id).split(":")[1]
                interrupt_id_list.append(one_interrupt_id)
                interrupt_value_text = InterruptMessage.from_str_or_dict(interrupt_value).to_text()
                value_2_db += f"编号【{thread_interrupt_id}】待确认信息如下\n：{interrupt_value_text}\n\n\n" if total_count > 1 else interrupt_value_text
                merged_map.update(interrupt_map)

            interrupt_id = ",".join(interrupt_id_list)

            yield self.create_stream_message(
                json.dumps(merged_map, ensure_ascii=False), message_type, is_last=True, conversation_id=conversation_id
            )

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
                status_description="发生中断，需用户响应",
                node_id=self.node_id,
                workflow_id=context.workflow.workflow_id if context.workflow else None,
                is_human_generated=0,
                message_status=1,
                seq_no=context.seq_no,
                conversation_type=context.conversation_type,
                knowledge_conversation_id=knowledge_conversation_id,
                thread_id=context.thread_id,
                interrupt_id=interrupt_id
            )
            yield self.create_stream_message("", message_type=message_type, is_last=True, is_over=True, conversation_id=conversation_id)
            return

        if full_msg:
            value_2_db = ""
            interrupt_id_list = []

            if context.is_user_input_interrupt_ack:
                resume_map = json.loads(context.user_input)
                total_count = len(resume_map)
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
                model_provider=self.node.model_provider or "zbank",
                model_url=self.node.model_url if self.node.model_url else None,
                model_ext_param=self.node.model_ext_param,
                status_description=f"用户的{self.__class__.__name__}业务正在进行中",
                node_id=self.node_id,
                workflow_id=context.workflow.workflow_id if context.workflow else None,
                is_human_generated=0,
                message_status=1,
                seq_no=context.seq_no,
                conversation_type=context.conversation_type,
                knowledge_conversation_id=knowledge_conversation_id,
                thread_id=context.thread_id,
                interrupt_id=interrupt_id
            )

        if accumulated_usage and context and self.node:
            latency_ms = int((time.time() - start_time) * 1000)
            await self.log_token_usage(context, self.node, accumulated_usage, latency_ms=latency_ms)

        yield self.create_stream_message("", message_type=message_type, is_last=True, is_over=True, conversation_id=conversation_id)

    def _process_stream_chunk(self, chunk, context: ChatContext, conversation_id: str, interrupt_messages: list) -> Dict[str, Any]:
        result = {
            "stream_msg": None,
            "full_msg_add": "",
            "message_type": None,
            "accumulated_usage": None,
        }
        if chunk["type"] == "updates":
            for node_name, state_update in chunk["data"].items():
                if node_name == "__interrupt__":
                    result["message_type"] = "interrupt"
                    last_interrupt = state_update[-1] if isinstance(state_update, (tuple, list)) else state_update
                    interrupt_value = getattr(last_interrupt, 'value', str(last_interrupt))
                    interrupt_id = getattr(last_interrupt, 'id', None)
                    interrupt_value_return = {f"{context.thread_id}:{interrupt_id}": interrupt_value}
                    interrupt_messages.append(json.dumps(interrupt_value_return, ensure_ascii=False))
        elif chunk["type"] == "custom":
            custom_data = chunk["data"]
            if isinstance(custom_data, AIMessageChunk):
                if custom_data.content:
                    is_last = getattr(custom_data, 'chunk_position', 'middle') == 'last'
                    result["stream_msg"] = self.create_stream_message(
                        custom_data.content, "model", is_last=is_last, conversation_id=conversation_id
                    )
                    result["full_msg_add"] = custom_data.content
                if hasattr(custom_data, 'usage_metadata') and custom_data.usage_metadata:
                    result["accumulated_usage"] = custom_data.usage_metadata
            elif isinstance(custom_data, dict) and "message_type" in custom_data and "content" in custom_data:
                result["stream_msg"] = custom_data
                result["full_msg_add"] = custom_data.get("content", "")

        return result

    @abstractmethod
    async def _initialize_tool(self, context: ChatContext = None) -> List[BusinessAgentInfo]:
        """子类实现的初始化方法，用于构造子Agent的配置信息"""
        pass

    @abstractmethod
    async def _build_intent_analysis_prompt(self, context: ChatContext = None) -> str:
        pass

    def _parse_json_response(self, response: str) -> Optional[Dict[str, str]]:
        response_text = response.strip()
        try:
            start_idx = response_text.find("{")
            end_idx = response_text.rfind("}") + 1
            if start_idx != -1 and end_idx > start_idx:
                json_str = response_text[start_idx:end_idx]
                result = json.loads(json_str)
                intent_type = result.get("intent_type", "").strip().lower()
                friendly_response = result.get("friendly_response", "").strip()
                business_type = result.get("business_type", "").strip()
                if intent_type in self.ALL_INTENT_TYPES:
                    return {
                        "intent_type": intent_type,
                        "friendly_response": friendly_response,
                        "business_type": business_type
                    }
        except Exception as e:
            app_logger.error(f"JSON 解析错误: {e}, 原始响应: {response}")
        return None