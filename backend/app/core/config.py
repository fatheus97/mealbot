from enum import Enum
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMProvider(str, Enum):
    OPENAI = "openai"
    GEMINI = "gemini"


class Settings(BaseSettings):
    # Which provider to use: "gemini" or "openai"
    llm_provider: LLMProvider = LLMProvider.GEMINI

    # OpenAI config (optional, for later)
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"

    # Gemini config
    gemini_api_key: str | None = None
    # You can change this to e.g. "gemini-2.5-pro" later
    gemini_model: str = "gemini-2.5-flash"

    # When True, LLMClient will return a deterministic fake JSON response
    llm_mock: bool = False

    use_rag: bool = False

    run_llm_tests: bool = False

    database_url: str = "sqlite:///./test.db"

    db_echo: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )



settings = Settings()
