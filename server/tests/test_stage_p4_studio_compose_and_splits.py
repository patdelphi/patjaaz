"""程序说明：覆盖阶段 P4 跨画布资产检索（M1）、技能模板（W1）、CSV 批量展开（W2）、ffmpeg 合片命令（V4）与大文件拆分约束（R-17）单测。"""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from routers.studio_router import (
    SaveTemplateRequest,
    list_studio_templates,
    parse_batch_variables_and_expand,
    save_studio_template,
    search_studio_assets,
)
from services.db_service import DatabaseService
from services.file_mapping_service import (
    list_file_mappings,
    parse_comfy_view_url,
    record_file_mapping,
)
from services.video_compose_service import (
    build_ffmpeg_compose_command,
    build_srt_content,
    compose_storyboard_clips,
    probe_video_clip_info,
    resolve_ffmpeg_binary,
)
from tools.video_edit_tools import video_edit_and_stitch_tool
from utils.path_security import PathSecurityError


class StageP4StudioComposeAndSplitsTests(unittest.IsolatedAsyncioTestCase):
    def test_batch_csv_and_multiline_variable_expansion(self) -> None:
        """验证 CSV 表格与单列多行变量均可准确代入提示词模板（W2）。"""
        csv_text = "角色,地点\n青衣茶师,江南雨巷\n白衣琴师,竹林松亭"
        expanded = parse_batch_variables_and_expand(csv_text, "16:9 画面：{角色}在{地点}")
        self.assertEqual(len(expanded), 2)
        self.assertEqual(expanded[0]["prompt"], "16:9 画面：青衣茶师在江南雨巷")
        self.assertEqual(expanded[1]["prompt"], "16:9 画面：白衣琴师在竹林松亭")

        lines_text = "春雨茶席\n秋夜烛光"
        expanded_lines = parse_batch_variables_and_expand(lines_text, "东方电影感：{场景}")
        self.assertEqual(expanded_lines[0]["prompt"], "东方电影感：春雨茶席")

    async def test_ffmpeg_command_builder_srt_and_path_traversal_guard(self) -> None:
        """验证 SRT 时间轴构建、ffmpeg 拼接滤镜参数生成及非法路径穿越拦截（V4）。"""
        srt = build_srt_content([{"start": 0.0, "end": 2.5, "text": "雨夜茶温，请慢用。"}])
        self.assertIn("00:00:00,000 --> 00:00:02,500", srt)
        self.assertIn("雨夜茶温，请慢用。", srt)

        cmd = build_ffmpeg_compose_command(
            "ffmpeg",
            ["/tmp/a.mp4", "/tmp/b.mp4"],
            "/tmp/out.mp4",
            narration_path="/tmp/voice.mp3",
            srt_path="/tmp/sub.srt",
        )
        self.assertEqual(cmd[0], "ffmpeg")
        self.assertIn("concat=n=2:v=1:a=0[vout]", " ".join(cmd))
        self.assertIn("mov_text", cmd)

        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(PathSecurityError):
                await compose_storyboard_clips(["../secret.mp4"], files_dir=tmpdir)

    async def test_real_ffmpeg_trim_and_stereo_audio_stitch_tool(self) -> None:
        """验证本机 ffmpeg 自动发现、单段截齐裁剪、原生立体声音轨无缝拼接及画布写入（V4 增强）。"""
        import subprocess

        ffmpeg_bin = resolve_ffmpeg_binary()
        self.assertTrue(os.path.isfile(ffmpeg_bin))

        with tempfile.TemporaryDirectory() as tmpdir:
            temp_db = DatabaseService(os.path.join(tmpdir, "stitch.db"))
            await temp_db.create_canvas("cv_stitch", "1分钟拼接画布")

            # 生成两段各 1.6 秒带立体声正弦音轨的测试 MP4，测试截齐为每段 1.0 秒并拼接成 2.0 秒成片
            for idx, freq in ((1, 440), (2, 660)):
                clip_p = os.path.join(tmpdir, f"seg_{idx}.mp4")
                subprocess.run(
                    [
                        ffmpeg_bin,
                        "-y",
                        "-f",
                        "lavfi",
                        "-i",
                        "color=c=navy:s=320x180:r=24:d=1.6",
                        "-f",
                        "lavfi",
                        "-i",
                        f"sine=frequency={freq}:sample_rate=48000:duration=1.6",
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

            with (
                patch("services.video_compose_service.FILES_DIR", tmpdir),
                patch("services.video_compose_service.db_service", temp_db),
            ):
                out_msg = await video_edit_and_stitch_tool.ainvoke(
                    {
                        "video_files": ["seg_1.mp4", "seg_2.mp4"],
                        "target_clip_duration": 1.0,
                        "transition_fade_sec": 0.1,
                        "preserve_clip_audio": True,
                    },
                    config={"configurable": {"canvas_id": "cv_stitch", "session_id": ""}},
                )
                self.assertIn("video_edit_and_stitch executed successfully", out_msg)
                self.assertIn("has_audio=True", out_msg)

                cv = await temp_db.get_canvas_data("cv_stitch")
                elems = (cv or {}).get("data", {}).get("elements", [])
                self.assertEqual(len(elems), 1)
                lineage = elems[0]["customData"]["jaazLineage"]
                self.assertEqual(lineage["parentFileIds"], ["seg_1.mp4", "seg_2.mp4"])

                fid = list((cv or {}).get("data", {}).get("files", {}).values())[0]["dataURL"].split("/api/file/")[1]
                meta = probe_video_clip_info(os.path.join(tmpdir, fid), ffmpeg_bin)
                self.assertTrue(meta["has_audio"])
                self.assertAlmostEqual(meta["duration"], 2.0, delta=0.25)

    def test_file_mapping_csv_uses_utf8_bom_and_crlf(self) -> None:
        """验证 ComfyUI 下载 URL 解析与 file_mappings.csv 生成严格符合 UTF-8 BOM + CRLF 规范。"""
        parsed = parse_comfy_view_url(
            "https://colab.patdelphi.xyz/view?filename=MiniMax_H3_00029_.mp4&subfolder=video&type=output"
        )
        self.assertEqual(parsed["comfy_rel"], "video/MiniMax_H3_00029_.mp4")

        with tempfile.TemporaryDirectory() as tmpdir:
            csv_p = os.path.join(tmpdir, "file_mappings.csv")
            record_file_mapping(
                "1n8wCYLbMD.mp4",
                source_url="https://colab.patdelphi.xyz/view?filename=MiniMax_H3_00029_.mp4&subfolder=video&type=output",
                canvas_id="film-1min-4x15s-2026",
                workflow_name="text2video_minimax_h3",
                csv_path=csv_p,
            )
            with open(csv_p, "rb") as f:
                raw = f.read()
            self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
            body = raw[3:]
            self.assertEqual(body.count(b"\n") - body.count(b"\r\n"), 0)
            rows = list_file_mappings(csv_p)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["comfy_output_relpath"], "video/MiniMax_H3_00029_.mp4")

    async def test_cross_canvas_asset_search_and_custom_templates(self) -> None:
        """验证跨画布资产检索支持按关键词与类型过滤，且自定义模板可持久化保存（M1 / W1）。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_db = DatabaseService(os.path.join(tmpdir, "studio.db"))
            sample_img = os.path.join(tmpdir, "tea_cup.png")
            with open(sample_img, "wb") as f:
                f.write(b"\x89PNG\r\n\x1a\n")

            await temp_db.create_canvas("cv_st_1", "宋韵茶席画布")
            await temp_db.save_canvas_data(
                "cv_st_1",
                json.dumps(
                    {
                        "elements": [
                            {
                                "id": "im_t1",
                                "type": "image",
                                "width": 1600,
                                "height": 900,
                                "fileId": "im_t1",
                                "isDeleted": False,
                                "customData": {
                                    "jaazLineage": {
                                        "workflowName": "text2image_minimax_h3",
                                        "prompt": "天青釉冰裂纹建盏特写",
                                    }
                                },
                            }
                        ],
                        "files": {
                            "im_t1": {
                                "id": "im_t1",
                                "dataURL": "/api/file/tea_cup.png",
                                "mimeType": "image/png",
                            }
                        },
                    }
                ),
            )

            tpl_file = os.path.join(tmpdir, "studio_templates.json")
            with (
                patch("routers.studio_router.db_service", temp_db),
                patch("routers.studio_router.FILES_DIR", tmpdir),
                patch("routers.studio_router.TEMPLATES_FILE", tpl_file),
            ):
                found = await search_studio_assets(q="建盏", kind="image")
                self.assertEqual(len(found), 1)
                self.assertEqual(found[0]["file_id"], "tea_cup.png")
                self.assertEqual(found[0]["canvas_name"], "宋韵茶席画布")

                saved_tpl = await save_studio_template(
                    SaveTemplateRequest(name="茶器套图", prompt_template="特写：{器物}")
                )
                self.assertEqual(saved_tpl["name"], "茶器套图")
                all_tpls = await list_studio_templates()
                self.assertTrue(any(t["name"] == "茶器套图" for t in all_tpls))

    def test_r17_split_modules_stay_under_600_lines_and_preserve_exports(self) -> None:
        """验证拆分后的 10 个核心后端模块文件行数均不超过 600 行，且原有公开符号全部兼容可用（R-17）。"""
        import routers.comfyui_router as cr
        import services.comfy_workflow_pack as cwp
        import services.db_service as dbs
        import services.llm_adapters as llma

        for attr in ("validate_workflow_pack", "generate_draft_config", "scan_workflows_dir", "scan_source_workflows_dir"):
            self.assertTrue(hasattr(cwp, attr), f"Missing {attr} on comfy_workflow_pack")
        for attr in ("AnthropicNativeChatModel", "GeminiNativeChatModel", "create_chat_model", "convert_messages_to_gemini"):
            self.assertTrue(hasattr(llma, attr), f"Missing {attr} on llm_adapters")
        self.assertTrue(hasattr(dbs.db_service, "list_comfy_workflows"))
        self.assertTrue(hasattr(cr, "router"))

        server_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        rel_files = [
            "services/comfy_workflow_pack.py",
            "services/comfy_pack_common.py",
            "services/comfy_pack_draft.py",
            "services/comfy_pack_source.py",
            "services/db_service.py",
            "services/db_comfy_repo.py",
            "routers/comfyui_router.py",
            "routers/comfyui_instance_routes.py",
            "services/llm_adapters.py",
            "services/llm_message_converters.py",
        ]
        for rel in rel_files:
            full_path = os.path.join(server_root, rel)
            with open(full_path, "r", encoding="utf-8") as f:
                line_count = sum(1 for _ in f)
            self.assertLessEqual(line_count, 600, f"{rel} has {line_count} lines (> 600)")


if __name__ == "__main__":
    unittest.main()
