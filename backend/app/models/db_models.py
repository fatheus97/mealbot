from datetime import UTC, date, datetime

from pgvector.sqlalchemy import Vector  # type: ignore[import-untyped]
from sqlalchemy import BigInteger, Boolean, Index, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine.default import DefaultExecutionContext
from sqlmodel import Column, Field, Relationship, SQLModel, String

from app.core.email_normalize import normalize_email


def _default_normalized_email(context: DefaultExecutionContext) -> str:
    """SQLAlchemy insert-time default: derive normalized_email from the row's email
    when it isn't set explicitly, so EVERY User insert (register, invite, admin,
    CLI, demo, and all test fixtures) gets a value without a per-call hook — the
    missed-hook class of bug simply can't happen. Explicit callers may still pass
    normalized_email, in which case this is not invoked."""
    return normalize_email(str(context.get_current_parameters()["email"]))


class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    email: str = Field(sa_column=Column(String, unique=True, index=True, nullable=False))
    # Canonical anti-abuse uniqueness key (app.core.email_normalize). The raw
    # `email` above stays verbatim for delivery/display/Stripe; uniqueness + all
    # auth/reset lookups key off THIS. Auto-populated at insert from `email` via
    # _default_normalized_email; the real insert sites also set it explicitly.
    normalized_email: str = Field(
        sa_column=Column(
            String,
            unique=True,
            index=True,
            nullable=False,
            default=_default_normalized_email,
        )
    )

    hashed_password: str = Field(nullable=False)

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # Whitelisted against app.core.country_whitelist at the API layer. Capped
    # at 60 chars to bound prompt-token use and match the longest canonical
    # name ("Saint Vincent and the Grenadines" is 32 chars — 60 is ample).
    country: str | None = Field(default=None, index=True, max_length=60)

    # "none" | "metric" | "imperial"
    measurement_system: str = Field(default="metric")

    # "traditional" | "experimental"
    variability: str = Field(default="traditional")

    # include spices in shopping list + stock
    include_spices: bool = Field(default=True)

    # preferred output language for LLM responses; whitelisted against
    # app.core.language_whitelist at the API layer. Capped at 50 chars to
    # bound prompt-token use and guard against pathological input.
    language: str = Field(default="English", max_length=50)

    # include snacks/ready-to-eat items from receipt scans
    track_snacks: bool = Field(default=True)

    # if false, frontend shows onboarding popup
    onboarding_completed: bool = Field(default=False, index=True)

    is_demo: bool = Field(default=False, index=True)

    # Preferred per-day meal-slot shape, e.g.
    #   ["sweet_breakfast", "snack", "main_course", "hot_dinner"]
    # NULL means the user hasn't set one — plan generation falls back to the
    # legacy meals_per_day counter. Values are validated against MealType at
    # the API layer; the column itself is a loose JSONB so historical or
    # migrated rows with legacy values don't break reads.
    default_day_layout: list[str] | None = Field(
        default=None,
        sa_column=Column(JSONB, nullable=True),
    )

    # Incremented on logout to revoke all outstanding JWTs for this user.
    # Tokens carry the version they were issued under ("tv" claim); requests
    # with a mismatched version are rejected in get_current_user.
    token_version: int = Field(default=0, sa_column_kwargs={"server_default": "0"}, nullable=False)

    # Grants access to the admin API (require_admin dependency). Set server-side
    # ONLY — via the create_user CLI (--admin) or a direct DB update; there is no
    # self-service path and no endpoint that writes it. Defaults false.
    is_admin: bool = Field(
        default=False, sa_column_kwargs={"server_default": "false"}, nullable=False
    )

    # Complimentary ("friendlist") access — bypasses the subscription paywall like
    # admin/demo do (see stripe_service.is_entitled). Used to grandfather existing
    # users when billing is switched on, and to comp friends/testers. Server-set
    # only (create_user --comp / direct DB update); no self-service path.
    is_comped: bool = Field(
        default=False, sa_column_kwargs={"server_default": "false"}, nullable=False
    )

    # Account enablement. False = disabled by an admin: the disable gate in
    # get_current_user + the login/refresh paths rejects the user, so they can
    # neither act on an existing access token nor obtain a new one. Reversible
    # (reactivate flips it back). Server-set only — no self-service path; the
    # admin user-management endpoints (and the create_user CLI, implicitly true)
    # are the only writers. Defaults true so every existing row is enabled.
    is_active: bool = Field(
        default=True, sa_column_kwargs={"server_default": "true"}, nullable=False
    )

    # --- Billing (Stripe) — mirror of Stripe state, kept current via webhooks so
    # entitlement checks are a local read, not a Stripe round-trip. Stripe is the
    # source of truth. ---
    stripe_customer_id: str | None = Field(default=None, index=True)
    stripe_subscription_id: str | None = Field(default=None)
    # "none" | "trialing" | "active" | "past_due" | "canceled" — loose str (mirrors
    # Stripe's subscription.status). Entitlement = trialing/active/past_due.
    subscription_status: str = Field(
        default="none", sa_column_kwargs={"server_default": "none"}, nullable=False
    )
    current_period_end: datetime | None = Field(default=None)
    # Mirror of Stripe's cancel_at_period_end: True once the customer has canceled
    # but still has access until current_period_end. Status stays trialing/active
    # in this window, so this flag is what distinguishes "will renew" from "will
    # end" in the UI.
    cancel_at_period_end: bool = Field(
        default=False, sa_column_kwargs={"server_default": "false"}, nullable=False
    )
    # Monotonic ordering watermark: the Unix-epoch ``created`` of the most recent
    # Stripe subscription event we applied. Stripe does NOT guarantee webhook
    # delivery order, so apply_subscription ignores any event older than this —
    # stopping a delayed pre-cancellation "active" from resurrecting a canceled
    # user (revenue leak) and a stale "canceled" from locking out a payer. Stored
    # as an epoch int (not a datetime) so the comparison is timezone-unambiguous;
    # BigInteger so it survives 2038.
    subscription_event_ts: int | None = Field(
        default=None, sa_column=Column(BigInteger, nullable=True)
    )
    # The Stripe Price id the active subscription is on (from the subscription's
    # first item), mirrored by apply_subscription. This is how we tell the MONTHLY
    # plan from the ANNUAL one — e.g. so the launch feedback €1 credit (6b) can
    # exclude annual subscribers (already effectively discounted). NULL until the
    # first subscription event lands (and for every pre-reprice row). Server-set only.
    subscription_price_id: str | None = Field(default=None)

    # One free trial per account, EVER (trial-abuse guard, Gate A). Set True once a
    # user has started a trial (or been clawed back for reusing a card); a repeat
    # checkout then OMITS the trial so Stripe charges at completion. Server-set only
    # — see services.trial_guard + stripe_service.create_checkout_session.
    has_used_trial: bool = Field(
        default=False, sa_column_kwargs={"server_default": "false"}, nullable=False
    )

    # --- Acquisition attribution (first-touch, captured once at signup) ---
    # UTM parameters + referrer from the URL that first brought this user to the
    # app, threaded through /users/register. This is the ONLY funnel data that
    # cannot be derived from existing tables — every downstream milestone
    # (generated / confirmed / cooked / paid) is read from MachineGeneration /
    # MealPlan / MealEntry / SaleRecord at query time, so nothing else is stored.
    #
    # Attacker-controllable (they come from query params), so treated as
    # untrusted: bounded length, stored verbatim, and only ever rendered as
    # escaped React text on the admin dashboard — never interpolated anywhere.
    # Nullable with no server_default: existing users (and any future
    # UTM-less/direct signup) are simply NULL, which the funnel buckets as
    # "direct". max_length mirrors the `country` cap rationale (bound
    # pathological input); referrer is a URL so it gets a longer cap.
    signup_utm_source: str | None = Field(default=None, max_length=200)
    signup_utm_medium: str | None = Field(default=None, max_length=200)
    signup_utm_campaign: str | None = Field(default=None, max_length=200)
    signup_referrer: str | None = Field(default=None, max_length=500)

    fridge_items: list[StockItem] = Relationship(back_populates="user")
    meal_plans: list[MealPlan] = Relationship(back_populates="user")
    meal_entries: list[MealEntry] = Relationship(back_populates="user")
    auth_sessions: list[AuthSession] = Relationship(back_populates="user")


