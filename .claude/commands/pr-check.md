Review this PR before merge. CI already runs pytest, mypy, ruff, eslint, frontend build, and gitleaks — **do not re-run them locally**. Read CI results via `gh pr checks <num>` and report red ones.

Focus on what CI can't check:

1. **CI status** — `gh pr checks <num>`. If any required check is red, stop and surface it before anything else.

2. **Migrations** — if `backend/alembic/versions/` has changes, the PR description MUST include a "Deployment notes" block explicitly mentioning `alembic upgrade head`. Alembic does not auto-run on backend startup in this project. Flag missing callouts.

3. **PR description accuracy** — compare description against the actual diff.
   - Every meaningful change in the diff should be reflected
   - Flag anything in the diff not mentioned (new endpoints, config changes, breaking changes, dependency bumps)
   - Flag anything in the description that no longer matches the code
   - Propose an updated description — don't silently rewrite

4. **Design smells** — scan the diff for violations of CLAUDE.md / `.claude/rules/`:
   - `dict` as a FastAPI response model (must be a Pydantic schema)
   - Sync DB/IO calls inside async endpoints
   - LLM output not parsed through a Pydantic model
   - External calls without timeout + error handling
   - Unvalidated user input / potential injection
   - Duplication of an existing utility (grep for similar helpers before approving new ones)

5. **Test coverage intent** — did the author add/modify tests for the new behavior? Qualitative judgment, not a coverage percentage. Bug fixes must start with a failing test per `.claude/rules/testing.md`.

6. **Commit hygiene** — conventional commits (feat/fix/refactor/chore/docs/test), one logical change, meaningful messages explaining WHY.

Fix what you can, flag what needs my input.

$ARGUMENTS
