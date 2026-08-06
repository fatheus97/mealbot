"""Transactional email copy, per locale.

Four emails go to users: confirm-your-address, reset-your-password, your-address-
was-changed, and the feedback-credit thank-you. Everything else Resend sends is
an OPERATOR alert (``billing_alerts``, ``disk_alert``) and stays English —
there is one operator and he reads English.

─── Coverage is mypy's job ─────────────────────────────────────────────────────
``EmailCopy`` is a total ``TypedDict``, so a locale's dict literal missing a key
is a type error naming it. Adding an English string without its Czech
counterpart therefore fails CI, the same trick the frontend plays with
``DictionaryFor`` — see ``frontend/src/i18n/en.ts``.

The one thing that trick CANNOT check is the plural sets, because how many forms
a language needs is CLDR data, not type information: ``reset_expiry`` is a plain
mapping and a test asserts each locale covers every category
``plural_category`` can actually return for it. The frontend learned this the
hard way — a Slovak dictionary with only one/other compiled clean.

─── ESCAPING STAYS AT THE CALL SITE ────────────────────────────────────────────
``render`` substitutes values verbatim. Every ``$placeholder`` below that can
carry user- or operator-controlled text (``$link``, ``$new_email``) is escaped
by its caller BEFORE it gets here, exactly as it was before this file existed.
Do not "helpfully" escape here as well — that would double-escape the callers
that already do it, and hide from the next reader that the guarantee lives with
whoever knows what the value is.
"""

from __future__ import annotations

from typing import Final, TypedDict

from app.core.i18n import Locale, PluralCategory, plural_category, render


class EmailCopy(TypedDict):
    """Every user-facing string a locale must supply. Total on purpose."""

    verify_subject: str
    verify_body: str  # $link

    reset_subject: str
    reset_body: str  # $link, $expiry
    # Inflected to sit inside `reset_body` and nowhere else — the Czech forms
    # follow "během", which puts them in the genitive, so they are not a
    # reusable "N minutes" phrase. Same rule as the frontend's link labels
    # being namespaced under the sentence that inflects them.
    reset_expiry: dict[PluralCategory, str]  # $count

    change_notice_subject: str
    change_notice_body: str  # $new_email

    credit_subject: str
    credit_body: str  # $credit_eur, $max_eur


#: Hardcoded in the copy rather than derived, matching the pre-existing English.
#: `test_verification_ttl_matches_the_copy` fails if TOKEN_TTL and this drift.
VERIFY_TTL_HOURS: Final = 48

_EN: Final[EmailCopy] = {
    "verify_subject": "Confirm your Mealbot email address",
    "verify_body": (
        "<p>Welcome to Mealbot! Please confirm this email address so we can "
        "reach you about your account.</p>"
        '<p><a href="$link">Confirm my email address</a></p>'
        "<p>If the link doesn't work, paste this into your browser:<br>"
        "$link</p>"
        "<p>The link is valid for 48 hours. If you didn't create a Mealbot "
        "account, you can ignore this email.</p>"
    ),
    "reset_subject": "Reset your Mealbot password",
    "reset_body": (
        "<p>Hi,</p>"
        "<p>Someone asked to reset the password for your Mealbot account. "
        "Click below within $expiry to choose a new one:</p>"
        '<p><a href="$link">Reset your password</a></p>'
        "<p>If the link doesn't work, paste this into your browser:<br>$link</p>"
        "<p>If you didn't ask for this, you can ignore this email — your "
        "password won't change until the link above is used.</p>"
        "<p>— Mealbot</p>"
    ),
    "reset_expiry": {"one": "$count minute", "other": "$count minutes"},
    "change_notice_subject": "Your Mealbot email address was changed",
    "change_notice_body": (
        "<p>The email address on your Mealbot account was just changed to "
        "<strong>$new_email</strong>.</p>"
        "<p>This address will no longer receive account email, and signing in "
        "now uses the new address.</p>"
        "<p><strong>If this wasn't you</strong>, your password is known to "
        "someone else — reply to this email straight away. Changing the address "
        "requires the account password, so a change you did not make means the "
        "password is compromised.</p>"
    ),
    "credit_subject": "Thanks for your feedback — a credit's on the way \U0001f389",
    "credit_body": (
        '<div style="font-family: sans-serif; max-width: 480px; color: #111827; '
        'line-height: 1.5;">'
        "<p>Hi,</p>"
        "<p>Thanks for taking the time to send us feedback — it genuinely helps shape "
        "Mealbot.</p>"
        "<p>As a thank-you, we've added a <strong>&euro;$credit_eur &lsquo;Feedback "
        "reward&rsquo; credit</strong> to your next invoice — you'll see it as a line on "
        "your next bill, and there's nothing you need to do.</p>"
        "<p>Spotted something else? Keep it coming — you can earn up to "
        "<strong>&euro;$max_eur off per month</strong> for accepted reports.</p>"
        "<p>&mdash; The Mealbot team</p>"
        "</div>"
    ),
}

