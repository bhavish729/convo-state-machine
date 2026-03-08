from __future__ import annotations

from enum import Enum

from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMProvider(str, Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="TARA_", extra="ignore")

    # LLM provider selection
    llm_provider: LLMProvider = LLMProvider.OPENAI

    # OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"

    # Anthropic
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-20250514"

    # Google Gemini
    google_api_key: str = ""
    google_model: str = "gemini-2.0-flash"

    # LLM parameters
    llm_temperature: float = 0.3
    llm_max_tokens: int = 1024

    # ElevenLabs
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = ""
    elevenlabs_base_url: str = ""  # Auto-detected from API key if empty

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = True

    # Conversation limits
    max_turns: int = 50
    escalation_sentiment_threshold: float = -0.7


settings = Settings()
