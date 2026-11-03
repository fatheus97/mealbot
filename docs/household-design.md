# Shared households: design

Status: designed 2026-11-02. Not built. Owner decisions taken that day are marked **(decided)**; the
rest carry a recommended default the owner approves or changes before the slice that needs it.

Goal: two or more accounts (first: the owner and his wife) share one plan list, fridge, pantry
staples and cookbook. Login, billing, consent and preferences stay per person.

How this was produced: four read-only mappers listed 212 single-owner assumptions in the code, three
independent designs (MVP-first, risk-first, long-term-first) were scored, the risk-first one won and
took the best parts of the other two, and an adversarial critic added 18 gaps. Every gap is placed
below; the list at the end says where.

## Invariants

| | |
|---|---|
| I1 | A request touches kitchen rows of the caller's current household only. Deliberate global reads stay as they are: the RAG global examples, admin, the sweeps. |
| I2 | Every fridge, staples or plan-state write of one household serializes on one advisory key. |
| I3 | Diet and allergy data about a person exists only under a current consent (theirs, or the entering member's for a one-off entry), and a plan whose covering consent is gone is treated as having lost it. |
| I4 | A member's deletion never deletes another member's kitchen. The last member's deletion deletes the household. |
| I5 | `is_admin` and `is_demo` are never inherited through a household. |

## Phase 1: what the owner and his wife need

Everything ships behind `HOUSEHOLDS_ENABLED` (default false). Until it flips, every account is a
household of one and behaves exactly as today.

### Data model

New:

- `household(id serial PK, created_at, fridge_version int NOT NULL DEFAULT 0, staples_version int NOT NULL DEFAULT 0)`.
- `"user".household_id int NOT NULL`, FK household.id (NO ACTION), indexed. Every account is always in
  exactly one household.
- `dietaryprofile(user_id PK FK user CASCADE, diet_types, allergens, avoid_ingredients jsonb, updated_at)`.
  One row per person, written only under that person's current consent **(decided: saved profiles,
  merged automatically)**.
- `planhealth(id PK, meal_plan_id FK mealplan CASCADE, entered_by_user_id FK user CASCADE, subject_user_id NULL FK user CASCADE, diet_types, allergens, avoid_ingredients jsonb)`.
  `entered_by_user_id` is whose consent covers the row. `subject_user_id` is the member the row
  describes, or NULL for a one-off entry typed for this plan (a guest, a child without an account).
  A row is written for every contributor even when all three lists are empty. Readers check the
  plan's `health_data_removed` first: a removed plan has no usable health data whatever its rows
  say (and its rows are deleted, see Migrations 6). Only on a plan that is not removed does a
  missing row mean a deleted member.
- `householdinvite(id, household_id FK CASCADE, invited_normalized_email, token_hash UNIQUE, created_by_user_id FK user CASCADE, expires_at)`.
  Redeem is `DELETE ... WHERE token_hash = :h AND invited_normalized_email = :email AND expires_at > now() RETURNING household_id`,
  so it is single-use by construction and a wrong account burns nothing. Revoke is a delete. No
  status columns.

Changed (the column is renamed in place, then only the rows of accounts whose household id differs
from their user id are rewritten, by a join; see Migrations 5):

| table | after |
|---|---|
| stockitem | `user_id` becomes `household_id`, FK household CASCADE. |
| pantrystaple | `household_id`, plus `UNIQUE (household_id, lower(name))`, declared in the model so `create_all` builds it. |
| mealplan | `household_id` CASCADE; new `created_by_user_id` NULL, FK user SET NULL, backfilled from the old owner; `UNIQUE (id, household_id)`; `ix_mealplan_catalog` follows the rename. `request_json` gains `health_contributors: [user_id, ...]`, every `entered_by_user_id` among the plan's rows, one-off entries included, and new writes carry the four health fields empty. |
| mealentry | `household_id`; composite FK `(meal_plan_id, household_id) -> mealplan(id, household_id) ON DELETE CASCADE ON UPDATE CASCADE` replaces the single plan FK, so an entry cannot sit in another household than its plan. The favourites index `(household_id, is_favorite)` is declared in `__table_args__` (today it exists only in a migration). |
| wasterecord | unchanged, per person. Added to the export (it is missing today). |

Favourites stay one bit per meal: unstarring removes the recipe for every member **(decided)**.

