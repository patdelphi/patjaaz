"""程序说明：阶段 4 与阶段 5 回归测试，覆盖 CapabilityRegistry 调度与回退、三协议配置推断、Claude/Gemini 原生适配器与工具调用及连接测试脱敏。"""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from routers.comfyui_execution import ComfyUIUnavailableError
from services.capabilities import (
    AssetRef,
    CapabilityInvokeRequest,
    CapabilityInvokeResult,
    CapabilityRegistry,
    ComfyUICapabilityProvider,
    HttpApiCapabilityProvider,
)
from services.config_service import infer_provider_protocol
from services.llm_adapters import (
    AnthropicNativeChatModel,
    GeminiNativeChatModel,
    convert_messages_to_anthropic,
    convert_messages_to_gemini,
    create_chat_model,
    test_llm_connection,
)


@tool("echo_tool")
def _dummy_echo_tool(text: str) -> str:
    """Echo input text back."""
    return f"echo:{text}"


class _MockTTSProvider(HttpApiCapabilityProvider):
    def __init__(self, provider_id: str = "mock_tts", priority: int = 50, fail: bool = False):
        super().__init__(
            provider_id=provider_id,
            capabilities={"tts"},
            base_url="https://tts.local",
            api_key="tts-key",
            priority=priority,
        )
        self.fail = fail

    async def _execute_http(self, request, on_progress=None, cancel_token=None):
        if self.fail:
            raise ComfyUIUnavailableError("primary provider offline")
        return CapabilityInvokeResult(
            provider_id=self.provider_id,
            capability=request.capability,
            outputs=[
                AssetRef(
                    asset_id="tts-1",
                    kind="audio",
                    file_path="/tmp/voice.wav",
                    mime_type="audio/wav",
                    url="/api/file/voice.wav",
                )
            ],
        )


