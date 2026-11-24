"""程序说明：提供基于 SQLite（WAL、外键约束与显式事务）的画布、会话、消息与工作流持久化服务。"""
import asyncio
from contextlib import contextmanager
import json
import os
import sqlite3
from typing import Any, Dict, Iterator, List, Optional

from .config_service import USER_DATA_DIR
from .migrations.manager import (
    CURRENT_VERSION,
    MigrationManager,
    backup_database_files,
    restore_database_backup,
)

DB_PATH = os.path.join(USER_DATA_DIR, "localmanus.db")


class DatabaseService:
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

    def _create_comfy_workflow_sync(
        self,
        name: str,
        api_json: str,
        description: str,
        inputs: str,
        outputs: Optional[str] = None,
        *,
        display_name: str = "",
        capability: str = "t2i",
        output_kind: str = "image",
        instance_id: Optional[str] = None,
        source_mode: str = "db",
        source_path: str = "",
        seed_strategy: str = "random",
        schema_version: int = 1,
        enabled: int = 1,
        checksum: str = "",
    ) -> int:
        with self._sync_transaction() as conn:
            cursor = conn.execute(
                """
                INSERT INTO comfy_workflows (
                    name, api_json, description, inputs, outputs,
                    display_name, capability, output_kind, instance_id,
                    source_mode, source_path, seed_strategy, schema_version,
                    enabled, checksum
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    name,
                    api_json,
                    description,
                    inputs,
                    outputs,
                    display_name or name,
                    capability or "t2i",
                    output_kind or "image",
                    instance_id,
                    source_mode or "db",
                    source_path or "",
                    seed_strategy or "random",
                    int(schema_version or 1),
                    1 if enabled else 0,
                    checksum or "",
                ),
            )
            return int(cursor.lastrowid or 0)

    async def create_comfy_workflow(
        self,
        name: str,
        api_json: str,
        description: str,
        inputs: str,
        outputs: Optional[str] = None,
        **kwargs: Any,
    ) -> int:
        """保存新的 ComfyUI 工作流定义。"""
        return await asyncio.to_thread(
            self._create_comfy_workflow_sync,
            name,
            api_json,
            description,
            inputs,
            outputs,
            **kwargs,
        )

    def _upsert_comfy_workflow_by_name_sync(
        self,
        name: str,
        api_json: str,
        description: str,
        inputs: str,
        outputs: Optional[str] = None,
        *,
        display_name: str = "",
        capability: str = "t2i",
        output_kind: str = "image",
        instance_id: Optional[str] = None,
        source_mode: str = "db",
        source_path: str = "",
        seed_strategy: str = "random",
        schema_version: int = 1,
        enabled: int = 1,
        checksum: str = "",
    ) -> Dict[str, Any]:
        """按工具名原地更新或新增工作流，绝不先删后建以防 ID 丢失或损坏数据。"""
        with self._sync_transaction() as conn:
            existing = conn.execute(
                "SELECT id FROM comfy_workflows WHERE name = ? ORDER BY id DESC LIMIT 1",
                (name,),
            ).fetchone()
            if existing is not None:
                wf_id = int(existing["id"])
                conn.execute(
                    """
                    UPDATE comfy_workflows
                    SET api_json = ?, description = ?, inputs = ?, outputs = ?,
                        display_name = ?, capability = ?, output_kind = ?,
                        instance_id = ?, source_mode = ?, source_path = ?,
                        seed_strategy = ?, schema_version = ?, enabled = ?,
                        checksum = ?,
                        updated_at = STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')
                    WHERE id = ?
                    """,
                    (
                        api_json,
                        description,
                        inputs,
                        outputs,
                        display_name or name,
                        capability or "t2i",
                        output_kind or "image",
                        instance_id,
                        source_mode or "db",
                        source_path or "",
                        seed_strategy or "random",
                        int(schema_version or 1),
                        1 if enabled else 0,
                        checksum or "",
                        wf_id,
                    ),
                )
                return {"id": wf_id, "created": False}

            cursor = conn.execute(
                """
                INSERT INTO comfy_workflows (
                    name, api_json, description, inputs, outputs,
                    display_name, capability, output_kind, instance_id,
                    source_mode, source_path, seed_strategy, schema_version,
                    enabled, checksum
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    name,
                    api_json,
                    description,
                    inputs,
                    outputs,
                    display_name or name,
                    capability or "t2i",
                    output_kind or "image",
                    instance_id,
                    source_mode or "db",
                    source_path or "",
                    seed_strategy or "random",
                    int(schema_version or 1),
                    1 if enabled else 0,
                    checksum or "",
                ),
            )
            return {"id": int(cursor.lastrowid or 0), "created": True}

    async def upsert_comfy_workflow_by_name(
        self,
        name: str,
        api_json: str,
        description: str,
        inputs: str,
        outputs: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """按工作流名原子新增或更新工作流定义。"""
        return await asyncio.to_thread(
            self._upsert_comfy_workflow_by_name_sync,
            name,
            api_json,
            description,
            inputs,
            outputs,
            **kwargs,
        )

    def _update_comfy_workflow_sync(
        self, id: int, updates: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """在事务内原地更新工作流字段并返回最新记录。"""
        allowed_cols = {
            "name",
            "display_name",
            "api_json",
            "description",
            "inputs",
            "outputs",
            "capability",
            "output_kind",
            "instance_id",
            "source_mode",
            "source_path",
            "seed_strategy",
            "schema_version",
            "enabled",
            "checksum",
        }
        filtered = {k: v for k, v in updates.items() if k in allowed_cols}
        if not filtered:
            return self._get_comfy_workflow_record_sync(id)

        if "enabled" in filtered:
            filtered["enabled"] = 1 if filtered["enabled"] else 0

        set_clauses = [f"{col} = ?" for col in filtered.keys()]
        set_clauses.append("updated_at = STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')")
        values = list(filtered.values()) + [id]

        with self._sync_transaction() as conn:
            cursor = conn.execute(
                f"UPDATE comfy_workflows SET {', '.join(set_clauses)} WHERE id = ?",
                values,
            )
            if cursor.rowcount == 0:
                return None

        return self._get_comfy_workflow_record_sync(id)

    async def update_comfy_workflow(
        self, id: int, updates: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """更新指定工作流记录。"""
        return await asyncio.to_thread(self._update_comfy_workflow_sync, id, updates)

    def _set_comfy_workflow_enabled_sync(
        self, id: int, enabled: bool
    ) -> Optional[Dict[str, Any]]:
        return self._update_comfy_workflow_sync(id, {"enabled": 1 if enabled else 0})

    async def set_comfy_workflow_enabled(
        self, id: int, enabled: bool
    ) -> Optional[Dict[str, Any]]:
        """切换 ComfyUI 工作流启用状态。"""
        return await asyncio.to_thread(self._set_comfy_workflow_enabled_sync, id, enabled)

    def _list_comfy_workflows_sync(self, enabled_only: bool = False) -> List[Dict[str, Any]]:
        conn = self._open_sync_connection()
        try:
            where_clause = "WHERE enabled = 1" if enabled_only else ""
            cursor = conn.execute(
                f"""
                SELECT id, name, display_name, description, api_json, inputs, outputs,
                       capability, output_kind, instance_id, source_mode, source_path,
                       seed_strategy, schema_version, enabled, checksum, created_at, updated_at
                FROM comfy_workflows
                {where_clause}
                ORDER BY id DESC
                """
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    async def list_comfy_workflows(self, enabled_only: bool = False) -> List[Dict[str, Any]]:
        """列出全部或仅启用的 ComfyUI 工作流。"""
        return await asyncio.to_thread(self._list_comfy_workflows_sync, enabled_only)

    def _get_comfy_workflow_record_sync(self, id: int) -> Optional[Dict[str, Any]]:
        conn = self._open_sync_connection()
        try:
            row = conn.execute(
                """
                SELECT id, name, display_name, description, api_json, inputs, outputs,
                       capability, output_kind, instance_id, source_mode, source_path,
                       seed_strategy, schema_version, enabled, checksum, created_at, updated_at
                FROM comfy_workflows WHERE id = ?
                """,
                (id,),
            ).fetchone()
            return dict(row) if row is not None else None
        finally:
            conn.close()

    async def get_comfy_workflow_record(self, id: int) -> Optional[Dict[str, Any]]:
        """获取包含完整元数据的工作流数据库记录。"""
        return await asyncio.to_thread(self._get_comfy_workflow_record_sync, id)

    def _delete_comfy_workflow_sync(self, id: int) -> None:
        with self._sync_transaction() as conn:
            conn.execute("DELETE FROM comfy_workflows WHERE id = ?", (id,))

    async def delete_comfy_workflow(self, id: int) -> None:
        """删除指定的 ComfyUI 工作流。"""
        await asyncio.to_thread(self._delete_comfy_workflow_sync, id)

    def _get_comfy_workflow_sync(self, id: int) -> Dict[str, Any]:
        conn = self._open_sync_connection()
        try:
            cursor = conn.execute(
                "SELECT api_json FROM comfy_workflows WHERE id = ?", (id,)
            )
            row = cursor.fetchone()
        finally:
            conn.close()

        if row is None:
            raise ValueError(f"ComfyUI workflow {id} not found")

        try:
            workflow_json = (
                row["api_json"]
                if isinstance(row["api_json"], dict)
                else json.loads(row["api_json"])
            )
            return workflow_json
        except json.JSONDecodeError as exc:
            raise ValueError(f"Stored workflow api_json is not valid JSON: {exc}")

    async def get_comfy_workflow(self, id: int) -> Dict[str, Any]:
        """读取并解析指定 ComfyUI 工作流的 API JSON。"""
        return await asyncio.to_thread(self._get_comfy_workflow_sync, id)

    # ---------- ComfyUI 多实例配置 ----------

    def _list_comfy_instances_sync(self, enabled_only: bool = False) -> List[Dict[str, Any]]:
        conn = self._open_sync_connection()
        try:
            where_clause = "WHERE enabled = 1" if enabled_only else ""
            rows = conn.execute(
                f"""
                SELECT id, name, base_url, auth_type, auth_header_name, auth_secret,
                       max_concurrency, timeout_sec, enabled, priority,
                       capabilities_json, last_health_json, updated_at
                FROM comfy_instances
                {where_clause}
                ORDER BY priority ASC, id ASC
                """
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    async def list_comfy_instances(self, enabled_only: bool = False) -> List[Dict[str, Any]]:
        """列出全部或启用的 ComfyUI 实例。"""
        return await asyncio.to_thread(self._list_comfy_instances_sync, enabled_only)

    def _get_comfy_instance_sync(self, instance_id: str) -> Optional[Dict[str, Any]]:
        conn = self._open_sync_connection()
        try:
            row = conn.execute(
                """
                SELECT id, name, base_url, auth_type, auth_header_name, auth_secret,
                       max_concurrency, timeout_sec, enabled, priority,
                       capabilities_json, last_health_json, updated_at
                FROM comfy_instances WHERE id = ?
                """,
                (instance_id,),
            ).fetchone()
            return dict(row) if row is not None else None
        finally:
            conn.close()

    async def get_comfy_instance(self, instance_id: str) -> Optional[Dict[str, Any]]:
        """获取指定 ComfyUI 实例配置。"""
        return await asyncio.to_thread(self._get_comfy_instance_sync, instance_id)

    def _upsert_comfy_instance_sync(self, data: Dict[str, Any]) -> Dict[str, Any]:
        instance_id = str(data["id"]).strip()
        name = str(data.get("name") or instance_id).strip()
        base_url = str(data.get("base_url") or "").strip().rstrip("/")
        auth_type = str(data.get("auth_type") or "none").strip() or "none"
        auth_header_name = str(data.get("auth_header_name") or "").strip()
        auth_secret = str(data.get("auth_secret") or "")
        max_concurrency = max(1, int(data.get("max_concurrency") or 1))
        timeout_sec = max(10, int(data.get("timeout_sec") or 300))
        enabled = 1 if data.get("enabled", True) else 0
        priority = int(data.get("priority") or 100)
        capabilities_raw = data.get("capabilities_json", "[]")
        capabilities_json = (
            capabilities_raw
            if isinstance(capabilities_raw, str)
            else json.dumps(capabilities_raw)
        )
        health_raw = data.get("last_health_json", "{}")
        last_health_json = (
            health_raw if isinstance(health_raw, str) else json.dumps(health_raw)
        )

        with self._sync_transaction() as conn:
            conn.execute(
                """
                INSERT INTO comfy_instances (
                    id, name, base_url, auth_type, auth_header_name, auth_secret,
                    max_concurrency, timeout_sec, enabled, priority,
                    capabilities_json, last_health_json, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now'))
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    base_url = excluded.base_url,
                    auth_type = excluded.auth_type,
                    auth_header_name = excluded.auth_header_name,
                    auth_secret = excluded.auth_secret,
                    max_concurrency = excluded.max_concurrency,
                    timeout_sec = excluded.timeout_sec,
                    enabled = excluded.enabled,
                    priority = excluded.priority,
                    capabilities_json = excluded.capabilities_json,
                    updated_at = STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')
                """,
                (
                    instance_id,
                    name,
                    base_url,
                    auth_type,
                    auth_header_name,
                    auth_secret,
                    max_concurrency,
                    timeout_sec,
                    enabled,
                    priority,
                    capabilities_json,
                    last_health_json,
                ),
            )
        record = self._get_comfy_instance_sync(instance_id)
        if record is None:
            raise RuntimeError(f"Failed to upsert comfy instance {instance_id}")
        return record

    async def upsert_comfy_instance(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """创建或更新 ComfyUI 实例配置。"""
        return await asyncio.to_thread(self._upsert_comfy_instance_sync, data)

    def _delete_comfy_instance_sync(self, instance_id: str) -> bool:
        with self._sync_transaction() as conn:
            cursor = conn.execute(
                "DELETE FROM comfy_instances WHERE id = ?", (instance_id,)
            )
            return cursor.rowcount > 0

    async def delete_comfy_instance(self, instance_id: str) -> bool:
        """删除 ComfyUI 实例配置。"""
        return await asyncio.to_thread(self._delete_comfy_instance_sync, instance_id)

    def _update_comfy_instance_health_sync(
        self, instance_id: str, health_json: str
    ) -> None:
        with self._sync_transaction() as conn:
            conn.execute(
                """
                UPDATE comfy_instances
                SET last_health_json = ?,
                    updated_at = STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE id = ?
                """,
                (health_json, instance_id),
            )

    async def update_comfy_instance_health(
        self, instance_id: str, health_json: str
    ) -> None:
        """更新 ComfyUI 实例健康检查快照。"""
        await asyncio.to_thread(
            self._update_comfy_instance_health_sync, instance_id, health_json
        )

    # ---------- 生成任务状态表 (jobs) ----------

    def _create_job_sync(self, job: Dict[str, Any]) -> str:
        job_id = str(job["id"])
        with self._sync_transaction() as conn:
            conn.execute(
                """
                INSERT INTO jobs (
                    id, session_id, canvas_id, tool_call_id, capability,
                    provider, instance_id, workflow_id, remote_prompt_id,
                    status, progress_pct, progress_text, error
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    job.get("session_id"),
                    job.get("canvas_id"),
                    job.get("tool_call_id"),
                    job.get("capability") or "custom",
                    job.get("provider") or "comfyui",
                    job.get("instance_id"),
                    job.get("workflow_id"),
                    job.get("remote_prompt_id"),
                    job.get("status") or "queued",
                    int(job.get("progress_pct") or 0),
                    job.get("progress_text") or "",
                    job.get("error"),
                ),
            )
        return job_id

    async def create_job(self, job: Dict[str, Any]) -> str:
        """写入一条新的异步媒体生成任务记录。"""
        return await asyncio.to_thread(self._create_job_sync, job)

    def _update_job_status_sync(self, job_id: str, **fields: Any) -> None:
        allowed_cols = {
            "remote_prompt_id",
            "status",
            "progress_pct",
            "progress_text",
            "error",
            "started_at",
            "finished_at",
        }
        filtered = {k: v for k, v in fields.items() if k in allowed_cols}
        if not filtered:
            return
        clauses = [f"{k} = ?" for k in filtered.keys()]
        values = list(filtered.values()) + [job_id]
        with self._sync_transaction() as conn:
            conn.execute(
                f"UPDATE jobs SET {', '.join(clauses)} WHERE id = ?",
                values,
            )

    async def update_job_status(self, job_id: str, **fields: Any) -> None:
        """更新生成任务进度、远程 prompt_id 或终态。"""
        await asyncio.to_thread(self._update_job_status_sync, job_id, **fields)

    def _get_job_sync(self, job_id: str) -> Optional[Dict[str, Any]]:
        conn = self._open_sync_connection()
        try:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            return dict(row) if row is not None else None
        finally:
            conn.close()

    async def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """读取指定任务记录。"""
        return await asyncio.to_thread(self._get_job_sync, job_id)

    def _interrupt_stale_jobs_sync(self) -> int:
        with self._sync_transaction() as conn:
            cur = conn.execute(
                """
                UPDATE jobs
                SET status = 'interrupted',
                    error = COALESCE(NULLIF(error, ''), 'Server restarted while the job was running'),
                    finished_at = COALESCE(finished_at, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
                WHERE status IN ('queued', 'running')
                  AND (remote_prompt_id IS NULL OR remote_prompt_id = '')
                """
            )
            return int(cur.rowcount or 0)

    def _list_recoverable_jobs_sync(self) -> List[Dict[str, Any]]:
        conn = self._open_sync_connection()
        try:
            rows = conn.execute(
                """
                SELECT * FROM jobs
                WHERE status IN ('queued', 'running')
                  AND remote_prompt_id IS NOT NULL AND remote_prompt_id != ''
                ORDER BY created_at ASC
                """
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    async def list_recoverable_jobs(self) -> List[Dict[str, Any]]:
        """列出重启时仍在远端执行、已知 prompt_id 的任务，供恢复流程接管。"""
        return await asyncio.to_thread(self._list_recoverable_jobs_sync)

    async def interrupt_stale_jobs(self) -> int:
        """服务启动时把上次崩溃或重启遗留的 queued/running 任务标为 interrupted，返回处理条数。"""
        return await asyncio.to_thread(self._interrupt_stale_jobs_sync)


# 全局单例数据库服务
db_service = DatabaseService()
