package com.artistplatform.integration;

import com.artistplatform.integration.dto.*;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.http.MediaType;
import org.springframework.http.client.MultipartBodyBuilder;
import org.springframework.stereotype.Service;
import org.springframework.web.reactive.function.BodyInserters;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.reactive.function.client.WebClientResponseException;
import reactor.core.publisher.Mono;

import java.util.List;
import java.util.Map;

/**
 * AiServiceClient
 * ──────────────────────────────────────────────────────────────────────────────
 * The ONLY class that talks to the Python AI service.
 *
 * Usage: Inject this into your Spring Boot service classes:
 *   @Autowired private AiServiceClient aiServiceClient;
 *
 * All methods return Mono<T> (reactive, non-blocking).
 * Call .block() if you need a synchronous result, but prefer reactive chains.
 *
 * Covered endpoints:
 *   1. moderateText()       → POST /ai/moderate/text
 *   2. moderateImage()      → POST /ai/moderate/image
 *   3. tagContent()         → POST /ai/tag-content
 *   4. createPostEmbedding()→ POST /ai/embeddings/post
 *   5. getRecommendations() → POST /ai/recommend/feed
 *   6. healthCheck()        → GET  /health
 * ──────────────────────────────────────────────────────────────────────────────
 */
@Service
public class AiServiceClient {

    private static final Logger log = LoggerFactory.getLogger(AiServiceClient.class);

    private final WebClient webClient;

    public AiServiceClient(@Qualifier("aiServiceWebClient") WebClient webClient) {
        this.webClient = webClient;
    }


    // ═══════════════════════════════════════════════════════════════════════
    // SERVICE 1 — CONTENT MODERATION
    // ═══════════════════════════════════════════════════════════════════════

    /**
     * Moderate a text content (caption, comment, bio, etc.).
     *
     * Called by: ModerationService (before publishing any text)
     *
     * @param userId      ID of the user submitting the content
     * @param contentType e.g. "POST_CAPTION", "COMMENT", "BIO", "GIG_DESCRIPTION"
     * @param text        The text to analyze
     * @return Mono<ModerationResult> with: safe, action (SAFE/REVIEW/BLOCK), scores, reason
     *
     * Example usage in ModerationService:
     *   ModerationResult result = aiServiceClient
     *     .moderateText(userId, "POST_CAPTION", caption)
     *     .block();
     *   if (result.action().equals("BLOCK")) { ... }
     */
    public Mono<ModerationResult> moderateText(Long userId, String contentType, String text) {
        Map<String, Object> body = Map.of(
            "userId",      userId,
            "contentType", contentType,
            "text",        text
        );

        log.debug("[AI] POST /ai/moderate/text | userId={} contentType={}", userId, contentType);

        return webClient.post()
            .uri("/ai/moderate/text")
            .contentType(MediaType.APPLICATION_JSON)
            .bodyValue(body)
            .retrieve()
            .bodyToMono(ModerationResult.class)
            .doOnSuccess(r -> log.info("[AI] Text moderation | userId={} action={}", userId, r.action()))
            .doOnError(e -> log.error("[AI] Text moderation failed | userId={} error={}", userId, e.getMessage()))
            .onErrorReturn(WebClientResponseException.class, ModerationResult.fallbackSafe());
    }

    /**
     * Moderate an image upload.
     *
     * Called by: ModerationService (after receiving image in upload request)
     *
     * @param userId      ID of the user uploading the image
     * @param contentType e.g. "POST_IMAGE"
     * @param imageBytes  Raw bytes of the image file
     * @param filename    Original filename (e.g. "photo.jpg") — used for MIME type detection
     * @return Mono<ModerationResult> with: safe, action, scores (explicit, violence, etc.), reason
     *
     * Example usage:
     *   byte[] imageBytes = file.getBytes();
     *   ModerationResult result = aiServiceClient
     *     .moderateImage(userId, "POST_IMAGE", imageBytes, file.getOriginalFilename())
     *     .block();
     */
    public Mono<ModerationResult> moderateImage(
        Long userId, String contentType, byte[] imageBytes, String filename
    ) {
        MultipartBodyBuilder builder = new MultipartBodyBuilder();
        builder.part("userId",      userId.toString());
        builder.part("contentType", contentType);
        builder.part("file", new ByteArrayResource(imageBytes) {
            @Override public String getFilename() { return filename; }
        }).header("Content-Disposition", "form-data; name=\"file\"; filename=\"" + filename + "\"");

        log.debug("[AI] POST /ai/moderate/image | userId={} filename={}", userId, filename);

        return webClient.post()
            .uri("/ai/moderate/image")
            .contentType(MediaType.MULTIPART_FORM_DATA)
            .body(BodyInserters.fromMultipartData(builder.build()))
            .retrieve()
            .bodyToMono(ModerationResult.class)
            .doOnSuccess(r -> log.info("[AI] Image moderation | userId={} action={}", userId, r.action()))
            .doOnError(e -> log.error("[AI] Image moderation failed | userId={} error={}", userId, e.getMessage()))
            .onErrorReturn(WebClientResponseException.class, ModerationResult.fallbackSafe());
    }


