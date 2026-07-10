from dataclasses import dataclass, field
import json
from typing import Any


@dataclass
class InterruptMessage:
    """
    中断消息
    """
    interrupt_bisiness_type: str = ""
    interrupt_message: str = ""
    extra_info: dict[str, Any] = field(default_factory=dict)

    def to_text(self) -> str:
        """将中断消息转换为文本格式，第一行为消息内容，后续为字段描述(字段名称)"""
        return self.interrupt_message

    @staticmethod
    def from_str_or_dict(data: str | dict) -> "InterruptMessage":
        """将字符串或字典转换为InterruptMessage对象，字符串为JSON则解析，否则作为消息内容"""
        if isinstance(data, dict):
            return InterruptMessage.from_dict(data)
        try:
            return InterruptMessage.from_dict(json.loads(data))
        except Exception:
            return InterruptMessage(interrupt_message=data)

    @staticmethod
    def from_dict(data: dict) -> "InterruptMessage":
        """从字典构造InterruptMessage对象"""
        return InterruptMessage(
            interrupt_bisiness_type=data.get("interrupt_bisiness_type", ""),
            interrupt_message=data.get("interrupt_message", ""),
            extra_info=data.get("extra_info", {})
        )

    @staticmethod
    def is_json_str(s: str) -> bool:
        """判断字符串是否为合法的JSON字符串"""
        try:
            json.loads(s)
            return True
        except (json.JSONDecodeError, TypeError):
            return False

    @staticmethod
    def from_json_str(json_str: str) -> "InterruptMessage":
        """从JSON字符串解析为InterruptMessage对象"""
        data = json.loads(json_str)
        return InterruptMessage(
            interrupt_bisiness_type=data.get("interrupt_bisiness_type", ""),
            interrupt_message=data.get("interrupt_message", ""),
            extra_info=data.get("extra_info", {})
        )

    def to_json_str(self) -> str:
        """将InterruptMessage对象转换为JSON字符串"""
        return json.dumps({
            "interrupt_bisiness_type": self.interrupt_bisiness_type,
            "interrupt_message": self.interrupt_message,
            "extra_info": self.extra_info
        }, ensure_ascii=False)
