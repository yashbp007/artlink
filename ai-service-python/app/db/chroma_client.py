"""
chroma_client.py — ChromaDB Vector Database Connection
=======================================================
ChromaDB is used ONLY by the Python AI service.
Spring Boot does not touch it directly.

Collections:
  - post_embeddings:   Vector for each published post (used for recommendation)
  - artist_embeddings: Vector for each artist bio (future: artist recommendation)
  - gig_embeddings:    Vector for each gig description (future: gig recommendation)

Data persists on disk at CHROMA_PERSIST_DIR (default: ./chroma_data).
On restart, all indexed posts are still available.
"""

import chromadb
import os
import logging

logger = logging.getLogger(__name__)

# ─── Singleton client (created once on first use) ────────────────────────────
_client: chromadb.ClientAPI | None = None
_collections: dict = {}

# ─── Collection name constants ────────────────────────────────────────────────
# Import these constants wherever you need a collection reference.
POST_EMBEDDINGS_COLLECTION   = "post_embeddings"
ARTIST_EMBEDDINGS_COLLECTION = "artist_embeddings"
GIG_EMBEDDINGS_COLLECTION    = "gig_embeddings"


def get_chroma_client() -> chromadb.ClientAPI:
    """
    Returns the singleton ChromaDB PersistentClient.
    Data is saved to disk, so it survives service restarts.
    """
    global _client
    if _client is None:
        persist_dir = os.getenv("CHROMA_PERSIST_DIR", "./chroma_data")
        os.makedirs(persist_dir, exist_ok=True)
        _client = chromadb.PersistentClient(path=persist_dir)
        logger.info(f"[ChromaDB] Client initialized | persist_dir={persist_dir}")
    return _client


def get_collection(name: str) -> chromadb.Collection:
    """
    Returns a ChromaDB collection by name, creating it if it doesn't exist.
    Uses cosine similarity (best for SentenceTransformer embeddings).
    """
    global _collections
    if name not in _collections:
        client = get_chroma_client()
        _collections[name] = client.get_or_create_collection(
            name=name,
            metadata={"hnsw:space": "cosine"}
        )
        logger.info(f"[ChromaDB] Collection '{name}' ready | count={_collections[name].count()}")
    return _collections[name]


def health_check() -> str:
    """Returns 'ok' if ChromaDB is reachable, 'error: ...' otherwise."""
    try:
        client = get_chroma_client()
        client.heartbeat()
        return "ok"
    except Exception as e:
        return f"error: {e}"
