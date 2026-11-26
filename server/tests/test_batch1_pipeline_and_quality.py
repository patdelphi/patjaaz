"""程序说明：回归验证工作流采样参数修复（CFG=1）、上传 SHA-256 缓存过期自动重传重试及音频输出写入画布能力。"""
import json
import os
import pathlib
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from services.comfy_instance_service import ComfyInstanceService
from services.job_recovery import append_outputs_to_canvas
from services.langgraph_service.canvas_context import build_canvas_scene_context
from tools.comfy_dynamic import build_tool, is_stale_upload_execution_error


class Batch1PipelineAndQualityTests(unittest.IsolatedAsyncioTestCase):
    """覆盖画质参数、上传缓存失效重试与音频元素落盘。"""

    def test_minimax_workflows_use_distilled_cfg_one_and_valid_scheduler_links(self) -> None:
        from services.comfy_workflow_pack import detect_api_json_issues, scan_workflows_dir

        repo_root = pathlib.Path(__file__).resolve().parents[2]
        wf_root = repo_root / "workflows"

        # 全量校验 workflows/ 目录下全部 17 套工作流包无解析错误、无断连节点
        scan_res = scan_workflows_dir(str(wf_root))
        self.assertEqual(scan_res["errors"], [])
        self.assertEqual(len(scan_res["valid"]), 17)
        for pack in scan_res["valid"]:
            issues = detect_api_json_issues(pack["api_json"])
            self.assertEqual(issues["missing_class_type_nodes"], [], pack["config_json"]["name"])
            self.assertEqual(issues["broken_links"], [], pack["config_json"]["name"])

        # 1) 文生图：4.0 MP + CFG=1 + 8步 + 内置 PE 默认开启
        t2i_api = json.loads((wf_root / "text2image_minimax_h3" / "workflow.api.json").read_text(encoding="utf-8"))
        t2i_meta = json.loads((wf_root / "text2image_minimax_h3" / "jaaz.workflow.json").read_text(encoding="utf-8"))
        self.assertEqual(t2i_api["23:7"]["inputs"]["cfg"], 1)
        self.assertEqual(t2i_api["23:7"]["inputs"]["steps"], 8)
        self.assertEqual(t2i_api["14"]["inputs"]["megapixels"], 4.0)
        self.assertEqual(t2i_api["23:2"]["inputs"]["clip_name"], "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors")
        self.assertTrue(t2i_api["23:22"]["inputs"]["switch"])
        mp_param = next(p for p in t2i_meta["inputs"] if p["name"] == "megapixels")
        enh_param = next(p for p in t2i_meta["inputs"] if p["name"] == "enable_prompt_enhancer")
        self.assertEqual(mp_param["default_value"], 4.0)
        self.assertTrue(enh_param["default_value"])

        # 2) 多参考图编辑：4.0 MP + CFG=1 + 8步 + 内置纯文本 PE 锁定关闭且不暴露给 Agent
        i2i_api = json.loads((wf_root / "image_edit_multiref_minimax_h3" / "workflow.api.json").read_text(encoding="utf-8"))
        i2i_meta = json.loads((wf_root / "image_edit_multiref_minimax_h3" / "jaaz.workflow.json").read_text(encoding="utf-8"))
        self.assertEqual(i2i_api["23:7"]["inputs"]["cfg"], 1)
        self.assertEqual(i2i_api["23:7"]["inputs"]["steps"], 8)
        self.assertEqual(i2i_api["14"]["inputs"]["megapixels"], 4.0)
        self.assertFalse(i2i_api["23:22"]["inputs"]["switch"])
        self.assertNotIn("enable_prompt_enhancer", [p["name"] for p in i2i_meta["inputs"]])

        # 3) 首帧 / 首尾帧 / 文生视频：统一 0.98 MP (768p) + 8步 Turbo LoRA 开启，且已移除孤立节点 119/120
        for fl_name in ("image2video_first_frame_minimax_h3", "image2video_first_last_frame_minimax_h3"):
            fl_api = json.loads((wf_root / fl_name / "workflow.api.json").read_text(encoding="utf-8"))
            self.assertNotIn("119", fl_api)
            self.assertNotIn("120", fl_api)
            self.assertEqual(fl_api["115"]["inputs"]["megapixels"], 0.98)
            self.assertTrue(fl_api["105:126"]["inputs"]["value"])

        # 4) 双图 FL2VA Turbo：轻量 nvfp4 CLIP + LoRA 强度 1.0 + <Picture N> 标签
        dual_api = json.loads((wf_root / "ref2video_dual_minimax_h3_fl2va_turbo" / "workflow.api.json").read_text(encoding="utf-8"))
        self.assertEqual(dual_api["92"]["inputs"]["clip_name"], "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors")
        self.assertEqual(dual_api["105"]["inputs"]["strength_model"], 1.0)

        # 5) Ref2VA：BasicScheduler 接开关输出 141 + normal 调度器 + 4步 v0.1 LoRA 默认关闭（20步高保真）
        ref2v_api = json.loads((wf_root / "ref2video_minimax_h3_ref2va" / "workflow.api.json").read_text(encoding="utf-8"))
        self.assertEqual(ref2v_api["124"]["inputs"]["model"], ["141", 0])
        self.assertEqual(ref2v_api["124"]["inputs"]["scheduler"], "normal")
        self.assertFalse(ref2v_api["146"]["inputs"]["value"])

        # 6) 多模态 RF 参考视频：使用专用 ref2va 权重且无 intToFloat _O 节点
        rf_api = json.loads((wf_root / "ref2video_multimodal_minimax_h3_rf" / "workflow.api.json").read_text(encoding="utf-8"))
        self.assertEqual(rf_api["4"]["inputs"]["unet_name"], "minimax_h3_ref2va_pruned_int8_convrot.safetensors")
        self.assertNotIn("33", rf_api)

        # 7) SeedVR2 视频超分：默认 2.0 倍率且已移除断连的 ImageCompareKJ (106)
        up_api = json.loads((wf_root / "video_upscale_seedvr2_3b" / "workflow.api.json").read_text(encoding="utf-8"))
        self.assertNotIn("106", up_api)
        self.assertEqual(up_api["66:57"]["inputs"]["resize_type.multiplier"], 2.0)

        # 8) 所有视频工作流的 SaveVideo 输出前缀统一落入 video/ 目录
        for pack in scan_res["valid"]:
            if pack["config_json"]["output_kind"] == "video":
                save_nodes = [
                    nd for nd in pack["api_json"].values()
                    if isinstance(nd, dict) and nd.get("class_type") == "SaveVideo"
                ]
                self.assertGreaterEqual(len(save_nodes), 1, pack["config_json"]["name"])
                for sn in save_nodes:
                    prefix = str((sn.get("inputs") or {}).get("filename_prefix") or "")
                    self.assertTrue(
                        prefix.startswith("video/"),
                        f"{pack['config_json']['name']} SaveVideo prefix '{prefix}' must start with 'video/'",
                    )

    def test_upload_cache_invalidation_and_stale_error_detection(self) -> None:
        svc = ComfyInstanceService()
        svc.set_cached_upload("colab|https://x", "sha_a", "remote_a.png")
        svc.set_cached_upload("colab|https://x", "sha_b", "remote_b.png")
        svc.set_cached_upload("other|http://y", "sha_c", "remote_c.png")

        self.assertEqual(svc.invalidate_cached_upload("colab|https://x", "sha_a"), 1)
        self.assertIsNone(svc.get_cached_upload("colab|https://x", "sha_a"))
        self.assertEqual(svc.get_cached_upload("colab|https://x", "sha_b"), "remote_b.png")

        self.assertEqual(svc.invalidate_cached_upload("colab|https://x"), 1)
        self.assertIsNone(svc.get_cached_upload("colab|https://x", "sha_b"))
        self.assertEqual(svc.get_cached_upload("other|http://y", "sha_c"), "remote_c.png")

        self.assertTrue(
            is_stale_upload_execution_error(
                "Invalid image file: remote_a.png", ["remote_a.png"]
            )
        )
        self.assertFalse(
            is_stale_upload_execution_error("CUDA out of memory", ["remote_a.png"])
        )

    async def test_stale_cached_upload_automatically_reuploads_and_retries_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            sample_img = pathlib.Path(tmp_dir) / "ref_local.png"
            sample_img.write_bytes(b"\x89PNG\r\n\x1a\nfakeimagebytes")

            wf_record = {
                "id": 901,
                "name": "mock_i2i_wf",
                "description": "Mock I2I",
                "capability": "i2i",
                "seed_strategy": "fixed",
                "inputs": [
                    {
                        "name": "ref_img",
                        "type": "image",
                        "required": True,
                        "node_id": "10",
                        "node_input_name": "image",
                        "default_value": "",
                    }
                ],
            }
            base_api = {"10": {"class_type": "LoadImage", "inputs": {"image": ""}}}

            fake_svc = ComfyInstanceService()
            sha_hex = fake_svc.compute_bytes_sha256(sample_img.read_bytes())
            cache_key = "inst1|http://comfy.test"
            fake_svc.set_cached_upload(cache_key, sha_hex, "stale_remote_01.png")

            fake_svc.resolve_instance = AsyncMock(
                return_value={
                    "id": "inst1",
                    "base_url": "http://comfy.test",
                    "headers": {},
                    "max_concurrency": 1,
                }
            )

            seen_workflows = []

            class FakeRunner:
                def __init__(self, wf_dict, *args, **kwargs):
                    seen_workflows.append(wf_dict)

                async def generate(self, ctx=None):
                    if len(seen_workflows) == 1:
                        raise RuntimeError("Invalid image file: stale_remote_01.png")
                    return [("audio/wav", 0, 0, "tts_out.wav")]

            saved_canvas_payloads = []
            broadcasts = []

            async def fake_save_canvas(cid, data_str):
                saved_canvas_payloads.append((cid, json.loads(data_str)))
                return True

            async def fake_broadcast(sid, cid, payload):
                broadcasts.append((sid, cid, payload))

            with (
                patch("tools.comfy_dynamic.FILES_DIR", tmp_dir),
                patch("tools.comfy_dynamic.comfy_instance_service", fake_svc),
                patch("tools.comfy_dynamic.upload_image", AsyncMock(return_value="fresh_remote_02.png")) as mock_upload,
                patch("tools.comfy_dynamic.ComfyUIWorkflowRunner", FakeRunner),
                patch("tools.comfy_dynamic.db_service.get_comfy_workflow", AsyncMock(return_value=base_api)),
                patch("tools.comfy_dynamic.db_service.create_job", AsyncMock()),
                patch("tools.comfy_dynamic.db_service.update_job_status", AsyncMock()),
                patch("tools.comfy_dynamic.db_service.get_canvas_data", AsyncMock(return_value={"data": {"elements": [], "files": {}}})),
                patch("tools.comfy_dynamic.db_service.save_canvas_data", side_effect=fake_save_canvas),
                patch("tools.comfy_dynamic.broadcast_session_update", side_effect=fake_broadcast),
            ):
                lc_tool = build_tool(wf_record)
                tool_msg = await lc_tool.ainvoke(
                    {
                        "name": "mock_i2i_wf",
                        "args": {"ref_img": "ref_local.png"},
                        "id": "tc_1",
                        "type": "tool_call",
                    },
                    config={"configurable": {"canvas_id": "cv_audio_1", "session_id": "sess_1"}},
                )
                result = tool_msg.content if hasattr(tool_msg, "content") else str(tool_msg)

            self.assertEqual(mock_upload.await_count, 1)
            self.assertEqual(len(seen_workflows), 2)
            self.assertEqual(seen_workflows[0]["10"]["inputs"]["image"], "stale_remote_01.png")
            self.assertEqual(seen_workflows[1]["10"]["inputs"]["image"], "fresh_remote_02.png")
            self.assertEqual(
                fake_svc.get_cached_upload(cache_key, sha_hex), "fresh_remote_02.png"
            )

            self.assertIn("tts_out.wav", result)
            self.assertEqual(len(saved_canvas_payloads), 1)
            saved_elements = saved_canvas_payloads[0][1]["elements"]
            self.assertEqual(len(saved_elements), 1)
            self.assertEqual(saved_elements[0]["type"], "audio")
            self.assertEqual(saved_elements[0]["link"], "/api/file/tts_out.wav")
            self.assertEqual(broadcasts[0][2]["type"], "audio_generated")

            scene_ctx = build_canvas_scene_context(saved_canvas_payloads[0][1])
            self.assertIn('画布音频#1: file_id="tts_out.wav"', scene_ctx)

    async def test_job_recovery_persists_and_broadcasts_audio_outputs(self) -> None:
        saved = []
        broadcasts = []
        with (
            patch("services.job_recovery.db_service.get_canvas_data", AsyncMock(return_value={"data": {"elements": [], "files": {}}})),
            patch("services.job_recovery.db_service.save_canvas_data", AsyncMock(side_effect=lambda cid, s: saved.append(json.loads(s)))),
            patch("services.job_recovery.broadcast_session_update", AsyncMock(side_effect=lambda sid, cid, p: broadcasts.append(p))),
        ):
            added = await append_outputs_to_canvas(
                "cv_rec", "sess_rec", [("audio/mpeg", 0, 0, "recovered_voice.mp3")]
            )
        self.assertEqual(added, 1)
        self.assertEqual(saved[0]["elements"][0]["type"], "audio")
        self.assertEqual(broadcasts[0]["type"], "audio_generated")
        self.assertEqual(broadcasts[0]["audio_url"], "/api/file/recovered_voice.mp3")

    async def test_video_input_uploads_to_root_subfolder_for_loadvideo_combo(self) -> None:
        """验证 type=video 的输入文件以空 subfolder 上传到 input 根目录，避免 LoadVideo COMBO 校验报错。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            sample_vid = os.path.join(tmpdir, "clip_v1.mp4")
            with open(sample_vid, "wb") as f:
                f.write(b"\x00\x00\x00\x18ftypmp42")

            fake_svc = ComfyInstanceService()
            wf_record = {
                "id": 914,
                "name": "video_upscale_seedvr2_3b",
                "capability": "upscale",
                "output_kind": "video",
                "seed_strategy": "fixed",
                "description": "Upscale video",
                "inputs": [
                    {
                        "name": "source_video",
                        "type": "video",
                        "required": True,
                        "node_id": "73",
                        "node_input_name": "file",
                    }
                ],
            }
            base_api = {"73": {"class_type": "LoadVideo", "inputs": {"file": ""}}}
            seen_uploads = []
            seen_workflows = []

            async def _fake_upload(stream, base_url, filename=None, subfolder="jaaz", headers=None):
                seen_uploads.append((filename, subfolder))
                return f"{subfolder}/{filename}" if subfolder else str(filename)

            class _FakeRunner:
                def __init__(self, wf_dict, *args, **kwargs):
                    seen_workflows.append(wf_dict)

                async def generate(self, ctx=None):
                    return [("video/mp4", 1920, 1080, "upscaled_out.mp4")]

            tool_fn = build_tool(wf_record)
            with (
                patch("tools.comfy_dynamic.FILES_DIR", tmpdir),
                patch("tools.comfy_dynamic.comfy_instance_service", fake_svc),
                patch.object(
                    fake_svc,
                    "resolve_instance",
                    AsyncMock(
                        return_value={
                            "id": "inst_vid",
                            "base_url": "http://127.0.0.1:8188",
                            "headers": {},
                            "max_concurrency": 1,
                        }
                    ),
                ),
                patch("tools.comfy_dynamic.upload_image", AsyncMock(side_effect=_fake_upload)),
                patch("tools.comfy_dynamic.db_service.get_comfy_workflow", AsyncMock(return_value=base_api)),
                patch("tools.comfy_dynamic.db_service.create_job", AsyncMock()),
                patch("tools.comfy_dynamic.db_service.update_job_status", AsyncMock()),
                patch("tools.comfy_dynamic.db_service.get_canvas_data", AsyncMock(return_value={"data": {"elements": [], "files": {}}})),
                patch("tools.comfy_dynamic.db_service.save_canvas_data", AsyncMock()),
                patch("tools.comfy_dynamic.broadcast_session_update", AsyncMock()),
                patch("tools.comfy_dynamic.ComfyUIWorkflowRunner", _FakeRunner),
            ):
                await tool_fn.ainvoke(
                    {
                        "name": "video_upscale_seedvr2_3b",
                        "args": {"source_video": "clip_v1.mp4"},
                        "id": "tc_vid_up",
                        "type": "tool_call",
                    },
                    config={"configurable": {"canvas_id": "cv_v", "session_id": "s_v"}},
                )

            self.assertEqual(seen_uploads, [("clip_v1.mp4", "")])
            self.assertEqual(seen_workflows[0]["73"]["inputs"]["file"], "clip_v1.mp4")

    async def test_ws_connect_transient_reset_retries_and_falls_back_to_none(self) -> None:
        """验证反向代理 WebSocket 握手发生 ConnectionResetError 时自动重试并安全降级为 None（交由 /history 轮询）。"""
        from routers.comfyui_execution import WorkflowExecution

        wf_exec = WorkflowExecution(
            {"1": {"class_type": "SaveImage", "inputs": {}}},
            "https://colab.patdelphi.xyz",
            False,
            None,
            False,
            30.0,
        )
        with (
            patch("routers.comfyui_execution.websockets.connect", AsyncMock(side_effect=ConnectionResetError())),
            patch("routers.comfyui_execution.asyncio.sleep", AsyncMock()),
        ):
            await wf_exec.connect()
        self.assertIsNone(wf_exec.ws)


if __name__ == "__main__":
    unittest.main()