class AuthSession(SQLModel, table=True):
    """One row per logged-in device. The refresh token is stored as its
    sha256 hex (never plaintext) — leak of a DB dump must not yield usable
    tokens. Rotation marks the old row revoked and chains via replaced_by_id
    so a replayed (already-rotated) refresh signals theft and we revoke the
    whole user."""

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True, nullable=False)
    refresh_token_hash: str = Field(
        sa_column=Column(String(64), unique=True, index=True, nullable=False),
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), nullable=False)
    last_used_at: datetime = Field(default_factory=lambda: datetime.now(UTC), nullable=False)
    # Indexed (standalone) so the periodic cleanup sweep — a global
    # DELETE ... WHERE expires_at < cutoff — is index-served. The existing
    # composite (user_id, expires_at) index is user_id-leading and can't serve
    # a filter on expires_at alone. See services/authsession_cleanup.
    expires_at: datetime = Field(nullable=False, index=True)
    revoked_at: datetime | None = Field(default=None)
    # Truncated User-Agent for future "Active sessions" UI; pure metadata,
    # never trusted for auth decisions.
    user_agent: str | None = Field(default=None, max_length=256)
    # Forensic chain pointer. When this row is rotated, we set replaced_by_id
    # to the new row's id; if a refresh comes in for this (revoked) row we
    # know the new row is still trusted, but the request itself is reuse.
    replaced_by_id: int | None = Field(
        default=None, foreign_key="authsession.id"
    )

    user: User = Relationship(back_populates="auth_sessions")


