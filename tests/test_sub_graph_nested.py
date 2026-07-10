"""
测试：在父图节点函数内部，手动调用编译后的子图（invoke）

与 add_node("name", sub_graph) 的区别：
- 前者：LangGraph 自动调度子图，父子图共享 State，interrupt 自动冒泡
- 本例：父图节点内部显式调用 sub_graph.invoke()，自主控制调用时机、参数转换、结果后处理

核心验证：子图内部 interrupt 是否仍能冒泡到父图？resume 恢复是否正常？
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

# 构建子图 —— 与父图共享同一 checkpointer
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
    """父图节点：手动调用子图

    与 add_node("call_sub", sub_graph) 不同，
    这里在节点函数内部显式调用 sub_graph.invoke()，
    可在调用前后添加自定义逻辑（参数转换、结果后处理等）。
    父子图共享同一 checkpointer + 同一 thread_id。
    """
    print("【父图-调用子图】开始，当前 content:", state["content"])

    # 直接复用父图的 config（同 checkpointer、同 thread_id）
    sub_result = sub_graph.invoke(
        {"content": state["content"]},
        config=config,
    )

    # 子图执行完成后，将结果写回父图 state
    print("【父图-调用子图】子图执行完成，结果 content:", sub_result.get("content", ""))
    state["content"] = sub_result.get("content", "")
    return state

# 构建父图 —— 与子图共享同一 checkpointer
parent_builder = StateGraph(GraphState)
parent_builder.add_node("p_start", parent_start_node)
parent_builder.add_node("call_subgraph", parent_call_subgraph_node)

parent_builder.add_edge(START, "p_start")
parent_builder.add_edge("p_start", "call_subgraph")
parent_builder.add_edge("call_subgraph", END)

parent_graph = parent_builder.compile(checkpointer=memory)


# ========== 运行测试 ==========
if __name__ == "__main__":
    config = {"configurable": {"thread_id": "manual_invoke_001"}}

    # ===== 第一次执行 =====
    print("=" * 60)
    print("首次运行，预期子图内部触发 interrupt")
    print("=" * 60)
    try:
        for chunk in parent_graph.stream({"content": ""}, config=config):
            print(chunk)
    except Exception as e:
        print(f"异常: {type(e).__name__}: {e}")

    # 检查状态（父子图共享同一 checkpointer + thread_id）
    parent_state = parent_graph.get_state(config)
    print(f"\n父图状态: {parent_state.values}")
    print(f"父图 tasks: {parent_state.tasks}")

    sub_state = sub_graph.get_state(config)
    print(f"\n子图状态: {sub_state.values}")
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

    final_state = parent_graph.get_state(config)
    print(f"\n父图最终状态: {final_state.values}")

    sub_final = sub_graph.get_state(config)
    print(f"子图最终状态: {sub_final.values}")

    # ========== 验证说明 ==========
    #
    # 1. 测试场景：父图节点内部手动调用 sub_graph.invoke()，
    #    子图内部节点触发 interrupt，父子图共享同一 checkpointer + 同一 thread_id
    #
    # 2. 实际运行结果：
    #    - 首次运行：p_start → call_subgraph → sub s1 → sub s2 → sub s3[interrupt] → 暂停
    #      interrupt 成功冒泡到父图，输出 __interrupt__ 事件
    #    - 恢复运行：call_subgraph 节点重入，再次调用 sub_graph.invoke()
    #      子图从 s3 中断点恢复（而非从头 s1），interrupt() 返回 resume 值
    #    - 最终状态：content = "父起点->子1->子2->子3(中断恢复:恢复中断)"
    #
    # 3. 核心机制 —— checkpoint_ns：
    #    - 共享同一 checkpointer + thread_id 时，LangGraph 通过 checkpoint_ns 区分父子图
    #    - 父图 tasks 中可看到 state.checkpoint_ns = 'call_subgraph:xxx'
    #    - 子图的 checkpoint 存储在独立命名空间下，不会与父图冲突
    #    - 直接用 sub_graph.get_state(config) 查不到子图的 interrupt（tasks 为空），
    #      因为 interrupt 由父图的命名空间管理
    #
    # 4. ⚠️ 核心机制 —— Resume 时中断节点及冒泡父节点整体重新执行：
    #    恢复时，有两类节点会重新执行：
    #    a. 子图中触发 interrupt 的节点（s3）—— 从头重新执行整个函数体
    #    b. 父图中 interrupt 冒泡到达的节点（call_subgraph）—— 从头重新执行整个函数体
    #
    #    输出证据（恢复时）：
    #      【父图-调用子图】开始                           ← call_subgraph 重新执行
    #      【子图节点3】准备触发中断                        ← s3 重新执行（interrupt前代码）
    #      （interrupt() 检测到 resume 值，穿透返回）        ← 不再阻塞
    #
    #    其他已完成节点不重执行：s1/s2 跳过，p_start 跳过
    #
    #    ⚠️ 实际影响：interrupt() 之前的代码必须具备幂等性或可重入性，
    #    因为每次恢复都会重新执行。如果有副作用（如写数据库、发请求），
    #    需要自行做幂等保护。
    #
    # 5. 与 add_node("name", sub_graph) 模式 (test_sub_graph_as_node) 的对比：
    #    ┌──────────────────┬──────────────────────────┬──────────────────────────┐
    #    │                  │ invoke 模式（本例）       │ add_node 模式             │
    #    ├──────────────────┼──────────────────────────┼──────────────────────────┤
    #    │ 子图调用方式     │ 节点内 sub_graph.invoke() │ add_node("name", sub)    │
    #    │ checkpointer     │ 需显式共享同一实例        │ 父图自动接管，子图无需设置│
    #    │ interrupt 冒泡   │ ✅ 冒泡到父图             │ ✅ 冒泡到父图             │
    #    │ Command(resume)  │ ✅ 穿透恢复               │ ✅ 穿透恢复               │
    #    │ ⚠️ 恢复时父节点  │ ✅ call_subgraph 整体重入  │ ❌ 无包裹代码，不重入     │
    #    │ 恢复时子图中断节点│ ✅ 整体重入               │ ✅ 整体重入               │
    #    │ 调用前后自定义   │ ✅ 可在 invoke 前后加逻辑  │ ❌ 子图作为黑盒节点       │
    #    │ 子图 checkpointer│ 必须与父图共享同一实例    │ 无论设什么都不影响        │
    #    └──────────────────┴──────────────────────────┴──────────────────────────┘
    #    ⚠️ 最大区别：invoke 模式恢复时，父图调用子图的节点函数整体重新执行
    #    （包括 invoke() 前后的自定义代码）；add_node 模式没有包裹代码，直接进入子图
    #    相同点：子图触发 interrupt 的节点都会从头重新执行整个函数体
    #
    # 6. 结论：
    #    ✅ 子图 invoke() 内部的 interrupt 能冒泡到父图
    #    ✅ 父图 Command(resume=...) 能穿透到子图内部恢复 interrupt
    #    ✅ 共享 checkpointer + thread_id 时，checkpoint_ns 机制避免状态冲突
    #    ✅ 子图恢复时从中断节点继续（不从头开始），其他已完成节点不重执行
    #
    # 7. 📊 嵌套调用 interrupt 冒泡全景对比（本系列3个测试文件）：
    #    ┌──────────────────────┬─────────────┬─────────────┬─────────────────┬──────────────────────┐
    #    │ 场景                 │ checkpointer │ thread_id   │ interrupt 冒泡  │ 恢复方式             │
    #    ├──────────────────────┼─────────────┼─────────────┼─────────────────┼──────────────────────┤
    #    │ 同CP + 同tid (本例)  │ 同一实例    │ 相同        │ ✅ 冒泡到父图   │ Command(resume=...)   │
    #    │ 同CP + 不同tid       │ 同一实例    │ 不同        │ ❌ 被静默吞掉   │ 必须单独恢复子图      │
    #    │ 不同CP + 同tid       │ 不同实例    │ 相同        │ ❌ 被静默吞掉   │ 必须单独恢复子图      │
    #    └──────────────────────┴─────────────┴─────────────┴─────────────────┴──────────────────────┘
    #    关键前提：interrupt 冒泡必须 同一 checkpointer + 同一 thread_id，缺一不可
    #    隔离机制：同CP+不同tid = 逻辑隔离（同一存储内 thread_id 区分）
    #             不同CP+同tid = 物理隔离（完全不同的存储实例）
    #             两者表现完全一致，interrupt 都无法冒泡
