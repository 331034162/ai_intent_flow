"""
多源知识路由器
根据用户问题和上传文件，智能判断需要使用的知识来源
"""
import asyncio
import json
import time
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
from enum import Enum

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage, AIMessage,BaseMessage
from langchain_openai import ChatOpenAI

from ..abstract_ai import AbstractAI
from ..context.chat_context import ChatContext
from ..db_connection_pool.zb_conversation_nodes_util import ZbConversationNode, _default_cache as node_cache
from ..db_connection_pool.file_load_2_db import UploadFile
from ..core.logger import app_logger

class TaskType(Enum):
    """任务类型枚举"""
    SUMMARY = "summary"      # 总结概括：总结文档、提炼要点、核心内容、摘要
    REPORT = "report"        # 分析报告：撰写报告、分析评估、调研分析、项目总结
    OUTLINE = "outline"      # 大纲框架：生成目录、大纲、框架、结构规划
    ARTICLE = "article"      # 文章撰写：撰写文章、论文、文案、公文、正式文稿
    QA = "qa"                # 问答查询：问题解答、查询信息、解释说明、概念定义
    COMPARE = "compare"      # 对比分析：对比文件、核对差异、检查合规、对比规范
    EXTRACT = "extract"      # 信息提取：提取数据、关键信息、表格数据、结构化输出
    TRANSLATE = "translate"  # 翻译转换：文档翻译、语言转换
    REWRITE = "rewrite"      # 改写润色：优化文字、润色文档、改写内容
    SPEECH = "speech"        # 演讲稿撰写：撰写演讲稿、发言稿、致辞稿
    BRIEFING = "briefing"    # 汇报撰写：撰写工作汇报、项目汇报、情况汇报
    WRITE_SUMMARY = "write_summary"  # 写总结：撰写工作总结、学习总结、年度总结
    NORMAL = "normal"        # 普通闲聊：日常问候、闲聊对话、无明确任务


class UseHistoryDocumentIntent(Enum):
    """是否需要历史文档意图类型枚举"""
    NEED_HISTORY = "need_history"      # 需要历史文档：基于历史文档/文章进行重写
    NO_HISTORY = "no_history"          # 不需要历史文档：其他所有情况


@dataclass
class RouteResult:
    """路由结果数据类"""
    use_file: bool                          # 是否需要使用上传文件
    use_knowledge_base: bool                # 是否需要查询知识库
    search_queries: List[str]               # 检索问题列表
    task_type: TaskType                     # 任务类型
    generate_prompt: List[str]              # 生成指令列表

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RouteResult":
        """从字典创建实例"""
        task_type_str = data.get("task_type", "normal")
        try:
            task_type = TaskType(task_type_str)
        except ValueError:
            task_type = TaskType.NORMAL

        return cls(
            use_file=data.get("use_file", False),
            use_knowledge_base=data.get("use_knowledge_base", False),
            search_queries=data.get("search_queries", []) or [],
            task_type=task_type,
            generate_prompt=data.get("generate_prompt", []) or []
        )

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "use_file": self.use_file,
            "use_knowledge_base": self.use_knowledge_base,
            "search_queries": self.search_queries,
            "task_type": self.task_type.value,
            "generate_prompt": self.generate_prompt
        }


