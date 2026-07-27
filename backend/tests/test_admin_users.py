"""GET /admin/users — the read side of admin user management (Slice 2).

Covers the require_admin gate, email search (incl. LIKE-wildcard escaping),
status/role filters, pagination + total, and the safe projection.
"""
from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_password_hash
from app.models.db_models import User


async def _make_admin(db_session: AsyncSession, test_user: User) -> None:
    test_user.is_admin = True
    db_session.add(test_user)
    await db_session.flush()


async def _seed(db_session: AsyncSession, email: str, **kw: object) -> User:
    u = User(email=email, hashed_password=get_password_hash("Whatever123"), **kw)  # type: ignore[arg-type]
    db_session.add(u)
    await db_session.flush()
    return u


class TestRequireAdminGate:
    async def test_non_admin_gets_403(
        self, client: AsyncClient, test_user: User,
    ) -> None:
        resp = await client.get("/api/admin/users")
        assert resp.status_code == 403

    async def test_admin_gets_200(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession,
    ) -> None:
        await _make_admin(db_session, test_user)
        resp = await client.get("/api/admin/users")
        assert resp.status_code == 200


class TestListing:
    async def test_returns_all_users_with_total(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession,
    ) -> None:
        await _make_admin(db_session, test_user)
        await _seed(db_session, "alice@example.com")
        await _seed(db_session, "bob@example.com")

        body = (await client.get("/api/admin/users")).json()
        assert body["total"] == 3  # test_user + alice + bob
        emails = {u["email"] for u in body["users"]}
        assert {"alice@example.com", "bob@example.com", test_user.email} <= emails

    async def test_projection_omits_sensitive_fields(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession,
    ) -> None:
        await _make_admin(db_session, test_user)
        row = (await client.get("/api/admin/users")).json()["users"][0]
        # Never leak secrets/raw billing ids through the admin list.
        assert "hashed_password" not in row
        assert "stripe_customer_id" not in row
        assert "stripe_subscription_id" not in row
        assert "token_version" not in row
        # But do carry the management fields.
        assert {
            "id", "email", "created_at", "is_active", "is_admin", "is_demo",
            "is_comped", "onboarding_completed", "subscription_status",
            "email_verified",
        }.issubset(row.keys())


class TestSearch:
    async def test_email_substring_match(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession,
    ) -> None:
        await _make_admin(db_session, test_user)
        await _seed(db_session, "needle@example.com")
        await _seed(db_session, "haystack@example.com")

        body = (await client.get("/api/admin/users", params={"q": "needle"})).json()
        assert {u["email"] for u in body["users"]} == {"needle@example.com"}

    async def test_like_wildcards_are_escaped(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession,
    ) -> None:
        # "a_b" is a literal search, so it must NOT match "axb" (the underscore is
        # escaped, not treated as a single-char wildcard).
        await _make_admin(db_session, test_user)
        await _seed(db_session, "axb@example.com")
        body = (await client.get("/api/admin/users", params={"q": "a_b"})).json()
        assert body["total"] == 0