Per person and unchanged: sessions and tokens, flags, the Stripe mirror, trial flag, terms, consent
and its history, feedback, campaigns, telemetry, `LlmUsage`, `SaleRecord`, and every preference
column. In phase 1 whoever generates decides the preferences (language, layout, spices).

Removed: the `User.fridge_items`, `meal_plans` and `meal_entries` relationships, so every stale
kitchen `user_id` read becomes a mypy error.

### Migrations

1. **`household_01`** backfills `household.id = user.id` for every user, then `setval`. The lock key
   `(KTCH, id)` therefore keeps its value for every account that exists at migration time, so old and new code
   serialize for those accounts during the deploy window. An account the old stack creates inside
   the window gets its household id from the sequence instead; for those seconds its old-code key can
   contend with another household's, and old and new code do not serialize for it. Accepted.
   `household_01` (#532) also starts the household sequence at `user_id_seq`'s next value, so new
   accounts usually get a household id equal to their user id too. Usually, not always: two
   concurrent inserts can swap their pair, and an insert that names its household (a join) uses a
   user id without a household one. Nothing may assume `household_id = user_id`.
2. A **BEFORE INSERT trigger** on `"user"` creates a household when `household_id` is NULL. It also
   covers the old stack during the deploy window (which still inserts users without the column), Core
   inserts, `scripts/create_user.py` and hand-run SQL. It is also attached as a metadata `DDL`
   listener so pytest's `create_all` schema has it.
3. An **AFTER DELETE trigger** on `"user"` deletes the household when no user references it. It
   first runs `SELECT 1 FROM household WHERE id = OLD.household_id FOR UPDATE`, so two last members
   deleting at once (or one deleting while the other leaves) cannot both miss the last-member case.
   Leave takes the same row lock. These are the repo's first triggers, justified by three bare
   `DELETE FROM "user"` paths that run no app code.
4. **Test sequence offset:** conftest restarts `household_id_seq` at 1000001 after `create_all`.
   Otherwise user ids and household ids coincide in tests (as in prod for most accounts), and a
   swapped-id bug passes. This offset is load-bearing.
5. **`household_02`** renames the kitchen columns and their indexes (`ALTER INDEX ... RENAME`, including
   the migration-only `ix_mealentry_user_id_is_favorite`), so prod and the `create_all` schema match.
   The test-db dry run compares the prod index list with the metadata. After the renames the
   columns still hold user ids, so before the FKs go on every kitchen table moves its rows to the
   account's household in one statement:
   `UPDATE t SET household_id = u.household_id FROM "user" u WHERE u.id = t.household_id AND u.household_id <> u.id`.
   For accounts that existed at `household_01` the two ids are equal and nothing is rewritten; the
   dry run seeds an account whose ids differ and checks its rows land in its own household.
   The renames, the remap and the FKs are one migration transaction, so no row is written in
   between. `household_02` first refuses to run if any household has more than one member: none
   can before PR 5 ships joins, and two members' rows landing in one household could collide on
   the new staples unique key. Before adding the FKs it checks that every kitchen row's
   `household_id` exists in `household` and fails with the table and the count if not, which
   reads better in a deploy log than an FK violation. Every unique key that includes
   `household_id` (the staples key, `uq_mealplan_id_household_id`) is created after the remap,
   so a swapped pair (A with ids 5/7, B with 7/5) cannot collide midway through the UPDATE; the
   dry run seeds such a pair holding the same staple name.
6. **`household_03` copies, it does not move.** It writes a creator `planhealth` row for every plan
   that is not already removed and has a creator (attributed to `created_by_user_id`, exact while
   every household has one member), holding that plan's health fields, and **leaves the blob as it
   is**. The reason is the deploy window, read the
   other way round: the old container keeps serving until the swap, and it reads only the blob. A
   blob emptied by the migration would make it fail OPEN, silently: a regenerate sent to the model
   without the allergens, an edit with no warning, a withdrawal that clears nothing and leaves rows
   behind. Copying keeps the old code correct. After the swap the new code reads the rows, writes
   rows for new plans with the four blob fields empty, and a withdrawal clears both. The window
   has two cases, and both fail closed:
   - **the old stack writes a plan:** a carrying blob and no row. Readers treat that blob as the
     creator's row;
   - **the old stack withdraws:** it empties the blob and sets `health_data_removed`, but the copied
     row survives. `health_data_removed` is a key of the stored request in `request_json` (the
     `MealPlanRequest` field), not a column, and stays there in 3a; it is the one flag both stacks
     read and write. It takes precedence over every row and the blob: a removed plan is never generated from, screened with or exported as health data,
     whatever rows it still has. And because consent was withdrawn, those rows must also go: the
     new code runs one idempotent statement at startup that deletes the `planhealth` rows of every
     plan whose blob says `health_data_removed`, so they are gone seconds after the swap. It scans
     every plan's `request_json` (no index covers the key), which is fine at today's scale and
     temporary: the contract migration (`household_04`, 3b-1) runs the same delete once, before
     emptying the blobs, and takes the startup statement out. The old code never rewrites the health fields of a blob otherwise (an edit touches
     `response_json` only), so withdrawal is the only blob change a row can miss.

   The contract step that empties the old blobs ships as `household_04` in 3b-1, when the code
   serving during its deploy window is 3a's, which reads the rows first.
   Details the map of the code settled:
   - every plan that is not already removed gets its creator row, even with three empty lists; the
     row's existence is also what makes the copy idempotent. A plan whose blob already says
     `health_data_removed` (withdrawn before the migration) gets no row: it has nothing to copy,
     and a row would only be deleted again at the first startup;
   - `diet_types` is copied reconciled (a legacy blob with only `diet_type` becomes `[diet_type]`),
     `balanced` included, because generation reads it; order is kept, since it drives the prompt
     lines and the screen;
   - `subject_user_id` is NULL for copied rows: a blob was typed per generation and may describe a
     child or partner, so it is not evidence about the creator's own health. 3b treats such a row
     like any one-off entry: its consent is `entered_by_user_id`'s, it is merged as typed, and
     when that member's consent is not current a regenerate answers 403 naming that member (the
     creator), as for the stored request today;
   - a plan with `created_by_user_id` NULL cannot be attributed: it gets no row and its blob is
     emptied with `health_data_removed` set. This is the one deliberate exception to "copy, don't
     move", and it fails closed. Zero such plans are expected, since the last member's delete
     cascades the household's plans; the dry run seeds one;
   - three blob shapes live in `request_json` (a plan's `MealPlanRequest`, Cook Now's
     `CookRecipeRequest`, the cookbook's `FavoriteRecipeRequest` with no health fields), and the
     frozen predicate is `health_data_consent_01`'s `_carries` (the earlier draft of this doc called
     it `_blob_carries`).
