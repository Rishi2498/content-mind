# Implementation Roadmap

## Phase 1: Foundation & Multi-tenancy ✅
- [x] Implement Authentication (JWT/OAuth). (JWT bearer tokens, HS256, pbkdf2_sha256 password hashing, `/api/auth/signup|login`)
- [x] Add `user_id` / `creator_id` to all relational models.
- [x] Implement tenant-isolation middleware/dependencies in FastAPI. (`get_current_user` dependency; every query scoped by `user_id`)
- [x] Update Frontend to include Login/Signup and Auth state management. (`AuthContext`, `Login`, `Signup`, route gate in `App.tsx`)

## Phase 2: Advanced Ingestion & Media Intelligence ✅
- [x] Setup Background Processing. *(Approved deviation: FastAPI `BackgroundTasks` + `MediaJob` status table instead of Redis + Celery — no external broker required; service layer abstracted so a Celery/Redis swap is isolated to `media_service.enqueue_processing`. Jobs interrupted by a restart are marked failed on startup.)*
- [x] Implement Video Pipeline:
    - [x] FFmpeg metadata extraction. (`ffmpeg_service.probe` — duration, width/height, has_audio; subprocess with hard timeout)
    - [x] Audio extraction & Whisper transcription. (mono 16 kHz WAV via FFmpeg; hybrid transcription: OpenAI-compatible whisper API → optional local faster-whisper → metadata-only degrade, controlled by `WHISPER_PROVIDER`)
    - [x] Keyframe extraction. (`ffmpeg_service.extract_keyframes` — thumbnail filter, numbered JPEGs)
- [x] Implement Image Pipeline:
    - [x] Vision model analysis. (`vision_service.analyze_keyframes` — per-frame scene/OCR/tags via the existing OpenAI-compatible vision LLM; image treated as single keyframe)
    - [x] OCR integration. (Vision-LLM OCR in the same call — on-screen text returned in `LLMImageAnalysis.ocr_text`; no separate Tesseract dependency)
- [x] Implement "Content DNA" structured representation. (`ContentDNA` model — transcript, language, scene description, OCR text, visual tags, per-keyframe analyses; reviewer scores are NULL = not evaluated until Phase 3)

## Phase 3: Pre-Publish Reviewer (Core Feature) ✅
- [x] Build Reviewer Service:
    - [x] Hook analysis. (heuristic: power openers, length, question/number signals; LLM when configured)
    - [x] Brand consistency check. (compares draft against BrandProfile tone/audience/platforms; scores 0-100)
    - [x] Evidence-based suggestions. (each suggestion cites a brand rule or a memory recalled via MemoryService)
- [x] Create Reviewer UI (Upload -> Analysis -> Iteration). (`/reviewer` page: draft form, score gauges, suggestion cards with evidence, review history; media assets reviewed via `POST /api/reviewer/media/{id}` which writes scores onto ContentDNA)

## Phase 4: Evidence-Based Analytics ✅
- [x] Implement baseline performance calculations. (Manual-first: `PublishedPost` + append-only `MetricSnapshot` models; `/api/performance/*` routes — register post, dated snapshots, dashboard aggregates with fixed rate denominators per-view vs per-impression; platform-reported CTR only)
- [x] Build "Insight Engine" (What happened -> Evidence -> Action). (`insight_service` — topic/format/platform/CTA/review-vs-performance analyses; every insight carries sample size, metric, evidence rows, observation period, limitations and an experiment recommendation; insufficient data yields an explicit insufficient-evidence state)
- [x] Add statistical uncertainty and sample size warnings. (Confidence labels: strong ≥10 / moderate 5-9 / weak 2-4 / insufficient <2 posts; mixed-platform limitations attached; planner consumes only moderate+ hints as experiments, falling back unchanged when evidence is thin)

## Phase 5: Creator Memory & Strategy ✅
- [x] Enhance Memory Service to store "Learned Patterns". (`strategy_agent_service` remembers curated niche + top-plan statements after each generation; `build_lessons` surfaces memory-recalled strategy lessons; explicit `update_preferences=True` feedback persists to `StrategyProfile.feedback_preferences` + memory)
- [x] Implement Strategy Planner (Weekly/Monthly). (`StrategyProfile` (creator preferences), `StrategyRecommendation` (immutable evidence/hypothesis fields + creator-editable status lifecycle), `Experiment`; deterministic `build_recommendations` — evidence-backed from Phase-4 validated hints, hypotheses when data is thin, avoid-topics respected, ≤14 recs)
- [x] Link Strategy output to historical evidence. (Every evidence-backed rec carries `sample_size`, `observation_period`, Phase-4 confidence label, and cited evidence rows; hypothesis recs carry a learning-oriented `test_method`; `evidence_sources` + `warnings` shown in UI; `/strategy` page with profile editor, recommendation cards, feedback, experiment tracking, lessons)

## Phase 6: Social Integrations & Automation ✅
- [x] Implement Instagram API integration.
    - [x] OAuth 2.0 authorization flow (Instagram Login) with CSRF-protected state.
    - [x] Token exchange, encrypted storage (AES-GCM), proactive refresh.
    - [x] Media import (IMAGE, VIDEO, CAROUSEL_ALBUM) with idempotent upsert.
    - [x] Metric insights sync (per-media + account-level) → MetricSnapshot.
    - [x] Sync orchestration with observable states and error categorization.
    - [x] Tenant-scoped API routes: authorize, callback, connections, sync, posts, insights.
    - [x] Frontend page: connect, disconnect, sync, insights, imported posts.
    - [x] Phase 4 analytics integration (Instagram posts in dashboard).
    - [x] Phase 5 strategy integration (evidence available to agent).
    - [x] 29 tests covering OAuth, token mgmt, media import, metrics, isolation.
- [ ] Implement YouTube API integration.
- [ ] Add automated metric syncing.
- [ ] Implement notification system for analysis completion.

## Phase 7: Commercial Readiness ✅
- [x] Security hardening and tenant isolation audit.
- [x] Instagram OAuth and encryption review.
- [x] Database migration strategy with Alembic (baseline + additive migrations).
- [x] PostgreSQL compatibility verified for all models.
- [x] Backup and restore scripts (SQLite/PostgreSQL, uploads, encrypted tokens).
- [x] Production deployment configuration (env validation, health checks, CORS).
- [x] Background job scheduler (APScheduler) for Instagram sync with persistence.
- [x] Structured logging and health endpoints (/health, /health/ready).
- [x] Frontend onboarding and error handling review.
- [x] End-to-end acceptance test plan documented.
- [x] CI/CD pipeline (GitHub Actions: tests, lint, build, migration test, deploy).
- [x] Production readiness documentation (PHASE7_PRODUCTION_READINESS.md).
- [ ] Implement Billing/Subscription logic.
- [ ] Deployment documentation.
