"""程序说明：SQLite v4 数据迁移，新增 ComfyUI 多实例表、任务追踪表，并幂等扩展工作流元数据与开关列。"""
import sqlite3
from . import Migration


class V4ComfyInstancesAndWorkflows(Migration):
    """数据库 v4 迁移：支持 ComfyUI 多实例配置、任务状态追踪与工作流能力元数据。"""

    version = 4
    description = "Add comfy_instances, jobs, and comfy_workflows metadata columns"

    def up(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS comfy_instances (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                base_url TEXT NOT NULL,
                auth_type TEXT NOT NULL DEFAULT 'none'
                    CHECK (auth_type IN ('none', 'bearer', 'basic', 'header')),
                auth_header_name TEXT DEFAULT '',
                auth_secret TEXT DEFAULT '',
                max_concurrency INTEGER NOT NULL DEFAULT 1,
                timeout_sec INTEGER NOT NULL DEFAULT 300,
                enabled INTEGER NOT NULL DEFAULT 1,
                priority INTEGER NOT NULL DEFAULT 100,
                capabilities_json TEXT NOT NULL DEFAULT '[]',
                last_health_json TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now'))
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                session_id TEXT,
                canvas_id TEXT,
                tool_call_id TEXT,
                capability TEXT NOT NULL,
                provider TEXT NOT NULL,
                instance_id TEXT,
                workflow_id INTEGER,
                remote_prompt_id TEXT,
                status TEXT NOT NULL DEFAULT 'queued',
                progress_pct INTEGER DEFAULT 0,
                progress_text TEXT DEFAULT '',
                error TEXT,
                created_at TEXT DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')),
                started_at TEXT,
                finished_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_jobs_session_created
            ON jobs(session_id, created_at DESC)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_jobs_status
            ON jobs(status)
            """
        )

        # 幂等检查现有列后再执行 ALTER TABLE，避免重放或历史差异导致 Duplicate column 错误
        existing_cols = {
            row[1]
            for row in conn.execute("PRAGMA table_info(comfy_workflows)").fetchall()
        }
        alter_columns = [
            ("display_name", "TEXT NOT NULL DEFAULT ''"),
            ("capability", "TEXT NOT NULL DEFAULT 't2i'"),
            ("output_kind", "TEXT NOT NULL DEFAULT 'image'"),
            ("instance_id", "TEXT DEFAULT NULL"),
            ("source_mode", "TEXT NOT NULL DEFAULT 'db'"),
            ("source_path", "TEXT NOT NULL DEFAULT ''"),
            ("seed_strategy", "TEXT NOT NULL DEFAULT 'random'"),
            ("schema_version", "INTEGER NOT NULL DEFAULT 1"),
            ("enabled", "INTEGER NOT NULL DEFAULT 1"),
            ("checksum", "TEXT NOT NULL DEFAULT ''"),
            ("updated_at", "TEXT NOT NULL DEFAULT ''"),
        ]
        for col_name, col_def in alter_columns:
            if col_name not in existing_cols:
                conn.execute(
                    f"ALTER TABLE comfy_workflows ADD COLUMN {col_name} {col_def}"
                )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_comfy_workflows_enabled_cap
            ON comfy_workflows(enabled, capability)
            """
        )

        # 回填历史工作流（如 text2image_MOSS、ImageEdit_MOSS）展示名与默认能力标签，保留原始数据完整
        conn.execute(
            """
            UPDATE comfy_workflows
            SET display_name = name
            WHERE display_name IS NULL OR TRIM(display_name) = ''
            """
        )
        conn.execute(
            """
            UPDATE comfy_workflows
            SET capability = CASE
                WHEN LOWER(name) LIKE '%edit%' OR LOWER(name) LIKE '%i2i%' THEN 'i2i'
                WHEN LOWER(name) LIKE '%inpaint%' THEN 'inpaint'
                WHEN LOWER(name) LIKE '%upscale%' THEN 'upscale'
                WHEN LOWER(name) LIKE '%i2v%' THEN 'i2v'
                WHEN LOWER(name) LIKE '%t2v%' OR LOWER(name) LIKE '%video%' THEN 't2v'
                WHEN LOWER(name) LIKE '%tts%' OR LOWER(name) LIKE '%audio%' THEN 'tts'
                ELSE 't2i'
            END,
            output_kind = CASE
                WHEN LOWER(name) LIKE '%i2v%' OR LOWER(name) LIKE '%t2v%' OR LOWER(name) LIKE '%video%' THEN 'video'
                WHEN LOWER(name) LIKE '%tts%' OR LOWER(name) LIKE '%audio%' THEN 'audio'
                ELSE 'image'
            END
            WHERE capability = 't2i'
            """
        )

    def down(self, conn: sqlite3.Connection) -> None:
        pass
