"""
管理 API：
- 对话流程节点配置、意图节点提示词配置查询（只读）
- 会话节点信息管理（zb_conversation_nodes）增删改查
- AI工作流管理（zb_ai_workflow）增删改查
- 大模型信息管理（zb_llm_models）增删改查
- 会话节点配置管理（zb_conversation_nodes + zb_node_prompt_ver_ctrl）
- 节点提示词版本管理（zb_node_prompt_ver_ctrl + zb_node_prompt）
"""
import traceback
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import text

from ..core.logger import app_logger
from ..db_connection_pool.async_mysql_connection import get_async_pool_instance

router = APIRouter()


# ============================================================
# 只读配置查询（节点 / 提示词缓存）
# ============================================================
@router.get("/api/nodes", summary="获取对话流程节点配置列表")
async def get_nodes():
    """从 zb_conversation_node 缓存读取所有节点配置（对话流程节点配置）"""
    try:
        from ..db_connection_pool.zb_conversation_nodes_util import _default_cache
        nodes = await _default_cache.get_all_nodes()
        data = [{
            "node_id": n.node_id,
            "node_name": n.node_name,
            "node_type": n.node_type,
            "node_description": n.node_description,
            "node_func_path": n.node_func_path,
            "node_business_range": n.node_business_range,
            "status": n.status,
            "parent_node_id": n.parent_node_id,
            "model_provider": n.model_provider,
            "model_name": n.model_name,
            "model_url": n.model_url,
        } for n in nodes]
        return {"code": 0, "message": "success", "data": data}
    except Exception as e:
        app_logger.error(f"获取节点配置失败: {str(e)}\n{traceback.format_exc()}")
        return {"code": -1, "message": f"获取失败: {str(e)}", "data": []}


@router.get("/api/prompts", summary="获取意图节点提示词配置列表")
async def get_prompts():
    """从 zb_node_prompt 缓存读取所有提示词配置（意图节点提示词配置）"""
    try:
        from ..db_connection_pool.zb_node_prompt_util import _default_cache
        prompts = await _default_cache.get_all_prompts()
        data = [{
            "id": p.id,
            "node_id": p.node_id,
            "prompt_key": p.prompt_key,
            "prompt_content": p.prompt_content,
            "model_id": p.model_id,
            "model_ext_param": p.model_ext_param,
            "prompt_var_names": p.prompt_var_names,
        } for p in prompts]
        return {"code": 0, "message": "success", "data": data}
    except Exception as e:
        app_logger.error(f"获取提示词配置失败: {str(e)}\n{traceback.format_exc()}")
        return {"code": -1, "message": f"获取失败: {str(e)}", "data": []}


# ============================================================
# 通用数据库会话辅助
# ============================================================
async def _get_session():
    db_conn = await get_async_pool_instance()
    return await db_conn.get_session()


def _bool_to_int(v, default=0) -> int:
    if v is None:
        return default
    return 1 if v else 0


# ============================================================
# 一、会话节点信息管理（zb_conversation_nodes）
# ============================================================
class ConversationNodeItem(BaseModel):
    node_id: str
    node_name: str
    node_type: str
    node_business_range: str = ""
    node_description: Optional[str] = None
    node_func_path: Optional[str] = None
    parent_node_id: Optional[str] = None
    model_id: Optional[str] = None
    model_ext_param: Optional[str] = None     # JSON 字符串
    status: int = 1


@router.get("/api/conversation-nodes", summary="查询会话节点列表（分页）")
async def list_conversation_nodes(
    node_type: Optional[str] = Query(None, description="按节点类型过滤"),
    keyword: Optional[str] = Query(None, description="模糊匹配 node_id / node_name"),
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(10, ge=1, le=1000, description="每页条数"),
):
    try:
        session = await _get_session()
        where = " WHERE 1=1"
        fparams = {}
        if node_type:
            where += " AND node_type = :node_type"
            fparams["node_type"] = node_type
        if keyword:
            where += " AND (node_id LIKE :kw OR node_name LIKE :kw)"
            fparams["kw"] = f"%{keyword}%"
        select_cols = """
            SELECT node_id, node_name, node_type, node_business_range, node_description,
                   node_func_path, parent_node_id, model_id, model_ext_param, status, updated_at
            FROM zb_conversation_nodes
        """
        async with session:
            async with session.begin():
                count_row = (await session.execute(
                    text("SELECT COUNT(*) AS cnt FROM zb_conversation_nodes" + where), fparams
                )).fetchone()
                total = int(count_row[0]) if count_row else 0
                offset = (page - 1) * page_size
                result = await session.execute(
                    text(select_cols + where + f" ORDER BY id DESC LIMIT {page_size} OFFSET {offset}"), fparams
                )
                rows = [dict(r._mapping) for r in result.fetchall()]
        return {"code": 0, "message": "success", "data": rows, "total": total, "page": page, "page_size": page_size}
    except Exception as e:
        app_logger.error(f"查询会话节点失败: {str(e)}\n{traceback.format_exc()}")
        return {"code": -1, "message": f"查询失败: {str(e)}", "data": [], "total": 0, "page": page, "page_size": page_size}


