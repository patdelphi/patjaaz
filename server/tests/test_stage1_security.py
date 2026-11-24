"""程序说明：阶段 1（安全 P0）同步回归测试，覆盖路径安全、代理白名单、上传校验、密钥掩码与 Socket 源校验。"""
from io import BytesIO
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from PIL import Image

SERVER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIR))

from routers.image_router import validate_uploaded_image
from services.config_service import (
    ConfigService,
    mask_secret,
    merge_masked_secrets,
)
from services.websocket_state import is_allowed_socket_origin
from tools.comfy_dynamic import resolve_comfy_input_image_path
from utils.path_security import (
    PathSecurityError,
    ensure_path_in_allowed_roots,
    safe_file_id_path,
    safe_join,
    validate_comfyui_proxy_target,
)


def _make_png_bytes(width: int = 8, height: int = 8) -> bytes:
    """生成用于测试的最小内存 PNG 字节流。"""
    buf = BytesIO()
    Image.new("RGB", (width, height), color=(255, 0, 0)).save(buf, format="PNG")
    return buf.getvalue()


class Stage1SecurityTests(unittest.TestCase):
    def test_safe_join_allows_nested_relative_and_blocks_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "workspace")
            os.makedirs(root, exist_ok=True)

            resolved = safe_join(root, "sub/note.md")
            self.assertEqual(resolved, os.path.realpath(os.path.join(root, "sub", "note.md")))

            bad_inputs = [
                "",
                "   ",
                "../secret.txt",
                "sub/../../secret.txt",
                "/etc/passwd",
                "\\Windows\\System32\\cmd.exe",
                "C:\\temp\\a.txt",
                "C:rel.txt",
                "\\\\server\\share\\file.txt",
                "a\x00b.txt",
                "../workspace_evil/file.txt",
            ]
            for bad in bad_inputs:
                with self.subTest(bad=bad):
                    with self.assertRaises(PathSecurityError):
                        safe_join(root, bad)

    def test_safe_file_id_path_validates_single_segment_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            resolved = safe_file_id_path(tmp, "im_abc123.png")
            self.assertEqual(resolved, os.path.realpath(os.path.join(tmp, "im_abc123.png")))

            for bad in ("../im_1.png", "a/b.png", "a\\b.png", "im..1.png", ".", "bad name.png", "a\x00.png"):
                with self.subTest(bad=bad):
                    with self.assertRaises(PathSecurityError):
                        safe_file_id_path(tmp, bad)

    def test_ensure_path_in_allowed_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            allowed_dir = os.path.join(tmp, "allowed")
            outside_dir = os.path.join(tmp, "outside")
            os.makedirs(allowed_dir, exist_ok=True)
            os.makedirs(outside_dir, exist_ok=True)

            inside = ensure_path_in_allowed_roots(os.path.join(allowed_dir, "a.png"), [allowed_dir])
            self.assertEqual(inside, os.path.realpath(os.path.join(allowed_dir, "a.png")))

            with self.assertRaises(PathSecurityError):
                ensure_path_in_allowed_roots(os.path.join(outside_dir, "b.png"), [allowed_dir])

    def test_validate_comfyui_proxy_target(self):
        configured = "http://127.0.0.1:8188/"
        self.assertEqual(
            validate_comfyui_proxy_target(configured, None, "/system_stats"),
            "http://127.0.0.1:8188/system_stats",
        )
        self.assertEqual(
            validate_comfyui_proxy_target(configured, "http://127.0.0.1:8188", "/object_info/KSampler"),
            "http://127.0.0.1:8188/object_info/KSampler",
        )

        # 拒绝外部 URL 与非白名单/穿越路径
        for req_url, req_path in [
            ("http://169.254.169.254", "/system_stats"),
            ("https://evil.com", "/api/object_info"),
            (None, "//evil.com/system_stats"),
            (None, "/system_stats/../secret"),
            (None, "/system_stats@evil.com"),
            (None, "/system_stats_other"),
            (None, "/etc/passwd"),
        ]:
            with self.subTest(req_url=req_url, req_path=req_path):
                with self.assertRaises(PathSecurityError):
                    validate_comfyui_proxy_target(configured, req_url, req_path)

    def test_resolve_comfy_input_image_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            img_path = os.path.join(tmp, "im_test.png")
            with open(img_path, "wb") as f:
                f.write(_make_png_bytes())

            self.assertEqual(
                resolve_comfy_input_image_path("/api/file/im_test.png", tmp),
                os.path.realpath(img_path),
            )
            self.assertIsNone(resolve_comfy_input_image_path("plain prompt text", tmp))

            with self.assertRaises(PathSecurityError):
                resolve_comfy_input_image_path("../../secret.png", tmp)

            with self.assertRaises(FileNotFoundError):
                resolve_comfy_input_image_path("im_missing.png", tmp)

    def test_validate_uploaded_image(self):
        png_bytes = _make_png_bytes(10, 12)
        ext, width, height = validate_uploaded_image(png_bytes, "image/png")
        self.assertEqual((ext, width, height), ("png", 10, 12))

        with self.assertRaises(HTTPException) as oversized:
            validate_uploaded_image(png_bytes, "image/png", max_bytes=16)
        self.assertEqual(oversized.exception.status_code, 413)

        with self.assertRaises(HTTPException) as bad_mime:
            validate_uploaded_image(png_bytes, "text/html")
        self.assertEqual(bad_mime.exception.status_code, 400)

        with self.assertRaises(HTTPException) as bad_bytes:
            validate_uploaded_image(b"not an image", "image/png")
        self.assertEqual(bad_bytes.exception.status_code, 400)

        big_png = _make_png_bytes(20, 20)
        with self.assertRaises(HTTPException) as too_many_pixels:
            validate_uploaded_image(big_png, "image/png", max_pixels=100)
        self.assertEqual(too_many_pixels.exception.status_code, 400)

    def test_config_secret_masking_and_merge(self):
        self.assertEqual(mask_secret(""), "")
        self.assertEqual(mask_secret("short"), "********")
        self.assertEqual(mask_secret("sk-1234567890abcd"), "sk-****abcd")

        svc = ConfigService.__new__(ConfigService)
        svc.app_config = {
            "openai": {"url": "https://api.openai.com/v1/", "api_key": "sk-secret-9876", "models": {}},
            "comfyui": {"url": "http://127.0.0.1:8188", "api_key": "", "models": {}},
        }
        masked = svc.get_masked_config()
        self.assertEqual(masked["openai"]["api_key"], "sk-****9876")
        # 原配置字典不得被就地修改
        self.assertEqual(svc.app_config["openai"]["api_key"], "sk-secret-9876")

        kept = merge_masked_secrets(
            {
                "openai": {"url": "https://api.openai.com/v1/", "api_key": "sk-****9876", "models": {}},
                "comfyui": {"url": "http://127.0.0.1:8199", "api_key": "", "models": {}},
            },
            svc.app_config,
        )
        self.assertEqual(kept["openai"]["api_key"], "sk-secret-9876")

        replaced = merge_masked_secrets(
            {"openai": {"api_key": "sk-new-key-value"}},
            svc.app_config,
        )
        self.assertEqual(replaced["openai"]["api_key"], "sk-new-key-value")

        cleared = merge_masked_secrets(
            {"openai": {"api_key": ""}},
            svc.app_config,
        )
        self.assertEqual(cleared["openai"]["api_key"], "")

    def test_socket_origin_allowlist(self):
        self.assertTrue(is_allowed_socket_origin("http://localhost:5174"))
        self.assertTrue(is_allowed_socket_origin("http://127.0.0.1:57988"))
        self.assertFalse(is_allowed_socket_origin("https://evil.example.com"))
        self.assertFalse(is_allowed_socket_origin(None))

        tunnel_env = {
            "wsgi.url_scheme": "http",
            "HTTP_HOST": "127.0.0.1:57988",
            "HTTP_X_FORWARDED_PROTO": "https",
            "HTTP_X_FORWARDED_HOST": "jaaz.example.com",
            "asgi.scope": {"client": ("127.0.0.1", 12345)},
        }
        self.assertTrue(is_allowed_socket_origin("https://jaaz.example.com", tunnel_env))
        self.assertFalse(is_allowed_socket_origin("https://attacker.com", tunnel_env))

        with patch.dict(os.environ, {"JAAZ_ALLOWED_ORIGINS": "https://custom.local"}):
            self.assertTrue(is_allowed_socket_origin("https://custom.local"))


if __name__ == "__main__":
    unittest.main()
