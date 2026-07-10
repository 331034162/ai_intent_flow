from typing import Literal
class ToolResponseMessage:

    """
    响应的消息内容
    """
    message:str

    """"
    消息类型。
    model:大模型消息
    tool：工具消息
    """
    message_type:Literal["model","tool","interrupt","knowledge_base"]

    """
    大模型token使用情况，比如:
    {'input_tokens': 1326, 'output_tokens': 144, 'total_tokens': 1470, 'input_token_details': {'cache_read': 832}
    """
    usage_metadata:dict

    """
    langraph信息，比如
    {'langgraph_step': 2, 'langgraph_node': 'tools', 'langgraph_triggers': ('__pregel_push',), 'langgraph_path': ('__pregel_push', 0, False), 'langgraph_checkpoint_ns': 'tools:2a47eac1-9b26-5cdc-284f-5e058864482d'}
    或者
    {'langgraph_step': 1, 'langgraph_node': 'model', 'langgraph_triggers': ('branch:to:model',), 'langgraph_path': ('__pregel_pull', 'model'), 'langgraph_checkpoint_ns': 'model:d35186b4-e7ed-b1b9-7e2d-437d1c663003', 'checkpoint_ns': 'model:d35186b4-e7ed-b1b9-7e2d-437d1c663003', 'ls_provider': 'openai', 'ls_model_name': 'deepseek-chat', 'ls_model_type': 'chat', 'ls_temperature': 0.7, 'ls_max_tokens': 262144}    
    """
    langraph_info:dict

    """
    节点信息统信息，比如
    content='' additional_kwargs={} response_metadata={'finish_reason': 'tool_calls', 'model_name': 'deepseek-chat', 'system_fingerprint': 'fp_eaab8d114b_prod0820_fp8_kvcache', 'model_provider': 'openai'} id='lc_run--019c8d51-4562-7962-99ab-686fc99daad0' tool_calls=[] invalid_tool_calls=[] usage_metadata={'input_tokens': 1326, 'output_tokens': 144, 'total_tokens': 1470, 'input_token_details': {'cache_read': 832}, 'output_token_details': {}} tool_call_chunks=[]
    """
    response_metadata:dict

    """结束原因"""
    finish_reason:str

    """块的位置，如果值等于last，则表示这是最后一块消息"""
    chunk_position:str