# Artist Social Platform AI Services Build Spec

Build a web application for artists, similar to LinkedIn + Instagram, but focused specifically on artist discovery, portfolios, collaboration, gigs, and recommendations.

The project should focus now on three AI/backend services:

1. Content Filtering for text and images
2. Recommendation System
3. Basic Flow: Upload Post With AI

## Existing Product Requirements

- Platform type: Web application
- Frontend: React
- Main backend: Spring Boot
- AI backend: Python service
- Databases: MySQL, MongoDB, localStorage
- User types: all kinds of artists
- Recommendation targets: posts, artists, gigs, collaborations, communities
- Media uploads: images, videos, audio, and text
- AI features needed:
  - Personalized feed recommendation
  - AI search
  - AI profile builder
  - AI post caption generator
  - AI content tagging
  - Collaboration matching
  - AI portfolio review
  - Content filtering/moderation
  - AI assistant

For this build, implement the foundation for content filtering, recommendation, and upload-post-with-AI flow.

## High-Level Architecture

Use three main layers:

```text
React Frontend
   |
Spring Boot Main Backend
   |
Python AI Service
   |
MySQL + MongoDB + Vector DB
```

React should call only the Spring Boot backend. React should not directly call the Python AI service.

Spring Boot should be the main application backend. It handles users, posts, authentication, uploads, comments, likes, follows, recommendations API, and moderation decisions.

Python should expose AI endpoints for moderation, image analysis, text analysis, content tagging, embeddings, and recommendation scoring.

## Recommended Project Structure

```text
artist-social-platform/
  frontend/
    React app

  backend-spring/
    Spring Boot main backend

  ai-service-python/
    FastAPI AI service

  docker-compose.yml
```

## Technology Requirements

Frontend:

```text
React
Axios or fetch API
React Router
State management as needed
```

Spring Boot:

```text
Spring Boot REST API
Spring Security / JWT auth
Spring Data JPA for MySQL
Spring Data MongoDB for MongoDB
WebClient for calling Python AI service
Multipart file upload support
```

Python AI service:

```text
FastAPI
Pydantic
SentenceTransformers for embeddings
Detoxify or similar free/open text moderation model
CLIP or similar image-text model for image tagging
Optional Hugging Face models/APIs
```

Databases:

```text
MySQL: users, follows, likes, posts, comments, genres, collaboration requests
MongoDB: AI metadata, moderation results, search history, flexible media metadata
Vector DB: Chroma or Qdrant for embeddings and semantic recommendation/search
localStorage: frontend-only non-sensitive state
```

Do not store sensitive data in localStorage. Do not store JWT refresh tokens, passwords, personal user data, or private messages in localStorage.

## Service 1: Content Filtering

Implement content filtering for:

- Post text/captions
- Comments
- Artist bios
- Collaboration/gig descriptions
- Uploaded images

Future support should allow:

- Video moderation by extracting frames
- Audio moderation by transcribing audio and checking the transcript

### Content Filtering Flow

```text
React submits content
   |
Spring Boot receives request
   |
Spring Boot calls Python AI moderation endpoint
   |
Python checks text and/or image
   |
Python returns moderation result
   |
Spring Boot decides:
   - publish
   - block
   - send to manual review
```

### Moderation Actions

Use these moderation actions:

```text
SAFE: publish immediately
REVIEW: save but do not publish until admin approval
BLOCK: reject content
```

### Text Moderation Categories

Detect:

```text
toxicity
hate speech
harassment
sexual content
spam
scam
threats
self-harm
abusive language
```

### Image Moderation Categories

Detect:

```text
explicit/nudity
violence
hate symbols
weapons
graphic content
spam-like content
unsafe content
```

### Python Endpoint: Text Moderation

Endpoint:

```http
POST /ai/moderate/text
```

Request:

```json
{
  "userId": 12,
  "contentType": "POST_CAPTION",
  "text": "uploaded caption or comment text"
}
```

Response:

```json
{
  "safe": true,
  "action": "SAFE",
  "scores": {
    "toxicity": 0.04,
    "hate": 0.01,
    "harassment": 0.02,
    "spam": 0.03,
    "sexual": 0.01,
    "threat": 0.0
  },
  "reason": null
}
```

If blocked:

