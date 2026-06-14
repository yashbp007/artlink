package com.artistplatform.integration.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import java.util.List;

/**
 * RecommendationResponse + RecommendationItem
 * ─────────────────────────────────────────────────────────────────────────────
 * Maps the response from:
 *   POST /ai/recommend/feed
 *
 * JSON structure:
 * {
 *   "recommendations": [
 *     {
 *       "targetType": "POST",
 *       "targetId":   45,
 *       "score":      91.4,
 *       "reason":     "Matches your hip hop interest. Related to your recent search: 'music producer'"
 *     },
 *     {
 *       "targetType": "POST",
 *       "targetId":   12,
 *       "score":      86.2,
 *       "reason":     "Similar to posts you liked (beats, studio)"
 *     }
 *   ]
 * }
 *
 * Spring Boot usage after receiving this response:
 *
 *   1. Extract post IDs:
 *      List<Long> postIds = result.recommendations().stream()
 *        .map(RecommendationItem::targetId)
 *        .collect(Collectors.toList());
 *
 *   2. Fetch full post objects from MySQL (maintaining order):
 *      List<Post> posts = postRepository.findAllById(postIds);
 *      // Important: re-sort by the AI ranking order, not MySQL default order
 *      Map<Long, Post> postMap = posts.stream()
 *        .collect(Collectors.toMap(Post::getId, p -> p));
 *      List<Post> rankedPosts = postIds.stream()
 *        .map(postMap::get)
 *        .filter(Objects::nonNull)
 *        .collect(Collectors.toList());
 *
 *   3. Fetch AI metadata from MongoDB (optional, for showing tags/genres in UI):
 *      List<PostAiMetadata> metadataList = postAiMetadataRepo.findByPostIdIn(postIds);
 *
 *   4. Attach reason strings from AI response to each post in the feed response:
 *      // The reason is shown to the user: "Recommended because: Matches your hip hop interest"
 *
 *   5. Track that user saw these posts (call POST /api/interactions internally):
 *      For each postId: logInteraction(userId, "POST", postId, "VIEW", weight=1)
 * ─────────────────────────────────────────────────────────────────────────────
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record RecommendationResponse(
    List<RecommendationItem> recommendations
) {
    /** Empty response for error fallback */
    public static RecommendationResponse empty() {
        return new RecommendationResponse(List.of());
    }

    /**
     * A single recommendation item.
     *   targetType: always "POST" for feed recommendations
     *   targetId:   Post ID — use this to fetch full post from MySQL
     *   score:      0–100 AI confidence score (higher = more relevant)
     *   reason:     Human-readable reason shown to user in the feed UI
     */
    @JsonIgnoreProperties(ignoreUnknown = true)
    public record RecommendationItem(
        String targetType,
        long   targetId,
        double score,
        String reason
    ) {}
}
