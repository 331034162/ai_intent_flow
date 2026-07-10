"""
LangGraph Agent 封装类

图结构（ReAct 循环）：
  START → chatbot ─┬→ END
                   └→ tool_executor → chatbot ←┘

核心设计：
  - messages 使用 add_messages reducer，自动合并消息
  - pending_tool_calls 节点返回值直接覆盖
  - chatbot: 有 tool_calls 则到 tool_executor，否则结束
  - tool_executor: 内部通过 asyncio.gather 并发执行所有 pending 工具，执行完回到 chatbot
  - 保留 ReAct：tool_executor 完成后始终回到 chatbot，由 LLM 决定下一步
"""
from typing import Annotated, List, Dict, Any
from collections.abc import Callable, AsyncIterator
from inspect import signature, iscoroutinefunction
from typing_extensions import TypedDict
import json as _json
import asyncio
from langgraph.graph.message import add_messages
from langgraph.graph import StateGraph, START, END
from langgraph.types import StreamPart, StreamMode, Command
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.config import RunnableConfig
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, SystemMessage, ToolMessage, HumanMessage, BaseMessage
from langchain_core.tools import BaseTool
from ..context.chat_context import ChatContext
from langgraph.errors import GraphInterrupt
from langgraph.prebuilt import ToolRuntime
from ..core.logger import app_logger as app_logger
import json


