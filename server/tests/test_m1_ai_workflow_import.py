"""程序说明：验证 AI Agent 工作流摘要、内置 LLM 自动解析与二次纠错、目录热同步及 workflow_cli.py 端到端流程。"""
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage

SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from routers import comfyui_router
from services import tool_service as tool_service_mod
from services.comfy_workflow_ai_importer import (
    auto_import_new_source_workflows,
    extract_json_from_llm_text,
    generate_workflow_config_with_ai,
)
from services.comfy_workflow_pack import (
    WORKFLOWS_DIR,
    compute_file_sha256,
    repair_missing_primitive_nodes,
    scan_source_workflows_dir,
    scan_workflows_dir,
    summarize_api_json_for_agent,
    sync_workflows_dir_to_db,
    validate_api_json,
    validate_workflow_pack,
)
from services.db_service import DatabaseService
from tools.comfy_dynamic import (
    apply_workflow_inputs_and_seeds,
    build_tool,
    resolve_comfy_input_media_path,
)
from utils.path_security import PathSecurityError


SAMPLE_MOSS_LIKE_API = {
    "6": {
        "class_type": "CLIPTextEncode",
        "_meta": {"title": "Positive Prompt"},
        "inputs": {"text": "a serene mountain lake", "clip": ["4", 1]},
    },
    "19": {
        "class_type": "MOSSImageAspectRatio",
        "_meta": {"title": "Aspect Ratio"},
        "inputs": {"aspect_ratio": "1:1 (Square)", "megapixels": 4},
    },
    "9": {
        "class_type": "SaveImage",
        "inputs": {"filename_prefix": "moss/out", "images": ["8", 0]},
    },
}

SAMPLE_OBJECT_INFO = {
    "MOSSImageAspectRatio": {
        "input": {
            "required": {
                "aspect_ratio": [["1:1 (Square)", "16:9 (Widescreen)", "9:16 (Portrait)"]],
                "megapixels": ["INT", {"default": 4, "min": 1, "max": 8}],
            }
        }
    }
}


