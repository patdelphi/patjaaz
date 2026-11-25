"""程序说明：画布防重叠智能排版、实时场景上下文提取、空白画布创建、多智能体跨能力交接及修复后工作流包完整性单元测试。"""
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

SERVER_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVER_DIR.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from routers import canvas as canvas_router
from services.chat_service import handle_chat
from services.langgraph_service.agent_manager import AgentManager
from services.langgraph_service.canvas_context import build_canvas_scene_context
from utils.canvas import _boxes_overlap, _elem_bounds, find_next_best_element_position


class CanvasLayoutCollisionTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_canvas_returns_origin(self):
        pos = await find_next_best_element_position({"elements": []})
        self.assertEqual(pos, (0, 0))

    async def test_places_first_media_beside_storyboard_shapes_and_negative_arrows(self):
        elements = [
            {"id": "f1", "type": "frame", "x": 40, "y": 60, "width": 560, "height": 600},
            {"id": "r1", "type": "rectangle", "x": 70, "y": 120, "width": 500, "height": 200},
            {"id": "t1", "type": "text", "x": 85, "y": 140, "width": 460, "height": 120, "text": "脚本1"},
            # 负宽高箭头：左边界在 580，右边界在 630；上边界在 150，下边界在 210
            {"id": "a_neg", "type": "arrow", "x": 630, "y": 210, "width": -50, "height": -60},
            {
                "id": "ba1",
                "type": "polygon",
                "x": 640,
                "y": 220,
                "width": 90,
                "height": 44,
                "customData": {"jaazType": "blockArrow", "variant": "straight"},
            },
        ]
        x, y = await find_next_best_element_position(
            {"elements": elements}, spacing=40, target_width=1024, target_height=1024
        )
        new_box = (x, y, x + 1024, y + 1024)
        for elem in elements:
            self.assertFalse(
                _boxes_overlap(new_box, _elem_bounds(elem)),
                f"新媒体框 {new_box} 不应与 {elem['id']} 重叠",
            )
        self.assertEqual(x, 770.0)
        self.assertEqual(y, 60.0)

    async def test_wide_storyboard_places_media_below(self):
        elements = [
            {"id": "wide_frame", "type": "frame", "x": 0, "y": 50, "width": 2400, "height": 500},
        ]
        x, y = await find_next_best_element_position(
            {"elements": elements}, spacing=40, target_width=640, target_height=640
        )
        self.assertEqual(x, 0.0)
        self.assertEqual(y, 590.0)

    async def test_shifts_past_interleaved_shape_obstacle_in_media_row(self):
        elements = [
            # 第一张图在 (800, 100, 512x512) -> 下一候选默认在 (1352, 100)
            {"id": "img1", "type": "image", "x": 800, "y": 100, "width": 512, "height": 512},
            # 用户在 (1400, 150) 放了一个批注矩形，阻挡第二列默认槽位
            {"id": "note_rect", "type": "rectangle", "x": 1400, "y": 150, "width": 220, "height": 180},
        ]
        x, y = await find_next_best_element_position(
            {"elements": elements}, spacing=40, target_width=512, target_height=512
        )
        new_box = (x, y, x + 512, y + 512)
        for elem in elements:
            self.assertFalse(_boxes_overlap(new_box, _elem_bounds(elem)))
        self.assertGreaterEqual(x, 1660.0)


class CanvasSceneContextTests(unittest.TestCase):
    def test_extracts_frames_bound_and_free_texts_block_arrows_and_embeddable_videos(self):
        canvas_data = {
            "elements": [
                {"id": "f1", "type": "frame", "name": "分镜区A", "x": 10, "y": 20, "width": 500, "height": 400},
                {"id": "r1", "type": "rectangle", "frameId": "f1", "x": 30, "y": 50, "width": 300, "height": 120},
                {
                    "id": "t_bound",
                    "type": "text",
                    "containerId": "r1",
                    "x": 40,
                    "y": 70,
                    "width": 260,
                    "height": 60,
                    "text": "脚本1：雨巷汉服女子",
                },
                {
                    "id": "t_free",
                    "type": "text",
                    "x": 30,
                    "y": 220,
                    "width": 260,
                    "height": 60,
                    "text": "脚本2：天青釉茶盏",
                },
                {
                    "id": "ba_curved",
                    "type": "polygon",
                    "x": 520,
                    "y": 100,
                    "width": 90,
                    "height": 50,
                    "customData": {"jaazType": "blockArrow", "variant": "curved"},
                },
                {
                    "id": "img_1",
                    "type": "image",
                    "fileId": "fid_img_1",
                    "x": 650,
                    "y": 50,
                    "width": 1024,
                    "height": 1024,
                },
                # Excalidraw 保存视频后转换为 embeddable + link
                {
                    "id": "vid_embed_1",
                    "type": "embeddable",
                    "link": "/api/file/clip_demo.mp4",
                    "x": 1720,
                    "y": 50,
                    "width": 640,
                    "height": 640,
                },
                {
                    "id": "deleted_txt",
                    "type": "text",
                    "isDeleted": True,
                    "x": 0,
                    "y": 0,
                    "width": 100,
                    "height": 30,
                    "text": "已删除内容不应出现",
                },
            ],
            "files": {
                "fid_img_1": {"id": "fid_img_1", "dataURL": "/api/file/hero_v1.png", "mimeType": "image/png"},
            },
        }
        ctx = build_canvas_scene_context(canvas_data)
        self.assertIn("<canvas_scene_context>", ctx)
        self.assertIn('画框 "分镜区A"', ctx)
        self.assertIn("图形(rectangle)内文字#1 [所属画框: 分镜区A]", ctx)
        self.assertIn("脚本1：雨巷汉服女子", ctx)
        self.assertIn("文字框#2", ctx)
        self.assertIn("脚本2：天青釉茶盏", ctx)
        self.assertIn("blockArrow(curved)×1", ctx)
        self.assertIn('画布图像#1: file_id="hero_v1.png"', ctx)
        self.assertIn('画布视频#2: file_id="clip_demo.mp4"', ctx)
        self.assertNotIn("已删除内容不应出现", ctx)