class TestFilters:
    async def test_status_disabled(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession,
    ) -> None:
        await _make_admin(db_session, test_user)
        await _seed(db_session, "active1@example.com", is_active=True)
        await _seed(db_session, "disabled1@example.com", is_active=False)

        body = (await client.get("/api/admin/users", params={"status": "disabled"})).json()
        assert {u["email"] for u in body["users"]} == {"disabled1@example.com"}

    async def test_status_active_filter(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession,
    ) -> None:
        await _make_admin(db_session, test_user)  # test_user stays active
        await _seed(db_session, "disabled2@example.com", is_active=False)

        body = (await client.get("/api/admin/users", params={"status": "active"})).json()
        emails = {u["email"] for u in body["users"]}
        assert test_user.email in emails
        assert "disabled2@example.com" not in emails

    async def test_status_unverified_filter(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession,
    ) -> None:
        await _make_admin(db_session, test_user)  # conftest user is verified
        await _seed(db_session, "stuck@example.com")  # email_verified_at defaults NULL
        await _seed(
            db_session, "confirmed@example.com", email_verified_at=datetime.now(UTC),
        )

        body = (await client.get("/api/admin/users", params={"status": "unverified"})).json()
        assert {u["email"] for u in body["users"]} == {"stuck@example.com"}
        assert body["total"] == 1

    async def test_status_unverified_excludes_demo_accounts(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession,
    ) -> None:
        # A demo account has a NULL stamp but reads as verified in the projection
        # (no inbox to confirm). The filter must agree, or the table would show a
        # row with no "Unverified" badge under the "Unverified email" filter.
        await _make_admin(db_session, test_user)
        demo = await _seed(db_session, "demo-unv@example.com", is_demo=True)
        assert demo.email_verified_at is None

        body = (await client.get("/api/admin/users", params={"status": "unverified"})).json()
        assert "demo-unv@example.com" not in {u["email"] for u in body["users"]}

    async def test_unverified_filter_agrees_with_the_projected_flag(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession,
    ) -> None:
        # Pins the filter/flag lockstep the schema comment calls out: every row
        # the filter returns must actually carry email_verified=false.
        await _make_admin(db_session, test_user)
        await _seed(db_session, "u1@example.com")
        await _seed(db_session, "u2@example.com", is_demo=True)
        await _seed(db_session, "u3@example.com", email_verified_at=datetime.now(UTC))

        body = (await client.get("/api/admin/users", params={"status": "unverified"})).json()
        assert body["users"], "expected at least one unverified row"
        assert all(u["email_verified"] is False for u in body["users"])

        # …and the converse: nobody flagged unverified is missing from it.
        everyone = (await client.get("/api/admin/users")).json()["users"]
        unflagged = {u["email"] for u in everyone if u["email_verified"] is False}
        assert unflagged == {u["email"] for u in body["users"]}

    async def test_role_admin_filter(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession,
    ) -> None:
        await _make_admin(db_session, test_user)
        await _seed(db_session, "plain@example.com")

        body = (await client.get("/api/admin/users", params={"role": "admin"})).json()
        assert {u["email"] for u in body["users"]} == {test_user.email}

    async def test_role_demo_filter(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession,
    ) -> None:
        await _make_admin(db_session, test_user)
        await _seed(db_session, "demo1@example.com", is_demo=True)
        await _seed(db_session, "plain2@example.com")

        body = (await client.get("/api/admin/users", params={"role": "demo"})).json()
        assert {u["email"] for u in body["users"]} == {"demo1@example.com"}

    async def test_role_comped_filter(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession,
    ) -> None:
        await _make_admin(db_session, test_user)
        await _seed(db_session, "comp1@example.com", is_comped=True)
        await _seed(db_session, "plain3@example.com")

        body = (await client.get("/api/admin/users", params={"role": "comped"})).json()
        assert {u["email"] for u in body["users"]} == {"comp1@example.com"}


class TestPagination:
    async def test_limit_offset_and_total(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession,
    ) -> None:
        await _make_admin(db_session, test_user)
        for i in range(5):
            await _seed(db_session, f"user{i}@example.com")

        body = (await client.get("/api/admin/users", params={"limit": 2, "offset": 0})).json()
        assert body["total"] == 6  # test_user + 5
        assert len(body["users"]) == 2
        assert body["limit"] == 2
        assert body["offset"] == 0

    async def test_offset_actually_skips_rows(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession,
    ) -> None:
        # offset=0 alone can't catch a dropped .offset() clause, so page through:
        # page 2 must be DISJOINT from page 1, which only holds if offset skips.
        await _make_admin(db_session, test_user)
        for i in range(4):
            await _seed(db_session, f"pg{i}@example.com")

        page1 = (await client.get("/api/admin/users", params={"limit": 2, "offset": 0})).json()
        page2 = (await client.get("/api/admin/users", params={"limit": 2, "offset": 2})).json()
        ids1 = {u["id"] for u in page1["users"]}
        ids2 = {u["id"] for u in page2["users"]}
        assert len(ids1) == 2
        assert len(ids2) == 2
        assert ids1.isdisjoint(ids2)

    async def test_limit_over_max_is_422(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession,
    ) -> None:
        await _make_admin(db_session, test_user)
        resp = await client.get("/api/admin/users", params={"limit": 999})
        assert resp.status_code == 422
