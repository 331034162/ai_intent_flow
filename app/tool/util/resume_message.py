from dataclasses import dataclass, field
from typing import Any
import json


@dataclass
class ResumeMessage:
    resume_business_type:str = ""
    resume_message: str = ""
    extra_info: dict[str, Any] = field(default_factory=dict)

    def to_text(self) -> str:
        """将恢复消息转换为文本格式"""
        return self.resume_message

    @staticmethod
    def from_str_or_dict(data: str | dict[str, Any]) -> "ResumeMessage":
        """将字符串或字典转换为ResumeMessage对象，字符串为JSON则解析，否则作为文本内容"""
        if isinstance(data, dict):
            return ResumeMessage.from_dict(data)
        try:
            return ResumeMessage.from_dict(json.loads(data))
        except Exception:
            return ResumeMessage(resume_message=data)

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "ResumeMessage":
        """从字典构造ResumeMessage对象"""
        return ResumeMessage(
            resume_business_type=data.get("resume_business_type", ""),
            resume_message=data.get("resume_message", ""),
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

    def to_json_str(self) -> str:
        """将ResumeMessage对象转换为JSON字符串"""
        return json.dumps({
            "resume_business_type": self.resume_business_type,
            "resume_message": self.resume_message,
            "extra_info": self.extra_info
        }, ensure_ascii=False)

    @staticmethod
    def from_json_str(json_str: str) -> "ResumeMessage":
        """从JSON字符串解析为ResumeMessage对象"""
        data = json.loads(json_str)
        return ResumeMessage(
            resume_business_type=data.get("resume_business_type", ""),
            resume_message=data.get("resume_message", ""),
            extra_info=data.get("extra_info", {})
        )
