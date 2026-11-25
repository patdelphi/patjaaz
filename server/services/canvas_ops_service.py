"""程序说明：提供画布元素级增量 op 合并与基于 SQLite 事务的画布版本快照管理服务（C1 / C10）。"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any, Dict, List, Optional

from services.db_service import db_service

MAX_SNAPSHOTS_PER_CANVAS = 20


def apply_canvas_element_ops(
    existing_data: Optional[Dict[str, Any]],
    ops: List[Dict[str, Any]],
    incoming_files: Optional[Dict[str, Any]] = None,
    app_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """将元素级增量 op（upsert / delete / reorder）应用到现有画布数据，按版本号防旧写覆盖。"""
    base = dict(existing_data) if isinstance(existing_data, dict) else {}
    raw_elements = base.get("elements")
    elements: List[Dict[str, Any]] = (
        [dict(el) for el in raw_elements if isinstance(el, dict)]
        if isinstance(raw_elements, list)
        else []
    )
    index_by_id: Dict[str, int] = {
        str(el["id"]): idx for idx, el in enumerate(elements) if el.get("id")
    }

    for op_item in ops or []:
        if not isinstance(op_item, dict):
            continue
        op_kind = str(op_item.get("op") or "upsert").strip().lower()
        if op_kind == "delete":
            target_id = str(op_item.get("id") or (op_item.get("element") or {}).get("id") or "")
            if target_id and target_id in index_by_id:
                cur = elements[index_by_id[target_id]]
                cur["isDeleted"] = True
                cur["version"] = int(cur.get("version") or 1) + 1
                cur["updated"] = int(time.time() * 1000)
        elif op_kind == "upsert":
            elem = op_item.get("element")
            if not isinstance(elem, dict) or not elem.get("id"):
                continue
            eid = str(elem["id"])
            if eid in index_by_id:
                cur = elements[index_by_id[eid]]
                cur_ver = int(cur.get("version") or 0)
                inc_ver = int(elem.get("version") or 0)
                if inc_ver >= cur_ver:
                    elements[index_by_id[eid]] = dict(elem)
            else:
                index_by_id[eid] = len(elements)
                elements.append(dict(elem))
        elif op_kind == "reorder":
            order_ids = op_item.get("order_ids")
            if isinstance(order_ids, list) and order_ids:
                rank = {str(eid): i for i, eid in enumerate(order_ids)}
                elements.sort(
                    key=lambda item: rank.get(str(item.get("id") or ""), len(order_ids) + 1)
                )
                index_by_id = {
                    str(el["id"]): idx for idx, el in enumerate(elements) if el.get("id")
                }

    files_map = dict(base.get("files")) if isinstance(base.get("files"), dict) else {}
    if isinstance(incoming_files, dict):
        files_map.update(incoming_files)

    result: Dict[str, Any] = {
        **base,
        "elements": elements,
        "files": files_map,
    }
    if isinstance(app_state, dict):
        result["appState"] = app_state
    return result


class CanvasSnapshotService:
    """在 SQLite 显式事务中管理画布历史快照的创建、列举与回退恢复。"""

    def _ensure_table_in_tx(self, conn) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS canvas_snapshots (
                id TEXT PRIMARY KEY,
                canvas_id TEXT NOT NULL,
                note TEXT DEFAULT '',
                element_count INTEGER DEFAULT 0,
                data TEXT NOT NULL,
                thumbnail TEXT DEFAULT '',
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_canvas_snapshots_cid_time
            ON canvas_snapshots (canvas_id, created_at DESC)
            """
        )

    def _create_snapshot_sync(self, canvas_id: str, note: str = "") -> Dict[str, Any]:
        with db_service._sync_transaction() as conn:
            self._ensure_table_in_tx(conn)
            row = conn.execute(
                "SELECT data, thumbnail FROM canvases WHERE id = ?", (canvas_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"Canvas not found: {canvas_id}")
            raw_data = str(row["data"] or "{}")
            thumbnail = str(row["thumbnail"] or "")
            try:
                parsed = json.loads(raw_data)
            except Exception:
                parsed = {}
            elems = parsed.get("elements") if isinstance(parsed, dict) else []
            active_count = sum(
                1 for e in (elems or []) if isinstance(e, dict) and not e.get("isDeleted")
            )

            snap_id = f"snap_{uuid.uuid4().hex[:12]}"
            created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            conn.execute(
                """
                INSERT INTO canvas_snapshots (id, canvas_id, note, element_count, data, thumbnail, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (snap_id, canvas_id, note.strip()[:120], active_count, raw_data, thumbnail, created_at),
            )
            # 同一画布最多保留最近 MAX_SNAPSHOTS_PER_CANVAS 份快照
            conn.execute(
                """
                DELETE FROM canvas_snapshots
                WHERE canvas_id = ? AND id NOT IN (
                    SELECT id FROM canvas_snapshots
                    WHERE canvas_id = ?
                    ORDER BY created_at DESC, rowid DESC
                    LIMIT ?
                )
                """,
                (canvas_id, canvas_id, MAX_SNAPSHOTS_PER_CANVAS),
            )
            return {
                "id": snap_id,
                "canvas_id": canvas_id,
                "note": note.strip()[:120],
                "element_count": active_count,
                "created_at": created_at,
            }

    def _list_snapshots_sync(self, canvas_id: str) -> List[Dict[str, Any]]:
        with db_service._sync_transaction() as conn:
            self._ensure_table_in_tx(conn)
            rows = conn.execute(
                """
                SELECT id, canvas_id, note, element_count, thumbnail, created_at
                FROM canvas_snapshots
                WHERE canvas_id = ?
                ORDER BY created_at DESC, rowid DESC
                """,
                (canvas_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def _restore_snapshot_sync(self, canvas_id: str, snap_id: str) -> Dict[str, Any]:
        with db_service._sync_transaction() as conn:
            self._ensure_table_in_tx(conn)
            snap = conn.execute(
                "SELECT data, thumbnail FROM canvas_snapshots WHERE id = ? AND canvas_id = ?",
                (snap_id, canvas_id),
            ).fetchone()
            if snap is None:
                raise KeyError(f"Snapshot '{snap_id}' not found for canvas '{canvas_id}'")
            raw_data = str(snap["data"] or "{}")
            thumbnail = str(snap["thumbnail"] or "")
            updated = conn.execute(
                """
                UPDATE canvases
                SET data = ?, thumbnail = CASE WHEN ? != '' THEN ? ELSE thumbnail END,
                    updated_at = STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'NOW')
                WHERE id = ?
                """,
                (raw_data, thumbnail, thumbnail, canvas_id),
            )
            if updated.rowcount == 0:
                raise KeyError(f"Canvas not found: {canvas_id}")
            try:
                data_obj = json.loads(raw_data)
            except Exception:
                data_obj = {"elements": [], "files": {}}
            return {"id": canvas_id, "snapshot_id": snap_id, "data": data_obj}

    async def create_snapshot(self, canvas_id: str, note: str = "") -> Dict[str, Any]:
        return await asyncio.to_thread(self._create_snapshot_sync, canvas_id, note)

    async def list_snapshots(self, canvas_id: str) -> List[Dict[str, Any]]:
        return await asyncio.to_thread(self._list_snapshots_sync, canvas_id)

    async def restore_snapshot(self, canvas_id: str, snap_id: str) -> Dict[str, Any]:
        return await asyncio.to_thread(self._restore_snapshot_sync, canvas_id, snap_id)


canvas_snapshot_service = CanvasSnapshotService()