```json
{
  "safe": false,
  "action": "BLOCK",
  "scores": {
    "toxicity": 0.92,
    "hate": 0.71,
    "harassment": 0.84,
    "spam": 0.14,
    "sexual": 0.05,
    "threat": 0.22
  },
  "reason": "High toxicity and harassment detected"
}
```

### Python Endpoint: Image Moderation

Endpoint:

```http
POST /ai/moderate/image
```

Use multipart/form-data:

```text
file: image file
userId: user id
contentType: POST_IMAGE
```

Response:

```json
{
  "safe": true,
  "action": "SAFE",
  "scores": {
    "explicit": 0.02,
    "violence": 0.01,
    "hate_symbol": 0.0,
    "weapon": 0.0,
    "graphic": 0.01
  },
  "reason": null
}
```

### Spring Boot Endpoints For Moderation

Spring Boot should expose:

```http
POST /api/moderation/text
POST /api/moderation/image
GET /api/admin/moderation/queue
POST /api/admin/moderation/{id}/approve
POST /api/admin/moderation/{id}/reject
```

Spring Boot should save all moderation results.

### MySQL Table: moderation_queue

```text
id
user_id
target_type
target_id
content_type
status: SAFE / REVIEW / BLOCKED / APPROVED / REJECTED
reason
created_at
reviewed_at
reviewed_by
```

### MongoDB Collection: moderation_results

```json
{
  "targetType": "POST",
  "targetId": 101,
  "contentType": "POST_CAPTION",
  "scores": {
    "toxicity": 0.04,
    "hate": 0.01
  },
  "action": "SAFE",
  "reason": null,
  "model": "detoxify-or-selected-model",
  "createdAt": "timestamp"
}
```

## Service 2: Recommendation System

Build a recommendation system for:

- Feed posts
- Artists to follow
- Gigs/opportunities
- Collaboration matches
- Communities

Start with a hybrid recommendation system:

```text
rule-based scoring + user behavior + genre matching + search history + embeddings
```

### Data To Track

Track all important user interactions:

```text
view post
like post
save post
comment
share
follow artist
search query
profile view
send collaboration request
skip/not interested
report
```

### Interaction Weights

Use these starting weights:

```text
VIEW = 1
LIKE = 3
COMMENT = 5
SAVE = 7
SHARE = 8
FOLLOW = 8
PROFILE_VIEW = 2
COLLAB_REQUEST = 10
SEARCH = 4
NOT_INTERESTED = -5
REPORT = -20
```

### MySQL Table: user_interactions

```text
id
user_id
target_type: POST / USER / GIG / COMMUNITY
target_id
action
weight
created_at
```

### MySQL Table: genres

```text
id
name
category
```

Examples:

```text
music: hip hop, classical, indie, jazz, rock
visual_art: digital art, painting, sketching, concept art
dance: hip hop dance, classical dance, contemporary
film: acting, direction, cinematography, editing
photography: portrait, fashion, wedding, street
```

### MySQL Tables For Genre Mapping

```text
user_genres
  user_id
  genre_id
  strength

post_genres
  post_id
  genre_id
  confidence
```

### MongoDB Collection: search_history

```json
{
  "userId": 12,
  "query": "hip hop producers in Mumbai",
  "detectedGenres": ["hip hop", "music production"],
  "detectedLocation": "Mumbai",
  "createdAt": "timestamp"
}
```

### Vector DB Embeddings

Create embeddings for:

```text
post captions
post AI tags
artist bios
portfolio descriptions
search queries
gig descriptions
collaboration requests
```

Each vector should include metadata:

```json
{
  "targetType": "POST",
  "targetId": 101,
  "userId": 12,
  "genres": ["hip hop", "producer"],
  "createdAt": "timestamp"
}
```

### Recommendation Formula

Use this starting formula:

```text
final_score =
  genre_match_score * 0.30
+ search_history_score * 0.20
+ interaction_similarity_score * 0.20
+ embedding_similarity_score * 0.15
+ freshness_score * 0.10
+ popularity_score * 0.05
```

Add penalties:

```text
- already_seen_penalty
- reported_content_penalty
- blocked_user_penalty
- not_interested_penalty
```

Add diversity:

