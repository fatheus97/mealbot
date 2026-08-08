// Runtime copy for the static marketing landing, per locale.
//
// ─── Why this is not the SPA's i18n ─────────────────────────────────────────
// The SPA (frontend/src/i18n/) resolves its locale from a zustand store that a
// user changes with a picker. This bundle has no picker and no store: the
// visitor is on `/` or on `/cs/`, and which one they are on IS the answer.
//
// So the locale is read from `document.documentElement.lang` — the attribute
// the page already has to declare for screen readers and for hreflang. Nothing
// new to keep in sync, and the failure mode is benign: a page that forgets the
// attribute renders English, which is what it renders today.
//
// ─── Strings that are NOT here ──────────────────────────────────────────────
// Everything the visitor reads before JS runs lives in the HTML, translated
// there. This file covers only what the bundle WRITES at runtime: button
// labels it swaps, validation it invents, and fetch failures it reports.

export type LandingLocale = 'en' | 'cs';

/**
 * The page's own declared language, narrowed to a locale we have copy for.
 *
 * Matches on the primary subtag, so `cs`, `cs-CZ` and `CS` all resolve — the
 * same rule the backend applies to `Accept-Language`. Anything else is English,
 * including a missing attribute.
 */
export function landingLocale(doc: Document = document): LandingLocale {
  const tag = doc.documentElement.getAttribute('lang')?.toLowerCase() ?? '';
  return tag.split('-')[0] === 'cs' ? 'cs' : 'en';
}

export interface LandingCopy {
  /** cta.ts — the primary CTA once /api/config reports registration is open. */
  ctaGetStarted: string;
  /** cta.ts — the demo button while a demo session is being minted. */
  ctaDemoStarting: string;

  /**
   * cta.ts — the four places the page states the ACCESS MODEL, replaced once
   * /api/config reports registration is open.
   *
   * The static HTML carries the closed wording ("private alpha", "leave your
   * email and we'll get back to you with an invite"), which is both true today
   * and the correct fail-safe: a visitor whose /api/config never resolves reads
   * the more conservative claim, and is told to ask rather than wrongly told to
   * sign up. Only the open variants live here, because only they are swapped in.
   *
   * Without these, flipping REGISTRATION_ENABLED leaves the primary CTA saying
   * "Get started" on a page that still says four times over that sign-ups are
   * closed — including in the FAQPage JSON-LD Google has indexed.
   */
  openCtaNote: string;
  openFaqAvailability: string;
  openAccessHeading: string;
  openAccessIntro: string;

  /** authModal.ts — login mode. */
  authLoginTitle: string;
  authLoginSubmit: string;
  authLoginPrompt: string;
  authLoginSwitchTo: string;
  /** authModal.ts — register mode. */
  authRegisterTitle: string;
  authRegisterSubmit: string;
  authRegisterPrompt: string;
  authRegisterSwitchTo: string;
  /** authModal.ts — client-side validation and in-flight labels. */
  authNeedEmail: string;
  authNeedPassword: string;
  authNeedTerms: string;
  authBusyRegister: string;
  authBusyLogin: string;
  authGenericError: string;

  /**
   * authApi.ts — client-side password complexity feedback.
   *
   * Functions, not strings, because two of them interpolate a bound. The
   * Czech forms read "…alespoň 8 znaků" — genitive plural, which is correct
   * for every value 5 and above. MIN_PASSWORD_LENGTH is 8 and MAX is far
   * higher, so no plural machinery is warranted; if MIN ever drops below 5
   * the noun becomes "znaky" and this needs the treatment error_copy.py gives
   * its plural keys.
   */
  passwordTooShort: (min: number) => string;
  passwordTooLong: (max: number) => string;
  passwordNeedsUpper: string;
  passwordNeedsLower: string;
  passwordNeedsDigit: string;

  /**
   * authApi.ts — the failures a visitor actually hits. `authLoginFailed`
   * fires on every wrong password, which makes it the most-read string in
   * this table.
   *
   * Wording is taken from the SPA dictionary (`auth.error.*`) rather than
   * reinvented: the landing modal and the app AuthBar are two front doors to
   * the same login, and a visitor who fails on one and retries on the other
   * should not be told two different things.
   */
  authLoginFailed: string;
  authRegisterFailed: string;
  authDemoFailed: string;
  authRegisteredNotSignedIn: string;

  /** accessRequest.ts */
  accessGenericFailure: string;
  accessRateLimited: string;
  accessBadEmail: string;
  accessNeedEmail: string;
  accessBusy: string;
  accessSubmit: string;
  accessThanks: string;
}

