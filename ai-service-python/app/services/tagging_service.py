"""
tagging_service.py — AI Content Tagging (Service 3)
====================================================
Generates tags, genres, mood, and artist categories for a post.

For TEXT posts:
  - Keyword matching against genre taxonomy
  - Mood detection via keyword heuristics

For IMAGE posts (when image file is available):
  - CLIP zero-shot classification against art domain prompts
  - CLIP zero-shot for mood and artist category detection
  - Combined with caption text analysis

Spring Boot calls /ai/tag-content AFTER moderation passes.
The returned tags/genres are saved to MongoDB post_ai_metadata
and to MySQL post_genres table by Spring Boot.
"""

import logging
import os
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ─── Singleton CLIP model (shared with image_moderation_service) ─────────────
_clip_model     = None
_clip_processor = None


# ═══════════════════════════════════════════════════════════════════
# ARTIST GENRE TAXONOMY
# ═══════════════════════════════════════════════════════════════════
#
# Mirrors the genres table in MySQL.
# Each domain maps to a list of specific genres the platform supports.
#
GENRE_TAXONOMY: Dict[str, List[str]] = {
    "music":       [
        "hip hop", "rap", "r&b", "soul", "pop", "rock", "indie", "classical",
        "jazz", "electronic", "edm", "lo-fi", "trap", "drill", "afrobeats",
        "metal", "folk", "country", "reggae", "funk", "music production",
        "beat making", "mixing", "mastering", "songwriting",
    ],
    "visual_art":  [
        "digital art", "illustration", "painting", "sketching", "concept art",
        "character design", "ui design", "graphic design", "3d art", "animation",
        "pixel art", "street art", "graffiti", "portrait art", "abstract art",
        "watercolor", "oil painting", "sculpture", "mural",
    ],
    "dance":       [
        "hip hop dance", "classical dance", "bharatnatyam", "contemporary dance",
        "freestyle dance", "breaking", "krump", "waacking", "ballet", "salsa",
        "choreography",
    ],
    "film":        [
        "acting", "film direction", "cinematography", "video editing", "vfx",
        "screenwriting", "documentary", "short film", "youtube",
    ],
    "photography": [
        "portrait photography", "fashion photography", "wedding photography",
        "street photography", "landscape photography", "sports photography",
        "product photography", "wildlife photography",
    ],
    "writing":     [
        "poetry", "lyrics", "creative writing", "storytelling",
        "stand-up comedy", "content creation",
    ],
    "fashion":     [
        "fashion design", "styling", "modeling", "streetwear",
    ],
}

ALL_GENRES: List[str] = [g for gs in GENRE_TAXONOMY.values() for g in gs]

# ─── Mood labels ─────────────────────────────────────────────────────────────
MOOD_LABELS = [
    "focused", "creative", "energetic", "chill", "emotional",
    "hype", "melancholic", "uplifting", "dark", "playful",
    "nostalgic", "peaceful", "raw", "inspirational",
]

# ─── Artist category labels ───────────────────────────────────────────────────
ARTIST_CATEGORY_LABELS = [
    "musician", "producer", "DJ", "singer", "rapper", "visual artist",
    "illustrator", "photographer", "dancer", "choreographer", "filmmaker",
    "actor", "writer", "poet", "designer", "content creator",
]

# ─── CLIP prompts for top-level domain detection ─────────────────────────────
DOMAIN_CLIP_TEMPLATES: Dict[str, str] = {
    "music":       "a music studio, musical instruments, or someone recording music",
    "visual_art":  "an artist painting, drawing, or creating digital artwork",
    "dance":       "a person dancing, a dance performance, or dance practice",
    "film":        "a film set, movie scene, camera crew, or acting performance",
    "photography": "a photographer with a camera, or professional photography setup",
    "writing":     "someone writing poetry, a book, or creative content",
    "fashion":     "fashion design, clothing, modeling, or a runway show",
}

# ─── Keyword hints for mood detection from caption ────────────────────────────
MOOD_KEYWORDS: Dict[str, List[str]] = {
    "focused":       ["focused", "grinding", "working", "creating", "late night", "session", "hustle"],
    "creative":      ["creative", "inspiration", "idea", "design", "making", "crafting", "building"],
    "energetic":     ["hype", "energy", "vibe", "fire", "lit", "banger", "turned up"],
    "chill":         ["chill", "relax", "lo-fi", "lofi", "easy", "calm", "laid back"],
    "emotional":     ["emotional", "feeling", "deep", "heart", "soul", "raw", "vulnerable"],
    "uplifting":     ["uplifting", "positive", "happy", "grateful", "blessed", "thankful"],
    "melancholic":   ["sad", "melancholy", "nostalgic", "remember", "miss", "lonely"],
    "nostalgic":     ["throwback", "memories", "remember when", "old times", "classic"],
    "inspirational": ["inspire", "motivated", "dream", "goal", "vision", "purpose"],
}


# ─── Private helpers ─────────────────────────────────────────────────────────

def _load_clip():
    global _clip_model, _clip_processor
    if _clip_model is None:
        logger.info("[Tagging] Loading CLIP model (openai/clip-vit-base-patch32)...")
        from transformers import CLIPModel, CLIPProcessor
        _clip_model     = CLIPModel.from_pretrained("openai/clip-vit-base-patch32")
        _clip_processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")
        logger.info("[Tagging] CLIP model loaded.")
    return _clip_model, _clip_processor


