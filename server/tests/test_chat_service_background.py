"""程序说明：验证聊天请求会快速交给后台任务处理。"""
import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

SERVER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIR))

from services.chat_service import handle_chat
from services.stream_service import (
    get_stream_status,
    get_stream_task,
    update_stream_status,
)
from routers.chat_router import chat_status


class ChatServiceBackgroundTests(unittest.IsolatedAsyncioTestCase):
    async def test_handle_chat_returns_while_agent_task_is_still_running(self):
        """HTTP handler 应快速返回，流任务仍可被取消接口找到。"""
        started = asyncio.Event()
        release_agent = asyncio.Event()

        async def slow_agent(*args):
            started.set()
            await release_agent.wait()

        payload = {
            "messages": [{"role": "user", "content": "test"}],
            "session_id": "background-test-session",
            "canvas_id": "test-canvas",
            "text_model": {"model": "mock", "provider": "mock"},
            "tool_list": [],
        }

        create_session = AsyncMock()
        create_message = AsyncMock()
        with (
            patch("services.chat_service.db_service.create_chat_session", create_session),
            patch("services.chat_service.db_service.create_message", create_message),
            patch("services.chat_service.langgraph_multi_agent", side_effect=slow_agent),
            patch("services.chat_service.send_to_websocket", new_callable=AsyncMock),
        ):
            request_task = asyncio.create_task(handle_chat(payload))
            background_task = None
            try:
                await asyncio.wait_for(started.wait(), timeout=1)
                await asyncio.wait_for(asyncio.shield(request_task), timeout=0.1)
                background_task = get_stream_task("background-test-session")
                self.assertIsNotNone(background_task)
                self.assertFalse(background_task.done())
                status = await chat_status("background-test-session")
                self.assertTrue(status["active"])
                self.assertEqual(status["status"], "Task is running")
                self.assertGreater(status["started_at"], 0)
                update_stream_status(
                    "background-test-session", "Executing KSampler 25%"
                )
                self.assertEqual(
                    get_stream_status("background-test-session")["status"],
                    "Executing KSampler 25%",
                )
                await handle_chat(payload)
                self.assertEqual(create_session.await_count, 1)
                self.assertEqual(create_message.await_count, 1)
            finally:
                release_agent.set()
                if not request_task.done():
                    await request_task
                await asyncio.sleep(0)
                remaining_tasks = [
                    task for task in asyncio.all_tasks()
                    if task.get_name() == "chat:background-test-session"
                ]
                if remaining_tasks:
                    await asyncio.gather(*remaining_tasks, return_exceptions=True)
            final_status = get_stream_status("background-test-session")
            self.assertFalse(final_status["active"])
            self.assertTrue(final_status["known"])
            self.assertEqual(final_status["terminal_state"], "completed")

    async def test_unhandled_agent_error_is_sent_to_the_session(self):
        """后台任务异常应通过 Socket.IO 错误事件反馈给当前会话。"""
        payload = {
            "messages": [{"role": "user", "content": "test"}],
            "session_id": "background-error-session",
            "canvas_id": "test-canvas",
            "text_model": {"model": "mock", "provider": "mock"},
            "tool_list": [],
        }

        async def failing_agent(*args):
            raise RuntimeError("model unavailable")

        with (
            patch("services.chat_service.db_service.create_chat_session", new_callable=AsyncMock),
            patch("services.chat_service.db_service.create_message", new_callable=AsyncMock),
            patch("services.chat_service.langgraph_multi_agent", side_effect=failing_agent),
            patch("services.chat_service.send_to_websocket", new_callable=AsyncMock) as send_event,
        ):
            await handle_chat(payload)
            background_task = get_stream_task("background-error-session")
            self.assertIsNotNone(background_task)
            await background_task

            send_event.assert_any_await(
                "background-error-session",
                {"type": "error", "error": "model unavailable"},
            )
            final_status = get_stream_status("background-error-session")
            self.assertFalse(final_status["active"])
            self.assertEqual(final_status["terminal_state"], "failed")


if __name__ == "__main__":
    unittest.main()