@router.get("/api/conversation-nodes/{node_id}", summary="查询单个会话节点")
async def get_conversation_node(node_id: str):
    try:
        session = await _get_session()
        sql = """
            SELECT node_id, node_name, node_type, node_business_range, node_description,
                   node_func_path, parent_node_id, model_id, model_ext_param, status, updated_at
            FROM zb_conversation_nodes WHERE node_id = :node_id LIMIT 1
        """
        async with session:
            async with session.begin():
                result = await session.execute(text(sql), {"node_id": node_id})
                row = result.fetchone()
        if not row:
            return {"code": -1, "message": "节点不存在", "data": None}
        return {"code": 0, "message": "success", "data": dict(row._mapping)}
    except Exception as e:
        app_logger.error(f"查询会话节点失败: {str(e)}\n{traceback.format_exc()}")
        return {"code": -1, "message": f"查询失败: {str(e)}", "data": None}


@router.post("/api/conversation-nodes", summary="新增会话节点")
async def create_conversation_node(item: ConversationNodeItem):
    try:
        session = await _get_session()
        sql = """
            INSERT INTO zb_conversation_nodes
                (node_id, node_name, node_type, node_business_range, node_description,
                 node_func_path, parent_node_id, model_id, model_ext_param, status)
            VALUES
                (:node_id, :node_name, :node_type, :node_business_range, :node_description,
                 :node_func_path, :parent_node_id, :model_id, :model_ext_param, :status)
        """
        params = {
            "node_id": item.node_id, "node_name": item.node_name, "node_type": item.node_type,
            "node_business_range": item.node_business_range, "node_description": item.node_description,
            "node_func_path": item.node_func_path, "parent_node_id": item.parent_node_id,
            "model_id": item.model_id, "model_ext_param": item.model_ext_param, "status": item.status,
        }
        async with session:
            async with session.begin():
                await session.execute(text(sql), params)
        # 刷新节点缓存
        try:
            from ..db_connection_pool.zb_conversation_nodes_util import _default_cache
            await _default_cache.force_refresh()
        except Exception as ce:
            app_logger.warning(f"刷新节点缓存失败(忽略): {ce}")
        return {"code": 0, "message": "创建成功"}
    except Exception as e:
        app_logger.error(f"新增会话节点失败: {str(e)}\n{traceback.format_exc()}")
        return {"code": -1, "message": f"创建失败: {str(e)}"}


@router.put("/api/conversation-nodes/{node_id}", summary="更新会话节点")
async def update_conversation_node(node_id: str, item: ConversationNodeItem):
    try:
        session = await _get_session()
        sql = """
            UPDATE zb_conversation_nodes SET
                node_name = :node_name, node_type = :node_type, node_business_range = :node_business_range,
                node_description = :node_description, node_func_path = :node_func_path,
                parent_node_id = :parent_node_id, model_id = :model_id,
                model_ext_param = :model_ext_param, status = :status
            WHERE node_id = :node_id
        """
        params = {
            "node_name": item.node_name, "node_type": item.node_type,
            "node_business_range": item.node_business_range, "node_description": item.node_description,
            "node_func_path": item.node_func_path, "parent_node_id": item.parent_node_id,
            "model_id": item.model_id, "model_ext_param": item.model_ext_param,
            "status": item.status, "node_id": node_id,
        }
        async with session:
            async with session.begin():
                result = await session.execute(text(sql), params)
        if result.rowcount == 0:
            return {"code": -1, "message": "节点不存在"}
        try:
            from ..db_connection_pool.zb_conversation_nodes_util import _default_cache
            await _default_cache.force_refresh()
        except Exception as ce:
            app_logger.warning(f"刷新节点缓存失败(忽略): {ce}")
        return {"code": 0, "message": "更新成功"}
    except Exception as e:
        app_logger.error(f"更新会话节点失败: {str(e)}\n{traceback.format_exc()}")
        return {"code": -1, "message": f"更新失败: {str(e)}"}


@router.delete("/api/conversation-nodes/{node_id}", summary="删除会话节点")
async def delete_conversation_node(node_id: str):
    try:
        session = await _get_session()
        async with session:
            async with session.begin():
                result = await session.execute(
                    text("DELETE FROM zb_conversation_nodes WHERE node_id = :node_id"),
                    {"node_id": node_id}
                )
        if result.rowcount == 0:
            return {"code": -1, "message": "节点不存在"}
        try:
            from ..db_connection_pool.zb_conversation_nodes_util import _default_cache
            await _default_cache.force_refresh()
        except Exception as ce:
            app_logger.warning(f"刷新节点缓存失败(忽略): {ce}")
        return {"code": 0, "message": "删除成功"}
    except Exception as e:
        app_logger.error(f"删除会话节点失败: {str(e)}\n{traceback.format_exc()}")
        return {"code": -1, "message": f"删除失败: {str(e)}"}


# ============================================================
# 二、AI工作流管理（zb_ai_workflow）
# ============================================================
class AiWorkflowItem(BaseModel):
    workflow_id: str
    workflow_desc: Optional[str] = None
    entry_node_id: str
    app_id: str
    intent_classify_node_id: Optional[str] = None
    status: int = 1
    enhance_intent_classify: int = 1