_CS: Final[EmailCopy] = {
    "verify_subject": "Potvrďte svou e-mailovou adresu v Mealbotu",
    "verify_body": (
        "<p>Vítejte v Mealbotu! Potvrďte prosím tuto e-mailovou adresu, "
        "abychom vás mohli kontaktovat ohledně vašeho účtu.</p>"
        '<p><a href="$link">Potvrdit e-mailovou adresu</a></p>'
        "<p>Pokud odkaz nefunguje, vložte do prohlížeče tuto adresu:<br>"
        "$link</p>"
        "<p>Odkaz platí 48 hodin. Pokud jste si účet v Mealbotu nezakládali, "
        "můžete tento e-mail ignorovat.</p>"
    ),
    "reset_subject": "Obnovení hesla k účtu Mealbot",
    "reset_body": (
        "<p>Dobrý den,</p>"
        "<p>Někdo požádal o obnovení hesla k vašemu účtu v Mealbotu. "
        "Klikněte během $expiry na odkaz níže a zvolte si nové:</p>"
        '<p><a href="$link">Obnovit heslo</a></p>'
        "<p>Pokud odkaz nefunguje, vložte do prohlížeče tuto adresu:<br>$link</p>"
        "<p>Pokud jste o obnovení nežádali, můžete tento e-mail ignorovat — "
        "heslo se nezmění, dokud odkaz výše nepoužijete.</p>"
        "<p>— Mealbot</p>"
    ),
    # Genitive, to follow "během": během 1 minuty / 3 minut / 30 minut.
    "reset_expiry": {
        "one": "$count minuty",
        "few": "$count minut",
        "other": "$count minut",
    },
    "change_notice_subject": "E-mailová adresa u vašeho účtu Mealbot byla změněna",
    "change_notice_body": (
        "<p>E-mailová adresa u vašeho účtu v Mealbotu byla právě změněna na "
        "<strong>$new_email</strong>.</p>"
        "<p>Na tuto adresu už nebudeme posílat e-maily k účtu a přihlašuje se "
        "nyní novou adresou.</p>"
        "<p><strong>Pokud jste to nebyli vy</strong>, vaše heslo zná někdo další "
        "— odpovězte prosím ihned na tento e-mail. Ke změně adresy je potřeba "
        "heslo k účtu, takže změna, kterou jste neprovedli, znamená, že heslo "
        "bylo prozrazeno.</p>"
    ),
    "credit_subject": "Díky za zpětnou vazbu — posíláme vám kredit \U0001f389",
    "credit_body": (
        '<div style="font-family: sans-serif; max-width: 480px; color: #111827; '
        'line-height: 1.5;">'
        "<p>Dobrý den,</p>"
        "<p>Díky, že jste si našli čas nám poslat zpětnou vazbu — opravdu nám "
        "pomáhá Mealbota zlepšovat.</p>"
        "<p>Jako poděkování jsme vám k příští faktuře přidali kredit "
        "<strong>&euro;$credit_eur &bdquo;Feedback reward&ldquo;</strong> — "
        "uvidíte ho jako položku na dalším vyúčtování a nemusíte nic dělat.</p>"
        "<p>Všimli jste si něčeho dalšího? Posílejte to dál — za přijatá hlášení "
        "můžete získat až <strong>&euro;$max_eur měsíčně</strong>.</p>"
        "<p>&mdash; Tým Mealbot</p>"
        "</div>"
    ),
}

COPY: Final[dict[Locale, EmailCopy]] = {"en": _EN, "cs": _CS}


def expiry_phrase(locale: Locale, minutes: int) -> str:
    """The "30 minutes" fragment for the reset email, in the right plural form."""
    forms = COPY[locale]["reset_expiry"]
    category = plural_category(locale, minutes)
    # "other" is the form every locale defines; falling back to it keeps a
    # missing category rendering a real phrase rather than a KeyError inside a
    # best-effort mail path. `test_every_locale_covers_its_plural_categories`
    # is what actually keeps the fallback unused.
    template = forms.get(category) or forms["other"]
    return render(template, count=str(minutes))