class PasswordResetToken(SQLModel, table=True):
    """One issued password-reset link.

    Stored as sha256 hex, never plaintext — same rule as
    ``AuthSession.refresh_token_hash``, and it matters more here: a leaked DB
    dump of *usable* reset tokens is direct account takeover on every row,
    with no password needed.

    Single-use via ``used_at`` (kept rather than deleted so a replayed link is
    distinguishable from an expired/forged one in the logs). ``expires_at`` is
    indexed standalone so a *future* retention sweep (a global
    ``DELETE ... WHERE expires_at < cutoff``) can be index-served — the
    ``user_id`` index is user_id-leading and cannot serve a global cutoff
    filter. **That sweep does not exist yet**; the index lands ahead of it, the
    same way ``ix_authsession_expires_at`` (z6a7b8c9d0e1) preceded
    ``services/authsession_cleanup``.

    No ORM relationship to ``User`` on purpose: redemption looks the row up by
    ``token_hash`` and then loads the user by id, so a back-reference would be
    unused machinery on both sides.
    """

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True, nullable=False)
    token_hash: str = Field(
        sa_column=Column(String(64), unique=True, index=True, nullable=False),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), nullable=False
    )
    expires_at: datetime = Field(nullable=False, index=True)
    used_at: datetime | None = Field(default=None)

    __table_args__ = (
        # "At most one LIVE token per user", enforced by the database rather
        # than by the service remembering to supersede first. The mint path is
        # a SELECT-then-INSERT with no lock, so concurrent requests can both
        # pass the cooldown check; this turns that race into an IntegrityError
        # the service handles, instead of two simultaneously-valid reset links.
        # Declared here (not only in the migration) because the test schema is
        # built from SQLModel.metadata — a migration-only constraint would be
        # absent under pytest and the race handling would go untested.
        Index(
            "uq_passwordresettoken_one_live_per_user",
            "user_id",
            unique=True,
            postgresql_where=text("used_at IS NULL"),
        ),
    )


class AdminAuditLog(SQLModel, table=True):
    """Append-only audit trail of admin actions on user accounts.

    Deliberately **not** FK-linked to ``user`` on either side. An audited action
    can be the *deletion* of the target user (a later slice), and the whole point
    of an audit log is to outlive the row it describes — so actor and target are
    stored as bare ids plus an email snapshot taken at action time, fully
    decoupled from the user-row lifecycle. Rows are only ever INSERTed, never
    updated or deleted.
    """

    id: int | None = Field(default=None, primary_key=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), nullable=False, index=True
    )
    # The admin who performed the action. Bare id (no FK) + email snapshot; see
    # the class docstring for why it isn't a relationship.
    actor_user_id: int = Field(nullable=False, index=True)
    actor_email: str = Field(nullable=False)
    # Dotted action name, e.g. "user.deactivate" / "user.grant_admin". A plain
    # str (not an enum column) so adding an action in a later slice needs no
    # migration; the writer side constrains the vocabulary.
    action: str = Field(nullable=False, index=True)
    # The user acted upon. Nullable: some actions (none yet) may not target a
    # user. No FK so a later hard-delete of the target can't cascade or block.
    target_user_id: int | None = Field(default=None, index=True)
    target_email: str | None = Field(default=None)
    # Optional structured context (e.g. {"field": "is_admin", "from": "false",
    # "to": "true"}). String-valued so the blob stays schema'd (no Any) and
    # trivially JSON-serialisable; loose JSONB so older rows never break reads.
    detail: dict[str, str] | None = Field(
        default=None, sa_column=Column(JSONB, nullable=True)
    )


class TrialFingerprint(SQLModel, table=True):
    """One row per physical card that has consumed a free trial — the key for
    cross-account trial-abuse detection (Gate B).

    Stores an HMAC of Stripe's ``PaymentMethod.card.fingerprint`` (never the raw
    fingerprint: we only ever do equality checks, so a one-way hash is strictly
    better and keeps a leaked DB dump useless). ``first_user_id`` is a bare id with
    NO FK — this is fraud data retained under legitimate interest and must OUTLIVE a
    hard-deleted account (same keep-the-record, decoupled-from-user-lifecycle
    philosophy as ``AdminAuditLog`` / ``SaleRecord``). A later account deletion thus
    leaves a *stale* first_user_id, which still reads as "not the current user" → a
    reuse on a new account is still caught.
    """

    id: int | None = Field(default=None, primary_key=True)
    # HMAC-SHA256 hex of the card fingerprint. UNIQUE (declared in __table_args__)
    # — one trial per physical card, ever.
    fingerprint_hash: str = Field(nullable=False)
    # The account that first used this card for a trial. Bare id, no FK (see class
    # docstring). NULL only if a writer couldn't resolve the user.
    first_user_id: int | None = Field(default=None, index=True)
    stripe_customer_id: str | None = Field(default=None)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), nullable=False
    )

    __table_args__ = (
        Index(
            "ix_trialfingerprint_fingerprint_hash", "fingerprint_hash", unique=True
        ),
    )


