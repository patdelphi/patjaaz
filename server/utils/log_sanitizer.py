"""程序说明：提供统一的敏感信息脱敏与安全日志辅助函数，自动擦除 Bearer/Basic/API Key 等凭据。"""
from __future__ import annotations

import logging
import re
from typing import Iterable, Optional

_SECRET_PATTERNS = (
    (re.compile(r"(Bearer\s+)[A-Za-z0-9._\-+/=]{6,}", re.IGNORECASE), r"\1***"),
    (re.compile(r"(Basic\s+)[A-Za-z0-9+/=]{6,}", re.IGNORECASE), r"\1***"),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}\b"), "sk-***"),
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{12,}\b"), "AIza***"),
    (
        re.compile(
            r'(["\']?(?:api_key|x-api-key|x-goog-api-key|auth_secret|authorization)["\']?\s*[:=]\s*["\']?)([^"\',\s}{]{6,})',
            re.IGNORECASE,
        ),
        r"\1***",
    ),
)


def redact_secrets(
    text: object, extra_secrets: Optional[Iterable[Optional[str]]] = None
) -> str:
    """擦除字符串中的常见密钥格式及调用方显式传入的敏感值。"""
    cleaned = str(text if text is not None else "")
    if not cleaned:
        return cleaned
    if extra_secrets:
        for item in extra_secrets:
            if item and len(item) >= 4:
                cleaned = cleaned.replace(item, "***")
    for pattern, repl in _SECRET_PATTERNS:
        cleaned = pattern.sub(repl, cleaned)
    return cleaned


class _RedactingFilter(logging.Filter):
    """标准 logging 过滤器：对消息文本与格式化后的异常信息自动脱敏。"""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
            record.msg = redact_secrets(msg)
            record.args = ()
        except Exception:
            pass
        return True


def get_sanitized_logger(name: str) -> logging.Logger:
    """获取挂载了凭据脱敏过滤器的标准 Logger。"""
    logger = logging.getLogger(name)
    if not any(isinstance(f, _RedactingFilter) for f in logger.filters):
        logger.addFilter(_RedactingFilter())
    return logger
