"""
text_moderation_service.py — Text Safety Analysis (Service 1)
=============================================================
Uses Detoxify (open-source, free) to score text content.

Detoxify raw labels  →  mapped to API scores
────────────────────────────────────────────
toxicity             →  toxicity
identity_attack      →  hate
insult + severe_tox  →  harassment  (max of both)
sexual_explicit +    →  sexual      (max of both)
  obscene
threat               →  threat
rule-based heuristic →  spam        (no ML model for spam; pattern matching)

Decision thresholds (tunable via env vars):
  score ≥ BLOCK_THRESHOLD  → BLOCK
  score ≥ REVIEW_THRESHOLD → REVIEW
  score < REVIEW_THRESHOLD → SAFE
"""

import re
import os
import logging
from typing import Dict, Tuple, Optional

logger = logging.getLogger(__name__)

# ─── Singleton model (lazy-loaded on first request) ──────────────────────────
_detoxify_model = None

# ─── Decision thresholds ─────────────────────────────────────────────────────
BLOCK_THRESHOLD  = float(os.getenv("TEXT_BLOCK_THRESHOLD",  "0.80"))
REVIEW_THRESHOLD = float(os.getenv("TEXT_REVIEW_THRESHOLD", "0.50"))

# ─── Spam detection patterns ─────────────────────────────────────────────────
_SPAM_PATTERNS_RAW = [
    r"\b(click here|buy now|limited offer|free money|winner|prize|claim now|act now)\b",
    r"(https?://[^\s]+\s*){3,}",   # 3 or more URLs in one message
    r"(.)\1{9,}",                   # same character repeated 10+ times
    r"\b(\w+)\b(?:\s+\b\1\b){3,}", # same word repeated 4+ times
    r"[A-Z]{10,}",                  # 10+ consecutive uppercase letters
    r"(\$\d+|\d+\$).{0,20}(guaranteed|easy money|earn|income)",
]
_SPAM_PATTERNS = [re.compile(p, re.IGNORECASE) for p in _SPAM_PATTERNS_RAW]


# ─── Private helpers ─────────────────────────────────────────────────────────

def _load_model():
    """Lazy-loads the Detoxify 'original' model (downloads ~500MB on first run, cached after)."""
    global _detoxify_model
    if _detoxify_model is None:
        logger.info("[TextMod] Loading Detoxify model... (first load ~10s, cached after)")
        from detoxify import Detoxify
        _detoxify_model = Detoxify("original")
        logger.info("[TextMod] Detoxify model loaded.")
    return _detoxify_model


def _spam_score(text: str) -> float:
    """
    Rule-based spam score (0.0–1.0).
    Detoxify doesn't detect spam, so we handle it with heuristics.
    """
    match_count = sum(1 for p in _SPAM_PATTERNS if p.search(text))
    caps_ratio  = sum(1 for c in text if c.isupper()) / max(len(text), 1)

    score = match_count * 0.25
    if caps_ratio > 0.7 and len(text) > 10:
        score += 0.3
    return round(min(score, 1.0), 4)


# ─── Public API ──────────────────────────────────────────────────────────────

def analyze_text(text: str) -> Dict[str, float]:
    """
    Runs Detoxify + spam heuristics on the input text.

    Returns a dict with keys:
        toxicity, hate, harassment, spam, sexual, threat
    All values are floats in [0.0, 1.0].
    """
    model = _load_model()
    raw   = model.predict(text)

    return {
        "toxicity":   round(float(raw["toxicity"]),                                    4),
        "hate":       round(float(raw["identity_attack"]),                             4),
        "harassment": round(max(float(raw["insult"]), float(raw["severe_toxicity"])),  4),
        "spam":       _spam_score(text),
        "sexual":     round(max(float(raw["sexual_explicit"]), float(raw["obscene"])), 4),
        "threat":     round(float(raw["threat"]),                                      4),
    }


def decide_action(scores: Dict[str, float]) -> Tuple[bool, str, Optional[str]]:
    """
    Given the score dict, decide the moderation action.

    Returns: (is_safe: bool, action: str, reason: str | None)
    """
    max_score = max(scores.values())
    max_key   = max(scores, key=scores.get)

    if max_score >= BLOCK_THRESHOLD:
        return False, "BLOCK",  f"High {max_key} detected (score: {max_score:.2f})"
    if max_score >= REVIEW_THRESHOLD:
        return False, "REVIEW", f"Moderate {max_key} flagged for review (score: {max_score:.2f})"
    return True, "SAFE", None


def health_check() -> str:
    """Returns 'ok' if model can be loaded, 'error: ...' otherwise."""
    try:
        _load_model()
        return "ok"
    except Exception as e:
        return f"error: {e}"
