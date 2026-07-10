# app/main.py
"""
AI Intent Flow 主应用入口

FastAPI 应用创建与启动（由 uvicorn 托管）
对外接口：POST /frame/run/sse  （见 app/api/frame_api.py）
"""
import argparse
import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.core.config import settings, get_settings
from app.core.logger import app_logger as logger

# 静态文件目录绝对路径
_STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动预热，关闭释放"""
    logger.info("=" * 60)
    logger.info(f"🚀 {settings.APP_NAME} v{settings.APP_VERSION} starting...")
    logger.info(f"   Environment: {settings.ENVIRONMENT}")
    logger.info("=" * 60)

    # 预热 MySQL 连接池（懒加载单例，首次取用即初始化；失败不阻断启动）
    try:
        from app.db_connection_pool.async_mysql_connection import get_async_pool_instance
        await get_async_pool_instance()
        logger.info("✅ MySQL connection pool ready")
    except Exception as e:
        logger.warning(f"⚠️ MySQL pool warm-up skipped: {e}")

    logger.info(f"✅ {settings.APP_NAME} started. API docs: /docs")
    yield

    logger.info(f"⏹️  {settings.APP_NAME} shutting down...")
    # 连接池为懒加载单例，随进程退出自动释放，无需显式关闭


def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用"""
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description="AI Intent Flow Framework - LangGraph based agent workflow framework",
        lifespan=lifespan,
        docs_url="/docs" if settings.DEBUG else None,
        redoc_url="/redoc" if settings.DEBUG else None,
    )

    app.include_router(api_router)

    # 根路径 → index.html 主框架页
    @app.get("/", include_in_schema=False)
    async def index_page():
        return FileResponse(os.path.join(_STATIC_DIR, "index.html"))

    # 对话测试页（旧版，保留兼容）
    @app.get("/chat", include_in_schema=False)
    async def chat_test_page():
        return FileResponse(os.path.join(_STATIC_DIR, "chat.html"))

    # 挂载静态文件目录（放在最后，避免覆盖自定义路由）
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

    # 全局异常兜底
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error(f"Unhandled exception: {exc}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "code": -1,
                "message": "Internal server error",
                "detail": str(exc) if settings.DEBUG else "An error occurred",
            },
        )

    return app


# 模块加载即创建应用实例（uvicorn 通过 "app.main:app" 引用）
app = create_app()


def parse_arguments():
    parser = argparse.ArgumentParser(description="AI Intent Flow Service")
    parser.add_argument("--host", default=None, help="服务器地址，默认使用配置")
    parser.add_argument("--port", type=int, default=None, help="服务器端口，默认使用配置")
    parser.add_argument("--reload", action="store_true", default=None, help="是否启用热重载")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_arguments()
    current_settings = get_settings()

    host = args.host or current_settings.HOST
    port = args.port or current_settings.PORT
    reload = args.reload if args.reload is not None else current_settings.DEBUG

    print(f"\n{'=' * 60}")
    print(f"🚀 Starting {current_settings.APP_NAME} v{current_settings.APP_VERSION}")
    print(f"🌐 Server: http://{host}:{port}")
    print(f"📚 API Docs: http://{host}:{port}/docs")
    print(f"{'=' * 60}\n")

    uvicorn.run("app.main:app", host=host, port=port, reload=reload, log_level="info")
