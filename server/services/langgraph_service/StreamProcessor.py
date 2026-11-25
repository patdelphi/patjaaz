"""程序说明：流式处理器，负责将 LangGraph Swarm 事件流转发至前端，并在工具完成时即时幂等持久化消息防丢失。"""
# type: ignore[import]
import json
from utils.log_sanitizer import get_sanitized_logger
_logger = get_sanitized_logger(__name__)
import traceback
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set
from langchain_core.messages import (
    AIMessageChunk,
    ToolCall,
    ToolMessage,
    convert_to_openai_messages,
)
from langgraph.graph import StateGraph


class StreamProcessor:
    """流式处理器 - 负责处理智能体的流式输出与中间工具结果即时落库"""

    def __init__(
        self,
        session_id: str,
        db_service: Any,
        websocket_service: Callable[[str, Dict[str, Any]], Awaitable[None]],
    ):
        self.session_id = session_id
        self.db_service = db_service
        self.websocket_service = websocket_service
        self.tool_calls: List[ToolCall] = []
        self.last_saved_message_index = 0
        self.last_streaming_tool_call_id: Optional[str] = None
        # 记录本轮子图流式过程中尚未进入外层 values 的工具调用与返回，防止收尾 LLM 429 导致记录丢失
        self._pending_agent_name: Optional[str] = None
        self._pending_assistant_text: List[str] = []
        self._pending_tool_requests: Dict[str, Dict[str, Any]] = {}
        self._persisted_tool_req_ids: Set[str] = set()
        self._persisted_tool_res_ids: Set[str] = set()

    async def process_stream(
        self, swarm: StateGraph, messages: List[Dict[str, Any]], context: Dict[str, Any]
    ) -> None:
        """处理整个流式响应"""
        self.last_saved_message_index = len(messages) - 1

        compiled_swarm = swarm.compile()

        async for chunk in compiled_swarm.astream(
            {"messages": messages},
            config=context,
            stream_mode=["messages", "custom", "values"],
        ):
            await self._handle_chunk(chunk)

        # 完成事件统一由 chat_service._run_chat_task 的 finally 块发送，避免重复触发 done。

    async def _handle_chunk(self, chunk: Any) -> None:
        """处理单个 chunk"""
        chunk_type = chunk[0]

        if chunk_type == "values":
            await self._handle_values_chunk(chunk[1])
        else:
            await self._handle_message_chunk(chunk[1][0])

    async def _handle_values_chunk(self, chunk_data: Dict[str, Any]) -> None:
        """处理 values 类型的 chunk，跳过已由工具即时落库保存过的消息避免重复写入。"""
        all_messages = chunk_data.get("messages", [])
        oai_messages = convert_to_openai_messages(all_messages)
        if not isinstance(oai_messages, list):
            oai_messages = [oai_messages] if oai_messages else []

        await self.websocket_service(
            self.session_id, {"type": "all_messages", "messages": oai_messages}
        )

        for i in range(self.last_saved_message_index + 1, len(oai_messages)):
            new_message = oai_messages[i]
            if len(oai_messages) > 0 and not self._is_already_persisted(new_message):
                self._mark_persisted_from_oai_message(new_message)
                await self.db_service.create_message(
                    self.session_id,
                    new_message.get("role", "user"),
                    json.dumps(new_message),
                )
            self.last_saved_message_index = i
        self._pending_assistant_text.clear()

    def _is_already_persisted(self, oai_message: Dict[str, Any]) -> bool:
        """判断外层 values 中的某条消息是否已在子图工具返回瞬间提前写入数据库。"""
        role = oai_message.get("role")
        if role == "tool":
            tc_id = str(oai_message.get("tool_call_id") or "")
            return bool(tc_id and tc_id in self._persisted_tool_res_ids)
        if role == "assistant" and oai_message.get("tool_calls"):
            tc_ids = [
                str(tc.get("id") or "")
                for tc in oai_message.get("tool_calls", [])
                if isinstance(tc, dict) and tc.get("id")
            ]
            return bool(tc_ids and all(tid in self._persisted_tool_req_ids for tid in tc_ids))
        return False

    def _mark_persisted_from_oai_message(self, oai_message: Dict[str, Any]) -> None:
        """登记通过外层 values 正常落库的工具请求或结果 ID。"""
        role = oai_message.get("role")
        if role == "tool" and oai_message.get("tool_call_id"):
            self._persisted_tool_res_ids.add(str(oai_message["tool_call_id"]))
        elif role == "assistant" and oai_message.get("tool_calls"):
            for tc in oai_message.get("tool_calls", []):
                if isinstance(tc, dict) and tc.get("id"):
                    self._persisted_tool_req_ids.add(str(tc["id"]))

    async def _persist_tool_exchange_immediately(
        self, tool_msg: ToolMessage, oai_tool_msg: Dict[str, Any]
    ) -> None:
        """在 ToolMessage 产生瞬间将对应的 assistant(tool_calls) 与 tool 消息幂等写入数据库。"""
        tc_id = str(getattr(tool_msg, "tool_call_id", "") or oai_tool_msg.get("tool_call_id") or "")
        if not tc_id:
            return

        if tc_id not in self._persisted_tool_req_ids:
            req_info = self._pending_tool_requests.get(tc_id)
            tool_name = (
                (req_info or {}).get("name")
                or getattr(tool_msg, "name", None)
                or oai_tool_msg.get("name")
                or "tool"
            )
            raw_args = ""
            if req_info:
                parts = "".join(req_info.get("args_parts") or [])
                if parts.strip():
                    raw_args = parts
                elif req_info.get("initial_args"):
                    init_args = req_info["initial_args"]
                    raw_args = (
                        json.dumps(init_args, ensure_ascii=False)
                        if isinstance(init_args, dict)
                        else str(init_args)
                    )
            if not raw_args:
                raw_args = "{}"

            assistant_msg: Dict[str, Any] = {
                "role": "assistant",
                "content": "".join(self._pending_assistant_text),
                "tool_calls": [
                    {
                        "type": "function",
                        "id": tc_id,
                        "function": {
                            "name": str(tool_name),
                            "arguments": raw_args,
                        },
                    }
                ],
            }
            if self._pending_agent_name:
                assistant_msg["name"] = self._pending_agent_name

            self._persisted_tool_req_ids.add(tc_id)
            self._pending_assistant_text.clear()
            await self.db_service.create_message(
                self.session_id, "assistant", json.dumps(assistant_msg)
            )

        if tc_id not in self._persisted_tool_res_ids:
            self._persisted_tool_res_ids.add(tc_id)
            await self.db_service.create_message(
                self.session_id, "tool", json.dumps(oai_tool_msg)
            )

    async def _handle_message_chunk(self, ai_message_chunk: AIMessageChunk) -> None:
        """处理消息类型的 chunk"""
        try:
            chunk_name = getattr(ai_message_chunk, "name", None)
            if isinstance(chunk_name, str) and chunk_name.strip() and not isinstance(ai_message_chunk, ToolMessage):
                self._pending_agent_name = chunk_name.strip()

            content = ai_message_chunk.content

            if isinstance(ai_message_chunk, ToolMessage):
                oai_message = convert_to_openai_messages([ai_message_chunk])[0]
                _logger.info("👇toolcall res oai_message", oai_message)
                await self._persist_tool_exchange_immediately(ai_message_chunk, oai_message)
                await self.websocket_service(
                    self.session_id,
                    {
                        "type": "tool_call_result",
                        "id": ai_message_chunk.tool_call_id,
                        "message": oai_message,
                    },
                )
            elif content:
                if isinstance(content, str):
                    self._pending_assistant_text.append(content)
                await self.websocket_service(
                    self.session_id, {"type": "delta", "text": content}
                )
            elif (
                hasattr(ai_message_chunk, "tool_calls")
                and ai_message_chunk.tool_calls
                and ai_message_chunk.tool_calls[0].get("name")
            ):
                await self._handle_tool_calls(ai_message_chunk.tool_calls)

            if hasattr(ai_message_chunk, "tool_call_chunks"):
                await self._handle_tool_call_chunks(ai_message_chunk.tool_call_chunks)
        except Exception as e:
            _logger.info("🟠error", e)
            traceback.print_stack()

    async def _handle_tool_calls(self, tool_calls: List[ToolCall]) -> None:
        """处理工具调用事件并缓存调用元数据供即时落库复用。"""
        self.tool_calls = [tc for tc in tool_calls if tc.get("name")]
        _logger.info("😘tool_call event", tool_calls)
        TOOLS_REQUIRING_CONFIRMATION: set[str] = set()

        for tool_call in self.tool_calls:
            tool_name = tool_call.get("name")
            tc_id = str(tool_call.get("id") or "")
            if tc_id:
                entry = self._pending_tool_requests.setdefault(
                    tc_id,
                    {
                        "id": tc_id,
                        "name": tool_name,
                        "initial_args": tool_call.get("args"),
                        "args_parts": [],
                    },
                )
                if tool_name:
                    entry["name"] = tool_name
                if tool_call.get("args"):
                    entry["initial_args"] = tool_call.get("args")

            if tool_name in TOOLS_REQUIRING_CONFIRMATION:
                print(
                    f"🔄 Tool {tool_name} requires confirmation, skipping StreamProcessor event"
                )
                continue
            await self.websocket_service(
                self.session_id,
                {
                    "type": "tool_call",
                    "id": tool_call.get("id"),
                    "name": tool_name,
                    "arguments": "{}",
                },
            )

    async def _handle_tool_call_chunks(self, tool_call_chunks: List[Any]) -> None:
        """处理工具调用参数流片段。"""
        for tool_call_chunk in tool_call_chunks:
            if tool_call_chunk.get("id"):
                self.last_streaming_tool_call_id = str(tool_call_chunk.get("id"))
                entry = self._pending_tool_requests.setdefault(
                    self.last_streaming_tool_call_id,
                    {
                        "id": self.last_streaming_tool_call_id,
                        "name": tool_call_chunk.get("name"),
                        "initial_args": None,
                        "args_parts": [],
                    },
                )
                if tool_call_chunk.get("name"):
                    entry["name"] = tool_call_chunk.get("name")
                if tool_call_chunk.get("args"):
                    entry["args_parts"].append(str(tool_call_chunk.get("args")))
            else:
                if self.last_streaming_tool_call_id:
                    arg_piece = tool_call_chunk.get("args")
                    if arg_piece:
                        entry = self._pending_tool_requests.get(
                            self.last_streaming_tool_call_id
                        )
                        if entry is not None:
                            entry["args_parts"].append(str(arg_piece))
                    await self.websocket_service(
                        self.session_id,
                        {
                            "type": "tool_call_arguments",
                            "id": self.last_streaming_tool_call_id,
                            "text": arg_piece,
                        },
                    )
                else:
                    _logger.info("🟠no last_streaming_tool_call_id", tool_call_chunk)