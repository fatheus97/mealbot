# Start fresh: restock the fridge after an absence, and on first run

## Goal

Once the fridge list has gone stale, one guided flow replaces it with what is actually at home. The person scans photos of their food and their recent receipts, reviews one combined list and saves it as the new fridge. The app asks once, when the household fridge list has not changed for 14 days or more. It offers the same flow as a second onboarding step when a new account's fridge is empty. A Start fresh button in the Fridge section opens it at any time.

Three properties hold throughout.

- The fridge is never emptied first. The only write is one version-checked replace at the end. A partner never sees an empty fridge while scanning runs, an abandoned flow changes nothing, and each scan still normalizes names against the old list.
- There is no new scan endpoint and no new LLM call, and the paygate and the rate limit do not change. Every image goes through the existing `POST /fridge/scan`.
- Nothing is recorded as waste.

These are deliberately left out of v1: server-side batch scanning with one cross-image normalize, a multi-file picker, a camera stream kept open across shots, client-side downscaling, a "keep from your old list" checklist, a server-side refusal while plans hold food, a bulk waste question, and a demo path. Each one appears again under Risks or Owner decisions, together with what would justify adding it.

This file lands as `docs/restock-design.md` in PR 1.

## What exists (file:line)

Everything below was read at 0f51f70. Two dependency bumps landed after that (#580, #583) and touch none of it. The alembic head was household_07; PR 1 adds restock_01 on top.

Scanning

- `POST /fridge/scan` takes one file and a `source` (receipt or food_photo). It sits behind `require_generation_budget` and a limit of 5 per minute per user (backend/app/api/fridge.py:199-348, limit at :200). Each call makes a vision call and then a second normalize call against the household's current fridge names (fridge.py:259-292). It stages usage and a `receipt_scan` MachineGeneration and returns `generation_id` (fridge.py:313-348).
- Expiry is the purchase date, or today, plus the shelf life (fridge.py:294-311). The "About expiry dates" InfoHint states that rule (frontend/src/i18n/en.ts:826-828).
- `ReceiptScanner` scans one file at a time. The input reads `files[0]` (frontend/src/components/ReceiptScanner.tsx:296) and renders only in the idle and error states. `handleScan` builds review rows against `currentFridge` (ReceiptScanner.tsx:242-284). `derive` marks a row as new when `existingQty === 0` (ReceiptScanner.tsx:474-483), so `currentFridge={[]}` shows every row as new with `needToUse` false. A failed confirm switches to the error state, which hides the rows (ReceiptScanner.tsx:301-332).
- `scanReceipt` falls back to an English sentence (frontend/src/api.ts:254-275), and `mergeFridgeItems` throws a raw status dump (api.ts:891-907). `RequestCopy` is the existing way to pass translated copy into api.ts (api.ts:655-660). slowapi's 429 envelope carries no `detail` (api.ts:634-642).

Writes

- `PUT /fridge` replaces the whole list. With `X-Fridge-Version` it is refused with 409 `fridge_changed` if anyone wrote since. Without the header it is accepted unchecked (fridge.py:122-153; backend/app/services/fridge_service.py:96-106).
- `_count_write` is the single place where a fridge write is counted, and it runs before anything is deleted (fridge_service.py:124-140). It is reached through `replace_fridge_items` (fridge_service.py:325), which serves PUT, merge, every plan transition and Cook Now, and through the household join (backend/app/services/household.py:261). It counts staples writes too.
- `POST /fridge/merge` takes one `generation_id`. It diffs the payload against that generation's output with `_canonical_scan_fields` and records a `receipt_merge` correction (fridge.py:80-101, 351-424). It is never version-checked.
- Waste is written only by `POST /fridge/waste` (fridge.py:156-196).
- On the client, `useUpdateShelf` sends the token of the list an edit was made from. It queues every fridge save under scope `fridge`, throws `ShelfChangedError` on 409, and invalidates the cache without awaiting the refetch (frontend/src/hooks/useServerState.ts:78-124). `cachedShelf` reads the list and its token together (useServerState.ts:42-48). `useMergeFridge` sits outside that queue (useServerState.ts:278-288).

Absence signal

- Nothing records when the fridge was written. Household has `created_at` and two integer counters (backend/app/models/db_models.py:50-58), and StockItem rows are rewritten on every save. The BEFORE INSERT trigger creates a household naming only `created_at` (db_models.py:75-77), so any new household column must be nullable or carry a server default. `HouseholdInvite.expires_at` is the TIMESTAMPTZ precedent (db_models.py:976-978). household_06 is the ADD COLUMN template, including `SET LOCAL lock_timeout = '5s'` (backend/alembic/versions/household_06_shelf_versions.py).
- `accept_terms` stamps the server clock and never trusts a time sent by the client (backend/app/api/user.py:227-254).

Plans

- The plan list returns only confirmed plans of kind `planned` (backend/app/api/plan.py:154-162), each with a derived status. `planned` and `active` mean uncooked meals remain. `cooked` means every meal is cooked but the plan is not finished (backend/app/services/plan_service.py:100-110). Finish merges the uncooked meals' reserved batches back into the fridge (plan_service.py:213-227, 302-330).
- Starring a recipe creates a `cook_now` plan: confirmed, with one uncooked entry and an empty snapshot, and never finished (backend/app/api/recipe.py:477-516). `useFinishPlan` exists, with an English error (useServerState.ts:641-655).

First run and layout

- `OnboardingModal` PATCHes the preferences with `onboarding_completed: true`, then calls `setOnboardingCompleted(true)` (frontend/src/components/OnboardingModal.tsx:22-42). It is mounted while `!onboardingCompleted` (frontend/src/App.tsx:98), next to `<Fridge />` (App.tsx:86) in `MainLayout`.
- Any 403 dispatches `mealbot:forbidden`, which re-reads the profile (frontend/src/contexts/AuthContext.tsx:389-393). Once the PATCH has landed, that re-read sets `onboardingCompleted` to true and unmounts the modal.
- `ModalShell` goes full screen on a phone and takes `closeOnEscape` (frontend/src/components/ModalShell.tsx:22-27). `ConfirmDialog` asks one question at z-index 1100 and can be non-destructive (frontend/src/components/ConfirmDialog.tsx). `InfoHint` is the approved way to explain things (frontend/src/components/InfoHint.tsx:63).
- The scanner mounts inside Fridge (Fridge.tsx:661). Add stays disabled until the first GET lands (Fridge.tsx:754).

Paygate

- Paid accounts get 2.00 EUR per calendar month and trials get 0.75 EUR. Admin and demo accounts are unlimited. Spend is counted per user_id (backend/app/core/config.py:226-227; backend/app/services/usage_budget.py:68-142). The cap is checked once per request (backend/app/api/deps.py:166-212). The usage-cap sentence is English only (usage_budget.py:150).

## The flow

### Return after an absence

1. On app load and on window focus, `useRestockStatus` calls `GET /fridge/restock`. It runs only for a logged-in, non-demo user who has finished onboarding.
2. The prompt is due when the household fridge has not been written for 14 days or more and this person has not answered since that write. A partner who kept the fridge current keeps it not due for both members.
3. A `ConfirmDialog` (not destructive) asks one question: "Your fridge list hasn't changed in 23 days. Start fresh from photos of your food and your recent receipts?" The buttons are Start fresh and Not now, and Escape or a backdrop click count as Not now. The wording is about the list, not "welcome back", because someone who used only drafts for two weeks gets the prompt too.
4. Either answer calls `POST /fridge/restock/answer`, which stamps the server clock. The prompt comes back only after the fridge is written again and then stays unchanged for another 14 days. A flag held for the session stops a focus refetch from asking again, even if the POST failed.
5. Start fresh opens the restock dialog described next.

### The restock dialog (one flow for all three entry points)

1. `RestockDialog` opens in a `ModalShell`. It is full screen on a phone, Escape and the backdrop do not close it, and an explicit Close button does. On mount it reads the fridge list and its token together with `cachedShelf`. Every entry point renders only after the first fridge GET has landed, so the token is not null. If it is, Save stays disabled and the loading copy shows; the dialog never sends an unchecked PUT.
2. The header says what will happen. When the list has items, it reads "Saving replaces your fridge list (34 items) with what you scan now." In a shared household it adds "You share this fridge. The new list replaces it for everyone in your household." For each plan with status planned or active it shows "Your plan from 20 Oct is not finished. Finish it first, or the food set aside for its uncooked meals comes back on top of your new list when you finish it later." with a Finish it button. After a Finish, the dialog refetches the fridge and the plan list and reads the list and token again.
3. Below the header sits the existing `ReceiptScanner` in replace mode: `currentFridge={[]}`, an `onSave` handler and a save label. The person picks Receipt or Food photo, then a file or the camera. After the first scan the review table appears, and "Add another photo or receipt" appends the next scan's rows to the same list. The source can change between scans.
4. Two badges help with review. A row whose name also came from a different scan says "Also in another scan. Remove one if it's the same food." A row whose date has already passed says "Past its date". When an image fails, its message shows under the list and every row stays.
5. The Save button reads "Replace the fridge with these 21 items". It sends one `PUT /fridge` with the token captured in step 1 and one `generation_id` per scan. On success the dialog shows "Your fridge now has 21 items" with Undo and Close. Undo PUTs the old list back with the token the save returned, so it is refused if anyone has written since.
6. On 409 `fridge_changed` the rows stay. The dialog awaits a fridge refetch, reads the new token and shows the server's sentence, followed by "Saving again replaces their change too."
7. When there is nothing to scan, the scanner's idle state offers "Empty the fridge". It saves an empty list through the same path and ends on the same Done screen with Undo. No reason is asked per item.

### Anytime

A Start fresh button sits beside Add ingredient in the Fridge section. It is hidden for demo accounts and disabled until the first fridge GET lands, the same rule as Add. Its InfoHint says: "Start fresh replaces the whole fridge list with what you scan now. You can undo it right after. Old items are not counted as waste. If the list hasn't changed for 14 days, the app asks you once."

### First run

1. `OnboardingModal` saves the preferences exactly as today, so `track_snacks` is stored before any scan.
2. If the fridge has loaded and is empty, the same card shows a second screen instead of closing: "Stock your fridge now? Take photos of your food and your latest receipts, check the list, save." The buttons are Scan my food and Later.
3. Invitees start with an unconfirmed email, and every scan returns 403 until they confirm it. For them, Scan is replaced by "Confirm your email first. Then Start fresh in the Fridge section scans your food." and a single OK button.
4. Every button calls `setOnboardingCompleted(true)`. Scan also opens `RestockDialog` from `MainLayout`. The dialog never renders inside the onboarding card, so a profile re-read (after any 403, for example) cannot unmount it while it holds paid scans. That unmount was the flaw in the first draft, which nested the scanner inside the modal.
5. With a non-empty fridge the modal closes exactly as today. That covers an admin onboarding reset and a new member of a shared household. A reload during the second screen skips it for good, because the server flag is already true. The Start fresh button is still there.

## Backend

PR 1, the absence signal

- Add `Household.fridge_written_at: datetime | None` and `User.restock_prompt_answered_at: datetime | None`. Both are `DateTime(timezone=True)` and nullable, following `HouseholdInvite.expires_at`, so comparisons are always aware against aware.
- In `_count_write`, when `shelf == "fridge"`, the same UPDATE with RETURNING also sets `fridge_written_at = func.now()`. That one change covers PUT, merge, every plan transition that writes the fridge, Cook Now and the household join, and a staples write never moves it. The demo seed inserts rows without `_count_write` (backend/app/services/demo_user.py:62-74), so a demo household stays NULL.
- In fridge_service.py, add `RESTOCK_AFTER: Final = timedelta(days=14)` and a pure `restock_due(written_at, answered_at, now) -> bool`. It is due when `written_at` is set, `now - written_at >= RESTOCK_AFTER`, and `answered_at` is None or earlier than `written_at`.
- Add `RestockStatus(BaseModel)` with `due: bool` and `days_since_write: int | None`, next to `StockItemDTO` in backend/app/models/plan_models.py.
- `GET /fridge/restock -> RestockStatus`. It returns due false for a demo user, or a user who has not finished onboarding, without touching the database. Otherwise it does one `session.get(Household, kitchen.household_id)` and calls `restock_due`. A missing household (a join race) counts as not due. It takes no lock.
- `POST /fridge/restock/answer -> RestockStatus` is limited with `@limiter.limit("10/minute", key_func=user_id_key_func)` and takes no body. It sets `restock_prompt_answered_at = datetime.now(UTC)` on the loaded user, commits and returns due false. It takes no kitchen lock, because nothing in the fridge changes. It is deliberately not a PATCH /users field, so the two-payload-builder trap and the AuthLoginResponse/UserProfile trap do not apply.

PR 2, several scans in one merge

- `merge_fridge_items` takes `generation_id: list[int] = Query(default=[])`. The name stays the same, so an old bundle still sending `?generation_id=5` keeps working. More than 20 ids returns 422.
- The telemetry block at fridge.py:385-412 moves into `_record_scan_corrections(session, user_id, generation_ids, payload, via)`. The helper resolves each id with `resolve_owned_generation(surface="receipt_scan")` and skips foreign ids. It concatenates their outputs and compares the concatenation with the payload through `_canonical_scan_fields`. If they differ, it records one `receipt_merge` correction per generation. Each correction has that generation's output as before, the payload as after, and context `{batch, scanned_count, submitted_count, via}`.
- With one id the result is exactly what today's merge records. With several, any edit marks every scan in the batch as corrected. That is conservative and never a false "accepted as is", and `context.batch` lets offline analysis tell batches apart. The existing try/except stays, so telemetry can never fail a save.

PR 3, the restock save

- `put_fridge` takes the same `generation_id` list. It calls `_record_scan_corrections(..., via="replace")` after `lock_kitchen`, in the same transaction as the replace. A PUT without ids behaves exactly as today.
- Nothing else changes on the backend. The token-checked PUT is already an atomic replace that returns 409 before anything is deleted (fridge_service.py:124-140, 369, 399), so no new write endpoint is needed. There is no change to /scan, the paygate, the rate limits, the prompts, `merge_into_fridge_buckets`, `replace_fridge_items` or error_copy.

## Frontend

PR 2: ReceiptScanner, used both by the everyday scanner and by the restock

- In the review state, the source radio, file input and camera button render as "Add another photo or receipt". `handleScan` appends when rows already exist. A scan that runs during review sets a `pending` flag instead of the `scanning` state, which would hide the table. Confirm is disabled while a scan is pending.
- `ReviewItem` gains `scan: number`, and `scanGenerationId` becomes `generationIds: number[]`.
- A scan that fails during review shows an inline error and keeps the rows. A confirm that fails stays in review with `confirmError` instead of switching to `error`.
- Badges: "Also in another scan" appears when the trimmed, lowercased name occurs in a row from a different scan. "Past its date" appears when `expirationDate < todayISO()`, the rule of `isExpired` in frontend/src/utils/expiry.ts.
- In api.ts, `scanReceipt(file, source, copy: RequestCopy)` reads the body once on a 429. When `detail.code === "usage_cap_reached"` it keeps the server's `user_detail`. Any other 429 throws `copy.rateLimited`. This works whatever shape slowapi's envelope turns out to have. (The first draft treated "no detail" as the rate-limit signal, and a test double with `{detail: "5 per 1 minute"}` would have shown that raw English.) The English fallback becomes `copy.fallback`.
- `mergeFridgeItems(items, generationIds, copy)` sends one `generation_id` parameter per id and uses `extractErrorDetail` with `copy.fallback`. The `useScanReceipt` and `useMergeFridge` variables follow.
- New i18n keys are receipt.addAnother, receipt.alsoInOtherScan, receipt.pastDate and receipt.rateLimited. The existing receipt.scanFailed and receipt.mergeFailed are reused as fallbacks.

PR 3: Start fresh

- `ReceiptScanner` gains optional `onSave(items, generationIds) => Promise<void>` and `saveLabel` props. When `onSave` is given, Confirm calls it instead of `useMergeFridge`, with the same error contract (the rows stay). The idle state then also shows "Empty the fridge", which calls `onSave([], [])`. The demo path is untouched.
- `ShelfSave` in `useUpdateShelf` gains an optional `generationIds`, appended to the PUT path only when the list is non-empty. Staples saves and Fridge.tsx edits send the same request as today.
- `RestockDialog.tsx` is new, about 150 lines.
  - It renders in `ModalShell` with `closeOnEscape={false}`, a no-op `onClose` and an explicit Close button. It sets an explicit surface and an explicit text colour.
  - It takes a snapshot `{items, token}` from `cachedShelf` at mount. `recapture()` awaits `queryClient.refetchQueries({ queryKey: ['fridge', userId], exact: true })` and the same for `['planList', userId]`, then reads `cachedShelf` again. It runs after Finish it and after a 409. The awaited refetch fixes the first draft's race: a quick second Save would otherwise still carry the stale token, because `useUpdateShelf.onError` does not await its invalidation.
  - The shared-household line comes from `useHousehold(userId, householdsEnabled)` when `members.length > 1`. The plan notices come from `usePlanList(userId)` entries with status `planned` or `active`, never `cooked`. Finish it uses `useFinishPlan`, with a localized error.
  - Save calls `useUpdateFridge().mutateAsync({ userId, items, token, generationIds })`. It therefore joins the `fridge` save queue, and Fridge.tsx's `savesPending` holds back its re-seed while the save runs. On `ShelfChangedError` it awaits `recapture()` and rethrows the server sentence followed by restock.saveAgain. On success it invalidates `['restock', userId]` and shows Done.
  - Undo sends the snapshot items, with their ids stripped, using the token the save returned.
- `MainLayout` in App.tsx owns `restockOpen`. It renders `{restockOpen && <RestockDialog onClose={...} />}` and passes `onStartRestock` one level down to `Fridge`, and in PR 5 to `OnboardingModal`. One level is not prop drilling, and it needs no store.
- `Fridge.tsx` gets the Start fresh button beside Add ingredient (Fridge.tsx:754). It is hidden for demo, `disabled={!serverFridge}`, and carries its InfoHint.
- New i18n keys: restock.title, restock.replaces_* (plural), restock.shared, restock.openPlan, restock.finishPlan, restock.finishFailed, restock.save_* (plural), restock.saveAgain, restock.emptyNow, restock.done_* (plural), restock.undo, restock.undoRefused, restock.close, fridge.startFresh, fridge.startFreshHintLabel and fridge.startFreshHint.

PR 4: the prompt

- types.ts gets `RestockStatus`, and api.ts gets `fetchRestockStatus()` and `answerRestockPrompt()`.
- useServerState gets `useRestockStatus(userId, enabled)`, with the SHARED options and key `['restock', userId]`, and `useAnswerRestock()`, which sets the cached `due` to false on success.
- `RestockPrompt.tsx` is new, about 50 lines. It is a `ConfirmDialog` with `destructive={false}`, rendered by MainLayout when `status.due && onboardingCompleted && !isDemo && !restockOpen` and the session flag is unset. Its days count uses `tn`. Both buttons answer, and Start fresh also calls `onStartRestock`. As a modal it moves nothing in the page flow, so it causes no CLS.
- New i18n keys are restock.promptTitle, restock.promptMessage_* (plural), restock.start and restock.notNow.

PR 5: onboarding

- `OnboardingModal` keeps a local `step: 'prefs' | 'stock'`. After a successful PATCH, if `useFridge(userId).data` has loaded and is empty, it shows the stock step. Otherwise it calls `setOnboardingCompleted(true)` as today. The unverified branch reads `emailVerified` from `useAuth`.
- The admin Reset onboarding InfoHint (UserManagementPanel.tsx:366) adds "and offers to stock an empty fridge".
- New i18n keys are onboarding.stockTitle, onboarding.stockText, onboarding.stockScan, onboarding.stockLater, onboarding.stockVerifyFirst and onboarding.stockOk.

Every new string follows the existing i18n rules. Each one has en and cs entries, one key per sentence, and the Czech plurals _one, _few, _many and _other. Each key is referenced literally so keyUsage.test.ts passes, and the Czech copy goes through humanizer-cs.

## Data and migration

PR 1 ships one revision, `restock_01_fridge_written_at`, with down_revision `household_07`:

```sql
SET LOCAL lock_timeout = '5s';
ALTER TABLE household ADD COLUMN fridge_written_at TIMESTAMPTZ NULL;
UPDATE household SET fridge_written_at = now();
ALTER TABLE "user" ADD COLUMN restock_prompt_answered_at TIMESTAMPTZ NULL;
```

- Both columns are nullable with no default. The ADD COLUMNs therefore change only the catalog, and the trigger that inserts a household naming only `created_at` keeps working.
- The backfill sets the deploy time. That is a lower bound on how stale each fridge is, so it can never fire a false prompt, and a household that is away across the deploy is still asked 14 days after it. Without the backfill that household would never be asked on this return. Two of the three drafts missed this.
- The UPDATE touches a handful of rows while holding the lock the ADD COLUMN already has.
- Households created after the deploy start at NULL, which is never due until their first fridge write. First run is covered by onboarding instead.
- Both ALTERs take ACCESS EXCLUSIVE, and `"user"` is read on every request. The 5 s lock timeout makes the migration give up rather than queue, and deploy.sh retries it.
- Downgrade drops both columns. They hold nobody's food.
- The migrate service runs it automatically on merge. Right before merging, re-check that `alembic heads` shows a single head, because parallel migration PRs once picked the same id (#272/#273).

## Shared household and plans

- The restock is a replace of the shared list, so the dialog says so in its header. The single PUT carries the token from when the dialog opened. A partner's edit, Cook Now, a plan confirm, finish or delete, or a save from this person's Fridge panel in another tab all bump the version, and the save then returns 409 before anything is deleted. The scanned rows stay. A second Save knowingly overwrites the other change, and the copy says so.
- Scans normalize names against the old list, which still exists until the save. Names therefore mostly line up across images and with the names in plan snapshots.
- Confirmed, unfinished plans hold food outside the fridge. That food sits in `consumed_snapshot_json`, and Finish, Unconfirm or Delete merges it back with its old dates. Photos of the real fridge also include that reserved food, so restocking around an open plan double-counts it. The dialog names each such plan and offers Finish it. A Finish that lands while the dialog is open (a partner's, say) returns 409 on the save, and the recapture then shows the plan.
- The check uses the plan list on purpose. The list excludes `cook_now` plans, while a raw MealEntry query for "confirmed, unfinished, uncooked" would also match every starred recipe. Starring creates a confirmed `cook_now` plan with an uncooked entry and an empty snapshot that is never finished (recipe.py:477-516). A server refusal built on that query, as proposed in the risk-first draft, would have blocked restock forever for anyone with a favourite. The status `cooked` (all meals cooked, not finished) restores nothing, so it is not flagged.
- After a restock, reopening an old finished plan may return 409 `plan_reopen_shortage`. That is existing behaviour and correct: the food is gone.
- The prompt is keyed on the household fridge, and the answer is per person. A restock by either member writes the fridge, which clears the prompt for both.
- Scan spend is per user_id, so the member who restocks pays for the scans.
- A first-run user who empties their fridge and later joins a household brings their kitchen into the partner's (household.py:138-199). That is existing join behaviour and unchanged here.

## Waste tracking

- A restock records nothing as waste. It never calls `POST /fridge/waste`, and PUT never writes a WasteRecord.
- Old items are not waste by default. WasteRecord is keyed by user_id, so a bulk answer would charge a partner's food to whoever restocked. A bulk answer would also blur the deliberate-removal signal, and `still_fine` is accepted only from `finish_plan`.
- Finish it in the dialog uses the bare `useFinishPlan` and skips MealPlanner's expired-items review, so it records nothing either. That is right, because the list is about to be replaced.
- The InfoHint says old items are not counted as waste. A frontend test asserts that no `/fridge/waste` request is made, and a backend test asserts that a PUT with generation ids leaves zero WasteRecord rows.

## Cost

- Each image costs one vision call and one normalize text call, and each goes through the existing per-request budget check and the 5 per minute limit. The save, the prompt endpoints and the answer make no LLM call.
- Scans are added one at a time by the person, so the soft cap (checked once per request) can be overshot by at most one scan. A sixth image within a minute gets a localized "too many scans, wait a moment", and the rows stay.
- The cost per scan has never been measured. Before PR 3 merges, read the prod LlmUsage rows with surface `receipt_scan` (median and 90th percentile EUR per scan over the last 30 days; read-only) and record the numbers in the PR. If ten scans would take more than about a third of the 0.75 EUR trial budget, add the per-restock image cap from the owner decisions below.
- The usage-cap 429 sentence is English only (usage_budget.py:150). It will show in Czech UI as it already does today. File it as a separate follow-up.
- Client-side downscaling to 2048 px JPEG is the follow-up if the measured cost is high or phone photos hit the 10 MB limit. It may also cut vision tokens, though that is unmeasured.

## PR slices

1. PR 1, `feat(fridge): record when the household fridge was last written`. It contains the migration, both model columns, the `_count_write` stamp (fridge shelf only), `RESTOCK_AFTER`, `restock_due`, `RestockStatus`, `GET /fridge/restock`, `POST /fridge/restock/answer` and this document. The tests go in backend/tests/test_restock.py:
   - the `restock_due` table: NULL is never due, 13 days is not due, 14 days is due, an answer before the last write is due, an answer after it is not;
   - a PUT, a merge, a plan finish that restores food, Cook Now and a household join each stamp the column;
   - a staples PUT does not stamp it, and a PUT refused with 409 leaves it unchanged;
   - demo and onboarding-incomplete users are never due, and a partner's write makes both members not due;
   - the answer endpoint ignores any body and uses the server clock;
   - the comparisons are aware against aware.
   It ships alone: nothing calls the endpoints yet, and the stamp starts collecting real data.
2. PR 2, `feat(scanner): add more photos and receipts to one review list`. It contains the merge `generation_id` list, `_record_scan_corrections`, the ReceiptScanner add-another, both badges, failures that keep the rows, the 429 split through `RequestCopy`, the localized merge errors, the hook variables and i18n.
   - test_receipt_telemetry.py: one id gives the same result as today; several unedited ids record no correction; several edited ids record one correction per generation with `context.batch`; a foreign id is ignored; 21 ids return 422.
   - ReceiptScanner.test.tsx: a second scan appends; the id list reaches merge; the duplicate badge appears only across scans; the past-date badge; rows stay after a failed scan and after a failed confirm; the rate-limit copy and the usage-cap copy; Confirm is disabled while a scan runs. The existing 30 cases stay unchanged, and the test count must reconcile.
   - An api test covers the 429 split.
   It ships alone and improves the everyday scanner.
3. PR 3, `feat(fridge): Start fresh replaces the shared fridge from scans`. It needs PR 2. It contains the PUT `generation_id` list, the ReceiptScanner `onSave`, `saveLabel` and empty button, `generationIds` in `useUpdateShelf`, RestockDialog, the MainLayout state, the Fridge button and InfoHint, and i18n.
   - Backend: a PUT with ids records corrections with `via=replace`; a PUT without ids is unchanged; a PUT with ids writes no WasteRecord; a stale-token PUT records nothing.
   - RestockDialog.test.tsx: the token from mount is sent; the generation ids ride on the PUT query; a 409 keeps the rows, and the second save uses the reloaded token only after the awaited refetch; the shared line shows only with more than one member; plan notices show only for planned and active; Finish it is followed by a recapture; Empty sends an empty list; no `/fridge/waste` call is made; Undo sends the old list without ids and with the returned token; Escape and the backdrop do not close the dialog; every visible string is translated.
   - Fridge test: the button is hidden for demo and disabled before load. useServerState test: the ids are appended only when non-empty.
   Before merging, record the prod cost reading, and run a two-theme browser check at 375 px with the camera open.
4. PR 4, `feat(fridge): ask once when the fridge list has gone stale`. It needs PR 1 and PR 3 and contains the hooks, api and types, RestockPrompt in MainLayout and i18n. RestockPrompt.test.tsx checks that the prompt renders only when due; that both buttons post the answer and Start fresh also opens the dialog; that a focus refetch in the same session does not ask again, even after a failed POST; and that the prompt is hidden for demo and during onboarding. Do the two-theme check here too.
5. PR 5, `feat(onboarding): offer Start fresh when a new fridge is empty`. It needs PR 3 and contains the OnboardingModal step, the unverified branch, the admin InfoHint text, i18n and the ROADMAP row moved to shipped. OnboardingModal.test.tsx checks that the step appears only for a loaded, empty fridge; that Later and Scan both complete onboarding and Scan calls `onStartRestock`; the unverified branch; that the PATCH payload is unchanged; and that every visible string is translated with the step open.

## Risks

- After a 409, a second Save overwrites the partner's edit, and the person is told so. The ceiling is that they do not see what the partner changed. If that bites, the upgrade is the risk-first draft's rebase: list the rows added since the snapshot, pre-ticked.
- The open-plan notice can be ignored, and a plan left open brings its reserved food back later. The notice explains the consequence and offers Finish it. A hard block is an owner decision below.
- Duplicates across images are only flagged, by exact lowercased name. Images are not normalized against each other, only against the old list. The upgrade path is a server batch with one normalize over the union of names.
- Old receipts give dates that have already passed, and `get_fridge_items` will tick use-soon on them. The past-date badge shows them and the dates can be edited. The date rule itself is unchanged, so the expiry InfoHint stays true.
- Paid scans are lost if the person presses Close or reloads before saving. Escape and the backdrop cannot close the dialog, and a failed confirm keeps the rows. If someone reports losing scans, add a sessionStorage draft.
- For an unverified user every scan returns 403, and each image shows that message; the dialog is no longer unmounted by the profile re-read. A 402 opens the PaywallModal (z-index 1200) over the dialog and the rows stay.
- Some phones may ask for camera permission again on each capture, because the stream stops after every shot. This cannot be verified from code. Keeping one stream open across shots is the follow-up if it is reported.
- The clock also moves on system writes (plan confirm and finish, Cook Now, a join). That is intended, because each is someone using the shared fridge, and the wording "hasn't changed in N days" stays true.
- Because of the backfill, every dormant household becomes due 14 days after deploy at the same moment. With two real users that is harmless.
- The migration takes locks on `household` and `"user"`. It runs under the 5 s lock timeout with deploy.sh retrying, uses a descriptive revision id, and gets a single-head check right before merging.
- Demo accounts get due false from the server, the button is hidden, the demo seed never stamps, and the single-scan demo path is untouched.
- Every new surface is a modal with an explicit background and text colour, so it causes no layout shift. The contrast suite runs, and PRs 3 to 5 need the two-theme browser pass. Without a browser, say so in the PR and ask the owner to look before merging.

## Owner decisions

### 1. Who does Not now cover?

The options are per person (`user.restock_prompt_answered_at`) or per household, where one partner's no silences both. The recommendation is per person, because the prompt is a personal interruption and a restock by either partner already clears it for both.

### 2. Does Start fresh also count as the answer?

The options are that any answer stamps, or that only Not now stamps and an abandoned Start asks again on the next load. The recommendation is that any answer stamps, because you asked for "asked once", and the Start fresh button in the Fridge section is always there.

### 3. How long a gap counts as away?

The options are a fixed 14 days as a code constant, an env setting, or a per-user setting. The recommendation is the 14-day constant, because it is your own example and changing it later is a one-line PR.

### 4. Which writes reset the clock?

The options are every counted fridge write (manual edits, scans, plan confirm and finish, Cook Now, a household join), or manual edits only, which needs a flag threaded through every writer. The recommendation is every counted write, because each one is someone using the shared fridge, and it costs no extra code.

### 5. What happens with an open plan at restock time?

The options are:

- a notice with a Finish it button, without blocking;
- blocking Save until the plan is finished;
- a server refusal, which must be scoped to kind `planned` so starred recipes do not block it forever;
- finishing the plan inside the save, which is a new server path.

The recommendation is the notice with Finish it, because blocking traps someone who is still cooking from that plan and you can choose case by case.

### 6. With waste tracking on, should a restock ask about the old food?

The options are to record nothing, or to ask one optional bulk question, which needs a new `restock` source in WasteEntryDTO. The recommendation is to record nothing, because old items are not waste by default and a bulk answer would charge a partner's food to whoever restocked.

### 7. Same food found in two scans?

The options are to flag it and let the person remove one, to sum automatically, or to drop the second automatically. The recommendation is to flag only, because two packs of milk are real while a receipt plus a photo of the same milk is one, and only the person at the fridge knows which.

### 8. First run for an invitee whose email is not confirmed yet?

The options are a one-sentence pointer (confirm your email, then use Start fresh), skipping the step, or showing the scanner and letting every scan fail with 403. The recommendation is the pointer, because invitees are almost the whole first-run population while registration is closed, and they all start unconfirmed.

### 9. Keep a "keep from your old list" checklist in the review?

The options are to leave it out of v1, or to add a collapsed checklist of the old items with nothing ticked. The recommendation is to leave it out, because your idea is to photograph what is at home, and Add ingredient covers an item someone missed. Add it if restocks keep losing freezer or cupboard food.

### 10. How many images per restock?

The options are no extra cap, or a cap of 10. The recommendation is no cap until the prod cost per scan is read, because the per-image budget check already stops spending at the monthly limit. Set the cap of 10 if ten scans turn out to cost more than about a third of the trial budget.

### 11. Demo accounts?

The options are to hide the flow in v1, or to build a fake multi-image path like `handleDemoScan`. The recommendation is to hide it, because the demo never calls /scan and its single-scan path already shows the feature's core.

### 12. Name?

The options are Start fresh / Začít nanovo, or Restock from photos / Doplnit z fotek a účtenek. The recommendation is Start fresh / Začít nanovo, because it is your own name for the idea and fits a phone button, while the prompt sentence carries the photos and receipts detail.