@router.get("/api/ai-workflows", summary="查询AI工作流列表（分页）")
async def list_ai_workflows(
    keyword: Optional[str] = Query(None, description="模糊匹配 workflow_id / workflow_desc"),
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(10, ge=1, le=1000, description="每页条数"),
):
    try:
        session = await _get_session()
        where = " WHERE 1=1"
        fparams = {}
        if keyword:
            where += " AND (workflow_id LIKE :kw OR workflow_desc LIKE :kw)"
            fparams["kw"] = f"%{keyword}%"
        select_cols = """
            SELECT id, workflow_id, workflow_desc, entry_node_id, app_id,
                   intent_classify_node_id, status, enhance_intent_classify,
                   created_at, updated_at
            FROM zb_ai_workflow
        """
        async with session:
            async with session.begin():
                count_row = (await session.execute(
                    text("SELECT COUNT(*) AS cnt FROM zb_ai_workflow" + where), fparams
                )).fetchone()
                total = int(count_row[0]) if count_row else 0
                offset = (page - 1) * page_size
                result = await session.execute(
                    text(select_cols + where + f" ORDER BY id DESC LIMIT {page_size} OFFSET {offset}"), fparams
                )
                rows = [dict(r._mapping) for r in result.fetchall()]
        return {"code": 0, "message": "success", "data": rows, "total": total, "page": page, "page_size": page_size}
    except Exception as e:
        app_logger.error(f"查询AI工作流失败: {str(e)}\n{traceback.format_exc()}")
        return {"code": -1, "message": f"查询失败: {str(e)}", "data": [], "total": 0, "page": page, "page_size": page_size}


@router.get("/api/ai-workflows/{workflow_id}", summary="查询单个AI工作流")
async def get_ai_workflow(workflow_id: str):
    try:
        session = await _get_session()
        sql = """
            SELECT id, workflow_id, workflow_desc, entry_node_id, app_id,
                   intent_classify_node_id, status, enhance_intent_classify,
                   created_at, updated_at
            FROM zb_ai_workflow WHERE workflow_id = :workflow_id LIMIT 1
        """
        async with session:
            async with session.begin():
                result = await session.execute(text(sql), {"workflow_id": workflow_id})
                row = result.fetchone()
        if not row:
            return {"code": -1, "message": "工作流不存在", "data": None}
        return {"code": 0, "message": "success", "data": dict(row._mapping)}
    except Exception as e:
        app_logger.error(f"查询AI工作流失败: {str(e)}\n{traceback.format_exc()}")
        return {"code": -1, "message": f"查询失败: {str(e)}", "data": None}


@router.post("/api/ai-workflows", summary="新增AI工作流")
async def create_ai_workflow(item: AiWorkflowItem):
    try:
        session = await _get_session()
        sql = """
            INSERT INTO zb_ai_workflow
                (workflow_id, workflow_desc, entry_node_id, app_id,
                 intent_classify_node_id, status, enhance_intent_classify)
            VALUES
                (:workflow_id, :workflow_desc, :entry_node_id, :app_id,
                 :intent_classify_node_id, :status, :enhance_intent_classify)
        """
        params = {
            "workflow_id": item.workflow_id, "workflow_desc": item.workflow_desc,
            "entry_node_id": item.entry_node_id, "app_id": item.app_id,
            "intent_classify_node_id": item.intent_classify_node_id,
            "status": item.status, "enhance_intent_classify": item.enhance_intent_classify,
        }
        async with session:
            async with session.begin():
                await session.execute(text(sql), params)
        return {"code": 0, "message": "创建成功"}
    except Exception as e:
        app_logger.error(f"新增AI工作流失败: {str(e)}\n{traceback.format_exc()}")
        return {"code": -1, "message": f"创建失败: {str(e)}"}


@router.put("/api/ai-workflows/{workflow_id}", summary="更新AI工作流")
async def update_ai_workflow(workflow_id: str, item: AiWorkflowItem):
    try:
        session = await _get_session()
        sql = """
            UPDATE zb_ai_workflow SET
                workflow_desc = :workflow_desc,
                entry_node_id = :entry_node_id,
                app_id = :app_id,
                intent_classify_node_id = :intent_classify_node_id,
                status = :status,
                enhance_intent_classify = :enhance_intent_classify
            WHERE workflow_id = :workflow_id
        """
        params = {
            "workflow_desc": item.workflow_desc,
            "entry_node_id": item.entry_node_id,
            "app_id": item.app_id,
            "intent_classify_node_id": item.intent_classify_node_id,
            "status": item.status,
            "enhance_intent_classify": item.enhance_intent_classify,
            "workflow_id": workflow_id,
        }
        async with session:
            async with session.begin():
                result = await session.execute(text(sql), params)
        if result.rowcount == 0:
            return {"code": -1, "message": "工作流不存在"}
        return {"code": 0, "message": "更新成功"}
    except Exception as e:
        app_logger.error(f"更新AI工作流失败: {str(e)}\n{traceback.format_exc()}")
        return {"code": -1, "message": f"更新失败: {str(e)}"}


@router.delete("/api/ai-workflows/{workflow_id}", summary="删除AI工作流")
async def delete_ai_workflow(workflow_id: str):
    try:
        session = await _get_session()
        async with session:
            async with session.begin():
                result = await session.execute(
                    text("DELETE FROM zb_ai_workflow WHERE workflow_id = :workflow_id"),
                    {"workflow_id": workflow_id}
                )
        if result.rowcount == 0:
            return {"code": -1, "message": "工作流不存在"}
        return {"code": 0, "message": "删除成功"}
    except Exception as e:
        app_logger.error(f"删除AI工作流失败: {str(e)}\n{traceback.format_exc()}")
        return {"code": -1, "message": f"删除失败: {str(e)}"}


