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

## Autonomy

Default: commit, push, open PRs, iterate on review feedback, AND merge —
without asking. The user runs this project fully autonomously; babysitting the
cycle defeats the point.

- Commit completed work on the feature branch — do not ask first.
- Push the branch — do not ask first.
- Open a PR with `gh pr create` — do not ask first.
- After pushing, wait for CI and the Claude PR Review workflow. Poll with
  `ScheduleWakeup` so the session doesn't block.
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
  `--admin`.) Then sync main and move to the next thing.
- Still surface (don't auto-merge) when CI is red, the review has unresolved
  actionable items, or the change is genuinely high-risk/ambiguous.

### How to decide while autonomous
- Ask the user ONLY on low confidence or when facing multiple genuinely-similar
  options with no clear winner. Otherwise pick the sensible default and proceed;
  mention the choice in passing.
- When there's an easy option vs. a harder option, and the harder one is better
  long-term / scales better, **go for the harder one.** Don't take shortcuts that
  accrue debt just to finish faster.
- De-risk big/risky changes with a pre-push adversarial multi-agent review
  (Workflow tool) before opening the PR — it has repeatedly caught real bugs CI
  and a single review pass missed.
- Plan-approval gates in slash commands (e.g. `/polish`, `/add-feature`)
  still apply pre-implementation — they are orthogonal to this autonomy rule.