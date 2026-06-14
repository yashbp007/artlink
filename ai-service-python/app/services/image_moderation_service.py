"""
image_moderation_service.py — Image Safety Analysis (Service 1)
===============================================================
Uses CLIP (openai/clip-vit-base-patch32) with zero-shot classification
to detect unsafe image content across 5 categories.

How it works:
  For each safety category, we give CLIP two prompts:
    - positive: "an image showing violence, blood, or physical harm"
    - negative: "a safe, peaceful image"
  CLIP returns a probability distribution. We take the positive probability
  as the risk score for that category.

Categories detected:
  explicit    — nudity, sexual content
  violence    — fighting, blood, physical harm
  hate_symbol — Nazi imagery, extremist symbols
  weapon      — guns, knives, deadly weapons
  graphic     — gore, disturbing content

Decision thresholds (tunable via env vars):
  score ≥ IMAGE_BLOCK_THRESHOLD  → BLOCK
  score ≥ IMAGE_REVIEW_THRESHOLD → REVIEW
  score < IMAGE_REVIEW_THRESHOLD → SAFE
"""

import io
import os
import logging
from typing import Dict, Tuple, Optional

logger = logging.getLogger(__name__)

# ─── Singleton models (lazy-loaded) ──────────────────────────────────────────
_clip_model     = None
_clip_processor = None

# ─── Decision thresholds ─────────────────────────────────────────────────────
BLOCK_THRESHOLD  = float(os.getenv("IMAGE_BLOCK_THRESHOLD",  "0.75"))
REVIEW_THRESHOLD = float(os.getenv("IMAGE_REVIEW_THRESHOLD", "0.50"))

# ─── Zero-shot prompts per safety category ───────────────────────────────────
#
# Each entry is (positive_prompt, negative_prompt).
# CLIP scores are softmax over these two. The positive score = risk score.
#
SAFETY_PROMPTS: Dict[str, Tuple[str, str]] = {
    "explicit": (
        "a sexually explicit image with nudity or pornographic content",
        "a safe, family-friendly, non-sexual image"
    ),
    "violence": (
        "a violent image showing blood, injury, fighting, or physical harm to people",
        "a calm, peaceful, non-violent scene"
    ),
    "hate_symbol": (
        "an image containing hate symbols, Nazi swastika, white supremacist signs, or extremist content",
        "a normal image without any offensive symbols or hateful imagery"
    ),
    "weapon": (
        "an image showing firearms, guns, rifles, knives, or other deadly weapons in a threatening way",
        "an everyday image without any weapons or dangerous items"
    ),
    "graphic": (
        "a graphic or disturbing image with gore, mutilation, or extremely distressing content",
        "a normal, non-disturbing image suitable for all audiences"
    ),
}


# ─── Private helpers ─────────────────────────────────────────────────────────

def _load_clip():
    """Lazy-loads CLIP. Model is shared with tagging_service to avoid double memory usage."""
    global _clip_model, _clip_processor
    if _clip_model is None:
        logger.info("[ImageMod] Loading CLIP model (openai/clip-vit-base-patch32)...")
        from transformers import CLIPModel, CLIPProcessor
        _clip_model     = CLIPModel.from_pretrained("openai/clip-vit-base-patch32")
        _clip_processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")
        logger.info("[ImageMod] CLIP model loaded.")
    return _clip_model, _clip_processor


def _clip_binary_score(image, positive_prompt: str, negative_prompt: str) -> float:
    """
    Returns the probability (0.0–1.0) that the image matches the positive_prompt,
    computed as softmax over [positive_prompt, negative_prompt].
    """
    import torch
    model, processor = _load_clip()

    inputs = processor(
        text=[positive_prompt, negative_prompt],
        images=image,
        return_tensors="pt",
        padding=True,
        truncation=True,
    )
    with torch.no_grad():
        outputs = model(**inputs)

    probs = outputs.logits_per_image.softmax(dim=1)
    return float(probs[0][0])  # probability for positive_prompt


# ─── Public API ──────────────────────────────────────────────────────────────

def analyze_image(image_bytes: bytes) -> Dict[str, float]:
    """
    Analyzes an image for unsafe content across 5 categories.

    Args:
        image_bytes: Raw bytes of the image (jpg, png, webp, etc.)

    Returns:
        Dict with keys: explicit, violence, hate_symbol, weapon, graphic
        All values are floats in [0.0, 1.0].
    """
    from PIL import Image
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")

    scores = {}
    for category, (pos, neg) in SAFETY_PROMPTS.items():
        score = _clip_binary_score(image, pos, neg)
        scores[category] = round(score, 4)
        logger.debug(f"[ImageMod] {category}={score:.4f}")

    return scores


def decide_action(scores: Dict[str, float]) -> Tuple[bool, str, Optional[str]]:
    """
    Given the score dict, decide the moderation action.

    Returns: (is_safe: bool, action: str, reason: str | None)
    """
    max_score = max(scores.values())
    max_key   = max(scores, key=scores.get)

    if max_score >= BLOCK_THRESHOLD:
        return False, "BLOCK",  f"High {max_key} content detected (score: {max_score:.2f})"
    if max_score >= REVIEW_THRESHOLD:
        return False, "REVIEW", f"Possible {max_key} content flagged for review (score: {max_score:.2f})"
    return True, "SAFE", None


def health_check() -> str:
    """Returns 'ok' if CLIP model can be loaded, 'error: ...' otherwise."""
    try:
        _load_clip()
        return "ok"
    except Exception as e:
        return f"error: {e}"
