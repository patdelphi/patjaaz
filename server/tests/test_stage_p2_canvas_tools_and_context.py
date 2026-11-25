"""程序说明：覆盖阶段 P2 画布原生排版连线工具（A2）、序号角标指向定位注入（A3）与长会话历史滑窗折叠（A9）单元测试。"""
import json
import unittest
from unittest.mock import AsyncMock, patch

from services.langgraph_service.canvas_context import build_canvas_scene_context
from services.langgraph_service.context_compactor import compact_chat_history
from tools.canvas_tools import (
    canvas_arrange_elements_tool,
    canvas_connect_and_badge_tool,
)


class StageP2CanvasToolsAndContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_canvas_arrange_and_connect_badge_tools_mutate_and_broadcast(self) -> None:
        """验证 Agent 调用画布排版与连线角标工具可创建分镜框、重排媒体并建立带标签箭头与角标。"""
        canvas_state = {
            "data": {
                "elements": [
                    {
                        "id": "im_01",
                        "type": "image",
                        "x": 0,
                        "y": 0,
                        "width": 1000,
                        "height": 1000,
                        "fileId": "im_01",
                        "isDeleted": False,
                    },
                    {
                        "id": "im_02",
                        "type": "image",
                        "x": 1200,
                        "y": 0,
                        "width": 1000,
                        "height": 1000,
                        "fileId": "im_02",
                        "isDeleted": False,
                    },
                ],
                "files": {
                    "im_01": {"id": "im_01", "dataURL": "/api/file/shot1.png", "mimeType": "image/png"},
                    "im_02": {"id": "im_02", "dataURL": "/api/file/shot2.png", "mimeType": "image/png"},
                },
            }
        }
        broadcasts = []

        async def _fake_save(cid, data_str, thumbnail=None):
            canvas_state["data"] = json.loads(data_str)
            return True

        with (
            patch("tools.canvas_tools.db_service.get_canvas_data", AsyncMock(side_effect=lambda cid: canvas_state)),
            patch("tools.canvas_tools.db_service.save_canvas_data", AsyncMock(side_effect=_fake_save)),
            patch(
                "tools.canvas_tools.broadcast_session_update",
                AsyncMock(side_effect=lambda sid, cid, p: broadcasts.append(p)),
            ),
        ):
            cfg = {"configurable": {"canvas_id": "cv_p2", "session_id": "s_p2"}}
            await canvas_arrange_elements_tool.ainvoke(
                {
                    "name": "canvas_arrange_elements",
                    "args": {
                        "action": "create_frame",
                        "title_or_text": "01 · 分镜泳道",
                        "x": 100,
                        "y": 100,
                        "width": 1400,
                        "height": 800,
                    },
                    "id": "tc_arr_1",
                    "type": "tool_call",
                },
                config=cfg,
            )
            await canvas_arrange_elements_tool.ainvoke(
                {
                    "name": "canvas_arrange_elements",
                    "args": {
                        "action": "grid_layout",
                        "target_refs": ["shot1.png", "shot2.png"],
                        "frame_ref": "01 · 分镜泳道",
                        "columns": 2,
                        "width": 500,
                    },
                    "id": "tc_arr_2",
                    "type": "tool_call",
                },
                config=cfg,
            )
            await canvas_connect_and_badge_tool.ainvoke(
                {
                    "name": "canvas_connect_and_badge",
                    "args": {
                        "source_ref": "shot1.png",
                        "target_ref": "shot2.png",
                        "arrow_label": "单图改图",
                        "badge_target_ref": "shot2.png",
                        "badge_rel_x": 0.88,
                        "badge_rel_y": 0.85,
                    },
                    "id": "tc_con_1",
                    "type": "tool_call",
                },
                config=cfg,
            )

        elems = canvas_state["data"]["elements"]
        self.assertTrue(any(e["type"] == "frame" for e in elems))
        self.assertTrue(any(e["type"] == "arrow" for e in elems))
        self.assertEqual(len(broadcasts), 3)
        self.assertEqual(broadcasts[-1]["type"], "canvas_elements_updated")

        # 验证 A3：序号角标落点被精准解析为 shot2.png 的右下角区域
        ctx_text = build_canvas_scene_context(canvas_state["data"])
        self.assertIn('标注 #1', ctx_text)
        self.assertIn('指向图像 file_id="shot2.png" 的右下角区域', ctx_text)

    def test_context_compactor_folds_old_turns_while_preserving_tool_ids_and_media_links(self) -> None:
        """验证长会话压缩折叠早期超长提示词与计划，同时完整保留 tool_call_id 配对和媒体链接。"""
        long_prompt = "江南烟雨茶馆细节描述 " * 60
        messages = [
            {"role": "user", "content": "第1轮需求"},
            {
                "role": "assistant",
                "name": "planner",
                "content": "",
                "tool_calls": [
                    {
                        "id": "tc_plan_1",
                        "type": "function",
                        "function": {
                            "name": "write_plan",
                            "arguments": json.dumps(
                                {"steps": [{"title": "生成底图", "description": "非常长的步骤解释" * 30}]},
                                ensure_ascii=False,
                            ),
                        },
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "tc_plan_1", "name": "write_plan", "content": "Plan made."},
            {
                "role": "assistant",
                "name": "image_creator",
                "content": "早期超长说明" * 120 + " ![id: early_out.png](/api/file/early_out.png)",
                "tool_calls": [
                    {
                        "id": "tc_img_1",
                        "type": "function",
                        "function": {
                            "name": "text2image_minimax_h3",
                            "arguments": json.dumps(
                                {"positive_prompt": long_prompt, "aspect_ratio": "16:9 (Widescreen)"},
                                ensure_ascii=False,
                            ),
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "tc_img_1",
                "name": "text2image_minimax_h3",
                "content": "workflow executed successfully ![id: early_out.png](/api/file/early_out.png)",
            },
            {"role": "user", "content": "最近一轮完整保留：" + long_prompt},
            {"role": "assistant", "name": "image_creator", "content": "最近回复完整保留"},
        ]

        compacted = compact_chat_history(messages, keep_recent_messages=2, max_old_arg_chars=80, max_old_text_chars=100)
        self.assertEqual(len(compacted), len(messages))
        # 早期 write_plan 的冗长 description 被剥离，仅保留 title
        plan_args = json.loads(compacted[1]["tool_calls"][0]["function"]["arguments"])
        self.assertEqual(plan_args["steps"], [{"title": "生成底图"}])
        # 早期生图调用保留 aspect_ratio 且截断超长 positive_prompt
        img_args = json.loads(compacted[3]["tool_calls"][0]["function"]["arguments"])
        self.assertEqual(img_args["aspect_ratio"], "16:9 (Widescreen)")
        self.assertLess(len(img_args["positive_prompt"]), 120)
        # 早期回复截断但仍保留 /api/file/early_out.png 标签
        self.assertIn("/api/file/early_out.png", compacted[3]["content"])
        # 最近 2 条消息原封不动保留
        self.assertEqual(compacted[-2]["content"], messages[-2]["content"])


if __name__ == "__main__":
    unittest.main()