class RAGPrompts:
    """RAG 提示词配置类 - 集中管理所有提示词相关常量"""

    # 任务类型描述映射
    TASK_TYPE_DESC = {
        TaskType.SUMMARY: "总结概括，突出重点，语言精炼",
        TaskType.REPORT: "撰写正式分析报告，结构完整，逻辑严谨",
        TaskType.OUTLINE: "生成清晰大纲，层级分明，条理清晰",
        TaskType.ARTICLE: "撰写完整文章，语言流畅，内容充实",
        TaskType.QA: "据实回答问题，准确简洁",
        TaskType.NORMAL: "自然对话，正常交流",
        TaskType.COMPARE: "对比分析，清晰呈现异同",
        TaskType.EXTRACT: "提取关键信息，结构化输出",
        TaskType.TRANSLATE: "准确翻译，保持原意",
        TaskType.REWRITE: "改写润色，优化表达",
        TaskType.SPEECH: "撰写演讲稿，语言生动，富有感染力",
        TaskType.BRIEFING: "撰写工作汇报，条理清晰，重点突出",
        TaskType.WRITE_SUMMARY: "撰写工作总结，全面客观，突出成果"
    }

    # 任务类型详细风格说明
    TASK_STYLE_DETAIL = {
        TaskType.SUMMARY: "语言精炼、要点清晰、突出核心，避免冗余描述",
        TaskType.REPORT: "结构完整、逻辑严谨、内容详实，包含背景、分析、结论",
        TaskType.OUTLINE: "层级分明、框架清晰、重点突出，使用合理的标题层级",
        TaskType.ARTICLE: "语言流畅、内容饱满、格式规范，段落衔接自然",
        TaskType.QA: "回答准确、简洁客观、基于资料，不编造信息",
        TaskType.NORMAL: "自然对话、正常交流，保持友好和专业",
        TaskType.COMPARE: "对比全面、分析深入、条理清晰，使用表格或分点呈现",
        TaskType.EXTRACT: "提取准确、格式规范、便于使用，按需结构化输出",
        TaskType.TRANSLATE: "翻译准确、语言地道、保持原意和风格",
        TaskType.REWRITE: "优化表达、保留原意、提升可读性",
        TaskType.SPEECH: "开头吸引人、主题鲜明、情感真挚、结尾有力，适合口头表达",
        TaskType.BRIEFING: "结构清晰、数据准确、重点突出、建议可行",
        TaskType.WRITE_SUMMARY: "内容全面、重点突出、数据详实、成果明显"
    }

    # 路由System Prompt
    ROUTE_SYSTEM_PROMPT = """你是一个专业的多源知识路由助手。请分析用户需求，输出合法JSON，无任何多余文字。

        ## 输出JSON格式

        {{
        "use_file": true/false,
        "use_knowledge_base": true/false,
        "search_queries": ["检索问题1", "检索问题2"],
        "task_type": "summary|report|outline|article|qa|compare|extract|translate|rewrite|speech|briefing|write_summary|normal",
        "generate_prompt": ["生成指令1", "生成指令2"]
        }}

        ## 字段说明

        ### 1. use_file（是否使用上传文件）
        用户需求涉及本次上传文件的操作，填true；否则填false。
        - 基于文件总结、提取、翻译、改写、对比 → true
        - 文件中查找信息、回答问题 → true
        - 与文件无关的问题 → false

        ### 2. use_knowledge_base（是否查询知识库）
        判断用户问题是否需要查询系统知识库获取外部信息。

        【需要查知识库】(true)：
        - 公司制度规范：年假制度、请假流程、报销规定、考勤制度、晋升机制
        - 业务流程指引：审批流程、报销流程、合同审批、采购流程
        - 专业技术规范：编码规范、设计规范、开发标准、接口规范
        - 合同法规条款：合同条款、法律条文、法规要求
        - 概念术语解释：专业术语、业务概念、技术名词解释
        - 历史资料参考：历史项目文档、参考案例、最佳实践
        - 合规性检查：是否符合规范、是否符合标准

        【不需要查知识库】(false)：
        - 仅对上传文件进行操作（总结、提取、翻译、改写）
        - 普通闲聊问候
        - 通用知识问答
        - 无需外部信息的创作

        ### 3. search_queries（知识库检索问题）
        仅当 use_knowledge_base=true 时填写。将用户需求拆分成独立可检索的问题列表。
        示例：用户问"公司年假制度和请假流程"，search_queries=["公司年假制度规定","请假流程步骤"]

        ### 4. task_type（最终生成内容类型）
        根据用户期望的输出形式选择类型：

        | 类型 | 说明 | 适用场景 |
        |------|------|---------|
        | summary | 总结概括 | 总结文档、提炼要点、核心内容、摘要 |
        | report | 分析报告 | 撰写报告、分析评估、调研分析 |
        | outline | 大纲框架 | 生成目录、大纲、框架、结构规划 |
        | article | 文章撰写 | 撰写文章、论文、文案、公文 |
        | qa | 问答回复 | 问题解答、信息查询、概念解释 |
        | compare | 对比分析 | 对比文件、核对差异、检查合规 |
        | extract | 信息提取 | 提取数据、关键信息、结构化输出 |
        | translate | 翻译转换 | 文档翻译、语言转换 |
        | rewrite | 改写润色 | 优化文字、润色文档、改写内容 |
        | normal | 普通闲聊 | 日常问候、闲聊对话 |

        ### 5. generate_prompt（生成指令）
        提炼用户对生成内容的具体要求，形成清晰的生成指令列表。
        示例：用户说"帮我写一份技术方案报告，要包含架构设计和实现步骤"
        generate_prompt=["撰写技术方案报告","包含架构设计部分","包含实现步骤部分"]

        ## 判断流程

        1. 分析用户问题是否涉及上传文件 → 设置 use_file
        2. 分析用户问题是否需要外部知识库信息 → 设置 use_knowledge_base 和 search_queries
        3. 判断用户期望的输出形式 → 设置 task_type
        4. 提取生成内容的具体要求 → 设置 generate_prompt

        ## 注意事项
        - use_file 和 use_knowledge_base 可以同时为 true
        - 如果用户只是查询信息，task_type 选 qa
        - 如果用户需要生成文档，根据文档类型选对应 task_type"""

    # 用户问题模板（带文件列表）
    ROUTE_USER_TEMPLATE_WITH_FILE = """【用户当前问题】
        {user_query}

        【用户本次上传文件列表】
        {file_list}"""

    # 用户问题模板（不带文件列表）
    ROUTE_USER_TEMPLATE_NO_FILE = """【用户当前问题】
        {user_query}"""


