"""程序说明：阶段 2（数据一致性）同步与异步回归测试，覆盖画布锁统一、WAL/外键与事务、缩略图保留、级联删除与 done 去重。"""
import asyncio
import inspect
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessageChunk

SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from routers import canvas as canvas_router
from services.db_service import DatabaseService
from services.langgraph_service.StreamProcessor import StreamProcessor
from tools import comfy_dynamic
from tools.utils import image_canvas_utils
from tools.video_generation import video_canvas_utils
from utils.canvas_lock import canvas_lock_manager


class Stage2DataConsistencyTests(unittest.TestCase):
    def test_shared_canvas_lock_manager_across_modules(self):
        self.assertIs(image_canvas_utils.canvas_lock_manager, canvas_lock_manager)
        self.assertIs(video_canvas_utils.canvas_lock_manager, canvas_lock_manager)
        self.assertIs(comfy_dynamic.canvas_lock_manager, canvas_lock_manager)
        self.assertIs(canvas_router.canvas_lock_manager, canvas_lock_manager)

    def test_sqlite_pragmas_wal_foreign_keys_busy_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "test.db")
            db = DatabaseService(db_path=db_path)
            conn = db._open_sync_connection()
            try:
                journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
                foreign_keys = conn.execute("PRAGMA foreign_keys").fetchone()[0]
                busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
            finally:
                conn.close()

            self.assertEqual(str(journal_mode).lower(), "wal")
            self.assertEqual(int(foreign_keys), 1)
            self.assertEqual(int(busy_timeout), 5000)

    def test_save_canvas_data_preserves_thumbnail_when_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "test.db")
            db = DatabaseService(db_path=db_path)
            db._create_canvas_sync("c1", "Canvas One")

            updated = db._save_canvas_data_sync("c1", '{"elements": [1]}', "thumb-v1")
            self.assertTrue(updated)

            # 未传 thumbnail（None）时必须保留原缩略图，不被覆盖为 NULL
            updated_again = db._save_canvas_data_sync("c1", '{"elements": [1, 2]}', None)
            self.assertTrue(updated_again)

            conn = db._open_sync_connection()
            try:
                row = conn.execute(
                    "SELECT data, thumbnail FROM canvases WHERE id = ?", ("c1",)
                ).fetchone()
            finally:
                conn.close()

            self.assertEqual(row["data"], '{"elements": [1, 2]}')
            self.assertEqual(row["thumbnail"], "thumb-v1")

    def test_delete_canvas_cascades_sessions_and_messages_under_foreign_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "test.db")
            db = DatabaseService(db_path=db_path)
            db._create_canvas_sync("c1", "Canvas One")
            db._create_canvas_sync("c2", "Canvas Two")

            db._create_chat_session_sync("s1", "gpt-4o", "openai", "c1", "Session 1")
            db._create_chat_session_sync("s2", "gpt-4o", "openai", "c2", "Session 2")
            db._create_message_sync("s1", "user", '{"role": "user", "content": "hi c1"}')
            db._create_message_sync("s2", "user", '{"role": "user", "content": "hi c2"}')

            # 外键开启时，按消息 -> 会话 -> 画布顺序在同一事务中删除
            db._delete_canvas_sync("c1")

            conn = db._open_sync_connection()
            try:
                canvases = [r["id"] for r in conn.execute("SELECT id FROM canvases").fetchall()]
                sessions = [r["id"] for r in conn.execute("SELECT id FROM chat_sessions").fetchall()]
                msgs = [r["session_id"] for r in conn.execute("SELECT session_id FROM chat_messages").fetchall()]
            finally:
                conn.close()

            self.assertNotIn("c1", canvases)
            self.assertIn("c2", canvases)
            self.assertEqual(sessions, ["s2"])
            self.assertEqual(msgs, ["s2"])

    def test_transaction_rolls_back_on_foreign_key_violation(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "test.db")
            db = DatabaseService(db_path=db_path)
            with self.assertRaises(sqlite3.IntegrityError):
                db._create_chat_session_sync("s-orphan", "m", "p", "missing-canvas", "title")

    def test_create_canvas_runs_before_handle_chat_and_stream_processor_no_done(self):
        create_src = inspect.getsource(canvas_router.create_canvas)
        self.assertLess(
            create_src.index("db_service.create_canvas"),
            create_src.index("handle_chat"),
        )

        stream_src = inspect.getsource(StreamProcessor.process_stream)
        self.assertNotIn("'type': 'done'", stream_src)
        self.assertNotIn('"type": "done"', stream_src)


