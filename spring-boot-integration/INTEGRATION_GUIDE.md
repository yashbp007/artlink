# Spring Boot ↔ Python AI Service — Integration Guide

> **For the backend engineer.** This guide explains exactly how to wire the Python AI service into your Spring Boot codebase for all three services.

---

## 1. Prerequisites

### Add to `pom.xml`

```xml
<!-- WebFlux (WebClient) — for calling the Python AI service -->
<dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-webflux</artifactId>
</dependency>

<!-- Netty (WebClient transport) -->
<dependency>
    <groupId>io.projectreactor.netty</groupId>
    <artifactId>reactor-netty-http</artifactId>
</dependency>
```

### Add to `application.properties`

```properties
# Python AI service URL (change for prod/docker)
ai.service.base-url=http://localhost:8000

# Timeouts — keep read timeout high (models can take 10-60s on first call)
ai.service.timeout.connect-ms=5000
ai.service.timeout.read-ms=60000
```

### Copy these files into your Spring Boot project

```
spring-boot-integration/
  AiServiceConfig.java        → com.yourpackage.integration.AiServiceConfig
  AiServiceClient.java        → com.yourpackage.integration.AiServiceClient
  dto/
    ModerationResult.java     → com.yourpackage.integration.dto.ModerationResult
    TaggingResult.java        → com.yourpackage.integration.dto.TaggingResult
    EmbeddingResult.java      → com.yourpackage.integration.dto.EmbeddingResult
    RecommendationResponse.java → com.yourpackage.integration.dto.RecommendationResponse
```

Update the `package` declarations in each file to match your package structure.

---

## 2. Service 1 — Content Moderation Flow

### Where to use: `ModerationService.java`

```java
@Service
public class ModerationService {

    @Autowired private AiServiceClient aiServiceClient;
    @Autowired private ModerationQueueRepository moderationQueueRepo;
    @Autowired private ModerationResultMongoRepo moderationResultMongoRepo;

    /**
     * Moderate text content and save result to DB.
     * Returns the action: "SAFE", "REVIEW", or "BLOCK"
     */
    public String moderateText(Long userId, String contentType, String text, Long targetId) {
        // 1. Call Python AI service
        ModerationResult result = aiServiceClient
            .moderateText(userId, contentType, text)
            .block();

        // 2. Save to MySQL moderation_queue
        ModerationQueueEntity queue = new ModerationQueueEntity();
        queue.setUserId(userId);
        queue.setTargetType(contentType);       // e.g. "POST_CAPTION"
        queue.setTargetId(targetId);
        queue.setStatus(result.action());       // "SAFE", "REVIEW", or "BLOCK"
        queue.setReason(result.reason());
        queue.setCreatedAt(LocalDateTime.now());
        moderationQueueRepo.save(queue);

        // 3. Save scores to MongoDB moderation_results
        ModerationResultDocument doc = new ModerationResultDocument();
        doc.setTargetType("POST");
        doc.setTargetId(targetId);
        doc.setContentType(contentType);
        doc.setScores(result.scores());
        doc.setAction(result.action());
        doc.setReason(result.reason());
        doc.setCreatedAt(new Date());
        moderationResultMongoRepo.save(doc);

        return result.action();
    }

    /** Same pattern for image — use aiServiceClient.moderateImage() */
}
```

### Moderation decisions in `PostService.java`

```java
String textAction  = moderationService.moderateText(userId, "POST_CAPTION", caption, postId);
String imageAction = hasImage
    ? moderationService.moderateImage(userId, "POST_IMAGE", imageBytes, filename, postId)
    : "SAFE";

// Combine: take the worst action
String finalAction = worstOf(textAction, imageAction);
// worstOf logic: BLOCK > REVIEW > SAFE

switch (finalAction) {
    case "BLOCK"  -> { post.setStatus("BLOCKED");      return blockedResponse(post); }
    case "REVIEW" -> { post.setStatus("NEEDS_REVIEW"); return reviewResponse(post);  }
    case "SAFE"   -> { /* proceed to tagging */ }
}
```

### Admin queue endpoints you need to implement