class M1CapabilitiesAndLLMTests(unittest.TestCase):
    def test_protocol_inference_and_chat_model_routing(self):
        self.assertEqual(infer_provider_protocol("openai", {}), "openai")
        self.assertEqual(infer_provider_protocol("anthropic", {}), "anthropic")
        self.assertEqual(infer_provider_protocol("claude_proxy", {"url": "https://api.anthropic.com"}), "anthropic")
        self.assertEqual(infer_provider_protocol("google", {}), "google")
        self.assertEqual(infer_provider_protocol("deepseek", {"url": "https://api.deepseek.com/v1/"}), "openai-compatible")
        self.assertEqual(
            infer_provider_protocol("custom", {"protocol": "anthropic", "url": "https://relay.example.com"}),
            "anthropic",
        )

        m_ollama = create_chat_model(
            {"provider": "ollama", "model": "qwen2.5", "url": "http://localhost:11434"},
            {},
        )
        self.assertIsInstance(m_ollama, ChatOllama)

        m_anthropic = create_chat_model(
            {"provider": "anthropic", "model": "claude-sonnet-4-20250514", "url": "https://api.anthropic.com"},
            {"protocol": "anthropic", "api_key": "sk-ant-test", "url": "https://api.anthropic.com"},
        )
        self.assertIsInstance(m_anthropic, AnthropicNativeChatModel)

        m_gemini = create_chat_model(
            {"provider": "google", "model": "gemini-2.5-flash", "url": "https://generativelanguage.googleapis.com"},
            {"protocol": "google", "api_key": "AIzaTestKey", "url": "https://generativelanguage.googleapis.com"},
        )
        self.assertIsInstance(m_gemini, GeminiNativeChatModel)

        m_compat = create_chat_model(
            {"provider": "deepseek", "model": "deepseek-chat", "url": "https://api.deepseek.com/v1/"},
            {"protocol": "openai-compatible", "api_key": "sk-ds-test", "url": "https://api.deepseek.com/v1/"},
        )
        self.assertIsInstance(m_compat, ChatOpenAI)

    def test_anthropic_and_gemini_message_conversion_and_react_agent_binding(self):
        msgs = [
            SystemMessage(content="You are helpful."),
            HumanMessage(
                content=[
                    {"type": "text", "text": "describe image"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
                ]
            ),
            AIMessage(
                content="",
                tool_calls=[{"id": "call_1", "name": "echo_tool", "args": {"text": "hi"}}],
            ),
            ToolMessage(content="echo:hi", tool_call_id="call_1", name="echo_tool"),
        ]

        sys_txt, anth_msgs = convert_messages_to_anthropic(msgs)
        self.assertEqual(sys_txt, "You are helpful.")
        self.assertEqual(anth_msgs[0]["content"][1]["source"]["media_type"], "image/png")
        self.assertEqual(anth_msgs[1]["content"][0]["type"], "tool_use")
        self.assertEqual(anth_msgs[2]["content"][0]["type"], "tool_result")

        sys_inst, gem_contents = convert_messages_to_gemini(msgs)
        self.assertEqual(sys_inst["parts"][0]["text"], "You are helpful.")
        self.assertEqual(gem_contents[0]["parts"][1]["inlineData"]["mimeType"], "image/png")
        self.assertEqual(gem_contents[1]["parts"][0]["functionCall"]["name"], "echo_tool")
        self.assertEqual(gem_contents[2]["parts"][0]["functionResponse"]["name"], "echo_tool")

        # 验证两种自定义适配器都能直接传给 langgraph create_react_agent 完成工具绑定
        anth_model = AnthropicNativeChatModel(model="claude-sonnet-4-20250514", api_key="sk-ant-test")
        gem_model = GeminiNativeChatModel(model="gemini-2.5-flash", api_key="AIzaTest")
        create_react_agent(name="a_agent", model=anth_model, tools=[_dummy_echo_tool], prompt="hi")
        create_react_agent(name="g_agent", model=gem_model, tools=[_dummy_echo_tool], prompt="hi")


class M1CapabilitiesAndLLMAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_capability_registry_routing_fallback_and_comfy_disabled_exclusion(self):
        registry = CapabilityRegistry()
        primary_failing = _MockTTSProvider(provider_id="primary_tts", priority=10, fail=True)
        fallback_ok = _MockTTSProvider(provider_id="backup_tts", priority=20, fail=False)
        registry.register(primary_failing)
        registry.register(fallback_ok)

        self.assertEqual(registry.list_capabilities()["tts"], ["primary_tts", "backup_tts"])
        result = await registry.invoke(CapabilityInvokeRequest(capability="tts", params={"text": "hello"}))
        self.assertEqual(result.provider_id, "backup_tts")
        self.assertEqual(result.outputs[0].kind, "audio")

        comfy_provider = ComfyUICapabilityProvider()
        with patch(
            "services.capabilities.comfyui_provider.db_service._list_comfy_workflows_sync",
            return_value=[{"name": "wf1", "capability": "t2i", "enabled": 1}],
        ):
            self.assertTrue(comfy_provider.supports("t2i"))
            self.assertFalse(comfy_provider.supports("tts"))

    async def test_anthropic_and_gemini_async_tool_calls_and_connection_test_redaction(self):
        # 1. 测试 AnthropicNativeChatModel 异步响应与 tool_use 解析
        anth_model = AnthropicNativeChatModel(model="claude-sonnet-4-20250514", api_key="sk-ant-secret")
        bound_anth = anth_model.bind_tools([_dummy_echo_tool])

        fake_anth_response = SimpleNamespace(
            content=[
                SimpleNamespace(type="text", text="calling tool"),
                SimpleNamespace(type="tool_use", id="tu_1", name="echo_tool", input={"text": "abc"}),
            ]
        )
        fake_async_client = MagicMock()
        fake_async_client.messages.create = AsyncMock(return_value=fake_anth_response)

        with patch("services.llm_adapters.anthropic.AsyncAnthropic", return_value=fake_async_client):
            ai_msg = await bound_anth.ainvoke([HumanMessage(content="test")])

        self.assertEqual(ai_msg.content, "calling tool")
        self.assertEqual(ai_msg.tool_calls[0]["name"], "echo_tool")
        self.assertEqual(ai_msg.tool_calls[0]["args"], {"text": "abc"})

        # 2. 测试 GeminiNativeChatModel 请求头传 key（非 query）与 functionCall 解析
        gem_model = GeminiNativeChatModel(model="gemini-2.5-flash", api_key="AIza-secret-xyz")
        bound_gem = gem_model.bind_tools([_dummy_echo_tool])

        captured_posts: list[tuple[str, dict, dict]] = []

        class _FakeGemResp:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {"functionCall": {"name": "echo_tool", "args": {"text": "gem"}}}
                                ]
                            }
                        }
                    ]
                }

        class _FakeHttpClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def post(self, url, json=None, headers=None):
                captured_posts.append((url, json or {}, headers or {}))
                return _FakeGemResp()

        with patch("services.llm_adapters.HttpClient.create", return_value=_FakeHttpClient()):
            gem_msg = await bound_gem.ainvoke([HumanMessage(content="run")])

        self.assertIn(":generateContent", captured_posts[0][0])
        self.assertNotIn("AIza-secret-xyz", captured_posts[0][0])
        self.assertEqual(captured_posts[0][2]["x-goog-api-key"], "AIza-secret-xyz")
        self.assertEqual(gem_msg.tool_calls[0]["name"], "echo_tool")
        self.assertEqual(gem_msg.tool_calls[0]["args"], {"text": "gem"})

        # 3. 测试 test_llm_connection 错误信息对 api_key 脱敏
        class _FailGetClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def get(self, url, headers=None):
                return SimpleNamespace(
                    status_code=401,
                    text="invalid key sk-super-secret-leak in request",
                )

        with patch("services.llm_adapters.HttpClient.create", return_value=_FailGetClient()):
            res = await test_llm_connection(
                "openai",
                {"url": "https://api.openai.com/v1/", "api_key": "sk-super-secret-leak", "protocol": "openai"},
            )
        self.assertFalse(res["ok"])
        self.assertNotIn("sk-super-secret-leak", res["message"])
        self.assertIn("***", res["message"])


if __name__ == "__main__":
    unittest.main()
