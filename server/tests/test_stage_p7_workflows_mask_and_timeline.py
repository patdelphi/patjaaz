"""程序说明：覆盖阶段 P7 全量 17 套 ComfyUI 工作流包结构与校准校验（P7-1）及画布涂抹遮罩转红色高亮引导图局部重绘闭环（P7-2）单测。"""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

from services.comfy_workflow_pack import scan_workflows_dir
from tools.visual_mask_tools import prepare_visual_mask_guide_tool


class StageP7WorkflowsMaskAndTimelineTests(unittest.IsolatedAsyncioTestCase):
    def test_p7_1_all_17_workflows_pass_validation_and_calibration(self) -> None:
        """验证 workflows/ 目录下全部 17 套成对工作流均通过 schema 与节点校验，且新入库 5 套节点连线已校准（P7-1）。"""
        scan_res = scan_workflows_dir()
        self.assertEqual(scan_res["errors"], [])
        valid_by_name = {
            r["config_json"]["name"]: r for r in scan_res["valid"]
        }
        for expected_name in (
            "text2image_MOSS",
            "ImageEdit_MOSS",
            "image_multiref_moss",
            "ref2video_quad_minimax_h3_ref2va",
            "ref2video_dual_minimax_h3_r2v",
        ):
            self.assertIn(expected_name, valid_by_name, f"Missing valid pack: {expected_name}")

        self.assertGreaterEqual(len(valid_by_name), 17)

        # 验证双图 R2V 悬空连线与 8 步 LoRA 步数已修复
        r2v_api = valid_by_name["ref2video_dual_minimax_h3_r2v"]["api_json"]
        self.assertEqual(r2v_api["171"]["inputs"]["prompt"], ["138", 0])
        self.assertEqual(r2v_api["171"]["inputs"]["width"], ["115", 0])
        self.assertEqual(r2v_api["170"]["inputs"]["value"], 8)
        self.assertEqual(r2v_api["173"]["inputs"]["model"], ["167", 0])

        # 验证四元素 Ref2VA 调度器模型经过 LoRA Switch 且为 normal
        quad_api = valid_by_name["ref2video_quad_minimax_h3_ref2va"]["api_json"]
        self.assertEqual(quad_api["124"]["inputs"]["model"], ["141", 0])
        self.assertEqual(quad_api["124"]["inputs"]["scheduler"], "normal")

        # 验证 ImageEdit_MOSS 已剔除孤立 ImageCompare 节点
        moss_edit_api = valid_by_name["ImageEdit_MOSS"]["api_json"]
        self.assertNotIn("20", moss_edit_api)

    async def test_p7_2_prepare_visual_mask_guide_composites_red_highlight_and_preserves_background(self) -> None:
        """验证从 RGBA 透明挖空遮罩自动合成半透明红框视觉引导图，并准确计算方位描述（P7-2）。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            orig_p = os.path.join(tmpdir, "scene_orig.png")
            mask_p = os.path.join(tmpdir, "inpaint_mask.png")

            orig_im = Image.new("RGB", (400, 300), (30, 80, 180))
            orig_im.save(orig_p, format="PNG")

            # 模拟前端 CanvasImageTools 导出：全图不透明，仅左上角 (30, 20)-(110, 90) 涂抹区 alpha=0
            mask_im = orig_im.convert("RGBA")
            draw = ImageDraw.Draw(mask_im)
            draw.rectangle([30, 20, 110, 90], fill=(30, 80, 180, 0))
            mask_im.save(mask_p, format="PNG")

            with (
                patch("services.visual_mask_guide_service.FILES_DIR", tmpdir),
                patch(
                    "services.visual_mask_guide_service.record_file_mapping",
                    lambda *a, **kw: {},
                ),
            ):
                msg = await prepare_visual_mask_guide_tool.ainvoke(
                    {"source_image": "scene_orig.png", "mask_image": "inpaint_mask.png"}
                )
                self.assertIn("prepare_visual_mask_guide executed successfully", msg)
                self.assertIn("region=上方左侧", msg)
                self.assertIn("<Picture 2>", msg)

                guide_files = [f for f in os.listdir(tmpdir) if f.startswith("guide_")]
                self.assertEqual(len(guide_files), 1)
                with Image.open(os.path.join(tmpdir, guide_files[0])) as gim:
                    self.assertEqual(gim.size, (400, 300))
                    r_in, _, b_in = gim.getpixel((60, 50))
                    r_out, g_out, b_out = gim.getpixel((350, 260))
                    # 涂抹区内红色分量显著增强，选区外保持原始纯蓝背景不变
                    self.assertGreater(r_in, 100)
                    self.assertLess(b_in, 180)
                    self.assertEqual((r_out, g_out, b_out), (30, 80, 180))

    def test_p7_modules_stay_under_600_lines(self) -> None:
        """验证阶段 P7 新增与扩展的后端模块均不超过 600 行（R-17 延续约束）。"""
        server_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for rel in (
            "services/visual_mask_guide_service.py",
            "tools/visual_mask_tools.py",
            "routers/studio_p5_routes.py",
            "services/tool_service.py",
        ):
            full_p = os.path.join(server_root, rel)
            with open(full_p, "r", encoding="utf-8") as f:
                cnt = sum(1 for _ in f)
            self.assertLessEqual(cnt, 600, f"{rel} has {cnt} lines (> 600)")


if __name__ == "__main__":
    unittest.main()
