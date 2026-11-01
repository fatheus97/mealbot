"""The version of the published legal documents a user's consent is recorded against.

Recording "they accepted" without recording WHAT they accepted is close to
worthless: the Terms say (§12, "Changes to these terms") that continuing to use
Mealbot after a change means accepting it, so the documents will change, and a
bare timestamp cannot answer "which text did this person agree to?" once they
have. (This said §11 until 2026-08-08 — §11 is "Ending the agreement". Wrong
either from a renumbering or from the start; the section TITLE is quoted here so
the next renumber makes the drift visible instead of silent.)

The value is the "Last updated" date printed on ``frontend/terms.html`` and
``frontend/privacy.html``, which is what a user actually sees. A test asserts
all three agree — the failure mode this guards against is editing a legal
document and forgetting the constant, which would silently file new consents
under the old version and make every stored record a lie.

Both documents share one version deliberately. They are presented together, at
one checkbox, in one act of consent; versioning them separately would imply the
user could have accepted one and not the other, which is not what the UI offers.
"""

from datetime import date
from typing import Final

from app.core.i18n import Locale

#: Keep in sync with the "Last updated" line in frontend/terms.html and
#: frontend/privacy.html — pinned by tests/test_legal_version.py.
TERMS_VERSION = "2026-11-01"

#: The newest version whose change is MATERIAL: the kind the Privacy Policy
#: ("Changes") and Terms §12 promise to tell users about. A user whose recorded
#: ``terms_version`` is older sees the in-app notice, and the notice email
#: (``services/policy_notice``) is keyed to this value.
#:
#: Separate from TERMS_VERSION on purpose. Every edit to a legal page moves
#: TERMS_VERSION (the CI job pins it to the printed date), so tying the notice
#: to it would make every user re-agree after a typo fix. Move THIS one only for
#: a change that matters to users, and rewrite CHANGE_SUMMARY in the same commit.
MATERIAL_CHANGE_VERSION: Final = "2026-11-01"

#: What MATERIAL_CHANGE_VERSION changed, as plain text, per locale. Shown in the
#: in-app banner and in the notice email, so one reviewed text says it in both.
#: The sentences come from the policy itself (the Czech from the hand-edited
#: cs/privacy.html), so the summary cannot claim more than the policy does.
CHANGE_SUMMARY: Final[dict[Locale, str]] = {
    "en": (
        "Your meal-plan requests can now go to OpenAI as well as to Google. A "
        "request goes to OpenAI when Google's service fails or answers too "
        "slowly, and we may send a share of requests to OpenAI first, to compare "
        "which of the two writes better plans. These requests include your "
        "allergens, diet types and fridge contents, but not your email address, "
        "your name or any account identifier. OpenAI acts as our processor, may "
        "not use the data to train its models, and keeps a copy for up to 30 "
        "days to detect abuse, longer only where the law requires it or to "
        "protect against harm."
    ),
    "cs": (
        "Požadavky na jídelníček teď kromě společnosti Google můžeme posílat také "
        "společnosti OpenAI. Stane se to, když Google selže nebo neodpoví včas. "
        "Část požadavků také můžeme poslat nejdřív OpenAI, abychom porovnali, "
        "která z obou služeb sestavuje lepší jídelníčky. Požadavek obsahuje vaše "
        "alergeny, typy stravy a obsah lednice, ale ne e-mailovou adresu, jméno "
        "ani žádný identifikátor účtu. OpenAI tyto údaje zpracovává pro nás jako "
        "zpracovatel, nesmí je používat k trénování svých modelů a kopii kvůli "
        "odhalování zneužití uchovává nejvýše 30 dní, déle jen tehdy, když to "
        "vyžaduje zákon nebo ochrana před újmou."
    ),
}


def terms_notice_due(terms_version: str | None) -> bool:
    """Whether a user who last accepted ``terms_version`` must see the notice.

    NULL (an account from before the checkbox, or one an operator created) is
    due: there is no record that this person has seen any version. A value that
    is not an ISO date cannot be compared, so it is due too. The server is the
    only writer, so that would be a bug, and showing the notice is the safe way
    to be wrong.
    """
    if terms_version is None:
        return True
    try:
        accepted = date.fromisoformat(terms_version)
    except ValueError:
        return True
    return accepted < date.fromisoformat(MATERIAL_CHANGE_VERSION)