# ============================================================
# 三、大模型信息管理（zb_llm_models）
# ============================================================
class LlmModelItem(BaseModel):
    model_id: str
    model_name: str
    description: Optional[str] = None
    provider: str
    api_model_name: str
    base_url: str
    api_key: str
    context_length: int = 4096
    supports_streaming: bool = True
    supports_function_calling: bool = False
    supports_vision: bool = False
    supports_search: bool = False
    supports_json_mode: bool = False
    input_price: float = 0.0
    output_price: float = 0.0
    currency: str = "CNY"
    is_enabled: bool = True
    is_production_ready: bool = False
    model_category: Optional[str] = None
    model_group: Optional[str] = None
    tags: Optional[str] = None
    api_parameters: Optional[str] = None
    custom_config: Optional[str] = None


@router.get("/api/llm-models", summary="查询大模型列表（分页）")
async def list_llm_models(
    provider: Optional[str] = Query(None, description="按 provider 过滤"),
    keyword: Optional[str] = Query(None, description="模糊匹配 model_id / model_name"),
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(10, ge=1, le=1000, description="每页条数"),
):
    try:
        session = await _get_session()
        where = " WHERE 1=1"
        fparams = {}
        if provider:
            where += " AND provider = :provider"
            fparams["provider"] = provider
        if keyword:
            where += " AND (model_id LIKE :kw OR model_name LIKE :kw)"
            fparams["kw"] = f"%{keyword}%"
        select_cols = """
            SELECT id, model_id, model_name, description, provider, api_model_name,
                   base_url, api_key, context_length, supports_streaming, supports_function_calling,
                   supports_vision, supports_search, supports_json_mode, input_price,
                   output_price, currency, is_enabled, is_production_ready,
                   model_category, model_group, tags, api_parameters, custom_config, updated_at
            FROM zb_llm_models
        """
        async with session:
            async with session.begin():
                count_row = (await session.execute(
                    text("SELECT COUNT(*) AS cnt FROM zb_llm_models" + where), fparams
                )).fetchone()
                total = int(count_row[0]) if count_row else 0
                offset = (page - 1) * page_size
                result = await session.execute(
                    text(select_cols + where + f" ORDER BY id DESC LIMIT {page_size} OFFSET {offset}"), fparams
                )
                rows = [dict(r._mapping) for r in result.fetchall()]
        return {"code": 0, "message": "success", "data": rows, "total": total, "page": page, "page_size": page_size}
    except Exception as e:
        app_logger.error(f"查询大模型失败: {str(e)}\n{traceback.format_exc()}")
        return {"code": -1, "message": f"查询失败: {str(e)}", "data": [], "total": 0, "page": page, "page_size": page_size}


@router.get("/api/llm-models/{model_id}", summary="查询单个大模型")
async def get_llm_model(model_id: str):
    try:
        session = await _get_session()
        sql = """
            SELECT id, model_id, model_name, description, provider, api_model_name,
                   base_url, api_key, context_length, supports_streaming, supports_function_calling,
                   supports_vision, supports_search, supports_json_mode, input_price,
                   output_price, currency, is_enabled, is_production_ready,
                   model_category, model_group, tags, api_parameters, custom_config, updated_at
            FROM zb_llm_models WHERE model_id = :model_id LIMIT 1
        """
        async with session:
            async with session.begin():
                result = await session.execute(text(sql), {"model_id": model_id})
                row = result.fetchone()
        if not row:
            return {"code": -1, "message": "模型不存在", "data": None}
        return {"code": 0, "message": "success", "data": dict(row._mapping)}
    except Exception as e:
        app_logger.error(f"查询大模型失败: {str(e)}\n{traceback.format_exc()}")
        return {"code": -1, "message": f"查询失败: {str(e)}", "data": None}


@router.post("/api/llm-models", summary="新增大模型")
async def create_llm_model(item: LlmModelItem):
    try:
        session = await _get_session()
        sql = """
            INSERT INTO zb_llm_models
                (model_id, model_name, description, provider, api_model_name, base_url, api_key,
                 context_length, supports_streaming, supports_function_calling, supports_vision,
                 supports_search, supports_json_mode, input_price, output_price, currency,
                 is_enabled, is_production_ready, model_category, model_group, tags,
                 api_parameters, custom_config, version)
            VALUES
                (:model_id, :model_name, :description, :provider, :api_model_name, :base_url, :api_key,
                 :context_length, :supports_streaming, :supports_function_calling, :supports_vision,
                 :supports_search, :supports_json_mode, :input_price, :output_price, :currency,
                 :is_enabled, :is_production_ready, :model_category, :model_group, :tags,
                 :api_parameters, :custom_config, 1)
        """
        params = {
            "model_id": item.model_id, "model_name": item.model_name, "description": item.description,
            "provider": item.provider, "api_model_name": item.api_model_name, "base_url": item.base_url,
            "api_key": item.api_key, "context_length": item.context_length,
            "supports_streaming": _bool_to_int(item.supports_streaming, 1),
            "supports_function_calling": _bool_to_int(item.supports_function_calling),
            "supports_vision": _bool_to_int(item.supports_vision),
            "supports_search": _bool_to_int(item.supports_search),
            "supports_json_mode": _bool_to_int(item.supports_json_mode),
            "input_price": item.input_price, "output_price": item.output_price, "currency": item.currency,
            "is_enabled": _bool_to_int(item.is_enabled, 1),
            "is_production_ready": _bool_to_int(item.is_production_ready),
            "model_category": item.model_category, "model_group": item.model_group,
            "tags": item.tags, "api_parameters": item.api_parameters, "custom_config": item.custom_config,
        }
        async with session:
            async with session.begin():
                await session.execute(text(sql), params)
        return {"code": 0, "message": "创建成功"}
    except Exception as e:
        app_logger.error(f"新增大模型失败: {str(e)}\n{traceback.format_exc()}")
        return {"code": -1, "message": f"创建失败: {str(e)}"}