class Stage2AsyncDataConsistencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_canvas_lock_serializes_concurrent_writers(self):
        events = []

        async def worker(canvas_id: str, label: str, delay: float):
            async with canvas_lock_manager.lock_canvas(canvas_id):
                events.append(f"enter:{label}")
                await asyncio.sleep(delay)
                events.append(f"exit:{label}")

        # 同一 canvas_id 必须严格串行进入；不同 canvas_id 可并发进行
        await asyncio.gather(
            worker("c-lock", "first", 0.03),
            worker("c-lock", "second", 0.01),
            worker("c-other", "other", 0.01),
        )
        first_enter = events.index("enter:first")
        first_exit = events.index("exit:first")
        second_enter = events.index("enter:second")
        self.assertLess(first_enter, first_exit)
        self.assertGreater(second_enter, first_exit)
        self.assertIn("enter:other", events)

    async def test_create_canvas_route_persists_before_starting_chat(self):
        call_order = []

        class _FakeRequest:
            async def json(self):
                return {"canvas_id": "c-async-1", "name": "Async Canvas"}

        async def fake_create(canvas_id, name):
            await asyncio.sleep(0.01)
            call_order.append(("create_canvas", canvas_id, name))

        async def fake_handle_chat(data):
            call_order.append(("handle_chat", data["canvas_id"]))

        with (
            patch.object(canvas_router.db_service, "create_canvas", side_effect=fake_create),
            patch.object(canvas_router, "handle_chat", side_effect=fake_handle_chat),
        ):
            res = await canvas_router.create_canvas(_FakeRequest())
            # 等待 asyncio.create_task 启动的 handle_chat 完成
            await asyncio.sleep(0.02)

        self.assertEqual(res, {"id": "c-async-1"})
        self.assertEqual(
            call_order,
            [("create_canvas", "c-async-1", "Async Canvas"), ("handle_chat", "c-async-1")],
        )

    async def test_stream_processor_does_not_emit_done(self):
        emitted = []

        async def fake_ws(session_id: str, payload: dict):
            emitted.append((session_id, payload))

        class _FakeCompiledSwarm:
            async def astream(self, inputs, config=None, stream_mode=None):
                yield ("messages", (AIMessageChunk(content="hello"), {}))

        class _FakeSwarm:
            def compile(self):
                return _FakeCompiledSwarm()

        processor = StreamProcessor("sess-1", db_service=AsyncMock(), websocket_service=fake_ws)
        await processor.process_stream(_FakeSwarm(), [{"role": "user", "content": "hi"}], {})

        self.assertEqual(emitted, [("sess-1", {"type": "delta", "text": "hello"})])
        self.assertFalse(any(p.get("type") == "done" for _, p in emitted))

    async def test_async_save_preserves_thumbnail_and_delete_cascades(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = DatabaseService(db_path=os.path.join(tmp, "async_stage2.db"))
            await db.create_canvas("c1", "Async Canvas")
            self.assertTrue(await db.save_canvas_data("c1", '{"v": 1}', "thumb-async"))
            self.assertTrue(await db.save_canvas_data("c1", '{"v": 2}', None))

            await db.create_chat_session("s1", "gpt-4o", "openai", "c1", "Chat")
            await db.create_message("s1", "user", '{"role": "user", "content": "hi"}')

            canvases = await db.list_canvases()
            self.assertEqual(canvases[0]["thumbnail"], "thumb-async")

            await db.delete_canvas("c1")
            self.assertIsNone(await db.get_canvas_data("c1"))
            self.assertEqual(await db.list_sessions("c1"), [])
            self.assertEqual(await db.get_chat_history("s1"), [])


if __name__ == "__main__":
    unittest.main()
