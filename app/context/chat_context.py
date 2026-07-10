from dataclasses import dataclass, field
from typing_extensions import Any
from ..db_connection_pool.zb_ai_workflow_util import ZbAiWorkflow
@dataclass
class ChatContext:
    user_id: str
    conversation_id: str
    conversation_name:str
    workflow:ZbAiWorkflow = None
    seq_no:str = None
    chat_history:list[dict] = None
    ##是否按照节点的去查找只跟当前节点相关的历史记录
    is_query_history_node_id:bool = False
    ##执行步数
    run_steps:int = 0
    ##最大执行步数，避免因意图识别问题，无限制执行
    run_steps_max:int = 5
    ##历史消息的最大条数，默认十二条
    history_max_records:int = 12
    ##对话类型，默认为1:模型对话。2、知识库对话
    conversation_type:int = 1
    ##对话用到的文件id列表，如果有多个，请用','分隔
    file_list:str = None
    ##用户名字
    user_name:str = None
    ##是否使用历史消息
    use_history:bool = True
    ##知识库会话id
    knowledge_conversation_id:str = None
    ##context_info里面的knowledge_conversation_id在调用完知识库之后，必须给赋值，以便更新到数据库
    context_info: dict[str,Any] = field(default_factory=lambda: {"knowledge_conversation_id":None,"end_business":False})
    ##用户输入
    user_input:str = ""
    ## 用户输入是否是中断后的用户响应
    is_user_input_interrupt_ack:bool = False
    ## 本轮对话的thread_id
    thread_id:str = None
    ## 用于消息摘要的大模型实例，middleware 通过此属性获取
    summary_llm:Any = None
    ## 从已完成 thread 快照加载的历史消息，由 middleware 临时拼接，不存入 state
    snapshot_messages:list = None

    def set_business_state_completed(self):
        """设置业务状态为已完成"""
        self.context_info["end_business"] = True