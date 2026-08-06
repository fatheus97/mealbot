Work through accepted user-feedback tickets and ship the fixes autonomously.

Tickets live in the **private** repo `fatheus97/mealbot-tickets` — each one was created by an admin **Accept** in the dashboard, so every open ticket is already human-vetted as worth doing (that Accept is the cost gate; don't second-guess whether a ticket deserves effort, only *how much*). Code and PRs go to `fatheus97/mealbot`. On the maintainer's host `gh` is authed for both repos; in a cloud session `gh` may be missing or unauthenticated — use the GitHub MCP tools for ticket operations instead, and stick to whichever path works for the whole run.

Optional argument: a specific ticket number (do just that one), or a cap N. Default: process up to **3** actionable tickets, then stop and report.

Arguments: $ARGUMENTS

## Per run

1. **Fetch the queue.** `gh issue list -R fatheus97/mealbot-tickets --state open --limit 30`. Skip any labelled `needs-info`, `blocked`, or `shipped` — they're waiting on the owner or already done. **Before starting each ticket, look for a PR that already references it** across ALL states (`gh pr list -R fatheus97/mealbot --state all --search "Ships fatheus97/mealbot-tickets#<N>"`) and branch on it — this both dedups and closes out BIG tickets the owner merged out-of-band:
   - **OPEN PR** → already in flight (a re-run or the scheduled Stage 1). Don't open a second — resume its review loop if SMALL, or leave it for the owner if BIG. Move on.
   - **MERGED PR** → already shipped (typically a BIG one the owner merged out-of-band, or a SMALL one whose close didn't run). Close the ticket + label `shipped` with that PR's URL right here (step 8) — do NOT re-solve. Move on.
   - **CLOSED-unmerged PR** → the owner previously declined a fix; do NOT silently re-solve. Label the ticket `blocked` (so the declined decision persists and it isn't re-flagged every run — the owner removes `blocked` to re-queue, or closes the ticket) and note it once in the report.
   - **No PR** → proceed to triage (step 2).

   If a specific number was given in the arguments, do only that ticket.

2. **Triage each ticket for actionability BEFORE spending tokens on it.** This is a paid, health-adjacent product — never guess:
   - **Clear, reproducible bug OR a well-scoped small feature** → proceed to solve.
   - **Vague / not reproducible from the description / underspecified** → do NOT guess. Comment on the ticket with exactly what's missing to act on it, add the `needs-info` label, and SKIP. Surface it in the final report for the owner.
   - **Already fixed in the current code** → verify against the code, comment with the evidence (file:line), and close the ticket.
   - **Not-a-bug / user error / wontfix** → flag in the report for the owner to decide. Do NOT close it yourself.
   - **Very large or genuinely ambiguous in scope** → STOP and confirm the scope/plan with the owner before implementing (a token-cost guard — don't build the wrong big thing).

3. **Classify risk — this sets the merge bar (step 7):**
   - **SMALL / low-risk:** a localized bug fix, copy or UI tweak, config/docs change. Small diff. Touches NONE of the BIG categories below; adds no new endpoint or feature surface.
   - **BIG / risky — never auto-merge, HOLD for the owner:** anything touching
     - billing / Stripe / money, or auth / session / security;
     - **allergy / dietary-restriction filtering, allergen screening, or any nutrition / health-safety logic** — the flagship safety surface; a wrong "nut-free" plan is a real liability, so a fix here never auto-merges on our own tests + our own review, no matter how small the diff;
     - **CI/CD (`.github/workflows/*`), Docker, or any quality/security gate** (mypy-strict, ruff, gitleaks/secret scan, the review guard) — these ARE the safety net the rest of this autonomy model depends on, so a human looks before they change;
     - **a breaking change to an existing endpoint's request/response contract** — a field removed / renamed / retyped, stricter validation that 422s previously-valid input, or changed status codes — backward-incompatible for existing clients (the frontend, integrations) even when the diff is one line; this is distinct from a *new* endpoint;
     - a DB migration, a new feature or endpoint, a large or cross-cutting diff — or anything you are not confident about.
   - **When unsure, treat it as BIG** — the test is blast radius (who breaks if this is wrong or incompatible?), not diff size.

4. **Implement** on a feature branch off `main` (never off another open branch — see `feedback_pr_base_branch`):
   - Follow `CLAUDE.md` + everything in `.claude/rules/` exactly (type safety, specific error handling, async correctness, frontend theme/CLS/a11y, testing).
   - A bug fix STARTS with a failing regression test that reproduces it (`.claude/rules/testing.md`).
   - **Scale effort to risk:** BIG/risky changes get a **pre-push adversarial multi-agent review** (Workflow tool) before the PR — it has repeatedly caught real bugs a single pass missed. **Money-movers ALWAYS get it.** SMALL changes skip the Workflow (keep them cheap) and rely on tests + the Claude PR review. (A change that only reveals itself as BIG at step 7's diff re-check loops **back here** to get this same review against the finished diff before the owner ever sees it — the triage guess doesn't get to cost a BIG change its adversarial pass.)
   - One ticket = one PR. Keep the diff tight; no "while I'm here" refactors.

5. **Open the PR** against `mealbot` and cross-link it to the ticket:
   - PR body: a short summary + `Ships fatheus97/mealbot-tickets#<N>`. **Never paste user PII** (the ticket is PII-safe by design — keep it that way; reference the user only as the ticket does).
   - Comment the PR URL on the ticket (cross-repo close keywords don't fire, so the link is the trace). The ticket is closed + labelled `shipped` when its PR merges — in step 8 this run for a SMALL PR (this run merges it), or via step 1's merged-PR check on a later run for a BIG PR the owner merged out-of-band.

6. **Run the CI + review loop** per the Autonomy section of `.claude/rules/git.md`: wait for CI + the Claude PR review (poll with `ScheduleWakeup`, don't block), then for **every** finding either fix it (verify against the real code first — the review can overcorrect) or reply on the thread with justification and resolve it. Respect the conversation-resolution merge gate. **Never `--admin`, never force-push, never bypass branch protection.**

7. **Merge bar — owner's rule is "auto-merge small, hold big":**
   - **First, re-classify the ACTUAL diff — the triage label was an estimate.** Step 3 classified SMALL/BIG from the ticket *description*, before any code existed. Before any SMALL auto-merge, re-apply the step-3 BIG categories to the *finished diff* (the Claude PR review already reads the whole diff — lean on it plus your own read). A ticket that triaged SMALL but whose fix ended up touching a BIG category — loosening a shared/validator that the allergen or billing path also uses, editing dietary/allergen code, a workflow/gate, or an existing endpoint's contract — **is now BIG.** The diff is the source of truth, not the triage guess.
   - **SMALL / low-risk (confirmed against the finished diff)** → once CI is green AND the review has no actionable items, **merge**: `gh pr merge <n> --squash --delete-branch`. This is the standing authorization — don't re-ask.
   - **BIG / risky (by triage OR by the diff re-check)** → do NOT merge; hold for the owner. **But first make sure it actually got BIG-tier rigor, not just the BIG-tier hold.** A change that was BIG *at triage* already received step 4's pre-push adversarial multi-agent review; one that triaged SMALL and escalated to BIG only *here* **skipped that Workflow at step 4** (the decision was made from the triage guess the finished diff has now disproved) — so left as-is it would reach the owner with only the standard Claude PR review behind it, on exactly the highest-risk tier. So **on a SMALL→BIG escalation, loop back to step 4 and run the adversarial Workflow review against the finished diff BEFORE pinging the owner** — fix or answer anything it surfaces per step 6, then re-confirm CI is green. Only then **ping the owner** with the PR link and a one-paragraph plain-English summary of what it does and any risk, for their glance and merge. (A change that was already BIG at triage skips straight to the ping — it got the Workflow at step 4.)

8. **Close the ticket when its PR is merged** — for a SMALL PR this run just merged, and for a BIG PR found already-merged via step 1 (the owner merged it out-of-band). Same for both, so the paths are symmetric: `gh issue close -R fatheus97/mealbot-tickets <N> -c "Shipped in <PR URL> — deploying."` then `gh issue edit -R fatheus97/mealbot-tickets <N> --add-label shipped`. (Merging `mealbot` main IS the deploy; don't tell the owner to deploy manually.)

## Report at the end

A compact list, one line per ticket: **outcome** (shipped+merged / awaiting-your-merge (BIG) / needs-info / flagged-for-you / failed) with the ticket and PR links. Then a short "**needs you**" section pulling together: BIG PRs awaiting your glance, `needs-info` tickets, and any wontfix / not-a-bug candidates. State what's left unprocessed in the queue.

## Guardrails

- The dashboard **Accept** + your **triage** are the two cost gates — never flail on a vague ticket; label it `needs-info` and move on.
- Respect the per-run cap; report the remaining queue rather than draining it.
- Everything ships through a PR + CI + review. Nothing bypasses branch protection.
- Support labels (`needs-info`, `blocked`, `shipped`) live in `mealbot-tickets`; if one is missing, `gh label create <name> -R fatheus97/mealbot-tickets`.
