import copy
import os
import traceback
import aiofiles
import toml
from typing import Dict, TypedDict, Literal, Optional

# 定义配置文件的类型结构


def mask_secret(value: str) -> str:
    """对密钥做掩码展示，不向前端返回明文 api_key。"""
    if not isinstance(value, str) or not value:
        return ""
    if len(value) > 8:
        return f"{value[:3]}****{value[-4:]}"
    return "********"


def is_masked_secret(value: str) -> bool:
    """判断传入字符串是否为掩码占位符。"""
    if not isinstance(value, str):
        return False
    stripped = value.strip()
    return bool(stripped) and ("****" in stripped or stripped == "********")


def merge_masked_secrets(incoming: "AppConfig", existing: "AppConfig") -> "AppConfig":
    """保存配置时，若 api_key 仍为掩码占位符则保留原有明文密钥。"""
    merged = copy.deepcopy(incoming)
    if not isinstance(merged, dict):
        return merged

    for provider, provider_config in merged.items():
        if not isinstance(provider_config, dict) or "api_key" not in provider_config:
            continue
        raw_key = provider_config.get("api_key", "")
        if is_masked_secret(raw_key):
            existing_provider = existing.get(provider, {}) if isinstance(existing, dict) else {}
            existing_key = (
                existing_provider.get("api_key", "")
                if isinstance(existing_provider, dict)
                else ""
            )
            provider_config["api_key"] = existing_key
    return merged


class ModelConfig(TypedDict, total=False):
    type: Literal["text", "image", "video"]
    is_custom: Optional[bool]
    is_disabled: Optional[bool]


class ProviderConfig(TypedDict, total=False):
    url: str
    api_key: str
    max_tokens: int
    models: Dict[str, ModelConfig]
    is_custom: Optional[bool]


AppConfig = Dict[str, ProviderConfig]


DEFAULT_PROVIDERS_CONFIG: AppConfig = {
    'jaaz': {
        'models': {
            # text models
            'gpt-4o': {'type': 'text'},
            'gpt-4o-mini': {'type': 'text'},
            'deepseek/deepseek-chat-v3-0324': {'type': 'text'},
            'anthropic/claude-sonnet-4': {'type': 'text'},
            'anthropic/claude-3.7-sonnet': {'type': 'text'},
        },
        'url': os.getenv('BASE_API_URL', 'https://jaaz.app').rstrip('/') + '/api/v1/',
        'api_key': '',
        'max_tokens': 8192,
    },
    'comfyui': {
        'models': {},
        'url': 'http://127.0.0.1:8188',
        'api_key': '',
    },
    'ollama': {
        'models': {},
        'url': 'http://localhost:11434',
        'api_key': '',
        'max_tokens': 8192,
    },
    'openai': {
        'models': {
            'gpt-4o': {'type': 'text'},
            'gpt-4o-mini': {'type': 'text'},
        },
        'url': 'https://api.openai.com/v1/',
        'api_key': '',
        'max_tokens': 8192,
    },

}

SERVER_DIR = os.path.dirname(os.path.dirname(__file__))
USER_DATA_DIR = os.getenv(
    "USER_DATA_DIR",
    os.path.join(SERVER_DIR, "user_data"),
)
FILES_DIR = os.path.join(USER_DATA_DIR, "files")


IMAGE_FORMATS = (
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",  # 基础格式
    ".bmp",
    ".tiff",
    ".tif",  # 其他常见格式
    ".webp",
)
VIDEO_FORMATS = (
    ".mp4",
    ".avi",
    ".mkv",
    ".mov",
    ".wmv",
    ".flv",
)


class ConfigService:
    def __init__(self):
        self.app_config: AppConfig = copy.deepcopy(DEFAULT_PROVIDERS_CONFIG)
        self.config_file = os.getenv(
            "CONFIG_PATH", os.path.join(USER_DATA_DIR, "config.toml")
        )
        self.initialized = False

    def _get_jaaz_url(self) -> str:
        """Get the correct jaaz URL"""
        return os.getenv('BASE_API_URL', 'https://jaaz.app').rstrip('/') + '/api/v1/'

    async def initialize(self) -> None:
        try:
            # Ensure the user_data directory exists
            os.makedirs(os.path.dirname(self.config_file), exist_ok=True)

            # Check if config file exists
            if not self.exists_config():
                print(
                    f"Config file not found at {self.config_file}, creating default configuration")
                # Create default config file
                with open(self.config_file, "w") as f:
                    toml.dump(self.app_config, f)
                print(f"Default config file created at {self.config_file}")
                self.initialized = True
                return

            async with aiofiles.open(self.config_file, "r") as f:
                content = await f.read()
                config: AppConfig = toml.loads(content)
            for provider, provider_config in config.items():
                if provider not in DEFAULT_PROVIDERS_CONFIG:
                    provider_config['is_custom'] = True
                self.app_config[provider] = provider_config
                # image/video models are hardcoded in the default provider config
                provider_models = copy.deepcopy(
                    DEFAULT_PROVIDERS_CONFIG.get(provider, {}).get('models', {})
                )
                for model_name, model_config in provider_config.get('models', {}).items():
                    # Only text model can be self added
                    if model_config.get('type') == 'text' and model_name not in provider_models:
                        provider_models[model_name] = model_config
                        provider_models[model_name]['is_custom'] = True
                self.app_config[provider]['models'] = provider_models

            # 确保 jaaz URL 始终正确
            if 'jaaz' in self.app_config:
                self.app_config['jaaz']['url'] = self._get_jaaz_url()
        except Exception as e:
            print(f"Error loading config: {e}")
            traceback.print_exc()
        finally:
            self.initialized = True

    def get_config(self) -> AppConfig:
        if 'jaaz' in self.app_config:
            self.app_config['jaaz']['url'] = self._get_jaaz_url()
        return self.app_config

    def get_masked_config(self) -> AppConfig:
        """返回供接口响应使用的配置副本，所有 api_key 均已掩码。"""
        masked = copy.deepcopy(self.get_config())
        for provider_config in masked.values():
            if isinstance(provider_config, dict) and 'api_key' in provider_config:
                provider_config['api_key'] = mask_secret(
                    provider_config.get('api_key', '')
                )
        return masked

    async def update_config(self, data: AppConfig) -> Dict[str, str]:
        try:
            sanitized = merge_masked_secrets(data, self.app_config)
            if 'jaaz' in sanitized and isinstance(sanitized['jaaz'], dict):
                sanitized['jaaz']['url'] = self._get_jaaz_url()

            os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
            with open(self.config_file, "w", encoding="utf-8") as f:
                toml.dump(sanitized, f)
            self.app_config = sanitized

            return {
                "status": "success",
                "message": "Configuration updated successfully",
            }
        except Exception as e:
            traceback.print_exc()
            return {"status": "error", "message": str(e)}

    def exists_config(self) -> bool:
        return os.path.exists(self.config_file)


config_service = ConfigService()
