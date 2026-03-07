## Testing Standards
- Every PR must include tests for new/changed behavior
- Use pytest for backend, Vitest for frontend
- Test structure: happy path, error cases, edge cases
- Bug fixes start with a failing test that reproduces the bug
- Mock external services (LLM API, external APIs) in tests
- Don't test trivial code (plain models, third-party libs)
- Run tests before committing: docker compose exec backend pytest