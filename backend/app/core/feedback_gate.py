"""The cheap first-pass gate for user feedback — pure text checks, no DB, no LLM.

This is the deliberately-dumb edge filter in front of the (expensive, advisory) LLM
triage. Its ONLY job is to reject obvious junk — empty / too-short / no-letters /
keyboard-mash — so that garbage never reaches the model or the moderation queue. It
does **not** judge whether a report is *valid, useful, or in scope* — that is a human
call, informed by the advisory triage. Being conservative is the point: a false
reject turns a real user's report away, so every rule here fires only on input no
genuine report could plausibly match.

Pure and dependency-free (like ``core.email_normalize``) so the winner/loser logic is
directly unit-testable and can't drift with app wiring. Lives in ``core`` and owns
the intake length bounds so the schema, the gate, and the tests share one source of
truth without a models→core→models import cycle.
"""

from dataclasses import dataclass
from enum import Enum

# Message body bounds. MIN is a floor a genuine report clears easily (a sentence);
# MAX bounds storage, prompt-token cost, and UI blow-up (also enforced at the schema
# layer, so an oversized body is a clean 422 rather than a truncated row). PAGE is
# the optional "what view were you on" context the client may attach.
MESSAGE_MIN_LEN = 10
MESSAGE_MAX_LEN = 4000
PAGE_MAX_LEN = 200

# A real report uses more than this many distinct letters; at/under it the body is
# single-key mash ("aaaaaaaaaa") or a two-letter alternation ("ababababab").
_MIN_DISTINCT_LETTERS = 2


class FeedbackRejectReason(str, Enum):
    """Why the cheap gate refused a submission (maps to a friendly API message)."""

    TOO_SHORT = "too_short"
    NO_LETTERS = "no_letters"
    LOW_VARIETY = "low_variety"


@dataclass(frozen=True)
class GateResult:
    ok: bool
    reason: FeedbackRejectReason | None = None


def evaluate_feedback(message: str) -> GateResult:
    """Classify a message body as ACCEPT or a specific junk reject. Never raises.

    Order matters: length first (cheapest, most common), then "contains no letters
    at all" (pure digits / punctuation / emoji), then "too few distinct letters"
    (keyboard mash). Whitespace is stripped first so "   " and "a a a a a" are judged
    on their real content. Everything else passes — the gate does NOT assess quality.
    """
    text = message.strip()
    if len(text) < MESSAGE_MIN_LEN:
        return GateResult(False, FeedbackRejectReason.TOO_SHORT)

    letters = [c for c in text if c.isalpha()]
    if not letters:
        return GateResult(False, FeedbackRejectReason.NO_LETTERS)

    # casefold() so "AaAa" counts as one distinct letter, not two — a mash is a mash
    # regardless of case. Unicode-aware (isalpha/casefold), so non-Latin reports are
    # judged on their own distinct-letter count, not rejected for lacking ASCII.
    if len({c.casefold() for c in letters}) <= _MIN_DISTINCT_LETTERS:
        return GateResult(False, FeedbackRejectReason.LOW_VARIETY)

    return GateResult(True)
