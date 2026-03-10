from enum import Enum
from typing import Any

from pydantic import BaseModel, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMProvider(str, Enum):
    OPENAI = "openai"
    GEMINI = "gemini"


class ModelEntry(BaseModel):
    provider: LLMProvider
    model: str


class Settings(BaseSettings):
    # Ordered model fallback chain — "provider/model,provider/model,..."
    # First model is primary; subsequent models are tried on quota errors (429).
    # Typed as str | list so pydantic-settings passes the raw env string through
    # to our field_validator instead of attempting JSON decode.
    llm_models: str | list[ModelEntry] = [
        ModelEntry(provider=LLMProvider.GEMINI, model="gemini-2.5-flash"),
        ModelEntry(provider=LLMProvider.GEMINI, model="gemini-2.5-flash-lite"),
    ]

    # API keys (still per-provider)
    openai_api_key: str | None = None
    gemini_api_key: str | None = None

    # When True, LLMClient will return a deterministic fake JSON response
    llm_mock: bool = False

    use_rag: bool = False

    run_llm_tests: bool = False


    db_echo: bool = False

    secret_key: str
    database_url: str

    allowed_origins: str = "http://localhost:5173,http://localhost:5174"

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @property
    def model_chain(self) -> list[ModelEntry]:
        """Return llm_models as a typed list (always resolved after validation)."""
        assert isinstance(self.llm_models, list)  # guaranteed by validator
        return self.llm_models

    @field_validator("llm_models", mode="before")
    @classmethod
    def parse_model_chain(cls, v: object) -> list[ModelEntry]:
        if isinstance(v, str):
            entries: list[ModelEntry] = []
            for item in v.split(","):
                item = item.strip()
                provider_str, model = item.split("/", 1)
                entries.append(ModelEntry(provider=LLMProvider(provider_str), model=model))
            return entries
        if isinstance(v, list):
            return v  # type: ignore[return-value]  # already parsed (e.g. default)
        raise ValueError(f"llm_models must be a comma-separated string or list, got {type(v)}")


# noinspection PyArgumentList
settings = Settings()  # type: ignore[call-arg]  # pydantic-settings reads from env vars
