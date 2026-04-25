Review the current codebase for production readiness. CI already enforces pytest, mypy (strict), ruff, eslint, frontend build, and gitleaks on every PR — **do not re-run them**. Read current CI state via `gh run list` if you need it. Focus on what CI cannot catch.

1. **Architecture & code volume** — less code is better.
   - Separation of concerns: business logic leaking into FastAPI route handlers instead of services; ORM calls scattered through services instead of repositories; DB models leaking into response schemas.
   - Module size & cohesion: files doing too much; flag anything that should split.
   - Dead code, unused exports, speculative abstractions, premature generalization.
   - Duplication: grep for existing utilities before accepting a new helper — same rule as `/pr-check`.
   - Hidden behavior / broken invariants: state mutated in surprising places, implicit coupling between layers.
   - Layering violations: frontend reaching past typed API contracts; backend exposing internals through response shapes.

2. **Semantic security** — gitleaks only catches committed secrets. It does not see:
   - SQL injection, XSS, auth/authz bypass, IDOR, path traversal
   - User input used without validation or sanitization
   - Secrets read from env but then logged, echoed in errors, or sent to an LLM

3. **Error handling on external calls** — every DB / LLM / HTTP call needs specific exceptions and an explicit timeout. Bare `except` or missing timeout is a production risk, not a style issue.

4. **Async discipline & performance** — blocking calls inside async endpoints, N+1 queries, missing indexes on filtered columns, unbounded result sets.

5. **Docker hardening** — non-root USER, pinned base images, minimal layers, `.dockerignore` excludes `node_modules` / `__pycache__` / `.git`. Not enforced by CI.

6. **Dependencies** — Dependabot opens bumps but does not gate on CVEs. Flag packages with known vulns, unnecessary libraries, and anything abandoned.

7. **Test-coverage gaps** — which endpoints, services, and business-logic branches have no tests? For each, list what's needed (happy path, error cases, edge cases). This is a qualitative gap analysis, not a coverage percentage.

Output a structured report:
- **CRITICAL** — must fix before deploy
- **WARNING** — should fix soon
- **INFO** — improvement suggestions
- **UNTESTED** — code with no test coverage

For each finding: file path, line number (if applicable), what's wrong, and how to fix it. Be direct and specific — quote `file:line`. If something is a production risk, say so.

Stop at the report. Don't start fixing — I'll pick which findings to act on. If I ask you to write missing tests, follow project conventions (pytest for backend, Vitest for frontend) and prioritize by risk: endpoints and business logic first, utilities last.

$ARGUMENTS