```
GET  /api/admin/moderation/queue        → SELECT * FROM moderation_queue WHERE status = 'REVIEW'
POST /api/admin/moderation/{id}/approve → UPDATE status = 'APPROVED', reviewed_by, reviewed_at
                                          + UPDATE posts SET status = 'PUBLISHED' WHERE id = targetId
POST /api/admin/moderation/{id}/reject  → UPDATE status = 'REJECTED'
                                          + UPDATE posts SET status = 'BLOCKED' WHERE id = targetId
```

---

## 3. Service 3 — Upload Post With AI Flow

### Full flow in `PostService.java`

```java
public PostResponse createPost(Long userId, String caption, MultipartFile file, String mediaType, String visibility) {

    // ── Step 1: Save post as PENDING ─────────────────────────────────────
    Post post = new Post();
    post.setUserId(userId);
    post.setCaption(caption);
    post.setMediaType(mediaType);
    post.setVisibility(visibility);
    post.setStatus("PENDING_AI_REVIEW");
    post.setCreatedAt(LocalDateTime.now());
    post = postRepository.save(post);                // get generated ID
    Long postId = post.getId();

    byte[] imageBytes = null;
    String filename   = null;
    if (file != null && !file.isEmpty()) {
        imageBytes = file.getBytes();
        filename   = file.getOriginalFilename();
        // Save file to your storage (local disk, S3, etc.)
        String savedPath = storageService.save(imageBytes, filename);
        post.setMediaUrl(savedPath);
        postRepository.save(post);
    }

    // ── Step 2: Text moderation ───────────────────────────────────────────
    String textAction = moderationService.moderateText(userId, "POST_CAPTION", caption, postId);

    // ── Step 3: Image moderation (if image attached) ──────────────────────
    String imageAction = "SAFE";
    if (imageBytes != null) {
        imageAction = moderationService.moderateImage(userId, "POST_IMAGE", imageBytes, filename, postId);
    }

    // ── Step 4: Handle unsafe content ────────────────────────────────────
    String finalAction = worstOf(textAction, imageAction);
    if ("BLOCK".equals(finalAction)) {
        post.setStatus("BLOCKED");
        postRepository.save(post);
        return PostResponse.blocked(post, "Content violates safety rules.");
    }
    if ("REVIEW".equals(finalAction)) {
        post.setStatus("NEEDS_REVIEW");
        postRepository.save(post);
        return PostResponse.pendingReview(post);
    }

    // ── Step 5: Tag content (only for SAFE posts) ─────────────────────────
    TaggingResult tagging = aiServiceClient
        .tagContent(postId, caption, mediaType, imageBytes, filename)
        .block();

    // Save genres to MySQL post_genres
    for (String genreName : tagging.genres()) {
        Genre genre = genreRepository.findByName(genreName).orElse(null);
        if (genre != null) {
            PostGenre pg = new PostGenre(postId, genre.getId(), tagging.confidence());
            postGenreRepository.save(pg);

            // Reinforce user's genre preference
            userGenreRepository.incrementStrength(userId, genre.getId());
        }
    }

    // ── Step 6: Create embedding ──────────────────────────────────────────
    String embeddingText = caption
        + " " + String.join(" ", tagging.tags())
        + " " + String.join(" ", tagging.genres());

    Map<String, Object> embMetadata = Map.of(
        "userId",    userId,
        "genres",    tagging.genres(),
        "tags",      tagging.tags(),
        "createdAt", post.getCreatedAt().toString() + "Z",
        "likes",     0,
        "comments",  0,
        "saves",     0
    );

    EmbeddingResult embedding = aiServiceClient
        .createPostEmbedding(postId, embeddingText, embMetadata)
        .block();

    // ── Step 7: Save AI metadata to MongoDB ───────────────────────────────
    PostAiMetadata aiMeta = new PostAiMetadata();
    aiMeta.setPostId(postId);
    aiMeta.setTags(tagging.tags());
    aiMeta.setGenres(tagging.genres());
    aiMeta.setMood(tagging.mood());
    aiMeta.setArtistCategories(tagging.artistCategories());
    aiMeta.setEmbeddingVectorId(embedding.vectorId());
    aiMeta.setEmbeddingStored(embedding.embeddingStored());
    aiMeta.setCreatedAt(new Date());
    postAiMetadataRepo.save(aiMeta);

    // ── Step 8: Publish post ──────────────────────────────────────────────
    post.setStatus("PUBLISHED");
    post.setPublishedAt(LocalDateTime.now());
    postRepository.save(post);

    return PostResponse.published(post, tagging, "SAFE");
}
```

