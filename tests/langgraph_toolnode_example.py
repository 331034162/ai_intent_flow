"""
LangGraph ToolNode 完整示例

ToolNode 是 LangGraph 的预构建节点，用于在工作流中执行工具调用。
它自动处理并行工具执行、错误处理和状态注入。

工作流程：
START -> llm_node -> (有工具调用?) -> tool_node -> llm_node -> ... -> END
                              (无工具调用?) -> END
"""

import os

from langchain.tools import tool
from langgraph.prebuilt import ToolNode
from langgraph.graph import MessagesState, StateGraph, START, END
from langchain_openai import ChatOpenAI
from langchain.messages import SystemMessage, HumanMessage
from typing import Literal

# ============ 1. 定义工具 ============

@tool
def search(query: str) -> str:
    """Search for information about a topic."""
    return f"Search results for: {query}\n- Result 1: Related information found\n- Result 2: More details available"


@tool
def calculator(expression: str) -> str:
    """Evaluate a math expression. Example: 2 + 3 * 4"""
    try:
        return str(eval(expression))
    except Exception as e:
        return f"Error: {e}"


@tool
def get_weather(city: str) -> str:
    """Get the current weather for a city."""
    return f"Weather in {city}: Sunny, 25°C"


# ============ 2. 配置 LLM ============

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "your-api-key-here")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"

tools = [search, calculator, get_weather]

llm = ChatOpenAI(
    base_url=DEEPSEEK_BASE_URL,
    model="deepseek-v4-pro",
    api_key=DEEPSEEK_API_KEY,
    temperature=0,
    extra_body={"thinking": {"type": "disabled"}}
)
# 绑定工具到 LLM
# parallel_tool_calls=False 禁止并行调用，工具会按顺序逐个执行（通过ToolNode的形式调用，parallel_tool_calls并不起任何作用）
llm_with_tools = llm.bind_tools(tools, parallel_tool_calls=False)


# ============ 3. 定义节点 ============

def llm_node(state: MessagesState):
    """LLM 节点：接收用户消息，决定是否调用工具"""
    messages = [
        SystemMessage(content="You are a helpful assistant. Use the available tools to answer questions. "
                              "Use search for information, calculator for math, and get_weather for weather.")
    ] + state["messages"]

    response = llm_with_tools.invoke(messages)
    return {"messages": [response]}


# ToolNode 是预构建节点，自动执行工具调用
# 无需手动编写 tool_node 函数，直接使用 ToolNode(tools)
tool_node = ToolNode(tools)


# ============ 4. 定义路由逻辑 ============

def should_continue(state: MessagesState) -> Literal["tool_node", "__end__"]:
    """根据 LLM 是否返回工具调用决定下一步"""
    messages = state["messages"]
    last_message = messages[-1]

    if last_message.tool_calls:
        return "tool_node"
    return END


# ============ 5. 构建工作流 ============

builder = StateGraph(MessagesState)

# 添加节点
builder.add_node("llm_node", llm_node)
builder.add_node("tool_node", tool_node)

# 添加边
builder.add_edge(START, "llm_node")
builder.add_conditional_edges("llm_node", should_continue, ["tool_node", END])
builder.add_edge("tool_node", "llm_node")

# 编译图
graph = builder.compile()


# ============ 6. 测试 ============

if __name__ == "__main__":
    # 打印工作流结构
    print("=== Workflow Structure ===")
    print(graph.get_graph().draw_mermaid())
    print()

    # 测试用例 1: 使用计算器
    print("=== Test 1: Calculator ===")
    result = graph.invoke({"messages": [HumanMessage(content="What is 15 * 8 + 23?")]})
    for msg in result["messages"]:
        msg.pretty_print()
    print()

    # 测试用例 2: 使用搜索工具
    print("=== Test 2: Search ===")
    result = graph.invoke({"messages": [HumanMessage(content="Search for information about quantum computing")]})
    for msg in result["messages"]:
        msg.pretty_print()
    print()

    # 测试用例 3: 使用天气工具
    print("=== Test 3: Weather ===")
    result = graph.invoke({"messages": [HumanMessage(content="What's the weather in Beijing?")]})
    for msg in result["messages"]:
        msg.pretty_print()
    print()

    # 测试用例 4: 同时调用天气和计算（并行工具调用）
    print("=== Test 4: Weather + Calculator (Parallel) ===")
    result = graph.invoke({"messages": [HumanMessage(
        content="What's the weather in Shanghai? And calculate 100 divided by 7?"
    )]})
    for msg in result["messages"]:
        msg.pretty_print()
