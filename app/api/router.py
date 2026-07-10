from fastapi import APIRouter

from . import frame_api, health, chat_api, manage_api

api_router = APIRouter()

# 业务接口：/frame/run/sse
api_router.include_router(frame_api.router, tags=["frame"])
# 健康检查：/health, /health/detail, /health/config
api_router.include_router(health.router, tags=["health"])
# 对话 API：会话列表、历史消息
api_router.include_router(chat_api.router, tags=["chat"])
# 管理 API：节点配置、提示词配置
api_router.include_router(manage_api.router, tags=["manage"])
