---
description: Rules for Dockerfile and docker-compose changes
globs: ["Dockerfile*", "docker-compose*.yml", ".dockerignore"]
---

# Docker Rules

- Always use multi-stage builds for the React frontend
- Backend base image: python:3.11-slim (never full python image)
- Never run as root — add a non-root USER directive
- Pin dependency versions in Dockerfiles
- Use .dockerignore to exclude node_modules, __pycache__, .git
- If user reports slow reloading: check volume mount config first
  (Windows volumes are slow — consider named volumes for node_modules)