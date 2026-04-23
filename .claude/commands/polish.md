I want to polish an existing part of the project — a bugfix, UX annoyance, or small improvement to an existing feature. This is NOT for adding new features (use /add-feature for that).

Description: $ARGUMENTS

Before writing any code:
1. **Reproduce or clearly describe the current behavior** — for a bug, confirm you can see it. For a QOL issue, describe precisely what's annoying today vs. what it should do.
2. **Find the root cause** — don't patch symptoms. Trace the issue to the actual source file(s) and explain *why* it's happening.
3. **Check for the same pattern elsewhere** — if this problem could exist in other places in the codebase, flag them (even if we only fix this one).
4. **Keep the scope tight** — outline the minimal change needed. No "while I'm here" refactors unless they're strictly necessary.
5. **Ask clarifying questions** if the expected behavior is ambiguous.
6. Show me the plan and wait for my approval.

When implementing:
- Follow all project conventions from CLAUDE.md
- Keep the diff minimal and focused
- If it's a bug: add a regression test so it can't silently come back
- Update or add tests to cover the new behavior
- Update API documentation only if user-facing behavior changed

After implementation, give me:
- A brief before/after summary (what was wrong, what changed)
- Anything I should manually verify (especially UI changes)
- Any side effects or nearby code I should double-check
