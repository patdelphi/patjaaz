from pydantic import BaseModel
from typing import Literal, NotRequired, Optional, TypedDict


ProtocolType = Literal["openai", "anthropic", "google", "openai-compatible"]


class ModelCapabilities(TypedDict, total=False):
    vision: bool
    tools: bool
    thinking: bool
    context_length: int


class LLMConfig(BaseModel):
    model: str
    base_url: str
    api_key: str
    max_tokens: int
    temperature: float


class ConfigUpdate(BaseModel):
    llm: LLMConfig


class ModelInfo(TypedDict):
    provider: str
    model: str  # For tool type, it is the function name
    url: str
    type: Literal['text', 'image', 'tool', 'video']
    protocol: NotRequired[ProtocolType]
    capabilities: NotRequired[ModelCapabilities]
    max_tokens: NotRequired[int]
