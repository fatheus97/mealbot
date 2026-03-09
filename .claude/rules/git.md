## Git Conventions
- Use conventional commits: feat/fix/refactor/chore/docs/test
- Write clear commit messages explaining WHY, not just what
- One logical change per commit
- main branch is protected — no direct pushes
- All changes go through PRs with squash merge
- Claude Code must NEVER force push or push directly to main
- Claude Code must NEVER merge PRs without explicit approval from me
- Always create feature branches for any changes
```

## The Full Cycle as a Diagram
```
1. Create a branch from the main (feature/, fix/, refactor/, chore/)
        ↓
2. Build the feature (small commits along the way)
        ↓
3. Push branch → Open PR
        ↓
4. Claude Code reviews the PR
        ↓
5. Fix any issues found
        ↓
6. Squash & merge to main
        ↓
7. Delete the feature branch
        ↓
8. Back to step 1 for the next thing