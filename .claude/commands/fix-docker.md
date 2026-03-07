Analyze the Docker setup (Dockerfile, docker-compose.yml, .dockerignore) for issues.

Check specifically:
- Is the frontend using multi-stage builds?
- Are base images minimal (slim/alpine)?
- Are containers running as non-root?
- Are volume mounts optimized for Windows? (named volumes for node_modules?)
- Are dependency layers cached properly? (COPY requirements first, then code)
- Is .dockerignore complete?

Fix any issues you find. Explain each change.

$ARGUMENTS