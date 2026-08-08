"""User-facing ``detail`` copy for error responses, per locale.

Sibling of ``email_copy``: same ``$name`` placeholders, same "escaping stays at
the call site" rule. What differs is WHO reads the string, and that decides both
what belongs here and how coverage is enforced.

─── Why a Literal + a test, and not email_copy's TypedDict ─────────────────────
``email_copy`` gets its completeness from a total ``TypedDict``, and callers
index it with a written-out key (``COPY[locale]["verify_subject"]``) so mypy
checks the name directly. Here the key is a VALUE — it travels from a ``raise``
in a router to a handler that renders it — so it needs a type of its own, and
that type has to be a ``Literal``. With ``ErrorKey`` spelling out every name
once, a second copy of the same list inside a ``TypedDict`` would be pure
duplication for redundant safety. So the names live in ``ErrorKey``, and
``test_error_copy_covers_every_key`` asserts both locales match it exactly.

The safety is not weaker, just differently timed: mypy still rejects a typo'd
key at every ``raise`` site (it is not a member of the Literal), and the test
rejects a key that is declared but unwritten in either language.

─── What is NOT in here ────────────────────────────────────────────────────────
Only about half the backend's ``detail=`` strings are copy. The rest stay
English on purpose, because translating them buys a user nothing and costs a
translator forever:

* **500-guards** — ``"Invalid user state"`` (a ``user.id is None`` narrowing
  that cannot happen), ``"Plan insert failed"``, ``"Cook Now persistence
  failed"``. If a user ever sees one, the sentence is not their problem.
* **Client-contract violations** — ``"day_index 7 out of bounds"``,
  ``"day_layouts length (3) must match days query param (5)"``. Our own SPA
  never sends these; they are debugging output for whoever wrote the caller.
* **Machine-to-machine** — ``"Invalid webhook signature."`` goes to Stripe.

No test can enforce that split — "is this sentence for a human" is a judgement
call. What IS enforced is the other direction: ``test_no_orphan_error_keys``
fails on a key nothing raises, so a string reclassified OUT of user-facing copy
cannot rot here.

─── Admin is out of scope ──────────────────────────────────────────────────────
``app/api/admin.py`` is the largest single source of ``detail=`` strings (40)
and none of them are here. There is one admin and he reads English — the same
call already made for the operator alert emails.
"""

from __future__ import annotations

from typing import Final, Literal

from app.core.i18n import Locale

