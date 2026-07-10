# syntax=docker/dockerfile:1.10
# Digest pinned so the exact same layer contents are built every time —
# tag mutability (even rare on official images) can't invalidate a
# reproducible build. To bump, `docker pull python:<new-tag>` and copy
# the digest from `docker image inspect --format '{{index .RepoDigests 0}}'`.
FROM python:3.14.6-slim@sha256:b877e50bd90de10af8d82c57a022fc2e0dc731c5320d762a27986facfc3355c1

WORKDIR /app

# 1. Install system tools needed for Postgres and C-extensions
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# 2. Upgrade pip and set a longer timeout for heavy ML packages
ENV PIP_ROOT_USER_ACTION=ignore
RUN pip install --no-cache-dir --upgrade pip && \
    pip config set global.timeout 1000

# 3. Copy only requirements first (Better layer caching)
COPY requirements.txt .
COPY requirements-dev.txt .

# 4. Install dependencies (dev deps only when INSTALL_DEV=true)
ARG INSTALL_DEV=false
RUN if [ "$INSTALL_DEV" = "true" ]; then \
        pip install --no-cache-dir --default-timeout=100 -r requirements-dev.txt; \
    else \
        pip install --no-cache-dir --default-timeout=100 -r requirements.txt; \
    fi

# 5. Create a non-root user
RUN adduser --disabled-password --no-create-home appuser

# HuggingFace / fastembed caches. appuser has no $HOME, so pin to /tmp.
# Without this, HF's xet downloader hits Permission denied on first use.
ENV HF_HOME=/tmp/hf_cache \
    FASTEMBED_CACHE_PATH=/tmp/fastembed_cache

# 6. Pre-download the embedding model into the image. Keeps first API call
#    fast (no 30s HuggingFace fetch on cold start) and makes the cache part
#    of an image layer so rebuilds don't re-download. HF_TOKEN is injected
#    via BuildKit secret — never written to image history. Missing token is
#    fine (falls back to anonymous), just louder and rate-limited.
RUN --mount=type=secret,id=hf_token,env=HF_TOKEN \
    mkdir -p /tmp/hf_cache /tmp/fastembed_cache && \
    python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='sentence-transformers/all-MiniLM-L6-v2')" && \
    chown -R appuser:appuser /tmp/hf_cache /tmp/fastembed_cache

# 7. Copy the rest of the code
COPY --chown=appuser:appuser . .

# 8. Switch to non-root user
USER appuser

EXPOSE 8000

# --proxy-headers + --forwarded-allow-ips restrict XFF trust to RFC-1918 ranges
# (compose internal networks). Caddy reaches the backend via the compose bridge
# so its source IP is always in 172.16.0.0/12; locking to private ranges means
# forged X-Forwarded-For from any publicly-routable source is ignored, even if
# the backend port is briefly exposed to the Docker host during debugging.
# Without this, slowapi's IP-based limit on /register, /login, /demo/session
# would see Caddy's container IP instead of the real client.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"]
