## Git Conventions
- Use conventional commits: feat/fix/refactor/chore/docs/test
- Write clear commit messages explaining WHY, not just what
- One logical change per commit
- Always create feature branches, never commit to main directly
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