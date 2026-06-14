# Artist Platform — Python AI Service

> **FastAPI microservice** exposing AI capabilities for the Artist Social Platform.  
> Called exclusively by Spring Boot — React never calls this directly.

---

## 📦 What's Inside

```
ai-service-python/
  app/
    main.py                         ← FastAPI app, startup, health check
    models/
      schemas.py                    ← All Pydantic request/response models
    db/
      chroma_client.py              ← ChromaDB vector DB connection
    services/
      text_moderation_service.py    ← Detoxify text analysis
      image_moderation_service.py   ← CLIP zero-shot image safety
      tagging_service.py            ← CLIP + keyword content tagging
      embedding_service.py          ← SentenceTransformers + ChromaDB
      recommendation_service.py     ← Hybrid scoring formula
    routers/
      moderation.py                 ← POST /ai/moderate/text + /image
      tagging.py                    ← POST /ai/tag-content
      embeddings.py                 ← POST /ai/embeddings/post
      recommendation.py             ← POST /ai/recommend/feed
  requirements.txt
  .env.example
  Dockerfile
```

---

## 🚀 Quick Start

**1. Install dependencies**
```bash
cd ai-service-python
pip install -r requirements.txt
```

**2. Configure environment**
```bash
cp .env.example .env
# Edit .env if needed (defaults work for local development)
```

**3. Run the service**
```bash
uvicorn app.main:app --reload --port 8000
```

**4. Open API docs**
```
http://localhost:8000/docs    ← Swagger UI (interactive)
http://localhost:8000/redoc   ← ReDoc (readable)
```

> ⚠️ **First startup** downloads AI models (~1.5GB total). Subsequent starts use cached models.

---

## 🧩 The 3 Services

### Service 1 — Content Moderation

Checks text and images for unsafe content before a post is published.

| Endpoint | Method | Description |
|---|---|---|
| `/ai/moderate/text` | POST | Analyze text: toxicity, hate, harassment, spam, sexual, threat |
| `/ai/moderate/image` | POST | Analyze image: explicit, violence, hate symbols, weapons, graphic |

**Decision thresholds (configurable in `.env`):**
- Score ≥ `TEXT_BLOCK_THRESHOLD` (0.80) → **BLOCK**
- Score ≥ `TEXT_REVIEW_THRESHOLD` (0.50) → **REVIEW** (send to admin queue)
- Score < `TEXT_REVIEW_THRESHOLD` → **SAFE** (proceed to publish)

**Models used:**
- Text: [Detoxify](https://github.com/unitaryai/detoxify) (`original` model)
- Image: [CLIP](https://huggingface.co/openai/clip-vit-base-patch32) (zero-shot classification)

---

### Service 3 — Upload Post With AI

Runs after moderation passes. Generates tags/genres and creates the post embedding.

| Endpoint | Method | Description |
|---|---|---|
| `/ai/tag-content` | POST | Generate tags, genres, mood, artist categories |
| `/ai/embeddings/post` | POST | Create semantic embedding, store in ChromaDB |

**Models used:**
- Tagging: CLIP (`openai/clip-vit-base-patch32`) for images + keyword matching for text
- Embeddings: [SentenceTransformers](https://www.sbert.net/) (`all-MiniLM-L6-v2`)

---

### Service 2 — Recommendation

Returns ranked post IDs for a user's personalized feed.

| Endpoint | Method | Description |
|---|---|---|
| `/ai/recommend/feed` | POST | Return ranked `[{targetType, targetId, score, reason}]` |

**Scoring formula (from spec):**
```
final_score =
  genre_match        * 0.30   (user genres vs post genres — Jaccard similarity)
  + search_history   * 0.20   (recent searches vs post tags)
  + interaction_sim  * 0.20   (liked post tags vs this post's tags)
  + embedding_sim    * 0.15   (cosine similarity from ChromaDB)
  + freshness        * 0.10   (exponential decay by post age)
  + popularity       * 0.05   (log-scaled likes/comments/saves)
  - already_seen     (90% penalty if user already saw this post)
```

> **⚠️ Prerequisite:** Posts must be indexed via `/ai/embeddings/post` when published.
> An empty ChromaDB returns empty recommendations.

---

## 🔌 How Spring Boot Connects

See `../spring-boot-integration/INTEGRATION_GUIDE.md` for full wiring instructions.

**Short version:**
1. Add `spring-webflux` to `pom.xml`
2. Copy `AiServiceConfig.java` and `AiServiceClient.java` into your Spring Boot project
3. Set `AI_SERVICE_BASE_URL=http://localhost:8000` in `application.properties`
4. Inject `AiServiceClient` into your `PostService`, `ModerationService`, `RecommendationService`

---

## 🌡️ Health Check

```bash
curl http://localhost:8000/health
```

Response:
```json
{
  "status": "ok",
  "services": {
    "text_moderation": "ok",
    "image_moderation": "ok",
    "embeddings":       "ok",
    "chromadb":         "ok"
  },
  "version": "1.0.0"
}
```

---

## 🐳 Docker

```bash
# Build
docker build -t artist-ai-service .

# Run with persistent volumes
docker run -p 8000:8000 \
  -v $(pwd)/model_cache:/model_cache \
  -v $(pwd)/chroma_data:/chroma_data \
  artist-ai-service
```

Or use `docker-compose` from the project root.

---

## 🔧 Environment Variables

| Variable | Default | Description |
|---|---|---|
| `PORT` | `8000` | Service port |
| `PRELOAD_MODELS` | `true` | Pre-load models at startup |
| `MODEL_CACHE_DIR` | `./model_cache` | HuggingFace model cache |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | SentenceTransformer model |
| `CHROMA_PERSIST_DIR` | `./chroma_data` | ChromaDB persistence directory |
| `TEXT_BLOCK_THRESHOLD` | `0.80` | Text score → BLOCK |
| `TEXT_REVIEW_THRESHOLD` | `0.50` | Text score → REVIEW |
| `IMAGE_BLOCK_THRESHOLD` | `0.75` | Image score → BLOCK |
| `IMAGE_REVIEW_THRESHOLD` | `0.50` | Image score → REVIEW |

---

## 🗺️ Architecture Rules (from spec)

1. ✅ **React** calls **Spring Boot** only
2. ✅ **Spring Boot** calls **this service** only
3. ✅ **This service** returns AI results only — it does not write to MySQL or MongoDB
4. ✅ **Spring Boot** owns all DB writes (MySQL + MongoDB)
5. ✅ **This service** reads/writes **ChromaDB** (its own vector DB)

---

## 🔮 Future Extensions

Extension points are stubbed in the code with `# TODO` comments:
- **Video moderation**: Frame extraction → CLIP per frame
- **Audio moderation**: Speech-to-text → text moderation on transcript
- **Artist recommendation**: `/ai/recommend/artists` using artist bio embeddings
- **Gig recommendation**: `/ai/recommend/gigs` using gig description embeddings
- **Collaboration matching**: embedding similarity between artist bios