class InviteToken(SQLModel, table=True):
    """One admin-generated invite link.

    A single-use, time-limited token that lets whoever holds it self-register a
    **new** account while public registration is closed (``registration_enabled``
    stays False) — the beta-onboarding path. Same hash-not-plaintext rule as
    ``PasswordResetToken``/``AuthSession``: only the sha256 hex is stored, so a
    leaked DB dump can't be turned into free account creation behind the closed
    gate.

    Single-use via ``used_at`` (kept, not deleted, so a replayed link is
    distinguishable from expired/revoked in the logs). ``revoked_at`` is separate
    so an admin can kill a leaked/unwanted link *before* it's redeemed.
    ``expires_at`` is indexed standalone for a future retention sweep, same as
    ``PasswordResetToken.expires_at``.

    Unlike ``PasswordResetToken`` there is no subject ``user_id`` — the invitee
    has no account yet and supplies their own email at redemption. The two user
    FKs here are attribution only (who minted it / who redeemed it), both
    nullable + ``ondelete="SET NULL"`` so a later hard-delete of that admin or
    invitee *anonymises* this row rather than cascade-deleting it — the same
    keep-the-record philosophy as ``SaleRecord.user_id``. No ORM relationships:
    redemption looks the row up by ``token_hash`` alone, so there's no
    caller-supplied identity to tamper with.

    ``is_comped`` is baked in at generation by the admin and copied onto the
    created account at redemption — it is NEVER read from the invitee's request,
    keeping ``is_comped`` server-set-only like everywhere else.
    """

    id: int | None = Field(default=None, primary_key=True)
    token_hash: str = Field(
        sa_column=Column(String(64), unique=True, index=True, nullable=False),
    )
    # Entitlement decided by the admin at mint time, copied onto the new account
    # on redeem. Never trusted from the invitee's body.
    is_comped: bool = Field(default=False, nullable=False)
    # Optional admin label ("for Alice") so the active-invites list is legible.
    note: str | None = Field(default=None, max_length=200)
    # Attribution only — nullable + SET NULL so a hard-deleted admin/invitee
    # anonymises this row instead of cascade-deleting it (cf. SaleRecord.user_id).
    created_by_admin_id: int | None = Field(
        default=None, foreign_key="user.id", index=True, ondelete="SET NULL"
    )
    redeemed_by_user_id: int | None = Field(
        default=None, foreign_key="user.id", index=True, ondelete="SET NULL"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), nullable=False
    )
    expires_at: datetime = Field(nullable=False, index=True)
    used_at: datetime | None = Field(default=None)
    revoked_at: datetime | None = Field(default=None)


