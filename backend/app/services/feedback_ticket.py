"""Feedback ticketing (6b): open a GitHub Issue in a PRIVATE tickets repo on Accept.

The code repo is PUBLIC and reports carry PII, so an accepted report becomes an Issue
in a SEPARATE PRIVATE repo (``feedback_ticket_repo``) via a token with issues:write —
which also sets up a future scheduled Claude-Code auto-fix job. A direct httpx call (no
SDK, per the project's simple-function bias), modelled on ``email_service``.

Env-gated + best-effort: a no-op (returns None) when unconfigured, and never raises — a
ticket failure must never block or reverse the money-critical Accept/credit. The issue
references the reporter only by ``user_id`` (not their email), keeping PII out of the
ticket even though the repo is private.
"""

import logging

import httpx

from app.core.config import settings
from app.models.db_models import FeedbackReport
from app.models.feedback_schemas import FeedbackTriage

logger = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com"
_TIMEOUT = 15.0


def ticket_configured() -> bool:
    """True when both a GitHub token and a target repo are set."""
    return bool(settings.github_token and settings.feedback_ticket_repo)


def _build_title(report: FeedbackReport, triage: FeedbackTriage | None) -> str:
    if triage is not None and triage.title:
        base = triage.title
    else:
        stripped = report.message.strip()
        base = stripped.splitlines()[0][:60] if stripped else report.kind
    return f"[{report.kind}] {base}"[:120]


def _build_body(report: FeedbackReport, triage: FeedbackTriage | None) -> str:
    lines = [
        f"**Feedback report #{report.id}** — user_id `{report.user_id}`, kind `{report.kind}`",
        "",
        "### Report",
        report.message,
    ]
    if triage is not None:
        lines += [
            "",
            "### AI triage (advisory)",
            f"- type: `{triage.type}` · severity: `{triage.severity}` · "
            f"actionable: `{triage.is_actionable}`",
            f"- {triage.summary}",
        ]
        if triage.repro:
            lines.append(f"- repro: {triage.repro}")
    lines += [
        "",
        "_Opened automatically on admin Accept. The reporter is referenced only by "
        "`user_id` — do not add their identity here._",
    ]
    return "\n".join(lines)


async def create_issue_for_report(
    report: FeedbackReport, triage: FeedbackTriage | None
) -> str | None:
    """Create a GitHub Issue for an accepted report; return its ``html_url`` on
    success, or None (unconfigured / failed). Never raises.

    The report message can contain user PII, so the response body is NOT logged on a
    4xx/5xx (GitHub can echo request content back) — only the status code.
    """
    if not ticket_configured():
        return None
    title = _build_title(report, triage)
    body = _build_body(report, triage)
    transport = httpx.AsyncHTTPTransport(retries=2)
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, transport=transport) as client:
            resp = await client.post(
                f"{_GITHUB_API}/repos/{settings.feedback_ticket_repo}/issues",
                headers={
                    "Authorization": f"Bearer {settings.github_token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                json={"title": title, "body": body},
            )
    except httpx.HTTPError:
        logger.exception("GitHub issue create failed for feedback report %s", report.id)
        return None
    if resp.status_code >= 400:
        logger.error(
            "GitHub issue create returned %s for feedback report %s",
            resp.status_code, report.id,
        )
        return None
    try:
        url = resp.json().get("html_url")
    except Exception:
        logger.exception("GitHub issue response parse failed for report %s", report.id)
        return None
    return str(url) if isinstance(url, str) and url else None
