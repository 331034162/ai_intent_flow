# app/api/health.py
"""
健康检查接口

提供三个层级的健康检查：
- /health        基础信息（不含外部依赖检查）
- /health/detail 详细检查（含 MySQL 连接检测）
- /health/config 当前配置查看
"""
from datetime import datetime

from fastapi import APIRouter
from sqlalchemy import text

from ..core.config import settings, get_current_settings
from ..core.logger import app_logger as logger
from ..db_connection_pool.async_mysql_connection import get_async_pool_instance

router = APIRouter()


@router.get("/health")
async def health_basic():
    """基础健康检查 — 仅返回服务自身信息，不检查外部依赖"""
    return {
        "status": "healthy",
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT,
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/health/detail")
async def health_detail():
    """
    详细健康检查 — 逐组件检查 MySQL 连接状态
    """
    health_status = {
        "status": "healthy",
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT,
        "timestamp": datetime.utcnow().isoformat(),
        "components": {},
    }

    # 检查 MySQL
    try:
        pool = await get_async_pool_instance()
        async with pool.get_session() as session:
            await session.execute(text("SELECT 1"))
            health_status["components"]["mysql"] = {
                "status": "healthy",
                "host": settings.MYSQL_HOST,
                "port": settings.MYSQL_PORT,
                "database": settings.MYSQL_DB,
                "message": "MySQL connection OK",
            }
    except Exception as e:
        health_status["status"] = "unhealthy"
        health_status["components"]["mysql"] = {
            "status": "unhealthy",
            "host": settings.MYSQL_HOST,
            "port": settings.MYSQL_PORT,
            "database": settings.MYSQL_DB,
            "message": f"MySQL connection failed: {str(e)}",
        }

    return health_status


@router.get("/health/config")
async def health_config():
    """查看当前框架的全部配置项"""
    try:
        current_settings = get_current_settings()
        config_dict = {}

        for attr_name in dir(current_settings):
            if attr_name.startswith("_"):
                continue
            if attr_name in ("model_fields", "model_fields_set", "model_config", "model_dump_json"):
                continue
            attr_value = getattr(current_settings, attr_name, None)
            if callable(attr_value):
                continue
            if attr_value is not None and "FieldInfo" in type(attr_value).__name__:
                continue
            if isinstance(attr_value, (str, int, float, bool, list, dict, type(None))):
                config_dict[attr_name] = attr_value
            else:
                try:
                    config_dict[attr_name] = str(attr_value)
                except Exception:
                    pass

        return {
            "status": "success",
            "message": "配置查询成功",
            "config": config_dict,
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        logger.error(f"查询配置失败: {e}", exc_info=True)
        return {
            "status": "error",
            "message": f"查询配置失败: {str(e)}",
            "config": {},
            "timestamp": datetime.utcnow().isoformat(),
        }