class M1AiWorkflowImportTests(unittest.TestCase):
    def test_summarize_filters_links_and_enriches_object_info_options(self):
        summary = summarize_api_json_for_agent(
            SAMPLE_MOSS_LIKE_API, object_info=SAMPLE_OBJECT_INFO
        )
        self.assertEqual(summary["node_count"], 3)
        by_id = {n["node_id"]: n for n in summary["nodes"]}

        # 连线 [4, 1] 与 [8, 0] 必须被过滤，只保留直接配置输入
        self.assertNotIn("clip", by_id["6"]["literal_inputs"])
        self.assertIn("text", by_id["6"]["literal_inputs"])
        self.assertNotIn("images", by_id["9"]["literal_inputs"])

        ratio_input = by_id["19"]["literal_inputs"]["aspect_ratio"]
        self.assertEqual(ratio_input["input_type"], "enum")
        self.assertEqual(
            ratio_input["options"],
            ["1:1 (Square)", "16:9 (Widescreen)", "9:16 (Portrait)"],
        )

    def test_extract_json_from_llm_text(self):
        fenced = '好的，生成配置如下：\n```json\n{"schema_version": 1, "name": "demo"}\n```\n说明结束。'
        self.assertEqual(extract_json_from_llm_text(fenced), {"schema_version": 1, "name": "demo"})

    def test_workflow_cli_end_to_end_inspect_validate_install_toggle(self):
        cli_path = os.path.join(SERVER_DIR, "scripts", "workflow_cli.py")
        with tempfile.TemporaryDirectory() as tmp:
            api_file = os.path.join(tmp, "moss.api.json")
            cfg_file = os.path.join(tmp, "moss.jaaz.json")
            bad_cfg_file = os.path.join(tmp, "bad.jaaz.json")
            wf_dir = os.path.join(tmp, "workflows")
            db_file = os.path.join(tmp, "cli_test.db")

            with open(api_file, "w", encoding="utf-8") as f:
                json.dump(SAMPLE_MOSS_LIKE_API, f)

            valid_cfg = {
                "schema_version": 1,
                "name": "cli_moss_t2i",
                "display_name": "CLI MOSS 文生图",
                "capability": "t2i",
                "output_kind": "image",
                "enabled": True,
                "description": "通过 CLI 导入的 MOSS 文生图工作流",
                "inputs": [
                    {
                        "name": "positive_prompt",
                        "type": "string",
                        "required": True,
                        "node_id": "6",
                        "node_input_name": "text",
                        "default_value": "",
                        "description": "正向画面描述",
                    },
                    {
                        "name": "aspect_ratio",
                        "type": "enum",
                        "required": True,
                        "node_id": "19",
                        "node_input_name": "aspect_ratio",
                        "default_value": "1:1 (Square)",
                        "options": ["1:1 (Square)", "16:9 (Widescreen)"],
                        "description": "画幅比例枚举",
                    },
                ],
            }
            with open(cfg_file, "w", encoding="utf-8") as f:
                json.dump(valid_cfg, f)

            bad_cfg = copy.deepcopy(valid_cfg)
            bad_cfg["inputs"][0]["node_id"] = "404"
            with open(bad_cfg_file, "w", encoding="utf-8") as f:
                json.dump(bad_cfg, f)

            def _run_cli(*cli_args: str) -> subprocess.CompletedProcess:
                return subprocess.run(
                    [
                        sys.executable,
                        cli_path,
                        "--db-path",
                        db_file,
                        "--workflows-dir",
                        wf_dir,
                        *cli_args,
                    ],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                )

            # 1. inspect
            r_inspect = _run_cli("inspect", api_file)
            self.assertEqual(r_inspect.returncode, 0, r_inspect.stderr)
            inspected = json.loads(r_inspect.stdout)
            self.assertEqual(inspected["node_count"], 3)

            # 2. validate 失败用例 & 成功用例
            r_bad = _run_cli("validate", api_file, bad_cfg_file)
            self.assertNotEqual(r_bad.returncode, 0)
            self.assertIn("404", r_bad.stderr)

            r_ok = _run_cli("validate", api_file, cfg_file)
            self.assertEqual(r_ok.returncode, 0, r_ok.stderr)

            # 3. install -> list -> disable -> enable
            r_inst = _run_cli("install", api_file, cfg_file)
            self.assertEqual(r_inst.returncode, 0, r_inst.stderr)
            inst_data = json.loads(r_inst.stdout)
            self.assertTrue(inst_data["success"])
            self.assertTrue(os.path.isfile(inst_data["config_path"]))

            r_dis = _run_cli("disable", "cli_moss_t2i")
            self.assertEqual(r_dis.returncode, 0, r_dis.stderr)
            with open(inst_data["config_path"], "r", encoding="utf-8") as f:
                self.assertFalse(json.load(f)["enabled"])

            r_list = _run_cli("list")
            self.assertEqual(r_list.returncode, 0, r_list.stderr)
            items = json.loads(r_list.stdout)
            self.assertEqual(len(items), 1)
            self.assertFalse(items[0]["enabled"])


