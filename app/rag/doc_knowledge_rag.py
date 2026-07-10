"""
知识路由器实现类
继承 AbstractRAG，实现完整的路由和生成流程
"""
import time
from typing import Dict, Any, AsyncGenerator, List
from ..db_connection_pool.file_load_2_db import UploadFile

from langchain_core.messages import SystemMessage, HumanMessage

from .abstract_rag import AbstractRAG
from ..context.chat_context import ChatContext
from ..core.logger import app_logger
from ..db_connection_pool.conversation_db_helper import ConversationDBHelper
from .abstract_rag import UseHistoryDocumentResult,UseHistoryDocumentIntent
from ..abstract_ai import AbstractAI
from ..db_connection_pool.file_load_2_db import FileLoad2DB
class DocKnowledgeRAG(AbstractRAG):
    """文档知识路由器实现类"""

    def __init__(self, node_id: str = "doc_knowledge_rag"):
        """初始化

        Args:
            node_id: 节点ID，默认为 "knowledge_router"
        """
        super().__init__(node_id=node_id)

    def _get_prompt_friendly_response(self, context: ChatContext = None) -> str:
        """获取友好回应提示词

        Args:
            context: 对话上下文（可选）
        """
        return "你是一个专业的知识路由助手。"

    async def process_user_input(
        self,
        user_input: str,
        context: ChatContext
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        处理用户输入（流式输出）

        流程：
        1. 初始化：确保节点已加载，获取聊天历史
        2. 文件准备：获取当前上传的文件信息
        3. 历史文档判断：识别是否需要引用历史对话中的文档
        4. 路由决策：确定任务类型、是否使用文件/知识库
        5. 内容获取：根据路由结果获取文件内容和知识库内容
        6. 构建提示词：生成最终的 System Prompt
        7. 大模型调用：流式生成回答
        8. 后处理：记录 token 使用、保存对话记录

        Args:
            user_input: 用户输入
            context: 对话上下文

        Yields:
            Dict[str, Any]: 流式输出的字典
        """

        try:
            # 1. 初始化：确保节点已加载
            await self._ensure_initialized(context)

            # 从数据库获取聊天历史
            if context.is_query_history_node_id and context.use_history:
                chat_history = await AbstractAI.get_chat_history_from_db(
                    context.conversation_id,
                    message_status=1,
                    node_id=self.node_id,
                    max=context.history_max_records
                )
                # 如果是开始的入口节点则不限制 node_id，获取完整对话历史(但不能包含is_human_generated=1)用于意图识别，否则只查询跟当前节点相关的信息，强化意图识别
                # if context.workflow.entry_node_id != self.node_id:
                #     chat_history = await AbstractAI.get_chat_history_from_db(context.conversation_id, message_status=1, node_id=self.node_id, max=context.history_max_records)
                # else:
                #     chat_history = await AbstractAI.get_chat_history_from_db(context.conversation_id, message_status=1, node_id=None, is_human_generated=0)
                context.chat_history = chat_history
            else:
                chat_history = context.chat_history
            
            # 2. 文件准备：获取当前上传的文件信息
            file_name_list: List[str] = []
            file_id_arr: List[str] = []
            upload_files: List[UploadFile] = []

            if context.file_list:
                file_id_arr = context.file_list.split(",")
                current_files = await FileLoad2DB.get_files_by_ids(file_id_arr)
                upload_files = current_files
                file_name_list = [f.file_name for f in current_files]

            # 3. 历史文档判断：识别是否需要引用历史对话中的文档
            use_history_result: UseHistoryDocumentResult = await self.classify_use_history_intent(
                user_input, file_name_list, chat_history, context
            )

            # 如果需要历史文档，获取历史文件并合并
            file_ids_his_arr: List[str] = []
            if use_history_result.intent == UseHistoryDocumentIntent.NEED_HISTORY:
                info_his: Dict[str, Any] = await self.extract_original_content_from_history(chat_history)
                if info_his:
                    file_ids_his: str = info_his.get("original_file_ids")
                    file_ids_his_arr = file_ids_his.split(",") if file_ids_his else []
                    # 移除当前已上传的文件ID（当前上传的文件优先）
                    file_ids_his_arr = [fid for fid in file_ids_his_arr if fid not in file_id_arr]
                    if file_ids_his_arr:
                        history_files = await FileLoad2DB.get_files_by_ids(file_ids_his_arr)
                        upload_files.extend(history_files)
                        file_name_list = [f.file_name for f in upload_files]

            # 转换聊天历史为 LangChain 消息格式
            history_messages = self._convert_history_to_messages(chat_history)

            # 4. 路由决策：确定任务类型、是否使用文件/知识库
            route_result = await self.route(
                user_query=user_input,
                file_name_list=file_name_list,
                history_messages=history_messages,
                context=context
            )
            app_logger.info(
                f"路由结果 | use_file={route_result.use_file} | "
                f"use_knowledge_base={route_result.use_knowledge_base} | "
                f"task_type={route_result.task_type.value} | "
                f"search_queries={route_result.search_queries} | "
                f"generate_prompt={route_result.generate_prompt}"
            )

            # 构建 final_instruction
            final_instruction = self.build_final_instruction(route_result, user_input)

            # 5. 内容获取：根据路由结果获取文件内容
            file_content = ""
            if route_result.use_file:
                file_content = self._get_file_content(upload_files)
                app_logger.info(f"获取文件内容完成，长度: {len(file_content)}")

            # 获取知识库内容
            knowledge_content = ""
            if route_result.use_knowledge_base:
                knowledge_content = await self._get_knowledge_content(
                    route_result.search_queries
                )
                app_logger.info(f"获取知识库内容完成，长度: {len(knowledge_content)}")

            # 6. 构建提示词：生成最终的 System Prompt
            generate_prompt = self.build_generate_prompt(
                final_instruction=final_instruction,
                task_type=route_result.task_type,
                use_file=route_result.use_file,
                use_knowledge_base=route_result.use_knowledge_base,
                file_content=file_content,
                knowledge_content=knowledge_content
            )

            # 构建消息列表
            messages = [SystemMessage(content=generate_prompt)]
            messages.extend(history_messages)
            messages.append(HumanMessage(content=user_input))

            # 7. 大模型调用：流式生成回答 —— 优先使用 prompt 级模型覆盖
            full_content = ""
            usage_metadata = None
            start_time = time.time()

            llm = (await self.resolve_prompt_model(self.node_id, "prompt_generate_answer")) or self.llm
            async for chunk in llm.astream(messages):
                if hasattr(chunk, 'usage_metadata') and chunk.usage_metadata:
                    usage_metadata = chunk.usage_metadata
                content = getattr(chunk, 'content', str(chunk)) if hasattr(chunk, 'content') else str(chunk)
                if content:
                    full_content += content
                    yield self.create_stream_message(
                        content=content,
                        message_type="model",
                        is_last=False,
                        is_over=False,
                        conversation_id=context.conversation_id
                    )

            latency_ms = int((time.time() - start_time) * 1000)

            # 8. 后处理：记录 token 使用、保存对话记录
            if usage_metadata and context and self.node:
                await self.log_token_usage(
                    context=context,
                    node=self.node,
                    usage_metadata=usage_metadata,
                    latency_ms=latency_ms
                )
                app_logger.info(f"Token 使用记录完成，耗时: {latency_ms}ms")

            # 合并所有用到的文件ID
            all_file_ids = file_id_arr.copy() if file_id_arr else []
            if use_history_result.intent == UseHistoryDocumentIntent.NEED_HISTORY and file_ids_his_arr:
                all_file_ids.extend(file_ids_his_arr)
            final_file_id_list = ",".join(all_file_ids) if all_file_ids else context.file_list

            await self._save_conversation_to_db(
                context=context,
                question=user_input,
                answer=full_content,
                status_description="处理成功",
                message_status=1,
                file_id_list=final_file_id_list,
                task_type=route_result.task_type.value
            )

            # 发送结束消息
            yield self.create_stream_message(
                content="",
                message_type="model",
                is_last=True,
                is_over=True,
                conversation_id=context.conversation_id
            )

        except Exception as e:
            app_logger.error(f"处理用户输入失败: {e}")
            error_message = f"抱歉，处理您的请求时出现错误: {str(e)}"
            # 保存失败的对话记录到数据库
            await self._save_conversation_to_db(
                context=context,
                question=user_input,
                answer=error_message,
                status_description=f"处理失败: {str(e)}",
                message_status=-1,
                file_id_list=context.file_list,
                task_type="normal"
            )
            # 发送错误消息
            yield self.create_stream_message(
                content=error_message,
                message_type="model",
                is_last=True,
                is_over=True,
                conversation_id=context.conversation_id
            )

    def _get_file_content(self, upload_files: List[UploadFile]) -> str:
        """
        获取上传文件内容

        Args:
            upload_files: 上传文件对象列表（由 _prepare_route_context 提供）

        Returns:
            文件内容字符串
        """
        file_content_parts = []
        for f in upload_files:
            # UploadFile 对象有 file_content 属性
            if f.file_content:
                file_content_parts.append(f"【文件: {f.file_name}】\n{f.file_content}")

        return "\n\n".join(file_content_parts)

    async def _get_knowledge_content(
        self,
        search_queries: list
    ) -> str:
        """
        获取知识库内容

        Args:
            search_queries: 检索问题列表

        Returns:
            知识库内容字符串
        """
        # TODO: 实现知识库检索逻辑
        # 这里需要根据实际的知识库实现来填充
        # 示例：调用向量数据库检索相关内容
        knowledge_parts = []
        for i, query in enumerate(search_queries):
            # 占位符，实际需要调用知识库检索
            knowledge_parts.append(f"【检索问题{i+1}: {query}】\n(待实现知识库检索)")
        return "\n\n".join(knowledge_parts)

    async def _save_conversation_to_db(
        self,
        context: ChatContext,
        question: str,
        answer: str,
        status_description: str,
        message_status: int,
        file_id_list: str = None,
        task_type: str = None
    ) -> bool:
        """
        保存对话记录到数据库

        Args:
            context: 对话上下文
            question: 用户问题
            answer: AI回答
            status_description: 状态描述
            message_status: 消息状态（1-成功，-1-失败）
            file_id_list: 对话用到的file_id列表（可选，用逗号分隔）
            task_type: 任务类型（可选）

        Returns:
            bool: 是否保存成功
        """
        try:
            # 获取模型信息
            model_name = self.node.model_name if self.node else "unknown"
            model_provider = self.node.model_provider if self.node else "zbank"
            model_url = self.node.model_url if self.node else None
            model_ext_param = self.node.model_ext_param if self.node else None

            # 获取工作流ID
            workflow_id = context.workflow.workflow_id if context.workflow else None

            # 调用保存方法
            # 优先使用 context_info 中的值，否则保留已有的 knowledge_conversation_id
            if context.context_info.get("knowledge_conversation_id"):
                context.knowledge_conversation_id = context.context_info["knowledge_conversation_id"]
            success = await ConversationDBHelper.save_conversation_record(
                conversation_id=context.conversation_id,
                conversation_name=context.conversation_name,
                employee_id=context.user_id,
                question=question,
                answer=answer,
                model_name=model_name,
                model_provider=model_provider,
                model_url=model_url,
                model_ext_param=model_ext_param,
                status_description=status_description,
                node_id=self.node_id,
                workflow_id=workflow_id,
                is_human_generated=0,
                message_status=message_status,
                seq_no=context.seq_no,
                conversation_type=context.conversation_type,
                file_id_list=file_id_list,
                task_type=task_type,
                knowledge_conversation_id=context.knowledge_conversation_id
            )

            if success:
                app_logger.info(f"对话记录保存成功: conversation_id={context.conversation_id}")
            else:
                app_logger.warning(f"对话记录保存失败: conversation_id={context.conversation_id}")

            return success

        except Exception as e:
            app_logger.error(f"保存对话记录异常: {str(e)}")
            return False

    @classmethod
    async def create_router(cls) -> "DocKnowledgeRAG":
        """
        创建路由器实例

        Returns:
            路由器实例
        """
        return cls()