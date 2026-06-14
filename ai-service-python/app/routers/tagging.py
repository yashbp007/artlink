"""
routers/tagging.py — Content Tagging Endpoint (Service 3)
==========================================================
Endpoint:
  POST /ai/tag-content

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HOW SPRING BOOT SHOULD USE THIS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Called ONLY after moderation passes (action = SAFE).

Spring Boot PostService flow:
  1. Save post to MySQL with status = PENDING_AI_REVIEW
  2. Call /ai/moderate/text → if SAFE, continue
  3. Call /ai/moderate/image (if image) → if SAFE, continue
  4. Call /ai/tag-content  ← THIS ENDPOINT
  5. Save returned tags/genres to:
       MySQL: post_genres table (post_id, genre_id, confidence)
       MongoDB: post_ai_metadata collection (full tagging result)
  6. Build embedding text = caption + " " + " ".join(tags) + " " + " ".join(genres)
  7. Call /ai/embeddings/post with that text + metadata
  8. Update post status to PUBLISHED in MySQL

For IMAGE posts, Spring Boot should:
  - Read the uploaded file from disk/storage
  - Send caption as JSON + file bytes in multipart/form-data

For TEXT-only posts, Spring Boot should:
  - Set mediaType = "TEXT"
  - imageUrlOrPath = null
  - Python will use text-only analysis
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Note on VIDEO/AUDIO:
  These are placeholder stubs for now. They accept the request,
  run caption-only analysis, and return text-based tags.
  Extension points are clearly marked with TODO comments.
"""

import logging
from typing import Optional
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from models.schemas import TagContentRequest, TagContentResponse, MediaType
from services import tagging_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["🏷️  Service 3 — AI Tagging"])


@router.post(
    "/tag-content",
    response_model=TagContentResponse,
    summary="Generate AI tags for a post",
    description=(
        "Generates tags, genres, mood, and artist categories for a post.\n\n"
        "For IMAGE posts: accepts multipart/form-data with the image file.\n"
        "For TEXT posts: accepts JSON body with caption only."
    ),
)
async def tag_content(
    postId:         int            = Form(...,  description="Post ID (assigned by Spring Boot after DB save)"),
    caption:        str            = Form(...,  description="Post caption text"),
    mediaType:      str            = Form(...,  description="IMAGE | VIDEO | AUDIO | TEXT"),
    imageFile:      Optional[UploadFile] = File(None, description="Image file (only for IMAGE posts)"),
    imageUrlOrPath: Optional[str]  = Form(None, description="Fallback: local path if image already saved to disk"),
):
    """
    Called by Spring Boot PostService after moderation passes.

    Spring Boot sends (multipart/form-data):
      postId         — int
      caption        — string
      mediaType      — "IMAGE" | "TEXT" | "VIDEO" | "AUDIO"
      imageFile      — binary (only if mediaType = IMAGE)

    Python returns:
      {
        "tags":             ["hip hop", "producer", "beat making", "studio"],
        "genres":           ["hip hop", "music production"],
        "mood":             ["focused", "creative"],
        "artistCategories": ["musician", "producer"],
        "confidence":       0.86
      }

    Spring Boot then:
      1. Saves genres to MySQL post_genres: (post_id, genre_id, confidence)
         (look up genre_id from genres table by name)
      2. Saves full result to MongoDB post_ai_metadata.tags / .genres / .mood etc.
      3. Proceeds to /ai/embeddings/post
    """
    logger.info(f"[/tag-content] postId={postId} mediaType={mediaType}")

    try:
        media_type_enum = MediaType(mediaType)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid mediaType: '{mediaType}'. Must be IMAGE, VIDEO, AUDIO, or TEXT.")

    # ── Read image bytes if provided ───────────────────────────────────────
    image_bytes: Optional[bytes] = None

    if media_type_enum == MediaType.IMAGE:
        if imageFile:
            if not imageFile.content_type or not imageFile.content_type.startswith("image/"):
                raise HTTPException(status_code=400, detail="imageFile must be an image.")
            image_bytes = await imageFile.read()
        elif imageUrlOrPath:
            # Fallback: load from local disk path (Spring Boot pre-saved the file)
            try:
                with open(imageUrlOrPath, "rb") as f:
                    image_bytes = f.read()
            except FileNotFoundError:
                logger.warning(f"[/tag-content] Image file not found at '{imageUrlOrPath}'. Falling back to text-only tagging.")

    # ── TODO: VIDEO — extract frames, tag via CLIP ─────────────────────────
    # if media_type_enum == MediaType.VIDEO:
    #     frames = extract_frames(imageUrlOrPath, sample_rate=1)
    #     image_bytes = frames[0]  # tag first keyframe for now

    # ── TODO: AUDIO — transcribe to text, tag via NLP ─────────────────────
    # if media_type_enum == MediaType.AUDIO:
    #     transcript = transcribe_audio(imageUrlOrPath)
    #     caption = caption + " " + transcript

    try:
        result = tagging_service.tag_content(
            post_id=postId,
            caption=caption,
            media_type=mediaType,
            image_bytes=image_bytes,
        )

        logger.info(
            f"[/tag-content] postId={postId} "
            f"genres={result['genres']} confidence={result['confidence']}"
        )

        return TagContentResponse(**result)

    except Exception as e:
        logger.error(f"[/tag-content] Error for postId={postId}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Content tagging failed: {e}")
