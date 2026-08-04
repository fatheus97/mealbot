import type { DictionaryFor } from ".";

/**
 * Czech. The type argument names the plural categories the language has, and
 * the annotation then requires EVERY English key plus a form for each of those
 * categories — so `tsc -b` fails the moment a string is added without its
 * Czech counterpart, and names the missing key (see ./en.ts).
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
export const cs: DictionaryFor<"one" | "few" | "many" | "other"> = {
  // ─── Language switcher ────────────────────────────────────────────────────
  "lang.label": "Jazyk",

  // ─── Auth panel ───────────────────────────────────────────────────────────
  "auth.welcome": "Vítejte",
  "auth.login": "Přihlášení",
  "auth.email": "E-mail",
  "auth.password": "Heslo",
  "auth.signIn": "Přihlásit se",
  // Reflexive, like "Přihlásit se" / "Odhlásit se" beside it. Bare
  // "Registrovat" is transitive and wants an object — it labels a button that
  // registers a device, not one that signs YOU up.
  "auth.register": "Zaregistrovat se",
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

  // ─── Settings modal ───────────────────────────────────────────────────────
  "settings.title": "Nastavení",
  "settings.close": "Zavřít nastavení",
  "settings.loading": "Načítání...",
  "settings.save": "Uložit nastavení",
  "settings.saveFailed": "Nastavení se nepodařilo uložit. Zkuste to prosím znovu.",
  "settings.discardTitle": "Zahodit neuložené zásoby spíže",
  "settings.discardBody": "Máte neuložené zásoby spíže. Chcete je zahodit?",
  "settings.discardConfirm": "Zahodit a zavřít",
  "settings.discardCancel": "Pokračovat v úpravách",
  "settings.emailAddress": "E-mailová adresa",
  "settings.changeEmail": "Změnit",
  "settings.sendFeedback": "💬 Poslat zpětnou vazbu",
  "settings.feedbackHintLabel": "Jak funguje kredit za zpětnou vazbu",
  "settings.feedbackHintText":
    "Za každé přijaté hlášení chyby nebo návrh funkce získáte €1 slevy — až €3 měsíčně. Objeví se jako kredit „Feedback reward“ na vaší příští faktuře, takže ho můžete dostat jen na měsíčním tarifu (s předplatným nebo ve zkušební době) — roční tarify už jsou zlevněné.",

  // ─── Onboarding ───────────────────────────────────────────────────────────
  "onboarding.title": "Vítejte! Nastavte si své předvolby",
  "onboarding.subtitle": "Pomohou nám vytvářet jídelníčky na míru právě vám.",
  "onboarding.submit": "Začít",

  // ─── Preferences form ─────────────────────────────────────────────────────
  "prefs.country": "Země",
  "prefs.countryHint": "Používá se pro dostupnost surovin a regionální recepty",
  "prefs.countryPlaceholder": "Začněte psát pro vyhledávání...",
  "prefs.countryInvalid": "Vyberte zemi ze seznamu.",

  "prefs.language": "Jazyk",
  "prefs.languageHint":
    "V tomto jazyce se budou generovat jídelníčky, recepty i názvy surovin",
  // Příklady zůstávají anglicky schválně — pole ukládá anglický název jazyka,
  // který přijímá seznam na serveru. Viz komentář v en.ts.
  "prefs.languagePlaceholder": "např. English, Czech, Spanish...",
  "prefs.languageInvalid": "Vyberte jazyk ze seznamu.",

  "prefs.cuisineStyle": "Styl kuchyně",
  "prefs.traditional": "Tradiční",
  "prefs.experimental": "Experimentální",
  "prefs.traditionalHint": "Klasická jídla typická pro vaši zemi",
  "prefs.experimentalHint": "Nápadité kombinace, fusion kuchyně a nové techniky",

  "prefs.units": "Jednotky v postupu",
  "prefs.unitsMetric": "Metrické",
  "prefs.unitsImperial": "Imperiální",
  "prefs.unitsNone": "Podle mého jazyka",
  "prefs.unitsMetricHint": "Gramy, mililitry a °C v postupu vaření",
  "prefs.unitsImperialHint": "Šálky, unce a °F v postupu vaření",
  "prefs.unitsNoneHint": "Jednotky obvyklé pro váš jazyk a zemi",

  "prefs.includeSpices": "Zahrnout koření do nákupního seznamu",
  "prefs.includeSpicesHint":
    "Jen dochucovadla (sůl, pepř, bylinky). Když je volba vypnutá, nebudou se objevovat v zásobách ani v nákupním seznamu (v postupu zůstávají). Na potraviny, které máte doma vždy — olej, mouku, rýži — použijte Zásoby spíže níže.",
  "prefs.showPieces": "Zobrazovat kusy místo gramů",
  "prefs.showPiecesHint":
    "U věcí, které kupujete celé — „2 vejce“ místo „120 g“. Jen tam, kde množství odpovídá celým kusům; jinde zůstávají gramy a přesná gramáž je vždy v popisku.",
  "prefs.trackSnacks": "Sledovat sladkosti a snacky z účtenek",
  "prefs.trackSnacksHint":
    "Když je volba vypnutá, hotové výrobky (dezerty, snacky, nápoje) se při skenování účtenek přeskočí",

  "prefs.dayLayout": "Výchozí rozvržení dne",
  "prefs.dayLayoutHint":
    "Jídla, která obvykle chcete mít v naplánovaném dni, v pořadí. Jednotlivé dny v plánu to mohou přepsat.",
  "prefs.saving": "Ukládání...",

  // ─── Pantry staples ───────────────────────────────────────────────────────
  "staples.title": "Zásoby spíže",
  "staples.hint":
    "Potraviny, které máte doma vždy — olej, mouku, rýži, cukr — vynecháme z generovaných nákupních seznamů, ať je nekupujete znovu. Dochucovadla (sůl, pepř, bylinky) řeší nastavení {includeSpices} výše.",
  "staples.hintIncludeSpices": "Zahrnout koření",
  "staples.loading": "Načítání zásob…",
  "staples.connecting": "Připojování k serveru…",
  "staples.placeholder": "Přidat položku (např. olivový olej)",
  "staples.newStapleLabel": "Název nové položky",
  "staples.add": "Přidat",
  "staples.save": "Uložit zásoby",
  "staples.saving": "Ukládání…",
  "staples.saved": "Uloženo",
  "staples.saveFailed": "Uložení se nezdařilo",
  "staples.empty": "Zatím žádné položky — přidejte věci, které nikdy nemusíte kupovat.",
  "staples.unsaved": "Neuložené změny",
  // 1 položku / 2-4 položky / 5+ položek
  "staples.max_one": "Můžete mít nejvýše {count} položku.",
  "staples.max_few": "Můžete mít nejvýše {count} položky.",
  "staples.max_many": "Můžete mít nejvýše {count} položky.",
  "staples.max_other": "Můžete mít nejvýše {count} položek.",

  // ─── Day layout editor ────────────────────────────────────────────────────
  "layout.empty": "Není nastaveno — plány místo toho použijí počet z „Jídel denně“.",
  "layout.addSlot": "+ Přidat jídlo",
  "layout.addSlotMax": "+ Přidat jídlo (max {max})",
  "layout.slot": "Jídlo {n}",
  "layout.moveUp": "Posunout jídlo {n} nahoru",
  "layout.moveDown": "Posunout jídlo {n} dolů",
  "layout.remove": "Odebrat jídlo {n}",
  "layout.ariaLabel": "Rozvržení dne",

  "mealType.sweet_breakfast": "Sladká snídaně",
  "mealType.savory_breakfast": "Slaná snídaně",
  "mealType.brunch": "Brunch",
  "mealType.snack": "Svačina",
  "mealType.soup": "Polévka",
  "mealType.light_lunch": "Lehký oběd",
  "mealType.main_course": "Hlavní chod",
  "mealType.side_dish": "Příloha",
  "mealType.hot_dinner": "Teplá večeře",
  "mealType.cold_dinner": "Studená večeře",
  "mealType.dessert": "Dezert",

  // ─── Plurals ──────────────────────────────────────────────────────────────
  // 1 minuta · 2–4 minuty · 1,5 minuty · 0 a 5+ minut.
  "time.minutes_one": "{count} minuta",
  "time.minutes_few": "{count} minuty",
  "time.minutes_many": "{count} minuty",
  "time.minutes_other": "{count} minut",
};
