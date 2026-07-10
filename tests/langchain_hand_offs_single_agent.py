import os
from typing import Callable, Literal
from typing_extensions import NotRequired

from langchain.agents import AgentState, create_agent
from langchain.agents.middleware import wrap_model_call, ModelRequest, ModelResponse
from langchain.messages import HumanMessage, ToolMessage
from langchain.tools import tool, ToolRuntime
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from langchain_core.utils.uuid import uuid7
from langchain_openai import ChatOpenAI
# ============================================================================
# 1. 定义状态
# ============================================================================
SupportStep = Literal["warranty_collector", "issue_classifier", "resolution_specialist"]

class SupportState(AgentState):
    """客服支持工作流状态"""
    current_step: NotRequired[SupportStep]
    warranty_status: NotRequired[Literal["in_warranty", "out_of_warranty"]]
    issue_type: NotRequired[Literal["hardware", "software"]]

# ============================================================================
# 2. 定义工具（通过 Command 更新状态）
# ============================================================================
@tool
def record_warranty_status(
    status: Literal["in_warranty", "out_of_warranty"],
    runtime: ToolRuntime[None, SupportState],
) -> Command:
    """记录保修状态并转换到下一步"""
    return Command(
        update={
            "messages": [
                ToolMessage(
                    content=f"保修状态已记录: {status}",
                    tool_call_id=runtime.tool_call_id,
                )
            ],
            "warranty_status": status,
            "current_step": "issue_classifier",  # 触发状态转换
        }
    )

@tool
def record_issue_type(
    issue_type: Literal["hardware", "software"],
    runtime: ToolRuntime[None, SupportState],
) -> Command:
    """记录问题类型并转换到解决方案阶段"""
    return Command(
        update={
            "messages": [
                ToolMessage(
                    content=f"问题类型已记录: {issue_type}",
                    tool_call_id=runtime.tool_call_id,
                )
            ],
            "issue_type": issue_type,
            "current_step": "resolution_specialist",  # 触发状态转换
        }
    )

@tool
def escalate_to_human(reason: str) -> str:
    """升级到人工支持"""
    return f"已升级到人工支持。原因: {reason}"

@tool
def provide_solution(solution: str) -> str:
    """提供解决方案"""
    return f"解决方案: {solution}"

# ============================================================================
# 3. 定义每个步骤的配置（提示词 + 工具）
# ============================================================================
WARRANTY_COLLECTOR_PROMPT = """你是一个客服支持代理，正在帮助客户处理设备问题。

当前阶段: 保修验证

在这个步骤，你需要:
1. 热情地问候客户
2. 询问客户的设备是否在保修期内
3. 使用 record_warranty_status 工具记录响应并进入下一步

保持对话友好，不要一次问多个问题。"""

ISSUE_CLASSIFIER_PROMPT = """你是一个客服支持代理，正在帮助客户处理设备问题。

当前阶段: 问题分类
客户信息: 保修状态为 {warranty_status}

在这个步骤，你需要:
1. 请客户描述他们的问题
2. 判断是硬件问题（物理损坏、零件故障）还是软件问题（应用崩溃、性能问题）
3. 使用 record_issue_type 工具记录分类并进入下一步

如果不确定，先问清楚再分类。"""

RESOLUTION_SPECIALIST_PROMPT = """你是一个客服支持代理，正在帮助客户处理设备问题。

当前阶段: 解决方案
客户信息: 保修状态为 {warranty_status}，问题类型为 {issue_type}

在这个步骤，你需要:
1. 对于软件问题: 使用 provide_solution 提供故障排除步骤
2. 对于硬件问题:
   - 如果在保修期内: 使用 provide_solution 解释保修维修流程
   - 如果不在保修期内: 使用 escalate_to_human 升级到人工支持获取付费维修选项

提供具体有用的解决方案。"""

STEP_CONFIG = {
    "warranty_collector": {
        "prompt": WARRANTY_COLLECTOR_PROMPT,
        "tools": [record_warranty_status],
        "requires": [],
    },
    "issue_classifier": {
        "prompt": ISSUE_CLASSIFIER_PROMPT,
        "tools": [record_issue_type],
        "requires": ["warranty_status"],
    },
    "resolution_specialist": {
        "prompt": RESOLUTION_SPECIALIST_PROMPT,
        "tools": [provide_solution, escalate_to_human],
        "requires": ["warranty_status", "issue_type"],
    },
}

