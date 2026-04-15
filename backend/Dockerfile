FROM python:3.11.12-slim

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
#    of an image layer so rebuilds don't re-download.
RUN mkdir -p /tmp/hf_cache /tmp/fastembed_cache && \
    python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='sentence-transformers/all-MiniLM-L6-v2')" && \
    chown -R appuser:appuser /tmp/hf_cache /tmp/fastembed_cache

# 7. Copy the rest of the code
COPY --chown=appuser:appuser . .

# 8. Switch to non-root user
USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]