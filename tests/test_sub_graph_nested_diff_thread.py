"""
测试：父图节点内部调用子图，共享同一 checkpointer 但使用不同 thread_id

与 test_sub_graph_nested.py 的区别：
- 前者：共享 checkpointer + 同一 thread_id，LangGraph 通过 checkpoint_ns 自动区分
- 本例：共享 checkpointer + 不同 thread_id，父子图 checkpoint 完全隔离

核心验证：不同 thread_id 下，子图 interrupt 的冒泡和恢复行为
"""
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import interrupt, Command
from typing import TypedDict


# 1. 统一状态
class GraphState(TypedDict):
    content: str


# ========== 子图：内置3个节点，第3个节点触发中断 ==========
def sub_node1(state: GraphState) -> GraphState:
    print("  【子图节点1】执行完成")
    state["content"] += "->子1"
    return state

def sub_node2(state: GraphState) -> GraphState:
    print("  【子图节点2】执行完成")
    state["content"] += "->子2"
    return state

def sub_node3(state: GraphState) -> GraphState:
    print("  【子图节点3】准备触发中断")
    user_input = interrupt("请输入确认信息，继续执行子图后续流程：")
    state["content"] += f"->子3(中断恢复:{user_input})"
    return state

# 构建子图 —— 共享 checkpointer，使用不同 thread_id
memory = MemorySaver()
sub_builder = StateGraph(GraphState)
sub_builder.add_node("s1", sub_node1)
sub_builder.add_node("s2", sub_node2)
sub_builder.add_node("s3", sub_node3)
sub_builder.add_edge(START, "s1")
sub_builder.add_edge("s1", "s2")
sub_builder.add_edge("s2", "s3")
sub_builder.add_edge("s3", END)
sub_graph = sub_builder.compile(checkpointer=memory)


# ========== 父图：节点内部手动调用子图 ==========
def parent_start_node(state: GraphState) -> GraphState:
    print("【父图起始节点】执行")
    state["content"] = "父起点"
    return state

def parent_call_subgraph_node(state: GraphState, config) -> GraphState:
    """父图节点：手动调用子图，使用不同的 thread_id"""
    print("【父图-调用子图】开始，当前 content:", state["content"])

    # 为子图构造独立的 thread_id
    parent_thread_id = config.get("configurable", {}).get("thread_id", "default")
    sub_thread_id = f"{parent_thread_id}__sub"
    sub_config = {"configurable": {"thread_id": sub_thread_id}}

    # 显式调用子图
    sub_result = sub_graph.invoke(
        {"content": state["content"]},
        config=sub_config,
    )

    print("【父图-调用子图】子图执行完成，结果 content:", sub_result.get("content", ""))
    state["content"] = sub_result.get("content", "")
    return state

# 构建父图 —— 共享同一 checkpointer
parent_builder = StateGraph(GraphState)
parent_builder.add_node("p_start", parent_start_node)
parent_builder.add_node("call_subgraph", parent_call_subgraph_node)

parent_builder.add_edge(START, "p_start")
parent_builder.add_edge("p_start", "call_subgraph")
parent_builder.add_edge("call_subgraph", END)

parent_graph = parent_builder.compile(checkpointer=memory)


