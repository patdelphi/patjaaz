"""程序说明：覆盖阶段 P6 多源离线兜底语音合成与视频音轨剥离（P6-2）、L4+T4 异构双实例自动分流调度（P6-3）及短片制片工程包 ZIP 归档（P6-4）单测。"""
from __future__ import annotations

import io
import json
import os
import subprocess
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
import zipfile

from services.comfy_instance_service import ComfyInstanceService
from services.db_service import DatabaseService
from services.file_mapping_service import record_file_mapping
from services.gpu_compatibility_guard import GiB
from services.project_bundle_service import build_canvas_project_bundle_zip
from services.video_compose_service import probe_video_clip_info, resolve_ffmpeg_binary
from tools.audio_tools import (
    extract_video_audio_tool,
    synthesize_speech_narration_tool,
)


class StageP6HeterogeneousAudioBundleTests(unittest.IsolatedAsyncioTestCase):
    async def test_p6_2_offline_tts_fallback_and_video_audio_extraction(self) -> None:
        """验证无云端语音密钥时自动回退本机离线中文语音引擎产出 MP3，并支持从视频剥离立体声音轨卡片（P6-2）。"""
        ffmpeg_bin = resolve_ffmpeg_binary()
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_db = DatabaseService(os.path.join(tmpdir, "p6_2.db"))
            await temp_db.create_canvas("cv_aud", "配音与音轨测试画布")

            src_vid = os.path.join(tmpdir, "rain_scene.mp4")
            subprocess.run(
                [
                    ffmpeg_bin,
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=teal:s=320x180:r=24:d=1.4",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=528:sample_rate=48000:duration=1.4",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    src_vid,
                ],
                check=True,
                capture_output=True,
            )

            with (
                patch("services.local_audio_service.FILES_DIR", tmpdir),
                patch("services.local_audio_service.db_service", temp_db),
                patch(
                    "services.local_audio_service.record_file_mapping",
                    lambda *a, **kw: {},
                ),
                patch(
                    "services.local_audio_service.config_service.get_config",
                    return_value={},
                ),
            ):
                if os.name == "nt":
                    tts_msg = await synthesize_speech_narration_tool.ainvoke(
                        {"text": "夜雨挑灯，一盏江湖。"},
                        config={"configurable": {"canvas_id": "cv_aud", "session_id": ""}},
                    )
                    self.assertIn("synthesize_speech_narration executed successfully", tts_msg)
                    self.assertIn("backend=local_windows_sapi", tts_msg)

                ext_msg = await extract_video_audio_tool.ainvoke(
                    {"video_file": "rain_scene.mp4", "normalize_loudness": True},
                    config={"configurable": {"canvas_id": "cv_aud", "session_id": ""}},
                )
                self.assertIn("extract_video_audio executed successfully", ext_msg)

                cv = await temp_db.get_canvas_data("cv_aud")
                files_map = (cv or {}).get("data", {}).get("files", {})
                self.assertGreaterEqual(len(files_map), 1)
                for fitem in files_map.values():
                    fname = fitem["dataURL"].split("/api/file/")[1]
                    meta = probe_video_clip_info(os.path.join(tmpdir, fname), ffmpeg_bin)
                    self.assertTrue(meta["has_audio"])
                    self.assertGreater(meta["duration"], 0.3)

    async def test_p6_3_heterogeneous_dual_instance_routing_l4_and_t4(self) -> None:
        """验证同时配置 L4 与 T4 时：重型 NVFP4 工作流路由至 L4，SeedVR2 超分优先分流至在线 T4，T4 离线时自动回退 L4（P6-3）。"""
        t4_health = json.dumps(
            {
                "online": True,
                "devices": [{"name": "cuda:0 Tesla T4", "vram_total": int(14.56 * GiB)}],
            }
        )
        l4_health = json.dumps(
            {
                "online": True,
                "devices": [{"name": "cuda:0 NVIDIA L4", "vram_total": int(22.49 * GiB)}],
            }
        )
        svc = ComfyInstanceService()

        # 场景 1：T4 优先级数值更小（priority=10），L4 为 50 -> 重型 H3 / SenseNova 仍自动避开 T4 选 L4
        pool_t4_first = [
            {
                "id": "colab_t4",
                "name": "T4 Worker",
                "base_url": "https://t4.example.com",
                "enabled": 1,
                "priority": 10,
                "capabilities_json": "[]",
                "last_health_json": t4_health,
            },
            {
                "id": "colab_l4",
                "name": "L4 Main",
                "base_url": "https://l4.example.com",
                "enabled": 1,
                "priority": 50,
                "capabilities_json": "[]",
                "last_health_json": l4_health,
            },
        ]
        with patch.object(svc, "ensure_default_instance", AsyncMock(return_value=pool_t4_first)):
            picked_h3 = await svc.resolve_instance(
                capability="t2v", workflow_name="text2video_minimax_h3"
            )
            self.assertEqual(picked_h3["id"], "colab_l4")
            picked_sn = await svc.resolve_instance(
                capability="t2i", workflow_name="text2image_sensenova_u16"
            )
            self.assertEqual(picked_sn["id"], "colab_l4")

        # 场景 2：L4 排在前面（priority=10），T4 为 50 -> SeedVR2 超分自动分流至在线 T4 释放 L4 队列
        pool_l4_first = [pool_t4_first[1], pool_t4_first[0]]
        with patch.object(svc, "ensure_default_instance", AsyncMock(return_value=pool_l4_first)):
            picked_up = await svc.resolve_instance(
                capability="i2v", workflow_name="video_upscale_seedvr2_3b"
            )
            self.assertEqual(picked_up["id"], "colab_t4")

        # 场景 3：T4 断线（online=False）-> SeedVR2 自动回退到在线 L4
        offline_t4 = dict(pool_t4_first[0])
        offline_t4["last_health_json"] = json.dumps({"online": False, "devices": []})
        with patch.object(
            svc, "ensure_default_instance", AsyncMock(return_value=[pool_t4_first[1], offline_t4])
        ):
            picked_fallback = await svc.resolve_instance(
                capability="i2v", workflow_name="video_upscale_seedvr2_3b"
            )
            self.assertEqual(picked_fallback["id"], "colab_l4")

    async def test_p6_4_project_bundle_zip_export_formats_and_media(self) -> None:
        """验证画布工程包 ZIP 包含合法的 canvas.json、UTF-8 BOM+CRLF 制片单/映射表/SRT 字幕草稿及关联媒体文件（P6-4）。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_db = DatabaseService(os.path.join(tmpdir, "p6_4.db"))
            csv_path = os.path.join(tmpdir, "file_mappings.csv")
            media_file = os.path.join(tmpdir, "shot_master.mp4")
            with open(media_file, "wb") as mf:
                mf.write(b"FAKE_MP4_STREAM_PAYLOAD")

            record_file_mapping(
                "shot_master.mp4",
                comfy_output_relpath="video/MiniMax_001.mp4",
                google_drive_path=r"H:\我的云端硬盘\comfyui\output\video\MiniMax_001.mp4",
                canvas_id="cv_bundle",
                workflow_name="text2video_minimax_h3",
                csv_path=csv_path,
            )

            await temp_db.create_canvas("cv_bundle", "江南夜雨短片")
            await temp_db.save_canvas_data(
                "cv_bundle",
                json.dumps(
                    {
                        "elements": [
                            {"id": "fr1", "type": "frame", "name": "第一幕 · 夜雨入巷"},
                            {"id": "tx1", "type": "text", "text": "青石板映着暖黄灯笼微光。"},
                            {
                                "id": "vid1",
                                "type": "embeddable",
                                "width": 1856,
                                "height": 1024,
                                "link": "/api/file/shot_master.mp4",
                                "customData": {
                                    "jaazLineage": {
                                        "workflowName": "video_upscale_chunked",
                                        "capability": "video_upscale",
                                        "prompt": "SeedVR2 2x 全高清成片",
                                        "parentFileIds": [],
                                        "params": {"scale_multiplier": 2.0},
                                    }
                                },
                            },
                        ],
                        "files": {},
                    }
                ),
            )

            bundle = await build_canvas_project_bundle_zip(
                "cv_bundle",
                include_media=True,
                files_dir=tmpdir,
                db=temp_db,
                csv_path=csv_path,
            )
            self.assertEqual(bundle["filename"], "jaaz_bundle_cv_bundle.zip")
            self.assertEqual(bundle["media_count"], 1)

            with zipfile.ZipFile(io.BytesIO(bundle["zip_bytes"]), "r") as zf:
                names = set(zf.namelist())
                self.assertIn("canvas.json", names)
                self.assertIn("production_sheet.md", names)
                self.assertIn("file_mappings.csv", names)
                self.assertIn("subtitles_draft.srt", names)
                self.assertIn("media/shot_master.mp4", names)

                for doc_name in ("production_sheet.md", "file_mappings.csv", "subtitles_draft.srt"):
                    raw = zf.read(doc_name)
                    self.assertTrue(raw.startswith(b"\xef\xbb\xbf"), f"Missing BOM in {doc_name}")
                    body = raw[3:]
                    self.assertEqual(body.count(b"\n"), body.count(b"\r\n"), f"LF found in {doc_name}")

                sheet_txt = zf.read("production_sheet.md").decode("utf-8-sig")
                self.assertIn("江南夜雨短片", sheet_txt)
                self.assertIn("video_upscale_chunked", sheet_txt)

    def test_p6_modules_stay_under_600_lines(self) -> None:
        """验证阶段 P6 新增与修改的后端模块均不超过 600 行（R-17 延续约束）。"""
        server_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for rel in (
            "services/comfy_instance_service.py",
            "services/local_audio_service.py",
            "services/project_bundle_service.py",
            "routers/studio_router.py",
            "routers/studio_p5_routes.py",
            "tools/audio_tools.py",
        ):
            full_p = os.path.join(server_root, rel)
            with open(full_p, "r", encoding="utf-8") as f:
                cnt = sum(1 for _ in f)
            self.assertLessEqual(cnt, 600, f"{rel} has {cnt} lines (> 600)")


if __name__ == "__main__":
    unittest.main()
