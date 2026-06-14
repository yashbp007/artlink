package com.artistplatform.integration.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import java.util.List;

/**
 * TaggingResult
 * ─────────────────────────────────────────────────────────────────────────────
 * Maps the response from:
 *   POST /ai/tag-content
 *
 * JSON structure:
 * {
 *   "tags":             ["hip hop", "producer", "beat making", "studio"],
 *   "genres":           ["hip hop", "music production"],
 *   "mood":             ["focused", "creative"],
 *   "artistCategories": ["musician", "producer"],
 *   "confidence":       0.86
 * }
 *
 * Spring Boot usage after receiving this response:
 *
 *   1. Save to MySQL post_genres table:
 *      For each genre in tagging.genres():
 *        - SELECT id FROM genres WHERE name = genre
 *        - INSERT INTO post_genres (post_id, genre_id, confidence)
 *          VALUES (postId, genreId, tagging.confidence())
 *        - UPDATE user_genres SET strength = strength + 1
 *          WHERE user_id = userId AND genre_id = genreId
 *          (reinforces user's genre preference based on what they post)
 *
 *   2. Save to MongoDB post_ai_metadata:
 *      {
 *        postId: postId,
 *        tags:   tagging.tags(),
 *        genres: tagging.genres(),
 *        mood:   tagging.mood(),
 *        artistCategories: tagging.artistCategories(),
 *        moderation: { text: textModerationResult, image: imageModerationResult },
 *        embedding:  { vectorId: null, stored: false },  // filled after embedding step
 *        createdAt:  timestamp
 *      }
 *
 *   3. Build embedding text for next step:
 *      String embText = caption + " "
 *        + String.join(" ", tagging.tags()) + " "
 *        + String.join(" ", tagging.genres());
 *
 *   4. Call /ai/embeddings/post with embText + metadata
 * ─────────────────────────────────────────────────────────────────────────────
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record TaggingResult(
    List<String> tags,
    List<String> genres,
    List<String> mood,
    List<String> artistCategories,
    double       confidence
) {}
