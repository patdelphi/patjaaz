"""程序说明：基于本地 aiohttp HTTP + WebSocket 模拟真实 ComfyUI 服务端，端到端验证提交、鉴权、进度、断线回退与取消链路，以及日志脱敏和 mtime 缓存。"""
import asyncio
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from aiohttp import web

from routers.comfyui_execution import execute
from services.comfy_instance_service import ComfyInstanceService
from services.comfy_workflow_pack import scan_workflows_dir
from services.llm_adapters import parse_anthropic_response, parse_gemini_response
from utils.log_sanitizer import redact_secrets


class FakeComfyUIServer:
    """轻量本地假 ComfyUI 服务：支持 /system_stats、/prompt、/history、/queue、/interrupt 与 /ws。"""

    def __init__(self, expected_token: str = "secret_comfy_token", drop_ws_early: bool = False):
        self.expected_token = expected_token
        self.drop_ws_early = drop_ws_early
        self.received_auth_headers: list[str] = []
        self.queue_deletes: list[list[str]] = []
        self.interrupt_calls: int = 0
        self.history_store: dict[str, dict] = {}
        self.ws_clients: list[web.WebSocketResponse] = []
        self.runner: web.AppRunner | None = None
        self.site: web.TCPSite | None = None
        self.base_url: str = ""

    def _check_auth(self, request: web.Request) -> None:
        auth = request.headers.get("Authorization", "")
        self.received_auth_headers.append(auth)
        if self.expected_token and auth != f"Bearer {self.expected_token}":
            raise web.HTTPUnauthorized(text="Unauthorized")

    async def start(self) -> str:
        app = web.Application()
        app.router.add_get("/sub/system_stats", self._handle_stats)
        app.router.add_get("/sub/api/prompt", self._handle_stats)
        app.router.add_post("/sub/prompt", self._handle_prompt)
        app.router.add_get("/sub/history/{prompt_id}", self._handle_history)
        app.router.add_post("/sub/queue", self._handle_queue)
        app.router.add_post("/sub/interrupt", self._handle_interrupt)
        app.router.add_get("/sub/ws", self._handle_ws)

        self.runner = web.AppRunner(app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await self.site.start()
        sockets = self.site._server.sockets  # type: ignore[attr-defined]
        port = sockets[0].getsockname()[1]
        self.base_url = f"http://127.0.0.1:{port}/sub"
        return self.base_url

    async def stop(self) -> None:
        for ws in list(self.ws_clients):
            await ws.close()
        if self.runner is not None:
            await self.runner.cleanup()

    async def _handle_stats(self, request: web.Request) -> web.Response:
        self._check_auth(request)
        return web.json_response({"system": {"os": "mock"}, "devices": []})

    async def _handle_prompt(self, request: web.Request) -> web.Response:
        self._check_auth(request)
        prompt_id = "pid_mock_001"
        self.history_store[prompt_id] = {
            "status": {"status_str": "success", "completed": True},
            "outputs": {
                "9": {
                    "images": [
                        {"filename": "mock_out.png", "subfolder": "", "type": "output"}
                    ]
                }
            },
        }
        asyncio.create_task(self._push_ws_events(prompt_id))
        return web.json_response({"prompt_id": prompt_id, "number": 1})

    async def _push_ws_events(self, prompt_id: str) -> None:
        await asyncio.sleep(0.03)
        for ws in list(self.ws_clients):
            if ws.closed:
                continue
            await ws.send_json(
                {"type": "executing", "data": {"prompt_id": prompt_id, "node": "23:7"}}
            )
            await ws.send_json(
                {
                    "type": "progress",
                    "data": {"prompt_id": prompt_id, "node": "23:7", "value": 4, "max": 8},
                }
            )
            if self.drop_ws_early:
                await ws.close()
                return
            await ws.send_json(
                {
                    "type": "executed",
                    "data": {
                        "prompt_id": prompt_id,
                        "node": "9",
                        "output": {
                            "images": [
                                {"filename": "mock_out.png", "subfolder": "", "type": "output"}
                            ]
                        },
                    },
                }
            )
            await ws.send_json(
                {"type": "executing", "data": {"prompt_id": prompt_id, "node": None}}
            )

    async def _handle_history(self, request: web.Request) -> web.Response:
        self._check_auth(request)
        pid = request.match_info["prompt_id"]
        if pid in self.history_store:
            return web.json_response({pid: self.history_store[pid]})
        return web.json_response({})

    async def _handle_queue(self, request: web.Request) -> web.Response:
        self._check_auth(request)
        body = await request.json()
        if isinstance(body.get("delete"), list):
            self.queue_deletes.append(body["delete"])
        return web.json_response({"ok": True})

    async def _handle_interrupt(self, request: web.Request) -> web.Response:
        self._check_auth(request)
        self.interrupt_calls += 1
        return web.json_response({"ok": True})

    async def _handle_ws(self, request: web.Request) -> web.WebSocketResponse:
        self._check_auth(request)
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.ws_clients.append(ws)
        try:
            async for _ in ws:
                pass
        finally:
            if ws in self.ws_clients:
                self.ws_clients.remove(ws)
        return ws


class StageCEngineeringAndFakeComfyTests(unittest.IsolatedAsyncioTestCase):
    """覆盖假 ComfyUI 全链路（含 WS 断线回退与取消）、usage_metadata、脱敏与 mtime 缓存。"""

    async def test_fake_comfyui_ws_execution_subpath_and_auth(self) -> None:
        server = FakeComfyUIServer(expected_token="tok_live_123", drop_ws_early=False)
        base_url = await server.start()
        try:
            wf = {
                "23:7": {"class_type": "KSampler", "inputs": {}},
                "9": {"class_type": "SaveImage", "inputs": {}},
            }
            headers = {"Authorization": "Bearer tok_live_123"}
            with patch.dict(os.environ, {"NO_PROXY": "127.0.0.1,localhost"}):
                res = await execute(
                    wf,
                    base_url,
                    wait=True,
                    headers=headers,
                    ctx={"session_id": "sess_mock"},
                    instance_id="mock_inst",
                )
            self.assertEqual(len(res.outputs), 1)
            self.assertIn("/sub/view?filename=mock_out.png", res.outputs[0])
            self.assertTrue(all(h == "Bearer tok_live_123" for h in server.received_auth_headers))
        finally:
            await server.stop()

    async def test_fake_comfyui_ws_disconnect_falls_back_to_history_and_cancel_hits_interrupt(self) -> None:
        server = FakeComfyUIServer(expected_token="tok_drop_456", drop_ws_early=True)
        base_url = await server.start()
        try:
            wf = {"9": {"class_type": "SaveImage", "inputs": {}}}
            headers = {"Authorization": "Bearer tok_drop_456"}
            with patch.dict(os.environ, {"NO_PROXY": "127.0.0.1,localhost"}):
                res = await execute(
                    wf,
                    base_url,
                    wait=True,
                    headers=headers,
                    ctx={"session_id": "sess_drop"},
                    instance_id="mock_inst",
                )
                self.assertEqual(len(res.outputs), 1)
                self.assertIn("mock_out.png", res.outputs[0])

                svc = ComfyInstanceService()
                svc.register_active_prompt(
                    "sess_cancel", base_url, "pid_cancel_9", headers=headers, instance_id="mock_inst"
                )
                cancel_res = await svc.cancel_session_prompts("sess_cancel")
                self.assertEqual(len(cancel_res), 1)
                self.assertTrue(cancel_res[0]["queue_deleted"])
                self.assertTrue(cancel_res[0]["interrupted"])
                self.assertEqual(server.queue_deletes, [["pid_cancel_9"]])
                self.assertEqual(server.interrupt_calls, 1)
        finally:
            await server.stop()

    def test_llm_usage_metadata_log_redaction_and_workflow_mtime_cache(self) -> None:
        anth_msg = parse_anthropic_response(
            {
                "content": [{"type": "text", "text": "hello"}],
                "usage": {"input_tokens": 120, "output_tokens": 35},
            }
        )
        self.assertEqual(
            anth_msg.usage_metadata,
            {"input_tokens": 120, "output_tokens": 35, "total_tokens": 155},
        )

        gem_msg = parse_gemini_response(
            {
                "candidates": [{"content": {"parts": [{"text": "world"}]}}],
                "usageMetadata": {
                    "promptTokenCount": 80,
                    "candidatesTokenCount": 20,
                    "totalTokenCount": 100,
                },
            }
        )
        self.assertEqual(
            gem_msg.usage_metadata,
            {"input_tokens": 80, "output_tokens": 20, "total_tokens": 100},
        )

        leaked = "Error with Authorization: Bearer secret_abc123456 and sk-proj1234567890"
        cleaned = redact_secrets(leaked)
        self.assertNotIn("secret_abc123456", cleaned)
        self.assertNotIn("sk-proj1234567890", cleaned)

        with tempfile.TemporaryDirectory() as tmp_wf:
            pack_dir = os.path.join(tmp_wf, "demo_wf")
            os.makedirs(pack_dir)
            with open(os.path.join(pack_dir, "workflow.api.json"), "w", encoding="utf-8") as f:
                json.dump({"1": {"class_type": "SaveImage", "inputs": {"filename_prefix": "x"}}}, f)
            with open(os.path.join(pack_dir, "jaaz.workflow.json"), "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "schema_version": 1,
                        "name": "demo_wf",
                        "display_name": "Demo",
                        "capability": "t2i",
                        "output_kind": "image",
                        "enabled": True,
                        "description": "d",
                        "inputs": [
                            {
                                "name": "prefix",
                                "type": "string",
                                "required": False,
                                "node_id": "1",
                                "node_input_name": "filename_prefix",
                                "default_value": "x",
                            }
                        ],
                    },
                    f,
                )

            first = scan_workflows_dir(tmp_wf)
            self.assertEqual(len(first["valid"]), 1)
            with patch(
                "services.comfy_workflow_pack._load_json_pair",
                side_effect=AssertionError("Should hit mtime cache"),
            ):
                second = scan_workflows_dir(tmp_wf)
                self.assertEqual(len(second["valid"]), 1)


if __name__ == "__main__":
    unittest.main()
