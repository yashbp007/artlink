"""
recommendation_service.py — Hybrid Recommendation Scoring (Service 2)
======================================================================
Implements the hybrid scoring formula from the spec:

  final_score =
    genre_match_score         * 0.30   ← how well post genres match user's genres
    + search_history_score    * 0.20   ← do recent searches relate to this post?
    + interaction_similarity  * 0.20   ← do user's liked-post tags overlap?
    + embedding_similarity    * 0.15   ← semantic similarity (ChromaDB cosine distance)
    + freshness_score         * 0.10   ← how recent is this post?
    + popularity_score        * 0.05   ← likes/comments/saves engagement

  Penalties applied after:
    - already_seen_penalty    (90% reduction)

All component scores are 0–100. Final score is 0–100.

This module contains PURE SCORING LOGIC.
It does NOT query any database.
Inputs come from the router (user context from Spring Boot request)
and from ChromaDB query results (from embedding_service.query_similar_posts).
"""

import math
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ─── Formula weights (must sum to 1.0) ───────────────────────────────────────
W_GENRE_MATCH     = 0.30
W_SEARCH_HISTORY  = 0.20
W_INTERACTION_SIM = 0.20
W_EMBEDDING_SIM   = 0.15
W_FRESHNESS       = 0.10
W_POPULARITY      = 0.05

# ─── Interaction weights from spec (used in popularity scoring) ───────────────
INTERACTION_WEIGHTS = {
    "VIEW":           1,
    "LIKE":           3,
    "COMMENT":        5,
    "SAVE":           7,
    "SHARE":          8,
    "FOLLOW":         8,
    "PROFILE_VIEW":   2,
    "COLLAB_REQUEST": 10,
    "SEARCH":         4,
    "NOT_INTERESTED": -5,
    "REPORT":         -20,
}

# ─── Already-seen penalty (multiply final score by this factor) ───────────────
SEEN_PENALTY_FACTOR = 0.10  # 90% reduction → only show re-runs if truly nothing else


# ═══════════════════════════════════════════════════════════════════
# INDIVIDUAL SCORING COMPONENTS
# Each function returns a score in [0, 100].
# ═══════════════════════════════════════════════════════════════════

def _genre_match_score(user_genres: List[str], post_genres: List[str]) -> float:
    """
    Jaccard similarity between user genre preferences and post genres.
    Returns 0–100. Small baseline (20) ensures some discovery.
    """
    if not user_genres or not post_genres:
        return 20.0  # baseline for serendipity / cold-start

    user_set = {g.lower() for g in user_genres}
    post_set = {g.lower() for g in post_genres}

    intersection = len(user_set & post_set)
    union        = len(user_set | post_set)

    jaccard = intersection / union if union > 0 else 0
    return round(jaccard * 100, 2)


def _search_history_score(recent_searches: List[str], post_tags: List[str]) -> float:
    """
    Checks how many user search terms appear in the post's tags.
    Each search is split into words; we look for word-level overlaps.
    Returns 0–100.
    """
    if not recent_searches or not post_tags:
        return 0.0

    post_tag_text = " ".join(post_tags).lower()
    hit_count = 0
    for search in recent_searches:
        words = search.lower().split()
        if any(word in post_tag_text for word in words):
            hit_count += 1

    return round(min(hit_count / len(recent_searches) * 100, 100), 2)


def _interaction_similarity_score(liked_tags: List[str], post_tags: List[str]) -> float:
    """
    Overlap between tags from posts the user liked/saved and this post's tags.
    Represents lightweight collaborative filtering via tag similarity.
    Returns 0–100.
    """
    if not liked_tags or not post_tags:
        return 0.0

    liked_set = {t.lower() for t in liked_tags}
    post_set  = {t.lower() for t in post_tags}

    overlap = len(liked_set & post_set)
    return round(min(overlap / max(len(post_set), 1) * 100, 100), 2)


def _embedding_similarity_score(cosine_distance: Optional[float]) -> float:
    """
    Converts ChromaDB cosine distance to a 0–100 score.
    ChromaDB cosine distance: 0 = identical, 2 = opposite.
    Similarity = 1 - distance (for unit vectors).
    Returns 0–100.
    """
    if cosine_distance is None:
        return 0.0
    similarity = max(0.0, 1.0 - cosine_distance)
    return round(similarity * 100, 2)


def _freshness_score(created_at_iso: Optional[str]) -> float:
    """
    Exponential decay based on post age.
      0h  → ~100
      24h → ~50
      7d  → ~10
      30d → ~2
    Returns 0–100.
    """
    if not created_at_iso:
        return 50.0  # neutral default

    try:
        created_at = datetime.fromisoformat(created_at_iso.replace("Z", "+00:00"))
        age_hours  = (datetime.now(timezone.utc) - created_at).total_seconds() / 3600
        score      = 100 * math.exp(-0.029 * age_hours)  # 24h half-life
        return round(max(score, 0), 2)
    except Exception:
        return 50.0