# ========== State 定义 ==========
class State(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    pending_tool_calls: list  # 节点返回值直接覆盖
    _return_direct_tracker: dict  # {tool_call_id: return_direct_bool}


# ========== Agent 类 ==========

class LangGraphAgent:
    """
    通用 LangGraph Agent 封装

    使用方式：
        from langchain_openai import ChatOpenAI
        llm = ChatOpenAI(model="deepseek-chat", api_key="...", base_url="...")
        agent = LangGraphAgent(model=llm, tools=[get_weather, delete_database])
        response = await agent.astream(context, config)
    """

    def __init__(
        self,
        model: BaseChatModel,
        tools: List[BaseTool],
        system_prompt: str | None = None,
        checkpointer: BaseCheckpointSaver | None = None,
        use_paraller: bool = False,
    ):
        if isinstance(model, str):
            raise ValueError(
                "model 传字符串时需要额外提供 api_key/base_url，请直接传入 BaseChatModel 实例"
            )
        self.llm: BaseChatModel = model
        self.tools: List[BaseTool] = tools
        self.tool_func_map: Dict[str, Callable] = {
            t.name: (t.func if t.func is not None else t.coroutine) for t in self.tools
        }
        self.tool_return_direct_map: Dict[str, bool] = {
            t.name: getattr(t, "return_direct", False) for t in self.tools
        }
        self._tool_inject_map: Dict[str, Dict[str, str]] = {}
        for t in self.tools:
            inject_info: Dict[str, str] = {}
            func = t.func if t.func is not None else t.coroutine
            for param_name, param in signature(func).parameters.items():
                param_type = param.annotation
                if param_type is not None:
                    try:
                        if isinstance(param_type, type) and issubclass(param_type, ToolRuntime):
                            inject_info[param_name] = "tool_runtime"
                        elif hasattr(param_type, "__origin__") and param_type.__origin__ is ToolRuntime:
                            inject_info[param_name] = "tool_runtime"
                    except TypeError:
                        pass
                if param_name == "context" and param_type is not None:
                    inject_info[param_name] = "context"
            if inject_info:
                self._tool_inject_map[t.name] = inject_info
        self.system_prompt: SystemMessage | None = (
            SystemMessage(content=system_prompt) if system_prompt else None
        )
        self.snapshot_messages: list | None = None
        self.use_paraller = use_paraller
        self.checkpointer: BaseCheckpointSaver | None = checkpointer
        self.llm_with_tools = self.llm.bind_tools(self.tools)
        self._graph = self._build_graph()

    # ========== 构建图 ==========

    def _build_graph(self):
        builder = StateGraph(State)
        builder.add_node("chatbot", self._chatbot_node)
        builder.add_node("tool_executor", self._tool_executor_node)

        builder.add_edge(START, "chatbot")
        builder.add_conditional_edges("chatbot", self._route_from_chatbot)
        builder.add_edge("tool_executor", "chatbot")

        return builder.compile(checkpointer=self.checkpointer)

    # ========== 节点 ==========

    @staticmethod
    def _trim_messages(messages: list, max_records: int) -> list:
        """截取最近 max_records*2 条消息，确保第一条是 HumanMessage，避免割裂。"""
        limit = max_records * 2
        if len(messages) <= limit:
            return messages
        start = len(messages) - limit
        for i in range(start, len(messages)):
            if isinstance(messages[i], HumanMessage):
                return messages[i:]
        for i in range(start - 1, -1, -1):
            if isinstance(messages[i], HumanMessage):
                return messages[i:]
        return messages

    @staticmethod
    def _format_result(result) -> str:
        """将工具返回值转为字符串"""
        if isinstance(result, str):
            return result
        if isinstance(result, (int, float, bool)):
            return str(result)
        try:
            return _json.dumps(result, ensure_ascii=False)
        except (TypeError, ValueError):
            return str(result)

    async def _chatbot_node(self, state: State, config: RunnableConfig) -> dict:
        """LLM 决策节点"""
        return_direct_tracker = state.get("_return_direct_tracker", {})

        # tool_executor 执行完所有工具后，检查是否全部为 return_direct
        if return_direct_tracker and all(return_direct_tracker.values()):
            return {"_return_direct_tracker": {}}

        messages = state.get("messages", [])
        if self.snapshot_messages:
            messages = self.snapshot_messages + messages
        context: ChatContext | None = config.get("configurable", {}).get("context")
        if context and hasattr(context, "history_max_records") and context.history_max_records > 0:
            messages = self._trim_messages(messages, context.history_max_records)
        if self.system_prompt:
            messages = [self.system_prompt] + messages
        response = await self.llm_with_tools.ainvoke(messages)

        update: dict = {"messages": [response], "_return_direct_tracker": {}}
        if response.tool_calls:
            update["pending_tool_calls"] = response.tool_calls

        return update

    async def _tool_executor_node(self, state: State, config: RunnableConfig) -> dict:
        """工具执行节点：内部通过 asyncio.gather 并发执行所有 pending 工具"""
        context: ChatContext | None = config.get("configurable", {}).get("context")
        pending = state.get("pending_tool_calls", [])

        if not pending:
            app_logger.warning("tool_executor 收到空 pending_tool_calls，跳过")
            return {}

        async def _execute_one(tool_call: dict) -> tuple:
            """执行单个工具，返回 (tool_call_id, return_direct, tool_msg, ai_chunk_or_none)"""
            tool_name = tool_call.get("name", "unknown")
            tool_args = tool_call.get("args", {})
            tool_call_id = tool_call.get("id", "")
            return_direct = self.tool_return_direct_map.get(tool_name, False)

            try:
                func = self.tool_func_map.get(tool_name)
                if not func:
                    result_content = f"未知工具: {tool_name}"
                else:
                    inject_info = self._tool_inject_map.get(tool_name, {})
                    inject_kwargs: Dict[str, Any] = {}
                    for param_name, inject_type in inject_info.items():
                        if inject_type == "tool_runtime":
                            inject_kwargs[param_name] = ToolRuntime(
                                state=state,
                                tool_call_id=tool_call_id,
                                config=config,
                                context=context,
                                store=None,
                                stream_writer=lambda _: None,
                            )
                        elif inject_type == "context":
                            inject_kwargs[param_name] = context
                    call_result = func(**tool_args, **inject_kwargs)
                    if iscoroutinefunction(func):
                        result_content = await call_result
                    else:
                        result_content = call_result
            except GraphInterrupt:
                raise
            except Exception as e:
                app_logger.error(f"工具执行异常：{tool_name}", exc_info=e)
                result_content = f"工具执行异常：{tool_name}，错误：{e}"

            tool_msg = ToolMessage(content=self._format_result(result_content), tool_call_id=tool_call_id)
            ai_chunk = None
            if return_direct:
                ai_chunk = AIMessageChunk(
                    content=self._format_result(result_content),
                    chunk_position="last"
                )

            return (tool_call_id, return_direct, tool_msg, ai_chunk)

        # 执行工具：串行或并行
        if self.use_paraller:
            results = await asyncio.gather(*[_execute_one(tc) for tc in pending])
        else:
            results = [await _execute_one(tc) for tc in pending]

        # 收集结果
        adding_messages = []
        tracker = {}
        for tool_call_id, return_direct, tool_msg, ai_chunk in results:
            adding_messages.append(tool_msg)
            tracker[tool_call_id] = return_direct
            if ai_chunk:
                adding_messages.append(ai_chunk)

        return {
            "messages": adding_messages,
            "pending_tool_calls": [],
            "_return_direct_tracker": tracker,
        }

    # ========== 路由 ==========

    def _route_from_chatbot(self, state: State):
        """有 pending_tool_calls 则到 tool_executor，否则结束"""
        pending = state.get("pending_tool_calls", [])
        if not pending:
            return END
        return "tool_executor"

    # ========== 对外接口 ==========

    async def aget_state(self, config: RunnableConfig, **kwargs):
        """获取指定 thread_id 的当前状态快照"""
        return await self._graph.aget_state(config, **kwargs)

    async def astream(
        self,
        context: ChatContext,
        config: RunnableConfig,
        stream_mode: StreamMode | None = None,
        # 如果不使用 checkpointer（无状态持久化），建议设置为 True 以保留历史对话效果
        append_local_history: bool = False,
    ) -> AsyncIterator[StreamPart]:
        """执行一轮对话（含 interrupt 恢复），流式返回"""
        if stream_mode is None:
            stream_mode = ["messages", "updates"]
        configurable = config.setdefault("configurable", {})
        configurable["context"] = context

        if context and context.is_user_input_interrupt_ack:
            resume_map_origin = json.loads(context.user_input)
            resume_map = {}
            for key, value in resume_map_origin.items():
                interrupt_id = str(key).split(":")[1]
                resume_map[interrupt_id] = value
            app_logger.info(f"确认信息: {resume_map}")
            async for chunk in self._graph.astream(
                Command(resume=resume_map),
                config=config,
                stream_mode=stream_mode,
                version="v2",
            ):
                yield chunk
        else:
            messages = []
            if append_local_history and context.chat_history:
                for msg in context.chat_history:
                    role = msg.get("role", "")
                    content = msg.get("content", "")
                    if role == "user":
                        messages.append(HumanMessage(content=content))
                    elif role == "assistant":
                        messages.append(AIMessage(content=content))
            messages.append(HumanMessage(content=context.user_input))
            async for chunk in self._graph.astream(
                    {"messages": messages, "pending_tool_calls": []},
                    config=config,
                    stream_mode=stream_mode,
                    version="v2",
                ):
                yield chunk