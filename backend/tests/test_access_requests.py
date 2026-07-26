"""Access requests: public intake + admin triage.

The public endpoint is the app's only unauthenticated write, so the emphasis
here is on the two properties that make it safe to expose: it never discloses
whether an address has an account, and one address can't flood the queue.
"""
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.db_models import AccessRequest, AdminAuditLog, User
from app.services.access_request import alert_html, submit_access_request

ENDPOINT = "/api/access-requests"
NEUTRAL = "Thanks — we've got your request and will be in touch by email."


async def _make_admin(db_session: AsyncSession, test_user: User) -> None:
    test_user.is_admin = True
    db_session.add(test_user)
    await db_session.flush()


async def _rows(db_session: AsyncSession) -> list[AccessRequest]:
    return list((await db_session.execute(select(AccessRequest))).scalars().all())


class TestPublicSubmit:
    async def test_stores_the_request_and_acknowledges(
        self, unauthed_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        resp = await unauthed_client.post(
            ENDPOINT, json={"email": "Alice@Example.com", "message": "please let me in"}
        )
        assert resp.status_code == 201
        assert resp.json()["message"] == NEUTRAL

        rows = await _rows(db_session)
        assert len(rows) == 1
        # Stored close to as-typed for contact (EmailStr lowercases the DOMAIN
        # but preserves local-part case), and fully normalized for dedup.
        assert rows[0].email == "Alice@example.com"
        assert rows[0].normalized_email == "alice@example.com"
        assert rows[0].status == "pending"

    async def test_message_is_optional(self, unauthed_client: AsyncClient, db_session: AsyncSession) -> None:
        resp = await unauthed_client.post(ENDPOINT, json={"email": "b@example.com"})
        assert resp.status_code == 201
        assert (await _rows(db_session))[0].message == ""

    async def test_whitespace_only_message_stores_empty(
        self, unauthed_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        resp = await unauthed_client.post(
            ENDPOINT, json={"email": "c@example.com", "message": "   \n  "}
        )
        assert resp.status_code == 201
        assert (await _rows(db_session))[0].message == ""

    async def test_a_second_request_from_the_same_address_does_not_queue_twice(
        self, unauthed_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        # Otherwise one mailbox can flood the admin queue; the rate limit alone
        # only slows that down.
        await unauthed_client.post(ENDPOINT, json={"email": "dup@example.com", "message": "one"})
        resp = await unauthed_client.post(
            ENDPOINT, json={"email": "dup@example.com", "message": "two"}
        )
        assert resp.status_code == 201
        assert resp.json()["message"] == NEUTRAL  # identical answer

        rows = await _rows(db_session)
        assert len(rows) == 1
        # The queued row keeps what was said FIRST — an unauthenticated caller
        # must not be able to rewrite a row already sitting in the admin queue.
        assert rows[0].message == "one"

    async def test_plus_tagged_and_dotted_gmail_dedupe_to_one_request(
        self, unauthed_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await unauthed_client.post(ENDPOINT, json={"email": "far.mer+a@gmail.com"})
        await unauthed_client.post(ENDPOINT, json={"email": "farmer+b@gmail.com"})
        assert len(await _rows(db_session)) == 1

    async def test_an_address_that_already_has_an_account_gets_the_SAME_answer(
        self, unauthed_client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        # The endpoint must not become an account-existence oracle.
        resp = await unauthed_client.post(ENDPOINT, json={"email": test_user.email})
        assert resp.status_code == 201
        assert resp.json()["message"] == NEUTRAL

    async def test_rejects_a_malformed_email(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.post(ENDPOINT, json={"email": "not-an-email"})
        assert resp.status_code == 422

    async def test_rejects_an_over_long_message(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.post(
            ENDPOINT, json={"email": "d@example.com", "message": "x" * 2001}
        )
        assert resp.status_code == 422

    async def test_rejects_a_malformed_json_body_with_422_not_500(
        self, unauthed_client: AsyncClient
    ) -> None:
        # An unauthenticated endpoint must not turn a bad body into a 500 with
        # a traceback in the logs.
        resp = await unauthed_client.post(
            ENDPOINT, content=b"{not json", headers={"Content-Type": "application/json"}
        )
        assert resp.status_code == 422

    async def test_one_pending_per_address_is_enforced_by_the_DATABASE(
        self, db_session: AsyncSession
    ) -> None:
        # The service pre-check is only the fast path; a partial unique index
        # (WHERE status='pending') is what makes this race-free on an endpoint
        # anyone can call. Insert straight past the service to prove the
        # constraint exists rather than trusting the check.
        from sqlalchemy.exc import IntegrityError

        db_session.add(
            AccessRequest(email="race@example.com", normalized_email="race@example.com")
        )
        await db_session.flush()
        db_session.add(
            AccessRequest(email="race@example.com", normalized_email="race@example.com")
        )
        with pytest.raises(IntegrityError):
            await db_session.flush()
        await db_session.rollback()

    async def test_is_csrf_exempt(self) -> None:
        from app.core.csrf import _CSRF_EXEMPT_PATHS

        # An anonymous visitor has never had a session, so there is no CSRF
        # cookie to double-submit.
        assert ENDPOINT in _CSRF_EXEMPT_PATHS


class TestOperatorAlert:
    """The alert is throttled to the empty→non-empty queue transition.

    Per-request alerts would be an outbound-mail lever for anyone: addresses
    are free and unverified, and the Resend key is SHARED with password-reset
    mail, so draining its quota silently breaks account recovery. Bounding
    alerts to queue-clearings ties the volume to the OPERATOR's actions.
    """

    @pytest.fixture
    def sent(self, monkeypatch: pytest.MonkeyPatch) -> list[str]:
        captured: list[str] = []

        async def _fake_send(subject: str, html: str) -> bool:
            captured.append(subject)
            return True

        monkeypatch.setattr("app.services.access_request.send_email", _fake_send)
        return captured

    async def test_alerts_on_the_first_request(
        self, unauthed_client: AsyncClient, sent: list[str]
    ) -> None:
        await unauthed_client.post(ENDPOINT, json={"email": "alert@example.com"})
        assert len(sent) == 1

    async def test_a_duplicate_submit_does_not_re_ping_the_operator(
        self, unauthed_client: AsyncClient, sent: list[str]
    ) -> None:
        await unauthed_client.post(ENDPOINT, json={"email": "alert@example.com"})
        await unauthed_client.post(ENDPOINT, json={"email": "alert@example.com"})
        assert len(sent) == 1

    async def test_MANY_DISTINCT_addresses_send_only_ONE_alert(
        self, unauthed_client: AsyncClient, sent: list[str]
    ) -> None:
        # The flood case: distinct addresses are free, so without this throttle
        # each one would be an outbound send on the key password reset shares.
        for i in range(12):
            await unauthed_client.post(ENDPOINT, json={"email": f"flood{i}@example.com"})
        assert len(sent) == 1

    async def test_alerts_again_once_the_operator_has_cleared_the_queue(
        self,
        client: AsyncClient,
        unauthed_client: AsyncClient,
        test_user: User,
        db_session: AsyncSession,
        sent: list[str],
    ) -> None:
        # Bounded by the operator's actions, not the caller's: emptying the
        # queue re-arms exactly one alert.
        await _make_admin(db_session, test_user)
        await unauthed_client.post(ENDPOINT, json={"email": "first@example.com"})
        assert len(sent) == 1

        first = (await _rows(db_session))[0]
        await client.patch(
            f"/api/admin/access-requests/{first.id}", json={"status": "handled"}
        )

        await unauthed_client.post(ENDPOINT, json={"email": "second@example.com"})
        assert len(sent) == 2

    def test_alert_html_escapes_both_attacker_controlled_values(self) -> None:
        html = alert_html('a"<script>@x.com', "<img src=x onerror=alert(1)>")
        assert "<script>" not in html
        assert "<img" not in html
        assert "&lt;script&gt;" in html

    def test_alert_html_handles_an_empty_message(self) -> None:
        assert "(no message)" in alert_html("a@b.com", "")


class TestAdminQueue:
    async def test_requires_admin(self, client: AsyncClient, test_user: User) -> None:
        assert (await client.get("/api/admin/access-requests")).status_code == 403

    async def test_lists_newest_first_with_pending_count(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        await _make_admin(db_session, test_user)
        for i, email in enumerate(["one@example.com", "two@example.com"]):
            await submit_access_request(
                db_session,
                email=email,
                message=f"m{i}",
                now=datetime(2026, 7, 1 + i, tzinfo=UTC),
            )
        await db_session.flush()

        body = (await client.get("/api/admin/access-requests")).json()
        assert [r["email"] for r in body["requests"]] == ["two@example.com", "one@example.com"]
        assert body["pending_count"] == 2

    async def test_flags_requests_whose_address_already_has_an_account(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        await _make_admin(db_session, test_user)
        await submit_access_request(db_session, email=test_user.email, message="")
        await submit_access_request(db_session, email="stranger@example.com", message="")
        await db_session.flush()

        by_email = {
            r["email"]: r for r in (await client.get("/api/admin/access-requests")).json()["requests"]
        }
        assert by_email[test_user.email]["has_account"] is True
        assert by_email["stranger@example.com"]["has_account"] is False

    async def test_filters_by_status(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        await _make_admin(db_session, test_user)
        req = (await submit_access_request(db_session, email="f@example.com", message="")).stored
        await db_session.flush()
        assert req is not None
        await client.patch(f"/api/admin/access-requests/{req.id}", json={"status": "handled"})

        pending = (await client.get("/api/admin/access-requests?status=pending")).json()
        handled = (await client.get("/api/admin/access-requests?status=handled")).json()
        assert pending["requests"] == []
        assert len(handled["requests"]) == 1
        assert pending["pending_count"] == 0

    async def test_handling_stamps_and_audits(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        await _make_admin(db_session, test_user)
        req = (await submit_access_request(db_session, email="h@example.com", message="")).stored
        await db_session.flush()
        assert req is not None

        resp = await client.patch(
            f"/api/admin/access-requests/{req.id}", json={"status": "handled"}
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "handled"
        assert resp.json()["handled_at"] is not None

        actions = [
            a.action
            for a in (await db_session.execute(select(AdminAuditLog))).scalars().all()
        ]
        assert "access_request.handled" in actions

    async def test_re_applying_the_same_status_does_not_re_stamp_who_handled_it(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        # Overwriting handled_at/handled_by would erase the record of who
        # actually closed it out.
        await _make_admin(db_session, test_user)
        req = (await submit_access_request(db_session, email="stamp@example.com", message="")).stored
        await db_session.flush()
        assert req is not None
        url = f"/api/admin/access-requests/{req.id}"

        first = (await client.patch(url, json={"status": "handled"})).json()
        second = (await client.patch(url, json={"status": "handled"})).json()
        assert first["handled_at"] == second["handled_at"]

    async def test_re_applying_the_same_status_is_idempotent(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        await _make_admin(db_session, test_user)
        req = (await submit_access_request(db_session, email="i@example.com", message="")).stored
        await db_session.flush()
        assert req is not None
        url = f"/api/admin/access-requests/{req.id}"
        assert (await client.patch(url, json={"status": "dismissed"})).status_code == 200
        assert (await client.patch(url, json={"status": "dismissed"})).status_code == 200

    async def test_cannot_dismiss_something_already_handled(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        # "handled" records that an invite actually went out — a later dismiss
        # must not silently overwrite that.
        await _make_admin(db_session, test_user)
        req = (await submit_access_request(db_session, email="j@example.com", message="")).stored
        await db_session.flush()
        assert req is not None
        url = f"/api/admin/access-requests/{req.id}"
        await client.patch(url, json={"status": "handled"})
        assert (await client.patch(url, json={"status": "dismissed"})).status_code == 409

    async def test_rejects_an_unknown_status(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        await _make_admin(db_session, test_user)
        req = (await submit_access_request(db_session, email="k@example.com", message="")).stored
        await db_session.flush()
        assert req is not None
        resp = await client.patch(
            f"/api/admin/access-requests/{req.id}", json={"status": "pending"}
        )
        assert resp.status_code == 422

    async def test_404_on_a_missing_request(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        await _make_admin(db_session, test_user)
        assert (
            await client.patch("/api/admin/access-requests/9999", json={"status": "handled"})
        ).status_code == 404

    async def test_closing_one_out_frees_the_address_to_ask_again(
        self, client: AsyncClient, unauthed_client: AsyncClient, test_user: User,
        db_session: AsyncSession,
    ) -> None:
        # The dedup is one-PENDING-per-address, not one-ever: a dismissal must
        # not permanently bar someone from requesting access.
        await _make_admin(db_session, test_user)
        await unauthed_client.post(ENDPOINT, json={"email": "again@example.com"})
        first = (await _rows(db_session))[0]
        await client.patch(
            f"/api/admin/access-requests/{first.id}", json={"status": "dismissed"}
        )

        await unauthed_client.post(ENDPOINT, json={"email": "again@example.com"})
        assert len(await _rows(db_session)) == 2


class TestAdminDelete:
    async def test_requires_admin(self, client: AsyncClient, test_user: User) -> None:
        assert (await client.delete("/api/admin/access-requests/1")).status_code == 403

    async def test_erases_the_row_and_audits_without_the_address(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        # GDPR erasure has to actually remove the third party's data, not just
        # flip a status — and the audit trail must not re-store the address.
        await _make_admin(db_session, test_user)
        req = (await submit_access_request(db_session, email="erase@example.com", message="secret")).stored
        await db_session.flush()
        assert req is not None

        resp = await client.delete(f"/api/admin/access-requests/{req.id}")
        assert resp.status_code == 204
        assert await _rows(db_session) == []

        logs = (await db_session.execute(select(AdminAuditLog))).scalars().all()
        deletion = [a for a in logs if a.action == "access_request.delete"]
        assert len(deletion) == 1
        assert "erase@example.com" not in str(deletion[0].detail)

    async def test_404_on_a_missing_request(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        await _make_admin(db_session, test_user)
        assert (await client.delete("/api/admin/access-requests/9999")).status_code == 404