#: Every user-facing error sentence, named by CONDITION rather than by wording:
#: ``auth_bad_credentials`` survives a copy rewrite, ``auth_incorrect_email_or_
#: password`` does not. Grouped by the module that raises them.
ErrorKey = Literal[
    # ── Authentication (app/api/auth.py, app/api/deps.py) ──────────────────
    "auth_not_authenticated",
    "auth_bad_credentials",
    "auth_account_disabled",
    "auth_session_ended",
    "auth_refresh_missing",
    "auth_refresh_invalid",
    "auth_refresh_expired",
    "auth_refresh_reuse",
    "auth_user_gone",
    "auth_admin_required",
    "auth_current_password_wrong",
    "auth_new_password_same",
    "auth_email_unchanged",
    "auth_email_taken",
    "auth_demo_cannot_change_email",
    "auth_demo_cannot_delete_account",
    "auth_admin_cannot_self_delete",
    "auth_delete_billing_unavailable",
    "auth_reset_link_invalid",
    "auth_confirm_link_invalid",
    "auth_demo_disabled",
    # ── Account gates (app/api/deps.py) ────────────────────────────────────
    "gate_confirm_email",
    "gate_subscription_required",
    # ── Meal plans (app/api/plan.py) ───────────────────────────────────────
    "plan_not_found",
    "plan_data_unreadable",
    "plan_data_inconsistent",
    "plan_repeat_not_repeatable",
    "plan_generation_failed",
    "plan_regeneration_failed",
    "plan_regenerate_confirmed",
    "plan_not_confirmed",
    "plan_not_finished",
    "plan_finished",
    "plan_edit_finished",
    "plan_unconfirm_finished",
    "plan_uncook_first",
    "plan_meal_not_found",
    "plan_meal_not_found_confirmed",
    "plan_leftovers_not_cookbookable",
    "plan_leftovers_no_ingredients",
    "plan_reopen_shortage",  # $ingredient, $needed, $have
    # ── Recipes (app/api/recipe.py) ────────────────────────────────────────
    "recipe_generation_failed",
    "recipe_no_meals",
    # ── Accounts (app/api/user.py) ─────────────────────────────────────────
    "user_registration_closed",
    "user_invite_invalid",
    "user_country_unsupported",
    "user_language_length",  # $max
    "user_language_unsupported",
    # ── Billing (app/api/billing.py) ───────────────────────────────────────
    "billing_unavailable",
    "billing_demo_cannot_subscribe",
    "billing_annual_unavailable",
    "billing_checkout_failed",
    "billing_no_account",
    "billing_portal_failed",
    # ── Feedback (app/api/feedback.py) ─────────────────────────────────────
    "feedback_disabled",
    "feedback_demo_blocked",
    "feedback_duplicate",
    "feedback_too_many_open",
    "feedback_too_short",  # $min_len
    "feedback_no_letters",
    "feedback_low_variety",
    # ── Cookbook (app/api/cookbook.py) ─────────────────────────────────────
    "cookbook_recipe_not_found",
    # ── Fridge / pantry (app/api/fridge.py, app/api/pantry.py) ─────────────
    "fridge_too_many_items",  # $count_given, $maximum
    "pantry_too_many_staples",  # $count_given, $maximum
    "upload_missing_content_type",
    "upload_bad_file_type",  # $content_type
    "upload_file_too_large",  # $size, $maximum
    # ── Receipt scanning (app/services/receipt_scanner.py) ─────────────────
    "receipt_pdf_unreadable",
    "receipt_pdf_no_text",
    "receipt_pdf_timeout",
]

#: Keys whose sentence changes with a count. The copy holds
#: ``{base}_{category}`` for every category ``plural_category`` can return in
#: that locale, and each variant is a WHOLE sentence — see the note in
#: ``errors.py`` for why Czech leaves no other option.
PluralErrorKey = Literal[
    "plan_favorites_block_delete",  # $count
    "plan_favorites_block_unconfirm",  # $count
    # Plural because `max_pages` is a PARAMETER, not the module constant: the
    # cap is 10 in production, which would always land in Czech's 5+ form, but
    # `_extract_pdf_text` takes it as an argument and tests pass small values.
    # Pinning the form to whatever production happens to produce is how a
    # message comes to read "2 stran" the first time someone lowers the cap.
    "receipt_pdf_too_many_pages",  # $count, $maximum
]