7. Descriptive revision ids, the first with `down_revision = "health_data_consent_01"`. Re-check for a
   single head right before each merge. CI does not run migrations: every one gets an
   upgrade/downgrade/upgrade dry run on `test-db` with seeded rows, never the shared dev DB.
   `downgrade()` refuses when any household has two or more members. Downgrading `household_03`
   writes each plan's creator row back into its blob (the inverse of the lift) and drops every other
   contributor's row. A plan whose creator was deleted (`created_by_user_id` NULL) has no creator
   row to restore, so its health data is dropped too; the dry run seeds that case. Downgrading
   `household_05` drops `dietaryprofile`: an emergency rollback loses saved profiles, the one
   downgrade that destroys Art. 9 data rather than moving it, and it logs how many it dropped.
8. **Deploy window (default: accept).** Between migrate and swap the old container's kitchen
   endpoints fail for seconds. The alternative is expand/contract, three extra PRs.

### Authorization

- `Kitchen(user_id, household_id: HouseholdId)` comes only from `Kitchen.of(user)`, reading the row
  `get_current_user` already loaded; never from the client. An AST test allows `HouseholdId(` only
  there and in test helpers.
- `lock_kitchen(session, kitchen)` takes the advisory lock on the household id, re-reads the user's
  `household_id` and returns 409 `household_changed` on a mismatch. Join and leave take it too, in
  ascending id order for two households. All 17 current call sites move to it.
- `replace_fridge_items` and `replace_staples` both refuse to run without the lock (staples has no
  lock today), and `PUT /staples` takes it.
- `load_plan(session, kitchen, id)` and `load_entry(...)` return 404 for another household. They
  replace the 15 `.user_id != current_user.id` checks and become the only `session.get(MealPlan|MealEntry)`
  callers in the API.
- **Route matrix test:** every route with a `plan_id` or `meal_entry_id` returns 404 for household B
  on household A's ids; every list endpoint returns none of A's rows; a path parameter the test does
  not classify fails it.