class UseHistoryDocumentPrompts:
    """是否需要历史文档意图识别提示词配置类"""

    # 是否需要历史文档意图识别 System Prompt
    USE_HISTORY_SYSTEM_PROMPT = """判断用户的请求【是否需要带上历史文档/文章】。

    ## 输出JSON格式
    {{
        "intent": "need_history 或 no_history",
        "reason": "判断理由"
    }}

    ## 判断标准

    **need_history（需要历史文档）**：
    - 用户说"重写"或类似表达，且【当前没有上传文件】
    - 典型场景：用户在上一轮生成了文章，这一轮说"帮我重写一下"，"请重写一篇","这篇文章不行，请重写"等等

    **no_history（不需要历史文档）**：其他所有情况，包括：
    - 用户上传了文件
    - 用户说"修改"、"润色"、"优化"
    - 全新创作、独立问题等

    ## 注意
    - 默认为 no_history
    - 输出必须是合法JSON，不要有多余文字"""

    # 用户问题模板
    USE_HISTORY_USER_TEMPLATE = """【用户当前问题】
    {user_query}

    【用户当前上传的文件】
    {file_list}

    【历史对话最后一条AI回复】
    {last_article_content}"""


@dataclass
class UseHistoryDocumentResult:
    """是否需要历史文档意图识别结果"""
    intent: UseHistoryDocumentIntent
    reason: str

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UseHistoryDocumentResult":
        """从字典创建实例"""
        intent_str = data.get("intent", "no_history")
        try:
            intent = UseHistoryDocumentIntent(intent_str)
        except ValueError:
            intent = UseHistoryDocumentIntent.NO_HISTORY

        return cls(
            intent=intent,
            reason=data.get("reason", "")
        )

