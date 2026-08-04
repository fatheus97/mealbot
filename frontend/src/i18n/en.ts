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

  // ─── Settings modal ───────────────────────────────────────────────────────
  "settings.title": "Settings",
  "settings.close": "Close settings",
  "settings.loading": "Loading...",
  "settings.save": "Save preferences",
  "settings.saveFailed": "Failed to save preferences. Please try again.",
  "settings.discardTitle": "Discard unsaved pantry staples",
  "settings.discardBody": "You have unsaved pantry staples. Discard them?",
  "settings.discardConfirm": "Discard & close",
  "settings.discardCancel": "Keep editing",
  "settings.emailAddress": "Email address",
  "settings.changeEmail": "Change",
  "settings.sendFeedback": "💬 Send feedback",
  "settings.feedbackHintLabel": "How feedback credit works",
  "settings.feedbackHintText":
    "Earn €1 off for every accepted bug report or feature request — up to €3/month. It shows up as a “Feedback reward” credit on your next invoice, so you'll need to be on the monthly plan (subscribed or on a free trial) to receive it — annual plans are already discounted.",

  // ─── Onboarding ───────────────────────────────────────────────────────────
  "onboarding.title": "Welcome! Set up your preferences",
  "onboarding.submit": "Get Started",

  // ─── Preferences form ─────────────────────────────────────────────────────
  "prefs.country": "Country",
  "prefs.countryHint": "Used for local ingredient availability and regional recipes",
  "prefs.countryPlaceholder": "Start typing to search...",
  "prefs.countryInvalid": "Pick a country from the list.",

  "prefs.language": "Language",
  "prefs.languageHint":
    "Meal plans, recipes, and ingredient names will be generated in this language",
  // The EXAMPLES stay in English even in a Czech UI, and that is not an
  // oversight: this field's stored value is the English exonym the backend
  // whitelist accepts, so the datalist offers "Czech", not "Čeština". Showing a
  // Czech reader "např. čeština" would be showing them a value the form
  // rejects. Only the "e.g." wrapper is translated.
  "prefs.languagePlaceholder": "e.g. English, Czech, Spanish...",
  "prefs.languageInvalid": "Pick a language from the list.",

  "prefs.cuisineStyle": "Cuisine Style",
  "prefs.traditional": "Traditional",
  "prefs.experimental": "Experimental",
  "prefs.traditionalHint": "Classic dishes typical for your country",
  "prefs.experimentalHint": "Creative combinations, fusion cuisine, and novel techniques",

  "prefs.units": "Units in recipe steps",
  "prefs.unitsMetric": "Metric",
  "prefs.unitsImperial": "Imperial",
  "prefs.unitsNone": "Match my language",
  "prefs.unitsMetricHint": "Grams, millilitres, °C in the cooking steps",
  "prefs.unitsImperialHint": "Cups, ounces, °F in the cooking steps",
  "prefs.unitsNoneHint": "Whatever units are normal for your language and country",

  "prefs.includeSpices": "Include spices in shopping list",
  "prefs.includeSpicesHint":
    "Seasonings only (salt, pepper, herbs). If off, they won't appear in stock/shopping lists (still in recipe steps). For groceries you always keep — oil, flour, rice — use Pantry staples below.",
  "prefs.showPieces": "Show pieces instead of grams",
  "prefs.showPiecesHint":
    "For things you buy whole — \"2 eggs\" rather than \"120g\". Only where the amount matches whole pieces; everything else stays in grams, and the exact grams are always in the tooltip.",
  "prefs.trackSnacks": "Track snacks from receipts",
  "prefs.trackSnacksHint":
    "If off, ready-to-eat items (desserts, snacks, drinks) are excluded when scanning receipts",

  "prefs.dayLayout": "Default day layout",
  "prefs.dayLayoutHint":
    "The meals you usually want on a planned day, in order. Individual days in a plan can override this.",
  "prefs.saving": "Saving...",

  // ─── Pantry staples ───────────────────────────────────────────────────────
  "staples.title": "Pantry staples",
  "staples.hint":
    "Groceries you always keep in — oil, flour, rice, sugar — left off your generated shopping lists so you don't re-buy them. Seasonings (salt, pepper, herbs) are handled by the {includeSpices} setting above.",
  // The setting is referred to by its short name here, not its full label —
  // a quoted control name inside a sentence, scoped to this sentence.
  "staples.hintIncludeSpices": "Include spices",
  "staples.loading": "Loading staples…",
  "staples.connecting": "Connecting to server…",
  "staples.placeholder": "Add a staple (e.g. olive oil)",
  "staples.newStapleLabel": "New staple name",
  "staples.add": "Add",
  "staples.save": "Save staples",
  "staples.saving": "Saving…",
  "staples.saved": "Saved",
  "staples.saveFailed": "Save failed",
  "staples.empty": "No staples yet — add the things you never need to buy.",
  "staples.unsaved": "Unsaved changes",
  "staples.max_one": "You can have at most {count} staple.",
  "staples.max_other": "You can have at most {count} staples.",

  // ─── Day layout editor ────────────────────────────────────────────────────
  "layout.empty": "No default set — plans will use the \"Meals per day\" count instead.",
  "layout.addSlot": "+ Add slot",
  "layout.addSlotMax": "+ Add slot (max {max})",
  "layout.slot": "Slot {n}",
  "layout.moveUp": "Move slot {n} up",
  "layout.moveDown": "Move slot {n} down",
  "layout.remove": "Remove slot {n}",
  "layout.ariaLabel": "Day layout",

  // Meal types. These mirror MEAL_TYPES in constants/mealTypes.ts, and
  // i18n.test.ts asserts the two lists stay in step — a missing key here would
  // render a raw enum value into a dropdown.
  "mealType.sweet_breakfast": "Sweet breakfast",
  "mealType.savory_breakfast": "Savory breakfast",
  "mealType.brunch": "Brunch",
  "mealType.snack": "Snack",
  "mealType.soup": "Soup",
  "mealType.light_lunch": "Light lunch",
  "mealType.main_course": "Main course",
  "mealType.side_dish": "Side dish",
  "mealType.hot_dinner": "Hot dinner",
  "mealType.cold_dinner": "Cold dinner",
  "mealType.dessert": "Dessert",

  // ─── Plurals ──────────────────────────────────────────────────────────────
  // Read with tn("time.minutes", n). English has two categories; Czech has four
  // (Intl.PluralRules picks). Present here from the start so the mechanism has
  // a real user of it rather than being proven only by a test fixture.
  "time.minutes_one": "{count} minute",
  "time.minutes_other": "{count} minutes",
} as const;