---

## 4. Service 2 — Feed Recommendation Flow

### In `RecommendationService.java`

```java
@Service
public class RecommendationService {

    @Autowired private AiServiceClient aiServiceClient;
    @Autowired private UserGenreRepository userGenreRepo;
    @Autowired private SearchHistoryMongoRepo searchHistoryRepo;
    @Autowired private UserInteractionRepository interactionRepo;
    @Autowired private PostAiMetadataMongoRepo postAiMetadataRepo;
    @Autowired private PostRepository postRepo;
    @Autowired private FollowRepository followRepo;

    public List<FeedPostDTO> getPersonalizedFeed(Long userId, int page, int limit) {

        // ── Step 1: Load user context from your DBs ────────────────────────

        // Genres from MySQL
        List<String> genres = userGenreRepo
            .findByUserId(userId)
            .stream()
            .map(ug -> genreRepository.findById(ug.getGenreId()).map(Genre::getName).orElse(""))
            .filter(s -> !s.isEmpty())
            .collect(Collectors.toList());

        // Recent searches from MongoDB (last 10)
        List<String> recentSearches = searchHistoryRepo
            .findTop10ByUserIdOrderByCreatedAtDesc(userId)
            .stream()
            .map(SearchHistory::getQuery)
            .collect(Collectors.toList());

        // Tags from liked/saved posts
        List<Long> likedPostIds = interactionRepo
            .findByUserIdAndActionIn(userId, List.of("LIKE", "SAVE"))
            .stream()
            .map(UserInteraction::getTargetId)
            .limit(50)
            .collect(Collectors.toList());
        List<String> likedTags = postAiMetadataRepo
            .findByPostIdIn(likedPostIds)
            .stream()
            .flatMap(m -> m.getTags().stream())
            .distinct()
            .limit(30)
            .collect(Collectors.toList());

        // Followed user IDs
        List<Long> followedUserIds = followRepo
            .findByFollowerId(userId)
            .stream()
            .map(Follow::getFollowedId)
            .collect(Collectors.toList());

        // Already seen post IDs (last 100 VIEW interactions)
        List<Long> seenPostIds = interactionRepo
            .findTop100ByUserIdAndActionOrderByCreatedAtDesc(userId, "VIEW")
            .stream()
            .map(UserInteraction::getTargetId)
            .collect(Collectors.toList());

        // ── Step 2: Call Python AI recommendation service ──────────────────
        RecommendationResponse aiResponse = aiServiceClient.getRecommendations(
            userId, genres, recentSearches, likedTags,
            followedUserIds, seenPostIds, limit
        ).block();

        if (aiResponse == null || aiResponse.recommendations().isEmpty()) {
            // Fallback: return latest published posts
            return postRepo.findLatestPublished(limit)
                .stream().map(FeedPostDTO::from).collect(Collectors.toList());
        }

        // ── Step 3: Fetch full post data using returned IDs ────────────────
        List<Long> rankedPostIds = aiResponse.recommendations()
            .stream()
            .map(RecommendationResponse.RecommendationItem::targetId)
            .collect(Collectors.toList());

        Map<Long, Post> postMap = postRepo.findAllById(rankedPostIds)
            .stream()
            .collect(Collectors.toMap(Post::getId, p -> p));

        Map<Long, PostAiMetadata> metaMap = postAiMetadataRepo.findByPostIdIn(rankedPostIds)
            .stream()
            .collect(Collectors.toMap(PostAiMetadata::getPostId, m -> m));

        // ── Step 4: Build enriched feed (preserve AI rank order) ───────────
        return aiResponse.recommendations().stream()
            .map(rec -> {
                Post post = postMap.get(rec.targetId());
                if (post == null) return null;
                PostAiMetadata meta = metaMap.get(rec.targetId());
                return FeedPostDTO.builder()
                    .post(post)
                    .tags(meta != null ? meta.getTags() : List.of())
                    .genres(meta != null ? meta.getGenres() : List.of())
                    .aiScore(rec.score())
                    .aiReason(rec.reason())       // ← show this in React feed UI
                    .build();
            })
            .filter(Objects::nonNull)
            .collect(Collectors.toList());
    }
}
```