    // ═══════════════════════════════════════════════════════════════════════
    // SERVICE 3 — TAGGING (called after moderation passes)
    // ═══════════════════════════════════════════════════════════════════════

    /**
     * Generate AI tags for a post.
     * Call this ONLY after both text and image moderation return SAFE.
     *
     * Called by: PostService (after moderation passes)
     *
     * @param postId    Post ID (must already be saved in MySQL with PENDING_AI_REVIEW status)
     * @param caption   Post caption text
     * @param mediaType "IMAGE", "TEXT", "VIDEO", or "AUDIO"
     * @param imageBytes Raw image bytes (null for TEXT/VIDEO/AUDIO posts)
     * @param filename  Original image filename (null for non-image posts)
     * @return Mono<TaggingResult> with: tags, genres, mood, artistCategories, confidence
     *
     * Example usage:
     *   TaggingResult tagging = aiServiceClient
     *     .tagContent(postId, caption, "IMAGE", imageBytes, filename)
     *     .block();
     *   // Save tagging.genres() to MySQL post_genres table
     *   // Save full tagging result to MongoDB post_ai_metadata
     */
    public Mono<TaggingResult> tagContent(
        Long postId, String caption, String mediaType,
        byte[] imageBytes, String filename
    ) {
        MultipartBodyBuilder builder = new MultipartBodyBuilder();
        builder.part("postId",    postId.toString());
        builder.part("caption",   caption);
        builder.part("mediaType", mediaType);

        if (imageBytes != null && filename != null) {
            builder.part("imageFile", new ByteArrayResource(imageBytes) {
                @Override public String getFilename() { return filename; }
            }).header("Content-Disposition", "form-data; name=\"imageFile\"; filename=\"" + filename + "\"");
        }

        log.debug("[AI] POST /ai/tag-content | postId={} mediaType={}", postId, mediaType);

        return webClient.post()
            .uri("/ai/tag-content")
            .contentType(MediaType.MULTIPART_FORM_DATA)
            .body(BodyInserters.fromMultipartData(builder.build()))
            .retrieve()
            .bodyToMono(TaggingResult.class)
            .doOnSuccess(r -> log.info("[AI] Tagging | postId={} genres={}", postId, r.genres()))
            .doOnError(e -> log.error("[AI] Tagging failed | postId={} error={}", postId, e.getMessage()));
    }


    // ═══════════════════════════════════════════════════════════════════════
    // SERVICE 3 — EMBEDDINGS (called after tagging)
    // ═══════════════════════════════════════════════════════════════════════

    /**
     * Create a semantic embedding for a post and store it in ChromaDB.
     * Call this AFTER tagging, as the final step before publishing.
     *
     * Called by: PostService (after tagContent succeeds)
     *
     * @param postId      Post ID
     * @param embeddingText  caption + " " + String.join(" ", tags) + " " + String.join(" ", genres)
     * @param metadata    Map with: userId, genres (List), tags (List), createdAt (ISO string),
     *                    likes (0), comments (0), saves (0)
     * @return Mono<EmbeddingResult> with: postId, embeddingStored (true), vectorId ("POST_101")
     *
     * Example usage:
     *   String embText = caption + " " + String.join(" ", tags) + " " + String.join(" ", genres);
     *   Map<String, Object> meta = Map.of(
     *     "userId", post.getUserId(),
     *     "genres", tagging.genres(),
     *     "tags",   tagging.tags(),
     *     "createdAt", post.getCreatedAt().toString(),
     *     "likes", 0, "comments", 0, "saves", 0
     *   );
     *   EmbeddingResult embedding = aiServiceClient
     *     .createPostEmbedding(postId, embText, meta)
     *     .block();
     *   // Save embedding.vectorId() to MongoDB post_ai_metadata.embedding.vectorId
     */
    public Mono<EmbeddingResult> createPostEmbedding(
        Long postId, String embeddingText, Map<String, Object> metadata
    ) {
        Map<String, Object> body = Map.of(
            "postId",   postId,
            "text",     embeddingText,
            "metadata", metadata
        );

        log.debug("[AI] POST /ai/embeddings/post | postId={}", postId);

        return webClient.post()
            .uri("/ai/embeddings/post")
            .contentType(MediaType.APPLICATION_JSON)
            .bodyValue(body)
            .retrieve()
            .bodyToMono(EmbeddingResult.class)
            .doOnSuccess(r -> log.info("[AI] Embedding stored | postId={} vectorId={}", postId, r.vectorId()))
            .doOnError(e -> log.error("[AI] Embedding failed | postId={} error={}", postId, e.getMessage()));
    }