class AccessRequest(SQLModel, table=True):
    """Someone asking for access from the public landing page while
    registration is closed.

    Replaces the landing page's old ``mailto:`` link so requests land in a
    queue the admin can act on (Invites tab) instead of an inbox. The intended
    close-out is "generate an invite from this request", which is why this
    table deliberately stores nothing more than what's needed to contact the
    person and decide.

    **This is the only UNAUTHENTICATED WRITE surface in the app**, so the
    hazards are spam and PII rather than privilege:

    * ``email``/``message`` are USER INPUT — length-bounded at the API layer,
      stored verbatim, and only ever rendered as escaped React text on the
      admin dashboard. Nothing downstream interpolates them.
    * ``normalized_email`` is the dedup key (same ``normalize_email`` used for
      accounts). The plain index is deliberately **NOT unique**: a request that
      was dismissed months ago shouldn't permanently bar that address from
      asking again. One-pending-per-address is instead a PARTIAL unique index
      (``uq_accessrequest_pending_email``, ``WHERE status='pending'``) declared
      in ``__table_args__`` below, so the invariant is a DB fact rather than a
      racy check-then-insert on an endpoint anyone can call.
    * There is no ``user_id`` — by definition the requester has no account.
      Submitting NEVER reveals whether the address already has one.
    * ``handled_by_admin_id`` is a bare id with no FK so it survives a later
      admin hard-delete (cf. ``FeedbackReport.reviewed_by_admin_id`` /
      ``AdminAuditLog``).

    GDPR: rows hold a third party's email + free text, so the admin API
    exposes a real DELETE (not just a status flip) — retention is a
    deliberate admin decision, and a handled request can be erased outright.
    """

    # Mirrors uq_accessrequest_pending_email in migration access_request_01 —
    # keep the two in step or the model and the DB drift.
    __table_args__ = (
        Index(
            "uq_accessrequest_pending_email",
            "normalized_email",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    # As typed, for display and for actually contacting them.
    email: str = Field(nullable=False, max_length=254)
    # Canonical form, for one-pending-per-address dedup. Indexed, NOT unique.
    normalized_email: str = Field(nullable=False, index=True, max_length=254)
    # Why they want access. Bounded at the API layer; may be empty.
    message: str = Field(default="", nullable=False)
    # "pending" | "handled" | "dismissed". Loose str (not an enum column) so a
    # new state needs no migration — same choice as FeedbackReport.status.
    status: str = Field(default="pending", nullable=False, index=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), nullable=False, index=True
    )
    handled_at: datetime | None = Field(default=None)
    handled_by_admin_id: int | None = Field(default=None)


class StockItem(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    name: str = Field(index=True)
    quantity_grams: float = Field(ge=0)
    need_to_use: bool = Field(default=False, index=True)
    expiration_date: date | None = Field(default=None, index=True)

    user: User = Relationship(back_populates="fridge_items")


class PantryStaple(SQLModel, table=True):
    """A per-user "always have" staple (salt, oil, flour…). Its name is excluded
    from the generated shopping list AT GENERATION TIME, so household staples stop
    landing on every list.

    Deliberately a name-only per-user collection — the StockItem shape minus the
    stock fields — because a staple is a membership set, not inventory (no
    quantity, no expiry). No DB cascade and no ORM back-relationship (like
    InviteToken): the write path is delete-all-then-insert and delete_user purges
    it explicitly, so neither is needed. Duplicate-name protection is handled in
    the service layer (case-insensitive dedup on the replace-all write), so the
    table needs no unique constraint."""
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    name: str = Field(index=True)


class MealPlan(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    days: int
    meals_per_day: int
    people_count: int

    # Calendar scheduling: the real-world date the plan's Day 1 falls on. Day N
    # (1-based, MealEntry.day_index) maps to start_date + (N - 1). NULL =
    # unscheduled — every legacy plan backfills to NULL, and the frontend renders
    # those by positional day index exactly as before. The API stamps it onto
    # MealPlanResponse from this column on every read, the same pattern as
    # plan_id: whatever placeholder sits in the serialized response_json is
    # always overwritten from here, so this column stays the single source of
    # truth (no authoritative second copy to drift).
    start_date: date | None = Field(default=None)

    # "planned" = the classic multi-day plan flow; "cook_now" = a one-shot
    # single-recipe cook (Phase 4). Kept as a plain str (not an enum column)
    # because future kinds are plausible and loose str avoids a migration
    # round-trip. The value is validated at the API layer.
    kind: str = Field(
        default="planned",
        sa_column_kwargs={"server_default": "planned"},
        nullable=False,
    )

    # For simplicity, we persist the raw request/response as JSON blobs.
    request_json: str  # store MealPlanRequest.model_dump_json()
    response_json: str  # store MealPlanResponse.model_dump_json()
    confirmed_at: datetime | None = Field(default=None)
    finished_at: datetime | None = Field(default=None)
    stock_after_json: str | None = Field(default=None)

    user: User = Relationship(back_populates="meal_plans")
    meal_entries: list[MealEntry] = Relationship(back_populates="meal_plan")

    __table_args__ = (
        # Partial composite index matching the plan-catalog query (list_plans):
        # WHERE user_id = ? AND confirmed_at IS NOT NULL AND kind = 'planned'
        # ORDER BY created_at DESC. Only user_id was indexed before, forcing a
        # scan+sort of all the user's plans per catalog load. Postgres scans this
        # index backward for the DESC order.
        Index(
            "ix_mealplan_catalog",
            "user_id",
            "created_at",
            postgresql_where=text("confirmed_at IS NOT NULL AND kind = 'planned'"),
        ),
    )

class MealEntry(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    meal_plan_id: int = Field(foreign_key="mealplan.id", index=True)
    day_index: int = Field(description="Which day of the plan this meal belongs to (1-based).")
    meal_index: int = Field(description="Index of the meal within the day (1-based).")
    name: str = Field(index=True)
    # Loose str at the DB layer. Current taxonomy values are validated via
    # PlannedMeal.meal_type (MealType enum); the column also holds legacy
    # "breakfast"/"lunch"/"dinner"/"snack" rows that PlannedMeal's pre-validator
    # translates on deserialization. Keeping this loose avoids a one-way
    # backfill and lets catalog/history endpoints return raw values the
    # frontend's mealTypeLabel() helper can render.
    meal_type: str = Field(index=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC)
    )
    cooked_at: datetime | None = Field(default=None)
    # Cookbook membership: starring a meal sets this True and triggers embedding
    # generation; un-starring clears both. Replaces the legacy 1–5 rating column —
    # we lost the granularity intentionally to keep the cookbook UX a single bit.
    #
    # No standalone index here — the composite (user_id, is_favorite) index
    # created in migration o5p6q7r8s9t0 covers every hot path (cookbook list,
    # count, RAG threshold check). Keeping index=True would make Alembic
    # autogenerate add a redundant single-column index next time it runs.
    is_favorite: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )
    # Keep details as JSON for now (ingredients, steps, etc.)
    meal_json: str = Field(
        description="Full PlannedMeal JSON (ingredients, steps, etc.)."
    )

    # Per-meal snapshot of which fridge batches were debited at confirm time.
    # JSON list[ConsumedBatch]. NULL on legacy rows (pre-migration); finish_plan
    # falls back to a lossy name+grams restore via restore_consumed_batches for
    # those — expiration_date and need_to_use are not recoverable.
    consumed_snapshot_json: str | None = Field(default=None)

    # --- Leftover projection (see app/services/leftovers.py) ---
    #
    # Derived from PlannedMeal.leftover_of in response_json, which stays
    # canonical; these columns are recomputed by persist_meal_entries on every
    # (re-)confirm. Denormalized here because meal_json is an opaque `str`, not
    # JSONB — nothing inside it is SQL-queryable, and the calendar endpoint
    # reads plain columns precisely so it never has to parse (and risk a
    # ValidationError 500 on) every blob in a 92-day window.
    #
    # 1-BASED, matching day_index/meal_index on this table — NOT the 0-based
    # LeftoverRef in the blob. Cross only via plan_service._ref_to_entry_coords.
    #
    # Intentionally no FK: these rows are bulk-deleted on unconfirm and
    # re-minted on re-confirm, so entry ids aren't stable enough to reference.
    # NULL on every existing row and on any non-leftover meal.
    leftover_of_day_index: int | None = Field(default=None)
    leftover_of_meal_index: int | None = Field(default=None)
    # Denormalized source name so the calendar and plan lists can show
    # provenance with no extra query and no blob parsing. Also the identity
    # check that detects a link silently retargeted by regeneration — which
    # never goes out of bounds, so a bounds check alone would not catch it.
    leftover_source_name: str | None = Field(default=None)

    # RAG embedding — 384d from all-MiniLM-L6-v2, generated when is_favorite=True
    embedding: list[float] | None = Field(
        default=None, sa_column=Column(Vector(384), nullable=True)
    )

    user: User = Relationship(back_populates="meal_entries")
    meal_plan: MealPlan = Relationship(back_populates="meal_entries")

    __table_args__ = (
        Index(
            "ix_mealentry_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


class MachineGeneration(SQLModel, table=True):
    """Append-only record of a raw machine/LLM/OCR output, captured at
    generation time BEFORE any user edits.

    Paired with MachineCorrection rows (via ``generation_id``) to reconstruct
    the machine-output → user-correction delta for offline quality analysis.
    Capturing every generation — not just edited ones — also yields an
    "accepted as-is" signal for free (a generation with no linked corrections).

    Best-effort telemetry: it shares the user action's transaction (so it's
    only persisted if that action commits — no phantom rows), but a failed
    write here must never surface to the user. See app.services.telemetry.
    """

    id: int | None = Field(default=None, primary_key=True)
    # CASCADE: telemetry is scoped to a user; when the user goes (e.g. demo-user
    # cleanup) their signal goes with them.
    user_id: int = Field(
        foreign_key="user.id", index=True, nullable=False, ondelete="CASCADE"
    )
    # Which flow produced this: "meal_plan" | "single_recipe" | "receipt_scan"
    # | "regenerate". Loose str (not an enum column) so new surfaces need no
    # migration; the value is set from a server-side constant set (never user
    # input) — see telemetry.GENERATION_SURFACES.
    surface: str = Field(index=True, nullable=False)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), index=True, nullable=False
    )
    # Loose link to the owning plan when the surface has one (meal_plan,
    # regenerate); NULL for plan-less surfaces (receipt_scan, single_recipe).
    # SET NULL, not CASCADE: deleting a plan must not destroy the durable
    # learning signal — the generation↔correction link and user_id survive.
    meal_plan_id: int | None = Field(
        default=None, foreign_key="mealplan.id", index=True, ondelete="SET NULL"
    )
    # The inputs that produced the output (request params / prompt inputs),
    # JSON. NULL when not meaningfully captured.
    request_json: str | None = Field(default=None)
    # The pristine machine output, JSON. The core signal.
    output_json: str = Field(nullable=False)


class LlmUsage(SQLModel, table=True):
    """Per-call LLM token usage, captured at call time. One row per successful,
    non-mock LLM call.

    Best-effort telemetry with the same contract as MachineGeneration — it rides
    the user action's transaction (recorded iff the action commits) and a failed
    write never surfaces to the user. See app.services.token_usage.
    ``surface``/``provider``/``model`` are server-controlled (``surface`` is a
    constant; ``provider``/``model`` come from our LLM_MODELS config), but the
    token counts are **provider-supplied, not server-controlled** — they're
    clamped in app.llm.usage._as_int to fit the int32 columns. That clamp is load-bearing,
    not belt-and-suspenders: it's the only thing stopping a malformed provider
    count from raising at flush and poisoning the caller's (on the plan paths,
    unguarded) transaction.

    ``total_tokens`` is stored as its own column, not derived: providers count
    reasoning/"thinking" tokens that are billed but excluded from prompt+
    completion (e.g. Gemini 2.5's total ≫ prompt+candidates), so total is the
    billing-relevant figure.

    Scope — this is a **lower bound on billed spend, not exact billing**:
    * Usage rides the user action's transaction, so a request that raises before
      it commits records nothing — and because a multi-call request (a multi-day
      plan, a regenerate) accumulates all its calls into one bucket committed at
      the end, one failed call discards the **whole request's** usage, including
      the earlier calls that already succeeded and were billed. (A future phase
      that needs exact billing should record each call in its own transaction so
      partial-failure spend survives; see ROADMAP.)
    * Only the final successful attempt is counted; `instructor`'s internal
      structured-output validation retries are billed but not captured here.
    Good enough for cost trends / relative per-user & per-surface comparison;
    reconcile against the provider's own billing for exact figures.
    """

    id: int | None = Field(default=None, primary_key=True)
    # CASCADE: usage is scoped to a user; demo-user cleanup takes it along.
    user_id: int = Field(
        foreign_key="user.id", index=True, nullable=False, ondelete="CASCADE"
    )
    # Which flow the call served: "meal_plan" | "single_recipe" | "receipt_scan"
    # | "regenerate". Loose str, server-set from token_usage.USAGE_SURFACES.
    surface: str = Field(index=True, nullable=False)
    # "gemini" | "openai" | "deepseek".
    provider: str = Field(nullable=False)
    # The concrete model that served the call, e.g. "gemini-2.5-flash".
    model: str = Field(nullable=False)
    prompt_tokens: int = Field(nullable=False)
    completion_tokens: int = Field(nullable=False)
    total_tokens: int = Field(nullable=False)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), index=True, nullable=False
    )
    # Loose link to the owning plan when the surface has one (meal_plan,
    # regenerate); NULL otherwise. SET NULL so deleting a plan doesn't destroy
    # the cost signal.
    meal_plan_id: int | None = Field(
        default=None, foreign_key="mealplan.id", index=True, ondelete="SET NULL"
    )

    __table_args__ = (
        # Serves the per-user windowed cost SUM behind the usage budget cap
        # (user_id AND created_at >= window); the single-column indexes don't.
        Index("ix_llmusage_user_created", "user_id", "created_at"),
    )