_EN: Final[dict[str, str]] = {
    "auth_not_authenticated": "Not authenticated",
    "auth_bad_credentials": "Incorrect email or password",
    "auth_account_disabled": "This account has been disabled.",
    "auth_session_ended": "Session ended; please log in again",
    "auth_refresh_missing": "Missing refresh token",
    "auth_refresh_invalid": "Invalid refresh token",
    "auth_refresh_expired": "Refresh token expired",
    "auth_refresh_reuse": "Refresh token reuse detected",
    "auth_user_gone": "User no longer exists",
    "auth_admin_required": "Admin access required",
    "auth_current_password_wrong": "Current password is incorrect",
    "auth_new_password_same": (
        "New password must be different from the current password"
    ),
    "auth_email_unchanged": "That is already the email address on your account.",
    "auth_email_taken": "Email already registered",
    "auth_demo_cannot_change_email": (
        "Demo accounts cannot change their email address."
    ),
    "auth_demo_cannot_delete_account": (
        "Demo accounts delete themselves automatically — there is nothing to do."
    ),
    "auth_admin_cannot_self_delete": (
        "Admin accounts cannot be deleted from Settings. Remove the admin flag first."
    ),
    "auth_delete_billing_unavailable": (
        "We could not cancel your subscription with our payment provider, so we "
        "stopped before deleting anything — otherwise you would keep being "
        "charged for an account that no longer exists. Please try again shortly."
    ),
    "auth_reset_link_invalid": (
        "This reset link is invalid or has expired. Please request a new one."
    ),
    "auth_confirm_link_invalid": "This confirmation link is invalid or has expired.",
    "auth_demo_disabled": "Demo mode is not enabled",
    "gate_confirm_email": "Please confirm your email address to use this feature.",
    "gate_subscription_required": (
        "An active subscription is required for this feature."
    ),
    "plan_not_found": "Plan not found",
    "plan_data_unreadable": "Stored plan data could not be loaded.",
    "plan_data_inconsistent": "Stored plan data is inconsistent; edit aborted.",
    "plan_repeat_not_repeatable": (
        "Only meal plans can be repeated, not a single Cook Now recipe."
    ),
    "plan_generation_failed": "Meal plan generation failed. Please try again.",
    "plan_regeneration_failed": "Meal plan regeneration failed. Please try again.",
    "plan_regenerate_confirmed": "Cannot regenerate a confirmed plan",
    "plan_not_confirmed": "Plan is not confirmed.",
    "plan_not_finished": "Plan is not finished.",
    "plan_finished": "Plan is finished.",
    "plan_edit_finished": "Cannot edit a finished plan; reopen it first.",
    "plan_unconfirm_finished": (
        "Cannot un-confirm a finished plan; reopen it first."
    ),
    "plan_uncook_first": "Uncook all meals before un-confirming.",
    "plan_meal_not_found": "Meal entry not found",
    "plan_meal_not_found_confirmed": "Meal entry not found for confirmed plan.",
    "plan_leftovers_not_cookbookable": (
        "Leftovers can't be saved to the cookbook — save the original meal instead."
    ),
    "plan_leftovers_no_ingredients": (
        "This meal is leftovers from an earlier meal and carries no ingredients "
        "of its own — edit the source meal instead."
    ),
    "plan_reopen_shortage": (
        "Not enough $ingredient in fridge to reopen this plan: need ${needed}g, "
        "have ${have}g."
    ),
    "recipe_generation_failed": "Recipe generation failed. Please try again.",
    "recipe_no_meals": "LLM returned no meals — try again.",
    # English needs only one/other; Czech's third form is what these exist for.
    "plan_favorites_block_delete_one": (
        "This plan contains $count cookbook recipe. Un-favorite it before "
        "deleting the plan."
    ),
    "plan_favorites_block_delete_other": (
        "This plan contains $count cookbook recipes. Un-favorite them before "
        "deleting the plan."
    ),
    "plan_favorites_block_unconfirm_one": (
        "This plan contains $count cookbook recipe. Un-favorite it before "
        "un-confirming the plan."
    ),
    "plan_favorites_block_unconfirm_other": (
        "This plan contains $count cookbook recipes. Un-favorite them before "
        "un-confirming the plan."
    ),
    "user_registration_closed": (
        "Registration is closed. This is a private alpha — contact the admin "
        "for access."
    ),
    "user_invite_invalid": "This invite link is invalid or has expired.",
    "user_country_unsupported": "Unsupported country. Pick one from the list.",
    "user_language_length": "Invalid language: must be 1-$max characters",
    "user_language_unsupported": (
        "Unsupported language. Pick one of the supported options."
    ),
    "billing_unavailable": "Billing is not available.",
    "billing_demo_cannot_subscribe": "Demo accounts cannot subscribe.",
    "billing_annual_unavailable": "Annual billing is not available.",
    "billing_checkout_failed": "Could not start checkout.",
    "billing_no_account": "No billing account yet — subscribe first.",
    "billing_portal_failed": "Could not open the billing portal.",
    "feedback_disabled": "Feedback is not being accepted right now.",
    "feedback_demo_blocked": (
        "Demo accounts can't submit feedback. Please create an account."
    ),
    "feedback_duplicate": "You've already sent this — thanks, we have it.",
    "feedback_too_many_open": (
        "You have several open reports already. Please wait for those to be "
        "reviewed before sending more."
    ),
    "feedback_too_short": (
        "Please add a little more detail (at least $min_len characters)."
    ),
    "feedback_no_letters": "Please describe the issue in words.",
    "feedback_low_variety": (
        "That doesn't look like a real report — please describe the issue."
    ),
    "cookbook_recipe_not_found": "Recipe not found in cookbook",
    "fridge_too_many_items": "Too many items ($count_given); maximum is $maximum.",
    "pantry_too_many_staples": (
        "Too many staples ($count_given); maximum is $maximum."
    ),
    "upload_missing_content_type": (
        "Missing Content-Type header. Accepted: JPEG, PNG, PDF."
    ),
    "upload_bad_file_type": (
        "Invalid file type '$content_type'. Accepted: JPEG, PNG, PDF."
    ),
    "upload_file_too_large": (
        "File too large ($size bytes). Maximum is $maximum bytes."
    ),
    "receipt_pdf_unreadable": (
        "Could not read PDF. The file may be corrupted or password-protected."
    ),
    "receipt_pdf_no_text": (
        "This PDF has no extractable text (likely a scanned image). Please take "
        "a photo of the receipt and upload the image instead."
    ),
    "receipt_pdf_timeout": (
        "Receipt PDF took too long to process. Try a smaller/simpler file."
    ),
    "receipt_pdf_too_many_pages_one": "PDF has $count page — maximum is $maximum.",
    "receipt_pdf_too_many_pages_other": (
        "PDF has $count pages — maximum is $maximum."
    ),
}

