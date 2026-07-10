"""
测试：将编译后的子图直接作为父图节点，子图内部触发 interrupt

核心验证：
- 子图作为父图节点时，子图内部的 interrupt 能否冒泡到父图
- 父图通过 Command(resume=...) 恢复时，能否穿透到子图内部中断点
- 子图内部条件分支 + interrupt 的组合场景

⚠️ 关键机制 —— Resume 时中断节点整体重新执行：
  当子图中的节点（如 sub_b_priority）调用 interrupt() 触发中断后，
  父图通过 Command(resume=值) 恢复时：
  1. 父图的 "process" 节点（即子图B）重新执行
  2. 子图B内部：已完成的节点（check）不重复执行，但触发中断的节点（priority_process）
     会从头重新执行整个函数体 —— 包括 interrupt() 之前的代码
  3. 到达 interrupt() 时，检测到 resume 值，直接穿透返回，不再阻塞
  4. 因此 interrupt() 之前的代码必须有幂等性或可重入性

  输出证据：恢复时先打印 "准备触发中断"，再打印 "中断恢复，用户输入: yes"
  说明 interrupt() 前的 print 确实重新执行了，但 interrupt() 本身不再阻断
"""
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import interrupt, Command
from typing import TypedDict, Annotated
from operator import add


# ========== 共享状态 ==========
class GraphState(TypedDict):
    content: str
    steps: Annotated[list[str], add]  # 累积执行步骤记录


# ========== 子图A：预处理（2个节点串联） ==========
def sub_a_normalize(state: GraphState) -> dict:
    """标准化输入内容"""
    print("  [子图A-标准化] 执行")
    return {
        "content": state["content"].strip().upper(),
        "steps": ["A_normalize"],
    }


def sub_a_enrich(state: GraphState) -> dict:
    """丰富上下文信息"""
    print("  [子图A-丰富] 执行")
    return {
        "content": f"[已处理]{state['content']}",
        "steps": ["A_enrich"],
    }


sub_a_builder = StateGraph(GraphState)
sub_a_builder.add_node("normalize", sub_a_normalize)
sub_a_builder.add_node("enrich", sub_a_enrich)
sub_a_builder.add_edge(START, "normalize")
sub_a_builder.add_edge("normalize", "enrich")
sub_a_builder.add_edge("enrich", END)
sub_a_graph = sub_a_builder.compile()


# ========== 子图B：核心处理（含条件分支 + interrupt） ==========
def sub_b_check(state: GraphState) -> dict:
    """检查内容是否包含关键词"""
    print("  [子图B-检查] 执行")
    has_keyword = "IMPORTANT" in state["content"]
    return {"steps": [f"B_check(有关键词={has_keyword})"]}


def sub_b_route(state: GraphState) -> str:
    """根据检查结果路由"""
    if "IMPORTANT" in state["content"]:
        return "priority_process"
    return "normal_process"


def sub_b_priority(state: GraphState) -> dict:
    """高优先级处理 —— 含 interrupt，需用户确认"""
    print("  [子图B-高优先级处理] 准备触发中断")
    # interrupt 之前的代码会重入，此处只做 print，无需幂等保护
    confirm = interrupt("高优先级内容，确认处理？(输入yes继续)")
    print(f"  [子图B-高优先级处理] 中断恢复，用户输入: {confirm}")
    if confirm == "yes":
        return {
            "content": f"⚡{state['content']}⚡",
            "steps": [f"B_priority(确认={confirm})"],
        }
    else:
        return {
            "content": f"❌{state['content']}❌(已拒绝)",
            "steps": [f"B_priority(确认={confirm},已拒绝)"],
        }


def sub_b_normal(state: GraphState) -> dict:
    """普通处理"""
    print("  [子图B-普通处理] 执行")
    return {
        "content": f"|{state['content']}|",
        "steps": ["B_normal"],
    }


memory = MemorySaver()

sub_b_builder = StateGraph(GraphState)
sub_b_builder.add_node("check", sub_b_check)
sub_b_builder.add_node("priority_process", sub_b_priority)
sub_b_builder.add_node("normal_process", sub_b_normal)
sub_b_builder.add_edge(START, "check")
sub_b_builder.add_conditional_edges("check", sub_b_route)
sub_b_builder.add_edge("priority_process", END)
sub_b_builder.add_edge("normal_process", END)
# 子图B需要checkpointer支持interrupt
sub_b_graph = sub_b_builder.compile(checkpointer=None)##checkpointer=memory，子图作为父图的节点时，checkpointer不传值，或者传None，或者传父图的checkpointer执行结果是一样的


# ========== 父图：串联子图A → 子图B ==========
def parent_init(state: GraphState) -> dict:
    """父图初始化"""
    print("[父图-初始化] 执行")
    return {"content": state.get("content", ""), "steps": ["init"]}


