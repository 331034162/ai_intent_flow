"""
LangGraph 强制串行工具调用示例

当 LLM 尝试同时调用多个工具时，通过自定义 ToolNode 或修改路由逻辑，
强制每次只执行一个工具调用，其余留到下一轮由 LLM 重新决定。

实现思路：
1. 自定义 tool_node，每次只执行第一个工具调用
2. 将未执行的工具调用保留在消息中，让 LLM 在下一轮继续处理
"""

import os

from langchain.tools import tool
from langgraph.graph import MessagesState, StateGraph, START, END
from langchain_openai import ChatOpenAI
from langchain.messages import SystemMessage, HumanMessage, ToolMessage
from typing import Literal

# ============ 1. 定义工具 ============

@tool
def search(query: str) -> str:
    """Search for information about a topic."""
    return f"Search results for: {query}"


@tool
def calculator(expression: str) -> str:
    """Evaluate a math expression."""
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
tools_by_name = {tool.name: tool for tool in tools}

llm = ChatOpenAI(
    base_url=DEEPSEEK_BASE_URL,
    model="deepseek-v4-pro",
    api_key=DEEPSEEK_API_KEY,
    temperature=0,
    extra_body={"thinking": {"type": "disabled"}}
)
llm_with_tools = llm.bind_tools(tools)


# ============ 3. 定义节点 ============

def llm_node(state: MessagesState):
    """LLM 节点"""
    messages = [
        SystemMessage(content="You are a helpful assistant. Use tools one at a time. "
                              "After each tool call, wait for the result before making the next call.")
    ] + state["messages"]
    response = llm_with_tools.invoke(messages)
    return {"messages": [response]}


def sequential_tool_node(state: MessagesState):
    """
    串行工具节点：每次只执行第一个工具调用
    
    如果 LLM 同时返回了多个工具调用，只执行第一个，
    其余的留到下一轮由 LLM 重新决定是否执行。
    """
    messages = state["messages"]
    last_message = messages[-1]
    
    if not last_message.tool_calls:
        return {"messages": []}
    
    # 只执行第一个工具调用
    first_tool_call = last_message.tool_calls[0]
    tool = tools_by_name[first_tool_call["name"]]
    observation = tool.invoke(first_tool_call["args"])
    
    result = [ToolMessage(content=observation, tool_call_id=first_tool_call["id"])]
    
    # 如果有多个工具调用，打印警告信息
    if len(last_message.tool_calls) > 1:
        print(f"  [串行模式] LLM 尝试同时调用 {len(last_message.tool_calls)} 个工具，"
              f"只执行第一个: {first_tool_call['name']}")
        print(f"  [串行模式] 剩余工具将在下一轮由 LLM 重新决定: "
              f"{[tc['name'] for tc in last_message.tool_calls[1:]]}")
    
    return {"messages": result}


# ============ 4. 定义路由逻辑 ============

def should_continue(state: MessagesState) -> Literal["tool_node", "__end__"]:
    """根据最后一条消息是否有工具调用决定下一步"""
    messages = state["messages"]
    last_message = messages[-1]
    
    if last_message.tool_calls:
        return "tool_node"
    return END


# ============ 5. 构建工作流 ============

builder = StateGraph(MessagesState)
builder.add_node("llm_node", llm_node)
builder.add_node("tool_node", sequential_tool_node)

builder.add_edge(START, "llm_node")
builder.add_conditional_edges("llm_node", should_continue, ["tool_node", END])
builder.add_edge("tool_node", "llm_node")

graph = builder.compile()


# ============ 6. 测试 ============

if __name__ == "__main__":
    print("=== 串行工具调用示例 ===")
    print("特点：即使 LLM 同时返回多个工具调用，每次也只执行一个\n")
    
    # 测试：同时请求天气和计算
    print("=== Test: Weather + Calculator (Sequential) ===")
    result = graph.invoke({"messages": [HumanMessage(
        content="What's the weather in Shanghai? And calculate 100 divided by 7?"
    )]})
    print()
    for msg in result["messages"]:
        msg.pretty_print()