class AgentPromptWiringAndHandoffTests(unittest.TestCase):
    def test_system_prompt_propagates_to_planner_and_capability_creators_with_handoffs(self):
        fake_t2i = MagicMock()
        fake_t2i.name = "comfyui_text2image_minimax_h3"
        fake_i2v = MagicMock()
        fake_i2v.name = "comfyui_ref2video_dual_minimax_h3_fl2va_turbo"

        tool_list = [
            {"id": "comfyui_text2image_minimax_h3", "provider": "comfyui", "type": "image", "capability": "t2i"},
            {"id": "comfyui_ref2video_dual_minimax_h3_fl2va_turbo", "provider": "comfyui", "type": "video", "capability": "i2v"},
        ]
        custom_prompt = "用户自定义规则\n<canvas_scene_context>画布脚本测试</canvas_scene_context>"

        with patch.object(AgentManager, "_create_langgraph_agent", side_effect=lambda model, cfg: cfg):
            with patch(
                "services.langgraph_service.agent_manager. tool_service"
                if False
                else "services.langgraph_service.agent_manager.tool_service"
            ) as mock_ts:
                mock_ts.get_tool.side_effect = lambda tid: (
                    fake_t2i if tid == "comfyui_text2image_minimax_h3" else fake_i2v
                )
                configs = AgentManager.create_agents("mock_model", tool_list, custom_prompt)

        by_name = {c.name: c for c in configs}
        self.assertIn("planner", by_name)
        self.assertIn("image_creator", by_name)
        self.assertIn("video_creator", by_name)

        for agent_name in ("planner", "image_creator", "video_creator"):
            self.assertIn("<canvas_scene_context>画布脚本测试</canvas_scene_context>", by_name[agent_name].system_prompt)

        img_handoffs = [h["agent_name"] for h in by_name["image_creator"].handoffs]
        vid_handoffs = [h["agent_name"] for h in by_name["video_creator"].handoffs]
        self.assertIn("video_creator", img_handoffs)
        self.assertIn("image_creator", vid_handoffs)
        self.assertIn("CROSS-CAPABILITY HANDOFF RULE", by_name["image_creator"].system_prompt)


class BlankCanvasCreationTests(unittest.IsolatedAsyncioTestCase):
    async def test_handle_chat_skips_when_messages_empty(self):
        with (
            patch("services.chat_service.db_service.create_chat_session", new_callable=AsyncMock) as mock_sess,
            patch("services.chat_service.langgraph_multi_agent", new_callable=AsyncMock) as mock_agent,
        ):
            await handle_chat({"canvas_id": "c_blank", "session_id": "s_blank", "messages": []})
            mock_sess.assert_not_awaited()
            mock_agent.assert_not_awaited()

    async def test_create_canvas_endpoint_skips_agent_on_blank_messages(self):
        import asyncio

        req = MagicMock()
        req.json = AsyncMock(
            return_value={
                "canvas_id": "c_blank_api",
                "name": "空白测试画布",
                "session_id": "s_blank_api",
                "messages": [],
            }
        )
        with (
            patch.object(canvas_router.db_service, "create_canvas", new_callable=AsyncMock) as mock_create,
            patch("services.chat_service.langgraph_multi_agent", new_callable=AsyncMock) as mock_agent,
        ):
            res = await canvas_router.create_canvas(req)
            await asyncio.sleep(0.02)
            self.assertEqual(res, {"id": "c_blank_api"})
            mock_create.assert_awaited_once_with("c_blank_api", "空白测试画布")
            mock_agent.assert_not_awaited()


