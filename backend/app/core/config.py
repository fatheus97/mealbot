from enum import Enum

from pydantic import BaseModel, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMProvider(str, Enum):
    OPENAI = "openai"
    GEMINI = "gemini"
    DEEPSEEK = "deepseek"


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
    deepseek_api_key: str | None = None

    # When True, LLMClient will return a deterministic fake JSON response
    llm_mock: bool = False

    use_rag: bool = False

    # RAG thresholds
    rag_min_results: int = 3
    rag_max_distance: float = 0.4
    rag_user_boost: float = 0.7

    # RAG retrieval sizing. At scale (thousands of users), a single global top-K
    # would rarely surface the requesting user's own meals, so we fetch the two
    # populations separately and merge. rag_max_context_meals caps the final set
    # that reaches the LLM prompt — token cost is linear, quality gains plateau.
    rag_own_user_fetch: int = 5
    rag_global_fetch: int = 15
    rag_max_context_meals: int = 8

    # Cookbook-only RAG threshold. Once a user has this many favorites, we skip
    # the global pool entirely and search only their cookbook. Their taste model
    # is well-defined by then, and global cross-user noise tends to dilute the
    # match quality. Configurable so we can tune after real usage data lands.
    rag_cookbook_threshold: int = 100
    rag_cookbook_only_fetch: int = 20

    run_llm_tests: bool = False


    demo_mode: bool = False
    demo_session_expire_minutes: int = 120

    registration_enabled: bool = False

    # Short-lived access JWT lives in an HttpOnly cookie. 15 min bounds the
    # window of a stolen access token; refresh keeps active sessions alive
    # without re-prompting the user.
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 30

    # Grace window for refresh-token rotation collisions. Two tabs that both
    # have an expired access token will race to /auth/refresh — the loser
    # finds the row already revoked and would otherwise trigger the theft
    # alarm. If the row was revoked within this many seconds AND has a
    # replaced_by_id, treat it as a benign tab race and mint the caller a
    # fresh session instead. Tight enough that real exfil-and-replay
    # (minutes-to-hours) still trips the alarm.
    refresh_grace_seconds: int = 10

    # Cookie attributes — apply to mealbot_at, mealbot_rt, mealbot_csrf.
    # secure=True requires HTTPS at the browser. Same-origin in dev (Vite
    # proxy) means SameSite=Lax is sufficient — no need for SameSite=None.
    cookie_secure: bool = True
    cookie_samesite: str = "lax"

    # Double-submit-cookie CSRF middleware. Off only as an emergency lever.
    csrf_enabled: bool = True

    db_echo: bool = False

    secret_key: str
    database_url: str

    @field_validator("secret_key")
    @classmethod
    def validate_secret_key(cls, v: str) -> str:
        if v == "CHANGE_ME" or len(v) < 32:
            raise ValueError(
                "SECRET_KEY is insecure. Generate a proper key with: "
                "python -c \"import secrets; print(secrets.token_urlsafe(64))\""
            )
        return v

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