- Drafts are per member: `clear_unconfirmed_plans(household_id, created_by_user_id)`, plus a sweep of
  drafts whose creator is NULL (a deleted member's).
- RAG "own" examples become the household's. The admin funnel reads confirmed and cooked through the
  creator.
- Deferred hardening: an ORM scope criterion or row-level security. RLS first needs a non-superuser
  app role; the app connects as the superuser today.

### Concurrency for two phones

The lock serializes transactions, but the fridge and staples are whole-list PUTs, so a stale phone
can still overwrite the partner's edit.

- `replace_fridge_items` and `replace_staples` bump `household.fridge_version` / `staples_version`.
- The token is household-scoped, `<household_id>:<version>`, sent as `X-Fridge-Version` /
  `X-Staples-Version` on GET **and** on PUT and merge responses. A PUT with a token for another
  household, or a stale one, gets 409 `fridge_changed` / `staples_changed` and writes nothing. A PUT
  without a token is accepted, so an old bundle keeps working.
- The client stores the token beside the cached list and sends each PUT only after the previous one
  returned, carrying the token it got back. Two quick edits on one phone never 409 each other.
- Shared queries (fridge, staples, plan list, calendar, cookbook) get `refetchOnWindowFocus: true`
  and `staleTime: 30s`.
- Benign writers stay unlocked: reschedule, cookbook remove, star, record waste.

### Diets, allergies and consent

- Each person's profile is saved under their own current consent. The consent text gets a new
  version (backend `HEALTH_CONSENT_VERSION` and `frontend/src/legal.ts` together) saying household
  members see the profile and plans are generated with it. Everyone is asked again, **in PR 7, right
  before the flag flips** (decision 12): `has_health_consent` is an equality check, so a bump makes
  every request with health data 403 until the user consents again, and doing that for a feature
  nobody can use yet would be noise. 3a stays within today's text (the same data, typed by the
  user, for the same purpose); saved profiles and eaters (3b) exist only behind the flag until then.
  The flag must not be able to go on before the new text exists: 3b-2a adds
  `HOUSEHOLD_CONSENT_VERSION: Final[str | None] = None` to `backend/app/core/legal.py`, the first
  consent version whose text covers households. `HOUSEHOLDS_ENABLED` has no effect unless it is set
  and `HEALTH_CONSENT_VERSION >= HOUSEHOLD_CONSENT_VERSION` (compared as dates); set before that,
  the backend logs an ERROR at startup. Not a refusal to start, as first written: in prod that is a
  crash-looping backend, the whole site down over one dark feature. Only PR 7 sets it, together
  with the bump.