class MachineCorrection(SQLModel, table=True):
    """Append-only record of a user editing/committing machine-generated
    content.

    Links to the MachineGeneration it derives from (``generation_id``) when the
    server can resolve one. One row per edit hop: replaying a target's rows
    ordered by ``created_at`` reconstructs the full edit chain, and the first
    hop's ``before_json`` is the pristine generation for that item.

    Best-effort telemetry with the same transactional semantics as
    MachineGeneration.
    """

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(
        foreign_key="user.id", index=True, nullable=False, ondelete="CASCADE"
    )
    # "meal_edit" | "recipe_cook" | "receipt_merge" | ... — see
    # telemetry.CORRECTION_SURFACES.
    surface: str = Field(index=True, nullable=False)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), index=True, nullable=False
    )
    # CASCADE: a correction is meaningless once its generation is gone.
    generation_id: int | None = Field(
        default=None,
        foreign_key="machinegeneration.id",
        index=True,
        ondelete="CASCADE",
    )
    # SET NULL for the same reason as MachineGeneration.meal_plan_id.
    meal_plan_id: int | None = Field(
        default=None, foreign_key="mealplan.id", index=True, ondelete="SET NULL"
    )
    # Small structured coords (day/meal index, item counts) for slicing without
    # parsing the big blobs. JSONB so it's queryable. int-valued only by
    # convention — anything richer belongs in the JSON snapshots.
    context_json: dict[str, int] | None = Field(
        default=None, sa_column=Column(JSONB, nullable=True)
    )
    # Immediate pre-edit state (JSON) when the server has it (e.g. meal_edit
    # reads the old meal); NULL when only the committed version is available.
    before_json: str | None = Field(default=None)
    # What the user committed (JSON). The core signal.
    after_json: str = Field(nullable=False)


