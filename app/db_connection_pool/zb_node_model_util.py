"""
节点模型数据库操作工具类
用于加载和查询 zb_llm_models 表数据
"""
import json
import traceback
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple
from sqlalchemy import text
from langchain_openai import ChatOpenAI
from .async_mysql_connection import get_async_pool_instance, AsyncMySQLConnection
from ..core.logger import app_logger
from ..core.config import settings


@dataclass
class ZbNodeModel:
    """节点模型数据类"""
    id: int
    model_id: str
    model_provider: str
    model_name: str
    model_url: str
    model_api_key: Optional[str] = None
    model_is_out: int = 0
    status: int = 1
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @classmethod
    def from_dict(cls, data: Dict) -> 'ZbNodeModel':
        """从字典创建实例"""
        return cls(
            id=data.get('id', 0),
            model_id=data.get('model_id', ''),
            model_provider=data.get('model_provider', ''),
            model_name=data.get('model_name', ''),
            model_url=data.get('model_url', ''),
            model_api_key=data.get('model_api_key'),
            model_is_out=data.get('model_is_out', 0),
            status=data.get('status', 1),
            created_at=data.get('created_at'),
            updated_at=data.get('updated_at')
        )


class ZbNodeModelUtil:
    """节点模型数据库操作助手"""

    # LLM 实例内存缓存：key=cache_key, value=(ChatOpenAI, created_at)
    # TTL 与节点缓存保持一致，到期后自动重建以获取最新模型配置
    _llm_cache: Dict[str, Tuple[ChatOpenAI, datetime]] = {}
    _llm_cache_ttl_seconds: int = 60  # 默认 60s，会被 settings 覆盖

    @staticmethod
    async def load_model_by_id(model_id: str) -> Optional[ZbNodeModel]:
        """
        根据模型ID获取模型配置

        Args:
            model_id: 模型ID

        Returns:
            ZbNodeModel 对象，如果未找到则返回 None
        """
        try:
            db_conn = await get_async_pool_instance()
            session = await db_conn.get_session()

            async with session:
                async with session.begin():
                    query = """
                        SELECT 
                            id,
                            model_id,
                            provider AS model_provider,
                            api_model_name AS model_name,
                            base_url AS model_url,
                            api_key AS model_api_key,
                            (provider != 'zbank') AS model_is_out,
                            is_enabled AS status,
                            created_at,
                            updated_at
                        FROM zb_llm_models
                        WHERE model_id = :model_id AND is_enabled = 1
                        LIMIT 1
                    """
                    result = AsyncMySQLConnection.all(
                        await session.execute(text(query), {"model_id": model_id})
                    )

                    if result and len(result) > 0:
                        model = ZbNodeModel.from_dict(result[0])
                        app_logger.info(f"成功加载模型: model_id={model_id}")
                        return model

            return None

        except Exception as e:
            app_logger.error(f"加载模型配置失败: {str(e)}\n{traceback.format_exc()}")
            return None

    @staticmethod
    async def load_all_models() -> list[ZbNodeModel]:
        """
        加载所有启用的模型配置

        Returns:
            List[ZbNodeModel]: 所有模型配置列表
        """
        try:
            db_conn = await get_async_pool_instance()
            session = await db_conn.get_session()

            async with session:
                async with session.begin():
                    query = """
                        SELECT 
                            id,
                            model_id,
                            provider AS model_provider,
                            api_model_name AS model_name,
                            base_url AS model_url,
                            api_key AS model_api_key,
                            (provider != 'zbank') AS model_is_out,
                            is_enabled AS status,
                            created_at,
                            updated_at
                        FROM zb_llm_models
                        WHERE is_enabled = 1
                    """
                    result = AsyncMySQLConnection.all(await session.execute(text(query)))

                    models = [ZbNodeModel.from_dict(row) for row in result] if result else []

            app_logger.info(f"成功加载 {len(models)} 个模型配置")
            return models

        except Exception as e:
            app_logger.error(f"加载模型配置失败: {str(e)}\n{traceback.format_exc()}")
            return []

    @staticmethod
    async def build_llm_by_model_id(
        model_id: str,
        extra_params: Optional[Dict[str, Any]] = None
    ) -> Optional[ChatOpenAI]:
        """
        根据 model_id 从 zb_llm_models 查询模型配置并构建 ChatOpenAI 实例。
        用于 prompt 级别的模型覆盖（prompt 指定 model_id 时，可覆盖节点级默认模型）。

        内置内存缓存：同一 model_id + extra_params 组合只会查库构建一次，后续直接从缓存返回。

        Args:
            model_id: 模型唯一标识
            extra_params: 额外的模型参数，会合并到 ChatOpenAI 的创建参数中。
                          其中 'extra_body' 键会被提取传给 extra_body 参数。

        Returns:
            ChatOpenAI 实例，或 None（模型未找到或未启用）
        """
        # 缓存 key = model_id + extra_params 的稳定字符串表示
        cache_key = model_id
        if extra_params:
            # 对 extra_params 做排序后序列化，确保相同参数命中同一缓存
            cache_key = f"{model_id}:{json.dumps(extra_params, sort_keys=True)}"

        # 命中缓存：检查 TTL，未过期直接返回
        if cache_key in ZbNodeModelUtil._llm_cache:
            llm, cached_at = ZbNodeModelUtil._llm_cache[cache_key]
            ttl = getattr(settings, 'AI_INTENT_FLOW_CONVERSATION_CACHE_REFRESH_INTERVAL',
                          ZbNodeModelUtil._llm_cache_ttl_seconds)
            if (datetime.now() - cached_at).total_seconds() < ttl:
                app_logger.debug(f"[prompt model cache] 命中缓存: cache_key={cache_key}")
                return llm
            else:
                # TTL 过期，清除旧缓存
                del ZbNodeModelUtil._llm_cache[cache_key]
                app_logger.info(f"[prompt model cache] 缓存过期，重新构建: cache_key={cache_key}")

        try:
            db_conn = await get_async_pool_instance()
            session = await db_conn.get_session()

            async with session:
                async with session.begin():
                    query = """
                        SELECT 
                            api_model_name AS model_name,
                            base_url AS model_url,
                            api_key AS model_api_key,
                            provider,
                            context_length,
                            supports_function_calling,
                            supports_vision,
                            supports_streaming
                        FROM zb_llm_models
                        WHERE model_id = :model_id AND is_enabled = 1
                        LIMIT 1
                    """
                    result = AsyncMySQLConnection.all(
                        await session.execute(text(query), {"model_id": model_id})
                    )

                    if not result or len(result) == 0:
                        app_logger.warning(f"未找到启用中的模型: model_id={model_id}")
                        return None

                    row = result[0]
                    model_name = row.get('model_name', '')
                    model_url = row.get('model_url', '')
                    model_api_key = row.get('model_api_key', '')

                    if not model_name or not model_url:
                        app_logger.warning(f"模型 {model_id} 缺少必要配置, model_name={model_name}, model_url={model_url}")
                        return None

                    # 构建 ChatOpenAI 参数
                    llm_params = {
                        'model': model_name,
                        'base_url': model_url,
                        'api_key': model_api_key if model_api_key else None,
                    }

                    # 合并额外参数（注意不要修改传入的 dict）
                    if extra_params:
                        extra_params_copy = dict(extra_params)
                        extra_body = extra_params_copy.pop('extra_body', None)
                        if extra_body:
                            llm_params['extra_body'] = extra_body
                        llm_params.update(extra_params_copy)

                    llm = ChatOpenAI(**llm_params)

                    # 存入缓存（含时间戳）
                    ZbNodeModelUtil._llm_cache[cache_key] = (llm, datetime.now())
                    app_logger.info(f"[prompt model override] 成功构建并缓存 LLM: model_id={model_id}, model={model_name}")
                    return llm

        except Exception as e:
            app_logger.error(f"构建 LLM 失败: model_id={model_id}, error={str(e)}\n{traceback.format_exc()}")
            return None