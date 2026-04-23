## Git Conventions
- Use conventional commits: feat/fix/refactor/chore/docs/test
- Write clear commit messages explaining WHY, not just what
- One logical change per commit
- main branch is protected — no direct pushes
- All changes go through PRs with squash merge
- Claude Code must NEVER force push or push directly to main
- Claude Code must NEVER merge PRs without explicit approval from me
- Always create feature branches for any changes
```

## Autonomy

Default: commit, push, open PRs, and iterate on review feedback without asking.

- Commit completed work on the feature branch — do not ask first.
- Push the branch — do not ask first.
- Open a PR with `gh pr create` — do not ask first.
- After pushing, wait for CI and the Claude PR Review workflow. Poll with
  `ScheduleWakeup` so the session doesn't block.
- Loop while any CI check is red OR the latest AI review lists any issues —
  regardless of severity label. Fix each item, commit, push, and wait for
  the next review. Low-severity items count; fix them unless the reviewer
  explicitly marks them as optional / non-blocking.
- Stop when every CI check is green AND the latest AI review contains no
  actionable items. An affirmative sign-off ("ready to merge", "no remaining
  issues") is sufficient but not required — absence of issues is the signal.
- Cap the loop at 5 iterations. If after 5 fix/push cycles the same issue
  persists (flaky CI, external dependency outage, reviewer oscillating on
  the same point), stop and surface what's stuck rather than continuing.
- Only then, ask for permission to merge. The merge itself still requires
  explicit user approval — see the hard rule above.
- Plan-approval gates in slash commands (e.g. `/polish`, `/add-feature`)
  still apply pre-implementation — they are orthogonal to this autonomy rule.

## The Full Cycle as a Diagram
```
1. Create a branch from the main (feature/, fix/, refactor/, chore/)
        ↓
2. Build the feature (small commits along the way)
        ↓
3. Push branch → Open PR
        ↓
4. Claude Code reviews the PR
        ↓
5. Fix any issues found
        ↓
6. Squash & merge to main
        ↓
7. Delete the feature branch
        ↓
8. Back to step 1 for the next thing