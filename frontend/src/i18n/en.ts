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
  "fridge.saveFailed": "Failed to save: {message}",
  "fridge.unknownError": "Unknown error",
  // A "batch" is a separate purchase of the same ingredient, with its own
  // expiry date.
  "fridge.batches_one": "({count} batch)",
  "fridge.batches_other": "({count} batches)",
  "fridge.removeGroupBody_one":
    "Remove all {count} batch of \"{name}\" from your fridge?",
  "fridge.removeGroupBody_other":
    "Remove all {count} batches of \"{name}\" from your fridge?",

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

  // ─── Plurals ──────────────────────────────────────────────────────────────
  // Read with tn("time.minutes", n). English has two categories; Czech has four
  // (Intl.PluralRules picks). Present here from the start so the mechanism has
  // a real user of it rather than being proven only by a test fixture.
  "time.minutes_one": "{count} minute",
  "time.minutes_other": "{count} minutes",
} as const;