def parent_finalize(state: GraphState) -> dict:
    """父图收尾"""
    print("[父图-收尾] 执行")
    return {
        "content": f"✅ {state['content']} ✅",
        "steps": ["finalize"],
    }


parent_builder = StateGraph(GraphState)
parent_builder.add_node("init", parent_init)
parent_builder.add_node("preprocess", sub_a_graph)    # 子图A作为节点
parent_builder.add_node("process", sub_b_graph)         # 子图B作为节点（含interrupt）
parent_builder.add_node("finalize", parent_finalize)

parent_builder.add_edge(START, "init")
parent_builder.add_edge("init", "preprocess")
parent_builder.add_edge("preprocess", "process")
parent_builder.add_edge("process", "finalize")
parent_builder.add_edge("finalize", END)

parent_graph = parent_builder.compile(checkpointer=memory)


# ========== 运行测试 ==========
if __name__ == "__main__":

    # --- 测试1：普通内容（走 normal 分支，无中断）---
    print("=" * 60)
    print("测试1：普通内容，无中断")
    print("=" * 60)
    config1 = {"configurable": {"thread_id": "sub_node_interrupt_001"}}
    for chunk in parent_graph.stream({"content": "  hello world  ", "steps": []}, config=config1):
        print(chunk)
    final1 = parent_graph.get_state(config1)
    print(f"\n最终内容: {final1.values['content']}")
    print(f"执行步骤: {final1.values['steps']}")

    # --- 测试2：含关键词内容（走 priority 分支，触发 interrupt）---
    print("\n" + "=" * 60)
    print("测试2：含关键词内容，触发中断")
    print("=" * 60)
    config2 = {"configurable": {"thread_id": "sub_node_interrupt_002"}}

    # 第一次运行，预期在子图B的 priority_process 节点中断
    print("--- 首次运行（预期中断） ---")
    for chunk in parent_graph.stream({"content": " this is IMPORTANT ", "steps": []}, config=config2):
        print(chunk)

    # 检查中断状态
    state2 = parent_graph.get_state(config2)
    print(f"\n中断后状态 content: {state2.values.get('content', '')}")
    print(f"中断后状态 steps: {state2.values.get('steps', [])}")
    print(f"待恢复的中断: {state2.tasks}")

    # 恢复执行，传入 "yes" 确认
    print("\n--- 恢复执行（传入 yes 确认） ---")
    for chunk in parent_graph.stream(Command(resume="yes"), config=config2):
        print(chunk)

    final2 = parent_graph.get_state(config2)
    print(f"\n最终内容: {final2.values['content']}")
    print(f"执行步骤: {final2.values['steps']}")

    # --- 测试3：含关键词内容，中断后拒绝 ---
    print("\n" + "=" * 60)
    print("测试3：含关键词内容，中断后拒绝")
    print("=" * 60)
    config3 = {"configurable": {"thread_id": "sub_node_interrupt_003"}}

    print("--- 首次运行（预期中断） ---")
    for chunk in parent_graph.stream({"content": " also IMPORTANT stuff ", "steps": []}, config=config3):
        print(chunk)

    print("\n--- 恢复执行（传入 no 拒绝） ---")
    for chunk in parent_graph.stream(Command(resume="no"), config=config3):
        print(chunk)

    final3 = parent_graph.get_state(config3)
    print(f"\n最终内容: {final3.values['content']}")
    print(f"执行步骤: {final3.values['steps']}")

    # ========== 验证说明 ==========
    #
    # 1. 测试场景：子图作为父图节点，子图内部 interrupt 冒泡与恢复
    #    - 子图A（预处理）：2节点串联，无 interrupt
    #    - 子图B（核心处理）：条件分支，priority 分支含 interrupt
    #    - 父图：init → 子图A → 子图B → finalize
    #
    # 2. interrupt 冒泡验证：
    #    ✅ 子图B内部的 interrupt 自动冒泡到父图，父图 stream 输出 __interrupt__ 事件
    #    ✅ 父图 get_state().tasks 可查看到待恢复的中断信息
    #    ✅ 子图A已完整执行，状态已持久化（不会被中断回滚）
    #
    # 3. Command(resume) 恢复验证：
    #    ✅ 父图调用 Command(resume=值) 可穿透到子图B内部的 interrupt 点
    #    ✅ resume 值作为 interrupt() 的返回值传入
    #    ✅ 恢复后子图B继续执行，完成后流程回到父图 → finalize → END
    #
    # 4. ⚠️ 核心机制 —— Resume 时中断节点整体重新执行：
    #    当子图中某个节点调用了 interrupt() 并被中断，恢复时该节点会**整体重新执行**，
    #    而不是从 interrupt() 调用处继续。具体流程：
    #
    #    (1) 父图收到 Command(resume=值)，"process" 节点重新执行（即子图B重新被调用）
    #    (2) 子图B内部，checkpointer 记录了执行进度：
    #        - 已完成的节点（check）跳过不执行
    #        - 触发中断的节点（priority_process）从头重新执行整个函数体
    #    (3) 因此 interrupt() 之前的代码会重新执行（如 print("准备触发中断")）
    #    (4) 当执行流再次到达 interrupt() 时，LangGraph 检测到 resume 值，
    #        interrupt() 不再阻塞，而是直接返回 resume 值作为函数返回值
    #    (5) 节点从 interrupt() 之后继续执行后续逻辑
    #
    #    输出证据（测试2恢复时）：
    #      [子图B-高优先级处理] 准备触发中断        ← interrupt() 前的代码重新执行
    #      [子图B-高优先级处理] 中断恢复，用户输入: yes  ← interrupt() 穿透返回
    #
    #    ⚠️ 实际影响：interrupt() 之前的代码必须具备幂等性或可重入性，
    #    因为每次恢复都会重新执行。如果有副作用（如写数据库、发请求），
    #    需要自行做幂等保护。
    #
    # 5. 条件分支 + interrupt 组合：
    #    - normal 分支：不触发 interrupt，直接完成
    #    - priority 分支：触发 interrupt，用户确认后才继续
    #    - 用户拒绝时仍走完子图B，返回带"已拒绝"标记的内容
    #
    # 6. ⚠️ 子图 checkpointer 设置无关性：
    #    当子图通过 add_node("process", sub_b_graph) 作为父图节点时，
    #    子图 compile() 时是否传入 checkpointer **完全不影响运行结果**：
    #      - checkpointer=memory → ✅ 正常
    #      - 不传（默认）       → ✅ 正常
    #      - checkpointer=None   → ✅ 正常
    #
    #    原因：父图的 checkpointer 通过 checkpoint_ns（命名空间）自动管理子图的检查点。
    #    从中断信息可以看到子图的命名空间：
    #      'checkpoint_ns': 'process:78171142-79ef-0c09-3647-7fd6dbbff2fb'
    #    子图的状态被保存在父图 checkpointer 的 "process:" 命名空间下，
    #    因此子图无需也无法独立控制 checkpointer，其生命周期完全由父图统一管理。
    #
    #    ⚠️ 这与 test_sub_graph_nested（invoke 模式）中的情况不同：
    #    - add_node 方式（本例）：子图是父图的"一等公民"节点，checkpointer 由父图接管
    #    - invoke 方式（前例）：子图是父图节点内的手动调用，需要显式共享同一 checkpointer
    #
    # 7. 与 invoke 模式 (test_sub_graph_nested) 的对比：
    #    ┌──────────────────┬──────────────────────────┬──────────────────────────┐
    #    │                  │ add_node 模式（本例）     │ invoke 模式               │
    #    ├──────────────────┼──────────────────────────┼──────────────────────────┤
    #    │ 子图调用方式     │ add_node("name", sub)    │ 节点内 sub_graph.invoke()│
    #    │ checkpointer     │ 父图自动接管，子图无需设置│ 需显式共享同一实例        │
    #    │ interrupt 冒泡   │ ✅ 冒泡到父图             │ ✅ 冒泡到父图             │
    #    │ Command(resume)  │ ✅ 穿透恢复               │ ✅ 穿透恢复               │
    #    │ ⚠️ 恢复时父节点  │ ❌ 无包裹代码，不重入     │ ✅ call_subgraph 整体重入  │
    #    │ 恢复时子图中断节点│ ✅ 整体重入               │ ✅ 整体重入               │
    #    │ 调用前后自定义   │ ❌ 子图作为黑盒节点       │ ✅ 可在 invoke 前后加逻辑 │
    #    │ 子图 checkpointer│ 无论设什么都不影响        │ 必须与父图共享同一实例    │
    #    └──────────────────┴──────────────────────────┴──────────────────────────┘
    #    ⚠️ 最大区别：invoke 模式恢复时，父图调用子图的节点函数整体重新执行
    #    （包括 invoke() 前后的自定义代码）；add_node 模式没有包裹代码，直接进入子图
    #    相同点：子图触发 interrupt 的节点都会从头重新执行整个函数体
    #
    # 8. 与 test_nested_sub_graph 的对比：
    #    - 前例：子图3个节点串联，固定在第3个节点中断
    #    - 本例：子图内部条件分支，只有 priority 路径才中断
    #           + 多子图串联（子图A先完成，子图B再处理）
    #           + resume 值参与后续逻辑判断（yes/no 不同结果）