class SaleRecord(SQLModel, table=True):
    """One successful subscription payment, captured from the Stripe
    ``invoice.paid`` webhook. An append-only revenue ledger that powers VAT
    threshold tracking (EU €10k OSS cross-border-B2C; CZ 2M CZK turnover).

    Rows persist beyond the user (``ondelete="SET NULL"``): a deleted account
    (e.g. demo cleanup, GDPR erasure) must not destroy the revenue/tax record.
    ``country`` + ``is_business`` are the categorisation axes; amounts are stored
    in the currency's minor unit exactly as Stripe reports them (no lossy FX at
    write time — conversion to CZK for the domestic threshold is done at read
    time with a configurable rate).
    """

    id: int | None = Field(default=None, primary_key=True)
    # Idempotency key: one row per Stripe invoice, so a webhook replay is a no-op
    # (the recorder checks for an existing row before inserting).
    stripe_invoice_id: str = Field(
        sa_column=Column(String, unique=True, index=True, nullable=False)
    )
    stripe_customer_id: str | None = Field(default=None, index=True)
    # SET NULL (not CASCADE): the sale outlives the user for tax record-keeping.
    user_id: int | None = Field(
        default=None, foreign_key="user.id", index=True, ondelete="SET NULL"
    )
    # Amount actually paid, in the currency's minor unit (e.g. euro cents), as
    # Stripe's invoice.amount_paid reports it. int is ample per invoice.
    amount_cents: int = Field(nullable=False)
    # ISO-4217, lowercase (Stripe's convention), e.g. "eur".
    currency: str = Field(nullable=False)
    # Billing country, ISO-3166-1 alpha-2 upper (e.g. "DE"), from the invoice's
    # customer address. NULL when Stripe supplied none. Drives EU-vs-CZ split.
    country: str | None = Field(default=None, index=True)
    # True when the customer supplied a (VAT) tax id → B2B, which is excluded
    # from the €10k cross-border B2C threshold.
    is_business: bool = Field(
        default=False, sa_column_kwargs={"server_default": "false"}, nullable=False
    )
    # Economic time of the sale (Stripe invoice paid time), UTC-naive to match
    # the rest of the schema. Indexed for rolling-window aggregation.
    occurred_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), index=True, nullable=False
    )


