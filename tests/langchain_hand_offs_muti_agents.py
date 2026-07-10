import os
from typing import Literal
from typing_extensions import NotRequired

from langchain.agents import AgentState, create_agent
from langchain.messages import AIMessage, ToolMessage
from langchain.tools import tool, ToolRuntime
from langgraph.graph import StateGraph, START, END
from langgraph.types import Command
from langchain_openai import ChatOpenAI
# ============================================================================
# 1. 定义状态
# ============================================================================
class MultiAgentState(AgentState):
    active_agent: NotRequired[str]

# ============================================================================
# 2. 创建 Handoff 工具
# ============================================================================
@tool
def transfer_to_sales(runtime: ToolRuntime) -> Command:
    """转移到销售代理"""
    # 获取触发 handoff 的 AI 消息
    last_ai_message = next(
        msg for msg in reversed(runtime.state["messages"]) 
        if isinstance(msg, AIMessage)
    )
    
    # 创建 ToolMessage 完成工具调用配对
    transfer_message = ToolMessage(
        content="已从支持代理转移到销售代理",
        tool_call_id=runtime.tool_call_id,
    )
    
    return Command(
        goto="sales_agent",
        update={
            "active_agent": "sales_agent",
            "messages": [last_ai_message, transfer_message],
        },
        graph=Command.PARENT,  # 导航到父图中的节点
    )

@tool
def transfer_to_support(runtime: ToolRuntime) -> Command:
    """转移到支持代理"""
    last_ai_message = next(
        msg for msg in reversed(runtime.state["messages"]) 
        if isinstance(msg, AIMessage)
    )
    
    transfer_message = ToolMessage(
        content="已从销售代理转移到支持代理",
        tool_call_id=runtime.tool_call_id,
    )
    
    return Command(
        goto="support_agent",
        update={
            "active_agent": "support_agent",
            "messages": [last_ai_message, transfer_message],
        },
        graph=Command.PARENT,
    )

# ============================================================================
# 3. 创建 Agent
# ============================================================================
model = ChatOpenAI(
    model="deepseek-v4-pro",
    base_url="https://api.deepseek.com",
    api_key=os.getenv("DEEPSEEK_API_KEY", "your-api-key-here"),
    extra_body={"thinking": {"type": "disabled"}},
)


sales_agent = create_agent(
    model,
    tools=[transfer_to_support],
    system_prompt="""你是一个销售代理。帮助客户处理销售咨询。
如果客户询问技术问题或需要支持，使用 transfer_to_support 工具转移到支持代理。""",
)

support_agent = create_agent(
    model,
    tools=[transfer_to_sales],
    system_prompt="""你是一个技术支持代理。帮助客户解决技术问题。
如果客户询问价格或购买相关的问题，使用 transfer_to_sales 工具转移到销售代理。""",
)

# ============================================================================
# 4. 创建 Agent 节点
# ============================================================================
def call_sales_agent(state: MultiAgentState):
    """调用销售代理的节点"""
    response = sales_agent.invoke(state)
    return response

def call_support_agent(state: MultiAgentState):
    """调用支持代理的节点"""
    response = support_agent.invoke(state)
    return response

# ============================================================================
# 5. 创建路由函数
# ============================================================================
def route_after_agent(
    state: MultiAgentState,
) -> Literal["sales_agent", "support_agent", "__end__"]:
    """根据 active_agent 路由，如果 Agent 完成则结束"""
    messages = state.get("messages", [])
    
    # 检查最后一条消息 - 如果是 AIMessage 且没有工具调用，则结束
    if messages:
        last_msg = messages[-1]
        if isinstance(last_msg, AIMessage) and not last_msg.tool_calls:
            return "__end__"
    
    # 否则路由到 active_agent
    active = state.get("active_agent", "sales_agent")
    return active if active else "sales_agent"

def route_initial(state: MultiAgentState) -> Literal["sales_agent", "support_agent"]:
    """初始路由，默认到销售代理"""
    ##流程开始的时候active_agent是的None，所以就默认走到sales_agent。
    return state.get("active_agent") or "sales_agent"

# ============================================================================
# 6. 构建图
# ============================================================================
builder = StateGraph(MultiAgentState)
builder.add_node("sales_agent", call_sales_agent)
builder.add_node("support_agent", call_support_agent)

# 初始条件路由
builder.add_conditional_edges(START, route_initial, ["sales_agent", "support_agent"])

# 每个 Agent 后检查是否结束或路由到其他 Agent
builder.add_conditional_edges(
    "sales_agent", route_after_agent, ["sales_agent", "support_agent", END]
)
builder.add_conditional_edges(
    "support_agent", route_after_agent, ["sales_agent", "support_agent", END]
)

graph = builder.compile()

# ============================================================================
# 7. 测试
# ============================================================================
if __name__ == "__main__":
    result = graph.invoke({
        "messages": [
            {"role": "user", "content": "你好，我在登录账户时遇到了问题，能帮我吗？"}
        ]
    })
    
    print("\n=== 对话结果 ===")
    for msg in result["messages"]:
        msg.pretty_print()

# ============================================================================
# 总结: 多 Agent Handoff（销售 ↔ 支持互相转移）
# ============================================================================
# 核心思路: 用 StateGraph 编排两个独立 Agent，通过 handoff 工具
# （transfer_to_*）实现 Agent 间的相互转移。
#
# 关键机制:
#   1. Handoff 工具 — transfer_to_sales / transfer_to_support 返回
#      Command(goto="目标节点", graph=Command.PARENT)，从子 Agent 跳出到
#      父图中的指定节点
#   2. 工具调用配对 — handoff 工具需要手动从 runtime.state 中获取最后一条
#      AIMessage，配合 ToolMessage 一起放入 Command.update，确保消息链完整
#   3. StateGraph 编排 — 两个 Agent 分别作为图节点（sales_agent /
#      support_agent），通过条件边（add_conditional_edges）实现路由
#   4. 路由逻辑 — route_initial 决定初始入口（默认 sales），route_after_agent
#      检查最后一条消息：如果是 AIMessage 且无 tool_calls 则结束，否则按
#      active_agent 路由到对应节点
#   5. 无中间件 — 与单 Agent 方案不同，这里每个 Agent 有独立的 system_prompt
#      和工具集，通过图的节点隔离而非中间件切换
#
# 一句话概括: 两个独立 Agent 作为 StateGraph 节点，通过 handoff 工具返回
# Command(goto=..., graph=Command.PARENT) 实现 Agent 间的相互转移和路由。
#
# 对比速查:
#   | 维度         | Single Agent                          | Multi Agent                              |
#   |-------------|---------------------------------------|------------------------------------------|
#   | 架构         | 1个 Agent + middleware                | 2个 Agent + StateGraph                   |
#   | 阶段切换     | 工具返回 Command 更新 current_step     | 工具返回 Command(goto=..., graph=PARENT) |
#   | 行为切换     | 中间件动态换 prompt/tools              | 每个 Agent 固定 prompt/tools             |
#   | 路由控制     | 状态字段驱动                           | 图的条件边驱动                            |
#   | 适用场景     | 串行多阶段流程（如客服SOP）             | 多个专业 Agent 需要灵活跳转               |