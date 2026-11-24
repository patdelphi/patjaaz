"""程序说明：管理 SQLite 数据库版本升级以及升级前的自动文件备份与失败恢复。"""
from datetime import datetime
import os
import shutil
import sqlite3
from typing import List, Type

from services.migrations.v1_initial_schema import V1InitialSchema
from services.migrations.v2_add_canvases import V2AddCanvases
from services.migrations.v3_add_comfy_workflow import V3AddComfyWorkflow
from services.migrations.v4_comfy_instances_and_workflows import (
    V4ComfyInstancesAndWorkflows,
)
from . import Migration

# Database version
CURRENT_VERSION = 4

ALL_MIGRATIONS = [
    {
        'version': 1,
        'migration': V1InitialSchema,
    },
    {
        'version': 2,
        'migration': V2AddCanvases,
    },
    {
        'version': 3,
        'migration': V3AddComfyWorkflow,
    },
    {
        'version': 4,
        'migration': V4ComfyInstancesAndWorkflows,
    },
]


def backup_database_files(db_path: str, from_version: int) -> str:
    """在数据库结构迁移前备份主库及 WAL/SHM 附属文件，返回备份主文件路径。"""
    abs_db = os.path.abspath(db_path)
    backup_dir = os.path.join(os.path.dirname(abs_db), "backups")
    os.makedirs(backup_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    base_name = os.path.basename(abs_db)
    backup_main = os.path.join(
        backup_dir, f"{base_name}.bak-v{from_version}-{timestamp}"
    )

    if os.path.exists(abs_db):
        shutil.copy2(abs_db, backup_main)
    for suffix in ("-wal", "-shm"):
        src_sidecar = f"{abs_db}{suffix}"
        if os.path.exists(src_sidecar):
            shutil.copy2(src_sidecar, f"{backup_main}{suffix}")
    return backup_main


def restore_database_backup(backup_main: str, db_path: str) -> None:
    """当迁移失败时，从备份恢复原数据库及附属文件。"""
    if not backup_main or not os.path.exists(backup_main):
        return
    abs_db = os.path.abspath(db_path)
    shutil.copy2(backup_main, abs_db)
    for suffix in ("-wal", "-shm"):
        bak_sidecar = f"{backup_main}{suffix}"
        dst_sidecar = f"{abs_db}{suffix}"
        if os.path.exists(bak_sidecar):
            shutil.copy2(bak_sidecar, dst_sidecar)
        elif os.path.exists(dst_sidecar):
            try:
                os.remove(dst_sidecar)
            except OSError:
                pass


class MigrationManager:
    """按版本号顺序执行数据库前向迁移。"""

    def get_migrations_to_apply(self, current_version: int, target_version: int) -> List[Type[Migration]]:
        """Get list of migrations to apply"""
        return [m for m in ALL_MIGRATIONS
                if m['version'] > current_version and m['version'] <= target_version]

    def get_migrations_to_rollback(self, current_version: int, target_version: int) -> List[Type[Migration]]:
        """Get list of migrations to rollback"""
        return [m for m in reversed(ALL_MIGRATIONS)
                if m['version'] <= current_version and m['version'] > target_version]

    def migrate(self, conn: sqlite3.Connection, from_version: int, to_version: int) -> None:
        """Apply forward migrations to reach target version"""
        if from_version < to_version:
            print('🦄 Applying migrations forward', from_version, '->', to_version)
            migrations_to_apply = self.get_migrations_to_apply(from_version, to_version)
            print('🦄 Migrations to apply', migrations_to_apply)
            for migration in migrations_to_apply:
                migration_class = migration['migration']
                migration_instance = migration_class()
                print(f"Applying migration {migration_instance.version}: {migration_instance.description}")
                migration_instance.up(conn)
                conn.execute("UPDATE db_version SET version = ?", (migration_instance.version,))