---
description: Rules for FastAPI backend code
globs: ["backend/**/*.py", "app/**/*.py"]
---

# FastAPI Rules

- All endpoints must have Pydantic request/response models
- Never use `dict` as a response model — always define a schema
- Async all the way: no sync DB calls inside async endpoints
- Every external API call needs timeout + retry + error handling
- Use dependency injection for DB sessions, auth, etc.
- All path params and query params must be typed
- Use HTTPException with specific status codes, not generic 500s