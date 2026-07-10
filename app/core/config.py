# app/core/config.py
import pathlib

from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


def get_env_file() -> pathlib.Path:
    """
    返回统一的 .env 配置文件路径（单环境配置）

    说明：本项目只维护一份 .env（运行用）与 .env.example（模板），
    不再按 dev/sit/uat/prod 拆分多份环境文件。
    """
    return pathlib.Path(__file__).parent.parent.parent / ".env"


class Settings(BaseSettings):
    """应用配置类 — 仅保留框架实际使用的字段"""

    # ========== 应用基础配置 ==========
    APP_NAME: str = "AI Intent Flow"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False
    ENVIRONMENT: str = "development"

    # ========== 外部接口域名 ==========
    AIGC_WQ_DOMAIN: str = ""

    # ========== 服务器配置 ==========
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # ========== MySQL 异步配置 ==========
    MYSQL_HOST: str = "localhost"
    MYSQL_PORT: int = 3306
    MYSQL_USER: str = "root"
    MYSQL_PASSWORD: str = ""
    MYSQL_DB: str = "info"
    MYSQL_POOL_SIZE: int = 50
    MYSQL_MAX_OVERFLOW: int = 20
    MYSQL_POOL_RECYCLE: int = 3600
    MYSQL_POOL_TIMEOUT: int = 30

    # ========== 日志配置 ==========
    LOG_LEVEL: str = "INFO"
    LOG_DIR: str = "logs"
    LOG_ROTATION: str = "500 MB"
    LOG_RETENTION: str = "30 days"
    LOG_COLORIZE: bool = False
    MY_POD_IP: str = "127.0.0.1"  # Pod IP，用于多 Pod 日志分离

    # ========== 缓存刷新间隔配置 ==========
    AI_INTENT_FLOW_WORKFLOW_CACHE_REFRESH_INTERVAL: int = 60
    AI_INTENT_FLOW_CONVERSATION_CACHE_REFRESH_INTERVAL: int = 60
    AI_INTENT_FLOW_NODE_PROMPT_CACHE_REFRESH_INTERVAL: int = 60

    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",  # 忽略 .env 中未定义的变量
    )


# 全局配置实例
_settings: Optional[Settings] = None


def get_settings(environment: str = None) -> Settings:
    """
    获取配置实例（单例模式）
    每次调用时从 .env 加载配置
    """
    global _settings
    if environment is not None and _settings is not None:
        env_file = get_env_file()
        print(f"[CONFIG] Reloading environment from: {env_file.name}")
        _settings = Settings(_env_file=env_file)
        return _settings
    if _settings is None:
        env_file = get_env_file()
        print(f"[CONFIG] Loading environment from: {env_file.name}")
        _settings = Settings(_env_file=env_file)
    return _settings


def get_current_settings() -> Settings:
    """
    获取当前配置实例
    """
    global _settings
    if _settings is None:
        _settings = get_settings()
    return _settings


class _SettingsProxy:
    """
    配置代理类，动态获取当前配置

    解决问题：避免其他模块在导入时就固定配置对象
    工作原理：每次访问属性时都动态获取最新的配置对象
    """

    def __getattr__(self, name):
        """动态获取配置属性"""
        current_settings = get_current_settings()
        return getattr(current_settings, name)


# 全局配置代理对象
settings = _SettingsProxy()
