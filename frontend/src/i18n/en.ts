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
  // The 403 branch. Separate from the line above because that advice is
  // actively wrong here — the credentials ARE correct, and a disabled user
  // following it retries the same password indefinitely.
  "auth.error.accountDisabled":
    "This account has been disabled. Contact {supportEmail} if you think " +
    "that's a mistake.",
  // The 429 branch. Same reasoning as above: the generic message would send
  // someone straight back into the rate limit they just hit.
  "auth.error.tooManyAttempts":
    "Too many sign-in attempts. Please wait a minute and try again.",
  "auth.error.passwordTooShort": "Password must be at least 8 characters.",
  "auth.error.acceptTerms":
    "Please accept the Terms of Service and Privacy Policy to create an account.",
  "auth.error.accountCreated": "Account created — please sign in to continue.",
  "auth.error.register":
    "Registration failed. Please try again or contact {supportEmail}.",
  "auth.error.demo": "Demo unavailable. Please try again.",

  // Shared by every modal in the account flow.
  "auth.emailPlaceholder": "you@example.com",
  "auth.genericError": "Something went wrong.",

  // ─── Forgot password ──────────────────────────────────────────────────────
  "auth.forgot.title": "Reset your password",
  "auth.forgot.body":
    "Enter your email and we'll send you a link to set a new password.",
  "auth.forgot.send": "Send reset link",
  "auth.forgot.sending": "Sending…",
  // The address is bolded mid-sentence, so this is one key read by <Trans>.
  "auth.forgot.sent":
    "If an account exists for {email}, we've sent it a link to reset the " +
    "password. Check your inbox — and your spam folder, just in case. The " +
    "link expires in 30 minutes.",
  "auth.forgot.done": "Done",
  "auth.forgot.cancel": "Cancel",

  // ─── Reset password (the emailed link's landing) ──────────────────────────
  "auth.reset.title": "Choose a new password",
  "auth.reset.newPassword": "New password",
  "auth.reset.confirmPassword": "Confirm new password",
  "auth.reset.submit": "Set new password",
  "auth.reset.saving": "Saving…",
  "auth.reset.done":
    "Your password has been updated, and you've been signed out everywhere " +
    "for security. Please sign in with your new password.",
  "auth.reset.signIn": "Sign in",
  "auth.reset.cancel": "Cancel",

  // Complete sentences, NOT fragments spliced after "Password needs ".
  // The English original composed one — `passwordProblem()` returned "a digit"
  // and the caller wrote `Password needs {problem}.` — which cannot survive
  // translation: Czech puts the noun in the accusative after "obsahovat"
  // ("obsahovat číslici"), and the required form differs per fragment, so no
  // single translation of the carrier sentence is correct for all of them.
  // `auth.error.passwordTooShort` above already covers the < 8 case.
  "auth.password.tooLong": "Password must be 128 characters or fewer.",
  "auth.password.needsUpper": "Password must contain an upper-case letter.",
  "auth.password.needsLower": "Password must contain a lower-case letter.",
  "auth.password.needsDigit": "Password must contain a digit.",
  "auth.password.mismatch": "Passwords don't match.",

  // ─── Invite registration (today's only way in — registration is closed) ───
  "auth.invite.title": "Create your account",
  "auth.invite.body": "You've been invited to Mealbot. Choose your login details below.",
  "auth.invite.email": "Email",
  "auth.invite.password": "Password",
  "auth.invite.confirmPassword": "Confirm password",
  "auth.invite.submit": "Create account",
  "auth.invite.creating": "Creating…",
  "auth.invite.cancel": "Cancel",
  "auth.invite.needsSignIn":
    "Your account was created, but we couldn't sign you in automatically. " +
    "Please sign in with the email and password you just chose.",
  "auth.invite.signIn": "Sign in",

  // ─── Change email address ─────────────────────────────────────────────────
  "auth.changeEmail.title": "Change email address",
  "auth.changeEmail.body":
    "Mistyped it at sign-up, or moved address? Enter the correct one and " +
    "we'll send the confirmation link there instead.",
  "auth.changeEmail.newEmail": "New email address",
  "auth.changeEmail.currentPassword": "Current password",
  "auth.changeEmail.why":
    "We ask for your password because whoever can read your email can reset it.",
  "auth.changeEmail.submit": "Change address",
  "auth.changeEmail.changing": "Changing…",
  "auth.changeEmail.unchanged": "That's already your address.",
  "auth.changeEmail.cancel": "Cancel",
  "auth.changeEmail.doneTitle": "Check your new inbox",
  // Bolded address mid-sentence → <Trans>.
  "auth.changeEmail.doneBody":
    "Your account now uses {email}. We've sent a confirmation link there — " +
    "open it to finish. You'll sign in with the new address from now on, and " +
    "any other devices have been signed out.",
  "auth.changeEmail.done": "Done",
  "auth.changeEmail.failed": "Could not change your email address.",

  // ─── Delete account ───────────────────────────────────────────────────────
  // The bullets stay specific rather than reassuring: the two things people are
  // surprised by afterwards are that the subscription stops with no refund for
  // the rest of the paid period, and that invoices survive because tax law says
  // they must. Saying so here is cheaper than saying it in a support reply.
  "auth.deleteAccount.title": "Delete your account",
  "auth.deleteAccount.body":
    "This is permanent and takes effect immediately. There is no undo and no grace period.",
  "auth.deleteAccount.pointData":
    "Your plans, recipes, cookbook, fridge, pantry staples and preferences are deleted.",
  "auth.deleteAccount.pointSubscription":
    "Your subscription is cancelled right away. The rest of the period you've paid for is not refunded.",
  "auth.deleteAccount.pointInvoices":
    "Your invoice records are kept without your account attached — tax law requires it.",
  "auth.deleteAccount.pointBackups":
    "You stay in our database backups for up to 14 days, after which they age out.",
  "auth.deleteAccount.exportFirst":
    "If you want a copy of anything, download your data first — you can't afterwards.",
  "auth.deleteAccount.currentPassword": "Current password",
  "auth.deleteAccount.submit": "Delete my account",
  "auth.deleteAccount.deleting": "Deleting…",
  "auth.deleteAccount.cancel": "Cancel",
  "auth.deleteAccount.failed": "Could not delete your account",
  "auth.deleteAccount.rateLimited":
    "Too many attempts. Please wait a minute and try again.",

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

  // ─── Confirmation-link toast (VerifyEmailHandler) ─────────────────────────
  // Missed entirely by the sweep that translated the rest of auth: the
  // component had no `t()` at all, so `untranslatedEnglishIn` had nothing to
  // compare against and reported it clean. See test/i18nAssertions.ts, SCOPE 2.
  //
  // These stay CLIENT-side copy rather than rendering the server's
  // `auth_confirm_link_invalid`, which is deliberate: the sentences below name
  // the control the user should reach for next and branch on whether they are
  // signed in, and the server knows neither of those things.
  "verifyToast.confirmed": "✅ Email confirmed — you're all set.",
  "verifyToast.alreadyUsed": "✅ That link was already used — your email is confirmed.",
  "verifyToast.invalid":
    "That confirmation link is invalid or has expired. Use “Resend link” on " +
    "the banner above to get a new one.",
  "verifyToast.invalidLoggedOut":
    "That confirmation link is invalid or has expired. Sign in and use " +
    "“Resend link” to get a new one.",
  "verifyToast.dismiss": "Dismiss",

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
  "settings.yourData": "Your data",
  "settings.exportData": "⬇️ Download my data",
  "settings.exporting": "Preparing…",
  "settings.exportFailed": "Could not prepare your data export",
  "settings.exportRateLimited":
    "You've requested this a few times already. Please try again later.",
  "settings.deleteAccount": "Delete my account",
  "settings.sendFeedback": "💬 Send feedback",
  "settings.feedbackHintLabel": "How feedback credit works",
  "settings.feedbackHintText":
    "Earn €1 off for every accepted bug report or feature request — up to €3/month. It shows up as a “Feedback reward” credit on your next invoice, so you'll need to be on the monthly plan (subscribed or on a free trial) to receive it — annual plans are already discounted.",

  // ─── Onboarding ───────────────────────────────────────────────────────────
  "onboarding.title": "Welcome! Set up your preferences",
  "onboarding.subtitle": "These help us generate meal plans tailored to you.",
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
  "prefs.needToUseEnabled": "Enable \"need to use\" tracking",
  "prefs.needToUseEnabledHint":
    "If off, the need-to-use flag is hidden everywhere in the fridge and no longer prioritized when generating meal plans. Turn it back on any time — nothing is lost.",

  "prefs.foodWaste": "Food waste",
  "prefs.wasteTracking": "Ask where food went",
  "prefs.wasteTrackingHint":
    "When you remove something from the fridge, Mealbot asks whether you ate it or threw it out. Answering is always optional. Off by default — nothing is recorded until you turn this on.",

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

  // ─── Dietary selector ─────────────────────────────────────────────────────
  // ⚠️ LIABILITY COPY. The disclaimer below is the frontend half of the
  // transparency-not-endorsement rule (docs/dietary-reference.md Part 4).
  // A translation must NEVER promise safety — no "safe", "allergen-free",
  // "guaranteed". "Helper, not a guarantee" is the claim, in every language.
  "diet.screeningDisclaimer":
    "Recipes are screened against your selected allergens and their common derivatives — this is a helper, not a guarantee. Always check product labels yourself.",
  "diet.sectionDiets": "Diets (combine any)",
  "diet.sectionAllergies": "Allergies to avoid",
  "diet.sulphiteHintLabel": "About sulphite screening",
  "diet.sulphiteHintText":
    "Sulphites are handled differently. We tell the AI to avoid them, but unlike the other 13 allergens there is no automatic check afterwards — whether sulphites must be declared depends on how much is left in the finished product, which can't be worked out from a recipe. Check labels on wine, vinegar and dried fruit yourself.",

  // Diets and allergens mirror constants/dietary.ts, which mirrors the backend
  // enums. i18n.test.ts asserts all four lists stay in step.
  "diet.vegetarian": "Vegetarian",
  "diet.vegan": "Vegan",
  "diet.pescatarian": "Pescatarian",
  "diet.gluten_free": "Gluten-free",
  "diet.dairy_free": "Dairy-free",
  "diet.keto": "Keto",
  "diet.paleo": "Paleo",
  "diet.mediterranean": "Mediterranean",
  "diet.dash": "DASH",
  "diet.low_fodmap": "Low-FODMAP",
  "diet.diabetic": "Diabetic / low-GI",
  "diet.high_protein": "High protein",
  "diet.low_carb": "Low carb",
  "diet.halal": "Halal",
  "diet.kosher": "Kosher",
  "diet.balanced": "Balanced",
  "diet.baby_food": "Baby food (6–12 mo)",

  // EU-14 (Reg. 1169/2011 Annex II). Names are REGULATORY, so the Czech is the
  // wording used in Czech food labelling, not a literal translation.
  "allergen.cereals_with_gluten": "Gluten (cereals)",
  "allergen.crustaceans": "Crustaceans",
  "allergen.eggs": "Eggs",
  "allergen.fish": "Fish",
  "allergen.peanuts": "Peanuts",
  "allergen.soybeans": "Soy",
  "allergen.milk": "Milk / dairy",
  "allergen.tree_nuts": "Tree nuts",
  "allergen.celery": "Celery",
  "allergen.mustard": "Mustard",
  "allergen.sesame": "Sesame",
  "allergen.sulphites": "Sulphites",
  "allergen.lupin": "Lupin",
  "allergen.molluscs": "Molluscs",

  // ─── Meal planner ─────────────────────────────────────────────────────────
  "planner.cookNow": "Cook Now",
  "planner.planAhead": "Plan Ahead",
  "planner.days": "Days to plan:",
  "planner.mealsPerDay": "Meals per day:",
  "planner.people": "People count:",
  "planner.stockOnly": "Use only stock ingredients (no shopping)",
  "planner.tastes": "Taste Preferences (comma separated):",
  "planner.tastesPlaceholder": "e.g. spicy, savory, Asian",
  "planner.avoid": "Ingredients to Avoid:",
  "planner.avoidPlaceholder": "Type an ingredient to avoid and press Enter",
  "planner.useUp": "Ingredients to use up (this run only):",
  "planner.useUpPlaceholder": "Type an ingredient and press Enter (fridge items auto-suggest)",
  "planner.customizeDays": "Customize meal types per day",
  "planner.customizeDaysHint": "Off: uses \"Meals per day\" count · On: overrides per day",
  "planner.day": "Day {n}",
  "planner.dayLayoutLabel": "Day {n} layout",
  "planner.startDate": "Start date",
  "planner.generate": "Generate Plan",
  "planner.generating": "Generating Plan (This takes a moment)...",
  "planner.errorPrefix": "Error:",

  "planner.titleFinished": "Finished Plan",
  "planner.titleConfirmed": "Confirmed Plan",
  "planner.titleGenerated": "Your Generated Plan",
  "planner.badgeFinished": "Finished",

  "planner.regenerate": "Regenerate Unfrozen",
  "planner.regenerating": "Regenerating...",
  "planner.confirm": "Confirm Plan",
  "planner.confirming": "Confirming...",
  "planner.unconfirm": "Un-confirm",
  "planner.unconfirming": "Un-confirming...",
  "planner.unconfirmTitle": "Restore the fridge debit and return to the editable plan view",
  "planner.finish": "Finish Plan",
  "planner.finishing": "Finishing...",
  "planner.reopen": "Reopen",
  "planner.reopening": "Reopening...",
  "planner.reopenTitle": "Re-debit ingredients for uncooked meals and return to the active plan",
  "planner.saveFailed": "Save failed",

  "planner.shoppingList": "Shopping List",
  "planner.copy": "Copy",
  "planner.copied": "Copied ✓",
  "planner.copyLabel": "Copy shopping list",
  "planner.share": "Share",
  "planner.shareLabel": "Share shopping list",

  "chips.remove": "Remove {chip}",
  "chips.count": "{count} of {max}",
  "chips.limitReached": "Limit of {max} reached — remove one to add another.",
  "fields.tastesOverLimit": "Only the first {max} will be used. You entered {count}.",

  // ─── Meal card ────────────────────────────────────────────────────────────
  "meal.freeze": "Freeze",
  "meal.frozen": "Frozen",
  "meal.cook": "Cook",
  "meal.freezeTitle": "Freeze this meal",
  "meal.unfreezeTitle": "Unfreeze this meal",
  "meal.cooked": "Cooked",
  "meal.notCooked": "Not cooked",
  "meal.markCooked": "Mark as cooked",
  "meal.markNotCooked": "Mark as not cooked",
  "meal.cookFailed": "Couldn't mark as cooked — check your connection and try again.",
  "meal.edit": "Edit",
  "meal.editTitle": "Edit this recipe",
  "meal.startCooking": "Start cooking",
  "meal.startCookingTitle": "Cook this recipe step by step",
  "meal.leftovers": "Leftovers",
  "meal.leftoverStarTitle":
    "Leftovers can't be saved to the cookbook — star the original meal instead",
  // The source is an LLM-written meal NAME, so it cannot be inflected. Czech
  // quotes it as an appositive after "z jídla" rather than trying to decline
  // it — "z Guláš" would be wrong and "z Guláše" is unknowable from here.
  "meal.leftoverFrom": "Uses leftovers from {source} — nothing extra to buy.",
  "meal.leftoverFromUnknown": "Uses leftovers from an earlier meal — nothing extra to buy.",
  "meal.ingredients": "Ingredients:",
  // The ↻ glyph carries the meaning on narrow screens; the word is the label.
  "meal.leftoversShort": "↻ Leftovers",
  "meal.leftoversFromTitle": "Leftovers from {source}",
  "meal.leftoversFromBadge": "↻ Leftovers from {source}",

  // The calendar chip's provenance line. Four shapes rather than one sentence
  // glued from "Leftovers" + "from {date}" + "— {name}": the server can fail to
  // resolve either half independently, and Czech needs "z" + a genitive date,
  // which no shared prefix can carry. The bare case reuses `meal.leftovers`.
  "calendar.leftoverFromDateAndName": "Leftovers from {date} — {name}",
  "calendar.leftoverFromDate": "Leftovers from {date}",
  "calendar.leftoverFromName": "Leftovers — {name}",

  // ─── Cook Now form ────────────────────────────────────────────────────────
  "cookNow.intro":
    "Generate one recipe for what you're cooking right now. Mark it cooked to debit your fridge.",
  "cookNow.mealType": "Meal type",
  "cookNow.people": "People",
  "cookNow.stockOnly": "Only use what's in the fridge",
  "cookNow.tastes": "Taste preferences (comma separated)",
  "cookNow.tastesPlaceholder": "e.g. spicy, light, Mediterranean",
  "cookNow.avoid": "Ingredients to avoid",
  "cookNow.avoidPlaceholder": "Type an ingredient to avoid and press Enter",
  "cookNow.feature": "Ingredients to feature",
  "cookNow.featurePlaceholder": "Type an ingredient and press Enter",
  "cookNow.note": "Note (optional)",
  "cookNow.notePlaceholder": "e.g. pasta-based, quick, use up cilantro",
  "cookNow.generate": "Generate recipe",
  "cookNow.generating": "Generating…",
  "cookNow.generateFailed": "Failed to generate recipe.",
  "cookNow.saveFailed": "Failed to save recipe.",
  "cookNow.favoriteFailed": "Couldn't save to your cookbook — check your connection and try again.",
  "cookNow.unfavoriteFailed": "Couldn't remove from your cookbook — check your connection and try again.",
  "cookNow.saving": "Saving…",
  "cookNow.cookFailed": "Couldn't save — check your connection and try again.",

  // ─── Cook mode ────────────────────────────────────────────────────────────
  "cook.done": "Done cooking",
  "cook.closeTitle": "Close cooking mode",
  "cook.ingredients": "Ingredients",
  "cook.hideIngredients": "Hide ingredients",
  "cook.startTimer": "Start a timer",
  "cook.cancel": "Cancel",
  "cook.dismiss": "Dismiss",
  "cook.pause": "Pause",
  "cook.resume": "Resume",
  "cook.addAnotherTimer": "Add another:",
  "cook.firstTimerHint": "Tap a time in the step, or set one:",
  "cook.minutesAbbrev": "min",
  "cook.customTimerLabel": "Custom timer minutes",
  "cook.setTimer": "Set timer",
  "cook.stepOf": "Step {n} of {total}",
  "cook.saving": "Saving…",
  "cook.timeUp": "⏰ Time's up!",
  "cook.timerRemaining": "Timer {clock} remaining",

  // ─── Meal editor ──────────────────────────────────────────────────────────
  "editor.header": "Editing {mealType} — meal type is fixed",
  "editor.nameLabel": "Name",
  "editor.name": "Meal name",
  "editor.totalTime": "Total time (minutes, optional)",
  "editor.totalTimeLabel": "Total time in minutes",
  "editor.ingredients": "Ingredients",
  "editor.ingredient": "Ingredient",
  "editor.needsPositiveAmount": "Every ingredient needs a positive amount in grams.",
  "editor.saving": "Saving…",
  "editor.cancel": "Cancel",
  "editor.save": "Save",
  "editor.grams": "g",
  "editor.spice": "spice",
  "editor.addIngredient": "+ Add ingredient",
  "editor.steps": "Steps",
  "editor.addStep": "+ Add step",
  "editor.ingredientName": "Ingredient {n} name",
  "editor.ingredientGrams": "Ingredient {n} grams",
  "editor.ingredientSpice": "Ingredient {n} is a spice",
  "editor.removeIngredient": "Remove ingredient {n}",
  "editor.step": "Step {n}",
  "editor.removeStep": "Remove step {n}",

  // ─── Fridge ───────────────────────────────────────────────────────────────
  "fridge.title": "Fridge",
  "fridge.loginPrompt": "Please log in to view and edit your fridge.",
  "fridge.loading": "Loading inventory...",
  "fridge.connecting": "Connecting to server…",
  "fridge.empty": "Fridge is empty.",
  "fridge.addIngredient": "Add ingredient",
  "fridge.remove": "Remove",
  "fridge.removeAll": "Remove all",
  "fridge.removing": "Removing…",
  "fridge.sort": "Sort:",
  "fridge.sortName": "Name",
  "fridge.sortQty": "Qty",
  "fridge.sortExpires": "Expires",
  "fridge.colIngredient": "Ingredient",
  "fridge.colQty": "Qty (g)",
  "fridge.colExpires": "Expires",
  "fridge.colNeedToUse": "Need to use?",
  "fridge.colAction": "Action",
  "fridge.yes": "Yes",
  "fridge.no": "No",
  "fridge.useSoon": "use soon",
  "fridge.expires": "exp {date}",
  "fridge.earliest": "earliest {date}",
  "fridge.gramsTotal": "{grams} g total",
  "fridge.groupSummary": "({shown} / {total} batches)",
  "fridge.removeGroupTitle": "Remove all batches?",
  "fridge.removeItemTitle": "Remove ingredient?",
  "fridge.removeItemBody": "Remove \"{name}\" ({grams} g) from your fridge?",
  // Shown in the remove dialog only when the food-waste preference is on.
  "fridge.wasteQuestion": "Where did it go?",
  "fridge.wasteEaten": "Ate it",
  "fridge.wasteThrownOut": "Threw it out",
  "fridge.wasteOptionalHint": "Optional — removing works either way.",
  "fridge.saveFailed": "Failed to save: {message}",
  "fridge.unknownError": "Unknown error",
  // A "batch" is a separate purchase of the same ingredient, with its own
  // expiry date.
  "fridge.batchN": "Batch {n}",
  "fridge.batches_one": "({count} batch)",
  "fridge.batches_other": "({count} batches)",
  "fridge.removeGroupBody_one":
    "Remove all {count} batch of \"{name}\" from your fridge?",
  "fridge.removeGroupBody_other":
    "Remove all {count} batches of \"{name}\" from your fridge?",

  // ─── Expired-item review (after finishing a plan) ─────────────────────────
  // Deliberately never says "safe" or "still good to eat" — the app is not
  // judging edibility and must not imply it has. The user is telling US.
  "expired.title": "Anything past its date?",
  "expired.body_one": "1 item in your fridge is past the date on it.",
  "expired.body_other": "{count} items in your fridge are past the date on them.",
  "expired.itemMeta": "{grams} g · dated {date}",
  "expired.stillFine": "Still fine",
  "expired.thrownOut": "Threw it out",
  "expired.apply": "Save",
  "expired.applying": "Saving…",
  "expired.skip": "Skip",
  // Says what "Still fine" DOES, because moving the date is a real edit to
  // their fridge and a silent one would read as a bug.
  "expired.optionalHint":
    "Optional — skip anything you're not sure about. \"Still fine\" keeps the item and moves its date on a week.",

  // ─── Fridge item modal ────────────────────────────────────────────────────
  "fridgeItem.addTitle": "Add Ingredient",
  "fridgeItem.editTitle": "Edit Ingredient",
  "fridgeItem.nameRequired": "Name is required",
  "fridgeItem.quantityPositive": "Enter a quantity greater than 0",
  "fridgeItem.namePlaceholder": "e.g. Chicken breast",
  "fridgeItem.quantity": "Quantity (g)",
  "fridgeItem.expiration": "Expiration date",
  "fridgeItem.needToUse": "Need to use",
  "fridgeItem.ok": "OK",
  "fridgeItem.cancel": "Cancel",
  "fridgeItem.name": "Name",

  // ─── Receipt scanner ──────────────────────────────────────────────────────
  "receipt.demoAlt": "Demo grocery receipt",
  "receipt.scanDemo": "Scan demo receipt",
  "receipt.selectFile": "Select receipt image or PDF",
  "receipt.openingCamera": "Opening camera…",
  "receipt.cameraPreview": "Camera preview",
  "receipt.waitingForCamera": "Waiting for the camera…",
  "receipt.capture": "Capture",
  "receipt.startingCamera": "Starting camera…",
  "receipt.reviewIntro": "Review the extracted items before adding to your fridge.",
  "receipt.noItems": "No food items found in receipt.",
  "receipt.qty": "Qty (g)",
  "receipt.expires": "Expires",
  "receipt.useSoon": "use soon",
  "receipt.remove": "Remove",
  "receipt.add": "Add to Fridge",
  "receipt.adding": "Adding...",
  "receipt.added": "Items added to fridge!",
  "receipt.typeIngredient": "ingredient",
  "receipt.typeSnack": "snack",
  "receipt.resultNew": "{grams}g (new)",
  "receipt.itemName": "Item {n} name",
  "receipt.itemQty": "Item {n} quantity",
  "receipt.itemExpiration": "Item {n} expiration date",
  "receipt.itemNeedToUse": "Item {n} need to use soon",
  "receipt.cameraDenied": "Camera permission denied — you can upload a photo instead.",
  "receipt.cameraNotFound": "No camera found — you can upload a photo instead.",
  "receipt.cameraFailed": "Couldn't open the camera — you can upload a photo instead.",
  "receipt.captureFailed": "Couldn't capture the photo — try uploading instead.",
  "receipt.scanFailed": "Failed to scan receipt.",
  "receipt.mergeFailed": "Failed to merge items.",
  // Demo receipt contents. Translated because a Czech user scanning a REAL
  // Czech receipt gets Czech names back — an English demo would misrepresent
  // the feature rather than showcase it.
  "receipt.cancel": "Cancel",
  "receipt.scanning": "Scanning receipt... This may take a few seconds.",
  "receipt.colIngredient": "Ingredient",
  "receipt.colType": "Type",
  "receipt.colAddedQty": "Added Qty (g)",
  "receipt.colResult": "Result",
  "receipt.colNeedToUse": "Need to use?",
  "receipt.colAction": "Action",
  "receipt.takePhoto": "📷 Take photo",
  "receipt.demo.milk": "Whole Milk",
  "receipt.demo.eggs": "Eggs",
  "receipt.demo.bananas": "Bananas",
  "receipt.demo.butter": "Butter",
  "receipt.demo.tomatoes": "Roma Tomatoes",
  "receipt.demo.bread": "Whole Wheat Bread",

  // ─── Plan catalog ─────────────────────────────────────────────────────────
  "plans.title": "My Plans",
  // The status enum, mirrored from the backend's PlanStatus. Same rule as
  // mealType/diet/allergen — a value with no key renders raw.
  "planStatus.planned": "planned",
  "planStatus.active": "active",
  "planStatus.cooked": "cooked",
  "planStatus.finished": "finished",
  "plans.summary": "{days}d / {meals} meals / {people}p",
  "plans.statusCount": "{status} ({cooked}/{total})",
  "plans.loading": "Loading plans...",
  "plans.empty": "No plans yet. Generate one below to get started.",
  "plans.open": "Open",
  "plans.opening": "Loading...",
  "plans.delete": "Delete",
  "plans.deleting": "Deleting…",
  "plans.repeat": "Repeat",
  "plans.repeating": "Copying…",
  "plans.repeatFailed": "Couldn't repeat that plan. Please try again.",
  "plans.deleteTitle": "Delete this plan?",
  "plans.deleteBody":
    "This will permanently delete the {days}-day / {meals}-meal plan from {date}. This cannot be undone.",
  "plans.openFailed": "Couldn't open that plan. Please try again.",
  "plans.deleteFailed": "Failed to delete plan.",
  "plans.dateFailed": "Couldn't update that plan's date. Please try again.",

  // ─── Plan calendar ────────────────────────────────────────────────────────
  "calendar.title": "Plan calendar",
  "calendar.previousMonth": "Previous month",
  "calendar.nextMonth": "Next month",
  "calendar.today": "Today",
  "calendar.close": "Close calendar",
  "calendar.plan": "Plan",
  "calendar.planNumbered": "Plan #{id}",
  "calendar.emptyMonth": "No scheduled plans in {month}. Give a plan a start date to see it here.",
  "calendar.loading": "Loading…",
  "calendar.scheduled": "Scheduled plans",
  "calendar.openPlan": "Open →",
  "calendar.openingPlan": "Opening…",
  "calendar.rescheduleFailed": "Couldn't reschedule that plan. Please try again.",

  // ─── Floating action buttons ──────────────────────────────────────────────
  "fab.openCookbook": "Open cookbook",
  "fab.openCalendar": "Open calendar",

  // ─── Cookbook ─────────────────────────────────────────────────────────────
  "cookbook.title": "Cookbook",
  "cookbook.loading": "Loading…",
  "cookbook.close": "Close cookbook",
  "cookbook.search": "Search recipes…",
  "cookbook.loadFailed": "Failed to load cookbook.",
  "cookbook.noMatches": "No recipes match your search.",
  "cookbook.empty": "Your cookbook is empty.",
  "cookbook.emptyHint": "Star a recipe in the planner or Cook Now to keep it here.",
  "cookbook.ingredients": "Ingredients",
  "cookbook.steps": "Steps",
  "cookbook.removeTitle": "Remove from cookbook?",
  // Shared ConfirmDialog defaults. Every caller passes confirmLabel and
  // loadingLabel; NOBODY passes cancelLabel, so its default is what always
  // renders — which is how "Cancel" stayed English behind eight call sites.
  "confirm.cancel": "Cancel",
  "confirm.delete": "Delete",
  "confirm.deleting": "Deleting…",
  "cookbook.removeBody":
    "Remove \"{name}\" from your cookbook? You can re-add it later from a meal plan.",
  "cookbook.remove": "Remove",
  "cookbook.removing": "Removing…",
  "cookbook.removeFromCookbook": "Remove from Cookbook",
  "cookbook.removeNamed": "Remove {name} from cookbook",
  "cookbook.removeLabel": "Remove from cookbook",

  // ─── Planner heading ──────────────────────────────────────────────────────
  // Missed in the slice that translated the rest of this component: the
  // checker compares against `en`, so a literal with no key is invisible to
  // it. See test/i18nAssertions.ts.
  "planner.heading": "Meal Planner",

  // ─── Feedback modal ───────────────────────────────────────────────────────
  "feedback.title": "Send feedback",
  "feedback.intro": "Found a bug or have an idea? Tell us — it genuinely helps shape Mealbot.",
  "feedback.type": "Type",
  "feedback.details": "Details",
  "feedback.detailsPlaceholder":
    "What happened, or what would you like to see? The more detail, the better.",
  "feedback.cancel": "Cancel",
  "feedback.send": "Send",
  "feedback.sending": "Sending…",
  "feedback.tooShort": "Please add a bit more detail.",
  "feedback.failed": "Could not send your feedback.",
  "feedback.attachScreenshot": "📎 Attach screenshot",
  "feedback.pasteHint": "You can also paste an image (Ctrl/Cmd+V) into this box.",
  "feedback.removeScreenshot": "Remove",
  "feedback.screenshotAlt": "Attached screenshot preview",
  "feedback.screenshotUnsupportedType": "Please attach a PNG or JPEG image.",
  "feedback.screenshotTooLarge": "That image is too large (max 3 MB). Try a smaller screenshot.",
  "feedback.screenshotEmpty": "That image file is empty. Try attaching it again.",
  "feedback.screenshotReadFailed": "Could not read that image. Try attaching it again.",
  "feedback.thanksTitle": "Thanks — we got it. 🙏",
  "feedback.thanksBody": "Your report is on its way to the team. We read every one.",
  "feedback.done": "Done",
  // Mirrors the FeedbackKind union; kindParity in i18n.test.ts pins the two.
  "feedbackKind.bug": "🐞 Something's broken",
  "feedbackKind.feature": "💡 Idea / feature request",
  "feedbackKind.other": "💬 Something else",

  // ─── Plurals ──────────────────────────────────────────────────────────────
  // ─── Demo banner ──────────────────────────────────────────────────────────
  "demo.banner":
    "Demo mode — generate plans, cook and rate meals. Your session and all " +
    "changes are auto-deleted in 2 hours.",

  // ─── Paywall modal ────────────────────────────────────────────────────────
  "billing.paywall.title": "Subscription required",
  "billing.paywall.body":
    "Generating meal plans and recipes needs an active subscription. Start a " +
    "10-day free trial — no charge until it ends, cancel anytime.",
  "billing.paywall.planGroup": "Billing plan",
  "billing.paywall.monthly": "Monthly",
  // The prices are keys, not literals, because the DECIMAL SEPARATOR is part
  // of the translation: Czech writes 4,99 € (comma, symbol after the number
  // with a space), and a hardcoded "€4.99" reads as broken to a Czech eye.
  // These are sticker figures for the toggle — Stripe's hosted checkout shows
  // the authoritative amount — so they are copy, not arithmetic.
  "billing.paywall.monthlyPrice": "€4.99",
  "billing.paywall.monthlySub": "per month",
  "billing.paywall.annual": "Annual",
  "billing.paywall.annualPrice": "€2.99",
  "billing.paywall.annualSub": "per month, billed €35.88/yr",
  "billing.paywall.annualBadge": "Save 40%",
  "billing.paywall.later": "Maybe later",
  "billing.paywall.start": "Start free trial",
  "billing.paywall.starting": "Starting…",
  // Its own sentence, but it REUSES `auth.acceptTerms.{terms,privacy}Link` for
  // the two labels. The warning recorded on those keys — that their Czech
  // values are inflected to fit their carrier and so are not general-purpose —
  // still stands; they are safe here specifically because this carrier governs
  // the SAME case. Both are "souhlasit s" + instrumental ("Souhlasím s
  // Podmínkami služby" / "Předplatným souhlasíte s Podmínkami služby"), so one
  // pair of labels is correct in both. A carrier taking a different case (e.g.
  // "přečtěte si Podmínky služby", accusative) would need its own labels.
  "billing.paywall.legal": "By subscribing you agree to our {terms} and {privacy}.",

  // ─── Subscription banner ──────────────────────────────────────────────────
  // A WHOLE sentence per state rather than a message plus a shared
  // "— renews {date}" suffix. Czech cannot take that suffix: "obnovuje se"
  // and "končí" govern the date differently, and the emoji-led opening
  // inflects with them. The English original concatenated, which is why the
  // dated and undated forms are separate keys here rather than one with an
  // optional hole.
  "billing.banner.trial": "🎉 Free trial.",
  "billing.banner.trialRenews": "🎉 Free trial — renews {date}.",
  "billing.banner.trialCanceled": "🚫 Trial canceled.",
  "billing.banner.trialCanceledEnds": "🚫 Trial canceled — ends {date}.",
  "billing.banner.active": "✓ Subscribed.",
  "billing.banner.activeRenews": "✓ Subscribed · renews {date}.",
  "billing.banner.canceled": "🚫 Subscription canceled.",
  "billing.banner.canceledEnds": "🚫 Subscription canceled — ends {date}.",
  "billing.banner.pastDue": "⚠️ Payment failed — update your card to keep access.",
  "billing.banner.subscribe": "Subscribe to keep generating meal plans & recipes.",
  "billing.banner.manage": "Manage",
  "billing.banner.updatePayment": "Update payment",
  "billing.banner.subscribeAction": "Subscribe",

  // Read with tn("time.minutes", n). English has two categories; Czech has four
  // (Intl.PluralRules picks). Present here from the start so the mechanism has
  // a real user of it rather than being proven only by a test fixture.
  "time.minutes_one": "{count} minute",
  "time.minutes_other": "{count} minutes",

  // ─── Persistent legal footer (AppFooter) ──────────────────────────────────
  // Separate keys from `auth.acceptTerms.*Link`, not a reuse: those are
  // inflected to sit inside a Czech sentence ("Podmínkami služby"), which reads
  // as a grammatical error standing alone. These are the nominative forms, and
  // match the wording the marketing landing's own footer already uses.
  "footer.privacy": "Privacy Policy",
  "footer.terms": "Terms of Service",
} as const;
