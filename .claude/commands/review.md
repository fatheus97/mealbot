Review the current codebase for production readiness. Check:

1. **Security:** SQL injection, XSS, auth bypass, exposed secrets, input validation
2. **Error Handling:** Unhandled exceptions, missing try/except on external calls
3. **Type Safety:** Any `Any` types, missing type hints, unvalidated data
4. **Docker:** Root user, unpinned versions, bloated images, missing .dockerignore
5. **Performance:** N+1 queries, missing indexes, blocking calls in async code
6. **Dependencies:** Outdated packages, unnecessary libraries, known CVEs

Output a structured report with:
- **CRITICAL** — must fix before deploy
- **WARNING** — should fix soon
- **INFO** — improvement suggestions

For each finding: file path, line number (if applicable), what's wrong, and how to fix it.

$ARGUMENTS