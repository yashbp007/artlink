"""
routers/recommendation.py — Feed Recommendation Endpoint (Service 2)
=====================================================================
Endpoint:
  POST /ai/recommend/feed

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HOW SPRING BOOT SHOULD USE THIS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Spring Boot RecommendationService should:

  Step 1 — Gather user context from MySQL/MongoDB:
    a. user genres        → SELECT genre_id FROM user_genres WHERE user_id = ?
                            JOIN genres table to get genre names
    b. recent searches    → MongoDB: search_history.find({ userId: ? })
                            → extract .query strings, last 10
    c. liked tags         → MySQL: SELECT target_id FROM user_interactions
                            WHERE user_id = ? AND action IN ('LIKE','SAVE')
                            → fetch post_ai_metadata from MongoDB for each post_id
                            → collect all tags
    d. followed user IDs  → SELECT followed_id FROM follows WHERE follower_id = ?
    e. already seen IDs   → SELECT target_id FROM user_interactions
                            WHERE user_id = ? AND target_type = 'POST'
                            → last 50–100 IDs

  Step 2 — Call this endpoint with the gathered context

  Step 3 — Receive ranked [ { targetType, targetId, score, reason } ]

  Step 4 — Fetch full post data from MySQL/MongoDB using returned targetIds:
    SELECT * FROM posts WHERE id IN (...)
    + MongoDB: post_ai_metadata.find({ postId: { $in: [...] } })

  Step 5 — Merge and return enriched feed to React (preserving rank order)

IMPORTANT:
  - Python returns ONLY IDs, scores, and reasons.
  - Spring Boot fetches all full post objects.
  - This separation keeps the Python service stateless.

Cold-start (new user, no interactions):
  → Send empty arrays for genres/searches/likedTags
  → Python will still return results based on freshness + popularity
  → Spring Boot can supplement with trending/popular posts
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import logging
from fastapi import APIRouter, HTTPException
from models.schemas import (
    FeedRecommendationRequest, FeedRecommendationResponse,
    RecommendationItem, TargetType,
)
from services import recommendation_service
from services.embedding_service import query_similar_posts

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai/recommend", tags=["🎯  Service 2 — Recommendation"])


@router.post(
    "/feed",
    response_model=FeedRecommendationResponse,
    summary="Get personalized feed recommendations",
    description=(
        "Returns a ranked list of post IDs using the hybrid scoring formula:\n\n"
        "- Genre match     (30%)\n"
        "- Search history  (20%)\n"
        "- Interaction sim (20%)\n"
        "- Embedding sim   (15%)\n"
        "- Freshness       (10%)\n"
        "- Popularity      ( 5%)\n\n"
        "Python returns only IDs + scores. "
        "Spring Boot fetches full post objects using those IDs."
    ),
)
async def recommend_feed(request: FeedRecommendationRequest):
    """
    Spring Boot sends all user context in one request body.
    Python queries ChromaDB + runs scoring. Returns ranked post IDs.

    NOTE: For this to work, posts must be indexed via /ai/embeddings/post
    when they are published. An empty ChromaDB means no recommendations.
    """
    logger.info(
        f"[/recommend/feed] userId={request.userId} "
        f"genres={request.genres} "
        f"searches={len(request.recentSearches)} "
        f"likedTags={len(request.likedTags)} "
        f"seenPosts={len(request.alreadySeenPostIds)} "
        f"limit={request.limit}"
    )

    try:
        # ── Step 1: Build user interest text for ChromaDB query ────────────
        interest_tokens = request.genres + request.likedTags + request.recentSearches
        user_interest_text = " ".join(interest_tokens).strip()

        # ── Step 2: Query ChromaDB for semantically similar posts ──────────
        embedding_results = []
        if user_interest_text:
            fetch_n = request.limit * 4  # fetch extra to allow for filtering
            embedding_results = query_similar_posts(
                query_text=user_interest_text,
                n_results=fetch_n,
                exclude_post_ids=[],  # we penalize seen posts, not exclude them
            )
        else:
            logger.info(f"[/recommend/feed] userId={request.userId}: no interest context — cold start mode")

        # ── Step 3: Build post list from ChromaDB results ──────────────────
        # Each result already has metadata (genres, tags, createdAt, likes, etc.)
        # stored when the post was indexed via /ai/embeddings/post
        posts_for_scoring = [
            {
                "postId":   item["postId"],
                "metadata": item["metadata"],
            }
            for item in embedding_results
        ]

        # ── Step 4: Score and rank posts ───────────────────────────────────
        ranked = recommendation_service.rank_posts(
            user_genres=request.genres,
            recent_searches=request.recentSearches,
            liked_tags=request.likedTags,
            posts=posts_for_scoring,
            embedding_results=embedding_results,
            already_seen_ids=request.alreadySeenPostIds,
            limit=request.limit,
        )

        # ── Step 5: Build response ─────────────────────────────────────────
        recommendations = [
            RecommendationItem(
                targetType=TargetType.POST,
                targetId=item["targetId"],
                score=item["score"],
                reason=item["reason"],
            )
            for item in ranked
        ]

        logger.info(
            f"[/recommend/feed] userId={request.userId} "
            f"→ returned {len(recommendations)} recommendations"
        )

        return FeedRecommendationResponse(recommendations=recommendations)

    except Exception as e:
        logger.error(f"[/recommend/feed] Error for userId={request.userId}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Recommendation failed: {e}")