def _clip_classify_multi(
    image,
    labels: List[str],
    templates: List[str],
) -> List[Tuple[str, float]]:
    """
    Zero-shot multi-class image classification with CLIP.
    Returns list of (label, probability) sorted by probability descending.
    """
    import torch
    model, processor = _load_clip()

    inputs = processor(
        text=templates, images=image,
        return_tensors="pt", padding=True, truncation=True,
    )
    with torch.no_grad():
        outputs = model(**inputs)

    probs = outputs.logits_per_image.softmax(dim=1)[0]
    results = [(labels[i], float(probs[i])) for i in range(len(labels))]
    results.sort(key=lambda x: x[1], reverse=True)
    return results


def _caption_keywords(caption: str) -> List[str]:
    """Return all genre keywords found in the caption text."""
    lower = caption.lower()
    return [g for g in ALL_GENRES if g in lower]


def _caption_domains(caption: str) -> List[str]:
    """Return art domains whose genre keywords appear most in the caption."""
    lower = caption.lower()
    hits  = {
        domain: sum(1 for g in genres if g in lower)
        for domain, genres in GENRE_TAXONOMY.items()
    }
    return [d for d, count in sorted(hits.items(), key=lambda x: x[1], reverse=True) if count > 0]


def _caption_mood(caption: str) -> List[str]:
    lower = caption.lower()
    return [
        mood for mood, kws in MOOD_KEYWORDS.items()
        if any(kw in lower for kw in kws)
    ]


def _fallback_artist_categories(genres: List[str]) -> List[str]:
    """Guess artist categories from detected genres if CLIP is unavailable."""
    genre_set = set(genres)
    if genre_set & {"hip hop", "rap", "music production", "beat making", "mixing"}:
        return ["musician", "producer"]
    if genre_set & {"digital art", "illustration", "painting", "graphic design"}:
        return ["visual artist", "illustrator"]
    if genre_set & {"portrait photography", "fashion photography", "street photography"}:
        return ["photographer"]
    if genre_set & {"hip hop dance", "contemporary dance", "choreography"}:
        return ["dancer", "choreographer"]
    if genre_set & {"acting", "film direction", "cinematography"}:
        return ["filmmaker", "actor"]
    return ["content creator"]


# ─── Public API ──────────────────────────────────────────────────────────────

def tag_content(
    post_id:     int,
    caption:     str,
    media_type:  str,
    image_bytes: Optional[bytes] = None,
) -> Dict:
    """
    Generate tags, genres, mood, and artist categories for a post.

    Args:
        post_id:     Post ID (used only for logging)
        caption:     Post caption text
        media_type:  "IMAGE", "VIDEO", "AUDIO", or "TEXT"
        image_bytes: Raw image bytes (only provided if media_type == "IMAGE")

    Returns:
        {
            "tags":             List[str],   # up to 10 tags
            "genres":           List[str],   # up to 5 genres
            "mood":             List[str],   # up to 3 moods
            "artistCategories": List[str],   # up to 3 categories
            "confidence":       float
        }
    """
    logger.info(f"[Tagging] Tagging post {post_id} | media_type={media_type}")

    # ── Step 1: Text-based analysis (always done) ──────────────────────────
    caption_tags    = _caption_keywords(caption)
    caption_domains = _caption_domains(caption)
    caption_genres  = []
    for domain in caption_domains[:2]:
        caption_genres.extend(GENRE_TAXONOMY[domain][:3])

    mood             = _caption_mood(caption) or ["creative"]
    artist_categories = []
    confidence        = 0.70
    image_genres      = []

    # ── Step 2: CLIP image analysis (only if image is provided) ───────────
    if image_bytes and media_type == "IMAGE":
        try:
            from PIL import Image
            import io
            pil_image = Image.open(io.BytesIO(image_bytes)).convert("RGB")

            # 2a. Detect art domain from image
            domain_labels    = list(DOMAIN_CLIP_TEMPLATES.keys())
            domain_templates = list(DOMAIN_CLIP_TEMPLATES.values())
            domain_results   = _clip_classify_multi(pil_image, domain_labels, domain_templates)

            top_domains = [label for label, score in domain_results if score > 0.12][:2]
            for domain in top_domains:
                image_genres.extend(GENRE_TAXONOMY[domain][:3])

            # 2b. Detect mood from image
            mood_templates = [f"an image with a {m} atmosphere or feeling" for m in MOOD_LABELS]
            mood_results   = _clip_classify_multi(pil_image, MOOD_LABELS, mood_templates)
            image_moods    = [label for label, score in mood_results if score > 0.10][:2]
            mood           = list(dict.fromkeys(mood + image_moods))[:3]

            # 2c. Detect artist categories from image
            cat_templates     = [f"a {cat} working, performing, or creating" for cat in ARTIST_CATEGORY_LABELS]
            cat_results       = _clip_classify_multi(pil_image, ARTIST_CATEGORY_LABELS, cat_templates)
            artist_categories = [label for label, score in cat_results if score > 0.08][:3]

            confidence = 0.86
            logger.info(f"[Tagging] CLIP analysis complete | top_domains={top_domains}")

        except Exception as exc:
            logger.warning(f"[Tagging] CLIP image analysis failed for post {post_id}: {exc} — using text-only fallback")
            confidence = 0.65

    # ── Step 3: Merge and deduplicate ─────────────────────────────────────
    all_genres = list(dict.fromkeys(caption_genres + image_genres))[:5]
    all_tags   = list(dict.fromkeys(caption_tags + all_genres))[:10]

    if not artist_categories:
        artist_categories = _fallback_artist_categories(all_genres)

    return {
        "tags":             all_tags,
        "genres":           all_genres,
        "mood":             list(dict.fromkeys(mood))[:3],
        "artistCategories": artist_categories[:3],
        "confidence":       confidence,
    }


def health_check() -> str:
    try:
        _load_clip()
        return "ok"
    except Exception as e:
        return f"error: {e}"
