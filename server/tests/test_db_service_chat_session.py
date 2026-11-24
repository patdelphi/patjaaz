"""程序说明：验证重复聊天请求不会因会话主键冲突而失败。"""
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIR))

from services.db_service import DatabaseService


class ChatSessionIdempotencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_chat_session_ignores_duplicate_id(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "chat.sqlite3"
            connection = sqlite3.connect(database_path)
            try:
                connection.execute(
                    """CREATE TABLE chat_sessions (
                        id TEXT PRIMARY KEY,
                        model TEXT,
                        provider TEXT,
                        canvas_id TEXT,
                        title TEXT
                    )"""
                )
            finally:
                connection.close()

            database = DatabaseService.__new__(DatabaseService)
            database.db_path = str(database_path)

            await database.create_chat_session(
                "same-session", "model-a", "provider-a", "canvas", "first"
            )
            await database.create_chat_session(
                "same-session", "model-b", "provider-b", "canvas", "retry"
            )

            connection = sqlite3.connect(database_path)
            try:
                rows = connection.execute(
                    "SELECT id, model, title FROM chat_sessions"
                ).fetchall()
            finally:
                connection.close()

        self.assertEqual(rows, [("same-session", "model-a", "first")])


if __name__ == "__main__":
    unittest.main()