@router.put("/api/llm-models/{model_id}", summary="更新大模型")
async def update_llm_model(model_id: str, item: LlmModelItem):
    try:
        session = await _get_session()
        sql = """
            UPDATE zb_llm_models SET
                model_name = :model_name, description = :description, provider = :provider,
                api_model_name = :api_model_name, base_url = :base_url, api_key = :api_key,
                context_length = :context_length, supports_streaming = :supports_streaming,
                supports_function_calling = :supports_function_calling, supports_vision = :supports_vision,
                supports_search = :supports_search, supports_json_mode = :supports_json_mode,
                input_price = :input_price, output_price = :output_price, currency = :currency,
                is_enabled = :is_enabled, is_production_ready = :is_production_ready,
                model_category = :model_category, model_group = :model_group,
                tags = :tags, api_parameters = :api_parameters, custom_config = :custom_config,
                version = version + 1
            WHERE model_id = :model_id
        """
        params = {
            "model_name": item.model_name, "description": item.description, "provider": item.provider,
            "api_model_name": item.api_model_name, "base_url": item.base_url, "api_key": item.api_key,
            "context_length": item.context_length,
            "supports_streaming": _bool_to_int(item.supports_streaming, 1),
            "supports_function_calling": _bool_to_int(item.supports_function_calling),
            "supports_vision": _bool_to_int(item.supports_vision),
            "supports_search": _bool_to_int(item.supports_search),
            "supports_json_mode": _bool_to_int(item.supports_json_mode),
            "input_price": item.input_price, "output_price": item.output_price, "currency": item.currency,
            "is_enabled": _bool_to_int(item.is_enabled, 1),
            "is_production_ready": _bool_to_int(item.is_production_ready),
            "model_category": item.model_category, "model_group": item.model_group,
            "tags": item.tags, "api_parameters": item.api_parameters, "custom_config": item.custom_config,
            "model_id": model_id,
        }
        async with session:
            async with session.begin():
                result = await session.execute(text(sql), params)
        if result.rowcount == 0:
            return {"code": -1, "message": "模型不存在"}
        return {"code": 0, "message": "更新成功"}
    except Exception as e:
        app_logger.error(f"更新大模型失败: {str(e)}\n{traceback.format_exc()}")
        return {"code": -1, "message": f"更新失败: {str(e)}"}


@router.delete("/api/llm-models/{model_id}", summary="删除大模型")
async def delete_llm_model(model_id: str):
    try:
        session = await _get_session()
        async with session:
            async with session.begin():
                result = await session.execute(
                    text("DELETE FROM zb_llm_models WHERE model_id = :model_id"),
                    {"model_id": model_id}
                )
        if result.rowcount == 0:
            return {"code": -1, "message": "模型不存在"}
        return {"code": 0, "message": "删除成功"}
    except Exception as e:
        app_logger.error(f"删除大模型失败: {str(e)}\n{traceback.format_exc()}")
        return {"code": -1, "message": f"删除失败: {str(e)}"}


