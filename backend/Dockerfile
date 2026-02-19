FROM python:3.11-slim

WORKDIR /app

# 1. Install system tools needed for Postgres and C-extensions
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# 2. Upgrade pip and set a longer timeout for heavy ML packages
RUN pip install --no-cache-dir --upgrade pip && \
    pip config set global.timeout 1000

# 3. Copy only requirements first (Better layer caching)
COPY requirements.txt .

# 4. Install dependencies with high retry/timeout
RUN pip install --no-cache-dir --default-timeout=100 -r requirements.txt

# 5. Copy the rest of the code
COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]