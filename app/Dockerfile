# Agent app (FastAPI). Multi-arch: builds on amd64 (dev) and arm64/sbsa (GB10).
FROM python:3.11-slim

WORKDIR /app

# System deps for soundfile (libsndfile) and pillow.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libsndfile1 && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY app ./app

# Core install (no GPU extras here; cuGraph runs in the serving image / host).
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir .

EXPOSE 8000
CMD ["ama", "serve", "--port", "8000"]
