"""LangGraph Agent Builder
构建 ReAct 循环子图（chatbot → tool_executor 循环），用于 LangGraph 多 Agent 架构。
支持两种使用方式：
1. build_standalone()：构建独立的 ReAct 循环图
2. add_to_graph()：将 ReAct 循环节点添加到已有的父图中（保持流式输出天然可用）

核心设计：
- tool_executor 内部处理串行/并行：use_paraller=True 时用 asyncio.gather 并发执行所有工具
- return_direct 控制：全为 return_direct 时跳过 LLM 总结直接返回；否则回 chatbot 让 LLM 总结
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from inspect import iscoroutinefunction, signature
from typing import Dict, Optional, Any, List
import json as _json
import asyncio

from ..context.chat_context import ChatContext
from ..core.logger import app_logger
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, AIMessageChunk, ToolMessage, BaseMessage
from langchain_openai import ChatOpenAI
from langgraph.config import RunnableConfig
from langchain_core.tools import BaseTool
from langgraph.prebuilt import ToolRuntime
from langgraph.errors import GraphInterrupt
from typing import Annotated
from langgraph.config import get_stream_writer
from datetime import datetime
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END


@dataclass
class WarappedMessage:
    message: BaseMessage
    agent_name: str
    create_at: datetime


def add_wrapped_messages(existing: List, new: List) -> List:
    """WarappedMessage 列表 reducer：
    - 新消息的 message.id 与已有消息重复 → 替换
    - 否则 → 追加
    """
    if not new:
        return existing
    if not existing:
        return list(new)
    existing_ids = {wm.message.id for wm in existing if hasattr(wm.message, 'id') and wm.message.id}
    result = list(existing)
    for wm in new:
        msg_id = getattr(wm.message, 'id', None)
        if msg_id and msg_id in existing_ids:
            result = [wm if item.message.id == msg_id else item for item in result]
        else:
            result.append(wm)
    return result


class State(TypedDict):
    messages: Annotated[List[WarappedMessage], add_wrapped_messages]
    pending_tool_calls: list  # 节点返回值直接覆盖
    current_input: str  # 用户当前输入
    exe_step: int  # 当前轮次执行步数，每次 process_user_input 重置为 0
    _return_direct_tracker: dict  # {tool_call_id: return_direct_bool}，工具执行后设置

    business_type: Optional[str]
    intent_type: Optional[str]
    friendly_response: Optional[str]


@dataclass
class AgentConfig:
    """Agent 配置信息"""
    agent_name: str
    system_prompt: str
    tools: List[BaseTool]
    llm: ChatOpenAI
    use_all_messages: bool = True
    use_paraller: bool = False


class LangGraphAgentBuilder:
    """构建 ReAct 循环子图的工具类
    
    每个业务 Agent 对应一个 LangGraphAgentBuilder 实例，
    内含 chatbot → tool_executor 循环。
    统一使用 messages（WarappedMessage 列表）存储所有消息，按 agent_name 筛选各 Agent 私有历史。
    
    并发设计：
    - tool_executor 内部通过 asyncio.gather 处理并发（use_paraller=True）
    - 不再使用 LangGraph 的 Send 机制，避免并行分支独立触发条件边的问题
    """

    def __init__(self, config: AgentConfig):
        self.config = config
        self._tool_map = self._build_tool_map(config.tools)
        self._llm_with_tools = config.llm.bind_tools(config.tools)

    def build_standalone(self, checkpointer=None):
        """构建独立的 ReAct 循环图（START → chatbot → tool_executor → chatbot 循环 → END）"""
        builder = StateGraph(State)
        builder.add_node("chatbot", self._make_chatbot_node())
        builder.add_node("tool_executor", self._make_tool_executor_node())
        builder.add_conditional_edges("chatbot", self._make_route_from_chatbot("tool_executor"))
        builder.add_edge("tool_executor", "chatbot")
        builder.add_edge(START, "chatbot")
        return builder.compile(checkpointer=checkpointer)

    def add_to_graph(self, builder: StateGraph, name_prefix: str = "") -> Dict[str, str]:
        """将 ReAct 循环节点添加到已有的 StateGraph 中
        
        节点以 name_prefix_chatbot / name_prefix_tool_executor 命名，
        保持与父图同一层级，流式输出天然可用。

        Args:
            builder: 父图 StateGraph builder
            name_prefix: 节点名称前缀（如 agent_name）

        Returns:
            dict: {"chatbot_name": ..., "tool_executor_name": ...}
        """
        chatbot_name = f"{name_prefix}_chatbot" if name_prefix else "chatbot"
        tool_executor_name = f"{name_prefix}_tool_executor" if name_prefix else "tool_executor"

        builder.add_node(chatbot_name, self._make_chatbot_node())
        builder.add_node(tool_executor_name, self._make_tool_executor_node())
        builder.add_conditional_edges(chatbot_name, self._make_route_from_chatbot(tool_executor_name))
        builder.add_edge(tool_executor_name, chatbot_name)

        return {"chatbot_name": chatbot_name, "tool_executor_name": tool_executor_name}

    def _make_chatbot_node(self):
        """创建 chatbot 节点：astream 流式调用 + get_stream_writer 推送"""
        agent_name = self.config.agent_name
        system_prompt = self.config.system_prompt
        llm_with_tools = self._llm_with_tools
        use_all_messages = self.config.use_all_messages

        async def chatbot_node(state: State, config: RunnableConfig):
            current_input = state.get("current_input", "")
            exe_step = state.get("exe_step", 0)
            return_direct_tracker = state.get("_return_direct_tracker", {})
            context: ChatContext | None = config.get("configurable", {}).get("context")

            # tool_executor 执行完所有工具后，检查是否全部为 return_direct
            if return_direct_tracker and all(return_direct_tracker.values()):
                # 全部是 return_direct，不调用 LLM，直接结束
                # AIMessageChunk 已在 tool_executor 中通过 writer 推送
                return {"_return_direct_tracker": {}}

            # 正常调用 LLM
            if use_all_messages:
                # use_all_messages=True：从 messages 获取全局历史
                msgs = [wm.message for wm in state.get("messages", [])]
                # 拼接快照（merge 模式的核心特性，已在 process_user_input 中加载）
                if context and hasattr(context, "snapshot_messages") and context.snapshot_messages:
                    msgs = [wm.message for wm in context.snapshot_messages] + msgs
            else:
                # use_all_messages=False：从 messages 按 agent_name 筛选私有历史
                msgs = [wm.message for wm in state.get("messages", []) if wm.agent_name == agent_name]
                # 从快照中按 agent_name 筛选存量历史
                if context and hasattr(context, "snapshot_messages") and context.snapshot_messages:
                    snapshot_agent_msgs = [wm.message for wm in context.snapshot_messages if wm.agent_name == agent_name]
                    if snapshot_agent_msgs:
                        msgs = snapshot_agent_msgs + msgs

            # 统一：exe_step == 0 时追加当前用户输入
            if exe_step == 0:
                msgs.append(HumanMessage(content=current_input))

            # 裁剪
            if context and hasattr(context, "history_max_records") and context.history_max_records > 0:
                msgs = self._trim_messages(msgs, context.history_max_records)

            # 添加 SystemMessage
            if system_prompt:
                msgs = [SystemMessage(content=system_prompt)] + msgs

            # 使用 astream 流式调用 LLM，通过 get_stream_writer 推送每个 token
            writer = get_stream_writer()
            chunks: list[AIMessageChunk] = []
            async for chunk in llm_with_tools.astream(msgs, config=config):
                chunks.append(chunk)
                # 推送每个 token chunk 到 custom stream
                if chunk.content:
                    writer(chunk)

            if not chunks:
                # 降级为 ainvoke
                response = await llm_with_tools.ainvoke(msgs, config=config)
            else:
                # 合并 chunks 为完整 AIMessage
                full = chunks[0]
                for c in chunks[1:]:
                    full = full + c
                response = AIMessage(
                    content=full.content,
                    tool_calls=getattr(full, "tool_calls", []),
                    usage_metadata=getattr(full, "usage_metadata", None),
                    response_metadata=getattr(full, "response_metadata", {}),
                    id=getattr(full, "id", None),
                    name=getattr(full, "name", None),
                )

            # 更新 messages：用 WarappedMessage 包装，统一存储
            now = datetime.now()
            new_wrapped_msgs = []
            if exe_step == 0:
                new_wrapped_msgs.append(WarappedMessage(
                    message=HumanMessage(content=current_input),
                    agent_name=agent_name,
                    create_at=now,
                ))
            new_wrapped_msgs.append(WarappedMessage(
                message=response,
                agent_name=agent_name,
                create_at=now,
            ))

            update: dict = {
                "messages": new_wrapped_msgs,
                "exe_step": exe_step + 1,
                "_return_direct_tracker": {},
            }
            if response.tool_calls:
                update["pending_tool_calls"] = response.tool_calls
            return update

        return chatbot_node

    def _make_tool_executor_node(self):
        """创建 tool_executor 节点：内部处理串行/并行工具执行"""
        agent_name = self.config.agent_name
        tool_map = self._tool_map
        use_paraller = self.config.use_paraller

        async def tool_executor_node(state: State, config: RunnableConfig):
            context: ChatContext | None = config.get("configurable", {}).get("context")
            pending = state.get("pending_tool_calls", [])

            if not pending:
                app_logger.warning(f"[{agent_name}] tool_executor 收到空 pending_tool_calls，跳过")
                return {}

            tool_func_map = tool_map.get("tool_func_map", {})
            tool_return_direct_map = tool_map.get("tool_return_direct_map", {})
            tool_inject_map = tool_map.get("tool_inject_map", {})

            async def _execute_one(tool_call: dict) -> tuple:
                """执行单个工具，返回 (tool_call_id, return_direct, tool_msg, ai_chunk_or_none)"""
                tool_name = tool_call.get("name", "unknown")
                tool_args = tool_call.get("args", {})
                tool_call_id = tool_call.get("id", "")
                return_direct = tool_return_direct_map.get(tool_name, False)

                try:
                    func = tool_func_map.get(tool_name)
                    if not func:
                        result_content = f"未知工具: {tool_name}"
                    else:
                        inject_info = tool_inject_map.get(tool_name, {})
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
                    app_logger.error(f"[{agent_name}] 工具执行异常：{tool_name}", exc_info=e)
                    result_content = f"工具执行异常：{tool_name}，错误：{e}"

                tool_msg = ToolMessage(content=self._format_result(result_content), tool_call_id=tool_call_id)
                ai_chunk = None
                if return_direct:
                    ai_chunk = AIMessageChunk(
                        content=self._format_result(result_content),
                        chunk_position="last"
                    )
                    # 推送 return_direct 结果到 custom stream
                    writer = get_stream_writer()
                    writer(ai_chunk)

                return (tool_call_id, return_direct, tool_msg, ai_chunk)

            # 执行工具：串行或并行
            if use_paraller:
                results = await asyncio.gather(*[_execute_one(tc) for tc in pending])
            else:
                results = [await _execute_one(tc) for tc in pending]

            # 收集结果
            adding_messages = []
            tracker = {}
            for tool_call_id, return_direct, tool_msg, ai_chunk in results:
                adding_messages.append(WarappedMessage(message=tool_msg, agent_name=agent_name, create_at=datetime.now()))
                tracker[tool_call_id] = return_direct
                if ai_chunk:
                    adding_messages.append(WarappedMessage(message=ai_chunk, agent_name=agent_name, create_at=datetime.now()))

            return {
                "messages": adding_messages,
                "pending_tool_calls": [],
                "_return_direct_tracker": tracker,
            }

        return tool_executor_node

    def _make_route_from_chatbot(self, tool_executor_name: str = "tool_executor"):
        """创建 chatbot 节点后的路由函数
        
        Args:
            tool_executor_name: tool_executor 节点的完整名称（可能带前缀）
        """
        def route_from_chatbot(state: State):
            pending = state.get("pending_tool_calls", [])
            if not pending:
                return END
            return tool_executor_name
        return route_from_chatbot

    @staticmethod
    def _build_tool_map(tools: List[BaseTool]) -> Dict:
        """构建工具函数映射和注入信息"""
        tool_func_map: Dict[str, Callable] = {}
        tool_return_direct_map: Dict[str, bool] = {}
        tool_inject_map: Dict[str, Dict[str, str]] = {}

        for t in tools:
            tool_func_map[t.name] = (t.func if t.func is not None else t.coroutine)
            tool_return_direct_map[t.name] = getattr(t, "return_direct", False)
            inject_info: Dict[str, str] = {}
            func = t.func if t.func is not None else t.coroutine
            if func:
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
                tool_inject_map[t.name] = inject_info

        return {
            "tool_func_map": tool_func_map,
            "tool_return_direct_map": tool_return_direct_map,
            "tool_inject_map": tool_inject_map,
        }

    @staticmethod
    def _trim_messages(messages: list, max_records: int) -> list:
        """截取最近 max_records*2 条消息，确保第一条是 HumanMessage，避免割裂。
        
        从后往前取 limit 条，再从该范围内找到第一个 HumanMessage 作为起始位置，
        保证不会出现开头的 ToolMessage/AIMessage 孤儿消息。
        """
        limit = max_records * 2
        if len(messages) <= limit:
            return messages
        # 从后往前扫描 limit 条，找第一个 HumanMessage 作为起始
        start = len(messages) - limit
        for i in range(start, len(messages)):
            if isinstance(messages[i], HumanMessage):
                return messages[i:]
        # 极端情况：limit 条内没有 HumanMessage，逐步向前扩大范围查找
        for i in range(start - 1, -1, -1):
            if isinstance(messages[i], HumanMessage):
                return messages[i:]
        # 兜底：全都没有 HumanMessage，返回原始消息
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