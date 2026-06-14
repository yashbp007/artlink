"""
main.py — FastAPI Application Entry Point
==========================================
Starts the AI service with all 3 service routers registered.

Run locally (from ai-service-python/ directory):
  uvicorn app.main:app --reload --port 8000

Run via Docker:
  docker compose up ai-service

Interactive API docs (auto-generated):
  http://localhost:8000/docs      ← Swagger UI
  http://localhost:8000/redoc     ← ReDoc

Health check:
  GET http://localhost:8000/health

Spring Boot base URL:
  AI_SERVICE_BASE_URL=http://localhost:8000
  (configure in Spring Boot application.properties / .env)
"""

# ─── Path fix: ensure bare imports (from routers, from services, etc.) work ──
# When uvicorn runs `app.main:app` from ai-service-python/, the `app/` directory
# is not automatically on sys.path. This adds it so submodules resolve correctly.
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import moderation, recommendation, tagging, embeddings  # noqa: E402

# ─── Logging configuration ────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ─── Lifespan: warm up models at startup ─────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Pre-loads AI models at startup so the first API request is fast.
    Without this, first request for each model takes 5-15 seconds.

    Comment out any model you don't want to pre-load (saves startup time).
    """
    logger.info("=" * 60)
    logger.info("Artist Platform AI Service — Starting up")
    logger.info("=" * 60)

    if os.getenv("PRELOAD_MODELS", "true").lower() == "true":
        logger.info("Pre-loading AI models (PRELOAD_MODELS=true)...")

        # 1. Text moderation (Detoxify)
        try:
            from services.text_moderation_service import health_check as tm_health
            status = tm_health()
            logger.info(f"  [Text Moderation] {status}")
        except Exception as e:
            logger.warning(f"  [Text Moderation] Pre-load failed (will lazy-load): {e}")

        # 2. Image moderation + Tagging (CLIP) — same model, load once
        try:
            from services.image_moderation_service import health_check as im_health
            status = im_health()
            logger.info(f"  [Image Moderation / CLIP] {status}")
        except Exception as e:
            logger.warning(f"  [Image Moderation / CLIP] Pre-load failed (will lazy-load): {e}")

        # 3. Embeddings (SentenceTransformers)
        try:
            from services.embedding_service import health_check as emb_health
            status = emb_health()
            logger.info(f"  [Embeddings] {status}")
        except Exception as e:
            logger.warning(f"  [Embeddings] Pre-load failed (will lazy-load): {e}")

        # 4. ChromaDB connection
        try:
            from db.chroma_client import health_check as chroma_health
            status = chroma_health()
            logger.info(f"  [ChromaDB] {status}")
        except Exception as e:
            logger.warning(f"  [ChromaDB] Pre-load failed: {e}")

    else:
        logger.info("PRELOAD_MODELS=false — models will load on first request.")

    logger.info("=" * 60)
    logger.info("AI Service ready! Listening on http://0.0.0.0:8000")
    logger.info("Swagger docs: http://localhost:8000/docs")
    logger.info("=" * 60)

    yield  # application runs here

    logger.info("AI Service shutting down.")


# ─── FastAPI application ──────────────────────────────────────────────────────
app = FastAPI(
    title="Artist Platform — AI Service",
    description=(
        "## Python AI backend for the Artist Social Platform\n\n"
        "Exposes three services:\n\n"
        "**Service 1 — Content Moderation** (`/ai/moderate/*`)\n"
        "- Text moderation: toxicity, hate, harassment, spam, sexual, threat\n"
        "- Image moderation: explicit, violence, hate symbols, weapons, graphic\n\n"
        "**Service 2 — Recommendation** (`/ai/recommend/*`)\n"
        "- Hybrid scoring: genre match + search history + interaction + embedding + freshness + popularity\n\n"
        "**Service 3 — Upload Post with AI** (`/ai/tag-content`, `/ai/embeddings/*`)\n"
        "- Content tagging: tags, genres, mood, artist categories\n"
        "- Embedding creation: stores semantic vectors in ChromaDB\n\n"
        "---\n"
        "React → **Spring Boot** → **This Service**\n\n"
        "React must NEVER call this service directly."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)


# ─── CORS (Spring Boot is the only caller — localhost in dev) ─────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("ALLOWED_ORIGINS", "http://localhost:8080").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Register all service routers ─────────────────────────────────────────────
app.include_router(moderation.router)      # POST /ai/moderate/text, /ai/moderate/image
app.include_router(tagging.router)         # POST /ai/tag-content
app.include_router(embeddings.router)      # POST /ai/embeddings/post
app.include_router(recommendation.router)  # POST /ai/recommend/feed


# ─── Health check ────────────────────────────────────────────────────────────
@app.get("/health", tags=["🩺 Health"], summary="Service health check")
async def health():
    """
    Returns the health status of all AI models and ChromaDB.
    Spring Boot should call this on startup to verify the AI service is ready.
    Also useful for Docker health checks.
    """
    from services.text_moderation_service  import health_check as tm_check
    from services.image_moderation_service import health_check as im_check
    from services.embedding_service        import health_check as emb_check
    from db.chroma_client                  import health_check as chroma_check

    services = {
        "text_moderation":  tm_check(),
        "image_moderation": im_check(),
        "embeddings":       emb_check(),
        "chromadb":         chroma_check(),
    }

    overall = "ok" if all(v == "ok" for v in services.values()) else "degraded"
    return {"status": overall, "services": services, "version": "1.0.0"}


@app.get("/", tags=["🩺 Health"], include_in_schema=False)
async def root():
    return {
        "service": "Artist Platform AI Service",
        "version": "1.0.0",
        "docs":    "/docs",
        "health":  "/health",
    }
