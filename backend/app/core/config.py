from enum import Enum

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMProvider(str, Enum):
    OPENAI = "openai"
    GEMINI = "gemini"
    DEEPSEEK = "deepseek"


class ModelEntry(BaseModel):
    provider: LLMProvider
    model: str


# Values that mean "not configured". The .env.example ships literal placeholders
# (your_key_here); an operator who copies it without editing leaves a truthy-but-
# useless key. Treating these as unset turns a confusing runtime 401 ("Incorrect
# API key: your_..._here", raised only when the provider is actually hit) into an
# honest "provider has no key" — surfaced at startup by check_model_chain_keys()
# and as a clear 500 from LLMClient._get_client instead.
_PLACEHOLDER_API_KEYS = frozenset({"your_key_here", "changeme", "change_me"})


def normalize_optional_key(value: str | None) -> str | None:
    """Collapse blank / placeholder API keys to None; pass real keys through."""
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    lowered = value.lower()
    if lowered in _PLACEHOLDER_API_KEYS or (
        lowered.startswith("your_") and lowered.endswith("_here")
    ):
        return None
    return value


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

    @field_validator("openai_api_key", "gemini_api_key", "deepseek_api_key", mode="after")
    @classmethod
    def _blank_placeholder_keys(cls, v: str | None) -> str | None:
        return normalize_optional_key(v)

    # When True, LLMClient will return a deterministic fake JSON response
    llm_mock: bool = False

    use_rag: bool = False

    # Master switch for leftover planning ("cook a bigger dinner, eat it as
    # tomorrow's lunch"). ON — the feature is complete:
    #   schema + invariants (#227), shopping-list and fridge accounting (#228),
    #   server-side assignment + batch-cooking prompt (#229), regeneration
    #   group-freezing and the edit fan-out (#232), planner and calendar UI (#234).
    #
    # Kept as a setting rather than deleted so it stays a kill switch: if
    # leftovers misbehave in the wild, LEFTOVERS_ENABLED=false in the prod .env
    # stops NEW links being created without a deploy or a code change. Existing
    # plans keep their links and stay coherent — the flag gates creation only,
    # and regeneration's group-expansion runs regardless (see plan.py).
    #
    # This is the rollout gate, deliberately NOT the request field:
    # MealPlanRequest is bound straight from the public request body, so the
    # endpoint overwrites payload.leftover_policy from this setting the same way
    # it overwrites include_spices. That overwrite is unconditional in BOTH
    # directions — a client can neither opt in nor opt out.
    leftovers_enabled: bool = True

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

    # --- Billing (Stripe subscriptions) ---
    # Master switch. While False, the generation endpoints are NOT gated and
    # nothing about billing is enforced — lets the code ship + deploy before the
    # Stripe account is live. Flip True (with live keys) to turn the paywall on.
    billing_enabled: bool = False
    stripe_secret_key: str | None = None
    stripe_webhook_secret: str | None = None
    # The recurring MONTHLY Price the Checkout subscribes the user to (the baseline
    # plan; billing_configured() requires it).
    stripe_price_id: str | None = None
    # The recurring ANNUAL Price ("€2.99/mo billed annually"). Optional: when unset,
    # the checkout offers monthly only and an annual request is rejected. Kept
    # separate from stripe_price_id so annual is additive and the monthly baseline
    # never depends on it.
    stripe_price_id_annual: str | None = None
    # Absolute base URL of the SPA — Checkout/Portal redirect back here.
    frontend_base_url: str = "http://localhost:5173"
    # 10-day free trial before the first charge.
    trial_period_days: int = 10

    # --- Trial-abuse guard (one free trial per physical card) ---
    # Gate A: a repeat card (user.has_used_trial) gets NO trial at checkout → Stripe
    # charges immediately. Gate B: a cross-account card reuse is clawed back on the
    # webhook (trial ended now). trial_abuse_guard_enabled is the kill switch
    # (mirrors leftovers_enabled); trial_fingerprint_hmac_secret domain-separates the
    # stored fingerprint HMAC (falls back to secret_key when unset).
    trial_abuse_guard_enabled: bool = True
    trial_fingerprint_hmac_secret: str | None = None
    # Outbound-Stripe network policy (per .claude/rules/fastapi.md: every external
    # call needs an explicit timeout + retry). The SDK default is 80s / 2 retries;
    # 20s is plenty for control-plane calls and keeps a hung request from tying up
    # an asyncio.to_thread worker for over a minute.
    stripe_timeout_seconds: int = 20
    stripe_max_retries: int = 2

    # --- Per-user LLM cost cap (usage budget) ---
    # Bounds monthly LLM spend per user (EUR summed from LlmUsage — see
    # app.services.usage_budget — NOT a raw request count, so a €0.06 seven-day
    # plan and a €0.009 recipe weigh correctly). One mechanism contains a power
    # user, a trial farmer, and a runaway-generation bug. Enforced even while
    # billing_enabled is false: LLM cost is incurred regardless of the paywall.
    # usage_cap_enabled is the kill switch (mirrors leftovers_enabled) — flip it
    # false in the prod .env to disable enforcement without a deploy.
    usage_cap_enabled: bool = True
    usage_cap_paid_eur: float = 2.0
    usage_cap_trial_eur: float = 0.75
    usage_soft_warn_ratio: float = Field(default=0.8, ge=0.0, le=1.0)

    # --- User feedback intake (bug reports / feature requests) ---
    # A logged-in user submits a report; a CHEAP regex/abuse gate rejects junk at
    # the edge, the report is stored, and (behind feedback_llm_triage_enabled) an
    # ADVISORY LLM triage pre-classifies it for the admin moderation queue. The LLM
    # NEVER authorizes anything — the €1 launch feedback credit + a private-repo
    # ticket are a later, human-Accept-gated slice. feedback_enabled is the kill
    # switch for the submit endpoint (mirrors leftovers_enabled); triage has its own
    # switch so the queue keeps working (raw reports, no advisory triage) if the LLM
    # misbehaves or costs spike.
    feedback_enabled: bool = True
    feedback_llm_triage_enabled: bool = True
    # Anti-flood caps on the intake (enforced in services.feedback_intake, on top of
    # the per-user route rate limit): the most OPEN (new/reviewing) reports a
    # single user may have queued at once, and the window in which an identical
    # resubmission from the same user is treated as a duplicate and refused. Both
    # bound queue spam + the LLM-triage cost an accepted report incurs.
    feedback_max_open_per_user: int = Field(default=20, ge=1, le=1000)
    feedback_dedup_window_hours: int = Field(default=24, ge=1, le=720)

    # --- VAT threshold tracking (revenue dashboard) ---
    # EU cross-border B2C distance-selling / OSS threshold: once cumulative B2C
    # sales to OTHER EU countries pass €10k, destination VAT (OSS) is required.
    vat_eu_oss_threshold_eur: float = 10_000.0
    # CZ domestic VAT-registration turnover threshold (obrat), CZK.
    vat_cz_domestic_threshold_czk: float = 2_000_000.0
    # Approximate EUR→CZK rate for the (EUR-priced) CZK threshold display. This is
    # an early-warning aid, not accounting — override with the real rate as needed.
    eur_czk_rate: float = 25.0

    # --- Alert emails (Resend) ---
    # The scheduled billing-alerts job emails the operator at 80%/100% of a VAT
    # threshold and once a month (identifikovaná-osoba reminder). All optional —
    # alerts are a no-op until an API key + recipient are set.
    resend_api_key: str | None = None
    # Default sender works without domain verification (Resend's shared domain);
    # switch to a verified from-address on your own domain for production.
    alert_email_from: str = "onboarding@resend.dev"
    alert_email_to: str | None = None
    # Day of month to send the monthly identifikovaná-osoba reminder — ahead of
    # the FÚ 25th deadline for self-assessing VAT on Stripe's foreign-service fees.
    # Bounded to 1..25 so the reminder can never fire after the 25th it references.
    vat_reminder_day: int = Field(default=20, ge=1, le=25)

    # --- Password reset ---
    # A reset link sits in an inbox, so its lifetime is the window in which
    # mailbox access converts into account access. 30 min is short enough to
    # bound that and long enough for a real person to notice the mail. Bounded
    # so a typo'd env var can't mint effectively-permanent links.
    password_reset_token_expire_minutes: int = Field(default=30, ge=5, le=1440)

    # --- Admin invite links ---
    # An admin-generated invite link lets a hand-picked beta tester self-register
    # while public registration stays closed. Like a reset link it sits in an
    # inbox/DM, so the TTL is the window in which link access converts to account
    # creation. Default 48h; bounded (1h..14d) so a typo'd env var can't mint an
    # effectively-permanent open-registration hole behind the closed gate.
    invite_token_expire_hours: int = Field(default=48, ge=1, le=336)

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

    # Max concurrent untrusted-input parse ops (PDF extraction + embedding) on
    # the dedicated pool in app.core.executors. Bounded so a burst of malicious
    # uploads can't starve the default thread pool that offloads bcrypt logins.
    # Small on purpose: parsing is CPU-bound, so oversubscribing cores past a
    # low cap only adds contention. Tune per box (CX23 = 2 vCPU).
    parse_executor_workers: int = Field(default=2, ge=1, le=32)

    # bcrypt work factor for password hashing. 12 (~250 ms/hash on the prod box)
    # is a sane 2020s default and the cost every stored hash currently carries.
    # The test suite overrides this to bcrypt's 4 floor (see conftest): the suite
    # hashes throwaway passwords ~1000× across fixtures + auth-flow tests, and at
    # cost 12 that alone adds minutes to CI wall-clock for zero security value.
    # Bounded to bcrypt's valid 4..31 range so a typo'd env var can neither
    # silently weaken prod hashing nor wedge it with an out-of-range cost.
    bcrypt_rounds: int = Field(default=12, ge=4, le=31)

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
