"""程序说明：覆盖阶段 P3 元素级增量 op 同步（C1）、SQLite 事务快照回退（C10）与生成元素血缘谱系写入（C9）单元测试。"""
import json
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services.canvas_ops_service import (
    CanvasSnapshotService,
    apply_canvas_element_ops,
)
from services.db_service import DatabaseService
from tools.comfy_dynamic import build_tool


class StageP3OpsSnapshotsLineageTests(unittest.IsolatedAsyncioTestCase):
    def test_apply_canvas_element_ops_upserts_deletes_and_protects_newer_versions(self) -> None:
        """验证增量 op 支持 upsert/delete/reorder，且旧版本号不会倒退覆盖高版本元素。"""
        existing = {
            "elements": [
                {"id": "e1", "type": "rectangle", "x": 10, "y": 10, "version": 5, "isDeleted": False},
                {"id": "e2", "type": "text", "x": 20, "y": 20, "version": 2, "isDeleted": False},
            ],
            "files": {"f1": {"id": "f1", "dataURL": "/api/file/a.png"}},
        }
        merged = apply_canvas_element_ops(
            existing,
            [
                # 旧版本 v3 不覆盖 v5
                {"op": "upsert", "element": {"id": "e1", "type": "rectangle", "x": 999, "y": 10, "version": 3}},
                # 删除 e2
                {"op": "delete", "id": "e2"},
                # 新增 e3
                {"op": "upsert", "element": {"id": "e3", "type": "frame", "name": "Lane", "version": 1}},
                # 重排顺序：e3 放最底，e1 在上
                {"op": "reorder", "order_ids": ["e3", "e2", "e1"]},
            ],
            incoming_files={"f2": {"id": "f2", "dataURL": "/api/file/b.png"}},
        )
        elems = merged["elements"]
        self.assertEqual([e["id"] for e in elems], ["e3", "e2", "e1"])
        self.assertEqual(elems[2]["x"], 10)
        self.assertTrue(elems[1]["isDeleted"])
        self.assertIn("f2", merged["files"])

    async def test_canvas_snapshot_create_list_and_restore_in_sqlite_transaction(self) -> None:
        """验证画布版本快照在 SQLite 事务中创建、列出并回退恢复原画布状态。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_db = DatabaseService(os.path.join(tmpdir, "snap_test.db"))
            await temp_db.create_canvas("cv_snap_1", "快照测试画布")
            v1_data = {
                "elements": [{"id": "rect_v1", "type": "rectangle", "isDeleted": False}],
                "files": {},
            }
            await temp_db.save_canvas_data("cv_snap_1", json.dumps(v1_data), "/api/file/t1.png")

            snap_svc = CanvasSnapshotService()
            with patch("services.canvas_ops_service.db_service", temp_db):
                snap = await snap_svc.create_snapshot("cv_snap_1", note="初稿状态")
                self.assertEqual(snap["element_count"], 1)

                # 修改画布为 v2
                v2_data = {"elements": [], "files": {}}
                await temp_db.save_canvas_data("cv_snap_1", json.dumps(v2_data))

                snaps = await snap_svc.list_snapshots("cv_snap_1")
                self.assertEqual(len(snaps), 1)
                self.assertEqual(snaps[0]["note"], "初稿状态")

                restored = await snap_svc.restore_snapshot("cv_snap_1", snap["id"])
                self.assertEqual(len(restored["data"]["elements"]), 1)
                self.assertEqual(restored["data"]["elements"][0]["id"], "rect_v1")

    async def test_comfy_dynamic_writes_jaaz_lineage_into_generated_element_custom_data(self) -> None:
        """验证生成元素落盘时在 customData 中自动记录工作流名、提示词与父图列表血缘信息（C9）。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            ref_img = os.path.join(tmpdir, "parent_ref.png")
            with open(ref_img, "wb") as f:
                f.write(b"\x89PNG\r\n\x1a\n")

            wf_record = {
                "id": 918,
                "name": "image_edit_sensenova_u16",
                "display_name": "SenseNova 编辑",
                "capability": "i2i",
                "output_kind": "image",
                "seed_strategy": "fixed",
                "inputs": [
                    {"name": "image_1", "type": "image", "required": True, "node_id": "1", "node_input_name": "image"},
                    {"name": "prompt", "type": "string", "required": True, "node_id": "2", "node_input_name": "text"},
                ],
            }
            saved_payloads = []

            class _FakeRunner:
                def __init__(self, *args, **kwargs):
                    pass

                async def generate(self, ctx=None):
                    return [("image/png", 1024, 1024, "child_out.png")]

            tool_fn = build_tool(wf_record)
            with (
                patch("tools.comfy_dynamic.FILES_DIR", tmpdir),
                patch(
                    "tools.comfy_dynamic.comfy_instance_service.resolve_instance",
                    AsyncMock(return_value={"id": "i1", "base_url": "http://127.0.0.1:8188", "headers": {}, "max_concurrency": 1}),
                ),
                patch("tools.comfy_dynamic.comfy_instance_service.maybe_free_memory_on_family_switch", AsyncMock()),
                patch("tools.comfy_dynamic.upload_image", AsyncMock(return_value="jaaz/parent_ref.png")),
                patch("tools.comfy_dynamic.db_service.get_comfy_workflow", AsyncMock(return_value={"1": {"inputs": {"image": ""}}, "2": {"inputs": {"text": ""}}})),
                patch("tools.comfy_dynamic.db_service.create_job", AsyncMock()),
                patch("tools.comfy_dynamic.db_service.update_job_status", AsyncMock()),
                patch("tools.comfy_dynamic.db_service.get_canvas_data", AsyncMock(return_value={"data": {"elements": [], "files": {}}})),
                patch("tools.comfy_dynamic.db_service.save_canvas_data", AsyncMock(side_effect=lambda cid, s: saved_payloads.append(json.loads(s)))),
                patch("tools.comfy_dynamic.broadcast_session_update", AsyncMock()),
                patch("tools.comfy_dynamic.ComfyUIWorkflowRunner", _FakeRunner),
            ):
                await tool_fn.ainvoke(
                    {
                        "name": "image_edit_sensenova_u16",
                        "args": {"image_1": "parent_ref.png", "prompt": "右下角添置暖光灯笼"},
                        "id": "tc_lin_1",
                        "type": "tool_call",
                    },
                    config={"configurable": {"canvas_id": "cv_lin", "session_id": "s_lin"}},
                )

            el = saved_payloads[0]["elements"][0]
            lineage = el["customData"]["jaazLineage"]
            self.assertEqual(lineage["workflowName"], "image_edit_sensenova_u16")
            self.assertEqual(lineage["parentFileIds"], ["parent_ref.png"])
            self.assertEqual(lineage["prompt"], "右下角添置暖光灯笼")


if __name__ == "__main__":
    unittest.main()
