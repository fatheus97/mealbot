"""The cheap feedback gate — pure text classification, no DB/LLM.

The gate rejects only obvious junk (too-short / no-letters / mash) and NEVER judges
quality, so these tests pin both directions: genuine reports pass, obvious garbage is
refused with the right reason, and the boundaries are exact.
"""

from app.core.feedback_gate import (
    MESSAGE_MIN_LEN,
    FeedbackRejectReason,
    evaluate_feedback,
)


class TestAccepts:
    def test_normal_bug_report(self) -> None:
        assert evaluate_feedback(
            "The meal plan crashes when I click regenerate twice."
        ).ok

    def test_short_but_real_report_at_min_len(self) -> None:
        # Exactly MESSAGE_MIN_LEN chars, 3 distinct letters — a real (if terse) report.
        msg = "abcabcabca"
        assert len(msg) == MESSAGE_MIN_LEN
        assert evaluate_feedback(msg).ok

    def test_non_latin_report_counts_its_own_letters(self) -> None:
        # Unicode letters count — a Czech report isn't rejected for lacking ASCII.
        assert evaluate_feedback("Aplikace padá při generování jídelníčku.").ok

    def test_leading_trailing_whitespace_is_stripped_but_body_passes(self) -> None:
        assert evaluate_feedback("   Login button does nothing on mobile.   ").ok


class TestRejects:
    def test_too_short(self) -> None:
        r = evaluate_feedback("bug")
        assert not r.ok
        assert r.reason is FeedbackRejectReason.TOO_SHORT

    def test_whitespace_only(self) -> None:
        r = evaluate_feedback("        ")
        assert not r.ok
        assert r.reason is FeedbackRejectReason.TOO_SHORT

    def test_whitespace_padded_short_body(self) -> None:
        # Strips to "hi" → too short, not accepted on raw length.
        r = evaluate_feedback("   hi   ")
        assert not r.ok
        assert r.reason is FeedbackRejectReason.TOO_SHORT

    def test_no_letters_digits_and_punct(self) -> None:
        r = evaluate_feedback("1234567890 !!! ###")
        assert not r.ok
        assert r.reason is FeedbackRejectReason.NO_LETTERS

    def test_low_variety_single_char_mash(self) -> None:
        r = evaluate_feedback("aaaaaaaaaaaaaa")
        assert not r.ok
        assert r.reason is FeedbackRejectReason.LOW_VARIETY

    def test_low_variety_two_letter_alternation(self) -> None:
        r = evaluate_feedback("abababababab")
        assert not r.ok
        assert r.reason is FeedbackRejectReason.LOW_VARIETY

    def test_low_variety_is_case_insensitive(self) -> None:
        # "AaAaAa..." is one distinct letter, not two.
        r = evaluate_feedback("AaAaAaAaAaAa")
        assert not r.ok
        assert r.reason is FeedbackRejectReason.LOW_VARIETY


class TestBoundaries:
    def test_one_below_min_len_rejected(self) -> None:
        msg = "abcdefghi"  # 9 chars, plenty of variety
        assert len(msg) == MESSAGE_MIN_LEN - 1
        r = evaluate_feedback(msg)
        assert not r.ok
        assert r.reason is FeedbackRejectReason.TOO_SHORT

    def test_length_checked_before_variety(self) -> None:
        # "aaa" is both too-short AND low-variety; length wins (cheapest, clearest).
        r = evaluate_feedback("aaa")
        assert r.reason is FeedbackRejectReason.TOO_SHORT

    def test_ok_result_has_no_reason(self) -> None:
        r = evaluate_feedback("A perfectly ordinary report about a real bug.")
        assert r.ok
        assert r.reason is None
