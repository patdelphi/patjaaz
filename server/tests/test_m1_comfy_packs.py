"""程序说明：阶段 2 与阶段 3 回归测试，覆盖 SQLite v4 备份迁移、多实例反代/鉴权/取消联动及 workflows/ 成对工作流包与启停开关。"""
import copy
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from routers import root_router
from services import tool_service as tool_service_mod
from services.comfy_instance_service import (
    ComfyInstanceService,
    build_auth_headers,
    build_comfy_http_url,
    build_comfy_ws_url,
    mask_instance_record,
    merge_masked_instance_secret,
    normalize_comfy_base_url,
)
from services.comfy_workflow_pack import (
    WorkflowPackValidationError,
    build_export_pack,
    generate_draft_config,
    save_pack_to_workflows_dir,
    scan_workflows_dir,
    update_pack_enabled_flag,
    validate_workflow_pack,
)
from services.db_service import DatabaseService
from services.migrations.manager import CURRENT_VERSION, MigrationManager
from tools.comfy_dynamic import apply_workflow_inputs_and_seeds
from utils.path_security import PathSecurityError


SAMPLE_T2I_API = {
    "3": {
        "class_type": "KSampler",
        "inputs": {"seed": 123456, "steps": 20, "cfg": 7.0},
    },
    "6": {
        "class_type": "CLIPTextEncode",
        "_meta": {"title": "Positive Prompt"},
        "inputs": {"text": "a cat"},
    },
    "7": {
        "class_type": "CLIPTextEncode",
        "_meta": {"title": "Negative Prompt"},
        "inputs": {"text": "ugly"},
    },
    "9": {
        "class_type": "SaveImage",
        "inputs": {"filename_prefix": "out"},
    },
}

SAMPLE_T2I_CONFIG = {
    "schema_version": 1,
    "name": "test_t2i_pack",
    "display_name": "测试文生图工作流",
    "capability": "t2i",
    "output_kind": "image",
    "enabled": True,
    "instance_id": "",
    "seed_strategy": "random",
    "description": "根据正向提示词生成测试图像",
    "inputs": [
        {
            "name": "prompt",
            "type": "string",
            "required": True,
            "node_id": "6",
            "node_input_name": "text",
            "default_value": "",
            "description": "正向画面描述",
        }
    ],
}


def _create_v3_db_with_legacy_workflows(db_path: str) -> None:
    """构造一个真实 v3 数据库（含类似 MOSS 的存量工作流）用于验证自动备份与无损升版。"""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE db_version (version INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO db_version (version) VALUES (0)")
        MigrationManager().migrate(conn, 0, 3)
        conn.execute(
            """
            INSERT INTO comfy_workflows (id, name, api_json, description, inputs, outputs)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                5,
                "text2image_MOSS",
                json.dumps(SAMPLE_T2I_API),
                "MOSS T2I workflow",
                json.dumps(SAMPLE_T2I_CONFIG["inputs"]),
                None,
            ),
        )
        conn.execute(
            """
            INSERT INTO comfy_workflows (id, name, api_json, description, inputs, outputs)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                6,
                "ImageEdit_MOSS",
                json.dumps(SAMPLE_T2I_API),
                "MOSS Image Edit workflow",
                json.dumps(SAMPLE_T2I_CONFIG["inputs"]),
                None,
            ),
        )
        conn.commit()
    finally:
        conn.close()


