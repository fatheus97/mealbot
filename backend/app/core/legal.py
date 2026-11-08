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
TERMS_VERSION = "2026-11-08"

#: The version of the explicit consent (GDPR Art. 9(2)(a)) to process diets,
#: allergens and ingredients to avoid: the sentence the SPA shows next to the
#: checkbox (``healthConsent.label`` in frontend/src/i18n). Separate from
#: TERMS_VERSION because accepting the Terms is not this consent and must never
#: count as it. A consent is valid only for THIS version, so bumping it (for a
#: new recipient or purpose the sentence has to name) asks everyone again.
#: The SPA sends the version it displayed; the CI "legal version" job pins the
#: frontend copy (frontend/src/legal.ts) to this one.
HEALTH_CONSENT_VERSION: Final = "2026-11-08"

#: The first HEALTH_CONSENT_VERSION whose text says that household members see
#: each other's saved profiles and that plans are generated with them. Set by
#: household PR 7 together with the bump; while it was None, HOUSEHOLDS_ENABLED
#: had no effect (household_consent_ready).
HOUSEHOLD_CONSENT_VERSION: Final[str | None] = "2026-11-08"


def household_consent_ready() -> bool:
    """Whether the consent text users agree to now covers shared households."""
    version = HOUSEHOLD_CONSENT_VERSION
    return version is not None and date.fromisoformat(
        HEALTH_CONSENT_VERSION
    ) >= date.fromisoformat(version)

#: The newest version whose change is MATERIAL: the kind the Privacy Policy
#: ("Changes") and Terms §12 promise to tell users about. A user whose recorded
#: ``terms_version`` is older sees the in-app notice, and the notice email
#: (``services/policy_notice``) is keyed to this value.
#:
#: Separate from TERMS_VERSION on purpose. Every edit to a legal page moves
#: TERMS_VERSION (the CI job pins it to the printed date), so tying the notice
#: to it would make every user re-agree after a typo fix. Move THIS one only for
#: a change that matters to users, and rewrite CHANGE_SUMMARY in the same commit.
MATERIAL_CHANGE_VERSION: Final = "2026-11-08"

#: What MATERIAL_CHANGE_VERSION changed, as plain text, per locale. Shown in the
#: in-app banner and in the notice email, so one reviewed text says it in both.
#: The sentences come from the policy itself (the Czech from the hand-edited
#: cs/privacy.html), so the summary cannot claim more than the policy does.
CHANGE_SUMMARY: Final[dict[Locale, str]] = {
    "en": (
        "You can now share a household, up to six accounts. Everyone in it "
        "shares one fridge, pantry staples, meal plans and cookbook, and sees "
        "the others' email addresses. With your consent, the diets, allergies "
        "and ingredients to avoid that you save are shown to the other members "
        "and used for the household's plans when you are among the people "
        "eating, so that consent has new wording and Mealbot asks for it again. "
        "To invite someone, you enter their email address; we keep it until the "
        "invite is used or cancelled, and an unused one is deleted after it "
        "expires (48 hours). When you leave or delete your account, the shared "
        "kitchen stays with the others and your diets and allergies are removed "
        "from the plans you shared."
    ),
    "cs": (
        "Domácnost teď může sdílet až šest účtů. Všichni v ní sdílejí lednici, "
        "spížové základy, jídelníčky a kuchařku a vidí e-mailové adresy "
        "ostatních. Uložené typy stravy, alergie a suroviny, kterým se chcete "
        "vyhnout, se s vaším souhlasem zobrazují ostatním členům a používají se "
        "pro jídelníčky domácnosti, když patříte mezi ty, kdo jedí. Proto má "
        "tento souhlas nové znění a Mealbot vás o něj požádá znovu. Když někoho "
        "zvete, zadáte jeho e-mailovou adresu; uchováme ji, dokud pozvánku nikdo "
        "nepoužije nebo ji nezrušíte, a nepoužitou smažeme po vypršení (48 "
        "hodin). Když odejdete nebo smažete účet, sdílená kuchyň zůstane "
        "ostatním a vaše typy stravy a alergie se odstraní z jídelníčků, které "
        "jste sdíleli."
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