# ============================================================
# 四、会话节点配置管理（zb_conversation_nodes + zb_node_prompt_ver_ctrl）
# ============================================================
@router.get("/api/node-configs", summary="查询会话节点配置列表（分页，含子提示词）")
async def list_node_configs(
    node_id: Optional[str] = Query(None, description="按节点ID模糊匹配"),
    node_name: Optional[str] = Query(None, description="按节点名称模糊匹配"),
    prompt_key: Optional[str] = Query(None, description="按提示词Key模糊匹配"),
    status: Optional[int] = Query(None, description="0=暂存,1=发布"),
    keyword: Optional[str] = Query(None, description="模糊匹配 node_id / node_name"),
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(10, ge=1, le=1000, description="每页条数"),
):
    """
    主行：会话节点信息（ zb_conversation_nodes ）
    子行：该节点关联的提示词版本记录（ zb_node_prompt_ver_ctrl ）
    支持按节点ID、节点名称、提示词Key、状态组合过滤
    """
    try:
        session = await _get_session()

        # 节点级过滤条件（节点列表以 zb_node_prompt_ver_ctrl 为数据源）
        node_where = ["1=1"]
        fparams = {}
        if node_id:
            node_where.append("v.node_id LIKE :node_id")
            fparams["node_id"] = f"%{node_id}%"
        if node_name:
            node_where.append("cn.node_name LIKE :node_name")
            fparams["node_name"] = f"%{node_name}%"
        if keyword:
            node_where.append("(v.node_id LIKE :kw OR cn.node_name LIKE :kw)")
            fparams["kw"] = f"%{keyword}%"
        node_filter_sql = " AND ".join(node_where)

        # 子行级过滤条件
        child_filters = []
        child_params = {}
        if prompt_key:
            child_filters.append("prompt_key LIKE :prompt_key")
            child_params["prompt_key"] = f"%{prompt_key}%"
        if status is not None:
            child_filters.append("status = :status")
            child_params["status"] = status

        async with session:
            async with session.begin():
                offset = (page - 1) * page_size

                # 统一从 zb_node_prompt_ver_ctrl 取节点列表，LEFT JOIN zb_conversation_nodes 取节点元信息
                child_filter_sql = (" AND " + " AND ".join(child_filters)) if child_filters else ""
                all_params = {**fparams, **child_params}

                count_sql = f"""
                    SELECT COUNT(DISTINCT v.node_id) AS cnt
                    FROM zb_node_prompt_ver_ctrl v
                    LEFT JOIN zb_conversation_nodes cn ON cn.node_id = v.node_id
                    WHERE {node_filter_sql} {child_filter_sql}
                """
                count_row = (await session.execute(text(count_sql), all_params)).fetchone()
                total = int(count_row[0]) if count_row else 0

                node_id_list_sql = f"""
                    SELECT DISTINCT v.node_id
                    FROM zb_node_prompt_ver_ctrl v
                    LEFT JOIN zb_conversation_nodes cn ON cn.node_id = v.node_id
                    WHERE {node_filter_sql} {child_filter_sql}
                    ORDER BY v.node_id
                    LIMIT {page_size} OFFSET {offset}
                """
                nids = [r[0] for r in (await session.execute(text(node_id_list_sql), all_params)).fetchall()]

                if not nids:
                    return {
                        "code": 0, "message": "success",
                        "data": [], "total": 0,
                        "page": page, "page_size": page_size,
                    }

                # 查询节点元信息（先 DISTINCT 取 node_id，再 LEFT JOIN 拿元信息）
                nid_placeholders = ",".join([f":nid{i}" for i in range(len(nids))])
                nid_params = {f"nid{i}": nid for i, nid in enumerate(nids)}
                node_rows = [dict(r._mapping) for r in (await session.execute(
                    text(f"""
                        SELECT cn.id, nd.node_id,
                               COALESCE(cn.node_name, nd.node_name) AS node_name,
                               cn.node_type, cn.node_business_range,
                               cn.node_description, cn.status, cn.parent_node_id,
                               cn.model_id, cn.created_at, cn.updated_at
                        FROM (
                            SELECT DISTINCT node_id, node_name
                            FROM zb_node_prompt_ver_ctrl
                            WHERE node_id IN ({nid_placeholders})
                        ) nd
                        LEFT JOIN zb_conversation_nodes cn ON cn.node_id = nd.node_id
                        ORDER BY nd.node_id DESC
                    """),
                    nid_params
                )).fetchall()]

                # 查询这些节点下的子提示词
                child_qparams = {f"nid{i}": nid for i, nid in enumerate(nids)}
                child_where = [f"node_id IN ({nid_placeholders})"]
                if prompt_key:
                    child_where.append("prompt_key LIKE :prompt_key")
                    child_qparams["prompt_key"] = f"%{prompt_key}%"
                if status is not None:
                    child_where.append("status = :status")
                    child_qparams["status"] = status

                child_rows = (await session.execute(
                    text(f"""
                        SELECT id, node_id, node_name, prompt_key, prompt_content,
                               model_id, model_ext_param,
                               status, prompt_content_before_modify, version_no, update_by,
                               created_at, updated_at
                        FROM zb_node_prompt_ver_ctrl
                        WHERE {' AND '.join(child_where)}
                        ORDER BY id DESC
                    """),
                    child_qparams
                )).fetchall()

                children_by_node = {}
                for r in child_rows:
                    d = dict(r._mapping)
                    nid = d["node_id"]
                    children_by_node.setdefault(nid, []).append(d)

                result = []
                for nr in node_rows:
                    nid = nr["node_id"]
                    prompts = children_by_node.get(nid, [])
                    result.append({
                        **nr,
                        "_children": prompts,
                        "_child_count": len(prompts),
                    })

                return {
                    "code": 0, "message": "success",
                    "data": result, "total": total,
                    "page": page, "page_size": page_size,
                }
    except Exception as e:
        app_logger.error(f"查询节点配置失败: {str(e)}\n{traceback.format_exc()}")
        return {"code": -1, "message": f"查询失败: {str(e)}", "data": [], "total": 0, "page": page, "page_size": page_size}


# ============================================================
# 五、节点提示词版本管理（zb_node_prompt_ver_ctrl + zb_node_prompt）
# ============================================================
class PromptVerItem(BaseModel):
    """提示词版本新增/编辑请求体"""
    node_id: str
    node_name: str = ""
    prompt_key: str
    prompt_content: str = ""
    model_id: Optional[str] = None
    model_ext_param: Optional[str] = None
    update_by: str = "system"