class AbstractRAG(AbstractAI):
    """多源知识路由器"""
    def __init__(self,node_id:str):
        """初始化"""
        super().__init__()
        self.node_id = node_id
        self.llm: ChatOpenAI = None
        self.node: Optional[ZbConversationNode] = None
        self._initialized = False
        self._init_lock = asyncio.Lock()

    def _get_prompt_friendly_response(self, context: ChatContext = None) -> str:
        """获取友好回应提示词

        Args:
            context: 对话上下文（可选）
        """
        return "你是一个专业的多源知识路由助手。"

    async def _ensure_initialized(self, context: ChatContext = None) -> None:
        """确保路由器已初始化

        Args:
            context: 对话上下文（可选）
        """
        # 使用锁确保只初始化一次
        if self._initialized:
            return
        async with self._init_lock:
            if self._initialized:
                return
            # 从数据库获取节点配置
            self.node = await node_cache.get_node_by_id(self.node_id)
            if self.node:
                self.llm: ChatOpenAI = await node_cache.get_llm_by_node_id(self.node_id)
                app_logger.info(f"路由器初始化完成 [{self.node_id}]，模型: {self.node.model_name}")
            else:
                # 使用默认配置
                app_logger.warning(f"未找到节点配置 {self.node_id}，使用默认配置")
            self._initialized = True

    def _convert_history_to_messages(self, chat_history: List[dict]) -> List[BaseMessage]:
        """
        将历史消息列表转换为 LangChain 消息格式

        Args:
            chat_history: 历史消息列表，格式为 [{"role": "user/assistant", "content": "..."}]

        Returns:
            LangChain 消息列表
        """
        messages = []
        if chat_history:
            for msg in chat_history:
                if msg.get("role") == "user":
                    messages.append(HumanMessage(content=msg.get("content", "")))
                elif msg.get("role") == "assistant":
                    messages.append(AIMessage(content=msg.get("content", "")))
        return messages

    async def classify_use_history_intent(
        self,
        user_query: str,
        file_name_list: List[str],
        chat_history: List[dict] = None,
        context: ChatContext = None
    ) -> UseHistoryDocumentResult:
        """
        单独识别是否需要历史文档

        这是一个独立的意图识别方法，用于判断用户的请求是否需要带上历史文档/文章。
        与 route() 方法分离，专门处理是否需要历史文档的场景。

        Args:
            user_query: 用户当前问题
            file_name_list: 由process_user_input方法生成的文件名列表
            chat_history: 原始历史消息列表
            context: 对话上下文（用于日志记录）

        Returns:
            UseHistoryDocumentResult: 是否需要历史文档意图识别结果
        """
        usage_metadata = None
        latency_ms = 0

        try:
            await self._ensure_initialized(context)

            # 获取历史对话中最后一条 AI 回复的完整内容
            last_article_content = ""
            if chat_history:
                for msg in reversed(chat_history):
                    if msg.get("role") == "assistant" and msg.get("content"):
                        last_article_content = msg.get("content", "")
                        break

            # 构建 Prompt
            prompt = ChatPromptTemplate.from_messages([
                ("system", UseHistoryDocumentPrompts.USE_HISTORY_SYSTEM_PROMPT),
                ("human", UseHistoryDocumentPrompts.USE_HISTORY_USER_TEMPLATE),
            ])

            # 构建文件列表字符串
            file_list = "无"
            if file_name_list:
                file_list = ", ".join(file_name_list)

            messages = prompt.format_messages(
                user_query=user_query,
                file_list=file_list,
                last_article_content=last_article_content or "无历史文章"
            )

            # 调用 LLM
            start_time = time.time()
            llm = (await self.resolve_prompt_model(self.node_id, "prompt_generate")) or self.llm
            response = await llm.ainvoke(messages)
            latency_ms = int((time.time() - start_time) * 1000)

            # 获取 usage_metadata
            if hasattr(response, 'usage_metadata') and response.usage_metadata:
                usage_metadata = response.usage_metadata

            # 解析 JSON 响应
            content = response.content if hasattr(response, 'content') else str(response)

            # 尝试解析 JSON
            try:
                start_idx = content.find("{")
                end_idx = content.rfind("}") + 1
                if start_idx != -1 and end_idx > start_idx:
                    json_str = content[start_idx:end_idx]
                    result_dict = json.loads(json_str)
                else:
                    raise json.JSONDecodeError("未找到有效的JSON", content, 0)
            except json.JSONDecodeError as e:
                app_logger.error(f"是否需要历史文档意图识别JSON解析失败: {e}, 原始响应: {content}")
                return UseHistoryDocumentResult(
                    intent=UseHistoryDocumentIntent.NO_HISTORY,
                    reason=f"JSON解析失败: {str(e)}"
                )

            result = UseHistoryDocumentResult.from_dict(result_dict)

            # 记录 token 使用情况
            if usage_metadata and context and self.node:
                await self.log_token_usage(
                    context=context,
                    node=self.node,
                    usage_metadata=usage_metadata,
                    latency_ms=latency_ms
                )

            app_logger.info(
                f"是否需要历史文档意图识别完成 | intent={result.intent.value} | "
                f"reason={result.reason} | "
                f"latency={latency_ms}ms"
            )

            return result

        except Exception as e:
            app_logger.error(f"是否需要历史文档意图识别失败: {e}")
            if context and self.node:
                await self.log_token_usage(
                    context=context,
                    node=self.node,
                    usage_metadata=usage_metadata or {},
                    latency_ms=latency_ms,
                    status=2,
                    error_msg=str(e)
                )
            return UseHistoryDocumentResult(
                intent=UseHistoryDocumentIntent.NO_HISTORY,
                reason=f"识别失败: {str(e)}"
            )

    async def route(
        self,
        user_query: str,
        file_name_list: List[str],
        history_messages: List[BaseMessage],
        context: ChatContext = None
    ) -> RouteResult:
        """
        异步执行路由分析

        Args:
            user_query: 用户当前问题
            file_name_list: 文件名列表（由 process_user_input 传入）
            history_messages: 历史消息列表（由 process_user_input 传入）
            context: 对话上下文（用于日志记录）

        Returns:
            RouteResult 路由结果
        """
        usage_metadata = None
        latency_ms = 0

        try:
            # 根据是否有文件选择用户模板
            if file_name_list:
                user_template = RAGPrompts.ROUTE_USER_TEMPLATE_WITH_FILE
                file_list_str = "\n".join([f"- {f}" for f in file_name_list])
            else:
                user_template = RAGPrompts.ROUTE_USER_TEMPLATE_NO_FILE
                file_list_str = ""

            # 动态构建 Prompt 模板
            prompt = ChatPromptTemplate.from_messages([
                ("system", RAGPrompts.ROUTE_SYSTEM_PROMPT),
                MessagesPlaceholder(variable_name="history"),
                ("human", user_template),
            ])

            # 格式化消息
            if file_name_list:
                messages = prompt.format_messages(
                    history=history_messages,
                    user_query=user_query,
                    file_list=file_list_str
                )
            else:
                messages = prompt.format_messages(
                    history=history_messages,
                    user_query=user_query
                )

            # 调用 LLM 并记录耗时
            start_time = time.time()
            llm = (await self.resolve_prompt_model(self.node_id, "prompt_classify")) or self.llm
            response = await llm.ainvoke(messages)
            latency_ms = int((time.time() - start_time) * 1000)

            # 获取 usage_metadata
            if hasattr(response, 'usage_metadata') and response.usage_metadata:
                usage_metadata = response.usage_metadata

            # 解析 JSON 响应
            content = response.content if hasattr(response, 'content') else str(response)

            # 尝试解析 JSON
            try:
                # 查找 JSON 部分
                start_idx = content.find("{")
                end_idx = content.rfind("}") + 1
                if start_idx != -1 and end_idx > start_idx:
                    json_str = content[start_idx:end_idx]
                    result_dict = json.loads(json_str)
                else:
                    raise json.JSONDecodeError("未找到有效的JSON", content, 0)
            except json.JSONDecodeError as e:
                app_logger.error(f"路由结果JSON解析失败: {e}, 原始响应: {content}")
                return self._get_default_result(file_name_list)

            route_result = RouteResult.from_dict(result_dict)

            # 记录 token 使用情况
            if usage_metadata and context and self.node:
                await self.log_token_usage(
                    context=context,
                    node=self.node,
                    usage_metadata=usage_metadata,
                    latency_ms=latency_ms
                )

            app_logger.info(
                f"路由分析完成 | use_file={route_result.use_file} | "
                f"use_knowledge_base={route_result.use_knowledge_base} | "
                f"task_type={route_result.task_type.value} | "
                f"search_queries={route_result.search_queries} | "
                f"generate_prompt={route_result.generate_prompt} | "
                f"latency={latency_ms}ms"
            )

            return route_result

        except json.JSONDecodeError as e:
            app_logger.error(f"路由结果JSON解析失败: {e}")
            # 记录失败日志
            if context and self.node:
                await self.log_token_usage(
                    context=context,
                    node=self.node,
                    usage_metadata=usage_metadata or {},
                    latency_ms=latency_ms,
                    status=2,
                    error_msg=str(e)
                )
            return self._get_default_result(file_name_list)
        except Exception as e:
            app_logger.error(f"路由分析失败: {e}")
            # 记录失败日志
            if context and self.node:
                await self.log_token_usage(
                    context=context,
                    node=self.node,
                    usage_metadata=usage_metadata or {},
                    latency_ms=latency_ms,
                    status=2,
                    error_msg=str(e)
                )
            return self._get_default_result(file_name_list)

    def build_final_instruction(
        self,
        route_result: RouteResult,
        user_query: str
    ) -> str:
        """
        根据路由结果合成最终指令

        Args:
            route_result: 路由结果
            user_query: 用户原始问题

        Returns:
            最终合成的指令字符串
        """
        task_type = route_result.task_type
        generate_prompts = route_result.generate_prompt

        # qa 或 normal 类型直接使用用户问题
        if task_type == TaskType.NORMAL:
            return user_query

        # 其他类型：合并生成指令
        if not generate_prompts or len(generate_prompts) == 0:
            return user_query

        # 合并成一个清晰的总指令
        final_instruction = "请完成以下所有任务：\n" + "\n".join([
            f"{i+1}. {item}"
            for i, item in enumerate(generate_prompts)
        ])

        return final_instruction

    def get_task_type_desc(self, task_type: TaskType) -> str:
        """
        获取任务类型描述

        Args:
            task_type: 任务类型

        Returns:
            任务类型描述字符串
        """
        return RAGPrompts.TASK_TYPE_DESC.get(task_type, "自然对话，正常交流")

    def get_task_style_detail(self, task_type: TaskType) -> str:
        """
        获取任务类型详细风格说明

        Args:
            task_type: 任务类型

        Returns:
            任务类型详细风格说明字符串
        """
        return RAGPrompts.TASK_STYLE_DETAIL.get(task_type, "自然对话、正常交流，保持友好和专业")

    def build_generate_prompt(
        self,
        final_instruction: str,
        task_type: TaskType,
        use_file: bool = False,
        use_knowledge_base: bool = False,
        file_content: str = "",
        knowledge_content: str = ""
    ) -> str:
        """
        构建生成内容的 System Prompt

        注意：历史对话由子类使用 LangChain 消息格式处理，不包含在此 prompt 中

        Args:
            final_instruction: 最终指令
            task_type: 任务类型
            use_file: 是否使用文件
            use_knowledge_base: 是否使用知识库
            file_content: 文件内容
            knowledge_content: 知识库内容

        Returns:
            完整的 System Prompt
        """
        task_type_desc = self.get_task_type_desc(task_type)
        task_style_detail = self.get_task_style_detail(task_type)

        # 构建参考资料部分（分别列出文件内容、知识库内容）
        reference_sections = []
        if use_file and file_content:
            reference_sections.append(f"【用户上传文件内容】\n{file_content}")
        if use_knowledge_base and knowledge_content:
            reference_sections.append(f"【系统知识库内容】\n{knowledge_content}")

        reference_content = "\n\n".join(reference_sections) if reference_sections else "无参考资料"

        prompt = f"""你是一个专业的智能助手。请根据提供的参考资料，完成用户的任务要求。

            {reference_content}

            【需要完成的任务】
            {final_instruction}

            【输出风格要求】
            {task_type_desc}
            具体要求：{task_style_detail}

            请输出一份完整、连贯、结构清晰的内容，不要分开发送，不要逐条生硬回复。"""
        return prompt

    async def extract_original_content_from_history(
        self,
        chat_history: List[dict]
    ) -> Dict[str, Any]:
        """
        从历史消息中提取原始内容（用于重写场景）
        只从非 NORMAL 类型的历史记录中提取（只有非 NORMAL 类型才生成文档）

        Args:
            chat_history: 历史消息列表

        Returns:
            dict: {
                "original_article": str,      # 原始文章内容
                "original_request": str,      # 原始用户需求
                "original_file_ids": str,     # 原始文件ID列表
                "original_message_id": int    # 原始消息ID
            }
        """
        result = {
            "original_article": "",
            "original_request": "",
            "original_file_ids": "",
            "original_message_id": None
        }

        if not chat_history or len(chat_history) < 2:
            return result

        # 从后往前找最近的非 NORMAL 类型的 assistant 消息（只有非 NORMAL 类型才生成文档）
        for i in range(len(chat_history) - 1, -1, -1):
            msg = chat_history[i]
            if msg.get("role") == "assistant" and msg.get("content"):
                msg_task_type = msg.get("task_type", "")
                # 只查找 task_type 不为空且不为 "normal" 的历史记录
                if msg_task_type and msg_task_type.lower() != "normal":
                    result["original_article"] = msg.get("content", "")
                    result["original_file_ids"] = msg.get("file_id_list", "")
                    result["original_message_id"] = msg.get("message_id")
                    if i > 0 and chat_history[i - 1].get("role") == "user":
                        result["original_request"] = chat_history[i - 1].get("content", "")
                    break

        return result

    def _get_default_result(self, file_name_list: List[str]) -> RouteResult:
        """获取默认路由结果"""
        return RouteResult(
            use_file=len(file_name_list) > 0,
            use_knowledge_base=False,
            search_queries=[],
            task_type=TaskType.NORMAL,
            generate_prompt=[]
        )

    @classmethod
    async def create_router(cls, node_id: str = "multi_source_knowledge_router") -> "AbstractRAG":
        """
        创建路由器实例

        Args:
            node_id: 节点ID，默认为 "multi_source_knowledge_router"

        Returns:
            路由器实例（初始化会在首次使用时自动进行）
        """
        return cls(node_id=node_id)