class WorkflowPackIntegrityTests(unittest.TestCase):
    def test_repaired_workflows_have_valid_models_and_no_preview_only_mie_nodes(self):
        dual_api = json.loads(
            (REPO_ROOT / "workflows" / "ref2video_dual_minimax_h3_fl2va_turbo" / "workflow.api.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            dual_api["93"]["inputs"]["vae_name"],
            "minimax_h3_video_vae_int8_convrot.safetensors",
        )
        self.assertEqual(
            dual_api["95"]["inputs"]["unet_name"],
            "minimax_h3_fl2va_pruned_int8_convrot.safetensors",
        )
        self.assertEqual(
            dual_api["105"]["inputs"]["lora_name"],
            "minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors",
        )

        rf_api = json.loads(
            (REPO_ROOT / "workflows" / "ref2video_multimodal_minimax_h3_rf" / "workflow.api.json").read_text(
                encoding="utf-8"
            )
        )
        class_types = {v.get("class_type") for v in rf_api.values() if isinstance(v, dict)}
        self.assertNotIn("ShowAnything|Mie", class_types)
        self.assertNotIn("PathchSageAttentionKJ", class_types)

        dual_classes = {v.get("class_type") for v in dual_api.values() if isinstance(v, dict)}
        self.assertNotIn("PathchSageAttentionKJ", dual_classes)
        self.assertNotIn("MiniMaxH3MemoryEfficientSageAttentionPatch", dual_classes)
        self.assertEqual(dual_api["84"]["inputs"]["model"], ["105", 0])
        self.assertEqual(dual_api["87"]["inputs"]["model"], ["105", 0])


class CanvasSaveRaceMergeTests(unittest.TestCase):
    def test_preserves_unseen_server_generated_media_on_stale_frontend_save(self):
        existing = {
            "elements": [
                {"id": "txt_1", "type": "text", "text": "旧文案", "isDeleted": False},
                {"id": "im_new12345", "type": "video", "fileId": "im_new12345", "isDeleted": False, "link": "/api/file/out.mp4"},
            ],
            "files": {
                "im_new12345": {"id": "im_new12345", "dataURL": "/api/file/out.mp4", "created": 1000},
            },
        }
        incoming = {
            "elements": [
                {"id": "txt_1", "type": "text", "text": "用户刚改的文案", "isDeleted": False},
            ],
            "files": {},
        }
        merged = canvas_router.merge_canvas_data_preserving_unseen_media(existing, incoming, now_ms=2000)
        ids = [e["id"] for e in merged["elements"]]
        self.assertEqual(ids, ["txt_1", "im_new12345"])
        self.assertEqual(merged["elements"][0]["text"], "用户刚改的文案")
        self.assertIn("im_new12345", merged["files"])

    def test_does_not_resurrect_explicitly_deleted_server_media(self):
        existing = {
            "elements": [
                {"id": "im_del12345", "type": "image", "fileId": "im_del12345", "isDeleted": False},
            ],
            "files": {
                "im_del12345": {"id": "im_del12345", "dataURL": "/api/file/a.png", "created": 1000},
            },
        }
        incoming = {
            "elements": [
                {"id": "im_del12345", "type": "image", "fileId": "im_del12345", "isDeleted": True},
            ],
            "files": {},
        }
        merged = canvas_router.merge_canvas_data_preserving_unseen_media(existing, incoming, now_ms=2000)
        self.assertEqual(len(merged["elements"]), 1)
        self.assertTrue(merged["elements"][0]["isDeleted"])

    def test_allows_clearing_old_canvas_to_empty_array(self):
        existing = {
            "elements": [
                {"id": "im_old12345", "type": "image", "fileId": "im_old12345", "isDeleted": False},
            ],
            "files": {
                "im_old12345": {"id": "im_old12345", "dataURL": "/api/file/old.png", "created": 1_000},
            },
        }
        incoming = {"elements": [], "files": {}}
        merged = canvas_router.merge_canvas_data_preserving_unseen_media(
            existing, incoming, now_ms=500_000
        )
        self.assertEqual(merged["elements"], [])


class ComfyHistoryTransientTimeoutAndSpaRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_history_outputs_swallows_transient_read_timeout(self):
        import httpx
        from routers.comfyui_execution import WorkflowExecution

        wf_exec = WorkflowExecution({}, "http://127.0.0.1:8188", False, None, False)
        wf_exec.prompt_id = "pid-timeout-test"

        class _TimeoutClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def get(self, *args, **kwargs):
                raise httpx.ReadTimeout("")

        with patch("routers.comfyui_execution.HttpClient.create", return_value=_TimeoutClient()):
            done = await wf_exec._fetch_history_outputs()
        self.assertFalse(done)

    def test_spa_routes_registered_for_canvas_and_assets(self):
        import main as server_main

        paths = {getattr(r, "path", None) for r in server_main.app.routes}
        self.assertIn("/", paths)
        self.assertIn("/canvas/{canvas_id}", paths)
        self.assertIn("/assets", paths)




if __name__ == "__main__":
    unittest.main()
