"""
小帮工作流实现

处理小帮相关业务的工作流逻辑
"""
import sys
import os
# 添加项目根目录到 sys.path，支持直接运行此文件
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from typing import AsyncGenerator, Dict, Any
from ..context.chat_context import ChatContext
from ..core.logger import app_logger, set_trace_id, get_trace_id
from ..db_connection_pool.zb_conversation_nodes_util import _default_cache as node_cache
from ..db_connection_pool.zb_conversation_util import ZbConversationUtil
from ..db_connection_pool.zb_ai_workflow_util import ZbAiWorkflow, _default_cache as workflow_cache
from ..abstract_ai import AbstractAI
import uuid
import random
from datetime import datetime
from fastapi.responses import StreamingResponse
from fastapi import Request
import json
import asyncio
import traceback
from ..tool.util.interrupt_message import InterruptMessage
from ..tool.util.resume_message import ResumeMessage
class ZBXiaoBangWorkflow:
    """小帮工作流类"""

    @staticmethod
    async def process_user_input(
        user_id: str,
        user_input: str,
        conversation_id: str,
        workflow_id: str,
        seq_no:str,
        file_list: str = "",
        history_max_records:int = 10,
        conversation_type:int = 1,
        user_name: str = None,
        use_history: bool = True,
        is_user_input_interrupt_ack: bool = False
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        处理用户输入并管理多轮对话（流式输出）

        Args:
            user_id: 用户ID
            user_input: 用户输入
            conversation_id: 会话ID
            workflow_id: 工作流ID
            seq_no: 序列号
            file_list: 文件ID列表（逗号分隔）
            history_max_records: 历史消息最大记录数
            conversation_type: 会话类型
            user_name: 用户名称

        Yields:
            流式输出的字典
        """
        # 如果当前没有 trace_id，则生成一个
        if get_trace_id() == "N/A":
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S") + f"{datetime.now().microsecond // 1000:03d}"
            random_suffix = f"{random.randint(0, 999999):06d}"
            trace_id = f"{timestamp}-{random_suffix}-{seq_no or ''}"
            set_trace_id(trace_id)

        # 获取工作流配置
        workflow:ZbAiWorkflow = await workflow_cache.get_workflow_by_id(workflow_id)
        if not workflow:
            yield {
                "message_type": "error",
                "content": f"未找到工作流配置: {workflow_id}",
                "is_last": True,
                "is_over": True,
                "conversation_id": conversation_id,
                "seq_no": seq_no
            }
            return

        app_logger.info(f"工作流配置: workflow_id={workflow.workflow_id}, "
                          f"entry_node_id={workflow.entry_node_id}, "
                          f"app_id={workflow.app_id}")

        # 准备conversation_id和conversation_name
        knowledge_conversation_id = None
        if not conversation_id or conversation_id.strip() == "":
            # 如果没有提供conversation_id，则生成一个新的UUID作为conversation_id
            conversation_id = str(uuid.uuid4())
            conversation_name = user_input[:128] if len(user_input) > 128 else user_input
            run_node: AbstractAI = await node_cache.instantiate_node(workflow.entry_node_id)
        else:
            conversation = await ZbConversationUtil.load_conversation(conversation_id, user_id)
            if conversation:
                conversation_id = conversation.conversation_id
                conversation_name = conversation.conversation_name
                knowledge_conversation_id = conversation.knowledge_conversation_id
                run_node: AbstractAI = await node_cache.instantiate_node(conversation.node_id)
            else:
                conversation_name = user_input[:128] if len(user_input) > 128 else user_input
                yield {
                    "message_type": "model",
                    "content": f"未找到用户{user_id}的{conversation_id}对应的会话信息，或者该会话信息有误",
                    "is_last": True,
                    "is_over": True,
                    "conversation_id": conversation_id,
                    "seq_no": seq_no
                }
                return

        # 创建上下文对象
        context: ChatContext = ChatContext(
            user_id=user_id,
            conversation_id=conversation_id,
            conversation_name=conversation_name,
            workflow=workflow,
            seq_no=seq_no,
            user_input=user_input,
            chat_history= await AbstractAI.get_chat_history_from_db(conversation_id, message_status=1,max=history_max_records,is_human_generated=0) if workflow.enhance_intent_classify == 0 and use_history else None,
            is_query_history_node_id=True if workflow.enhance_intent_classify != 0 else False,
            history_max_records = history_max_records,
            conversation_type = conversation_type,
            file_list=file_list,
            user_name=user_name,
            use_history=use_history,
            knowledge_conversation_id=knowledge_conversation_id,
            is_user_input_interrupt_ack=is_user_input_interrupt_ack
        )
        async for chunk in run_node.process_user_input(user_input, context):
            # 在返回结果中添加 seq_no
            if isinstance(chunk, dict) and "seq_no" not in chunk:
                chunk["seq_no"] = seq_no
            yield chunk
    
    @staticmethod
    async def _event_generator(
        user_id: str,
        user_input: str,
        conversation_id: str,
        workflow_id: str,
        seq_no: str,
        file_list: str = "",
        history_max_records: int = 10,
        conversation_type: int = 1,
        user_name: str = None,
        use_history: bool = True,
        is_user_input_interrupt_ack: bool = False
    ):
        """流式响应生成器，直接返回JSON字符串

        统一响应结构：
        {
          "content": "",           # 消息内容
          "status": "",            # processing（处理中）/ done（完成）
          "conversation_id": "",   # 会话ID
          "content_type": "",      # model / tool / interrupt / knowledge_base / error
          "seq_no": ""             # 对话流水号
        }

        每条消息用双换行符分隔
        """
        last_conversation_id = conversation_id
        response = {
            "content": "",
            "status": "done",
            "conversation_id": last_conversation_id,
            "content_type": "model",
            "seq_no": seq_no
        }
        try:
            app_logger.info(f"开始处理请求: user_id={user_id}, conversation_id={conversation_id}")

            async for chunk in ZBXiaoBangWorkflow.process_user_input(
                user_id, user_input, conversation_id, workflow_id, seq_no,
                file_list, history_max_records, conversation_type, user_name, use_history,
                is_user_input_interrupt_ack
            ):
                if not isinstance(chunk, dict):
                    chunk = {"content": str(chunk), "message_type": "model"}

                # 记录 conversation_id（如果返回了新的）
                if chunk.get("conversation_id"):
                    last_conversation_id = chunk["conversation_id"]

                # 判断状态：is_last && is_over 时为 done，其他为 processing
                is_last = chunk.get("is_last", False)
                is_over = chunk.get("is_over", False)
                status = "done" if (is_last and is_over) else "processing"

                # 构建简化响应结构
                response = {
                    "content": chunk.get("content", ""),
                    "status": status,
                    "conversation_id": last_conversation_id,
                    "content_type": chunk.get("message_type", "model"),
                    "seq_no": seq_no
                }
                # 如果状态为 done，结束生成器
                if status == "done":
                    app_logger.info(f"业务处理完成 (status=done)")
                    break
                else:
                    yield f"{json.dumps(response, ensure_ascii=False)}\n\n"
            yield f"{json.dumps(response, ensure_ascii=False)}\n\n"

        except asyncio.CancelledError:
            app_logger.warning(f"客户端断开连接，请求被取消")
            raise
        except GeneratorExit:
            app_logger.warning(f"生成器被外部关闭")
            raise
        except Exception as e:
            app_logger.error(f"生成器异常: {e}")
            # 发送错误信息
            try:
                error_response = {
                    "content": "",
                    "status": "done",
                    "conversation_id": last_conversation_id,
                    "content_type": "error",
                    "seq_no": seq_no
                }
                yield f"{json.dumps(error_response, ensure_ascii=False)}\n\n"
            except:
                pass
    
    @staticmethod
    async def ai_brain_stream_endpoint(request: Request):
        """
        AI智能大脑流式API接口

        请求参数（Query Params）：
        - user_id: 用户ID（必填）
        - user_input: 用户输入内容（必填）
        - conversation_id: 会话ID（可选，首次对话为空，续传时提供）
        - workflow_id: 工作流ID（必填）
        - seq_no: 序列号（必填）
        - file_list: 文件ID列表，逗号分隔（可选）
        - history_max_records: 历史消息最大记录数（默认10）
        - conversation_type: 会话类型（默认1）

        返回：流式JSON响应，每条消息用双换行符分隔，统一结构：
        {
          "content": "",           # 消息内容
          "status": "",           # processing（处理中）/ done（完成）
          "conversation_id": "",   # 会话ID
          "content_type": "",      # model / tool / interrupt / knowledge_base / error
          "seq_no": ""           # 对话流水号
        }

        状态说明：
        - status="processing": 正在处理消息
        - status="done": 处理完成（is_last && is_over 时）
        - content_type="model": AI回复消息
        - content_type="tool": 工具调用消息
        - seq_no: 对话流水号，唯一标识每一次对话

        响应示例：
        {"content":"您好！","status":"processing","conversation_id":"abc123","content_type":"model","seq_no":"202603311200001234567"}

        {"content":"预订成功！","status":"done","conversation_id":"abc123","content_type":"model","seq_no":"202603311200001234567"}

        interrupt的响应的content示例如下：
        {"e44e670a632e4d48bd413828fb68c78a:981e83f3680df4590cb4c9e61265a38e": "以下是您要预定的会议...", "e44e670a632e4d48bd413828fb68c78a:342b324efdb48ce2c87f08e429802e31": "以下是您要预定的会议室信息..."}
        {"thread_id:interrupt_id":"interrupt_value"}
        """
        query_params = dict(request.query_params)

        user_id = query_params.get('user_id', None)
        user_input = query_params.get('user_input', None)
        conversation_id = query_params.get('conversation_id', None)
        workflow_id = query_params.get('workflow_id', None)
        seq_no = query_params.get('seq_no', None)
        file_list = query_params.get('file_list', None)
        history_max_records = int(query_params.get('history_max_records', 10))
        conversation_type = int(query_params.get('conversation_type', 1))
        user_name = query_params.get('user_name', None)
        use_history = query_params.get('use_history', 'true').lower() == 'true'
        is_user_input_interrupt_ack = query_params.get('is_user_input_interrupt_ack', 'false').lower() == 'true'

        # 必填参数校验
        required_params = {
            "user_id": user_id,
            "user_input": user_input,
            "workflow_id": workflow_id,
            "seq_no": seq_no,
            "user_name": user_name,
        }
        missing = [k for k, v in required_params.items() if not v]
        if missing:
            async def error_generator():
                error_response = {
                    "content": f"缺少必填参数：{' / '.join(missing)}",
                    "status": "done",
                    "conversation_id": conversation_id or "",
                    "content_type": "model",
                    "seq_no": seq_no or ""
                }
                yield f"{json.dumps(error_response, ensure_ascii=False)}\n\n"
            return StreamingResponse(
                error_generator(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                }
            )

        return StreamingResponse(
            ZBXiaoBangWorkflow._event_generator(
                user_id, user_input, conversation_id, workflow_id, seq_no,
                file_list, history_max_records, conversation_type, user_name, use_history,
                is_user_input_interrupt_ack
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # 禁用 Nginx 缓冲
            }
        )


if __name__ == "__main__":
    """
    控制台交互示例
    使用方法：
    1. 设置正确的 workflow_id
    2. 运行此脚本
    3. 在控制台输入与 AI 助手对话
    4. 输入 'quit'、'exit' 或 '退出' 结束对话
    """

    async def console_chat():
        """控制台对话函数"""
        print("=" * 70)
        print("欢迎使用小帮 AI 助手！")
        print("=" * 70)
        print("请输入用户ID和消息与AI助手对话")
        print("-" * 70)

        # 配置参数
        workflow_id = "xiaobang_all"#xiaobang_all#""##"xiaobang_knowledge_search_employee"  # 请根据实际情况修改为正确的工作流ID
        conversation_id = ""  # 首次对话为空，续传时使用返回的 conversation_id
        is_user_input_interrupt_ack = False
        print(f"工作流ID: {workflow_id}")
        print("-" * 70)

        # 退出关键词集合
        exit_keywords = {"quit", "exit", "q", "退出"}
        should_exit = False

        interrupt_map:dict[str, InterruptMessage] = {}
        while True:
            try:
                # 获取用户ID（如果还没有）
                user_input = "zhanglulu"##nput("\n用户ID（例如: user_001）: ").strip()

                if not user_input or user_input.lower() in exit_keywords:
                    print("\n感谢使用，再见！")
                    break

                user_id = user_input

                # 对话循环
                while True:
                    # 获取用户输入
                    user_input = input("\n您: ").strip()

                    # 检查是否退出
                    if user_input.lower() in exit_keywords:
                        print("\n小帮: 感谢使用，再见！")
                        should_exit = True
                        break

                    # 如果输入为空，继续下一轮
                    if not user_input:
                        continue

                    print("\n小帮: ", end="", flush=True)

                    if is_user_input_interrupt_ack:
                        for key,value in interrupt_map.items():
                            interrupt_message:InterruptMessage = InterruptMessage.from_str_or_dict(value)
                            resume_message: ResumeMessage = ResumeMessage(
                                resume_business_type=interrupt_message.interrupt_bisiness_type,
                                resume_message=user_input,
                                extra_info={}
                            )
                            interrupt_map[key] = resume_message.to_json_str()
                        user_input = json.dumps(interrupt_map, ensure_ascii=False)
                    
                    # 调用工作流处理用户输入
                    last_conversation_id = conversation_id
                    async for chunk in ZBXiaoBangWorkflow.process_user_input(
                        user_id=user_id,
                        user_input=user_input,
                        user_name=user_id,
                        conversation_id=conversation_id,
                        workflow_id=workflow_id,
                        seq_no=str(uuid.uuid4()),
                        is_user_input_interrupt_ack=is_user_input_interrupt_ack
                    ):
                        content = chunk.get("content", "")
                        message_type = chunk.get("message_type", "model")

                        if message_type == "interrupt":
                            # 收到 interrupt 消息，标记下次输入为中断确认
                            is_user_input_interrupt_ack = True
                            if content:
                                interrupt_map = json.loads(content)
                            print(f"【需要确认】\n{content}", end="", flush=True)
                        else:
                            print(content, end="", flush=True)
                            is_user_input_interrupt_ack = False


                        # 更新 conversation_id
                        if chunk.get("conversation_id"):
                            last_conversation_id = chunk["conversation_id"]

                        # 判断是否是最后一条消息
                        if chunk.get("is_last", False):
                            print()

                    # 更新 conversation_id，用于下一轮对话
                    conversation_id = last_conversation_id

                if should_exit:
                    break

            except (KeyboardInterrupt, asyncio.CancelledError):
                print("\n\n对话被中断，再见！")
                break
            except Exception as e:
                print(f"\n发生错误: {str(e)}")
                traceback.print_exc()
                continue

    # 运行主函数
    try:
        asyncio.run(console_chat())
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass  # 正常退出，忽略取消错误
    except Exception as e:
        print(f"\n程序异常退出: {e}")