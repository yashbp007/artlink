"""
routers/moderation.py — Content Moderation Endpoints (Service 1)
=================================================================
Endpoints:
  POST /ai/moderate/text    ← JSON body
  POST /ai/moderate/image   ← multipart/form-data

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HOW SPRING BOOT SHOULD USE THESE:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. User submits post/comment/bio on React
2. Spring Boot receives the request
3. Spring Boot calls /ai/moderate/text for all text content
4. Spring Boot calls /ai/moderate/image if an image is attached
5. Based on action returned:
     SAFE   → proceed to tagging + embedding + publish
     REVIEW → save post with status=NEEDS_REVIEW, notify admin
     BLOCK  → reject request, return error to React

Spring Boot is responsible for:
  - Saving results to MySQL moderation_queue table
  - Saving results to MongoDB moderation_results collection
  - Making the final PUBLISH / BLOCK / REVIEW decision
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import logging
from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from models.schemas import (
    ImageModerationResponse, ImageModerationScores,
    ModerationAction,
    TextModerationRequest, TextModerationResponse, TextModerationScores,
)
from services import image_moderation_service, text_moderation_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai/moderate", tags=["🛡️  Service 1 — Content Moderation"])


# ─────────────────────────────────────────────────────────────────
# TEXT MODERATION
# ─────────────────────────────────────────────────────────────────

@router.post(
    "/text",
    response_model=TextModerationResponse,
    summary="Moderate text content",
    description=(
        "Analyzes text (caption, comment, bio, etc.) for:\n"
        "- toxicity, hate speech, harassment\n"
        "- sexual content, threats, spam\n\n"
        "Returns SAFE / REVIEW / BLOCK decision with per-category scores."
    ),
)
async def moderate_text(request: TextModerationRequest):
    """
    Called by Spring Boot `ModerationService` before publishing any text.

    Spring Boot sends:
      { userId, contentType, text }

    Python returns:
      { safe, action, scores: { toxicity, hate, harassment, spam, sexual, threat }, reason }

    Spring Boot then:
      1. Saves result to MySQL moderation_queue (status = action)
      2. Saves scores to MongoDB moderation_results
      3. Decides whether to continue (SAFE) or stop (REVIEW/BLOCK)
    """
    logger.info(
        f"[/moderate/text] user={request.userId} "
        f"contentType={request.contentType} textLen={len(request.text)}"
    )
    try:
        scores                  = text_moderation_service.analyze_text(request.text)
        is_safe, action, reason = text_moderation_service.decide_action(scores)

        logger.info(
            f"[/moderate/text] user={request.userId} "
            f"action={action} maxScore={max(scores.values()):.3f}"
        )

        return TextModerationResponse(
            safe=is_safe,
            action=ModerationAction(action),
            scores=TextModerationScores(**scores),
            reason=reason,
        )

    except Exception as e:
        logger.error(f"[/moderate/text] Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Text moderation failed: {e}")


# ─────────────────────────────────────────────────────────────────
# IMAGE MODERATION
# ─────────────────────────────────────────────────────────────────

@router.post(
    "/image",
    response_model=ImageModerationResponse,
    summary="Moderate image content",
    description=(
        "Analyzes an uploaded image for:\n"
        "- explicit / nudity\n"
        "- violence, hate symbols, weapons, graphic content\n\n"
        "Accepts multipart/form-data. Returns SAFE / REVIEW / BLOCK."
    ),
)
async def moderate_image(
    file:        UploadFile = File(...,             description="Image file (jpg, png, webp, gif)"),
    userId:      int        = Form(...,             description="ID of the user uploading the image"),
    contentType: str        = Form("POST_IMAGE",    description="Content type label (e.g. POST_IMAGE)"),
):
    """
    Called by Spring Boot `ModerationService` after receiving an image upload.

    Spring Boot sends:
      multipart/form-data with:
        file        — the image file bytes
        userId      — user ID (int)
        contentType — e.g. "POST_IMAGE"

    Python returns:
      { safe, action, scores: { explicit, violence, hate_symbol, weapon, graphic }, reason }

    Spring Boot then:
      1. Saves result to MySQL moderation_queue
      2. Saves scores to MongoDB moderation_results
      3. Combines with text moderation result to make final decision

    Note: If both text and image moderation pass, Spring Boot proceeds to tagging.
    If either fails, the post is BLOCKED or sent to REVIEW.
    """
    # Validate content type
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(
            status_code=400,
            detail=f"Expected an image file. Got content_type='{file.content_type}'"
        )

    logger.info(
        f"[/moderate/image] user={userId} "
        f"contentType={contentType} filename={file.filename}"
    )

    try:
        image_bytes             = await file.read()
        scores                  = image_moderation_service.analyze_image(image_bytes)
        is_safe, action, reason = image_moderation_service.decide_action(scores)

        logger.info(
            f"[/moderate/image] user={userId} "
            f"action={action} maxScore={max(scores.values()):.3f}"
        )

        return ImageModerationResponse(
            safe=is_safe,
            action=ModerationAction(action),
            scores=ImageModerationScores(**scores),
            reason=reason,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[/moderate/image] Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Image moderation failed: {e}")
