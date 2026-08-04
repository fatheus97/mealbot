import type { Dictionary } from ".";

/**
 * Czech. Typed as the COMPLETE `Dictionary`, so `tsc -b` fails the moment an
 * English key is added without one here — that type annotation is the entire
 * translation-coverage mechanism (see ./en.ts).
 *
 * Two things Czech forces that English hides:
 *
 * • FOUR plural categories, not two. `Intl.PluralRules("cs")` returns "one" for
 *   1, "few" for 2–4, "many" for decimals ("1,5 minuty") and "other" for 0 and
 *   5+ — and the noun differs in all four. Every `_one`/`_other` pair in the
 *   English file therefore wants `_few` and `_many` here.
 *
 * • CASE. A noun's ending changes with its grammatical role, so a phrase cannot
 *   be assembled from independently-translated fragments. "Podmínky služby"
 *   (nominative) becomes "Podmínkami služby" after "Souhlasím s" (instrumental)
 *   — which is why link labels live inside the sentence key that uses them.
 */
export const cs: Dictionary = {
  // ─── Language switcher ────────────────────────────────────────────────────
  "lang.label": "Jazyk",

  // ─── Auth panel ───────────────────────────────────────────────────────────
  "auth.welcome": "Vítejte",
  "auth.login": "Přihlášení",
  "auth.email": "E-mail",
  "auth.password": "Heslo",
  "auth.signIn": "Přihlásit se",
  "auth.register": "Registrovat",
  "auth.tryDemo": "Vyzkoušet demo",
  "auth.demoTitle": "Bez registrace — prozkoumejte aplikaci s ukázkovými daty.",
  "auth.logout": "Odhlásit se",
  "auth.settings": "Nastavení",
  "auth.busy": "...",
  "auth.forgotPassword": "Zapomněli jste heslo?",

  "auth.error.login": "Přihlášení se nezdařilo. Zkontrolujte přihlašovací údaje.",
  "auth.error.passwordTooShort": "Heslo musí mít alespoň 8 znaků.",
  "auth.error.acceptTerms":
    "Pro vytvoření účtu prosím potvrďte souhlas s Podmínkami služby a Zásadami ochrany osobních údajů.",
  "auth.error.accountCreated": "Účet byl vytvořen — pokračujte přihlášením.",
  "auth.error.register":
    "Registrace se nezdařila. Zkuste to prosím znovu nebo napište na {supportEmail}.",
  "auth.error.demo": "Demo není dostupné. Zkuste to prosím znovu.",

  // Instrumental case after "Souhlasím s" — see the file header.
  "auth.acceptTerms": "Souhlasím s {terms} a {privacy}.",
  "auth.acceptTerms.termsLink": "Podmínkami služby",
  "auth.acceptTerms.privacyLink": "Zásadami ochrany osobních údajů",

  "auth.closedAlpha": "Toto je uzavřená alfa verze. O přístup si napište na {supportEmail}.",

  // ─── Email verification banner ────────────────────────────────────────────
  "verify.title": "Potvrďte svou e-mailovou adresu",
  "verify.body":
    "{title}, abyste mohli začít vytvářet jídelníčky. Odkaz jsme poslali na {email} — zkontrolujte doručenou poštu (i spam).",
  "verify.sent": "Odesláno ✓",
  "verify.sending": "Odesílání…",
  "verify.resend": "Poslat odkaz znovu",
  "verify.wrongAddress": "Špatná adresa?",
  "verify.resendFailed": "Odeslání se teď nepovedlo — zkuste to prosím za minutu.",

  // ─── Plurals ──────────────────────────────────────────────────────────────
  // 1 minuta · 2–4 minuty · 1,5 minuty · 0 a 5+ minut.
  "time.minutes_one": "{count} minuta",
  "time.minutes_few": "{count} minuty",
  "time.minutes_many": "{count} minuty",
  "time.minutes_other": "{count} minut",
};
