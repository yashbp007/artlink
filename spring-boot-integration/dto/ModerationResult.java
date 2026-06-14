package com.artistplatform.integration.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import java.util.Map;

/**
 * ModerationResult
 * ─────────────────────────────────────────────────────────────────────────────
 * Maps the response from:
 *   POST /ai/moderate/text
 *   POST /ai/moderate/image
 *
 * JSON structure (text moderation example):
 * {
 *   "safe":   true,
 *   "action": "SAFE",            // "SAFE" | "REVIEW" | "BLOCK"
 *   "scores": {
 *     "toxicity":   0.04,        // text moderation scores
 *     "hate":       0.01,
 *     "harassment": 0.02,
 *     "spam":       0.03,
 *     "sexual":     0.01,
 *     "threat":     0.00
 *   },
 *   "reason": null               // Non-null if action != SAFE
 * }
 *
 * JSON structure (image moderation example):
 * {
 *   "safe":   false,
 *   "action": "BLOCK",
 *   "scores": {
 *     "explicit":    0.91,       // image moderation scores
 *     "violence":    0.02,
 *     "hate_symbol": 0.01,
 *     "weapon":      0.00,
 *     "graphic":     0.03
 *   },
 *   "reason": "High explicit content detected (score: 0.91)"
 * }
 *
 * Spring Boot usage:
 *   if ("BLOCK".equals(result.action())) { reject post }
 *   if ("REVIEW".equals(result.action())) { set post status = NEEDS_REVIEW }
 *   if ("SAFE".equals(result.action())) { proceed to tagging }
 * ─────────────────────────────────────────────────────────────────────────────
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record ModerationResult(
    boolean safe,
    String  action,       // "SAFE" | "REVIEW" | "BLOCK"
    Map<String, Double> scores,
    String  reason        // null if safe
) {
    /**
     * Fallback result when the AI service is unreachable.
     * Returns SAFE to avoid blocking all posts on AI service downtime.
     * Spring Boot can configure this behavior per business requirements.
     */
    public static ModerationResult fallbackSafe() {
        return new ModerationResult(true, "SAFE", Map.of(), null);
    }

    /** Convenience: is this content blocked? */
    public boolean isBlocked() { return "BLOCK".equals(action); }

    /** Convenience: needs manual review? */
    public boolean needsReview() { return "REVIEW".equals(action); }
}
