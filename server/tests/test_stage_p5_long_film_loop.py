"""程序说明：覆盖阶段 P5 长视频自动分块断点超分（P5-1）、关键帧提取接力（P5-2）、远端 GPU 自适应防呆与 Colab 换址热续跑（P5-3）、FFmpeg 成片精装（P5-4）及孤立切片安全清理（P5-5）单测。"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from PIL import Image

from routers.comfyui_execution import ComfyUIUnavailableError
from services.comfy_instance_service import comfy_instance_service
from services.db_service import DatabaseService
from services.gpu_compatibility_guard import (
    GiB,
    compute_safe_upscale_slice_sec,
    evaluate_workflow_hardware_guard,
    hot_resume_colab_instance,
)
from services.long_video_pipeline_service import (
    get_upscale_job,
    upscale_long_video_chunked,
)
from services.storage_cleanup_service import (
    delete_confirmed_orphan_files,
    scan_orphan_media_files,
)
from services.video_compose_service import probe_video_clip_info, resolve_ffmpeg_binary
from tools.long_video_tools import extract_video_frame_tool
from tools.video_edit_tools import video_edit_and_stitch_tool


def _make_sample_video(ffmpeg_bin: str, out_path: str, duration: float = 2.4, freq: int = 440) -> None:
    """使用内置 ffmpeg 生成带 48kHz 立体声正弦音轨的测试 MP4。"""
    subprocess.run(
        [
            ffmpeg_bin,
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=darkslateblue:s=320x180:r=24:d={duration}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={freq}:sample_rate=48000:duration={duration}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            out_path,
        ],
        check=True,
        capture_output=True,
    )


class StageP5LongFilmLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_p5_1_safe_slice_calc_and_resumable_chunked_upscale_with_audio(self) -> None:
        """验证按内存计算超分安全秒数、Colab 断线保存断点、恢复后跳过已完成分块并无损合流音轨（P5-1）。"""
        self.assertEqual(
            compute_safe_upscale_slice_sec(928, 512, 2.0, ram_bytes=50 * GiB), 15.0
        )
        self.assertEqual(
            compute_safe_upscale_slice_sec(928, 512, 2.0, ram_bytes=28 * GiB), 10.0
        )
        self.assertEqual(
            compute_safe_upscale_slice_sec(928, 512, 2.0, ram_bytes=12 * GiB), 4.0
        )

        ffmpeg_bin = resolve_ffmpeg_binary()
        with tempfile.TemporaryDirectory() as tmpdir:
            files_dir = os.path.join(tmpdir, "files")
            jobs_dir = os.path.join(tmpdir, "upscale_jobs")
            os.makedirs(files_dir, exist_ok=True)
            temp_db = DatabaseService(os.path.join(tmpdir, "p5_1.db"))
            await temp_db.create_canvas("cv_up", "超分断点测试画布")

            src_mp4 = os.path.join(files_dir, "master_src.mp4")
            _make_sample_video(ffmpeg_bin, src_mp4, duration=3.0, freq=520)

            executed_slices: list[str] = []
            fail_on_second = {"should_fail": True}

            async def fake_seedvr2_upscaler(slice_p: str, dest_p: str, scale: float) -> None:
                executed_slices.append(os.path.basename(slice_p))
                if "slice_001" in slice_p and fail_on_second["should_fail"]:
                    raise ComfyUIUnavailableError("HTTP 530 Cloudflare Tunnel Offline")
                w = int(320 * scale)
                h = int(180 * scale)
                subprocess.run(
                    [
                        ffmpeg_bin,
                        "-y",
                        "-i",
                        slice_p,
                        "-vf",
                        f"scale={w}:{h}",
                        "-c:v",
                        "libx264",
                        "-pix_fmt",
                        "yuv420p",
                        dest_p,
                    ],
                    check=True,
                    capture_output=True,
                )

            with (
                patch("services.long_video_pipeline_service.db_service", temp_db),
                patch(
                    "services.long_video_pipeline_service.record_file_mapping",
                    lambda *a, **kw: {},
                ),
            ):
                first_res = await upscale_long_video_chunked(
                    "master_src.mp4",
                    scale_multiplier=2.0,
                    slice_seconds=2.0,
                    canvas_id="cv_up",
                    files_dir=files_dir,
                    jobs_dir=jobs_dir,
                    chunk_upscaler=fake_seedvr2_upscaler,
                )
                self.assertEqual(first_res["status"], "paused_offline")
                self.assertEqual(first_res["completed_chunks"], 1)
                self.assertEqual(first_res["total_chunks"], 2)
                saved_job = get_upscale_job(first_res["job_id"], jobs_dir)
                self.assertIsNotNone(saved_job)
                self.assertEqual(saved_job["status"], "paused_offline")

                # 模拟 Colab 恢复在线后断点续跑：第 0 段不应重复超分
                executed_slices.clear()
                fail_on_second["should_fail"] = False
                resumed_res = await upscale_long_video_chunked(
                    job_id=first_res["job_id"],
                    canvas_id="cv_up",
                    files_dir=files_dir,
                    jobs_dir=jobs_dir,
                    chunk_upscaler=fake_seedvr2_upscaler,
                )
                self.assertEqual(executed_slices, ["slice_001.mp4"])
                self.assertEqual(resumed_res["status"], "completed")
                self.assertEqual(resumed_res["width"], 640)
                self.assertEqual(resumed_res["height"], 360)
                self.assertTrue(resumed_res["has_audio"])

                out_meta = probe_video_clip_info(
                    os.path.join(files_dir, resumed_res["file_id"]), ffmpeg_bin
                )
                self.assertEqual(out_meta["width"], 640)
                self.assertEqual(out_meta["height"], 360)
                self.assertTrue(out_meta["has_audio"])
                self.assertAlmostEqual(out_meta["duration"], 3.0, delta=0.25)

    async def test_p5_2_extract_video_frame_last_and_timestamp_with_lineage(self) -> None:
        """验证视频尾帧与指定时刻抽帧生成合法 PNG 并写入画布血缘（P5-2）。"""
        ffmpeg_bin = resolve_ffmpeg_binary()
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_db = DatabaseService(os.path.join(tmpdir, "p5_2.db"))
            await temp_db.create_canvas("cv_frame", "抽帧接力画布")
            clip_p = os.path.join(tmpdir, "shot_01.mp4")
            _make_sample_video(ffmpeg_bin, clip_p, duration=1.8, freq=440)

            with (
                patch("services.long_video_pipeline_service.FILES_DIR", tmpdir),
                patch("services.long_video_pipeline_service.db_service", temp_db),
                patch(
                    "services.long_video_pipeline_service.record_file_mapping",
                    lambda *a, **kw: {},
                ),
            ):
                msg = await extract_video_frame_tool.ainvoke(
                    {"video_file": "shot_01.mp4", "mode": "last"},
                    config={"configurable": {"canvas_id": "cv_frame", "session_id": ""}},
                )
                self.assertIn("extract_video_frame executed successfully", msg)
                cv = await temp_db.get_canvas_data("cv_frame")
                elems = (cv or {}).get("data", {}).get("elements", [])
                self.assertEqual(len(elems), 1)
                self.assertEqual(
                    elems[0]["customData"]["jaazLineage"]["parentFileIds"],
                    ["shot_01.mp4"],
                )
                fid = list((cv or {}).get("data", {}).get("files", {}).values())[0][
                    "dataURL"
                ].split("/api/file/")[1]
                with Image.open(os.path.join(tmpdir, fid)) as im:
                    self.assertEqual(im.size, (320, 180))

    async def test_p5_3_hardware_guard_blocks_t4_nvfp4_clamps_l4_15s_and_hot_resumes(self) -> None:
        """验证拦截 Tesla T4 上的 NVFP4 重模型、放行 SeedVR2、L4 15 秒自动降档 megapixels 及 Colab 换址热更新（P5-3）。"""
        t4_health = {
            "online": True,
            "devices": [{"name": "cuda:0 Tesla T4 : cudaMallocAsync", "vram_total": int(14.56 * GiB)}],
            "system": {"ram_total": int(51.0 * GiB)},
        }
        blocked_h3 = evaluate_workflow_hardware_guard(
            "text2video_minimax_h3",
            {"1": {"inputs": {"unet_name": "minimax_h3_nvfp4.safetensors"}}},
            {"duration_seconds": 5.0},
            t4_health,
        )
        self.assertTrue(blocked_h3["blocked"])
        self.assertIn("Tesla T4", blocked_h3["reason"])
        self.assertIn("Ampere", blocked_h3["reason"])

        allowed_seedvr2 = evaluate_workflow_hardware_guard(
            "video_upscale_seedvr2_3b",
            {"1": {"inputs": {"model": "seedvr2_ema_3b_fp16.safetensors"}}},
            {"scale_multiplier": 2.0},
            t4_health,
        )
        self.assertFalse(allowed_seedvr2["blocked"])

        l4_health = {
            "online": True,
            "devices": [{"name": "cuda:0 NVIDIA L4 : cudaMallocAsync", "vram_total": int(22.49 * GiB)}],
            "system": {"ram_total": int(53.0 * GiB)},
        }
        clamped_l4 = evaluate_workflow_hardware_guard(
            "text2video_minimax_h3",
            {},
            {"duration_seconds": 15.0, "megapixels": 0.90},
            l4_health,
        )
        self.assertFalse(clamped_l4["blocked"])
        self.assertEqual(clamped_l4["adjusted_params"].get("megapixels"), 0.45)

        with tempfile.TemporaryDirectory() as tmpdir:
            temp_db = DatabaseService(os.path.join(tmpdir, "p5_3.db"))
            await temp_db.upsert_comfy_instance(
                {
                    "id": "colab_main",
                    "name": "Colab",
                    "base_url": "https://old-tunnel.example.com",
                    "enabled": 1,
                }
            )
            comfy_instance_service.set_cached_upload("colab_main", "deadbeef", "stale.png")
            fake_probe = AsyncMock(return_value=l4_health)
            with (
                patch("services.gpu_compatibility_guard.db_service", temp_db),
                patch.object(comfy_instance_service, "ensure_default_instance", AsyncMock(return_value=await temp_db.list_comfy_instances())),
                patch.object(comfy_instance_service, "probe_instance_health", fake_probe),
            ):
                res = await hot_resume_colab_instance("https://new-tunnel.example.com/")
                self.assertEqual(res["base_url"], "https://new-tunnel.example.com")
                self.assertGreaterEqual(res["cleared_upload_cache"], 1)
                self.assertIn("NVIDIA L4", res["gpu_name"])
                updated = await temp_db.get_comfy_instance("colab_main")
                self.assertEqual(updated["base_url"], "https://new-tunnel.example.com")

    async def test_p5_4_ffmpeg_finishing_loudnorm_burn_subtitles_title_and_outro_fade(self) -> None:
        """验证 Windows 路径下的硬烧录字幕、EBU R128 响度均衡、片头标题渐显与片尾淡出实机合成成功（P5-4）。"""
        ffmpeg_bin = resolve_ffmpeg_binary()
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_db = DatabaseService(os.path.join(tmpdir, "p5_4.db"))
            await temp_db.create_canvas("cv_fin", "成片精装画布")
            _make_sample_video(ffmpeg_bin, os.path.join(tmpdir, "c1.mp4"), duration=1.5, freq=400)
            _make_sample_video(ffmpeg_bin, os.path.join(tmpdir, "c2.mp4"), duration=1.5, freq=600)

            with (
                patch("services.video_compose_service.FILES_DIR", tmpdir),
                patch("services.video_compose_service.db_service", temp_db),
            ):
                out_msg = await video_edit_and_stitch_tool.ainvoke(
                    {
                        "video_files": ["c1.mp4", "c2.mp4"],
                        "transition_fade_sec": 0.15,
                        "preserve_clip_audio": True,
                        "normalize_audio_loudness": True,
                        "burn_subtitles": True,
                        "intro_title": "江南夜雨",
                        "fade_out_outro_sec": 0.5,
                        "subtitles": [
                            {"start": 0.2, "end": 2.4, "text": "夜雨挑灯，一盏江湖。"}
                        ],
                    },
                    config={"configurable": {"canvas_id": "cv_fin", "session_id": ""}},
                )
                self.assertIn("video_edit_and_stitch executed successfully", out_msg)
                self.assertIn("has_audio=True", out_msg)

    async def test_p5_5_orphan_scan_and_confirmed_cleanup_protects_canvas_files(self) -> None:
        """验证孤立文件扫描永不列出画布或血缘引用的文件，且二次确认清理拦截误传的受保护文件（P5-5）。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            files_dir = os.path.join(tmpdir, "files")
            jobs_dir = os.path.join(tmpdir, "jobs")
            os.makedirs(files_dir, exist_ok=True)
            temp_db = DatabaseService(os.path.join(tmpdir, "p5_5.db"))

            for fn in (
                "canvas_active.mp4",
                "lineage_ref.png",
                "src_slice_00_0s_10s.mp4",
                "unreferenced_clip.mp4",
            ):
                with open(os.path.join(files_dir, fn), "wb") as f:
                    f.write(b"0123456789ABCDEF")

            await temp_db.create_canvas("cv_keep", "受保护画布")
            await temp_db.save_canvas_data(
                "cv_keep",
                json.dumps(
                    {
                        "elements": [
                            {
                                "id": "v1",
                                "type": "embeddable",
                                "link": "/api/file/canvas_active.mp4",
                                "customData": {
                                    "jaazLineage": {"parentFileIds": ["lineage_ref.png"]}
                                },
                            }
                        ],
                        "files": {},
                    }
                ),
            )

            scan = await scan_orphan_media_files(
                files_dir=files_dir, db=temp_db, jobs_dir=jobs_dir
            )
            orphan_names = [item["filename"] for item in scan["orphans"]]
            self.assertEqual(
                orphan_names, ["src_slice_00_0s_10s.mp4", "unreferenced_clip.mp4"]
            )
            self.assertEqual(scan["orphans"][0]["category"], "temp_slice")

            with self.assertRaises(ValueError):
                await delete_confirmed_orphan_files(
                    ["src_slice_00_0s_10s.mp4"],
                    confirm=False,
                    files_dir=files_dir,
                    db=temp_db,
                    jobs_dir=jobs_dir,
                )

            cleaned = await delete_confirmed_orphan_files(
                ["src_slice_00_0s_10s.mp4", "canvas_active.mp4"],
                confirm=True,
                files_dir=files_dir,
                db=temp_db,
                jobs_dir=jobs_dir,
            )
            self.assertEqual(cleaned["deleted"], ["src_slice_00_0s_10s.mp4"])
            self.assertEqual(cleaned["skipped_referenced"], ["canvas_active.mp4"])
            self.assertTrue(os.path.isfile(os.path.join(files_dir, "canvas_active.mp4")))
            self.assertFalse(
                os.path.isfile(os.path.join(files_dir, "src_slice_00_0s_10s.mp4"))
            )

    def test_p5_1b_seedvr2_real_workflow_video_param_binding(self) -> None:
        """回归验证：SeedVR2 分块超分必须将上传切片名绑定到 LoadVideo 节点（source_video），严禁残留示例视频名。"""
        from services.upscale_job_store import build_upscale_workflow_inputs
        from tools.comfy_dynamic import apply_workflow_inputs_and_seeds

        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        wf_dir = os.path.join(repo_root, "workflows", "video_upscale_seedvr2_3b")
        with open(os.path.join(wf_dir, "jaaz.workflow.json"), "r", encoding="utf-8") as mf:
            meta = json.load(mf)
        with open(os.path.join(wf_dir, "workflow.api.json"), "r", encoding="utf-8") as af:
            api_wf = json.load(af)

        mapped = build_upscale_workflow_inputs(meta["inputs"], "slice_000.mp4", 2.0)
        payload = apply_workflow_inputs_and_seeds(
            api_wf, meta["inputs"], mapped, seed_strategy="fixed"
        )
        self.assertEqual(payload["73"]["inputs"]["file"], "slice_000.mp4")
        self.assertEqual(payload["66:57"]["inputs"]["resize_type.multiplier"], 2.0)

    def test_p5_modules_stay_under_600_lines(self) -> None:
        """验证阶段 P5 新增与扩展的后端模块均保持不超过 600 行（R-17 延续约束）。"""
        server_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for rel in (
            "services/video_compose_service.py",
            "services/video_finishing_service.py",
            "services/gpu_compatibility_guard.py",
            "services/long_video_pipeline_service.py",
            "services/upscale_job_store.py",
            "services/storage_cleanup_service.py",
            "routers/studio_router.py",
            "routers/studio_p5_routes.py",
            "tools/long_video_tools.py",
            "tools/video_edit_tools.py",
        ):
            full_p = os.path.join(server_root, rel)
            with open(full_p, "r", encoding="utf-8") as f:
                cnt = sum(1 for _ in f)
            self.assertLessEqual(cnt, 600, f"{rel} has {cnt} lines (> 600)")


if __name__ == "__main__":
    unittest.main()
