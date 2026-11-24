"""程序说明：阶段 3（已知 bug 修复）同步与异步回归测试，覆盖会话列表、工具过滤、相对路径、ComfyUI 健壮性、种子保留与 HTTPException 透传。"""
import asyncio
import inspect
import os
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from routers import comfyui_execution, root_router, tool_confirmation
from routers.comfyui_execution import ComfyUIUnavailableError, WorkflowExecution
from services.db_service import DatabaseService
from tools.comfy_dynamic import apply_workflow_inputs_and_seeds
from tools.video_generation.video_canvas_utils import format_video_success_message
from utils.comfyui_history import history_output_urls


class Stage3BugFixTests(unittest.TestCase):
    def test_list_sessions_without_canvas_id_returns_all_sessions(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = DatabaseService(db_path=os.path.join(tmp, "s3.db"))
            db._create_canvas_sync("c1", "C1")
            db._create_canvas_sync("c2", "C2")
            db._create_chat_session_sync("s1", "m", "p", "c1", "A")
            db._create_chat_session_sync("s2", "m", "p", "c2", "B")

            all_sessions = db._list_sessions_sync()
            self.assertEqual({s["id"] for s in all_sessions}, {"s1", "s2"})

            c1_sessions = db._list_sessions_sync("c1")
            self.assertEqual([s["id"] for s in c1_sessions], ["s1"])

    def test_filter_available_tools_skips_missing_provider_config(self):
        tools = {
            "sys": {"provider": "system", "type": "tool", "display_name": "Sys"},
            "comfy": {"provider": "comfyui", "type": "image", "display_name": "Comfy"},
            "missing_provider": {"provider": "nonexistent", "type": "image", "display_name": "X"},
            "no_key": {"provider": "openai", "type": "image", "display_name": "NoKey"},
            "has_key": {"provider": "custom", "type": "video", "display_name": "Custom"},
        }
        config = {
            "comfyui": {"url": "http://127.0.0.1:8188"},
            "openai": {"api_key": "   "},
            "custom": {"api_key": "sk-test-123"},
        }

        filtered = root_router.filter_available_tools(tools, config)
        self.assertEqual([t["id"] for t in filtered], ["comfy", "has_key"])

    def test_relative_file_urls_without_hardcoded_localhost(self):
        video_msg = format_video_success_message("vi_123.mp4")
        self.assertIn("](/api/file/vi_123.mp4)", video_msg)
        self.assertNotIn("http://localhost:", video_msg)

        for mod_name in ("routers.image_router", "tools.utils.image_generation_core", "tools.comfy_dynamic"):
            mod = sys.modules.get(mod_name) or __import__(mod_name, fromlist=["*"])
            src = inspect.getsource(mod)
            self.assertNotIn("http://localhost:{DEFAULT_PORT}/api/file/", src, mod_name)

    def test_history_output_urls_extracts_images_gifs_videos_audio(self):
        record = {
            "outputs": {
                "1": {"images": [{"filename": "a.png", "type": "output"}]},
                "2": {"gifs": [{"filename": "b.gif", "type": "output"}]},
                "3": {"videos": [{"filename": "c.mp4", "type": "output"}]},
                "4": {"audio": [{"filename": "d.wav", "type": "output"}]},
            }
        }
        urls = history_output_urls(record, "http://127.0.0.1:8188/")
        self.assertEqual(len(urls), 4)
        self.assertTrue(any("c.mp4" in u for u in urls))
        self.assertTrue(any("d.wav" in u for u in urls))

    def test_comfy_execution_no_typer_exit_and_safe_node_title(self):
        exec_src = inspect.getsource(comfyui_execution.execute)
        self.assertNotIn("typer.Exit", exec_src)
        self.assertTrue(issubclass(ComfyUIUnavailableError, RuntimeError))

        queue_src = inspect.getsource(WorkflowExecution.queue)
        upload_src = inspect.getsource(comfyui_execution.upload_image)
        self.assertIn("raise_for_status()", queue_src)
        self.assertIn("raise_for_status()", upload_src)

        wf_exec = WorkflowExecution(
            workflow={
                "6": {"class_type": "CLIPTextEncode", "_meta": {"title": "Prompt"}},
                "12": {"class_type": "SubgraphWrapper"},
            },
            base_url="http://127.0.0.1:8188",
            verbose=False,
            progress=None,
            local_paths=False,
        )
        self.assertEqual(wf_exec.get_node_title("6"), "Prompt")
        self.assertEqual(wf_exec.get_node_title("12:3"), "SubgraphWrapper")
        self.assertEqual(wf_exec.get_node_title("999"), "Node 999")

        status_src = inspect.getsource(WorkflowExecution.on_status)
        self.assertIn("return True", status_src)
        self.assertNotIn("data['data']", status_src)

    def test_apply_workflow_inputs_and_seeds_preserves_explicit_seed_and_noise_seed(self):
        workflow = {
            "3": {"class_type": "KSampler", "inputs": {"seed": 1, "steps": 20}},
            "25": {"class_type": "RandomNoise", "inputs": {"noise_seed": 2}},
            "99": {"class_type": "KSampler", "inputs": {"seed": 3}},
        }
        input_defs = [
            {"name": "seed", "node_id": "3", "node_input_name": "seed"},
            {"name": "flux_seed", "node_id": "25", "node_input_name": "noise_seed"},
        ]

        counter = iter([777777, 888888])
        updated = apply_workflow_inputs_and_seeds(
            workflow,
            input_defs,
            {"seed": 42, "flux_seed": 12345},
            seed_generator=lambda: next(counter),
        )
        # 显式传入的 seed 与 noise_seed 保持原值；未指定的 99 号节点被随机替换
        self.assertEqual(updated["3"]["inputs"]["seed"], 42)
        self.assertEqual(updated["25"]["inputs"]["noise_seed"], 12345)
        self.assertEqual(updated["99"]["inputs"]["seed"], 777777)

        # 原字典不被修改
        self.assertEqual(workflow["3"]["inputs"]["seed"], 1)

    def test_tool_confirmation_rethrows_http_exception(self):
        src = inspect.getsource(tool_confirmation.handle_tool_confirmation)
        self.assertIn("except HTTPException:", src)
        self.assertLess(src.index("except HTTPException:"), src.index("except Exception"))


class Stage3AsyncBugFixTests(unittest.IsolatedAsyncioTestCase):
    async def test_tool_confirmation_missing_call_raises_404_not_500(self):
        req = tool_confirmation.ToolConfirmationRequest(
            session_id="s1",
            tool_call_id="nonexistent-tool-call",
            confirmed=True,
        )
        with self.assertRaises(HTTPException) as ctx:
            await tool_confirmation.handle_tool_confirmation(req)
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_execute_raises_business_error_when_comfy_offline(self):
        with patch.object(comfyui_execution, "check_comfy_server_running", AsyncMock(return_value=False)):
            with self.assertRaises(ComfyUIUnavailableError):
                await comfyui_execution.execute({}, "http://127.0.0.1:8188")

    async def test_on_message_status_and_executed_media_outputs(self):
        wf = WorkflowExecution(
            workflow={"9": {"class_type": "SaveMedia"}},
            base_url="http://127.0.0.1:8188",
            verbose=False,
            progress=None,
            local_paths=False,
            ctx={"session_id": "sess-3", "tool_call_id": "tc-3"},
        )
        wf.prompt_id = "p-async-1"

        ws_mock = AsyncMock()
        with (
            patch.object(comfyui_execution, "send_to_websocket", ws_mock),
            patch.object(comfyui_execution, "update_stream_status"),
        ):
            # status 事件没有 prompt_id，必须正常处理并返回 True（不能返回 None 被当作完成）
            keep_running = await wf.on_message(
                {"type": "status", "data": {"status": {"exec_info": {"queue_remaining": 3}}}}
            )
            self.assertIs(keep_running, True)

            await wf.on_message(
                {
                    "type": "executed",
                    "data": {
                        "prompt_id": "p-async-1",
                        "node": "9",
                        "output": {
                            "images": [{"filename": "img.png", "type": "output"}],
                            "gifs": [{"filename": "anim.gif", "type": "output"}],
                            "videos": [{"filename": "clip.mp4", "type": "output"}],
                            "audio": [{"filename": "voice.wav", "type": "output"}],
                        },
                    },
                }
            )

        self.assertEqual(len(wf.outputs), 4)
        self.assertTrue(any("clip.mp4" in u for u in wf.outputs))
        self.assertTrue(any("voice.wav" in u for u in wf.outputs))
        ws_mock.assert_any_await(
            "sess-3",
            {
                "type": "tool_call_progress",
                "tool_call_id": "tc-3",
                "session_id": "sess-3",
                "update": "In queue, there's 3 works ahead...",
            },
        )

    async def test_watch_execution_falls_back_to_history_on_ws_disconnect_and_closes_ws(self):
        class _BrokenWS:
            def __init__(self):
                self.close = AsyncMock()

            async def recv(self):
                raise OSError("ws reset")

        wf = WorkflowExecution({}, "http://127.0.0.1:8188", False, None, False, timeout=2.0)
        wf.prompt_id = "p-fallback"
        ws = _BrokenWS()
        wf.ws = ws

        async def fake_history():
            wf.outputs.append("http://127.0.0.1:8188/view?filename=recovered.png")
            return True

        with patch.object(wf, "_fetch_history_outputs", side_effect=fake_history):
            await wf.watch_execution()

        self.assertEqual(wf.outputs, ["http://127.0.0.1:8188/view?filename=recovered.png"])
        ws.close.assert_awaited_once()
        self.assertIsNone(wf.ws)

    async def test_watch_execution_times_out_and_closes_ws(self):
        class _HangingWS:
            def __init__(self):
                self.close = AsyncMock()

            async def recv(self):
                await asyncio.sleep(5)
                return "{}"

        wf = WorkflowExecution({}, "http://127.0.0.1:8188", False, None, False, timeout=0.05)
        wf.prompt_id = "p-timeout"
        ws = _HangingWS()
        wf.ws = ws

        with patch.object(wf, "_fetch_history_outputs", AsyncMock(return_value=False)):
            with self.assertRaises(TimeoutError):
                await wf.watch_execution()

        ws.close.assert_awaited_once()
        self.assertIsNone(wf.ws)


if __name__ == "__main__":
    unittest.main()
