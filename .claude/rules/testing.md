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