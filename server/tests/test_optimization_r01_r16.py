"""程序说明：优化计划 R-01~R-16 回归测试，覆盖命名冲突保护、能力分组智能体、实例并发与选择、遗留任务收尾、自动导入开关、摘要截断、Gemini 重试与流式。"""
import asyncio
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from langchain_core.messages import HumanMessage

SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from services import comfy_workflow_pack as pack
from services.comfy_instance_service import ComfyInstanceService
from services.db_service import DatabaseService
from services.langgraph_service.capability_groups import (
    AUDIO_GROUP,
    IMAGE_GROUP,
    VIDEO_GROUP,
    group_tools_by_capability,
)
from services.langgraph_service.configs.image_vide_creator_config import (
    CapabilityCreatorAgentConfig,
)
from services.langgraph_service.configs.planner_config import PlannerAgentConfig
from services.llm_adapters import GeminiNativeChatModel
from services.tool_service import ToolService
from tools.comfy_dynamic import _python_type, apply_workflow_inputs_and_seeds

API = {
    "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "x" * 500}},
    "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "o", "images": ["6", 0]}},
}


def _cfg(name: str, source_file: str = "") -> dict:
    cfg = {
        "schema_version": 1,
        "name": name,
        "display_name": name,
        "capability": "t2i",
        "output_kind": "image",
        "enabled": True,
        "description": "测试工作流",
        "inputs": [],
    }
    if source_file:
        cfg["source_file"] = source_file
    return cfg


class PackOptimizationTests(unittest.TestCase):
    def test_non_ascii_names_get_distinct_hashed_names(self):
        a = pack._sanitize_workflow_name("文生图_MiniMax-H3-Image")
        b = pack._sanitize_workflow_name("多参考图编辑_MiniMax-H3-Image")
        self.assertNotEqual(a, b)
        self.assertRegex(a, r"^[a-zA-Z0-9_]+$")
        self.assertEqual(pack._sanitize_workflow_name("plain_name"), "plain_name")

    def test_save_rejects_overwrite_from_other_source_and_unique_name_suffixes(self):
        with tempfile.TemporaryDirectory() as wf_dir:
            pack.save_pack_to_workflows_dir(API, _cfg("same_name", "a.json"), wf_dir)

            with self.assertRaises(pack.WorkflowPackValidationError):
                pack.save_pack_to_workflows_dir(API, _cfg("same_name", "b.json"), wf_dir)

            # 同一来源文件更新允许原地覆盖
            pack.save_pack_to_workflows_dir(API, _cfg("same_name", "a.json"), wf_dir)

            self.assertEqual(pack.unique_pack_name("same_name", "a.json", wf_dir), "same_name")
            self.assertEqual(pack.unique_pack_name("same_name", "b.json", wf_dir), "same_name_2")

    def test_summary_truncates_long_strings(self):
        summary = pack.summarize_api_json_for_agent(API)
        value = summary["nodes"][0]["literal_inputs"]["text"]["value"]
        self.assertLess(len(value), 300)
        self.assertIn("已截断", value)

    def test_seed_bundled_workflows_does_not_overwrite_existing(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundled = os.path.join(tmp, "bundled")
            target = os.path.join(tmp, "target")
            os.makedirs(os.path.join(bundled, "wf_a"))
            os.makedirs(os.path.join(bundled, "wf_b"))
            with open(os.path.join(bundled, "wf_a", "jaaz.workflow.json"), "w", encoding="utf-8") as f:
                f.write("new")
            with open(os.path.join(bundled, "wf_b", "jaaz.workflow.json"), "w", encoding="utf-8") as f:
                f.write("new")
            os.makedirs(os.path.join(target, "wf_a"))
            with open(os.path.join(target, "wf_a", "jaaz.workflow.json"), "w", encoding="utf-8") as f:
                f.write("user-edited")

            copied = pack.seed_bundled_workflows(bundled, target)
            self.assertEqual(copied, ["wf_b"])
            with open(os.path.join(target, "wf_a", "jaaz.workflow.json"), encoding="utf-8") as f:
                self.assertEqual(f.read(), "user-edited")

    def test_auto_import_switch_defaults_off_and_persists(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"USER_DATA_DIR": tmp}):
                self.assertFalse(pack.get_auto_import_source_enabled())
                pack.set_auto_import_source_enabled(True)
                self.assertTrue(pack.get_auto_import_source_enabled())
                pack.set_auto_import_source_enabled(False)
                self.assertFalse(pack.get_auto_import_source_enabled())

    def test_number_params_use_float_and_integer_defaults_are_restored(self):
        self.assertIs(_python_type("number", 15), float)
        api = {"7": {"class_type": "PrimitiveInt", "inputs": {"value": 1}}}
        defs = [{"name": "dur", "type": "number", "required": False, "node_id": "7",
                 "node_input_name": "value", "default_value": 15}]
        out = apply_workflow_inputs_and_seeds(api, defs, {"dur": 8.0})
        self.assertEqual(out["7"]["inputs"]["value"], 8)
        self.assertIsInstance(out["7"]["inputs"]["value"], int)
        out2 = apply_workflow_inputs_and_seeds(api, defs, {"dur": 7.5})
        self.assertEqual(out2["7"]["inputs"]["value"], 7.5)


