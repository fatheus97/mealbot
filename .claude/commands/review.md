Review the current codebase for production readiness. Check:

1. **Security:** SQL injection, XSS, auth bypass, exposed secrets, input validation
2. **Error Handling:** Unhandled exceptions, missing try/except on external calls
3. **Type Safety:** Any `Any` types, missing type hints, unvalidated data
4. **Docker:** Root user, unpinned versions, bloated images, missing .dockerignore
5. **Performance:** N+1 queries, missing indexes, blocking calls in async code
6. **Dependencies:** Outdated packages, unnecessary libraries, known CVEs
7. **Test Coverage:** Identify all untested endpoints, services, and business logic.
   For each untested area, note what tests are needed (happy path, error cases, edge cases).

Output a structured report with:
- **CRITICAL** — must fix before deploy
- **WARNING** — should fix soon
- **INFO** — improvement suggestions
- **UNTESTED** — code that has no test coverage

For each finding: file path, line number (if applicable), what's wrong, and how to fix it.

After the report, ask me:
"Would you like me to generate the missing tests now?"
If I say yes, create tests following project conventions — pytest for backend, Vitest for frontend.
Prioritize by risk: test endpoints and business logic first, utilities last.

$ARGUMENTS