def _popularity_score(likes: int = 0, comments: int = 0, saves: int = 0) -> float:
    """
    Log-scaled engagement score to prevent viral posts from dominating.
    Uses spec interaction weights for likes/comments/saves.
    Returns 0–100.
    """
    total = (
        likes    * INTERACTION_WEIGHTS["LIKE"]    +
        comments * INTERACTION_WEIGHTS["COMMENT"] +
        saves    * INTERACTION_WEIGHTS["SAVE"]
    )
    # log1p(1000) ≈ 6.9 → ~1000 weighted interactions = 100 score
    return round(min(math.log1p(total) / math.log1p(1000) * 100, 100), 2)


# ═══════════════════════════════════════════════════════════════════
# REASON BUILDER
# ═══════════════════════════════════════════════════════════════════

def _build_reason(
    user_genres:     List[str],
    post_genres:     List[str],
    recent_searches: List[str],
    post_tags:       List[str],
    embedding_score: float,
    liked_tags:      List[str],
) -> str:
    """Builds a human-readable reason string shown in the React feed UI."""
    reasons = []

    genre_overlap = {g.lower() for g in user_genres} & {g.lower() for g in post_genres}
    if genre_overlap:
        reasons.append(f"Matches your {', '.join(list(genre_overlap)[:2])} interest")

    post_tag_text = " ".join(post_tags).lower()
    search_hits   = [s for s in recent_searches if any(w.lower() in post_tag_text for w in s.split())]
    if search_hits:
        reasons.append(f"Related to your recent search: \"{search_hits[0]}\"")

    liked_overlap = {t.lower() for t in liked_tags} & {t.lower() for t in post_tags}
    if liked_overlap:
        reasons.append(f"Similar to posts you liked ({', '.join(list(liked_overlap)[:2])})")

    if embedding_score > 70 and not reasons:
        reasons.append("Highly similar to posts you've engaged with")

    return ". ".join(reasons) if reasons else "Recommended for you based on your profile"


# ═══════════════════════════════════════════════════════════════════
# MAIN PUBLIC API
# ═══════════════════════════════════════════════════════════════════

def rank_posts(
    user_genres:      List[str],
    recent_searches:  List[str],
    liked_tags:       List[str],
    posts:            List[Dict],
    embedding_results: List[Dict],
    already_seen_ids: List[int],
    limit:            int = 20,
) -> List[Dict]:
    """
    Score and rank a list of posts using the hybrid formula.

    Args:
        user_genres:       User's genre preferences (from MySQL user_genres)
        recent_searches:   User's recent search strings (from MongoDB search_history)
        liked_tags:        Tags from posts user liked/saved (from user_interactions + post_ai_metadata)
        posts:             Candidate post dicts from ChromaDB query results.
                           Each dict must have: postId, metadata (genres, tags, createdAt, likes, comments, saves)
        embedding_results: Output from embedding_service.query_similar_posts().
                           Each dict: { postId, distance, metadata }
        already_seen_ids:  Post IDs the user already saw (penalized, not excluded)
        limit:             Max number of recommendations to return

    Returns:
        List of recommendation dicts, sorted by score descending:
          { targetType, targetId, score, reason }
    """
    seen_set      = set(already_seen_ids)
    # Build lookup: postId → cosine distance from ChromaDB
    distance_map  = {item["postId"]: item["distance"] for item in embedding_results}

    scored_posts = []

    for post in posts:
        post_id     = post.get("postId") or post.get("id")
        if post_id is None:
            continue

        meta        = post.get("metadata", post)  # support both ChromaDB result and plain dict
        post_genres = meta.get("genres", [])
        post_tags   = meta.get("tags",   [])
        created_at  = meta.get("createdAt")
        likes       = int(meta.get("likes",    0))
        comments    = int(meta.get("comments", 0))
        saves       = int(meta.get("saves",    0))

        emb_distance = distance_map.get(post_id)
        already_seen = post_id in seen_set

        # ── Compute all components ─────────────────────────────────────────
        g_score   = _genre_match_score(user_genres, post_genres)
        s_score   = _search_history_score(recent_searches, post_tags)
        i_score   = _interaction_similarity_score(liked_tags, post_tags)
        e_score   = _embedding_similarity_score(emb_distance)
        f_score   = _freshness_score(created_at)
        p_score   = _popularity_score(likes, comments, saves)

        final = (
            g_score * W_GENRE_MATCH     +
            s_score * W_SEARCH_HISTORY  +
            i_score * W_INTERACTION_SIM +
            e_score * W_EMBEDDING_SIM   +
            f_score * W_FRESHNESS       +
            p_score * W_POPULARITY
        )

        if already_seen:
            final *= SEEN_PENALTY_FACTOR

        reason = _build_reason(
            user_genres, post_genres,
            recent_searches, post_tags,
            e_score, liked_tags,
        )

        scored_posts.append({
            "targetType": "POST",
            "targetId":   post_id,
            "score":      round(final, 2),
            "reason":     reason,
            # Debug breakdown (remove in production if needed)
            "_debug": {
                "genre": g_score, "search": s_score, "interaction": i_score,
                "embedding": e_score, "freshness": f_score, "popularity": p_score,
            }
        })

    scored_posts.sort(key=lambda x: x["score"], reverse=True)
    return scored_posts[:limit]