```text
Do not show only one genre repeatedly.
Mix primary interests with related discovery.
For example, hip hop artists can also see beat producers, cover designers, dancers, video editors, and event organizers.
```

### Python Endpoint: Feed Recommendation

Endpoint:

```http
POST /ai/recommend/feed
```

Request:

```json
{
  "userId": 12,
  "genres": ["hip hop", "rap", "music production"],
  "recentSearches": ["music producer", "rap battle"],
  "likedTags": ["beats", "studio", "producer"],
  "followedUserIds": [4, 8, 20],
  "alreadySeenPostIds": [1, 2, 3],
  "limit": 20
}
```

Response:

```json
{
  "recommendations": [
    {
      "targetType": "POST",
      "targetId": 45,
      "score": 91.4,
      "reason": "Matches hip hop genre and recent producer searches"
    },
    {
      "targetType": "POST",
      "targetId": 12,
      "score": 86.2,
      "reason": "Similar to posts saved by user"
    }
  ]
}
```

### Spring Boot Recommendation Endpoints

```http
GET /api/feed
GET /api/recommendations/artists
GET /api/recommendations/gigs
GET /api/recommendations/collaborations
POST /api/interactions
POST /api/search
```

Spring Boot should:

1. Receive feed request from React.
2. Load user genres, interactions, searches, blocked users, seen posts.
3. Call Python AI recommendation service.
4. Receive ranked IDs.
5. Fetch full data from MySQL/MongoDB.
6. Return full response to React.

Python should return IDs and scores, not full post objects.

## Service 3: Basic Flow - Upload Post With AI

Implement AI-assisted post upload.

Supported content:

```text
text caption
image
video metadata placeholder
audio metadata placeholder
```

For now, fully implement text and image handling. Keep clear extension points for video and audio.

### Upload Flow

```text
React user creates post
   |
React uploads caption + media to Spring Boot
   |
Spring Boot saves post as PENDING_AI_REVIEW
   |
Spring Boot calls Python text moderation
   |
Spring Boot calls Python image moderation if image exists
   |
If unsafe:
   post status = BLOCKED or NEEDS_REVIEW
   return warning to frontend
If safe:
   Python generates tags/genres/mood
   Python creates embedding
   Spring Boot saves AI metadata
   post status = PUBLISHED
   return published post to frontend
```

### Post Status Values

```text
DRAFT
PENDING_AI_REVIEW
PUBLISHED
NEEDS_REVIEW
BLOCKED
DELETED
```

### Spring Boot Endpoint: Create Post

```http
POST /api/posts
```

Use multipart/form-data:

```text
caption
mediaFile
mediaType: IMAGE / VIDEO / AUDIO / TEXT
visibility: PUBLIC / FOLLOWERS / PRIVATE
```

Response if published:

```json
{
  "postId": 101,
  "status": "PUBLISHED",
  "caption": "Late night beat session.",
  "aiTags": ["hip hop", "producer", "beat making", "studio"],
  "genres": ["hip hop", "music production"],
  "moderation": {
    "action": "SAFE"
  }
}
```

Response if blocked:

```json
{
  "postId": 101,
  "status": "BLOCKED",
  "message": "This post could not be published because it violates content safety rules.",
  "moderation": {
    "action": "BLOCK",
    "reason": "High toxicity detected"
  }
}
```

### Python Endpoint: Tag Content

Endpoint:

```http
POST /ai/tag-content
```

Request:

```json
{
  "postId": 101,
  "caption": "Late night beat session in my home studio",
  "mediaType": "IMAGE",
  "imageUrlOrPath": "path-or-url-if-available"
}
```

Response:

```json
{
  "tags": ["hip hop", "producer", "beat making", "studio"],
  "genres": ["hip hop", "music production"],
  "mood": ["focused", "creative"],
  "artistCategories": ["musician", "producer"],
  "confidence": 0.86
}
```

### Python Endpoint: Create Embedding

Endpoint:

```http
POST /ai/embeddings/post
```

Request:

```json
{
  "postId": 101,
  "text": "Late night beat session hip hop producer beat making studio"
}
```

Response:

```json
{
  "postId": 101,
  "embeddingStored": true,
  "vectorId": "POST_101"
}
```

### MySQL Table: posts

```text
id
user_id
caption
media_url
media_type
visibility
status
created_at
updated_at
published_at
```

