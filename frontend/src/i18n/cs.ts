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
  "auth.error.accountDisabled":
    "Tento účet byl zablokován. Pokud si myslíte, že jde o omyl, napište na " +
    "{supportEmail}.",
  "auth.error.tooManyAttempts":
    "Příliš mnoho pokusů o přihlášení. Počkejte prosím minutu a zkuste to znovu.",
  "auth.error.passwordTooShort": "Heslo musí mít alespoň 8 znaků.",
  "auth.error.acceptTerms":
    "Pro vytvoření účtu prosím potvrďte souhlas s Podmínkami služby a Zásadami ochrany osobních údajů.",
  "auth.error.accountCreated": "Účet byl vytvořen — pokračujte přihlášením.",
  "auth.error.register":
    "Registrace se nezdařila. Zkuste to prosím znovu nebo napište na {supportEmail}.",
  "auth.error.demo": "Demo není dostupné. Zkuste to prosím znovu.",

  "auth.emailPlaceholder": "vas@email.cz",
  "auth.genericError": "Něco se pokazilo.",

  "auth.forgot.title": "Obnovení hesla",
  "auth.forgot.body":
    "Zadejte svůj e-mail a pošleme vám odkaz pro nastavení nového hesla.",
  "auth.forgot.send": "Poslat odkaz",
  "auth.forgot.sending": "Odesílám…",
  // Two sentences where the English has a dash. Czech does not punctuate an
  // afterthought that way, and "just in case" has no natural Czech carrier —
  // "i složku se spamem" already carries it.
  "auth.forgot.sent":
    "Pokud účet s adresou {email} existuje, poslali jsme na něj odkaz pro " +
    "obnovení hesla. Zkontrolujte si schránku i složku se spamem. " +
    "Odkaz platí 30 minut.",
  "auth.forgot.done": "Hotovo",
  "auth.forgot.cancel": "Zrušit",

  "auth.reset.title": "Zvolte si nové heslo",
  "auth.reset.newPassword": "Nové heslo",
  "auth.reset.confirmPassword": "Nové heslo znovu",
  "auth.reset.submit": "Nastavit heslo",
  "auth.reset.saving": "Ukládám…",
  "auth.reset.done":
    "Heslo bylo změněno. Z bezpečnostních důvodů jsme vás odhlásili na všech " +
    "zařízeních, přihlaste se prosím novým heslem.",
  "auth.reset.signIn": "Přihlásit se",
  "auth.reset.cancel": "Zrušit",

  // "obsahovat" takes the accusative and each noun inflects differently
  // ("velké písmeno" / "číslici"), which is exactly why these are whole
  // sentences rather than fragments dropped into a shared carrier.
  "auth.password.tooLong": "Heslo může mít nejvýše 128 znaků.",
  "auth.password.needsUpper": "Heslo musí obsahovat velké písmeno.",
  "auth.password.needsLower": "Heslo musí obsahovat malé písmeno.",
  "auth.password.needsDigit": "Heslo musí obsahovat číslici.",
  "auth.password.mismatch": "Hesla se neshodují.",

  "auth.invite.title": "Vytvořte si účet",
  "auth.invite.body":
    "Dostali jste pozvánku do Mealbotu. Zvolte si níže přihlašovací údaje.",
  "auth.invite.email": "E-mail",
  "auth.invite.password": "Heslo",
  "auth.invite.confirmPassword": "Heslo znovu",
  "auth.invite.submit": "Vytvořit účet",
  "auth.invite.creating": "Vytvářím…",
  "auth.invite.cancel": "Zrušit",
  "auth.invite.needsSignIn":
    "Účet byl vytvořen, ale nepodařilo se vás automaticky přihlásit. " +
    "Přihlaste se prosím e-mailem a heslem, které jste si právě zvolili.",
  "auth.invite.signIn": "Přihlásit se",

  "auth.changeEmail.title": "Změna e-mailové adresy",
  "auth.changeEmail.body":
    "Napsali jste ji při registraci špatně, nebo používáte jinou? Zadejte " +
    "správnou adresu a potvrzovací odkaz pošleme na ni.",
  "auth.changeEmail.newEmail": "Nová e-mailová adresa",
  "auth.changeEmail.currentPassword": "Současné heslo",
  "auth.changeEmail.why":
    "Heslo po vás chceme proto, že kdo se dostane do vaší e-mailové schránky, " +
    "může si ho nechat obnovit.",
  "auth.changeEmail.submit": "Změnit adresu",
  "auth.changeEmail.changing": "Měním…",
  "auth.changeEmail.unchanged": "Tuto adresu už na účtu máte.",
  "auth.changeEmail.cancel": "Zrušit",
  "auth.changeEmail.doneTitle": "Zkontrolujte novou schránku",
  "auth.changeEmail.doneBody":
    "Váš účet teď používá {email}. Poslali jsme tam potvrzovací odkaz, " +
    "otevřete ho a změnu tím dokončíte. Od této chvíle se budete přihlašovat " +
    "novou adresou a na ostatních zařízeních jsme vás odhlásili.",
  "auth.changeEmail.done": "Hotovo",
  "auth.changeEmail.failed": "E-mailovou adresu se nepodařilo změnit.",

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

  // ─── Confirmation-link toast (VerifyEmailHandler) ─────────────────────────
  "verifyToast.confirmed": "✅ E-mail potvrzen — máte hotovo.",
  "verifyToast.alreadyUsed": "✅ Tento odkaz už byl použit — váš e-mail je potvrzený.",
  // "Resend link" is quoted because it names a button the user must find on
  // screen, so it carries the Czech label from `verify.resend`, not the English.
  "verifyToast.invalid":
    "Tento potvrzovací odkaz je neplatný nebo mu vypršela platnost. Použijte " +
    "„Poslat odkaz znovu“ v pruhu nahoře a nechte si poslat nový.",
  "verifyToast.invalidLoggedOut":
    "Tento potvrzovací odkaz je neplatný nebo mu vypršela platnost. Přihlaste " +
    "se a nechte si poslat nový přes „Poslat odkaz znovu“.",
  "verifyToast.dismiss": "Zavřít",

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

  // ─── Dietary selector ─────────────────────────────────────────────────────
  // ⚠️ Nikdy neslibovat bezpečnost — "pomůcka, ne záruka". Viz en.ts.
  "diet.screeningDisclaimer":
    "Recepty kontrolujeme proti vámi zvoleným alergenům a jejich běžným derivátům — je to pomůcka, ne záruka. Vždy si sami zkontrolujte etikety výrobků.",
  "diet.sectionDiets": "Diety (lze kombinovat)",
  "diet.sectionAllergies": "Alergeny, kterým se vyhnout",
  "diet.sulphiteHintLabel": "O kontrole siřičitanů",
  "diet.sulphiteHintText":
    "Se siřičitany zacházíme jinak. Umělé inteligenci říkáme, aby se jim vyhnula, ale na rozdíl od ostatních 13 alergenů neprobíhá žádná následná automatická kontrola — jestli se siřičitany musí uvádět, závisí na tom, kolik jich zůstane v hotovém výrobku, což z receptu spočítat nelze. Etikety na víně, octu a sušeném ovoci si zkontrolujte sami.",

  "diet.vegetarian": "Vegetariánská",
  "diet.vegan": "Veganská",
  "diet.pescatarian": "Pescatariánská",
  "diet.gluten_free": "Bezlepková",
  "diet.dairy_free": "Bez mléka",
  "diet.keto": "Keto",
  "diet.paleo": "Paleo",
  "diet.mediterranean": "Středomořská",
  "diet.dash": "DASH",
  "diet.low_fodmap": "Nízký obsah FODMAP",
  "diet.diabetic": "Diabetická / nízký GI",
  "diet.high_protein": "Vysoký obsah bílkovin",
  "diet.low_carb": "Nízký obsah sacharidů",
  "diet.halal": "Halal",
  "diet.kosher": "Košer",
  "diet.balanced": "Vyvážená",
  "diet.baby_food": "Příkrmy (6–12 měsíců)",

  // Znění podle českého značení potravin (nařízení 1169/2011, příloha II).
  "allergen.cereals_with_gluten": "Lepek (obiloviny)",
  "allergen.crustaceans": "Korýši",
  "allergen.eggs": "Vejce",
  "allergen.fish": "Ryby",
  "allergen.peanuts": "Arašídy",
  "allergen.soybeans": "Sója",
  "allergen.milk": "Mléko",
  "allergen.tree_nuts": "Skořápkové plody",
  "allergen.celery": "Celer",
  "allergen.mustard": "Hořčice",
  "allergen.sesame": "Sezam",
  "allergen.sulphites": "Siřičitany",
  "allergen.lupin": "Vlčí bob",
  "allergen.molluscs": "Měkkýši",

  // ─── Meal planner ─────────────────────────────────────────────────────────
  "planner.cookNow": "Uvařit hned",
  "planner.planAhead": "Naplánovat dopředu",
  "planner.days": "Počet dní:",
  "planner.mealsPerDay": "Jídel denně:",
  "planner.people": "Počet osob:",
  "planner.stockOnly": "Použít jen suroviny ze zásob (bez nákupu)",
  "planner.tastes": "Chuťové preference (oddělené čárkou):",
  "planner.tastesPlaceholder": "např. pikantní, slané, asijské",
  "planner.avoid": "Suroviny, kterým se vyhnout:",
  "planner.avoidPlaceholder": "Napište surovinu a stiskněte Enter",
  "planner.useUp": "Suroviny ke spotřebování (jen pro toto generování):",
  "planner.useUpPlaceholder": "Napište surovinu a stiskněte Enter (položky z lednice se napovídají)",
  "planner.customizeDays": "Upravit typy jídel pro jednotlivé dny",
  "planner.customizeDaysHint": "Vypnuto: použije se počet z „Jídel denně“ · Zapnuto: přepíše se po dnech",
  "planner.day": "{n}. den",
  "planner.dayLayoutLabel": "Rozvržení {n}. dne",
  "planner.startDate": "Datum začátku",
  "planner.generate": "Vytvořit jídelníček",
  "planner.generating": "Vytváříme jídelníček (chvíli to potrvá)...",
  "planner.errorPrefix": "Chyba:",

  "planner.titleFinished": "Dokončený jídelníček",
  "planner.titleConfirmed": "Potvrzený jídelníček",
  "planner.titleGenerated": "Váš jídelníček",
  "planner.badgeFinished": "Dokončeno",

  "planner.regenerate": "Přegenerovat nezamčené",
  "planner.regenerating": "Přegenerovávám...",
  "planner.confirm": "Potvrdit jídelníček",
  "planner.confirming": "Potvrzuji...",
  "planner.unconfirm": "Zrušit potvrzení",
  "planner.unconfirming": "Ruším potvrzení...",
  "planner.unconfirmTitle": "Vrátit suroviny do lednice a přejít zpět na upravitelný jídelníček",
  "planner.finish": "Dokončit jídelníček",
  "planner.finishing": "Dokončuji...",
  "planner.reopen": "Znovu otevřít",
  "planner.reopening": "Otevírám...",
  "planner.reopenTitle": "Znovu odečíst suroviny na neuvařená jídla a vrátit se k aktivnímu jídelníčku",
  "planner.saveFailed": "Uložení se nezdařilo",

  "planner.shoppingList": "Nákupní seznam",
  "planner.copy": "Kopírovat",
  "planner.copied": "Zkopírováno ✓",
  "planner.copyLabel": "Kopírovat nákupní seznam",
  "planner.share": "Sdílet",
  "planner.shareLabel": "Sdílet nákupní seznam",

  "chips.remove": "Odebrat {chip}",

  // ─── Meal card ────────────────────────────────────────────────────────────
  "meal.freeze": "Zamknout",
  "meal.frozen": "Zamčeno",
  "meal.cook": "Uvařit",
  "meal.freezeTitle": "Zamknout toto jídlo",
  "meal.unfreezeTitle": "Odemknout toto jídlo",
  "meal.cooked": "Uvařeno",
  "meal.notCooked": "Neuvařeno",
  "meal.markCooked": "Označit jako uvařené",
  "meal.markNotCooked": "Označit jako neuvařené",
  "meal.cookFailed": "Nepodařilo se označit jako uvařené — zkontrolujte připojení a zkuste to znovu.",
  "meal.edit": "Upravit",
  "meal.editTitle": "Upravit tento recept",
  "meal.startCooking": "Začít vařit",
  "meal.startCookingTitle": "Vařit tento recept krok za krokem",
  "meal.leftovers": "Zbytky",
  "meal.leftoverStarTitle":
    "Zbytky nelze uložit do kuchařky — přidejte hvězdičku původnímu jídlu",
  // "z jídla „X“" — název jídla zůstává nesklonovaný v uvozovkách.
  "meal.leftoverFrom": "Využívá zbytky z jídla „{source}“ — není potřeba nic dokupovat.",
  "meal.leftoverFromUnknown": "Využívá zbytky z dřívějšího jídla — není potřeba nic dokupovat.",
  "meal.ingredients": "Suroviny:",
  "meal.leftoversShort": "↻ Zbytky",
  "meal.leftoversFromTitle": "Zbytky z jídla „{source}“",
  "meal.leftoversFromBadge": "↻ Zbytky z jídla „{source}“",

  // "z" + genitive for the date; a COLON, not a dash, introduces the dish —
  // Czech does not punctuate an apposition with an em-dash.
  "calendar.leftoverFromDateAndName": "Zbytky z {date}: {name}",
  "calendar.leftoverFromDate": "Zbytky z {date}",
  "calendar.leftoverFromName": "Zbytky: {name}",

  // ─── Cook Now form ────────────────────────────────────────────────────────
  "cookNow.intro":
    "Vygenerujte jeden recept na to, co právě vaříte. Označte ho jako uvařený a suroviny se odečtou z lednice.",
  "cookNow.mealType": "Typ jídla",
  "cookNow.people": "Počet osob",
  "cookNow.stockOnly": "Použít jen to, co je v lednici",
  "cookNow.tastes": "Chuťové preference (oddělené čárkou)",
  "cookNow.tastesPlaceholder": "např. pikantní, lehké, středomořské",
  "cookNow.avoid": "Suroviny, kterým se vyhnout",
  "cookNow.avoidPlaceholder": "Napište surovinu a stiskněte Enter",
  "cookNow.feature": "Suroviny, které použít",
  "cookNow.featurePlaceholder": "Napište surovinu a stiskněte Enter",
  "cookNow.note": "Poznámka (nepovinné)",
  "cookNow.notePlaceholder": "např. těstoviny, rychlovka, spotřebovat koriandr",
  "cookNow.generate": "Vytvořit recept",
  "cookNow.generating": "Vytvářím…",
  "cookNow.generateFailed": "Recept se nepodařilo vytvořit.",
  "cookNow.saveFailed": "Recept se nepodařilo uložit.",
  "cookNow.favoriteFailed": "Nepodařilo se uložit do kuchařky — zkontrolujte připojení a zkuste to znovu.",
  "cookNow.unfavoriteFailed": "Nepodařilo se odebrat z kuchařky — zkontrolujte připojení a zkuste to znovu.",
  "cookNow.saving": "Ukládám…",
  "cookNow.cookFailed": "Nepodařilo se uložit — zkontrolujte připojení a zkuste to znovu.",

  // ─── Cook mode ────────────────────────────────────────────────────────────
  "cook.done": "Dovařeno",
  "cook.closeTitle": "Zavřít režim vaření",
  "cook.ingredients": "Suroviny",
  "cook.hideIngredients": "Skrýt suroviny",
  "cook.startTimer": "Spustit časovač",
  "cook.cancel": "Zrušit",
  "cook.dismiss": "Skrýt",
  "cook.pause": "Pozastavit",
  "cook.resume": "Pokračovat",
  "cook.addAnotherTimer": "Přidat další:",
  "cook.firstTimerHint": "Klepněte na čas v kroku, nebo si nastavte vlastní:",
  "cook.minutesAbbrev": "min",
  "cook.customTimerLabel": "Vlastní čas v minutách",
  "cook.setTimer": "Nastavit časovač",
  "cook.stepOf": "Krok {n} z {total}",
  "cook.saving": "Ukládám…",
  "cook.timeUp": "⏰ Čas vypršel!",
  "cook.timerRemaining": "Časovač, zbývá {clock}",

  // ─── Meal editor ──────────────────────────────────────────────────────────
  "editor.header": "Úprava: {mealType} — typ jídla nelze změnit",
  "editor.nameLabel": "Název",
  "editor.name": "Název jídla",
  "editor.totalTime": "Celkový čas (v minutách, nepovinné)",
  "editor.totalTimeLabel": "Celkový čas v minutách",
  "editor.ingredients": "Suroviny",
  "editor.ingredient": "Surovina",
  "editor.needsPositiveAmount": "Každá surovina musí mít kladné množství v gramech.",
  "editor.saving": "Ukládám…",
  "editor.cancel": "Zrušit",
  "editor.save": "Uložit",
  "editor.grams": "g",
  "editor.spice": "koření",
  "editor.addIngredient": "+ Přidat surovinu",
  "editor.steps": "Postup",
  "editor.addStep": "+ Přidat krok",
  "editor.ingredientName": "Název suroviny {n}",
  "editor.ingredientGrams": "Množství suroviny {n} v gramech",
  "editor.ingredientSpice": "Surovina {n} je koření",
  "editor.removeIngredient": "Odebrat surovinu {n}",
  "editor.step": "Krok {n}",
  "editor.removeStep": "Odebrat krok {n}",

  // ─── Fridge ───────────────────────────────────────────────────────────────
  "fridge.title": "Lednice",
  "fridge.loginPrompt": "Pro zobrazení a úpravu lednice se prosím přihlaste.",
  "fridge.loading": "Načítání zásob...",
  "fridge.connecting": "Připojování k serveru…",
  "fridge.empty": "Lednice je prázdná.",
  "fridge.addIngredient": "Přidat surovinu",
  "fridge.remove": "Odebrat",
  "fridge.removeAll": "Odebrat vše",
  "fridge.removing": "Odebírám…",
  "fridge.sort": "Řadit:",
  "fridge.sortName": "Název",
  "fridge.sortQty": "Množství",
  "fridge.sortExpires": "Spotřebovat do",
  "fridge.colIngredient": "Surovina",
  "fridge.colQty": "Množství (g)",
  "fridge.colExpires": "Spotřebovat do",
  "fridge.colNeedToUse": "Spotřebovat brzy?",
  "fridge.colAction": "Akce",
  "fridge.yes": "Ano",
  "fridge.no": "Ne",
  "fridge.useSoon": "spotřebovat brzy",
  "fridge.expires": "do {date}",
  "fridge.earliest": "nejdříve {date}",
  "fridge.gramsTotal": "{grams} g celkem",
  "fridge.groupSummary": "({shown} / {total} balení)",
  "fridge.removeGroupTitle": "Odebrat všechna balení?",
  "fridge.removeItemTitle": "Odebrat surovinu?",
  "fridge.removeItemBody": "Odebrat z lednice „{name}“ ({grams} g)?",
  "fridge.saveFailed": "Uložení se nezdařilo: {message}",
  "fridge.unknownError": "Neznámá chyba",
  // "balení" is neuter and INVARIANT across number — 1 balení / 3 balení /
  // 5 balení — so these four forms coincide. That is a property of the noun,
  // not an untranslated copy-paste: "dávka" would inflect to dávky / dávek.
  "fridge.batchN": "Balení {n}",
  "fridge.batches_one": "({count} balení)",
  "fridge.batches_few": "({count} balení)",
  "fridge.batches_many": "({count} balení)",
  "fridge.batches_other": "({count} balení)",
  // The NUMERAL's agreement does change, even though the noun does not:
  // "všechno 1 balení" / "všechna 3 balení" / "všech 5 balení".
  "fridge.removeGroupBody_one":
    "Odebrat z lednice všechno {count} balení „{name}“?",
  "fridge.removeGroupBody_few":
    "Odebrat z lednice všechna {count} balení „{name}“?",
  "fridge.removeGroupBody_many":
    "Odebrat z lednice všechna {count} balení „{name}“?",
  "fridge.removeGroupBody_other":
    "Odebrat z lednice všech {count} balení „{name}“?",

  // ─── Fridge item modal ────────────────────────────────────────────────────
  "fridgeItem.addTitle": "Přidat surovinu",
  "fridgeItem.editTitle": "Upravit surovinu",
  "fridgeItem.nameRequired": "Název je povinný",
  "fridgeItem.quantityPositive": "Zadejte množství větší než 0",
  "fridgeItem.namePlaceholder": "např. kuřecí prsa",
  "fridgeItem.quantity": "Množství (g)",
  "fridgeItem.expiration": "Datum spotřeby",
  "fridgeItem.needToUse": "Spotřebovat brzy",
  "fridgeItem.ok": "OK",
  "fridgeItem.cancel": "Zrušit",
  "fridgeItem.name": "Název",

  // ─── Receipt scanner ──────────────────────────────────────────────────────
  "receipt.demoAlt": "Ukázková účtenka z nákupu",
  "receipt.scanDemo": "Naskenovat ukázkovou účtenku",
  "receipt.selectFile": "Vyberte obrázek účtenky nebo PDF",
  "receipt.openingCamera": "Otevírám fotoaparát…",
  "receipt.cameraPreview": "Náhled fotoaparátu",
  "receipt.waitingForCamera": "Čekání na fotoaparát…",
  "receipt.capture": "Vyfotit",
  "receipt.startingCamera": "Spouštím fotoaparát…",
  "receipt.reviewIntro": "Než položky přidáte do lednice, zkontrolujte je.",
  "receipt.noItems": "Na účtence nebyly nalezeny žádné potraviny.",
  "receipt.qty": "Množství (g)",
  "receipt.expires": "Spotřebovat do",
  "receipt.useSoon": "spotřebovat brzy",
  "receipt.remove": "Odebrat",
  "receipt.add": "Přidat do lednice",
  "receipt.adding": "Přidávám...",
  "receipt.added": "Položky byly přidány do lednice!",
  "receipt.typeIngredient": "surovina",
  "receipt.typeSnack": "snack",
  "receipt.resultNew": "{grams} g (nové)",
  "receipt.itemName": "Název položky {n}",
  "receipt.itemQty": "Množství položky {n}",
  "receipt.itemExpiration": "Datum spotřeby položky {n}",
  "receipt.itemNeedToUse": "Položku {n} spotřebovat brzy",
  "receipt.cameraDenied": "Přístup k fotoaparátu byl odepřen — můžete místo toho nahrát fotku.",
  "receipt.cameraNotFound": "Fotoaparát nebyl nalezen — můžete místo toho nahrát fotku.",
  "receipt.cameraFailed": "Fotoaparát se nepodařilo otevřít — můžete místo toho nahrát fotku.",
  "receipt.captureFailed": "Fotku se nepodařilo pořídit — zkuste ji nahrát.",
  "receipt.scanFailed": "Účtenku se nepodařilo naskenovat.",
  "receipt.mergeFailed": "Položky se nepodařilo sloučit.",
  "receipt.cancel": "Zrušit",
  "receipt.scanning": "Skenuji účtenku... Může to pár sekund trvat.",
  "receipt.colIngredient": "Surovina",
  "receipt.colType": "Typ",
  "receipt.colAddedQty": "Přidané množství (g)",
  "receipt.colResult": "Výsledek",
  "receipt.colNeedToUse": "Spotřebovat brzy?",
  "receipt.colAction": "Akce",
  "receipt.takePhoto": "📷 Vyfotit",
  "receipt.demo.milk": "Plnotučné mléko",
  "receipt.demo.eggs": "Vejce",
  "receipt.demo.bananas": "Banány",
  "receipt.demo.butter": "Máslo",
  "receipt.demo.tomatoes": "Rajčata Roma",
  "receipt.demo.bread": "Celozrnný chléb",

  // ─── Plan catalog ─────────────────────────────────────────────────────────
  "plans.title": "Moje jídelníčky",
  "planStatus.planned": "naplánováno",
  "planStatus.active": "probíhá",
  "planStatus.cooked": "uvařeno",
  "planStatus.finished": "dokončeno",
  "plans.summary": "{days} d / {meals} jídel denně / {people} os.",
  "plans.statusCount": "{status} ({cooked}/{total})",
  "plans.loading": "Načítání jídelníčků...",
  "plans.empty": "Zatím žádné jídelníčky. Vytvořte si níže první.",
  "plans.open": "Otevřít",
  "plans.opening": "Načítání...",
  "plans.delete": "Smazat",
  "plans.deleting": "Mažu…",
  "plans.deleteTitle": "Smazat tento jídelníček?",
  "plans.deleteBody":
    "Tímto trvale smažete jídelníček na {days} dní po {meals} jídlech z {date}. Akci nelze vrátit zpět.",
  "plans.openFailed": "Jídelníček se nepodařilo otevřít. Zkuste to prosím znovu.",
  "plans.deleteFailed": "Jídelníček se nepodařilo smazat.",
  "plans.dateFailed": "Datum jídelníčku se nepodařilo změnit. Zkuste to prosím znovu.",

  // ─── Plan calendar ────────────────────────────────────────────────────────
  "calendar.title": "Kalendář jídelníčků",
  "calendar.previousMonth": "Předchozí měsíc",
  "calendar.nextMonth": "Další měsíc",
  "calendar.today": "Dnes",
  "calendar.close": "Zavřít kalendář",
  "calendar.plan": "Jídelníček",
  "calendar.planNumbered": "Jídelníček č. {id}",
  "calendar.emptyMonth": "V měsíci {month} nejsou naplánované žádné jídelníčky. Přiřaďte jídelníčku datum začátku a objeví se tady.",
  "calendar.loading": "Načítání…",
  "calendar.scheduled": "Naplánované jídelníčky",
  "calendar.openPlan": "Otevřít →",
  "calendar.openingPlan": "Otevírám…",
  "calendar.rescheduleFailed": "Jídelníček se nepodařilo přeplánovat. Zkuste to prosím znovu.",

  // ─── Floating action buttons ──────────────────────────────────────────────
  "fab.openCookbook": "Otevřít kuchařku",
  "fab.openCalendar": "Otevřít kalendář",

  // ─── Cookbook ─────────────────────────────────────────────────────────────
  "cookbook.title": "Kuchařka",
  "cookbook.loading": "Načítání…",
  "cookbook.close": "Zavřít kuchařku",
  "cookbook.search": "Hledat recepty…",
  "cookbook.loadFailed": "Kuchařku se nepodařilo načíst.",
  "cookbook.noMatches": "Vašemu hledání neodpovídá žádný recept.",
  "cookbook.empty": "Vaše kuchařka je prázdná.",
  "cookbook.emptyHint": "Přidejte receptu hvězdičku v plánovači nebo v Uvařit hned a zůstane tady.",
  "cookbook.ingredients": "Suroviny",
  "cookbook.steps": "Postup",
  "cookbook.removeTitle": "Odebrat z kuchařky?",
  "confirm.cancel": "Zrušit",
  "confirm.delete": "Smazat",
  "confirm.deleting": "Mažu…",
  "cookbook.removeBody":
    "Odebrat „{name}“ z kuchařky? Později ho můžete přidat zpět z jídelníčku.",
  "cookbook.remove": "Odebrat",
  "cookbook.removing": "Odebírám…",
  "cookbook.removeFromCookbook": "Odebrat z kuchařky",
  "cookbook.removeNamed": "Odebrat {name} z kuchařky",
  "cookbook.removeLabel": "Odebrat z kuchařky",

  // ─── Planner heading ──────────────────────────────────────────────────────
  "planner.heading": "Plánovač jídel",

  // ─── Feedback modal ───────────────────────────────────────────────────────
  "feedback.title": "Poslat zpětnou vazbu",
  "feedback.intro": "Našli jste chybu nebo máte nápad? Napište nám — opravdu nám to pomáhá Mealbota zlepšovat.",
  "feedback.type": "Typ",
  "feedback.details": "Podrobnosti",
  "feedback.detailsPlaceholder":
    "Co se stalo, nebo co byste si přáli? Čím víc podrobností, tím lépe.",
  "feedback.cancel": "Zrušit",
  "feedback.send": "Odeslat",
  "feedback.sending": "Odesílám…",
  "feedback.tooShort": "Napište prosím trochu více podrobností.",
  "feedback.failed": "Zpětnou vazbu se nepodařilo odeslat.",
  "feedback.thanksTitle": "Díky — máme to. 🙏",
  "feedback.thanksBody": "Vaše hlášení míří k týmu. Čteme každé.",
  "feedback.done": "Hotovo",
  "feedbackKind.bug": "🐞 Něco nefunguje",
  "feedbackKind.feature": "💡 Nápad / návrh funkce",
  "feedbackKind.other": "💬 Něco jiného",

  // ─── Plurals ──────────────────────────────────────────────────────────────
  // 1 minuta · 2–4 minuty · 1,5 minuty · 0 a 5+ minut.
  "demo.banner":
    "Ukázkový režim: můžete generovat jídelníčky, vařit a hodnotit jídla. " +
    "Vaše relace i všechny změny se za 2 hodiny automaticky smažou.",

  "billing.paywall.title": "Je potřeba předplatné",
  // "10denní" is written as one word — Czech fuses a numeral with the
  // adjective it forms, where English hyphenates ("10-day").
  "billing.paywall.body":
    "Generování jídelníčků a receptů vyžaduje aktivní předplatné. Začněte " +
    "10denní zkušební verzí zdarma: než skončí, nic vám nenaúčtujeme a " +
    "zrušit ji můžete kdykoli.",
  "billing.paywall.planGroup": "Varianta předplatného",
  "billing.paywall.monthly": "Měsíčně",
  // Decimal comma, symbol after the number with a non-breaking space.
  "billing.paywall.monthlyPrice": "4,99 €",
  "billing.paywall.monthlySub": "za měsíc",
  "billing.paywall.annual": "Ročně",
  "billing.paywall.annualPrice": "2,99 €",
  "billing.paywall.annualSub": "za měsíc, účtováno 35,88 € ročně",
  // Czech puts a space before the percent sign.
  "billing.paywall.annualBadge": "Ušetříte 40 %",
  "billing.paywall.later": "Teď ne",
  "billing.paywall.start": "Vyzkoušet zdarma",
  "billing.paywall.starting": "Spouštím…",
  // "souhlasit s" + instrumental, the same government as `auth.acceptTerms`,
  // which is why both share the two link labels.
  "billing.paywall.legal": "Předplatným souhlasíte s {terms} a {privacy}.",

  // A comma, not a dash, joins the state to its date. "obnovuje se" (renews)
  // and "končí" (ends) govern the clause differently, so these could never
  // have been one message plus a shared suffix.
  "billing.banner.trial": "🎉 Zkušební období zdarma.",
  "billing.banner.trialRenews":
    "🎉 Zkušební období zdarma, {date} přejde na placené předplatné.",
  "billing.banner.trialCanceled": "🚫 Zkušební období zrušeno.",
  "billing.banner.trialCanceledEnds": "🚫 Zkušební období zrušeno, končí {date}.",
  "billing.banner.active": "✓ Předplatné aktivní.",
  "billing.banner.activeRenews": "✓ Předplatné aktivní, obnovuje se {date}.",
  "billing.banner.canceled": "🚫 Předplatné zrušeno.",
  "billing.banner.canceledEnds": "🚫 Předplatné zrušeno, končí {date}.",
  "billing.banner.pastDue":
    "⚠️ Platba neproběhla. Aktualizujte prosím kartu, ať o přístup nepřijdete.",
  "billing.banner.subscribe":
    "Chcete-li dál generovat jídelníčky a recepty, aktivujte si předplatné.",
  "billing.banner.manage": "Spravovat",
  "billing.banner.updatePayment": "Aktualizovat kartu",
  "billing.banner.subscribeAction": "Aktivovat",

  "time.minutes_one": "{count} minuta",
  "time.minutes_few": "{count} minuty",
  "time.minutes_many": "{count} minuty",
  "time.minutes_other": "{count} minut",
};
