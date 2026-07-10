# app/core/logger.py

import sys
from loguru import logger
from pathlib import Path
from .config import settings
from contextvars import ContextVar
import time

# ✅ 上下文变量：线程安全的请求追踪
TRACE_ID_CTX: ContextVar[str] = ContextVar("trace_id", default="N/A")


class LoggerConfig:
    """日志配置类 (异步写入)"""

    @staticmethod
    def init_logger():
        """初始化日志系统"""
        logger.remove()

        # 确保日志目录存在，创建以 MY_POD_IP 命名的子目录
        # 例如：logs/127.0.0.1/ 或 logs/10.244.1.5/
        log_path = Path(settings.LOG_DIR) / settings.MY_POD_IP
        log_path.mkdir(parents=True, exist_ok=True)

        logger.info(f"📝 Log directory: {log_path}")

        # 日志格式 (带颜色标签 - 仅用于支持颜色的终端)
        log_format_with_colors = (
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "<yellow>Trace-ID: {extra[trace_id]}</yellow> | "
            "<level>{message}</level>"
        )

        # 日志格式 (纯文本 - 用于文件和不支持颜色的环境)
        log_format_plain = (
            "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
            "{level: <8} | "
            "{name}:{function}:{line} | "
            "Trace-ID: {extra[trace_id]} | "
            "{message}"
        )

        # 定义 filter 函数，动态从 ContextVar 获取 trace_id
        def trace_id_filter(record):
            trace_id = TRACE_ID_CTX.get("N/A")
            record["extra"]["trace_id"] = trace_id
            return True  # 返回 True 表示记录这条日志

        # 解析日志轮转大小配置（如 "100 MB" -> 字节数）
        def parse_rotation_size(size_str: str) -> int:
            """解析日志大小配置，返回字节数"""
            size_str = size_str.strip().upper()
            units = {
                "KB": 1024,
                "MB": 1024 ** 2,
                "GB": 1024 ** 3,
            }
            for unit, multiplier in units.items():
                if size_str.endswith(unit):
                    value = float(size_str[:-len(unit)])
                    return int(value * multiplier)
            # 默认返回 100MB
            return 100 * 1024 * 1024

        # 从配置获取轮转大小（字节数）
        rotation_size_bytes = parse_rotation_size(settings.LOG_ROTATION)

        # 定义自定义轮转函数：同时支持按大小和日期轮转
        def custom_rotation(message, file):
            """自定义轮转逻辑：检查文件大小和是否需要按日期轮转"""
            import os
            from datetime import datetime

            # 获取文件大小（字节）
            try:
                file_size = os.path.getsize(file.name)
                # 超过配置的大小时轮转
                if file_size > rotation_size_bytes:
                    return True
            except FileNotFoundError:
                pass

            # 检查是否需要按日期轮转（文件名中包含旧日期）
            file_name = os.path.basename(file.name)
            current_date = datetime.now().strftime("%Y-%m-%d")
            # 如果文件名中的日期不是今天，需要轮转
            if f"app_{current_date}.log" not in file_name:
                # 检查文件名是否已包含日期
                if "_" in file_name and file_name != "app.log":
                    # 提取文件名中的日期部分
                    try:
                        file_date = file_name.split("_")[1].split(".")[0]
                        if file_date != current_date:
                            return True
                    except (IndexError, ValueError):
                        pass

            return False

        # 根据配置选择日志格式
        use_color = settings.LOG_COLORIZE
        console_format = log_format_with_colors if use_color else log_format_plain

        # ✅ 控制台输出 (enqueue=True 异步写入)
        logger.add(
            sys.stdout,
            format=console_format,
            level=settings.LOG_LEVEL,
            colorize=use_color,  # 根据配置决定是否启用颜色
            enqueue=True,  # ✅ 异步写入，避免阻塞事件循环
            filter=trace_id_filter,  # 使用 filter 动态注入 trace_id
        )

        # ✅ 文件输出 (enqueue=True 异步写入，所有日志合并到一个文件，纯文本格式)
        logger.add(
            log_path / "app_{time:YYYY-MM-DD}.log",
            format=log_format_plain,  # 文件始终使用纯文本格式
            level="DEBUG",  # 记录所有级别的日志
            rotation=custom_rotation,  # 自定义轮转：同时支持大小和日期
            retention=settings.LOG_RETENTION,  # 使用配置的保留时间
            compression="gz",  # ✅ 旧日志自动压缩为 .gz 格式
            encoding="utf-8",
            enqueue=True,  # ✅ 异步写入
            colorize=False,  # 文件始终禁用颜色，确保不包含 ANSI 代码
            delay=True,  # ✅ 延迟创建文件，避免文件锁定问题
            backtrace=True,
            diagnose=True,
            filter=trace_id_filter,  # 使用 filter 动态注入 trace_id
        )

        return logger


def get_trace_id() -> str:
    """获取当前请求的日志流水号"""
    return TRACE_ID_CTX.get()


def set_trace_id(trace_id: str):
    """设置当前请求的日志流水号"""
    TRACE_ID_CTX.set(trace_id)


def generate_trace_id() -> str:
    """生成唯一的日志流水号"""
    return f"{int(time.time() * 1000)}-{id(object())}"


# 导出 logger 实例
app_logger = LoggerConfig.init_logger()