- **Generation** picks who is eating; the server defaults to all members when the field is missing in
  a household of two or more (an old bundle must not silently skip the partner's allergies). A
  household of one with no selection behaves byte-identically to today. Each eater needs current
  consent, otherwise 403 naming the member, and the UI offers to untick them. One-off entries need
  the generating member's consent. Cook Now follows the same rules.
- **Merge** is a deduplicated union, shown to the user before Generate, with 422 on overflow and no
  silent truncation (`sanitize_input` truncates today).
- Settled in 3b-2b (owner's check-in Q6-Q9, 2026-11-03, defaults he can still overrule): only an
  eater whose saved profile carries health data needs consent; only contributors whose data
  carried something count as lost when deleted; someone alone in their household uses only the
  typed fields, their saved profile does not apply; the 403 names the member by email (accounts
  have no name).
- **After the LLM**, under the household lock, keep only contributors who still exist, are still
  members and still consent, then write `planhealth` and `health_contributors`.
- **Lost data is treated as lost.** A plan whose `health_contributors` lists someone with no
  `planhealth` row left (their account was deleted, which cascades with no app code) reads as
  `health_data_removed`: regenerate returns 409, edits warn, repeat refuses. One-off rows are
  entered by a member and cascade with that member, so a child's allergies cannot vanish silently;
  the plan reads as removed instead.
- **Readers fail closed during the deploy window:** a plan whose blob still carries health fields and
  has no `planhealth` rows is read as the creator's row.
- **Withdrawal while staying:** delete the person's profile and every `planhealth` row they entered
  or that describes them in the household, and flag those plans `health_data_removed`.
- Editing screens against the plan's `planhealth` rows whoever edits (since 3b-1). Repeat refuses a
  removed plan (3b-1), and re-screens the copied meals against the current eaters and fails closed
  (3b-2).
- Known limit: a `baby_food` member makes every meal infant food. Shown in the UI; per-slot eaters
  are out of scope.

### Join and leave

- **Invites:** any member of a household below the cap mints one: email-bound, single-use, 48 hours,
  at most 3 live. The code is a `create_refresh_token()` plaintext (`secrets.token_urlsafe(32)`, 256
  bits), stored only as its hash, because it unlocks a kitchen holding other people's allergy data:
  never a short human-friendly code. The redeem endpoint is rate-limited per user, like the consent
  endpoints. Both the minter and the redeemer must be verified, non-demo accounts. Redeeming
  never creates an account; a partner without one gets an admin invite first while registration is
  closed.
- **Billing rule for phase 1 (decided: each member on their own):** joining requires the joiner and
  every member to be entitled independently (subscribed, comped or grandfathered). No billing code
  changes. AI spend caps stay per person.
- **Join** is allowed only from a household of one. Redeem runs in this order: look up the
  invite's `household_id` by `token_hash` (a plain SELECT; a miss is 404); take both households'
  kitchen locks in ascending id; run the email-bound `DELETE ... RETURNING`; check the cap. The
  DELETE and the cap check both come after the lock, so two redeems at 5 of 6 cannot both pass. Zero
  rows returned after the lock is the same 404 as an email mismatch or an unknown code, so the
  endpoint cannot be used to learn which emails hold invites. All of it is one transaction, so a
  cap failure (409) rolls back the DELETE too and the invite stays usable. The cap's 409 is distinct
  from the 404 of every other miss on purpose: by then the caller has proved a valid code and the
  matching email, so it reveals nothing new.
- **Bringing the kitchen (decided):** plans and fridge rows move by `UPDATE ... SET household_id` (entries and `planhealth` follow
  through the FKs; fridge rows move as batches, so an item both partners hold becomes two batches of
  it, which the fridge already supports), staples merge with `ON CONFLICT DO NOTHING`, the joiner's drafts are deleted, the
  versions bump, the old household is deleted.
- **Leave:** under the lock, the leaver moves to a new household of one with nothing but their
  profile and export **(default)**. Their drafts and every `planhealth` row they entered or that
  describes them are deleted (plans flagged), and the invites they minted are revoked.
- Admin deactivation moves the member to a household of one, so a deactivated account cannot hold a
  cap slot.
- No removal of another member and no roles in v1. After a join or leave the client reloads the
  page, which drops every cache, so query keys can stay user-keyed.

### GDPR

- **Export:** personal data unchanged, plus the dietary profile and `WasteRecord`. Fridge, staples,
  plans and meals are labelled as shared. `planhealth` only where the requester entered it or is its
  subject (Art. 15(4)). `_EXCLUDED` names "other members' health entries" and "households you left".
- **Delete dialog:** a household of one keeps today's text. A shared household gets a branch: the
  shared kitchen stays with the other members, your health data is removed. en and cs.
- **Legal:** the privacy policy (en, and the hand-edited cs page, never regenerated) says members see
  the shared kitchen and each other's dietary profiles. `MATERIAL_CHANGE_VERSION`, `CHANGE_SUMMARY`
  (en, cs) and `TERMS_VERSION` move together. All before the flag flips.

### Phase 1 slices

Each is one PR and a no-op for solo accounts until the flag flips. PR 2 and PR 3 get the pre-push
adversarial review.

| PR | content | key tests |
|---|---|---|
| 0 | `fix(export)`: `WasteRecord` in the export. | waste exported; a meta-test that every table with a user FK is exported or named in `_EXCLUDED`. |
| 1 | `household_01`: table, backfill, `user.household_id`, both triggers (migration + DDL listener), sequence offset. | every creation path gets a household; last-member delete removes it, one of two keeps it; two last members deleting at once leave no orphan (two-connection harness); demo sweep leaves none; downgrade refuses on 2+. |
| 2 | `household_02` rekey: renames and index renames, `created_by_user_id`, composite FK, staples unique + lock, `Kitchen`, `lock_kitchen(kitchen)`, `load_plan`/`load_entry`, RAG, per-member drafts. Withdraw and export key on the creator until PR 3. | route matrix; two-member races in the `test_kitchen_lock.py` harness, with a per-user-key negative control that goes red; membership change while waiting returns 409; composite FK rejects a cross-household entry; moving a plan to another household carries its entries (ON UPDATE CASCADE is load-bearing); A's Generate keeps B's draft; index list matches metadata. |
| 3s | Safety net before any of 3: API tests that the stored health data reaches the model on generate, regenerate and Cook Now, survives repeat and a Cook Now save, and is in the export. A 3a that reads the emptied blob must go red. | each test negative-controlled against the production path it pins; the PR records the suite's test count, which 3a reconciles against; it also pins that editing, confirming, cooking, starring and regenerating a plan leave its `request_json` unchanged, the claim that makes withdrawal the only blob rewrite a copied row can miss. |
| 3a | `household_03`: `planhealth` and `health_contributors`, the copy (Migrations 6), every reader and writer switched to rows with the blob as fallback (generate, Cook Now, regenerate, repeat, edit screen, withdraw, export, telemetry), `health_data_removed` taking precedence, and the startup delete of a removed plan's rows. Byte-identical for a household of one, including two behaviours the design later changes (below). No consent change. | 3s stays green unchanged; a new plan's blob holds the four HEALTH_FIELDS empty (legacy diet_type included); copy is idempotent and attributes every blob to its creator; a carrying blob with no row reads as the creator's row; a removed plan with a row left over is never read as health data, and the startup delete removes that row; withdrawal clears rows and blob; dry run up/down/up with all three blob shapes, a NULL creator, and "row copied, then the old stack withdraws". |
| 3b-1 | `household_04`, the contract step: runs the removed-plan delete once and takes the startup statement out, gives a plan the pre-3a stack wrote in 3a's window its creator row, empties the four fields of every blob that has rows and names its contributors. Flips the two kept behaviours, for everyone: the edit screen warns from the plan's rows whoever edits (before, the editor's own consent decided), and repeat refuses a plan whose health data was removed, 409 (before, it copied it, still marked). Split from 3b so the one step that rewrites stored health data ships and deploys on its own. | dry run: the app reads every plan identically before and after, removed rows gone, idempotent, downgrade a no-op, down to `household_02` and back; editor without current consent still gets the allergen warning; repeat of a removed or lost-contributor plan 409s and copies nothing. |
| 3b-2a | `household_05` (`dietaryprofile`, empty), the profile API (GET; PUT behind `HOUSEHOLDS_ENABLED`, under the kitchen lock with the consent read as committed; DELETE), withdrawal and DELETE removing the profile whatever the flag says, the profile in the export, `HOUSEHOLDS_ENABLED` and the `HOUSEHOLD_CONSENT_VERSION` gate. Nothing reads a profile yet. Split from 3b-2 to keep the additive part apart from the generation changes. | flag off or no consent text: PUT 404; carrying data without a current consent, read fresh: 403; "balanced" alone needs none; withdrawal and DELETE remove it with the flag off again; export shows it; the startup log; user delete cascades; migration dry run with the schema equal to the model. |
| 3b-2b | Eaters and the merge for Generate and Regenerate, behind `HOUSEHOLDS_ENABLED`: `eaters` on the plan request (excluded from the stored request, the prompt and telemetry), every member by default, each eater's saved profile as their own row after the typed one, the union for the model, per-eater consent (403 naming them by email), one 422 for any non-member id, the avoid union refused when too long, `merged_request_json` deduplicating across rows, regenerate needing each contributor's consent, and the after-the-LLM re-check of every contributor (exists, still a member, still consents; their user rows FOR KEY SHARE against an unlocked account delete) that saves the plan marked when one fails. `request_to_store` now refuses to run without the kitchen lock. | a household of one, with or without a saved profile, generates byte-identically (model request, stored request, rows, telemetry); default and chosen eaters; non-member 422 names nobody; missing consent names the member; no-data eater needs no consent; the union cap; regenerate's union and consent; withdraw and leave mid-generation save the plan marked; a member with nothing saved is not a contributor. |
| 3b-2c-1 | Cook Now eaters: `/recipe/generate` resolves them like plan Generate (merged union to the model, the same 403/422 before the model call); `/recipe/cook` re-reads every eater's profile at save time, under the kitchen lock, and refuses nothing (the meal is cooked, the fridge must be updated): an eater who left, withdrew or whose consent lapsed since is left out, the others kept (check-in Q10). `SingleRecipeRequest.eaters` (`exclude`). `/recipe/favorite` stays without health data. | a household of one generates and cooks byte-identically, with and without a saved profile; default and chosen eaters on both steps; `eaters` stored nowhere; the three refusals before the model; a profile changed since `/generate` is what `/cook` stores; left, withdrew and lapsed each leave that eater out and keep the rest; the lock-first guard runs with the flag on, so a read before the lock goes red. |
| 3b-2c-2 | Repeat in a shared household: `PlanRepeatRequest.eaters`; the copy keeps the source's one-off rows under their author's consent (403 naming them, not the repeater's consent), takes every current eater's profile (refused like Generate, union cap included), and re-screens the copied meals against that union with the plan's language: an allergen, a baby-food rule or an ingredient the screen cannot read refuses the copy, 409 `plan_repeat_unsafe_for_eaters` naming the meal (check-in Q11). A leftover still carrying the server's step is not re-screened (its source meal is); one whose step was edited is. Sulphites have no screen (prompt-only at generation), so an eater's sulphites the source was not made to avoid refuse the copy, 409 `plan_repeat_unscreened_for_eaters`. On a non-English plan a meal with steps and no ingredients counts as unreadable. The planner shows the server's sentence for a repeat 422 too. Other diets and avoid lists have no deterministic screen; the copy stores them for regenerate. A household of one repeats as before. | a household of one repeats byte-identically with a saved profile and an edited-in allergen; the copy's rows are the one-off rows plus every current eater's profile, a newcomer included; `eaters` picks; an allergen, a baby-food rule and an unreadable ingredient each 409 and copy nothing; a leftover with the server's step naming "butter" passes, an edited one is screened; new sulphites refuse, sulphites the source avoided pass; a Czech meal of steps alone refuses; non-member 422, eater without consent 403, union cap 422; a one-off row's lapsed author 403, and the repeater needs no consent for another's row; repeat joins the lock-first guard. |
| 3b-2c-3 | The edit screen on a plan whose health data is gone (withdrawn, or lost with a contributor's account): in a shared household, or by someone now alone in theirs when the plan's stored `health_contributors` name anyone else, `MealEditResponse.health_data_removed` is true and the planner shows "This edit was not checked for allergies" instead of silence (check-in Q12). `request_to_store` keeps naming the contributors when it saves a plan marked, so a partner who left during generation still counts. The notice resets with Generate and Regenerate. A household of one after its own withdrawal, and the flag off, are unchanged. | a plan with its data warns as before and is not flagged; after a withdrawal and after a contributor's account went, the edit is flagged, also in a two-person household left alone (deleted account, partner left during generation); a household of one and a shared household with the flag off stay silent; the planner shows the notice only when the server flags it (and the component test). |
| 4a | Versions, the API: `household_06` (`fridge_version`, `staples_version`, int NOT NULL DEFAULT 0), counted in `replace_fridge_items` / `replace_staples` (every writer: PUT, merge, plan confirm/unconfirm/finish/delete/reopen, Cook Now) by one conditional UPDATE right after the lock guard and before any write; `X-Fridge-Version` / `X-Staples-Version` on GET (version read before the list), PUT and merge; a PUT's token compared by equality, a stale, foreign or unparsable one is 409 `fridge_changed` / `staples_changed` (en + cs); no token accepted (old bundles). The response token is the write's own count, never a post-commit read. | stale, partner-made, foreign and unparsable tokens 409 and write nothing; two edits each with the token before succeed; no token accepted and counted; merge never refused; confirm and Cook Now count; fridge and staples count apart; staples join the lock-first guard; dry run on test-db (a held fridge write makes the upgrade give up in 6 s with nothing changed, existing/old-style/trigger households get 0/0, household columns equal to create_all, downgrade and up again). |
| 4b | Versions, the client: token kept in the query data beside the list, each PUT queued behind the previous (mutation scope, across components) and sent with the token the one before returned, a queued PUT's response moving only the token; in-flight reads cancelled before a PUT, and no focus or mount refetch of a shelf while a save is pending; a 409 shows the server's sentence and reloads, and saves queued behind it are refused unsent; shared queries refetch on focus (staleTime 30 s); Fridge dialogs hold rows by identity kept across a reload by server id (an item removed elsewhere says so); PantryStaples keeps unsaved chips through a reload and saves with the version they were made from. CORS allows and exposes both headers (for a `VITE_API_BASE` bundle). | token cached beside the list and sent; two quick saves, the second with the first's token and the cache moving only the token meanwhile; a 409 reloads and refuses the queued save without a request, a save after the reload carries the new token; an in-flight GET cannot roll a save back; focus refetch skipped while saving, then done; no token, no header; staples send the caller's token; Fridge edit and remove dialogs hit their own item after a reload that shifts indices, a removed item says so and saves nothing, a 409 shows the sentence and the reloaded list; staples keep unsaved chips through a reload, the save is refused and the partner's list shows; the planner's expired-items alert shows the sentence; CORS preflight and expose for both headers. 11 negative controls; Vitest in its own `docker run`. |
| 5 | Join, leave, invites API behind the flag. | concurrent redeem: exactly one wins; two redeems at the cap: one wins; a redeem rejected at the cap leaves the invite in place; demo minter and redeemer 403; email mismatch 404; the cap; non-entitled member refused; "bring" moves everything; leave revokes the leaver's invites and flags plans. |
| 6 | UI: Settings "Household" section, profile editor, eater picker with the merged summary, delete-dialog branch, reload after join/leave, InfoHints. en + cs, sentence-level keys. | Vitest, `tsc -b`, key-usage and parity tests, two-theme browser check. |
| 7 | Legal: privacy en + cs, material change, owner's Czech read, the health consent version bump (decision 12). Gate before the flag flips: decision 11 (global RAG examples) is settled and, if it changes code, shipped. Then the owner flips the flag. | legal-version CI job. |

## Phase 2: before strangers use households

Needed before households are offered to paying users who do not each have their own access.

- **One subscription per household.** `lock_billing` keyed on the household when starting Checkout;
  Checkout returns 409 `billing_household_covered`. A Checkout session stays open 24 hours, so the
  webhook also cancels and refunds a second subscription that starts on a covered household, and the
  join guard rejects a joiner with an open session. Entitlement counts active members only.
- **Pooled AI spend cap:** stamp `LlmUsage.household_id` at write time with an index on
  `(household_id, created_at)` and sum by household. Summing current members' rows instead would let
  a household reset its budget by deleting a throwaway member, and would charge a joiner's pre-join
  spend to the household.
- **Feedback credit** goes to the paying member's Stripe customer, with lock, cap and floor keyed on
  the payer, and only to a customer with a live subscription.
- **Admin funnel:** members covered by someone else's subscription leave the "paid" denominator.
- Trial: one per household. Payer deletion: warn, never block.

## Decisions with defaults (owner approves or changes)

1. Deploy window: accept seconds of kitchen errors per migration (the alternative is expand/contract).
2. Every account is always in exactly one household: yes.
3. Member cap: 6.
4. Join mechanism: an email-bound code pasted into Settings. A link variant can come later.
5. A leaver keeps their profile and their export, nothing from the shared kitchen.
6. Drafts are per member.
7. Diet merge: union, shown before Generate. Cook Now eaters: all members by default.
8. Children without accounts: one-off entries per plan under the generating member's consent.
9. Preferences stay per person; whoever generates decides. Household settings come when it confuses.
10. `WasteRecord` stays per person and joins the export.
11. Global RAG examples across accounts (pre-existing): plan content from one account can shape
    another account's prompt. Decide before the flag flips, not open-ended.
12. Health consent version bump: in PR 7 with the legal texts, not in PR 3 (see "Diets, allergies
    and consent"). **(decided 2026-11-02)** Decision 1's "accept the window" does not cover the
    health data copy: there the window fails open and silently, so 3a copies and 3b-1 contracts.

## Where each critic gap went

| gap | severity | placed in |
|---|---|---|
| one-off allergies vanish when their member leaves or is deleted | blocker | Diets: `health_contributors`, removed-on-read |
| last-member trigger race leaves an orphan household | major | Migrations 3 |
| two members subscribe through open Checkout sessions | major | Phase 2 |
| version numbers collide across households after a join | major | Concurrency: household-scoped token |
| second quick edit on one phone 409s | major | Concurrency: token on PUT, client queue |
| pooled cap reset by deleting a member | major | Phase 2 |
| old stack writes health blobs after the lift | major | Migrations 6, readers fail closed |
| demo account mints an invite | major | Join: minter must be verified, non-demo |
| feedback credit to a dormant customer | major | Phase 2 |
| Cook Now missing from the planhealth writers | minor | PR 3 |
| missing eater field skips the partner's allergies | minor | Diets: server default all members |
| contributor left or deleted mid-generation | minor | Diets: after-the-LLM filter |
| deactivated member holds a slot or covers the household | minor | Join and Phase 2 |
| leaver's invites stay valid | minor | Leave |
| a deleted member's drafts never swept | minor | Authorization: NULL-creator sweep |
| renamed columns keep old index names | minor | Migrations 5 |
| old stack cannot insert users after `household_01` | minor | Migrations 2: BEFORE INSERT trigger |
| funnel counts covered members as non-payers | minor | Phase 2 |
