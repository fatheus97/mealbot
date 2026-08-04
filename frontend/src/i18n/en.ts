/**
 * The English dictionary — the SOURCE OF TRUTH for every UI string key.
 *
 * `keyof typeof en` is the `TranslationKey` type, so this file defines what
 * `t()` will accept anywhere in the app. Every other locale is typed as a
 * COMPLETE map of these keys (see ./cs.ts), which makes the compiler the
 * coverage tool: adding an English string here fails `tsc -b` until the Czech
 * one exists. No lint rule, no extraction script, no untranslated-key report —
 * the build simply will not pass.
 *
 * ─── Conventions ────────────────────────────────────────────────────────────
 * • Keys are flat and dotted, grouped by screen: `auth.signIn`, not nested
 *   objects. Flat keys are what makes `keyof typeof` produce a usable union.
 * • `{name}` placeholders interpolate values. The same placeholders must appear
 *   in every locale — i18n.test.ts asserts that, because a translator dropping
 *   `{email}` silently ships a sentence with a hole in it.
 * • Plurals use `_one` / `_other` SUFFIXES on a shared base key and are read
 *   with `tn()`. English needs two forms; Czech needs four. Never assemble a
 *   plural by concatenating a number and a noun.
 * • Sentences containing a link or bold run stay ONE key with placeholders for
 *   the marked-up parts (see `auth.acceptTerms`), rendered with <Trans>. They
 *   are never split into prefix/suffix fragments: word order differs between
 *   languages, and a Czech noun after a preposition changes case, so a fragment
 *   translated in isolation cannot be made correct.
 */
export const en = {
  // ─── Language switcher ────────────────────────────────────────────────────
  // Names the UI language only. The language recipes are WRITTEN in is a
  // separate setting (`User.language`, in preferences) and stays that way — see
  // store/useLocaleStore.ts for why the two lists are not the same list.
  "lang.label": "Language",

  // ─── Auth panel ───────────────────────────────────────────────────────────
  "auth.welcome": "Welcome",
  "auth.login": "Login",
  "auth.email": "Email",
  "auth.password": "Password",
  "auth.signIn": "Sign In",
  "auth.register": "Register",
  "auth.tryDemo": "Try Demo",
  "auth.demoTitle": "No signup needed — explore with mocked data.",
  "auth.logout": "Logout",
  "auth.settings": "Settings",
  "auth.busy": "...",
  "auth.forgotPassword": "Forgot your password?",

  "auth.error.login": "Login failed. Check your credentials.",
  "auth.error.passwordTooShort": "Password must be at least 8 characters.",
  "auth.error.acceptTerms":
    "Please accept the Terms of Service and Privacy Policy to create an account.",
  "auth.error.accountCreated": "Account created — please sign in to continue.",
  "auth.error.register":
    "Registration failed. Please try again or contact {supportEmail}.",
  "auth.error.demo": "Demo unavailable. Please try again.",

  // One key, two placeholders: Czech puts both documents in the instrumental
  // case after "Souhlasím s", which a prefix/suffix split cannot express.
  //
  // The two link labels are namespaced UNDER this sentence on purpose. Their
  // Czech values are inflected to fit it ("Podmínkami služby"), so they are not
  // reusable as a page heading — a key named `auth.termsOfService` would invite
  // exactly that, and read as a grammatical error wherever it landed. A heading
  // needs its own key with the nominative form.
  "auth.acceptTerms": "I accept the {terms} and {privacy}.",
  "auth.acceptTerms.termsLink": "Terms of Service",
  "auth.acceptTerms.privacyLink": "Privacy Policy",

  "auth.closedAlpha": "This is a closed alpha. For access, contact {supportEmail}.",

  // ─── Email verification banner ────────────────────────────────────────────
  "verify.title": "Confirm your email address",
  "verify.body":
    "{title} to start generating plans. We've sent a link to {email} — check your inbox (and spam).",
  "verify.sent": "Sent ✓",
  "verify.sending": "Sending…",
  "verify.resend": "Resend link",
  "verify.wrongAddress": "Wrong address?",
  "verify.resendFailed": "Couldn't resend just now — please try again in a minute.",

  // ─── Plurals ──────────────────────────────────────────────────────────────
  // Read with tn("time.minutes", n). English has two categories; Czech has four
  // (Intl.PluralRules picks). Present here from the start so the mechanism has
  // a real user of it rather than being proven only by a test fixture.
  "time.minutes_one": "{count} minute",
  "time.minutes_other": "{count} minutes",
} as const;
