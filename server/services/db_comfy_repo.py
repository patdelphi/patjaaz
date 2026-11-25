"""程序说明：DatabaseService 的 ComfyUI 工作流、多实例配置与后台任务状态（jobs）仓储混入类。"""
from __future__ import annotations

import asyncio
import json
import sqlite3
from typing import Any, Dict, List, Optional


class ComfyWorkflowAndJobRepoMixin:
    """封装 comfy_workflows、comfy_instances 与 jobs 三张表的同步事务与异步访问方法。"""

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
