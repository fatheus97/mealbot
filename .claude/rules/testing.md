## Testing Standards
- Every PR must include tests for new/changed behavior
- Use pytest for backend, Vitest for frontend
- Test structure: happy path, error cases, edge cases
- Bug fixes start with a failing test that reproduces the bug
- Mock external services (LLM API, external APIs) in tests
- Don't test trivial code (plain models, third-party libs)
- Run tests before committing: docker compose exec backend pytest

## A green run is only evidence if you know what it ran against
Sessions run in parallel worktrees and a checkout can move under you (see
`.claude/rules/git.md` → Worktrees), so "all passed" can describe the wrong tree.

- **Watch the test COUNT, not just pass/fail.** It only goes up as the repo
  grows, so FEWER tests than the last run means the tree moved — or that a file
  failed to import and was silently skipped. Reconcile the number before
  claiming a run passed: `pytest --collect-only -q | tail -1`.
- An import-time failure is invisible to a type checker: annotations referencing
  a missing import (`Iterator`, `AsyncGenerator`) raise at COLLECTION time, so
  mypy stays green while the tests never run. The count is the only tell.
- **Negative-control anything you are trusting to fail.** Before concluding a
  guard works, break it on purpose and confirm the check goes red. A control
  that silently did not apply looks identical to a passing test.

### A count drop has a second, benign cause — don't chase a phantom rebase
The rule above says a drop means the tree moved. It can also mean two tools
fought over one container. Three consecutive frontend runs, same tree, same
commit (2026-08-08):

| single `docker run` | result |
|---|---|
| `npm run build` then Vitest | 1102 passed / 85 files |
| `tsc -b --force` then Vitest | **11 files failed to COLLECT, 732 passed** |
| Vitest alone, fresh container | 1102 passed / 85 files |

Every one of the 11 files passed when run standalone. Note the first row —
`npm run build` alongside Vitest was fine — so this is not "two commands is too
many"; `--force` is what's implicated.

**The mechanism was not isolated, and the intuitive guess is wrong.** "`--force`
rewrites files while Vitest reads them" cannot be it: both tsconfigs set
`"noEmit": true`, so `tsc -b` emits nothing, and its only write is a
`tsBuildInfoFile` under `node_modules/`, which the container shadows with the
`mealbot_fe_nm` named volume — never the mounted source tree. Row 1 is the
counterexample: `npm run build` is `tsc -b && vite build`, and `vite build`
*does* write into the bind-mounted tree (`dist/`), yet that run was clean. What
`--force` adds over row 1 is type-check **work**, not writes, so resource
pressure is the surviving candidate. Treat the table as a reproduction recipe,
not an explanation.

What matters is that the signature — a big count drop plus import/collection
failures — is **identical** to the moved-checkout case above, and that is the
expensive misdiagnosis. So:

- Give Vitest its **own** `docker run`. Costs one extra container, removes the
  ambiguity entirely.
- If the count drops anyway, **re-run the suite alone in a clean container
  before** concluding anything about the tree. One command separates the two
  causes; a rebase hunt does not.