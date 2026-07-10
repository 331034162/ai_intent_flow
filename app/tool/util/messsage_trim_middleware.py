from langchain_core.messages import trim_messages
from ...context.chat_context import ChatContext
from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from typing import Callable, Awaitable


class MessageTrimMiddleware(AgentMiddleware):
    """
    消息裁剪中间件

    使用 awrap_model_call 拦截 LLM 调用，临时裁剪消息并拼接快照，
    不修改 state，因此不会导致消息堆积或重复。
    """

    def __init__(self, context: ChatContext):
        """
        初始化中间件

        Args:
            context: 对话上下文
        """
        self.context = context

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        context = self.context

        if context and hasattr(context, 'history_max_records'):
            # 获取当前消息列表
            msgs = request.state.get("messages", [])

            # 临时拼接快照消息，不存入 state
            if context.snapshot_messages:
                msgs = context.snapshot_messages + msgs

            # 裁剪
            if len(msgs) > context.history_max_records * 2:
                msgs = trim_messages(
                    msgs,
                    max_tokens=context.history_max_records * 2,
                    strategy="last",
                    token_counter=lambda _: 1,
                    include_system=True,
                    allow_partial=False,
                    start_on="human"
                )

            # 创建新的 request，只修改 messages，不修改原始 state
            request = request.override(messages=msgs)

        # 调用下一个 handler（实际的 LLM 调用）
        return await handler(request)