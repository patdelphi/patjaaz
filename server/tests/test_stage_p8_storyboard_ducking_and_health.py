"""程序说明：覆盖阶段 P8 一键剧本拆镜铺板（P8-1）、背景配乐循环与人声侧链自动闪避混音（P8-2）及画布媒体完整性健康巡检（P8-3）单测。"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from services.canvas_health_service import inspect_canvas_media_health
from services.db_service import DatabaseService
from services.file_mapping_service import record_file_mapping
from services.storyboard_planner_service import plan_and_layout_storyboard_on_canvas
from services.video_compose_service import probe_video_clip_info, resolve_ffmpeg_binary
from tools.storyboard_tools import canvas_plan_storyboard_tool
from tools.video_edit_tools import video_edit_and_stitch_tool


class StageP8StoryboardDuckingAndHealthTests(unittest.IsolatedAsyncioTestCase):
    async def test_p8_1_plan_storyboard_creates_bible_lanes_block_arrows_and_srt_quotes(self) -> None:
        """验证多行大纲自动提取引号台词，并在画布生成角色设定框、分镜泳道、闭合块箭头与递增角标（P8-1）。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_db = DatabaseService(os.path.join(tmpdir, "p8_1.db"))
            await temp_db.create_canvas("cv_sb", "拆镜测试画布")

            with patch("services.storyboard_planner_service.db_service", temp_db):
                res = await plan_and_layout_storyboard_on_canvas(
                    "cv_sb",
                    film_title="雨夜茶亭",
                    character_anchor_desc="青衫侠客与素衣茶师，冷雨暖灯对比",
                    raw_script=(
                        "1. 青石巷夜雨滂沱，侠客缓步推门，“风急雨寒，借一盏热茶。”\n"
                        "2. 茶师执壶注水，茶汤泛起细密白沫\n"
                        "3. 窗外孤舟远去，“此去山高水长，珍重。”"
                    ),
                    shot_duration_sec=15.0,
                )
                self.assertEqual(res["shot_count"], 3)
                self.assertEqual(res["total_duration_sec"], 45.0)
                self.assertEqual(len(res["subtitles"]), 2)
                self.assertEqual(res["subtitles"][0]["text"], "风急雨寒，借一盏热茶。")

                tool_out = await canvas_plan_storyboard_tool.ainvoke(
                    {
                        "film_title": "竹林听风",
                        "raw_script": "翠竹摇曳\n古琴轻拨",
                        "shot_duration_sec": 10.0,
                    },
                    config={"configurable": {"canvas_id": "cv_sb", "session_id": ""}},
                )
                self.assertIn("canvas_plan_storyboard executed successfully", tool_out)

            cv = await temp_db.get_canvas_data("cv_sb")
            elems = (cv or {}).get("data", {}).get("elements", [])
            frames = [e for e in elems if e.get("type") == "frame"]
            block_arrows = [
                e for e in elems if (e.get("customData") or {}).get("kind") == "block-arrow"
            ]
            badges = [
                e for e in elems if (e.get("customData") or {}).get("jaazType") == "callout-badge"
            ]
            # 第一次 1+3=4 个 frame、2 个块箭头、3 个角标；第二次 1+2=3 个 frame、1 个块箭头、2 个角标
            self.assertEqual(len(frames), 7)
            self.assertEqual(len(block_arrows), 3)
            self.assertEqual(len(badges), 5)

    async def test_p8_2_real_ffmpeg_bgm_loop_and_sidechain_ducking_mix(self) -> None:
        """验证较短背景配乐自动循环对齐成片总时长，并经 sidechaincompress 人声侧链自动闪避混音成功（P8-2）。"""
        ffmpeg_bin = resolve_ffmpeg_binary()
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_db = DatabaseService(os.path.join(tmpdir, "p8_2.db"))
            await temp_db.create_canvas("cv_duck", "闪避混音画布")

            clip_p = os.path.join(tmpdir, "dlg_shot.mp4")
            bgm_p = os.path.join(tmpdir, "short_bgm.mp3")
            subprocess.run(
                [
                    ffmpeg_bin,
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=darkslategray:s=320x180:r=24:d=2.2",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=520:sample_rate=48000:duration=2.2",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    clip_p,
                ],
                check=True,
                capture_output=True,
            )
            # 生成仅 0.7 秒的短配乐，验证 aloop 自动循环填充至 2.2 秒
            subprocess.run(
                [
                    ffmpeg_bin,
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=220:sample_rate=48000:duration=0.7",
                    "-c:a",
                    "libmp3lame",
                    bgm_p,
                ],
                check=True,
                capture_output=True,
            )

            with (
                patch("services.video_compose_service.FILES_DIR", tmpdir),
                patch("services.video_compose_service.db_service", temp_db),
            ):
                out_msg = await video_edit_and_stitch_tool.ainvoke(
                    {
                        "video_files": ["dlg_shot.mp4"],
                        "preserve_clip_audio": True,
                        "bgm_audio": "short_bgm.mp3",
                        "bgm_volume": 0.30,
                        "enable_audio_ducking": True,
                        "normalize_audio_loudness": True,
                    },
                    config={"configurable": {"canvas_id": "cv_duck", "session_id": ""}},
                )
                self.assertIn("video_edit_and_stitch executed successfully", out_msg)
                self.assertIn("has_audio=True", out_msg)

                cv = await temp_db.get_canvas_data("cv_duck")
                fid = list((cv or {}).get("data", {}).get("files", {}).values())[0][
                    "dataURL"
                ].split("/api/file/")[1]
                meta = probe_video_clip_info(os.path.join(tmpdir, fid), ffmpeg_bin)
                self.assertTrue(meta["has_audio"])
                self.assertAlmostEqual(meta["duration"], 2.2, delta=0.25)

    async def test_p8_3_canvas_media_health_detects_present_missing_and_drive_mapping(self) -> None:
        """验证画布完整性巡检准确统计本地就绪媒体、缺失媒体及云盘备份覆盖数（P8-3）。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_db = DatabaseService(os.path.join(tmpdir, "p8_3.db"))
            csv_p = os.path.join(tmpdir, "file_mappings.csv")
            ok_img = os.path.join(tmpdir, "present_ok.png")
            with open(ok_img, "wb") as f:
                f.write(b"\x89PNG\r\n\x1a\n12345678")

            record_file_mapping(
                "present_ok.png",
                google_drive_path=r"H:\我的云端硬盘\comfyui\output\sensenova\ok.png",
                canvas_id="cv_h",
                csv_path=csv_p,
            )

            await temp_db.create_canvas("cv_h", "巡检测试画布")
            await temp_db.save_canvas_data(
                "cv_h",
                json.dumps(
                    {
                        "elements": [
                            {
                                "id": "e1",
                                "type": "image",
                                "fileId": "f1",
                                "customData": {"workflowName": "text2image_sensenova_u16"},
                            },
                            {
                                "id": "e2",
                                "type": "embeddable",
                                "link": "/api/file/missing_vid.mp4",
                            },
                        ],
                        "files": {
                            "f1": {"id": "f1", "dataURL": "/api/file/present_ok.png"}
                        },
                    }
                ),
            )

            report = await inspect_canvas_media_health(
                "cv_h", files_dir=tmpdir, db=temp_db, csv_path=csv_p
            )
            self.assertFalse(report["healthy"])
            self.assertEqual(report["total_media_elements"], 2)
            self.assertEqual(report["present_count"], 1)
            self.assertEqual(report["missing_count"], 1)
            self.assertEqual(report["drive_mapped_count"], 1)
            self.assertEqual(report["missing_files"][0]["filename"], "missing_vid.mp4")

    def test_p8_modules_stay_under_600_lines(self) -> None:
        """验证阶段 P8 新增与修改的后端模块均不超过 600 行（R-17 延续约束）。"""
        server_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for rel in (
            "services/video_compose_service.py",
            "services/video_finishing_service.py",
            "services/storyboard_planner_service.py",
            "services/canvas_health_service.py",
            "routers/studio_router.py",
            "routers/studio_p8_routes.py",
            "tools/storyboard_tools.py",
            "tools/video_edit_tools.py",
        ):
            full_p = os.path.join(server_root, rel)
            with open(full_p, "r", encoding="utf-8") as f:
                cnt = sum(1 for _ in f)
            self.assertLessEqual(cnt, 600, f"{rel} has {cnt} lines (> 600)")


if __name__ == "__main__":
    unittest.main()