class M1ComfyPacksTests(unittest.TestCase):
    def test_v3_to_v4_migration_creates_backup_and_preserves_workflows(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "localmanus.db")
            _create_v3_db_with_legacy_workflows(db_path)

            db = DatabaseService(db_path=db_path)
            backup_dir = os.path.join(tmp, "backups")
            self.assertTrue(os.path.isdir(backup_dir))
            backups = os.listdir(backup_dir)
            self.assertTrue(any("bak-v3-" in b for b in backups))

            conn = db._open_sync_connection()
            try:
                ver = conn.execute("SELECT version FROM db_version").fetchone()[0]
                self.assertEqual(int(ver), CURRENT_VERSION)
                tables = {
                    r[0]
                    for r in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
                self.assertIn("comfy_instances", tables)
                self.assertIn("jobs", tables)
            finally:
                conn.close()

            rows = db._list_comfy_workflows_sync()
            by_name = {r["name"]: r for r in rows}
            self.assertIn("text2image_MOSS", by_name)
            self.assertIn("ImageEdit_MOSS", by_name)
            self.assertEqual(by_name["text2image_MOSS"]["capability"], "t2i")
            self.assertEqual(by_name["ImageEdit_MOSS"]["capability"], "i2i")
            self.assertEqual(int(by_name["text2image_MOSS"]["enabled"]), 1)
            self.assertEqual(int(by_name["ImageEdit_MOSS"]["enabled"]), 1)

    def test_comfy_url_prefix_auth_headers_and_secret_masking(self):
        base = "https://gpu.example.com/comfy/"
        self.assertEqual(normalize_comfy_base_url(base), "https://gpu.example.com/comfy")
        self.assertEqual(
            build_comfy_http_url(base, "/prompt"),
            "https://gpu.example.com/comfy/prompt",
        )
        self.assertEqual(
            build_comfy_ws_url(base, "cid-42"),
            "wss://gpu.example.com/comfy/ws?clientId=cid-42",
        )

        self.assertEqual(
            build_auth_headers({"auth_type": "bearer", "auth_secret": "tok-abc"}),
            {"Authorization": "Bearer tok-abc"},
        )
        self.assertEqual(
            build_auth_headers({"auth_type": "basic", "auth_secret": "u:p"}),
            {"Authorization": "Basic dTpw"},
        )
        self.assertEqual(
            build_auth_headers(
                {
                    "auth_type": "header",
                    "auth_header_name": "X-Comfy-Key",
                    "auth_secret": "secret-1",
                }
            ),
            {"X-Comfy-Key": "secret-1"},
        )

        existing = {"id": "remote", "auth_secret": "super-secret-value-99"}
        masked = mask_instance_record(existing)
        self.assertNotIn("super-secret-value-99", masked["auth_secret"])
        kept = merge_masked_instance_secret(
            {"id": "remote", "auth_secret": masked["auth_secret"]}, existing
        )
        self.assertEqual(kept["auth_secret"], "super-secret-value-99")

    def test_workflow_pack_validation_draft_save_scan_export_and_seed_strategy(self):
        # 1. 必须拒绝 ComfyUI UI Graph JSON
        ui_graph = {"last_node_id": 10, "nodes": [{"id": 1}], "links": []}
        res_ui = validate_workflow_pack(ui_graph, SAMPLE_T2I_CONFIG)
        self.assertFalse(res_ui["valid"])
        self.assertTrue(any("Export (API)" in err for err in res_ui["errors"]))

        # 2. 必须拒绝不存在的 node_id 或 node_input_name
        bad_cfg = copy.deepcopy(SAMPLE_T2I_CONFIG)
        bad_cfg["inputs"][0]["node_id"] = "999"
        res_missing_node = validate_workflow_pack(SAMPLE_T2I_API, bad_cfg)
        self.assertFalse(res_missing_node["valid"])
        self.assertTrue(any("999" in err for err in res_missing_node["errors"]))

        # 3. 单 API JSON 自动生成草稿并可反向通过校验
        draft = generate_draft_config(SAMPLE_T2I_API, suggested_name="auto_t2i")
        self.assertEqual(draft["capability"], "t2i")
        self.assertEqual(draft["output_kind"], "image")
        self.assertTrue(validate_workflow_pack(SAMPLE_T2I_API, draft)["valid"])

        # 4. 目录安全保存、扫描（含子目录包+平铺对+坏文件容错）、写回 enabled
        with tempfile.TemporaryDirectory() as wf_dir:
            bad_name_cfg = copy.deepcopy(SAMPLE_T2I_CONFIG)
            bad_name_cfg["name"] = "../escape"
            with self.assertRaises(WorkflowPackValidationError):
                save_pack_to_workflows_dir(SAMPLE_T2I_API, bad_name_cfg, wf_dir)

            saved = save_pack_to_workflows_dir(SAMPLE_T2I_API, SAMPLE_T2I_CONFIG, wf_dir)
            self.assertEqual(saved["source_mode"], "pack_dir")
            self.assertTrue(os.path.isfile(saved["api_path"]))
            self.assertTrue(os.path.isfile(saved["config_path"]))

            # 再放置一个平铺成对格式
            flat_cfg = copy.deepcopy(SAMPLE_T2I_CONFIG)
            flat_cfg["name"] = "flat_pair_t2i"
            with open(os.path.join(wf_dir, "flat_pair_t2i.api.json"), "w", encoding="utf-8") as f:
                json.dump(SAMPLE_T2I_API, f)
            with open(os.path.join(wf_dir, "flat_pair_t2i.jaaz.json"), "w", encoding="utf-8") as f:
                json.dump(flat_cfg, f)

            # 再放置一个损坏目录，确保扫描不崩溃且能报出错误项
            broken_dir = os.path.join(wf_dir, "broken_wf")
            os.makedirs(broken_dir, exist_ok=True)
            with open(os.path.join(broken_dir, "workflow.api.json"), "w", encoding="utf-8") as f:
                f.write("{}")

            scanned = scan_workflows_dir(wf_dir)
            valid_names = {item["config_json"]["name"] for item in scanned["valid"]}
            self.assertEqual(valid_names, {"test_t2i_pack", "flat_pair_t2i"})
            self.assertEqual(len(scanned["errors"]), 1)

            self.assertTrue(update_pack_enabled_flag("test_t2i_pack", False, wf_dir))
            with open(saved["config_path"], "r", encoding="utf-8") as f:
                self.assertFalse(json.load(f)["enabled"])

        # 5. 导出旧记录格式 & seed_strategy='fixed' 保持原 seed
        exported = build_export_pack(
            {
                "name": "text2image_MOSS",
                "display_name": "text2image_MOSS",
                "capability": "t2i",
                "output_kind": "image",
                "enabled": 1,
                "seed_strategy": "fixed",
                "description": "MOSS",
                "api_json": json.dumps(SAMPLE_T2I_API),
                "inputs": json.dumps(SAMPLE_T2I_CONFIG["inputs"]),
            }
        )
        self.assertEqual(exported["config_json"]["name"], "text2image_MOSS")
        fixed = apply_workflow_inputs_and_seeds(
            SAMPLE_T2I_API,
            SAMPLE_T2I_CONFIG["inputs"],
            {"prompt": "new prompt"},
            seed_strategy="fixed",
        )
        self.assertEqual(fixed["3"]["inputs"]["seed"], 123456)
        self.assertEqual(fixed["6"]["inputs"]["text"], "new prompt")


class M1ComfyPacksAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_session_prompts_calls_queue_delete_and_interrupt(self):
        svc = ComfyInstanceService()
        svc.register_active_prompt(
            "sess-cancel-1",
            "https://gpu.example.com/comfy/",
            "prompt-88",
            headers={"Authorization": "Bearer secret-tok"},
            instance_id="gpu-1",
        )

        called: list[tuple[str, dict, dict]] = []

        class _Resp:
            status_code = 200

        class _FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def post(self, url, json=None, headers=None):
                called.append((url, json or {}, headers or {}))
                return _Resp()

        with patch("services.comfy_instance_service.HttpClient.create", return_value=_FakeClient()):
            res = await svc.cancel_session_prompts("sess-cancel-1")

        self.assertEqual(len(res), 1)
        self.assertTrue(res[0]["queue_deleted"])
        self.assertTrue(res[0]["interrupted"])
        self.assertEqual(called[0][0], "https://gpu.example.com/comfy/queue")
        self.assertEqual(called[0][1], {"delete": ["prompt-88"]})
        self.assertEqual(called[1][0], "https://gpu.example.com/comfy/interrupt")
        self.assertEqual(called[1][1], {"prompt_id": "prompt-88"})
        self.assertEqual(called[1][2], {"Authorization": "Bearer secret-tok"})

    async def test_disabled_workflow_excluded_from_agent_tools_and_output_kind_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = DatabaseService(db_path=os.path.join(tmp, "tools.db"))
            enabled_img_id = await db.create_comfy_workflow(
                name="wf_img_enabled",
                api_json=json.dumps(SAMPLE_T2I_API),
                description="Enabled image workflow",
                inputs=json.dumps(SAMPLE_T2I_CONFIG["inputs"]),
                capability="t2i",
                output_kind="image",
                enabled=1,
            )
            disabled_id = await db.create_comfy_workflow(
                name="wf_disabled",
                api_json=json.dumps(SAMPLE_T2I_API),
                description="Disabled workflow",
                inputs=json.dumps(SAMPLE_T2I_CONFIG["inputs"]),
                capability="t2i",
                output_kind="image",
                enabled=0,
            )
            audio_id = await db.create_comfy_workflow(
                name="wf_tts_audio",
                api_json=json.dumps(SAMPLE_T2I_API),
                description="Audio TTS workflow",
                inputs=json.dumps(SAMPLE_T2I_CONFIG["inputs"]),
                display_name="中文配音",
                capability="tts",
                output_kind="audio",
                enabled=1,
            )
            self.assertGreater(enabled_img_id, 0)
            self.assertGreater(audio_id, 0)

            tool_service_mod.tool_service.clear_tools()
            with patch.object(tool_service_mod, "db_service", db):
                await tool_service_mod.register_comfy_tools()

            tools = tool_service_mod.tool_service.get_all_tools()
            self.assertIn("comfyui_wf_img_enabled", tools)
            self.assertNotIn("comfyui_wf_disabled", tools)
            self.assertIn("comfyui_wf_tts_audio", tools)
            self.assertEqual(tools["comfyui_wf_tts_audio"]["type"], "audio")
            self.assertEqual(tools["comfyui_wf_tts_audio"]["capability"], "tts")

            available = root_router.filter_available_tools(
                tools, {"comfyui": {"url": "http://127.0.0.1:8188"}}
            )
            available_ids = {t["id"] for t in available}
            self.assertEqual(
                available_ids, {"comfyui_wf_img_enabled", "comfyui_wf_tts_audio"}
            )

            # 切换关闭后再次刷新，Agent 侧立即可见变化
            await db.set_comfy_workflow_enabled(enabled_img_id, False)
            tool_service_mod.tool_service.clear_tools()
            with patch.object(tool_service_mod, "db_service", db):
                await tool_service_mod.register_comfy_tools()
            self.assertNotIn(
                "comfyui_wf_img_enabled",
                tool_service_mod.tool_service.get_all_tools(),
            )
            tool_service_mod.tool_service.clear_tools()


if __name__ == "__main__":
    unittest.main()