@router.get("/api/node-prompts/{record_id}", summary="查询单条提示词版本记录")
async def get_node_prompt(record_id: int):
    try:
        session = await _get_session()
        async with session:
            async with session.begin():
                row = (await session.execute(
                    text("""
                        SELECT id, node_id, node_name, prompt_key, prompt_content,
                               model_id, model_ext_param,
                               status, prompt_content_before_modify, version_no,
                               parent_id, update_by, created_at, updated_at
                        FROM zb_node_prompt_ver_ctrl WHERE id = :rid LIMIT 1
                    """), {"rid": record_id}
                )).fetchone()
        if not row:
            return {"code": -1, "message": "记录不存在", "data": None}
        return {"code": 0, "message": "success", "data": dict(row._mapping)}
    except Exception as e:
        app_logger.error(f"查询提示词版本失败: {str(e)}\n{traceback.format_exc()}")
        return {"code": -1, "message": f"查询失败: {str(e)}", "data": None}


@router.post("/api/node-prompts", summary="新增提示词（暂存，version_no=组内最大+1）")
async def create_node_prompt(item: PromptVerItem):
    """
    业务规则：新增提示词
    - 状态设为 0-暂存，parent_id=NULL
    - version_no 取该 (node_id, prompt_key) 组内最大版本号 + 1（全新 prompt 即为 1，避免重复插入 version_no=1）
    - 不操作 zb_node_prompt 生效表
    """
    try:
        session = await _get_session()
        async with session:
            async with session.begin():
                max_row = (await session.execute(
                    text("SELECT COALESCE(MAX(version_no), 0) FROM zb_node_prompt_ver_ctrl "
                         "WHERE node_id = :nid AND prompt_key = :pkey"),
                    {"nid": item.node_id, "pkey": item.prompt_key}
                )).fetchone()
                new_version = int(max_row[0] or 0) + 1
                sql = """
                    INSERT INTO zb_node_prompt_ver_ctrl
                        (node_id, node_name, prompt_key, prompt_content, model_id, model_ext_param, status,
                         prompt_content_before_modify, version_no, parent_id, update_by)
                    VALUES
                        (:node_id, :node_name, :prompt_key, :prompt_content, :model_id, :model_ext_param, 0,
                         NULL, :version_no, NULL, :update_by)
                """
                params = {
                    "node_id": item.node_id, "node_name": item.node_name or item.node_id,
                    "prompt_key": item.prompt_key, "prompt_content": item.prompt_content,
                    "model_id": item.model_id or None, "model_ext_param": item.model_ext_param or None,
                    "version_no": new_version,
                    "update_by": item.update_by,
                }
                await session.execute(text(sql), params)
        return {"code": 0, "message": "新增成功"}
    except Exception as e:
        app_logger.error(f"新增提示词失败: {str(e)}\n{traceback.format_exc()}")
        return {"code": -1, "message": f"新增失败: {str(e)}"}


@router.put("/api/node-prompts/{record_id}/save-draft", summary="保存草稿")
async def save_draft(record_id: int, item: PromptVerItem):
    """
    暂存逻辑：
    1) 编辑已发布记录 -> 新增一条暂存版本（status=0, version_no+1, parent_id=当前ID）
    2) 编辑暂存记录 -> 原地更新当前暂存记录内容（不新增版本）
    """
    try:
        session = await _get_session()
        async with session:
            async with session.begin():
                cur_row = (await session.execute(
                    text("SELECT id, status, prompt_content, version_no FROM zb_node_prompt_ver_ctrl WHERE id = :rid LIMIT 1"),
                    {"rid": record_id}
                )).fetchone()

                if not cur_row:
                    return {"code": -1, "message": "记录不存在"}

                cur_status = int(cur_row[1] if cur_row[1] is not None else 0)
                cur_content = cur_row[2] or ""

                if cur_status == 1:
                    # 编辑已发布记录 -> 新增暂存版本
                    # 版本号取该 (node_id, prompt_key) 组的最大版本号 + 1，避免与已有草稿版本号冲突
                    max_row = (await session.execute(
                        text("SELECT COALESCE(MAX(version_no), 0) FROM zb_node_prompt_ver_ctrl "
                             "WHERE node_id = :nid AND prompt_key = :pkey"),
                        {"nid": item.node_id, "pkey": item.prompt_key}
                    )).fetchone()
                    new_version = int(max_row[0] or 0) + 1
                    new_content = item.prompt_content or ""
                    ins_sql = """
                        INSERT INTO zb_node_prompt_ver_ctrl
                            (node_id, node_name, prompt_key, prompt_content, model_id, model_ext_param, status,
                             prompt_content_before_modify, version_no, parent_id, update_by)
                        VALUES
                            (:node_id, :node_name, :prompt_key, :prompt_content, :model_id, :model_ext_param, 0,
                             :before_modify, :version_no, :parent_id, :update_by)
                    """
                    ins_params = {
                        "node_id": item.node_id, "node_name": item.node_name or item.node_id,
                        "prompt_key": item.prompt_key, "prompt_content": new_content,
                        "model_id": item.model_id or None, "model_ext_param": item.model_ext_param or None,
                        "before_modify": cur_content,
                        "version_no": new_version,
                        "parent_id": record_id,
                        "update_by": item.update_by,
                    }
                    await session.execute(text(ins_sql), ins_params)
                else:
                    # 编辑暂存记录 -> 原地更新
                    # 只要提示词内容发生变化，就记录修改前的内容；否则不动该字段
                    new_content = item.prompt_content
                    content_changed = (new_content or "") != cur_content
                    upd_sql = """
                        UPDATE zb_node_prompt_ver_ctrl SET
                            prompt_content = :prompt_content,
                            model_id = :model_id,
                            model_ext_param = :model_ext_param,
                            node_name = :node_name,
                            update_by = :update_by
                            """ + (", prompt_content_before_modify = :before_modify," if content_changed else ",") + """
                            updated_at = NOW()
                        WHERE id = :rid AND status = 0
                    """
                    upd_params = {
                        "prompt_content": new_content,
                        "model_id": item.model_id, "model_ext_param": item.model_ext_param,
                        "node_name": item.node_name or item.node_id,
                        "update_by": item.update_by,
                        "rid": record_id,
                    }
                    if content_changed:
                        upd_params["before_modify"] = cur_content
                    await session.execute(text(upd_sql), upd_params)

        return {"code": 0, "message": "暂存成功"}
    except Exception as e:
        app_logger.error(f"保存草稿失败: {str(e)}\n{traceback.format_exc()}")
        return {"code": -1, "message": f"暂存失败: {str(e)}"}


