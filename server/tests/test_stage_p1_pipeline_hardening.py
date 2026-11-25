"""程序说明：覆盖阶段 P1 的三项链路加固测试（子图工具结果即时落库防 429 丢失、中间预览输出节点过滤、跨模型家族自动释放显存）。"""
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from routers.comfyui_execution import WorkflowExecution
from services.comfy_instance_service import (
    ComfyInstanceService,
    infer_workflow_model_family,
)
from services.langgraph_service.StreamProcessor import StreamProcessor
from utils.comfyui_history import history_output_urls, resolve_allowed_output_node_ids


class StageP1PipelineHardeningTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_processor_persists_tool_call_and_result_before_closing_429(self) -> None:
        """验证当工具已执行完毕返回 ToolMessage 后收尾 LLM 抛出 429 时，tool_calls 与 tool 消息已完成落库。"""
        saved_messages = []
        fake_db = MagicMock()
        fake_db.create_message = AsyncMock(
            side_effect=lambda sid, role, msg_str: saved_messages.append((role, json.loads(msg_str)))
        )
        fake_ws = AsyncMock()

        class _FakeCompiledSwarm:
            async def astream(self, state, config=None, stream_mode=None):
                ai_chunk = AIMessageChunk(
                    content="正在修改海报",
                    name="image_creator",
                    tool_calls=[
                        {
                            "name": "image_edit_sensenova_u16",
                            "args": {"image_1": "in.png"},
                            "id": "call_p1_001",
                            "type": "tool_call",
                        }
                    ],
                )
                yield ("messages", (ai_chunk, {}))
                tool_msg = ToolMessage(
                    content="workflow executed successfully ![id: out.png](/api/file/out.png)",
                    tool_call_id="call_p1_001",
                    name="image_edit_sensenova_u16",
                )
                yield ("messages", (tool_msg, {}))
                raise RuntimeError("Error code: 429 - concurrency allocated quota exceeded")

        fake_swarm = MagicMock()
        fake_swarm.compile.return_value = _FakeCompiledSwarm()

        processor = StreamProcessor("sess_p1", fake_db, fake_ws)
        with self.assertRaises(RuntimeError):
            await processor.process_stream(
                fake_swarm,
                [{"role": "user", "content": "修改这张海报"}],
                {},
            )

        self.assertEqual(len(saved_messages), 2)
        self.assertEqual(saved_messages[0][0], "assistant")
        self.assertEqual(saved_messages[0][1]["name"], "image_creator")
        self.assertEqual(
            saved_messages[0][1]["tool_calls"][0]["function"]["name"],
            "image_edit_sensenova_u16",
        )
        self.assertEqual(saved_messages[1][0], "tool")
        self.assertIn("out.png", saved_messages[1][1]["content"])

    async def test_stream_processor_deduplicates_when_values_chunk_arrives_normally(self) -> None:
        """验证正常完成时外层 values 不会重复插入已即时落库的工具请求与工具返回消息。"""
        saved_messages = []
        fake_db = MagicMock()
        fake_db.create_message = AsyncMock(
            side_effect=lambda sid, role, msg_str: saved_messages.append((role, json.loads(msg_str)))
        )
        fake_ws = AsyncMock()

        class _FakeCompiledSwarm:
            async def astream(self, state, config=None, stream_mode=None):
                ai_chunk = AIMessageChunk(
                    content="",
                    name="image_creator",
                    tool_calls=[
                        {
                            "name": "text2image_minimax_h3",
                            "args": {"positive_prompt": "tea"},
                            "id": "call_p1_002",
                            "type": "tool_call",
                        }
                    ],
                )
                yield ("messages", (ai_chunk, {}))
                tool_msg = ToolMessage(
                    content="workflow executed successfully ![id: tea.png](/api/file/tea.png)",
                    tool_call_id="call_p1_002",
                    name="text2image_minimax_h3",
                )
                yield ("messages", (tool_msg, {}))
                yield (
                    "values",
                    {
                        "messages": [
                            HumanMessage(content="生图"),
                            AIMessage(
                                content="",
                                name="image_creator",
                                tool_calls=[
                                    {
                                        "name": "text2image_minimax_h3",
                                        "args": {"positive_prompt": "tea"},
                                        "id": "call_p1_002",
                                        "type": "tool_call",
                                    }
                                ],
                            ),
                            tool_msg,
                            AIMessage(content="已生成完成！", name="image_creator"),
                        ]
                    },
                )

        fake_swarm = MagicMock()
        fake_swarm.compile.return_value = _FakeCompiledSwarm()

        processor = StreamProcessor("sess_p1_ok", fake_db, fake_ws)
        await processor.process_stream(fake_swarm, [{"role": "user", "content": "生图"}], {})

        roles = [r for r, _ in saved_messages]
        self.assertEqual(roles, ["assistant", "tool", "assistant"])
        self.assertEqual(saved_messages[2][1]["content"], "已生成完成！")

    async def test_intermediate_loadvideo_and_preview_outputs_are_filtered_out(self) -> None:
        """验证存在 SaveVideo 节点时，LoadVideo 与 PreviewImage 的中间预览输出不会混入结果。"""
        wf = {
            "73": {"class_type": "LoadVideo", "inputs": {"file": "in.mp4"}},
            "80": {"class_type": "PreviewImage", "inputs": {}},
            "76": {"class_type": "SaveVideo", "inputs": {"filename_prefix": "video/out"}},
        }
        allowed = resolve_allowed_output_node_ids(wf)
        self.assertEqual(allowed, {"76"})

        hist_record = {
            "outputs": {
                "73": {"videos": [{"filename": "preview_input.mp4", "type": "temp"}]},
                "80": {"images": [{"filename": "debug_frame.png", "type": "temp"}]},
                "76": {"videos": [{"filename": "upscaled_2k.mp4", "subfolder": "video", "type": "output"}]},
            }
        }
        urls = history_output_urls(hist_record, "http://127.0.0.1:8188", workflow=wf)
        self.assertEqual(len(urls), 1)
        self.assertIn("upscaled_2k.mp4", urls[0])

        exec_obj = WorkflowExecution(wf, "http://127.0.0.1:8188", False, None, False)
        await exec_obj.on_executed(
            {"node": "73", "output": {"videos": [{"filename": "preview_input.mp4", "type": "temp"}]}}
        )
        await exec_obj.on_executed(
            {"node": "76", "output": {"videos": [{"filename": "upscaled_2k.mp4", "type": "output"}]}}
        )
        self.assertEqual(len(exec_obj.outputs), 1)
        self.assertIn("upscaled_2k.mp4", exec_obj.outputs[0])

    async def test_auto_free_memory_triggers_only_when_model_family_switches(self) -> None:
        """验证同一实例连续跑同家族模型不触发 /api/free，切换到新模型家族时自动请求 /api/free。"""
        self.assertEqual(
            infer_workflow_model_family(
                "text2image_sensenova_u16",
                {"1": {"inputs": {"unet_name": "sensenova_u1.6_8b.safetensors"}}},
            ),
            "sensenova",
        )
        self.assertEqual(
            infer_workflow_model_family(
                "image2video_first_frame_minimax_h3",
                {"1": {"inputs": {"unet_name": "minimax_h3_fl2va_pruned_int8.safetensors"}}},
            ),
            "minimax_h3_video",
        )

        svc = ComfyInstanceService()
        post_mock = AsyncMock(return_value=MagicMock(status_code=200))

        class _FakeClientCtx:
            async def __aenter__(self):
                m = MagicMock()
                m.post = post_mock
                return m

            async def __aexit__(self, *args):
                return False

        with patch("services.comfy_instance_service.HttpClient.create", return_value=_FakeClientCtx()):
            # 首次运行无前序家族，不触发释放
            r1 = await svc.maybe_free_memory_on_family_switch(
                "inst1", "https://colab.patdelphi.xyz", "sensenova", auto_free=True
            )
            # 同家族连续运行，不触发释放
            r2 = await svc.maybe_free_memory_on_family_switch(
                "inst1", "https://colab.patdelphi.xyz", "sensenova", auto_free=True
            )
            # 切换到 minimax_h3_image，触发 /api/free
            r3 = await svc.maybe_free_memory_on_family_switch(
                "inst1", "https://colab.patdelphi.xyz", "minimax_h3_image", auto_free=True
            )

        self.assertFalse(r1)
        self.assertFalse(r2)
        self.assertTrue(r3)
        self.assertEqual(post_mock.await_count, 1)


if __name__ == "__main__":
    unittest.main()