# ========== 运行测试 ==========
if __name__ == "__main__":
    config = {"configurable": {"thread_id": "diff_thread_001"}}
    sub_config = {"configurable": {"thread_id": "diff_thread_001__sub"}}

    # ===== 第一次执行 =====
    print("=" * 60)
    print("首次运行，预期子图内部触发 interrupt")
    print("=" * 60)
    try:
        for chunk in parent_graph.stream({"content": ""}, config=config):
            print(chunk)
    except Exception as e:
        print(f"异常: {type(e).__name__}: {e}")

    # 分别检查父子图状态
    parent_state = parent_graph.get_state(config)
    print(f"\n父图状态: {parent_state.values}")
    print(f"父图 tasks: {parent_state.tasks}")

    sub_state = sub_graph.get_state(sub_config)
    print(f"\n子图状态 (独立thread_id): {sub_state.values}")
    print(f"子图 tasks: {sub_state.tasks}")

    # ===== 恢复执行 =====
    print("\n" + "=" * 60)
    print("恢复父图执行（Command(resume=...)）")
    print("=" * 60)
    try:
        for chunk in parent_graph.stream(Command(resume="恢复中断"), config=config):
            print(chunk)
    except Exception as e:
        print(f"异常: {type(e).__name__}: {e}")

    # 最终状态
    final_parent = parent_graph.get_state(config)
    print(f"\n父图最终状态: {final_parent.values}")

    final_sub = sub_graph.get_state(sub_config)
    print(f"子图最终状态: {final_sub.values}")

    # ========== 验证说明 ==========
    #
    # 1. 测试场景：父图节点内部调用 sub_graph.invoke()，
    #    共享同一 checkpointer 但子图使用不同 thread_id
    #
    # 2. 实际运行结果（关键发现）：
    #    - 首次运行：子图 s1 → s2 → s3[interrupt]
    #      但 interrupt 被静默吞掉！invoke() 直接返回了中断前的状态
    #      父图 content = "父起点->子1->子2"（缺少子3的中断恢复部分）
    #    - 父图没有感知到 interrupt：
    #      父图 tasks 为空，没有 __interrupt__ 事件，图直接走完
    #    - 子图自己的 get_state(sub_config) 能看到 interrupt：
    #      tasks 中有 s3 节点的 interrupt 记录
    #    - 恢复父图 Command(resume=...) 无效：父图没有 interrupt 需要恢复
    #      直接跳过，content 不变
    #
    # 3. 根本原因：
    #    不同 thread_id 时，父子图的 checkpoint 完全隔离。
    #    子图的 interrupt 发生在子图的独立 checkpoint 中，
    #    无法冒泡到父图。invoke() 捕获 GraphInterrupt 异常后
    #    直接返回了当前状态（中断前），父图以为子图正常完成。
    #
    # 4. 与同一 thread_id (test_sub_graph_nested) 的对比：
    #    ┌─────────────────┬──────────────────────┬──────────────────────┐
    #    │                 │ 同一 thread_id        │ 不同 thread_id        │
    #    ├─────────────────┼──────────────────────┼──────────────────────┤
    #    │ interrupt 冒泡  │ ✅ 冒泡到父图         │ ❌ 被静默吞掉         │
    #    │ 父图 tasks      │ 有 interrupt 记录     │ 空，无感知            │
    #    │ sub_graph.invoke │ 返回中断前状态       │ 返回中断前状态        │
    #    │ 子图 get_state  │ 看不到 tasks(命名空间) │ 能看到 tasks          │
    #    │ Command(resume)  │ ✅ 穿透恢复子图      │ ❌ 父图无 interrupt   │
    #    │ 恢复方式        │ 父图 resume 即可      │ 必须单独恢复子图      │
    #    └─────────────────┴──────────────────────┴──────────────────────┘
    #
    # 5. 结论：
    #    ❌ 不同 thread_id 下，子图 interrupt 无法冒泡到父图
    #    ❌ invoke() 静默返回中断前状态，父图以为子图正常完成
    #    ✅ 子图自身 checkpoint 保留了 interrupt 记录
    #    ❌ 父图 Command(resume=...) 无法穿透到不同 thread_id 的子图
    #    ⚠️  如需恢复，必须手动恢复子图：sub_graph.stream(Command(resume=...), sub_config)
    #       然后再次调用父图（或重新调用子图获取完整结果）
    #
    # 6. 📊 嵌套调用 interrupt 冒泡全景对比（本系列3个测试文件）：
    #    ┌──────────────────────┬─────────────┬─────────────┬─────────────────┬──────────────────────┐
    #    │ 场景                 │ checkpointer │ thread_id   │ interrupt 冒泡  │ 恢复方式             │
    #    ├──────────────────────┼─────────────┼─────────────┼─────────────────┼──────────────────────┤
    #    │ 同CP + 同tid         │ 同一实例    │ 相同        │ ✅ 冒泡到父图   │ Command(resume=...)   │
    #    │ 同CP + 不同tid (本例)│ 同一实例    │ 不同        │ ❌ 被静默吞掉   │ 必须单独恢复子图      │
    #    │ 不同CP + 同tid       │ 不同实例    │ 相同        │ ❌ 被静默吞掉   │ 必须单独恢复子图      │
    #    └──────────────────────┴─────────────┴─────────────┴─────────────────┴──────────────────────┘
    #    关键前提：interrupt 冒泡必须 同一 checkpointer + 同一 thread_id，缺一不可
    #    隔离机制：同CP+不同tid = 逻辑隔离（同一存储内 thread_id 区分）
    #             不同CP+同tid = 物理隔离（完全不同的存储实例）
    #             两者表现完全一致，interrupt 都无法冒泡