_CS: Final[dict[str, str]] = {
    "auth_not_authenticated": "Nejste přihlášeni",
    # Deliberately does not say WHICH of the two is wrong — neither does the
    # English, and an error that distinguishes them turns the login form into an
    # account-enumeration oracle.
    "auth_bad_credentials": "Nesprávný e-mail nebo heslo",
    "auth_account_disabled": "Tento účet byl zablokován.",
    "auth_session_ended": "Relace skončila, přihlaste se prosím znovu",
    "auth_refresh_missing": "Chybí obnovovací token",
    "auth_refresh_invalid": "Neplatný obnovovací token",
    "auth_refresh_expired": "Platnost obnovovacího tokenu vypršela",
    "auth_refresh_reuse": "Zjištěno opakované použití obnovovacího tokenu",
    "auth_user_gone": "Uživatel už neexistuje",
    "auth_admin_required": "Vyžaduje se oprávnění správce",
    "auth_current_password_wrong": "Současné heslo není správné",
    "auth_new_password_same": "Nové heslo se musí lišit od současného",
    "auth_email_unchanged": "Tuto e-mailovou adresu už na účtu máte.",
    "auth_email_taken": "E-mail je už zaregistrovaný",
    "auth_demo_cannot_change_email": "U demo účtů nelze změnit e-mailovou adresu.",
    "auth_demo_cannot_delete_account": (
        "Demo účty se smažou samy — není co dělat."
    ),
    "auth_admin_cannot_self_delete": (
        "Účty správců nelze smazat z Nastavení. Nejdřív odeberte příznak správce."
    ),
    "auth_delete_billing_unavailable": (
        "Nepodařilo se nám u platební brány zrušit vaše předplatné, takže jsme "
        "nic nesmazali — jinak by vám dál účtovala platby za účet, který už "
        "neexistuje. Zkuste to prosím za chvíli znovu."
    ),
    "auth_reset_link_invalid": (
        "Tento odkaz pro obnovení hesla je neplatný nebo mu vypršela platnost. "
        "Vyžádejte si prosím nový."
    ),
    "auth_confirm_link_invalid": (
        "Tento potvrzovací odkaz je neplatný nebo mu vypršela platnost."
    ),
    "auth_demo_disabled": "Demo režim není zapnutý",
    "gate_confirm_email": (
        "Pro použití této funkce prosím potvrďte svou e-mailovou adresu."
    ),
    "gate_subscription_required": "Tato funkce vyžaduje aktivní předplatné.",
    "plan_not_found": "Jídelníček nenalezen",
    "plan_data_unreadable": "Uložená data jídelníčku se nepodařilo načíst.",
    "plan_data_inconsistent": (
        "Uložená data jídelníčku nejsou konzistentní, úprava byla zrušena."
    ),
    "plan_repeat_not_repeatable": (
        "Zopakovat lze jen jídelníček, ne jednotlivý recept z režimu Uvařit teď."
    ),
    "plan_generation_failed": (
        "Vytvoření jídelníčku se nezdařilo. Zkuste to prosím znovu."
    ),
    "plan_regeneration_failed": (
        "Přegenerování jídelníčku se nezdařilo. Zkuste to prosím znovu."
    ),
    "plan_regenerate_confirmed": "Potvrzený jídelníček nelze přegenerovat",
    "plan_not_confirmed": "Jídelníček není potvrzený.",
    "plan_not_finished": "Jídelníček není dokončený.",
    "plan_finished": "Jídelníček je dokončený.",
    "plan_edit_finished": (
        "Dokončený jídelníček nelze upravit, nejprve ho znovu otevřete."
    ),
    "plan_unconfirm_finished": (
        "U dokončeného jídelníčku nelze zrušit potvrzení, nejprve ho znovu "
        "otevřete."
    ),
    "plan_uncook_first": "Před zrušením potvrzení odznačte všechna uvařená jídla.",
    "plan_meal_not_found": "Jídlo nenalezeno",
    "plan_meal_not_found_confirmed": "Jídlo v potvrzeném jídelníčku nenalezeno.",
    "plan_leftovers_not_cookbookable": (
        "Zbytky nelze uložit do kuchařky — uložte místo nich původní jídlo."
    ),
    "plan_leftovers_no_ingredients": (
        "Toto jídlo jsou zbytky z dřívějšího jídla a nemá vlastní suroviny — "
        "upravte původní jídlo."
    ),
    # "$ingredient" arrives from the LLM in the user's recipe language, so it
    # is left in the nominative and the sentence is built around it rather than
    # inflecting it — there is no way to decline a word we do not know.
    "plan_reopen_shortage": (
        "V lednici není dost potřebné suroviny ($ingredient) na znovuotevření "
        "tohoto jídelníčku: potřeba ${needed} g, k dispozici ${have} g."
    ),
    "recipe_generation_failed": "Vytvoření receptu se nezdařilo. Zkuste to prosím znovu.",
    "recipe_no_meals": "Model nevrátil žádná jídla — zkuste to prosím znovu.",
    # The count governs the case of "recept" AND of the pronoun after it, so
    # these are three whole sentences, not one sentence with a swapped ending:
    #   1  → recept   / ho odeberte
    #   2-4→ recepty  / je odeberte
    #   5+ → receptů  / je odeberte
    "plan_favorites_block_delete_one": (
        "Tento jídelníček obsahuje $count recept v kuchařce. Před smazáním "
        "jídelníčku ho odeberte z oblíbených."
    ),
    "plan_favorites_block_delete_few": (
        "Tento jídelníček obsahuje $count recepty v kuchařce. Před smazáním "
        "jídelníčku je odeberte z oblíbených."
    ),
    "plan_favorites_block_delete_other": (
        "Tento jídelníček obsahuje $count receptů v kuchařce. Před smazáním "
        "jídelníčku je odeberte z oblíbených."
    ),
    "plan_favorites_block_unconfirm_one": (
        "Tento jídelníček obsahuje $count recept v kuchařce. Před zrušením "
        "potvrzení ho odeberte z oblíbených."
    ),
    "plan_favorites_block_unconfirm_few": (
        "Tento jídelníček obsahuje $count recepty v kuchařce. Před zrušením "
        "potvrzení je odeberte z oblíbených."
    ),
    "plan_favorites_block_unconfirm_other": (
        "Tento jídelníček obsahuje $count receptů v kuchařce. Před zrušením "
        "potvrzení je odeberte z oblíbených."
    ),
    "user_registration_closed": (
        "Registrace je uzavřená. Jde o soukromou alfa verzi — o přístup si "
        "napište správci."
    ),
    "user_invite_invalid": "Tato pozvánka je neplatná nebo jí vypršela platnost.",
    "user_country_unsupported": "Nepodporovaná země. Vyberte prosím ze seznamu.",
    "user_language_length": "Neplatný jazyk: musí mít 1 až $max znaků",
    "user_language_unsupported": (
        "Nepodporovaný jazyk. Vyberte prosím z nabízených možností."
    ),
    "billing_unavailable": "Platby nejsou k dispozici.",
    "billing_demo_cannot_subscribe": "Demo účty si nemohou pořídit předplatné.",
    "billing_annual_unavailable": "Roční předplatné není k dispozici.",
    "billing_checkout_failed": "Platbu se nepodařilo zahájit.",
    "billing_no_account": (
        "Zatím nemáte platební účet — nejprve si zřiďte předplatné."
    ),
    "billing_portal_failed": "Správu plateb se nepodařilo otevřít.",
    "feedback_disabled": "Zpětnou vazbu teď nepřijímáme.",
    "feedback_demo_blocked": (
        "Z demo účtu nelze posílat zpětnou vazbu. Založte si prosím účet."
    ),
    "feedback_duplicate": "Tohle už jste nám poslali — díky, máme to.",
    "feedback_too_many_open": (
        "Máte už několik otevřených hlášení. Počkejte prosím, než je "
        "zpracujeme, a teprve pak posílejte další."
    ),
    "feedback_too_short": (
        "Popište to prosím trochu podrobněji (alespoň $min_len znaků)."
    ),
    "feedback_no_letters": "Popište prosím problém slovy.",
    "feedback_low_variety": (
        "Tohle nevypadá jako skutečné hlášení — popište prosím problém."
    ),
    "cookbook_recipe_not_found": "Recept v kuchařce nenalezen",
    # "položek" / "surovin" / "bajtů" are genitive plurals governed by "mnoho"
    # and by "maximum je" — they do NOT vary with the number, so these need no
    # plural forms even though they interpolate a count. The PDF-pages message
    # below is the opposite case: there the number governs the noun directly.
    "fridge_too_many_items": (
        "Příliš mnoho položek ($count_given); maximum je $maximum."
    ),
    "pantry_too_many_staples": (
        "Příliš mnoho základních surovin ($count_given); maximum je $maximum."
    ),
    "upload_missing_content_type": (
        "Chybí hlavička Content-Type. Přijímáme: JPEG, PNG, PDF."
    ),
    "upload_bad_file_type": (
        "Neplatný typ souboru „$content_type“. Přijímáme: JPEG, PNG, PDF."
    ),
    "upload_file_too_large": (
        "Soubor je příliš velký ($size bajtů). Maximum je $maximum bajtů."
    ),
    "receipt_pdf_unreadable": (
        "PDF se nepodařilo přečíst. Soubor může být poškozený nebo chráněný "
        "heslem."
    ),
    "receipt_pdf_no_text": (
        "Toto PDF neobsahuje čitelný text (nejspíš jde o sken). Vyfoťte prosím "
        "účtenku a nahrajte fotku."
    ),
    "receipt_pdf_timeout": (
        "Zpracování PDF s účtenkou trvalo příliš dlouho. Zkuste menší nebo "
        "jednodušší soubor."
    ),
    # Here the count DOES govern the noun: 1 strana / 2-4 strany / 5+ stran.
    "receipt_pdf_too_many_pages_one": "PDF má $count stranu — maximum je $maximum.",
    "receipt_pdf_too_many_pages_few": "PDF má $count strany — maximum je $maximum.",
    "receipt_pdf_too_many_pages_other": "PDF má $count stran — maximum je $maximum.",
}

ERROR_COPY: Final[dict[Locale, dict[str, str]]] = {"en": _EN, "cs": _CS}
