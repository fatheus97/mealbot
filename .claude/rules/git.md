## Git Conventions
- Use conventional commits: feat/fix/refactor/chore/docs/test
- Write clear commit messages explaining WHY, not just what
- One logical change per commit
- main branch is protected — no direct pushes
- All changes go through PRs with squash merge
- Claude Code must NEVER force push or push directly to main
- Claude Code must NEVER bypass branch protection — no `gh pr merge --admin`
- Merging is STANDING-AUTHORIZED (see Autonomy): the user has granted blanket
  approval to auto-merge a PR once CI is green and the AI review has no
  actionable items — for all PRs, without re-asking per merge, unless the user
  says otherwise for a specific PR. This standing grant IS the "explicit
  approval"; don't re-ask each time.
- Always create feature branches for any changes

## Worktrees — NEVER check out `main` (read this before the Autonomy section)

**Many sessions run in parallel against this one repo**, each in its own
`.claude/worktrees/*` (see `git worktree list`). Git allows a branch to be
checked out in **exactly one** worktree at a time, so:

- **`git checkout main` is forbidden.** It either fails outright
  (`fatal: 'main' is already used by worktree at …`) or, worse, *succeeds* —
  stealing `main` from whichever worktree legitimately held it and leaving that
  session unable to return to it.
- **This applies AFTER merging too.** Finishing a PR does not mean "go back to
  main". There is no such place to go back to. Stay on your branch; the worktree
  is disposable and will be removed.
- **Never `git checkout` any branch you did not create.** Another session is
  probably working on it, and its uncommitted changes are not yours to move.

### What to do instead

