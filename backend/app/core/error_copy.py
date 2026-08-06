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
]

#: Keys whose sentence changes with a count. The copy holds
#: ``{base}_{category}`` for every category ``plural_category`` can return in
#: that locale, and each variant is a WHOLE sentence — see the note in
#: ``errors.py`` for why Czech leaves no other option.
PluralErrorKey = Literal[
    "plan_favorites_block_delete",  # $count
    "plan_favorites_block_unconfirm",  # $count
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
}

ERROR_COPY: Final[dict[Locale, dict[str, str]]] = {"en": _EN, "cs": _CS}
