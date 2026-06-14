"""
routers/embeddings.py — Post Embedding Endpoint (Service 3)
===========================================================
Endpoint:
  POST /ai/embeddings/post

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HOW SPRING BOOT SHOULD USE THIS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
This is the LAST step in the post upload flow (Service 3).

Spring Boot PostService calls this AFTER tagging:
  1. Get tags + genres from /ai/tag-content response
  2. Build embedding text:
       text = caption + " " + " ".join(tags) + " " + " ".join(genres)
  3. Call POST /ai/embeddings/post with:
       postId   = post ID
       text     = embedding text (from step 2)
       metadata = {
         userId:    post.userId,
         genres:    taggingResult.genres,
         tags:      taggingResult.tags,
         createdAt: post.createdAt.toISOString(),
         likes:     0,  // always 0 for new posts
         comments:  0,
         saves:     0
       }
  4. Python stores embedding in ChromaDB and returns vectorId
  5. Spring Boot saves vectorId to MongoDB post_ai_metadata.embedding.vectorId
  6. Spring Boot updates post status → PUBLISHED in MySQL

IMPORTANT: The metadata object must be as complete as possible.
           It's used by the recommendation scoring engine WITHOUT
           making additional DB calls. If metadata is missing,
           recommendation quality degrades.

Spring Boot should also call this endpoint when:
  - A post's likes/comments/saves counts are updated significantly
    (e.g., every 100 likes), to keep popularity scores fresh.
    → Call with updated metadata, Python will upsert the vector.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import logging
from fastapi import APIRouter, HTTPException
from models.schemas import PostEmbeddingRequest, PostEmbeddingResponse
from services.embedding_service import store_post_embedding

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai/embeddings", tags=["🔢  Service 3 — Embeddings"])


@router.post(
    "/post",
    response_model=PostEmbeddingResponse,
    summary="Create and store post embedding",
    description=(
        "Creates a semantic embedding vector for a post and stores it in ChromaDB.\n\n"
        "The stored metadata (genres, tags, createdAt, likes, comments, saves) "
        "is used directly by the recommendation engine for scoring — "
        "no additional DB lookups needed at recommendation time."
    ),
)
async def create_post_embedding(request: PostEmbeddingRequest):
    """
    Called by Spring Boot PostService as the final step after tagging.

    Spring Boot sends:
      {
        "postId": 101,
        "text":   "Late night beat session hip hop producer beat making studio",
        "metadata": {
          "userId":    12,
          "genres":    ["hip hop", "music production"],
          "tags":      ["beats", "studio", "producer"],
          "createdAt": "2024-01-15T22:30:00Z",
          "likes":     0,
          "comments":  0,
          "saves":     0
        }
      }

    Python:
      1. Generates 384-dim embedding vector from 'text'
      2. Upserts into ChromaDB post_embeddings collection
         with key "POST_{postId}"
      3. Returns { postId, embeddingStored: true, vectorId: "POST_101" }

    Spring Boot then:
      - Saves vectorId to MongoDB post_ai_metadata.embedding.vectorId
      - Updates MySQL posts.status = 'PUBLISHED'
      - Returns published post to React
    """
    logger.info(f"[/embeddings/post] postId={request.postId} textLen={len(request.text)}")

    if not request.text.strip():
        raise HTTPException(
            status_code=400,
            detail="'text' field cannot be empty. Provide caption + tags + genres."
        )

    try:
        meta_dict = None
        if request.metadata:
            meta_dict = request.metadata.model_dump()

        vector_id = store_post_embedding(
            post_id=request.postId,
            text=request.text,
            metadata=meta_dict,
        )

        logger.info(f"[/embeddings/post] Stored vectorId='{vector_id}' for postId={request.postId}")

        return PostEmbeddingResponse(
            postId=request.postId,
            embeddingStored=True,
            vectorId=vector_id,
        )

    except Exception as e:
        logger.error(f"[/embeddings/post] Error for postId={request.postId}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Embedding creation failed: {e}")