class M1AiWorkflowImportAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_ai_importer_auto_repairs_invalid_node_id_and_preserves_enum(self):
        broken_first_reply = {
            "schema_version": 1,
            "name": "moss_ai_wf",
            "display_name": "MOSS AI 导入",
            "capability": "t2i",
            "output_kind": "image",
            "enabled": True,
            "description": "AI 生成的描述",
            "inputs": [
                {
                    "name": "positive_prompt",
                    "type": "string",
                    "required": True,
                    "node_id": "999",
                    "node_input_name": "text",
                    "default_value": "",
                    "description": "错误的节点编号测试自纠",
                }
            ],
        }
        repaired_second_reply = {
            "schema_version": 1,
            "name": "moss_ai_wf",
            "display_name": "MOSS AI 导入",
            "capability": "t2i",
            "output_kind": "image",
            "enabled": True,
            "description": "使用 MOSS 生成高清图像",
            "inputs": [
                {
                    "name": "positive_prompt",
                    "type": "string",
                    "required": True,
                    "node_id": "6",
                    "node_input_name": "text",
                    "default_value": "",
                    "description": "正向画面描述",
                },
                {
                    "name": "aspect_ratio",
                    "type": "enum",
                    "required": True,
                    "node_id": "19",
                    "node_input_name": "aspect_ratio",
                    "default_value": "1:1 (Square)",
                    "options": ["1:1 (Square)", "16:9 (Widescreen)", "9:16 (Portrait)"],
                    "description": "画幅比例",
                },
            ],
        }

        fake_chat = AsyncMock()
        fake_chat.ainvoke = AsyncMock(
            side_effect=[
                AIMessage(content=f"```json\n{json.dumps(broken_first_reply)}\n```"),
                AIMessage(content=json.dumps(repaired_second_reply)),
            ]
        )

        res = await generate_workflow_config_with_ai(
            SAMPLE_MOSS_LIKE_API,
            user_hint="只暴露提示词和比例",
            chat_model=fake_chat,
            object_info=SAMPLE_OBJECT_INFO,
        )
        self.assertTrue(res["repaired"])
        self.assertTrue(res["used_object_info"])
        self.assertEqual(res["config_json"]["name"], "moss_ai_wf")
        self.assertEqual(res["config_json"]["inputs"][1]["options"][0], "1:1 (Square)")
        self.assertEqual(fake_chat.ainvoke.await_count, 2)
        second_call_msgs = fake_chat.ainvoke.await_args_list[1].args[0]
        self.assertIn("999", second_call_msgs[-1].content)

    async def test_sync_workflows_dir_and_list_route_preserve_existing_db_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = DatabaseService(db_path=os.path.join(tmp, "sync.db"))
            await db.create_comfy_workflow(
                name="legacy_db_wf",
                api_json=json.dumps(SAMPLE_MOSS_LIKE_API),
                description="legacy",
                inputs="[]",
                source_mode="db",
                enabled=1,
            )

            wf_dir = os.path.join(tmp, "workflows", "agent_added")
            os.makedirs(wf_dir, exist_ok=True)
            with open(os.path.join(wf_dir, "workflow.api.json"), "w", encoding="utf-8") as f:
                json.dump(SAMPLE_MOSS_LIKE_API, f)
            with open(os.path.join(wf_dir, "jaaz.workflow.json"), "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "schema_version": 1,
                        "name": "agent_added_wf",
                        "display_name": "Agent 放入工作流",
                        "capability": "t2i",
                        "output_kind": "image",
                        "enabled": True,
                        "description": "由外部 Agent 直接写入 workflows/ 的工作流",
                        "inputs": [],
                    },
                    f,
                )

            with (
                patch.object(comfyui_router, "db_service", db),
                patch.object(comfyui_router, "WORKFLOWS_DIR", os.path.join(tmp, "workflows")),
                patch.object(tool_service_mod, "db_service", db),
            ):
                resp = await comfyui_router.list_workflows_rich(auto_sync=True)

            names = {w["name"]: w for w in resp["workflows"]}
            self.assertIn("legacy_db_wf", names)
            self.assertIn("agent_added_wf", names)
            self.assertEqual(names["legacy_db_wf"]["source_mode"], "db")
            self.assertEqual(names["agent_added_wf"]["source_mode"], "pack_dir")
            self.assertIn("comfyui_agent_added_wf", tool_service_mod.tool_service.get_all_tools())
            tool_service_mod.tool_service.clear_tools()

    async def test_source_dir_ignored_by_pack_scan_and_tracked_across_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            wf_dir = os.path.join(tmp, "workflows")
            src_dir = os.path.join(wf_dir, "source")
            os.makedirs(src_dir, exist_ok=True)

            # 1. 即使 workflows/source/ 里含原始 API JSON 与 .index.json，scan_workflows_dir 也必须忽略不报错
            raw_broken_primitive = {
                "10": {"class_type": "CLIPTextEncode", "inputs": {"text": ["7", 0]}},
                "7": {"inputs": {"UNKNOWN": "hello"}},
                "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "x", "images": ["10", 0]}},
            }
            # 确认未修复时 validate_api_json 拦截坏节点
            self.assertTrue(validate_api_json(raw_broken_primitive))

            repaired, notes = repair_missing_primitive_nodes(raw_broken_primitive)
            self.assertEqual(repaired["7"]["class_type"], "PrimitiveStringMultiline")
            self.assertEqual(validate_api_json(repaired), [])
            self.assertTrue(notes)

            src_file = os.path.join(src_dir, "demo_source.json")
            with open(src_file, "w", encoding="utf-8") as f:
                json.dump(raw_broken_primitive, f)
            with open(os.path.join(src_dir, ".index.json"), "w", encoding="utf-8") as f:
                f.write("{}")
            with open(os.path.join(src_dir, "ui_graph.json"), "w", encoding="utf-8") as f:
                json.dump({"last_node_id": 2, "nodes": [{"id": 1}], "links": []}, f)

            pack_scan = scan_workflows_dir(wf_dir)
            self.assertEqual(pack_scan["errors"], [])

            # 2. scan_source_workflows_dir 识别 new / invalid 并忽略 .index.json
            src_scan = scan_source_workflows_dir(source_dir=src_dir, workflows_dir=wf_dir)
            self.assertEqual([i["filename"] for i in src_scan["new"]], ["demo_source.json"])
            self.assertEqual([i["filename"] for i in src_scan["invalid"]], ["ui_graph.json"])

            # 3. 无可用 LLM 时优雅跳过，不抛错
            db = DatabaseService(db_path=os.path.join(tmp, "auto_src.db"))
            with patch(
                "services.comfy_workflow_ai_importer.select_available_text_model",
                side_effect=RuntimeError("未配置文本大模型"),
            ):
                skip_res = await auto_import_new_source_workflows(
                    source_dir=src_dir, workflows_dir=wf_dir, db=db
                )
            self.assertEqual(skip_res["imported"], [])
            self.assertEqual(skip_res["skipped_no_llm"], ["demo_source.json"])

            # 4. 注入 Mock LLM 后自动修复导入、落盘与入库，且二次运行幂等不重复导入
            mock_cfg = {
                "schema_version": 1,
                "name": "auto_repaired_demo",
                "display_name": "自动修复测试工作流",
                "capability": "t2i",
                "output_kind": "image",
                "enabled": True,
                "description": "自动修复并导入的测试工作流",
                "inputs": [
                    {
                        "name": "positive_prompt",
                        "type": "string",
                        "required": True,
                        "node_id": "7",
                        "node_input_name": "value",
                        "default_value": "",
                        "description": "正向提示词",
                    }
                ],
            }
            fake_chat = AsyncMock()
            fake_chat.ainvoke = AsyncMock(
                return_value=AIMessage(content=json.dumps(mock_cfg))
            )
            imp_res = await auto_import_new_source_workflows(
                source_dir=src_dir,
                workflows_dir=wf_dir,
                db=db,
                chat_model=fake_chat,
                object_info={},
            )
            self.assertEqual(len(imp_res["imported"]), 1)
            self.assertEqual(imp_res["imported"][0]["name"], "auto_repaired_demo")

            second_res = await auto_import_new_source_workflows(
                source_dir=src_dir,
                workflows_dir=wf_dir,
                db=db,
                chat_model=fake_chat,
                object_info={},
            )
            self.assertEqual(second_res["imported"], [])
            self.assertEqual(len(second_res["already_imported"]), 1)

            # 5. 修改源文件后应识别为 updated
            with open(src_file, "w", encoding="utf-8") as f:
                raw_broken_primitive["7"]["inputs"]["UNKNOWN"] = "updated hello"
                json.dump(raw_broken_primitive, f)
            upd_scan = scan_source_workflows_dir(source_dir=src_dir, workflows_dir=wf_dir)
            self.assertEqual([i["filename"] for i in upd_scan["updated"]], ["demo_source.json"])

    def test_optional_media_node_pruning_and_video_audio_resolution(self):
        # 测试视频/音频路径解析及防越界
        with tempfile.TemporaryDirectory() as files_dir:
            vid = os.path.join(files_dir, "clip_1.mp4")
            aud = os.path.join(files_dir, "voice_1.wav")
            with open(vid, "wb") as f:
                f.write(b"fake-mp4")
            with open(aud, "wb") as f:
                f.write(b"fake-wav")

            self.assertEqual(
                resolve_comfy_input_media_path("clip_1.mp4", files_dir, "video"), vid
            )
            self.assertEqual(
                resolve_comfy_input_media_path("/api/file/voice_1.wav", files_dir, "audio"),
                aud,
            )
            self.assertIsNone(
                resolve_comfy_input_media_path("None", files_dir, "audio")
            )
            with self.assertRaises(PathSecurityError):
                resolve_comfy_input_media_path("../escape.mp4", files_dir, "video")

        # 测试未传可选 LoadImage/LoadAudio 时自动裁剪下游连线和加载节点
        wf_api = {
            "10": {"class_type": "LoadImage", "inputs": {"image": "req.png"}},
            "11": {"class_type": "LoadImage", "inputs": {"image": "None"}},
            "16": {"class_type": "LoadAudio", "inputs": {"audio": "None"}},
            "26": {
                "class_type": "MiniMaxH3ReferenceToVideo",
                "inputs": {
                    "prompt": "run",
                    "ref_images.ref_image_0": ["10", 0],
                    "ref_images.ref_image_1": ["11", 0],
                    "ref_audios.ref_audio_0": ["16", 0],
                },
            },
        }
        input_defs = [
            {"name": "ref1", "type": "image", "required": True, "node_id": "10", "node_input_name": "image"},
            {"name": "ref2", "type": "image", "required": False, "node_id": "11", "node_input_name": "image"},
            {"name": "aud1", "type": "audio", "required": False, "node_id": "16", "node_input_name": "audio"},
        ]
        pruned = apply_workflow_inputs_and_seeds(
            wf_api, input_defs, {"ref1": "jaaz/real.png", "ref2": "", "aud1": None}
        )
        self.assertEqual(pruned["10"]["inputs"]["image"], "jaaz/real.png")
        self.assertNotIn("11", pruned)
        self.assertNotIn("16", pruned)
        self.assertIn("ref_images.ref_image_0", pruned["26"]["inputs"])
        self.assertNotIn("ref_images.ref_image_1", pruned["26"]["inputs"])
        self.assertNotIn("ref_audios.ref_audio_0", pruned["26"]["inputs"])

    def test_repo_installed_workflow_packs_validate_and_build_tools(self):
        scan = scan_workflows_dir(WORKFLOWS_DIR)
        self.assertEqual(scan["errors"], [])
        self.assertGreaterEqual(len(scan["valid"]), 10)
        for pack in scan["valid"]:
            cfg = pack["config_json"]
            val = validate_workflow_pack(pack["api_json"], cfg)
            self.assertTrue(val["valid"], f"{cfg['name']} failed validation: {val['errors']}")
            tool_obj = build_tool(
                {
                    "id": 100,
                    "name": cfg["name"],
                    "description": cfg["description"],
                    "inputs": cfg["inputs"],
                    "capability": cfg["capability"],
                    "output_kind": cfg["output_kind"],
                    "seed_strategy": cfg["seed_strategy"],
                    "instance_id": cfg.get("instance_id") or None,
                }
            )
            self.assertEqual(tool_obj.name, cfg["name"])

        cli_path = os.path.join(SERVER_DIR, "scripts", "workflow_cli.py")
        r_chk = subprocess.run(
            [sys.executable, cli_path, "check-source"],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(r_chk.returncode, 0, r_chk.stderr)
        payload = json.loads(r_chk.stdout)
        self.assertEqual(payload["new"], [])
        self.assertEqual(payload["invalid"], [])
        self.assertGreaterEqual(len(payload["already_imported"]), 10)


if __name__ == "__main__":
    unittest.main()