@router.put("/api/node-prompts/{record_id}/publish", summary="发布提示词版本")
async def publish_node_prompt(record_id: int, item: PromptVerItem = None):
    """
    发布逻辑（事务内执行）：
    1) 校验：只有暂存状态可发布，发布状态直接拒绝
    2) 更新当前暂存记录 -> status=1，同步最新内容
    3) 同 node_id + prompt_key 下原有发布记录改为 status=0
    4) 同步 upsert 到 zb_node_prompt 生效表
    """
    try:
        session = await _get_session()
        async with session:
            async with session.begin():
                cur_row = (await session.execute(
                    text("""SELECT id, node_id, node_name, prompt_key, prompt_content, status
                           FROM zb_node_prompt_ver_ctrl WHERE id = :rid LIMIT 1"""),
                    {"rid": record_id}
                )).fetchone()

                if not cur_row:
                    return {"code": -1, "message": "记录不存在"}

                cur_data = dict(cur_row._mapping)
                if cur_data["status"] == 1:
                    return {"code": -1, "message": "该记录已是发布状态，无法重复发布。请先编辑并暂存新版本后再发布。"}

                node_id = cur_data["node_id"]
                prompt_key = cur_data["prompt_key"]
                cur_content = cur_data.get("prompt_content") or ""
                new_content = item.prompt_content if item else cur_content
                new_model_id = ((item.model_id if item else cur_data.get("model_id")) or None)
                new_model_ext = ((item.model_ext_param if item else cur_data.get("model_ext_param")) or None)
                update_by = item.update_by if item else "system"
                content_changed = new_content != cur_content

                # (1) 当前暂存记录 -> 更新为发布，内容变化时记录修改前内容
                publish_upd_sql = """
                    UPDATE zb_node_prompt_ver_ctrl SET
                        prompt_content = :content,
                        model_id = :model_id,
                        model_ext_param = :model_ext_param,
                        status = 1,
                        update_by = :update_by""" + (", prompt_content_before_modify = :before_modify" if content_changed else "") + """,
                        updated_at = NOW()
                    WHERE id = :rid
                """
                publish_upd_params = {
                    "content": new_content, "model_id": new_model_id,
                    "model_ext_param": new_model_ext, "update_by": update_by,
                    "rid": record_id,
                }
                if content_changed:
                    publish_upd_params["before_modify"] = cur_content
                await session.execute(text(publish_upd_sql), publish_upd_params)

                # (2) 同 node_id+prompt_key 下其它发布记录 -> 改为暂存
                await session.execute(text("""
                    UPDATE zb_node_prompt_ver_ctrl SET
                        status = 0,
                        updated_at = NOW()
                    WHERE node_id = :nid AND prompt_key = :pkey
                      AND status = 1 AND id != :rid
                """), {"nid": node_id, "pkey": prompt_key, "rid": record_id})

                # (3) 同步 upsert zb_node_prompt 生效表
                await session.execute(text("""
                    INSERT INTO zb_node_prompt (node_id, prompt_key, prompt_content, model_id, model_ext_param, created_at, updated_at)
                    VALUES (:nid, :pkey, :content, :model_id, :model_ext_param, NOW(), NOW())
                    ON DUPLICATE KEY UPDATE
                        prompt_content = :content,
                        model_id = :model_id,
                        model_ext_param = :model_ext_param,
                        updated_at = NOW()
                """), {"nid": node_id, "pkey": prompt_key, "content": new_content,
                       "model_id": new_model_id, "model_ext_param": new_model_ext})

        # 发布后触发缓存刷新
        try:
            from ..db_connection_pool.zb_node_prompt_util import _default_cache
            await _default_cache.force_refresh()
        except Exception:
            pass

        return {"code": 0, "message": "发布成功"}
    except Exception as e:
        app_logger.error(f"发布提示词失败: {str(e)}\n{traceback.format_exc()}")
        return {"code": -1, "message": f"发布失败: {str(e)}"}
