"""程序说明：提供基于 SQLite（WAL、外键约束与显式事务）的画布、会话、消息与工作流持久化服务。"""
import asyncio
from contextlib import contextmanager
import json
import os
import sqlite3
from typing import Any, Dict, Iterator, List, Optional

from .config_service import USER_DATA_DIR
from .db_comfy_repo import ComfyWorkflowAndJobRepoMixin
from .migrations.manager import (
    CURRENT_VERSION,
    MigrationManager,
    backup_database_files,
    restore_database_backup,
)

DB_PATH = os.path.join(USER_DATA_DIR, "localmanus.db")


class DatabaseService(ComfyWorkflowAndJobRepoMixin):
    """封装画布、聊天会话、消息和工作流配置的 SQLite 存储操作。"""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._ensure_db_directory()
        self._migration_manager = MigrationManager()
        self._init_db()

    def _ensure_db_directory(self) -> None:
        """确保数据库所在目录存在。"""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

    def _open_sync_connection(self) -> sqlite3.Connection:
        """打开配置好 WAL、外键约束与锁超时的同步连接。"""
        conn = sqlite3.connect(self.db_path, isolation_level=None, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    @contextmanager
    def _sync_transaction(self) -> Iterator[sqlite3.Connection]:
        """在显式 IMMEDIATE 事务中执行写操作，异常时自动回滚。"""
        conn = self._open_sync_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.execute("COMMIT")
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        """初始化版本表，在结构迁移前自动备份已有数据库并支持失败回滚。"""
        backup_path: Optional[str] = None
        if os.path.exists(self.db_path) and os.path.getsize(self.db_path) > 0:
            check_conn = self._open_sync_connection()
            try:
                has_ver_table = check_conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='db_version'"
                ).fetchone()
                if has_ver_table:
                    row = check_conn.execute("SELECT version FROM db_version").fetchone()
                    if row is not None and 0 < int(row[0]) < CURRENT_VERSION:
                        # 迁移前刷盘 WAL，确保备份包含完整一致数据
                        check_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                        from_ver = int(row[0])
                        check_conn.close()
                        check_conn = None
                        backup_path = backup_database_files(self.db_path, from_ver)
                        print(f"💾 Backed up SQLite v{from_ver} database to: {backup_path}")
            finally:
                if check_conn is not None:
                    check_conn.close()

        try:
            with self._sync_transaction() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS db_version (
                        version INTEGER PRIMARY KEY
                    )
                    """
                )

                cursor = conn.execute("SELECT version FROM db_version")
                current_version = cursor.fetchone()
                print(
                    'local db version',
                    current_version[0] if current_version else None,
                    'latest version',
                    CURRENT_VERSION,
                )

                if current_version is None:
                    conn.execute("INSERT INTO db_version (version) VALUES (0)")
                    self._migration_manager.migrate(conn, 0, CURRENT_VERSION)
                elif current_version[0] < CURRENT_VERSION:
                    print('Migrating database from version', current_version[0], 'to', CURRENT_VERSION)
                    self._migration_manager.migrate(conn, current_version[0], CURRENT_VERSION)
        except Exception:
            if backup_path:
                print(f"⚠️ Migration failed, restoring database backup from: {backup_path}")
                restore_database_backup(backup_path, self.db_path)
            raise

    def _create_canvas_sync(self, id: str, name: str) -> None:
        with self._sync_transaction() as conn:
            conn.execute(
                """
                INSERT INTO canvases (id, name)
                VALUES (?, ?)
                """,
                (id, name),
            )

    async def create_canvas(self, id: str, name: str) -> None:
        """创建新画布记录。"""
        await asyncio.to_thread(self._create_canvas_sync, id, name)

    def _list_canvases_sync(self) -> List[Dict[str, Any]]:
        conn = self._open_sync_connection()
        try:
            cursor = conn.execute("""
                SELECT id, name, description, thumbnail, created_at, updated_at
                FROM canvases
                ORDER BY updated_at DESC
            """)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    async def list_canvases(self) -> List[Dict[str, Any]]:
        """按更新时间倒序列出全部画布。"""
        return await asyncio.to_thread(self._list_canvases_sync)

    def _create_chat_session_sync(
        self,
        id: str,
        model: str,
        provider: str,
        canvas_id: str,
        title: Optional[str] = None,
    ) -> None:
        with self._sync_transaction() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO chat_sessions (id, model, provider, canvas_id, title)
                VALUES (?, ?, ?, ?, ?)
                """,
                (id, model, provider, canvas_id, title),
            )

    async def create_chat_session(
        self,
        id: str,
        model: str,
        provider: str,
        canvas_id: str,
        title: Optional[str] = None,
    ) -> None:
        """创建聊天会话；重试时忽略已存在的相同会话 ID。"""
        await asyncio.to_thread(
            self._create_chat_session_sync, id, model, provider, canvas_id, title
        )

    def _create_message_sync(self, session_id: str, role: str, message: str) -> None:
        with self._sync_transaction() as conn:
            conn.execute(
                """
                INSERT INTO chat_messages (session_id, role, message)
                VALUES (?, ?, ?)
                """,
                (session_id, role, message),
            )

    async def create_message(self, session_id: str, role: str, message: str) -> None:
        """保存单条聊天消息。"""
        await asyncio.to_thread(self._create_message_sync, session_id, role, message)

    def _get_chat_history_sync(self, session_id: str) -> List[Dict[str, Any]]:
        conn = self._open_sync_connection()
        try:
            cursor = conn.execute(
                """
                SELECT role, message, id
                FROM chat_messages
                WHERE session_id = ?
                ORDER BY id ASC
                """,
                (session_id,),
            )
            rows = cursor.fetchall()

            messages: List[Dict[str, Any]] = []
            for row in rows:
                row_dict = dict(row)
                if row_dict['message']:
                    try:
                        msg = json.loads(row_dict['message'])
                        messages.append(msg)
                    except json.JSONDecodeError:
                        pass
            return messages
        finally:
            conn.close()

    async def get_chat_history(self, session_id: str) -> List[Dict[str, Any]]:
        """获取指定会话的历史消息列表。"""
        return await asyncio.to_thread(self._get_chat_history_sync, session_id)

    def _list_sessions_sync(self, canvas_id: Optional[str] = None) -> List[Dict[str, Any]]:
        conn = self._open_sync_connection()
        try:
            if canvas_id:
                cursor = conn.execute(
                    """
                    SELECT id, title, model, provider, created_at, updated_at
                    FROM chat_sessions
                    WHERE canvas_id = ?
                    ORDER BY updated_at DESC
                    """,
                    (canvas_id,),
                )
            else:
                cursor = conn.execute("""
                    SELECT id, title, model, provider, created_at, updated_at
                    FROM chat_sessions
                    ORDER BY updated_at DESC
                """)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    async def list_sessions(self, canvas_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """按画布 ID 或全局列出聊天会话。"""
        return await asyncio.to_thread(self._list_sessions_sync, canvas_id)

    def _save_canvas_data_sync(
        self, id: str, data: str, thumbnail: Optional[str] = None
    ) -> bool:
        """保存画布 JSON 数据；未显式传入 thumbnail 时保留数据库原缩略图。"""
        with self._sync_transaction() as conn:
            if thumbnail is None:
                cursor = conn.execute(
                    """
                    UPDATE canvases
                    SET data = ?, updated_at = STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')
                    WHERE id = ?
                    """,
                    (data, id),
                )
            else:
                cursor = conn.execute(
                    """
                    UPDATE canvases
                    SET data = ?, thumbnail = ?, updated_at = STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')
                    WHERE id = ?
                    """,
                    (data, thumbnail, id),
                )
            return cursor.rowcount == 1

    async def save_canvas_data(
        self, id: str, data: str, thumbnail: Optional[str] = None
    ) -> bool:
        """保存画布数据，并可选更新缩略图。"""
        return await asyncio.to_thread(self._save_canvas_data_sync, id, data, thumbnail)

    def _get_canvas_data_sync(self, id: str) -> Optional[Dict[str, Any]]:
        conn = self._open_sync_connection()
        try:
            cursor = conn.execute(
                """
                SELECT data, name
                FROM canvases
                WHERE id = ?
                """,
                (id,),
            )
            row = cursor.fetchone()
            sessions = self._list_sessions_sync(id)

            if row:
                return {
                    'data': json.loads(row['data']) if row['data'] else {},
                    'name': row['name'],
                    'sessions': sessions,
                }
            return None
        finally:
            conn.close()

    async def get_canvas_data(self, id: str) -> Optional[Dict[str, Any]]:
        """获取指定画布的内容及其会话列表。"""
        return await asyncio.to_thread(self._get_canvas_data_sync, id)

    def _delete_canvas_sync(self, id: str) -> None:
        """在同一事务内先删聊天消息和会话，再删画布（暂保留磁盘资产文件）。"""
        with self._sync_transaction() as conn:
            conn.execute(
                """
                DELETE FROM chat_messages
                WHERE session_id IN (
                    SELECT id FROM chat_sessions WHERE canvas_id = ?
                )
                """,
                (id,),
            )
            conn.execute("DELETE FROM chat_sessions WHERE canvas_id = ?", (id,))
            conn.execute("DELETE FROM canvases WHERE id = ?", (id,))

    async def delete_canvas(self, id: str) -> None:
        """删除画布及其关联的聊天会话与消息记录。"""
        await asyncio.to_thread(self._delete_canvas_sync, id)

    def _rename_canvas_sync(self, id: str, name: str) -> None:
        with self._sync_transaction() as conn:
            conn.execute(
                """
                UPDATE canvases
                SET name = ?, updated_at = STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE id = ?
                """,
                (name, id),
            )

    async def rename_canvas(self, id: str, name: str) -> None:
        """重命名画布。"""
        await asyncio.to_thread(self._rename_canvas_sync, id, name)




# 全局单例数据库服务
db_service = DatabaseService()