class CapabilityGroupTests(unittest.TestCase):
    def test_tools_are_grouped_by_capability_and_empty_falls_back(self):
        tools = [
            {"id": "a", "provider": "comfyui", "type": "image", "capability": "t2i"},
            {"id": "b", "provider": "comfyui", "type": "video", "capability": "upscale"},
            {"id": "c", "provider": "comfyui", "type": "video", "capability": "i2v"},
            {"id": "d", "provider": "comfyui", "type": "audio", "capability": "tts"},
            {"id": "e", "provider": "comfyui", "type": "image", "capability": "upscale"},
        ]
        grouped = group_tools_by_capability(tools)
        self.assertEqual(list(grouped.keys()), [IMAGE_GROUP, VIDEO_GROUP, AUDIO_GROUP])
        self.assertEqual([t["id"] for t in grouped[IMAGE_GROUP]], ["a", "e"])
        self.assertEqual([t["id"] for t in grouped[VIDEO_GROUP]], ["b", "c"])
        self.assertEqual(list(group_tools_by_capability([]).keys()), [IMAGE_GROUP])

    def test_agent_configs_only_hand_off_to_existing_groups(self):
        planner = PlannerAgentConfig([IMAGE_GROUP, VIDEO_GROUP])
        self.assertEqual([h["agent_name"] for h in planner.handoffs], [IMAGE_GROUP, VIDEO_GROUP])
        self.assertIn(VIDEO_GROUP, planner.system_prompt)
        self.assertNotIn(AUDIO_GROUP, planner.system_prompt)

        creator = CapabilityCreatorAgentConfig(
            VIDEO_GROUP, [{"id": "c", "provider": "comfyui"}], [IMAGE_GROUP, VIDEO_GROUP]
        )
        self.assertEqual(creator.name, VIDEO_GROUP)
        self.assertEqual([h["agent_name"] for h in creator.handoffs], [IMAGE_GROUP])


class InstanceServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_acquire_slot_serializes_when_capacity_is_one(self):
        svc = ComfyInstanceService()
        running = 0
        peak = 0

        async def worker():
            nonlocal running, peak
            async with svc.acquire_slot("inst", 1):
                running += 1
                peak = max(peak, running)
                await asyncio.sleep(0.02)
                running -= 1

        await asyncio.gather(*(worker() for _ in range(4)))
        self.assertEqual(peak, 1)

    async def test_resolve_instance_prefers_capable_and_online(self):
        svc = ComfyInstanceService()
        instances = [
            {"id": "offline_i2v", "base_url": "http://a:8188", "enabled": 1,
             "capabilities_json": '["i2v"]', "last_health_json": '{"online": false}'},
            {"id": "t2i_only", "base_url": "http://b:8188", "enabled": 1,
             "capabilities_json": '["t2i"]', "last_health_json": "{}"},
            {"id": "online_i2v", "base_url": "http://c:8188", "enabled": 1,
             "capabilities_json": '["i2v"]', "last_health_json": '{"online": true}'},
        ]
        with patch.object(svc, "ensure_default_instance", AsyncMock(return_value=instances)):
            chosen = await svc.resolve_instance(capability="i2v")
            self.assertEqual(chosen["id"], "online_i2v")
            # 没有实例声明该能力时退回全部启用实例，而不是报错
            fallback = await svc.resolve_instance(capability="upscale")
            self.assertEqual(fallback["id"], "t2i_only")
            explicit = await svc.resolve_instance("offline_i2v")
            self.assertEqual(explicit["id"], "offline_i2v")


class DbAndToolServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_interrupt_stale_jobs_marks_running_and_queued_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = DatabaseService(db_path=os.path.join(tmp, "jobs.db"))
            await db.create_job({"id": "j_run", "status": "running"})
            await db.create_job({"id": "j_queue", "status": "queued"})
            await db.create_job({"id": "j_done", "status": "completed"})

            self.assertEqual(await db.interrupt_stale_jobs(), 2)
            self.assertEqual((await db.get_job("j_run"))["status"], "interrupted")
            self.assertEqual((await db.get_job("j_queue"))["status"], "interrupted")
            self.assertEqual((await db.get_job("j_done"))["status"], "completed")
            self.assertTrue((await db.get_job("j_run"))["finished_at"])

    async def test_tool_service_waits_until_ready(self):
        svc = ToolService()
        self.assertFalse(await svc.wait_until_ready(timeout=0.05))
        svc.ready.set()
        self.assertTrue(await svc.wait_until_ready(timeout=0.05))


class GeminiRetryAndStreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_retries_on_503_then_succeeds(self):
        calls = []

        class _Resp:
            def __init__(self, status):
                self.status_code = status

            def raise_for_status(self):
                if self.status_code >= 400:
                    raise RuntimeError(f"HTTP {self.status_code}")

            def json(self):
                return {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}

        class _Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def post(self, url, json=None, headers=None):
                calls.append(url)
                return _Resp(503 if len(calls) == 1 else 200)

        model = GeminiNativeChatModel(model="gemini-2.5-flash", api_key="k")
        with (
            patch("services.llm_adapters.HttpClient.create", return_value=_Client()),
            patch("services.llm_adapters.asyncio.sleep", new=AsyncMock()),
        ):
            msg = await model.ainvoke([HumanMessage(content="hi")])
        self.assertEqual(msg.content, "ok")
        self.assertEqual(len(calls), 2)

    async def test_stream_emits_text_increments_and_final_tool_call(self):
        sse_lines = [
            'data: {"candidates":[{"content":{"parts":[{"text":"Hel"}]}}]}',
            "",
            'data: {"candidates":[{"content":{"parts":[{"text":"lo"}]}}]}',
            'data: {"candidates":[{"content":{"parts":[{"functionCall":{"name":"echo","args":{"a":1}}}]}}]}',
        ]

        class _StreamResp:
            def raise_for_status(self):
                return None

            async def aiter_lines(self):
                for line in sse_lines:
                    yield line

        class _StreamCtx:
            async def __aenter__(self):
                return _StreamResp()

            async def __aexit__(self, *args):
                return False

        class _Client:
            captured = {}

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            def stream(self, method, url, json=None, headers=None):
                _Client.captured["url"] = url
                return _StreamCtx()

        model = GeminiNativeChatModel(model="gemini-2.5-flash", api_key="k")
        texts = []
        tool_calls = []
        with patch("services.llm_adapters.HttpClient.create", return_value=_Client()):
            async for chunk in model.astream([HumanMessage(content="hi")]):
                if chunk.content:
                    texts.append(chunk.content)
                tool_calls.extend(chunk.tool_calls or [])

        self.assertEqual("".join(texts), "Hello")
        self.assertIn("streamGenerateContent", _Client.captured["url"])
        self.assertIn("alt=sse", _Client.captured["url"])
        self.assertEqual(tool_calls[0]["name"], "echo")


class AnthropicStreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_yields_text_then_tool_call_from_final_message(self):
        from services.llm_adapters import AnthropicNativeChatModel

        class _Block:
            def __init__(self, **kw):
                self.__dict__.update(kw)

        final = _Block(content=[
            _Block(type="text", text="Hi"),
            _Block(type="tool_use", id="tu_1", name="echo", input={"a": 1}),
        ])

        class _Stream:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            @property
            def text_stream(self):
                async def gen():
                    yield "H"
                    yield "i"
                return gen()

            async def get_final_message(self):
                return final

        class _Messages:
            def stream(self, **req):
                return _Stream()

        class _Client:
            messages = _Messages()

        model = AnthropicNativeChatModel(model="claude-x", api_key="k")
        texts, calls = [], []
        with patch("services.llm_adapters.anthropic.AsyncAnthropic", return_value=_Client()):
            async for chunk in model.astream([HumanMessage(content="hi")]):
                if chunk.content:
                    texts.append(chunk.content)
                calls.extend(chunk.tool_calls or [])
        self.assertEqual("".join(texts), "Hi")
        self.assertEqual(calls[0]["name"], "echo")
        self.assertEqual(calls[0]["args"], {"a": 1})


class JobRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def _make_db(self, tmp):
        db = DatabaseService(db_path=os.path.join(tmp, "rec.db"))
        await db.create_job({"id": "j_rec", "status": "running", "canvas_id": "c1",
                             "session_id": "s1", "instance_id": "i1"})
        await db.update_job_status("j_rec", remote_prompt_id="pid-1")
        await db.create_job({"id": "j_norec", "status": "running"})
        return db

    async def test_recoverable_jobs_are_not_marked_interrupted(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = await self._make_db(tmp)
            self.assertEqual([j["id"] for j in await db.list_recoverable_jobs()], ["j_rec"])
            self.assertEqual(await db.interrupt_stale_jobs(), 1)
            self.assertEqual((await db.get_job("j_rec"))["status"], "running")
            self.assertEqual((await db.get_job("j_norec"))["status"], "interrupted")

    async def test_recover_job_downloads_outputs_and_completes(self):
        from services import job_recovery as jr

        with tempfile.TemporaryDirectory() as tmp:
            db = await self._make_db(tmp)
            record = {"status": {"status_str": "success"},
                      "outputs": {"9": {"images": [{"filename": "a.png", "subfolder": "x", "type": "output"}]}}}
            probes = iter([("pending", None), ("done", record)])
            append = AsyncMock(return_value=1)
            with (
                patch.object(jr, "db_service", db),
                patch.object(jr.comfy_instance_service, "resolve_instance",
                             AsyncMock(return_value={"base_url": "http://c", "headers": {}})),
                patch.object(jr, "_probe", AsyncMock(side_effect=lambda *a: next(probes))),
                patch.object(jr, "download_outputs",
                             AsyncMock(return_value=[("image/png", 10, 10, "f.png")])),
                patch.object(jr, "append_outputs_to_canvas", append),
                patch.object(jr.asyncio, "sleep", AsyncMock()),
            ):
                result = await jr.recover_job((await db.list_recoverable_jobs())[0])
            self.assertEqual(result, "completed")
            self.assertEqual((await db.get_job("j_rec"))["status"], "completed")
            append.assert_awaited_once()

    async def test_recover_job_gives_up_when_prompt_is_lost(self):
        from services import job_recovery as jr

        with tempfile.TemporaryDirectory() as tmp:
            db = await self._make_db(tmp)
            with (
                patch.object(jr, "db_service", db),
                patch.object(jr.comfy_instance_service, "resolve_instance",
                             AsyncMock(return_value={"base_url": "http://c", "headers": {}})),
                patch.object(jr, "_probe", AsyncMock(return_value=("lost", None))),
                patch.object(jr.asyncio, "sleep", AsyncMock()),
            ):
                result = await jr.recover_job((await db.list_recoverable_jobs())[0])
            self.assertEqual(result, "interrupted")
            self.assertEqual((await db.get_job("j_rec"))["status"], "interrupted")


if __name__ == "__main__":
    unittest.main()
