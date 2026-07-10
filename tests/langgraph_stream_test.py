from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import interrupt, Command
from typing import TypedDict

# ============================================================================
# 1. 定义状态
# ============================================================================
class State(TypedDict):
    topic: str
    refined_topic: str
    joke: str

# ============================================================================
# 2. 定义节点函数
# ============================================================================
def refine_topic(state: State) -> dict:
    """节点1: 精炼话题"""
    topic = state["topic"]
    refined = f"[已精炼] {topic} - 这是一个很有趣的话题"
    print(f"  >> refine_topic 执行完毕, 返回: {refined}")
    return {"refined_topic": refined}

def generate_joke(state: State) -> dict:
    """节点2: 生成笑话"""
    topic = state.get("refined_topic", state["topic"])
    joke = f"关于{topic}的笑话: 为什么大家都喜欢这个话题? 因为它太有趣了!"
    print(f"  >> generate_joke 执行完毕, 返回: {joke}")
    return {"joke": joke}

def human_review(state: State) -> dict:
    """节点3: 人工审核（带中断）"""
    print(f"  >> human_review 节点被调用")
    print(f"  >> 当前笑话: {state.get('joke', 'N/A')}")
    review_result = interrupt("请审核这个笑话是否合适，回复 'approve' 或 'reject':")
    print(f"  >> 收到审核结果: {review_result}")
    if review_result == "approve":
        return {"joke": f"[已通过审核] {state['joke']}"}
    else:
        return {"joke": f"[已拒绝] {state['joke']}"}

# ============================================================================
# 3. 构建图（不带中断）
# ============================================================================
graph = (
    StateGraph(State)
    .add_node("refine_topic", refine_topic)
    .add_node("generate_joke", generate_joke)
    .add_edge(START, "refine_topic")
    .add_edge("refine_topic", "generate_joke")
    .add_edge("generate_joke", END)
    .compile(checkpointer=MemorySaver())
)

# ============================================================================
# 4. 构建带中断的图
# ============================================================================
graph_with_interrupt = (
    StateGraph(State)
    .add_node("refine_topic", refine_topic)
    .add_node("generate_joke", generate_joke)
    .add_node("human_review", human_review)
    .add_edge(START, "refine_topic")
    .add_edge("refine_topic", "generate_joke")
    .add_edge("generate_joke", "human_review")
    .add_edge("human_review", END)
    .compile(checkpointer=MemorySaver())
)

# ============================================================================
# 5. 测试多模式 stream（一次性输出 updates / values / checkpoints / custom）
# ============================================================================
def process_chunk(chunk, conversation_id="test_conv"):
    """
    按照生产代码模式处理多模式 stream 返回的 chunk。
    chunk 结构: {"type": str, "data": any}
    """
    import json
    chunk_type = chunk["type"]
    data = chunk["data"]
    result = {
        "stream_msg": None,
        "full_msg_add": "",
        "message_type": "normal",
        "accumulated_usage": None,
        "interrupt_messages": [],
    }

    if chunk_type == "updates":
        for node_name, state_update in data.items():
            if node_name == "__interrupt__":
                result["message_type"] = "interrupt"
                # state_update 可能是列表或单个对象
                last_interrupt = state_update[-1] if isinstance(state_update, (tuple, list)) else state_update
                interrupt_value = getattr(last_interrupt, 'value', str(last_interrupt))
                interrupt_id = getattr(last_interrupt, 'id', None)
                # 构建中断返回值: {thread_id:interrupt_id: interrupt_value}
                interrupt_value_return = {f"{conversation_id}:{interrupt_id}": interrupt_value}
                result["interrupt_messages"].append(json.dumps(interrupt_value_return, ensure_ascii=False))
                print(f"  [interrupt] id: {interrupt_id}")
                print(f"  [interrupt] value: {interrupt_value}")
                print(f"  [interrupt] return_dict: {interrupt_value_return}")
            else:
                print(f"  [updates] node: {node_name}")
                print(f"  [updates] state_update: {state_update}")

    elif chunk_type == "values":
        print(f"  [values] full_state: {data}")
        result["full_msg_add"] = str(data)

    elif chunk_type == "checkpoints":
        print(f"  [checkpoints] values: {data.get('values', {})}")
        print(f"  [checkpoints] step: {data.get('metadata', {}).get('step', 'N/A')}")
        print(f"  [checkpoints] next: {data.get('next', [])}")

    elif chunk_type == "custom":
        from langchain_core.messages import AIMessageChunk
        if isinstance(data, AIMessageChunk):
            if data.content:
                is_last = getattr(data, 'chunk_position', 'middle') == 'last'
                print(f"  [custom] AIMessageChunk content: {data.content}")
                print(f"  [custom] is_last: {is_last}")
                result["stream_msg"] = {
                    "content": data.content,
                    "type": "model",
                    "is_last": is_last,
                }
                result["full_msg_add"] = data.content
            if hasattr(data, 'usage_metadata') and data.usage_metadata:
                result["accumulated_usage"] = data.usage_metadata
                print(f"  [custom] usage_metadata: {data.usage_metadata}")
        elif isinstance(data, dict) and "message_type" in data and "content" in data:
            print(f"  [custom] dict message: {data}")
            result["stream_msg"] = data
            result["full_msg_add"] = data.get("content", "")
        else:
            print(f"  [custom] raw data: {data}")

    return result

if __name__ == "__main__":
    # --- 测试 1: 无中断图 — 多模式 stream ---
    print("=" * 60)
    print("测试 1: 无中断图 — stream_mode=['updates','values','checkpoints']")
    print("=" * 60)
    config1 = {"configurable": {"thread_id": "t1"}}
    for chunk in graph.stream(
        {"topic": "ice cream"},
        config=config1,
        stream_mode=["updates", "values", "checkpoints"],
        version="v2"
    ):
        process_chunk(chunk)
    print()

    # --- 测试 2: 带中断图 — 多模式 stream + 中断 ---
    print("=" * 60)
    print("测试 2: 带中断图 — stream_mode=['updates','values','checkpoints']")
    print("=" * 60)
    config2 = {"configurable": {"thread_id": "t2"}}
    for chunk in graph_with_interrupt.stream(
        {"topic": "programming"},
        config=config2,
        stream_mode=["updates", "values", "checkpoints"],
        version="v2",
    ):
        result = process_chunk(chunk)
        if result["message_type"] == "interrupt":
            print(f"  [interrupt] interrupt_messages: {result['interrupt_messages']}")

    # --- 测试 3: 恢复中断 — 多模式 stream ---
    print("\n" + "=" * 60)
    print("测试 3: 恢复中断 (approve) — stream_mode=['updates','values','checkpoints']")
    print("=" * 60)
    for chunk in graph_with_interrupt.stream(
        Command(resume="approve"),
        config=config2,
        stream_mode=["updates", "values", "checkpoints"],
        version="v2",
    ):
        process_chunk(chunk)

    # --- 测试 4: 从 checkpointer 读取历史快照 ---
    print("\n" + "=" * 60)
    print("测试 4: 从 checkpointer 读取完整快照历史")
    print("=" * 60)
    for cp_tuple in graph_with_interrupt.checkpointer.list(config2):
        cp_id = cp_tuple.config["configurable"].get("checkpoint_id")
        print(f"  checkpoint_id: {cp_id}")
        print(f"  metadata: {cp_tuple.metadata}")
        print(f"  channel_values: {cp_tuple.checkpoint.get('channel_values', {})}")
        print()
