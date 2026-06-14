"""
schemas.py — All Pydantic request/response models for the AI service.
=====================================================================
This file is the SINGLE SOURCE OF TRUTH for all API contracts.
The Java DTOs in spring-boot-integration/dto/ mirror these models exactly.

Any change here must be reflected in the corresponding Java DTO.
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict
from enum import Enum


# ═══════════════════════════════════════════════════════════════════
# ENUMS
# ═══════════════════════════════════════════════════════════════════

class ContentType(str, Enum):
    POST_CAPTION       = "POST_CAPTION"
    COMMENT            = "COMMENT"
    BIO                = "BIO"
    GIG_DESCRIPTION    = "GIG_DESCRIPTION"
    COLLAB_DESCRIPTION = "COLLAB_DESCRIPTION"


class MediaType(str, Enum):
    IMAGE = "IMAGE"
    VIDEO = "VIDEO"   # future: frame extraction
    AUDIO = "AUDIO"   # future: speech-to-text → moderate transcript
    TEXT  = "TEXT"


class ModerationAction(str, Enum):
    SAFE   = "SAFE"    # publish immediately
    REVIEW = "REVIEW"  # save, wait for admin approval
    BLOCK  = "BLOCK"   # reject content


class TargetType(str, Enum):
    POST      = "POST"
    USER      = "USER"
    GIG       = "GIG"
    COMMUNITY = "COMMUNITY"


# ═══════════════════════════════════════════════════════════════════
# SERVICE 1 — CONTENT MODERATION
# Spring Boot calls these endpoints:
#   POST /ai/moderate/text
#   POST /ai/moderate/image
# ═══════════════════════════════════════════════════════════════════

class TextModerationRequest(BaseModel):
    userId:      int         = Field(..., description="ID of the user submitting content")
    contentType: ContentType = Field(..., description="Type of content being moderated")
    text:        str         = Field(..., min_length=1, description="Text to analyze")

    model_config = {
        "json_schema_extra": {
            "example": {
                "userId": 12,
                "contentType": "POST_CAPTION",
                "text": "Late night beat session in my home studio"
            }
        }
    }


class TextModerationScores(BaseModel):
    toxicity:   float = Field(..., ge=0, le=1)
    hate:       float = Field(..., ge=0, le=1)
    harassment: float = Field(..., ge=0, le=1)
    spam:       float = Field(..., ge=0, le=1)
    sexual:     float = Field(..., ge=0, le=1)
    threat:     float = Field(..., ge=0, le=1)


class TextModerationResponse(BaseModel):
    safe:   bool
    action: ModerationAction
    scores: TextModerationScores
    reason: Optional[str] = None

    model_config = {
        "json_schema_extra": {
            "example": {
                "safe": True,
                "action": "SAFE",
                "scores": {
                    "toxicity": 0.04, "hate": 0.01,
                    "harassment": 0.02, "spam": 0.03,
                    "sexual": 0.01, "threat": 0.0
                },
                "reason": None
            }
        }
    }


class ImageModerationScores(BaseModel):
    explicit:    float = Field(..., ge=0, le=1)
    violence:    float = Field(..., ge=0, le=1)
    hate_symbol: float = Field(..., ge=0, le=1)
    weapon:      float = Field(..., ge=0, le=1)
    graphic:     float = Field(..., ge=0, le=1)


class ImageModerationResponse(BaseModel):
    safe:   bool
    action: ModerationAction
    scores: ImageModerationScores
    reason: Optional[str] = None


# ═══════════════════════════════════════════════════════════════════
# SERVICE 2 — RECOMMENDATION
# Spring Boot calls:
#   POST /ai/recommend/feed
# ═══════════════════════════════════════════════════════════════════

class FeedRecommendationRequest(BaseModel):
    userId:             int       = Field(..., description="ID of the requesting user")
    genres:             List[str] = Field(default_factory=list, description="User genre preferences (from user_genres table)")
    recentSearches:     List[str] = Field(default_factory=list, description="Recent search query strings (from MongoDB search_history)")
    likedTags:          List[str] = Field(default_factory=list, description="Tags from posts user liked/saved (from user_interactions + post_ai_metadata)")
    followedUserIds:    List[int] = Field(default_factory=list, description="IDs of users this user follows")
    alreadySeenPostIds: List[int] = Field(default_factory=list, description="Post IDs already shown (to avoid repeats)")
    limit:              int       = Field(default=20, ge=1, le=100, description="Max recommendations to return")

    model_config = {
        "json_schema_extra": {
            "example": {
                "userId": 12,
                "genres": ["hip hop", "music production"],
                "recentSearches": ["music producer", "rap battle"],
                "likedTags": ["beats", "studio", "producer"],
                "followedUserIds": [4, 8, 20],
                "alreadySeenPostIds": [1, 2, 3],
                "limit": 20
            }
        }
    }


class RecommendationItem(BaseModel):
    targetType: TargetType
    targetId:   int
    score:      float = Field(..., description="Score 0-100")
    reason:     str   = Field(..., description="Human-readable reason for recommendation")


class FeedRecommendationResponse(BaseModel):
    recommendations: List[RecommendationItem]


# ═══════════════════════════════════════════════════════════════════
# SERVICE 3 — UPLOAD POST WITH AI  (Tagging + Embeddings)
# Spring Boot calls, in order:
#   POST /ai/tag-content
#   POST /ai/embeddings/post
# ═══════════════════════════════════════════════════════════════════

class TagContentRequest(BaseModel):
    postId:         int           = Field(..., description="Post ID assigned by Spring Boot")
    caption:        str           = Field(..., description="Post caption text")
    mediaType:      MediaType     = Field(..., description="Type of attached media")
    imageUrlOrPath: Optional[str] = Field(None, description="Local path or URL of image (only for IMAGE type)")

    model_config = {
        "json_schema_extra": {
            "example": {
                "postId": 101,
                "caption": "Late night beat session in my home studio",
                "mediaType": "IMAGE",
                "imageUrlOrPath": "/uploads/posts/101.jpg"
            }
        }
    }


class TagContentResponse(BaseModel):
    tags:             List[str]
    genres:           List[str]
    mood:             List[str]
    artistCategories: List[str]
    confidence:       float


class PostEmbeddingMetadata(BaseModel):
    """
    Rich metadata stored in ChromaDB alongside the embedding vector.
    The recommendation service uses this metadata for scoring WITHOUT
    making any additional DB calls to MySQL or MongoDB.

    Spring Boot MUST populate all fields when calling /ai/embeddings/post.
    """
    userId:    int
    genres:    List[str] = []
    tags:      List[str] = []
    createdAt: str = Field(..., description="ISO 8601 timestamp, e.g. '2024-01-15T22:30:00Z'")
    likes:     int = 0
    comments:  int = 0
    saves:     int = 0


class PostEmbeddingRequest(BaseModel):
    postId:   int                             = Field(..., description="Post ID")
    text:     str                             = Field(..., description="Text to embed: caption + space-separated tags + genres")
    metadata: Optional[PostEmbeddingMetadata] = Field(None, description="Post metadata stored in vector DB for recommendation scoring")

    model_config = {
        "json_schema_extra": {
            "example": {
                "postId": 101,
                "text": "Late night beat session hip hop producer beat making studio",
                "metadata": {
                    "userId": 12,
                    "genres": ["hip hop", "music production"],
                    "tags": ["beats", "studio", "producer", "hip hop"],
                    "createdAt": "2024-01-15T22:30:00Z",
                    "likes": 0, "comments": 0, "saves": 0
                }
            }
        }
    }


class PostEmbeddingResponse(BaseModel):
    postId:          int
    embeddingStored: bool
    vectorId:        str


# ═══════════════════════════════════════════════════════════════════
# HEALTH CHECK
# ═══════════════════════════════════════════════════════════════════

class HealthResponse(BaseModel):
    status:   str
    services: Dict[str, str]
    version:  str
