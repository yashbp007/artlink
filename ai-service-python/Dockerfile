# ─────────────────────────────────────────────────────────────────────────────
# Artist Platform — AI Service Dockerfile
# ─────────────────────────────────────────────────────────────────────────────
# Build:   docker build -t artist-ai-service .
# Run:     docker run -p 8000:8000 artist-ai-service
# Compose: see docker-compose.yml in project root
# ─────────────────────────────────────────────────────────────────────────────

FROM python:3.11-slim

LABEL maintainer="artist-platform"
LABEL description="Python AI Service — Moderation, Tagging, Embeddings, Recommendation"

# ── System dependencies ───────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# ── Working directory ─────────────────────────────────────────────────────────
WORKDIR /app

# ── Install Python dependencies ───────────────────────────────────────────────
# Copy requirements first to leverage Docker layer caching.
# Dependencies are only reinstalled when requirements.txt changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Copy application code ─────────────────────────────────────────────────────
COPY app/ ./app/

# ── Environment variables (override with docker-compose or .env) ──────────────
ENV PORT=8000
ENV PRELOAD_MODELS=true
ENV MODEL_CACHE_DIR=/model_cache
ENV HF_HOME=/model_cache
ENV CHROMA_PERSIST_DIR=/chroma_data

# ── Volumes ───────────────────────────────────────────────────────────────────
# /model_cache  → persists downloaded HuggingFace models (~1.5GB total)
# /chroma_data  → persists ChromaDB post embeddings
VOLUME ["/model_cache", "/chroma_data"]

# ── Port ──────────────────────────────────────────────────────────────────────
EXPOSE 8000

# ── Startup ───────────────────────────────────────────────────────────────────
# --workers 1 is intentional: models are loaded in memory per worker.
# Multiple workers would each load ~1.5GB of models. Use 1 worker + async.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
