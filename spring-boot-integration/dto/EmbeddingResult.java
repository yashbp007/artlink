package com.artistplatform.integration.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

/**
 * EmbeddingResult
 * ─────────────────────────────────────────────────────────────────────────────
 * Maps the response from:
 *   POST /ai/embeddings/post
 *
 * JSON structure:
 * {
 *   "postId":          101,
 *   "embeddingStored": true,
 *   "vectorId":        "POST_101"
 * }
 *
 * Spring Boot usage after receiving this response:
 *
 *   1. Update MongoDB post_ai_metadata:
 *      db.post_ai_metadata.updateOne(
 *        { postId: postId },
 *        { $set: {
 *            "embedding.vectorId": result.vectorId(),
 *            "embedding.stored":   result.embeddingStored()
 *          }
 *        }
 *      )
 *
 *   2. Update MySQL posts table:
 *      UPDATE posts SET status = 'PUBLISHED', published_at = NOW()
 *      WHERE id = postId
 *
 *   3. Return the published post to React frontend.
 *
 * Note: vectorId format is always "POST_{postId}" (e.g., "POST_101").
 *       Store this as-is; you don't need to do anything with it on the
 *       Spring Boot side beyond saving it to MongoDB for reference.
 * ─────────────────────────────────────────────────────────────────────────────
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record EmbeddingResult(
    long    postId,
    boolean embeddingStored,
    String  vectorId
) {}
