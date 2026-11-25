"""程序说明：长会话历史滑窗与大参数折叠压缩模块（A9），在不破坏 tool_call_id 配对与媒体引用的前提下降低多轮 Token 开销。"""
from __future__ import annotations

import copy
import json
import re
from typing import Any, Dict, List

DEFAULT_KEEP_RECENT_MESSAGES = 14
DEFAULT_MAX_OLD_ARG_CHARS = 240
DEFAULT_MAX_OLD_TEXT_CHARS = 500
_PROMPT_LIKE_KEYS = frozenset(
    {
        "prompt",
        "positive_prompt",
        "negative_prompt",
        "task_prompt",
        "edit_instruction",
        "description",
    }
)
_MEDIA_TAG_RE = re.compile(r"!\[[^\]]*\]\(/api/file/[^)]+\)")


def _compact_tool_arguments(tool_name: str, raw_args: Any, max_chars: int) -> str:
    """对历史远期工具调用参数中的长提示词与计划详情做保结构截断，完整保留文件名与枚举参数。"""
    if isinstance(raw_args, dict):
        parsed = copy.deepcopy(raw_args)
    elif isinstance(raw_args, str):
        if len(raw_args) <= max_chars:
            return raw_args
        try:
            parsed = json.loads(raw_args)
        except Exception:
            return raw_args[:max_chars] + "…"
    else:
        return "{}"

    if not isinstance(parsed, dict):
        return json.dumps(parsed, ensure_ascii=False)[:max_chars]

    if tool_name == "write_plan" and isinstance(parsed.get("steps"), list):
        parsed["steps"] = [
            {"title": str(s.get("title") or "")[:80]}
            for s in parsed["steps"]
            if isinstance(s, dict)
        ]
        return json.dumps(parsed, ensure_ascii=False)

    for key, val in list(parsed.items()):
        if isinstance(val, str) and (key in _PROMPT_LIKE_KEYS or len(val) > max_chars):
            if len(val) > max_chars:
                parsed[key] = val[:max_chars] + "…"
    return json.dumps(parsed, ensure_ascii=False)


def _compact_old_text(content: str, max_chars: int) -> str:
    """截断早期超长助手回复正文，同时确保文中的 /api/file/ 媒体标签不丢失。"""
    if len(content) <= max_chars:
        return content
    preserved_tags = _MEDIA_TAG_RE.findall(content)
    head = content[:max_chars].rstrip() + "… [早期消息已折叠]"
    missing_tags = [tag for tag in preserved_tags if tag not in head]
    if missing_tags:
        head = head + "\n" + " ".join(missing_tags)
    return head


def compact_chat_history(
    messages: List[Dict[str, Any]],
    *,
    keep_recent_messages: int = DEFAULT_KEEP_RECENT_MESSAGES,
    max_old_arg_chars: int = DEFAULT_MAX_OLD_ARG_CHARS,
    max_old_text_chars: int = DEFAULT_MAX_OLD_TEXT_CHARS,
) -> List[Dict[str, Any]]:
    """对超过保留窗口的早期对话消息做无损结构折叠，保留最近轮次完整原文与全部 tool_call_id 配对。"""
    if not messages or len(messages) <= max(2, keep_recent_messages):
        return list(messages)

    cutoff = len(messages) - keep_recent_messages
    compacted: List[Dict[str, Any]] = []

    for idx, msg in enumerate(messages):
        if idx >= cutoff or not isinstance(msg, dict):
            compacted.append(msg)
            continue

        msg_copy = copy.deepcopy(msg)
        role = msg_copy.get("role")
        content = msg_copy.get("content")

        if role == "assistant":
            if isinstance(content, str) and len(content) > max_old_text_chars:
                msg_copy["content"] = _compact_old_text(content, max_old_text_chars)
            if isinstance(msg_copy.get("tool_calls"), list):
                for tc in msg_copy["tool_calls"]:
                    if not isinstance(tc, dict):
                        continue
                    fn = tc.get("function")
                    if isinstance(fn, dict):
                        fn["arguments"] = _compact_tool_arguments(
                            str(fn.get("name") or ""),
                            fn.get("arguments"),
                            max_old_arg_chars,
                        )
                    elif "args" in tc:
                        shrunk = _compact_tool_arguments(
                            str(tc.get("name") or ""), tc.get("args"), max_old_arg_chars
                        )
                        try:
                            tc["args"] = json.loads(shrunk)
                        except Exception:
                            pass

        compacted.append(msg_copy)

    return compacted