### MongoDB Collection: post_ai_metadata

```json
{
  "postId": 101,
  "tags": ["hip hop", "producer", "beat making"],
  "genres": ["hip hop", "music production"],
  "mood": ["focused", "creative"],
  "artistCategories": ["musician", "producer"],
  "moderation": {
    "text": {
      "action": "SAFE",
      "scores": {
        "toxicity": 0.01
      }
    },
    "image": {
      "action": "SAFE",
      "scores": {
        "explicit": 0.01
      }
    }
  },
  "embedding": {
    "vectorId": "POST_101",
    "stored": true
  },
  "createdAt": "timestamp"
}
```

## React UI Requirements

Build frontend screens/components for:

```text
Create Post
Feed
Recommendation sections
Search
Moderation warning state
Admin moderation queue
```

### Create Post UI

The create post UI should include:

```text
caption textarea
media upload input
visibility selector
submit button
AI moderation loading state
blocked/review warning state
published success state
AI-generated tags preview after upload
```

### Feed UI

The feed should show:

```text
recommended posts
reason for recommendation if available
like/comment/save/follow buttons
not interested button
report button
```

Every interaction should call:

```http
POST /api/interactions
```

This is important because recommendations depend on interaction data.

## Spring Boot Service Classes

Create service classes like:

```text
PostService
ModerationService
RecommendationService
InteractionService
AiClientService
SearchService
```

The `AiClientService` should call Python FastAPI using WebClient.

Example AI service URLs:

```text
AI_SERVICE_BASE_URL=http://localhost:8000
```

## Python AI Service Structure

```text
ai-service-python/
  app/
    main.py
    routers/
      moderation.py
      recommendation.py
      tagging.py
      embeddings.py
    services/
      text_moderation_service.py
      image_moderation_service.py
      recommendation_service.py
      embedding_service.py
      tagging_service.py
    models/
      schemas.py
```

## Environment Variables

Use environment variables:

```text
SPRING_DATASOURCE_URL
SPRING_DATASOURCE_USERNAME
SPRING_DATASOURCE_PASSWORD
MONGODB_URI
AI_SERVICE_BASE_URL
VECTOR_DB_URL
MEDIA_UPLOAD_DIR
JWT_SECRET
```

Python:

```text
VECTOR_DB_URL
MONGODB_URI
MODEL_CACHE_DIR
HF_TOKEN optional
```

## Acceptance Criteria

The build is successful when:

1. A user can upload a post with caption and image.
2. Spring Boot saves the post as pending before AI checks.
3. Python checks text moderation.
4. Python checks image moderation.
5. Unsafe posts are blocked or sent to review.
6. Safe posts are published.
7. Safe posts receive AI tags, genres, mood, and artist category metadata.
8. Post embeddings are created and stored in the vector DB.
9. User interactions are tracked.
10. Feed recommendations are returned based on genre, search history, interactions, and embeddings.
11. React feed displays recommended posts.
12. React create-post page shows moderation status and AI tags.
13. Admin can see posts needing review.

## Implementation Priority

Build in this exact order:

1. Spring Boot post upload endpoint
2. MySQL post model and status lifecycle
3. Python text moderation endpoint
4. Python image moderation endpoint
5. Spring Boot moderation client
6. Save moderation results
7. Publish/block/review logic
8. Python content tagging endpoint
9. Python embedding endpoint
10. Vector DB connection
11. Interaction tracking endpoint
12. Recommendation endpoint in Python
13. Feed endpoint in Spring Boot
14. React create-post page
15. React feed page
16. Admin moderation queue

## Important Rules

- React must not call Python directly.
- Spring Boot must own business logic and database writes.
- Python should only return AI results.
- Do not publish unsafe content.
- Always store moderation results for audit.
- Always track interactions for recommendations.
- Keep video/audio extension points, but implement text and image first.
- Do not store sensitive user data in localStorage.
- Do not make recommendations from blocked, reported, deleted, or unsafe content.

## Future Extensions

After these three services work, add:

- AI profile builder
- AI caption generator before posting
- AI assistant
- Portfolio review
- Full video moderation by frame extraction
- Audio moderation using speech-to-text
- Collaboration matching
- Gig recommendation
- Community recommendation
- Advanced analytics dashboard
