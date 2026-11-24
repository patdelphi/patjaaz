"""程序说明：阶段 1 去 Jaaz 云端清理回归测试，确认废弃云端文件、路由与默认工具注册已完全移除。"""
import inspect
import os
import sys
import tempfile
import unittest

SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(SERVER_DIR)
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from routers import chat_router, settings as settings_router
from services.config_service import ConfigService, DEFAULT_PROVIDERS_CONFIG
from services.langgraph_service.configs import image_vide_creator_config
from services.tool_service import TOOL_MAPPING
from tools.utils import image_generation_core


class M1CloudCleanupTests(unittest.TestCase):
    def test_deprecated_cloud_files_and_routes_are_removed(self):
        removed_paths = [
            os.path.join(SERVER_DIR, "services", "jaaz_service.py"),
            os.path.join(SERVER_DIR, "services", "magic_service.py"),
            os.path.join(SERVER_DIR, "services", "knowledge_service.py"),
            os.path.join(SERVER_DIR, "services", "mcp.py"),
            os.path.join(SERVER_DIR, "services", "OpenAIAgents_service"),
            os.path.join(SERVER_DIR, "tools", "image_providers", "jaaz_provider.py"),
            os.path.join(SERVER_DIR, "tools", "generate_image_by_gpt_image_1_jaaz.py"),
            os.path.join(REPO_ROOT, "react", "src", "api", "magic.ts"),
            os.path.join(REPO_ROOT, "react", "src", "api", "knowledge.ts"),
            os.path.join(REPO_ROOT, "react", "src", "api", "auth.ts"),
            os.path.join(REPO_ROOT, "react", "src", "routes", "knowledge.tsx"),
            os.path.join(REPO_ROOT, "react", "src", "routes", "agent_studio.tsx"),
        ]
        for path in removed_paths:
            with self.subTest(path=path):
                self.assertFalse(os.path.exists(path), f"Should have been removed: {path}")

    def test_no_jaaz_defaults_or_cloud_routes_remain(self):
        self.assertNotIn("jaaz", DEFAULT_PROVIDERS_CONFIG)
        self.assertNotIn("jaaz", image_generation_core.IMAGE_PROVIDERS)
        self.assertEqual(TOOL_MAPPING, {})

        chat_paths = {route.path for route in chat_router.router.routes}
        self.assertNotIn("/api/magic", chat_paths)
        self.assertNotIn("/api/magic/cancel/{session_id}", chat_paths)

        settings_paths = {route.path for route in settings_router.router.routes}
        self.assertNotIn("/api/settings/knowledge/enabled", settings_paths)

        src = inspect.getsource(image_vide_creator_config)
        self.assertNotIn("generate_image_by_gpt_image_1_jaaz", src)


class M1CloudCleanupAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_jaaz_section_in_config_toml_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = os.path.join(tmp, "config.toml")
            with open(cfg_path, "w", encoding="utf-8") as f:
                f.write(
                    '[jaaz]\nurl = "https://jaaz.app/api/v1/"\napi_key = "old"\n\n'
                    '[openai]\nurl = "https://api.openai.com/v1/"\napi_key = "sk-test"\n'
                )

            svc = ConfigService()
            svc.config_file = cfg_path
            await svc.initialize()
            self.assertNotIn("jaaz", svc.get_config())
            self.assertEqual(svc.get_config()["openai"]["api_key"], "sk-test")


if __name__ == "__main__":
    unittest.main()