---

## 5. Interaction Tracking (feeds the recommendation system)

Every user action in React should call `POST /api/interactions`.

```java
// In InteractionService.java
@Service
public class InteractionService {

    @Autowired private UserInteractionRepository interactionRepo;

    // Interaction weights (from spec — these are for reference; Python uses them internally)
    private static final Map<String, Integer> WEIGHTS = Map.of(
        "VIEW",           1,
        "LIKE",           3,
        "COMMENT",        5,
        "SAVE",           7,
        "SHARE",          8,
        "FOLLOW",         8,
        "PROFILE_VIEW",   2,
        "COLLAB_REQUEST", 10,
        "SEARCH",         4,
        "NOT_INTERESTED", -5,
        "REPORT",        -20
    );

    public void logInteraction(Long userId, String targetType, Long targetId, String action) {
        UserInteraction interaction = new UserInteraction();
        interaction.setUserId(userId);
        interaction.setTargetType(targetType);   // "POST", "USER", "GIG", "COMMUNITY"
        interaction.setTargetId(targetId);
        interaction.setAction(action);
        interaction.setWeight(WEIGHTS.getOrDefault(action, 0));
        interaction.setCreatedAt(LocalDateTime.now());
        interactionRepo.save(interaction);
    }
}
```

**React should send interactions for:** view, like, save, comment, share, follow, not-interested, report.

---

## 6. Endpoint Reference

| Python Endpoint | Called From | When |
|---|---|---|
| `POST /ai/moderate/text` | `ModerationService` | Before publishing any text |
| `POST /ai/moderate/image` | `ModerationService` | Before publishing any image |
| `POST /ai/tag-content` | `PostService` | After BOTH moderation = SAFE |
| `POST /ai/embeddings/post` | `PostService` | After tagging succeeds |
| `POST /ai/recommend/feed` | `RecommendationService` | When React calls `GET /api/feed` |
| `GET /health` | Startup / health check | Spring Boot startup, monitoring |

---

## 7. Spring Boot Endpoints to Implement

```
POST /api/posts                              → createPost() in PostService
GET  /api/feed                               → getPersonalizedFeed() in RecommendationService
GET  /api/recommendations/artists           → (future)
GET  /api/recommendations/gigs              → (future)
GET  /api/recommendations/collaborations    → (future)
POST /api/interactions                       → logInteraction() in InteractionService
POST /api/search                             → search + save to MongoDB search_history
POST /api/moderation/text                    → proxy to Python (or use directly in PostService)
POST /api/moderation/image                   → proxy to Python (or use directly in PostService)
GET  /api/admin/moderation/queue            → get pending REVIEW items
POST /api/admin/moderation/{id}/approve     → approve and publish
POST /api/admin/moderation/{id}/reject      → reject and block
```

---

## 8. Docker Compose (add to project root `docker-compose.yml`)

```yaml
services:
  ai-service:
    build: ./ai-service-python
    ports:
      - "8000:8000"
    environment:
      - PRELOAD_MODELS=true
      - CHROMA_PERSIST_DIR=/chroma_data
      - MODEL_CACHE_DIR=/model_cache
    volumes:
      - ai_model_cache:/model_cache    # persists HuggingFace models
      - ai_chroma_data:/chroma_data    # persists ChromaDB vectors
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 60s              # give time for model loading

  # your existing spring-boot service:
  backend:
    # ...
    environment:
      - AI_SERVICE_BASE_URL=http://ai-service:8000  # use service name in Docker network
    depends_on:
      ai-service:
        condition: service_healthy

volumes:
  ai_model_cache:
  ai_chroma_data:
```

---

## 9. Architecture Rules (do not violate)

| Rule | ✅ Correct | ❌ Wrong |
|---|---|---|
| Who calls Python | Spring Boot only | React, or direct client |
| Who writes to MySQL | Spring Boot only | Python |
| Who writes to MongoDB | Spring Boot only | Python |
| Who reads/writes ChromaDB | Python only | Spring Boot |
| Who makes publish/block decision | Spring Boot | Python |
| What Python returns | AI results (scores, IDs, tags) | Full post objects |

---

*Questions? Read the Python service source code — every endpoint has detailed comments explaining the exact data flow.*
