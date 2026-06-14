"""
embedding_service.py — Vector Embeddings (Service 3 + Recommendation)
======================================================================
Creates semantic text embeddings using SentenceTransformers and stores
them in ChromaDB. These embeddings are the backbone of the recommendation system.

Flow (called by Spring Boot during post upload):
  1. Post passes moderation → Spring Boot calls /ai/tag-content
  2. Spring Boot calls /ai/embeddings/post with:
       text = caption + " " + " ".join(tags) + " " + " ".join(genres)
       metadata = { userId, genres, tags, createdAt, likes, comments, saves }
  3. Python creates embedding vector and stores it in ChromaDB
  4. Spring Boot stores vectorId in MongoDB post_ai_metadata

Flow (called internally during recommendation):
  1. /ai/recommend/feed receives user interest context
  2. recommendation.py builds a user interest text
  3. query_similar_posts() finds semantically similar post vectors
  4. Recommendation service scores them using stored ChromaDB metadata

Why store metadata in ChromaDB?
  → The recommendation service can score posts without making DB calls
    back to MySQL or MongoDB. Everything it needs is in the vector metadata.
"""

import os
import logging
from typing import Dict, List, Optional

from db.chroma_client import get_collection, POST_EMBEDDINGS_COLLECTION

logger = logging.getLogger(__name__)

# ─── Singleton model ──────────────────────────────────────────────────────────
_sentence_model = None


def _load_model():
    """Lazy-loads SentenceTransformer. Model is ~90MB, fast after first download."""
    global _sentence_model
    if _sentence_model is None:
        model_name = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
        logger.info(f"[Embedding] Loading SentenceTransformer '{model_name}'...")
        from sentence_transformers import SentenceTransformer
        _sentence_model = SentenceTransformer(model_name)
        logger.info("[Embedding] Model loaded.")
    return _sentence_model


# ─── Public API ──────────────────────────────────────────────────────────────

def create_embedding(text: str) -> List[float]:
    """
    Creates a 384-dimension embedding vector for the given text.
    Used by both post indexing and recommendation queries.
    """
    model = _load_model()
    vector = model.encode(text, convert_to_tensor=False)
    return vector.tolist()


def store_post_embedding(
    post_id:  int,
    text:     str,
    metadata: Optional[Dict] = None,
) -> str:
    """
    Creates an embedding for a post and stores it in ChromaDB.

    Args:
        post_id:  Post ID. Vector will be stored as "POST_{post_id}".
        text:     Text to embed. Combine: caption + tags + genres for best results.
                  Example: "Late night beat session hip hop producer beat making studio"
        metadata: Dict with: userId, genres (list), tags (list),
                  createdAt (ISO str), likes, comments, saves.
                  Stored in ChromaDB and used by recommendation scoring.

    Returns:
        vector_id: "POST_{post_id}"
    """
    vector_id = f"POST_{post_id}"
    embedding = create_embedding(text)

    # Flatten list fields to strings — ChromaDB metadata must be scalar
    flat_meta = {"postId": post_id}
    if metadata:
        flat_meta.update({
            "userId":    metadata.get("userId", 0),
            "genres":    ",".join(metadata.get("genres", [])),    # "hip hop,music production"
            "tags":      ",".join(metadata.get("tags", [])),      # "beats,studio,producer"
            "createdAt": metadata.get("createdAt", ""),
            "likes":     metadata.get("likes", 0),
            "comments":  metadata.get("comments", 0),
            "saves":     metadata.get("saves", 0),
        })

    collection = get_collection(POST_EMBEDDINGS_COLLECTION)
    # upsert: safe to call multiple times (e.g., if post is re-indexed after edit)
    collection.upsert(
        ids=[vector_id],
        embeddings=[embedding],
        documents=[text],
        metadatas=[flat_meta],
    )

    logger.info(f"[Embedding] Stored vector '{vector_id}' | text_len={len(text)}")
    return vector_id


def query_similar_posts(
    query_text:       str,
    n_results:        int = 60,
    exclude_post_ids: Optional[List[int]] = None,
) -> List[Dict]:
    """
    Finds posts in ChromaDB whose embeddings are semantically close to query_text.
    Used by the recommendation service.

    Args:
        query_text:       Text representing user's interests.
                          Built from: genres + liked_tags + recent_searches.
        n_results:        How many similar posts to fetch (before filtering).
        exclude_post_ids: Post IDs to exclude (already-seen posts).

    Returns:
        List of dicts, each with:
          postId    (int)   — Post ID
          vectorId  (str)   — "POST_{postId}"
          distance  (float) — Cosine distance (0=identical, 2=opposite)
          metadata  (dict)  — Stored metadata (userId, genres, tags, createdAt, likes, etc.)
    """
    if not query_text.strip():
        logger.warning("[Embedding] query_similar_posts called with empty query text")
        return []

    collection = get_collection(POST_EMBEDDINGS_COLLECTION)
    total = collection.count()
    if total == 0:
        logger.warning("[Embedding] ChromaDB post_embeddings collection is empty. No posts indexed yet.")
        return []

    embedding    = create_embedding(query_text)
    fetch_n      = min(n_results, total)
    exclude_set  = {f"POST_{pid}" for pid in (exclude_post_ids or [])}

    results = collection.query(
        query_embeddings=[embedding],
        n_results=fetch_n,
        include=["distances", "metadatas", "documents"],
    )

    ids       = results.get("ids",       [[]])[0]
    distances = results.get("distances", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]

    items = []
    for vec_id, dist, meta in zip(ids, distances, metadatas):
        if vec_id in exclude_set:
            continue
        post_id = int(vec_id.replace("POST_", ""))

        # Unflatten list fields that were stored as comma-separated strings
        parsed_meta = dict(meta)
        parsed_meta["genres"] = [g for g in parsed_meta.get("genres", "").split(",") if g]
        parsed_meta["tags"]   = [t for t in parsed_meta.get("tags",   "").split(",") if t]

        items.append({
            "postId":   post_id,
            "vectorId": vec_id,
            "distance": round(dist, 4),
            "metadata": parsed_meta,
        })

    logger.info(f"[Embedding] query_similar_posts | query_len={len(query_text)} | found={len(items)}")
    return items


def delete_post_embedding(post_id: int) -> bool:
    """
    Removes a post's embedding from ChromaDB.
    Call this when a post is DELETED or BLOCKED permanently.
    Spring Boot should call /ai/embeddings/post DELETE (future endpoint).
    """
    vector_id  = f"POST_{post_id}"
    collection = get_collection(POST_EMBEDDINGS_COLLECTION)
    try:
        collection.delete(ids=[vector_id])
        logger.info(f"[Embedding] Deleted vector '{vector_id}'")
        return True
    except Exception as e:
        logger.error(f"[Embedding] Failed to delete vector '{vector_id}': {e}")
        return False


def health_check() -> str:
    try:
        _load_model()
        return "ok"
    except Exception as e:
        return f"error: {e}"
