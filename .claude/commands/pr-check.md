Before this PR is ready to merge, verify:

1. **Tests:** New/changed code has test coverage (happy path + error cases)
   - Only check coverage for files changed in this PR
   - pytest and other test tools are in requirements-dev.txt, NOT requirements.txt
   - The default docker backend container does NOT have test dependencies installed
2. **Types:** Run `docker compose exec backend-dev mypy .` (or whatever your actual command is)
   Fix any mypy errors in files touched by this PR.
   Don't fix mypy errors in unrelated files — that's for the full /project:review.
3. **Lint:** Code follows project conventions
4. **Security:** No hardcoded secrets, input is validated
5. **Docs:** API changes are reflected in docstrings/schemas
6. **Commits:** Clean conventional commit messages

Run the test suite and type checker. Report any failures.
Fix what you can, flag what needs my input.

$ARGUMENTS