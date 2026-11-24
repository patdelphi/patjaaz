"""程序说明：验证画布保存能识别数据库更新失败。"""
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIR))

from services.db_service import DatabaseService


class CanvasPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_save_canvas_data_reports_updated_and_missing_canvas(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "canvas.sqlite3"
            connection = sqlite3.connect(database_path)
            try:
                connection.execute(
                    "CREATE TABLE canvases (id TEXT PRIMARY KEY, data TEXT, thumbnail TEXT, updated_at TEXT)"
                )
                connection.execute(
                    "INSERT INTO canvases (id, data, thumbnail) VALUES (?, ?, ?)",
                    ("existing", "{}", ""),
                )
                connection.commit()
            finally:
                connection.close()

            database = DatabaseService.__new__(DatabaseService)
            database.db_path = str(database_path)

            saved = await database.save_canvas_data("existing", '{"elements":[]}', "")
            missing = await database.save_canvas_data("missing", '{"elements":[]}', "")

        self.assertTrue(saved)
        self.assertFalse(missing)


if __name__ == "__main__":
    unittest.main()