const EN: LandingCopy = {
  ctaGetStarted: 'Get started',
  ctaDemoStarting: 'Starting…',

  openCtaNote: '10-day free trial. Cancel any time.',
  openFaqAvailability:
    'Yes. Sign up above and start a 10-day free trial — no charge until it ends.',
  openAccessHeading: 'Questions before you start?',
  openAccessIntro:
    "Sign-ups are open — use Get started above. If you'd rather ask something first, leave your email and we'll reply.",

  authLoginTitle: 'Log in',
  authLoginSubmit: 'Log in',
  authLoginPrompt: "Don't have an account?",
  authLoginSwitchTo: 'Create one',
  authRegisterTitle: 'Create your account',
  authRegisterSubmit: 'Create account',
  authRegisterPrompt: 'Already have an account?',
  authRegisterSwitchTo: 'Log in',
  authNeedEmail: 'Enter your email address.',
  authNeedPassword: 'Enter your password.',
  authNeedTerms:
    'Please accept the Terms of Service and Privacy Policy to create an account.',
  authBusyRegister: 'Creating…',
  authBusyLogin: 'Logging in…',
  authGenericError: 'Something went wrong. Please try again.',

  passwordTooShort: (min) => `Password must be at least ${min} characters.`,
  passwordTooLong: (max) => `Password must be at most ${max} characters.`,
  passwordNeedsUpper: 'Password must contain an uppercase letter.',
  passwordNeedsLower: 'Password must contain a lowercase letter.',
  passwordNeedsDigit: 'Password must contain a digit.',

  authLoginFailed: 'Login failed. Check your credentials.',
  authRegisterFailed:
    'Registration failed. Please try again or contact info@trymealbot.com.',
  authDemoFailed: 'Could not start the demo. Please try again.',
  authRegisteredNotSignedIn: 'Account created — please sign in to continue.',

  accessGenericFailure:
    'Something went wrong. Please try again, or email info@trymealbot.com.',
  accessRateLimited: 'Too many requests just now. Please try again in a minute.',
  accessBadEmail: "That doesn't look like a valid email address — please check it.",
  accessNeedEmail: 'Enter your email address.',
  accessBusy: 'Sending…',
  accessSubmit: 'Send request',
  accessThanks: "Thanks — we've got your request.",
};

const CS: LandingCopy = {
  ctaGetStarted: 'Začít',
  ctaDemoStarting: 'Spouštím…',

  openCtaNote: '10denní zkušební verze zdarma. Zrušit můžete kdykoli.',
  openFaqAvailability:
    'Ano. Zaregistrujte se výše a začněte s 10denní zkušební verzí zdarma; platíte až po jejím skončení.',
  openAccessHeading: 'Máte otázku, než začnete?',
  openAccessIntro:
    'Registrace je otevřená, použijte tlačítko Začít výše. Pokud se chcete nejdříve na něco zeptat, nechte nám e-mail a ozveme se.',

  authLoginTitle: 'Přihlásit se',
  authLoginSubmit: 'Přihlásit se',
  authLoginPrompt: 'Nemáte účet?',
  authLoginSwitchTo: 'Vytvořte si ho',
  authRegisterTitle: 'Vytvořte si účet',
  authRegisterSubmit: 'Vytvořit účet',
  authRegisterPrompt: 'Už účet máte?',
  authRegisterSwitchTo: 'Přihlaste se',
  authNeedEmail: 'Zadejte svou e-mailovou adresu.',
  authNeedPassword: 'Zadejte heslo.',
  // "Souhlas s" governs the instrumental case, so both document names are
  // inflected — Obchodní podmínky → Obchodními podmínkami. This is why the
  // sentence is ONE string and not assembled from the link labels.
  authNeedTerms:
    'Pro vytvoření účtu prosím potvrďte souhlas s Obchodními podmínkami a Zásadami ochrany osobních údajů.',
  authBusyRegister: 'Vytvářím…',
  authBusyLogin: 'Přihlašuji…',
  authGenericError: 'Něco se pokazilo. Zkuste to prosím znovu.',

  passwordTooShort: (min) => `Heslo musí mít alespoň ${min} znaků.`,
  passwordTooLong: (max) => `Heslo musí mít nejvýše ${max} znaků.`,
  passwordNeedsUpper: 'Heslo musí obsahovat velké písmeno.',
  passwordNeedsLower: 'Heslo musí obsahovat malé písmeno.',
  passwordNeedsDigit: 'Heslo musí obsahovat číslici.',

  // Verbatim from src/i18n/cs.ts `auth.error.*`, with {supportEmail}
  // resolved — the landing page has no interpolator and one support address.
  authLoginFailed: 'Přihlášení se nezdařilo. Zkontrolujte přihlašovací údaje.',
  authRegisterFailed:
    'Registrace se nezdařila. Zkuste to prosím znovu nebo napište na info@trymealbot.com.',
  authDemoFailed: 'Demo není dostupné. Zkuste to prosím znovu.',
  authRegisteredNotSignedIn: 'Účet byl vytvořen — pokračujte přihlášením.',

  accessGenericFailure:
    'Něco se pokazilo. Zkuste to prosím znovu, nebo napište na info@trymealbot.com.',
  accessRateLimited: 'Teď je požadavků příliš mnoho. Zkuste to prosím za minutu.',
  accessBadEmail: 'Tohle nevypadá jako platná e-mailová adresa — zkontrolujte ji prosím.',
  accessNeedEmail: 'Zadejte svou e-mailovou adresu.',
  accessBusy: 'Odesílám…',
  accessSubmit: 'Odeslat žádost',
  accessThanks: 'Díky — žádost máme.',
};

const COPY: Record<LandingLocale, LandingCopy> = { en: EN, cs: CS };

export function landingCopy(locale: LandingLocale = landingLocale()): LandingCopy {
  return COPY[locale];
}
