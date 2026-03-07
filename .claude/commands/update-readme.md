Update the project's README.md to reflect the current state of the codebase.

Steps:

1. Find the last commit that modified README.md:
   `git log -1 --format="%H %ai" -- README.md`

2. Get all commits since that point:
   `git log <that-hash>..HEAD --oneline --no-merges`

3. Review what actually changed — read the modified files, not just commit messages.
   Understand what features were added, removed, or changed.

4. Update README.md accordingly. Only change sections affected by the new commits.
   Do NOT rewrite sections that are still accurate.
   Do NOT remove content that is still relevant.

Things to keep up to date:
- Project description and features list
- Setup/installation instructions
- Environment variables and configuration
- API endpoints (if applicable)
- Tech stack and dependencies
- Usage examples

Rules:
- Keep the existing structure and tone of the README
- If there is no README.md yet, create one following standard conventions
- Write for someone who has never seen this project before
- Be concise — README is an overview, not full documentation
- If a feature was removed, remove it from the README
- If setup steps changed (new env vars, new dependencies, new Docker config), update them

After updating, show me a summary of what you changed and why.

$ARGUMENTS