# ============================================================================
# 4. 创建中间件（根据 current_step 动态应用配置）
# ============================================================================
@wrap_model_call
def apply_step_config(
    request: ModelRequest,
    handler: Callable[[ModelRequest], ModelResponse],
) -> ModelResponse:
    """根据当前步骤配置 Agent 行为"""
    current_step = request.state.get("current_step", "warranty_collector")
    step_config = STEP_CONFIG[current_step]
    
    # 验证必需的状态字段
    for key in step_config["requires"]:
        if request.state.get(key) is None:
            raise ValueError(f"在到达 {current_step} 之前必须设置 {key}")
    
    # 格式化提示词（注入状态值）
    system_prompt = step_config["prompt"].format(**request.state)
    
    # 覆盖系统提示词和可用工具
    request = request.override(
        system_prompt=system_prompt,
        tools=step_config["tools"],
    )
    
    return handler(request)

# ============================================================================
# 5. 创建 Agent
# ============================================================================
model = ChatOpenAI(
    model="deepseek-v4-pro",
    base_url="https://api.deepseek.com",
    api_key=os.getenv("DEEPSEEK_API_KEY", "your-api-key-here"),
    extra_body={"thinking": {"type": "disabled"}},
)

all_tools = [
    record_warranty_status,
    record_issue_type,
    provide_solution,
    escalate_to_human,
]

agent = create_agent(
    model,
    tools=all_tools,
    state_schema=SupportState,
    middleware=[apply_step_config],
    checkpointer=InMemorySaver(),  # 持久化状态
)

# ============================================================================
# 6. 测试工作流
# ============================================================================
if __name__ == "__main__":
    thread_id = str(uuid7())
    config = {"configurable": {"thread_id": thread_id}}
    
    # 第1轮: 保修收集
    print("=== 第1轮: 保修收集 ===")
    result = agent.invoke(
        {"messages": [HumanMessage("你好，我的手机屏幕碎了")]},
        config
    )
    for msg in result['messages']:
        msg.pretty_print()
    
    # 第2轮: 用户回答保修状态
    print("\n=== 第2轮: 保修响应 ===")
    result = agent.invoke(
        {"messages": [HumanMessage("是的，还在保修期内")]},
        config
    )
    for msg in result['messages']:
        msg.pretty_print()
    print(f"当前步骤: {result.get('current_step')}")
    
    # 第3轮: 用户描述问题
    print("\n=== 第3轮: 问题描述 ===")
    result = agent.invoke(
        {"messages": [HumanMessage("屏幕是摔碎的，有明显的裂痕")]},
        config
    )
    for msg in result['messages']:
        msg.pretty_print()
    print(f"当前步骤: {result.get('current_step')}")
    
    # 第4轮: 解决方案
    print("\n=== 第4轮: 解决方案 ===")
    result = agent.invoke(
        {"messages": [HumanMessage("我该怎么办？")]},
        config
    )
    for msg in result['messages']:
        msg.pretty_print()

# ============================================================================
# 总结: 单 Agent 多阶段工作流（客服支持流程）
# ============================================================================
# 核心思路: 用一个 Agent + 中间件（middleware）实现分阶段客服流程，通过
# current_step 状态字段控制 Agent 在不同阶段的行为。
#
# 关键机制:
#   1. 状态驱动 — SupportState 继承 AgentState，扩展 current_step、
#      warranty_status、issue_type 三个状态字段
#   2. 工具即状态转换器 — record_warranty_status、record_issue_type 等工具
#      返回 Command，不仅产生 ToolMessage，还更新状态字段并触发 current_step 切换
#   3. 中间件动态配置 — @wrap_model_call 装饰的 apply_step_config 中间件根据
#      current_step 动态注入对应的系统提示词和可用工具集，并验证必需状态字段
#   4. 三阶段流程 — warranty_collector → issue_classifier → resolution_specialist，
#      每阶段有独立的 prompt 和工具
#   5. Checkpointer — 使用 InMemorySaver 保持跨轮次对话的线程状态
#
# 一句话概括: 单 Agent 通过工具返回 Command 更新状态 + 中间件读取状态切换配置，
# 实现多阶段串行工作流。
#
# 对比速查:
#   | 维度         | Single Agent                          | Multi Agent                              |
#   |-------------|---------------------------------------|------------------------------------------|
#   | 架构         | 1个 Agent + middleware                | 2个 Agent + StateGraph                   |
#   | 阶段切换     | 工具返回 Command 更新 current_step     | 工具返回 Command(goto=..., graph=PARENT) |
#   | 行为切换     | 中间件动态换 prompt/tools              | 每个 Agent 固定 prompt/tools             |
#   | 路由控制     | 状态字段驱动                           | 图的条件边驱动                            |
#   | 适用场景     | 串行多阶段流程（如客服SOP）             | 多个专业 Agent 需要灵活跳转               |