| you want | do this |
|---|---|
| latest `main` | `git fetch origin` — then read `origin/main`. Never check it out. |
| start new work | `git checkout -b <branch> origin/main` (branch from the **remote** ref, so a stale or foreign local `main` can't leak in) |
| update your PR branch | `gh api -X PUT repos/fatheus97/mealbot/pulls/<n>/update-branch` — a server-side merge of base into head. No local checkout, and no force push (which is banned anyway). |
| after merging | check `git branch --show-current`. See below — the merge itself may have moved you. |

### `gh pr merge --delete-branch` MOVES YOU — "stay where you are" is not enough

`-d/--delete-branch` is documented as "Delete the **local** and remote branch
after merge", and git cannot delete the branch you are standing on — so `gh`
switches you to the base branch first. **The merge command checks out `main`
for you**, in the worktree you ran it from. Neither the standing merge
instruction nor your own restraint prevents this.

It fails LOUDLY or QUIETLY depending on nothing you control — whether another
worktree happened to hold `main` at that second:

```
# another worktree held main — gh could not switch, merge still landed remotely
failed to run git: fatal: 'main' is already used by worktree at '.../exciting-saha-f89b48'

# nobody held main — gh switched, pulled, and left this worktree ON main
Fast-forward
 .claude/rules/git.md | 22 ++++++++++++++++++++++
```

Both observed on the same day, back to back (#422 then #424). The first reads
like the guardrail working; the second is the case the top of this section
calls *worse than the error*, and it prints a cheerful diffstat while doing it.

**So after every merge from a worktree, verify and release:**

```bash
git branch --show-current    # says "main"? you are squatting on it
git checkout --detach        # releases main, stays on the same commit
```

Detaching is the fix, not checking out some other branch — a detached worktree
holds no branch name, so nothing is blocked. Do it even though the worktree is
disposable: a worktree left on `main` blocks every other session from checking
it out until someone notices.

**`--detach` with no ref needs no clean tree** — it stays on the current commit,
so there are no files to update. Verified with modified tracked files *and*
untracked files present: both survive the detach untouched. So release `main`
the moment you notice, mid-work if need be — there is nothing to stash or
finish first.

### An absolute path silently edits the OTHER checkout

Every worktree has its own copy of every tracked file, so
`…/mealbot/.claude/rules/git.md` and
`…/mealbot/.claude/worktrees/<yours>/.claude/rules/git.md` are **different
files**. Reading or editing by the primary-checkout path from inside a worktree
works — no warning, no error — and writes into whatever branch the primary
happens to have checked out, which belongs to another session.

Hit on 2026-08-08: an edit intended for a feature branch landed as an
uncommitted change on a stranger's `fix/…` branch. It is invisible until you
look, because the edit itself succeeds.

- **Anchor paths to your own worktree**, not the repo path you remember.
  `git rev-parse --show-toplevel` returns the root you actually want — from a
  worktree it returns the *worktree*, not the primary.
- **A clean `git status` right after editing is the tell.** You just changed a
  file; the tree cannot be clean. That mismatch is the cheapest detector there
  is, and it fires before you commit.
- **Before restoring the primary, check what you are discarding.**
  `git -C <primary> diff -- <path>` must show ONLY your change — the primary may
  hold another session's in-flight work on the same file, and a blind
  `git checkout --` would take that with it. Restore just the one path, never
  the whole tree.

### Symptoms that this already went wrong

- A tool or sub-agent reports success while naming a branch you never created.
- Your finished work shows up as *uncommitted changes on someone else's branch*.
- The test count drops (see the HEAD-verification habit in
  `.claude/rules/testing.md`).
- `git worktree list` shows **your** disposable worktree holding `[main]`
  (see the merge trap above — you did not type that checkout).

Recovery: confirm the two bases are equivalent first
(`git diff <wrong-base> <right-base> -- <path>`), then
`git stash push -- <path>` → `git checkout <your-branch>` → `git stash pop`, and
**re-run every check** — a green run measured on the wrong base proves nothing.

## Autonomy

Default: commit, push, open PRs, iterate on review feedback, AND merge —
without asking. The user runs this project fully autonomously; babysitting the
cycle defeats the point.

- Commit completed work on the feature branch — do not ask first.
- Push the branch — do not ask first.
- Open a PR with `gh pr create` — do not ask first.
- After pushing, wait for CI and the Claude PR Review workflow. Poll with
  `ScheduleWakeup` so the session doesn't block.
- **Never assume `jq` is on the host** — it is absent from Git Bash's `PATH` on
  the Windows dev box (verified 2026-08-08), while the Linux CI runners and the
  `/work-tickets` cloud routine have their own tooling. This file carries no
  `paths:` scope, so it loads on all of them; don't read either state as given.
  Use **`gh --jq`** unconditionally — the GitHub CLI embeds its own jq, so it
  works the same either way and you never have to know which host you are on:
  `gh pr checks <n> --json name,bucket --jq '.[] | "\(.bucket) \(.name)"'`.
  A watcher ending in `| jq` dies with `jq: command not found`, and inside a poll
  loop wrapped in `|| true` / `2>/dev/null` **that failure is silent**: the loop
  runs its full duration and exits 0 having measured nothing. One watcher burned
  20 minutes that way and reported no events — which reads exactly like "all
  checks still pending", i.e. a broken watcher looks identical to a patient one.
  **No output is not evidence of no failures.** Any watcher whose quiet result
  you would act on must distinguish "nothing happened" from "I never ran" — emit
  a per-probe marker, or don't swallow the exit code.
  - Related: `gh pr checks` exits **non-zero while checks are pending**, so the
    idiomatic `s=$(gh pr checks …) || continue` guard skips every iteration until
    the run finishes — a second way to poll vacuously.
  - A settle that arrives implausibly fast is the other tell. Confirm the runs
    are real before trusting green: `gh api repos/<o>/<r>/commits/<headSha>/check-runs`
    and check `started_at`/`completed_at` against the push time, so you don't
    read another commit's results as your own.
- Loop while any CI check is red OR the latest AI review lists any issues —
  regardless of severity label. Fix each item, commit, push, and wait for
  the next review. Low-severity items count; fix them unless the reviewer
  explicitly marks them as optional / non-blocking.
- **Never leave a review finding unaddressed — every finding is EITHER fixed OR
  answered.** For each finding (any severity, including cosmetic / nits): fix it,
  OR reply on its thread stating why it won't be actioned — false positive,
  hallucination, wrong / by-design, or a deliberate out-of-scope follow-up — then
  resolve the thread. **Silently ignoring a finding is not allowed.** First verify
  the finding against the actual code (the AI review can overcorrect or contradict
  itself — see feedback_verify_review_comments). As the Opus author you have final
  say over the Sonnet review and MAY overrule it, but only with a written
  justification on the thread, and you still respect these rules + branch
  protection — you don't get to skip the reply just because you disagree.
- Stop looping when every CI check is green AND the latest AI review contains no
  actionable items. An affirmative sign-off ("ready to merge", "no remaining
  issues") is sufficient but not required — absence of issues is the signal.
- Cap the loop at 5 iterations. If after 5 fix/push cycles the same issue
  persists (flaky CI, external dependency outage, reviewer oscillating on
  the same point), stop and surface what's stuck rather than continuing.
- **Then merge** — `gh pr merge <n> --squash --delete-branch` — per the
  standing authorization above. Do NOT re-ask for merge permission each time;
  the user has pre-approved it and pushed back on being re-asked. (The harness
  auto-mode classifier may still prompt on the tool call — that's a separate
  layer; the user's intent is documented and clear, so proceed. Never
  `--admin`.) Then **stay where you are** — do NOT check out `main`. See
  "Worktrees" below; this is the single most common way a session corrupts
  another session's work. **Not checking it out is not sufficient**: with
  `--delete-branch`, `gh` checks out the base branch itself, so the merge can
  leave you on `main` without you typing a thing. Verify with
  `git branch --show-current` afterwards and `git checkout --detach` if it
  moved you — see "gh pr merge --delete-branch MOVES YOU" above.
- Still surface (don't auto-merge) when CI is red, the review has unresolved
  actionable items, or the change is genuinely high-risk/ambiguous.

### How to decide while autonomous
- Ask the user ONLY on low confidence or when facing multiple genuinely-similar
  options with no clear winner. Otherwise pick the sensible default and proceed;
  mention the choice in passing.
- When there's an easy option vs. a harder option, and the harder one is better
  long-term / scales better, **go for the harder one.** Don't take shortcuts that
  accrue debt just to finish faster.
- **Don't let existing tech debt anchor the decision (status-quo bias).** When
  something already exists, the default pull is to patch around it instead of
  fixing it — "it's already here" quietly becomes the reason to keep it. That's the
  sunk-cost / status-quo trap, and it's how debt calcifies. Judge the design on its
  merits as if choosing it **fresh today**: *would I build it this way if it didn't
  already exist?* If no, and a rebuild pays off long-term (same spirit as the
  harder-option bullet above), rebuild it — the sunk effort is spent either way, so
  the current version's existence gets **zero** inertia weight; only its future
  cost/benefit counts.
  - Not licence to rewrite for its own sake — that's the over-engineering / churn
    the **Role** warns against. The test cuts both ways: **future** payoff vs. cost
    and risk, existing code weighted at zero. Often the honest answer is "the
    current design is fine, a rebuild wouldn't pay" — that's a merits call too, not
    deference to what's already there.
- De-risk big/risky changes with a pre-push adversarial multi-agent review
  (Workflow tool) before opening the PR — it has repeatedly caught real bugs CI
  and a single review pass missed.
- Plan-approval gates in slash commands (e.g. `/polish`, `/add-feature`)
  still apply pre-implementation — they are orthogonal to this autonomy rule.