class FeedbackReport(SQLModel, table=True):
    """One user-submitted bug report / feature request.

    Intake pipeline: a CHEAP regex/abuse gate (``core.feedback_gate``) rejects junk
    at submit time; the survivor is stored here as ``status="new"`` and — when
    ``feedback_llm_triage_enabled`` — an ADVISORY LLM triage (``services.
    feedback_triage``) fills the ``triage_*`` columns. An admin then moderates from
    the queue. **No money and no ticket are created here**: the €1 launch feedback
    credit + the private-repo GitHub issue are a later slice (6b), gated on a human
    admin *Accept*, NEVER on the LLM (untrusted input + a real reward = a
    prompt-injection/fraud surface, so the model only advises).

    ``kind`` / ``message`` / ``page`` are USER INPUT: length-bounded at the API
    layer, stored verbatim, only ever rendered as escaped React text on the admin
    dashboard, and — in ``feedback_triage`` — fed to the model under an explicit
    "treat this as data, not instructions" contract. The ``triage_*`` fields are
    MODEL OUTPUT, equally untrusted; nothing downstream acts on them automatically.

    ``user_id`` is ``ondelete="CASCADE"`` — a report carries no money/tax record (the
    credit lands on Stripe's ledger in 6b, not here), so it is safe to remove with
    the account, unlike ``SaleRecord``. ``reviewed_by_admin_id`` is a bare id with no
    FK so it survives a later admin deletion (cf. ``AdminAuditLog``).
    """

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(
        foreign_key="user.id", index=True, nullable=False, ondelete="CASCADE"
    )
    # The reporter's self-declared category: "bug" | "feature" | "other". Validated
    # at the API layer against a server-side set; advisory only (the LLM may
    # reclassify into triage_type). Loose str so a new category needs no migration.
    kind: str = Field(nullable=False)
    # The report body — user input, length-bounded at the API layer.
    message: str = Field(nullable=False)
    # Optional client-supplied context (the app view/route the user was on when they
    # reported). Untrusted, bounded at the API layer. NULL when not supplied.
    page: str | None = Field(default=None)
    # Moderation lifecycle: "new" (unmoderated) | "reviewing" | "accepted" |
    # "rejected" | "spam". Loose str (not an enum column) so a new state needs no
    # migration; allowed transitions are enforced in the admin API. This tracks the
    # HUMAN decision only — advisory triage state is separate (triage_status below),
    # so a report stays "new" (in the admin queue) after auto-triage. "accepted" is
    # reserved for the money-moving 6b slice and is NOT settable by the 6a PATCH.
    status: str = Field(
        default="new", sa_column_kwargs={"server_default": "new"}, nullable=False, index=True
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), index=True, nullable=False
    )

    # --- Advisory LLM triage (services.feedback_triage). All nullable: absent until
    # triage runs and STAYS absent when the LLM is disabled/unavailable. NEVER
    # authorizes anything — a human Accept is the sole money/ticket trigger. ---
    # "pending" (scheduled) | "done" | "failed" | NULL (never attempted).
    triage_status: str | None = Field(default=None)
    triage_is_actionable: bool | None = Field(default=None)
    # The model's own classification, richer than user `kind`: e.g. "bug" |
    # "feature" | "question" | "spam" | "praise" | "other".
    triage_type: str | None = Field(default=None)
    triage_severity: str | None = Field(default=None)  # "low" | "medium" | "high"
    triage_title: str | None = Field(default=None)
    triage_summary: str | None = Field(default=None)
    # Full FeedbackTriage.model_dump_json() (title, summary, repro, dedupe_hint, …)
    # kept for the record so 6b ticket creation needs no second LLM call.
    triage_json: str | None = Field(default=None)

    # --- Moderation bookkeeping ---
    # Bare id, no FK (survives a later admin hard-delete — see class docstring).
    reviewed_by_admin_id: int | None = Field(default=None)
    reviewed_at: datetime | None = Field(default=None)

    # --- 6b: credit + ticket (set on admin ACCEPT only; NEVER by the LLM/triage) ---
    # The Stripe invoice-item credit ("Feedback reward" line) queued for this accepted
    # report, in minor units (e.g. 100 = €1). NULL = no credit granted. credit_granted_at
    # doubles as the
    # idempotency marker (a report is credited at most once) and feeds the per-user
    # rolling-window rate cap. Both stay NULL when the credit is disabled/ineligible/
    # capped, or the grant failed (retryable via a repeat Accept).
    credit_cents: int | None = Field(default=None)
    credit_granted_at: datetime | None = Field(default=None)
    # URL of the GitHub Issue opened for this report in the private tickets repo. NULL
    # when ticketing is unconfigured or the create failed (retryable). Never the raw
    # issue body — just the link.
    ticket_url: str | None = Field(default=None)


class BillingAlert(SQLModel, table=True):
    """Dedupe ledger for operator alert emails so the scheduled billing-alerts job
    sends each one exactly once. ``dedupe_key`` is unique — a job re-run (or an
    accidental overlapping run) can't double-send.

    Keys:
      threshold:<key>:<year>:<level>   e.g. "threshold:eu_oss:2026:80"
      vat_reminder:<year>-<month>      e.g. "vat_reminder:2026-07"
    """

    id: int | None = Field(default=None, primary_key=True)
    dedupe_key: str = Field(
        sa_column=Column(String, unique=True, index=True, nullable=False)
    )
    kind: str = Field(nullable=False)  # "threshold" | "vat_reminder"
    sent_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), nullable=False
    )