    // ═══════════════════════════════════════════════════════════════════════
    // SERVICE 2 — RECOMMENDATION
    // ═══════════════════════════════════════════════════════════════════════

    /**
     * Get personalized feed recommendations for a user.
     *
     * Called by: RecommendationService (when React calls GET /api/feed)
     *
     * Spring Boot must gather all user context BEFORE calling this.
     * See INTEGRATION_GUIDE.md → "Feed Recommendation Flow" for the full flow.
     *
     * @param userId             Requesting user's ID
     * @param genres             User's genre preferences (from MySQL user_genres + genres tables)
     * @param recentSearches     Last 10 search strings (from MongoDB search_history)
     * @param likedTags          Tags from posts user liked/saved (from user_interactions + post_ai_metadata)
     * @param followedUserIds    IDs of users this user follows (from MySQL follows table)
     * @param alreadySeenPostIds Post IDs already shown to this user (from MySQL user_interactions)
     * @param limit              Max recommendations to return (default 20)
     * @return Mono<RecommendationResponse> with: recommendations list of { targetType, targetId, score, reason }
     *
     * After receiving the response:
     *   1. Extract all targetIds
     *   2. SELECT * FROM posts WHERE id IN (targetIds)  [MySQL]
     *   3. Find post_ai_metadata WHERE postId IN (targetIds)  [MongoDB]
     *   4. Merge and return enriched posts to React, preserving rank order
     */
    public Mono<RecommendationResponse> getRecommendations(
        Long userId,
        List<String> genres,
        List<String> recentSearches,
        List<String> likedTags,
        List<Long> followedUserIds,
        List<Long> alreadySeenPostIds,
        int limit
    ) {
        Map<String, Object> body = Map.of(
            "userId",             userId,
            "genres",             genres,
            "recentSearches",     recentSearches,
            "likedTags",          likedTags,
            "followedUserIds",    followedUserIds,
            "alreadySeenPostIds", alreadySeenPostIds,
            "limit",              limit
        );

        log.debug("[AI] POST /ai/recommend/feed | userId={} limit={}", userId, limit);

        return webClient.post()
            .uri("/ai/recommend/feed")
            .contentType(MediaType.APPLICATION_JSON)
            .bodyValue(body)
            .retrieve()
            .bodyToMono(RecommendationResponse.class)
            .doOnSuccess(r -> log.info(
                "[AI] Recommendations | userId={} count={}", userId,
                r.recommendations() != null ? r.recommendations().size() : 0
            ))
            .doOnError(e -> log.error("[AI] Recommendations failed | userId={} error={}", userId, e.getMessage()))
            .onErrorReturn(WebClientResponseException.class, RecommendationResponse.empty());
    }


    // ═══════════════════════════════════════════════════════════════════════
    // HEALTH CHECK
    // ═══════════════════════════════════════════════════════════════════════

    /**
     * Check if the Python AI service is up and all models are loaded.
     * Call this on Spring Boot startup to verify AI service connectivity.
     *
     * @return Mono<Map> with status ("ok" or "degraded") and per-service statuses
     */
    public Mono<Map> healthCheck() {
        return webClient.get()
            .uri("/health")
            .retrieve()
            .bodyToMono(Map.class)
            .doOnSuccess(r -> log.info("[AI] Health check: {}", r.get("status")))
            .doOnError(e -> log.error("[AI] Health check failed: {}", e.getMessage()));
    }
}
