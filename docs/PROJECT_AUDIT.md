# ContentMind Project Audit

## 1. Existing Architecture
The project follows a decoupled frontend-backend architecture:
- **Frontend**: React 19 with TypeScript, Vite, Tailwind CSS, and React Router.
- **Backend**: FastAPI (Python) with a modular service-based architecture.
- **Database**: SQLAlchemy (currently SQLite for dev, compatible with PostgreSQL).
- **Memory Layer**: Integration with "Hindsight" (Vectorize) for long-term semantic memory, with a local in-process fallback.
- **AI Layer**: LLM-agnostic service supporting OpenAI-compatible providers.

## 2. Current Dependencies
- **Backend**: `fastapi`, `uvicorn`, `pydantic`, `SQLAlchemy`, `python-dotenv`, `httpx`.
- **Frontend**: `react`, `react-dom`, `react-router-dom`, `recharts`, `axios`, `tailwindcss`.

## 3. Existing Features
- **Content Management**: Basic CRUD for content items (title, body, platform, topic).
- **Analytics**: Basic performance tracking (impressions, likes, shares, etc.).
- **Memory/Insights**: Ability to generate and store insights linked to content.
- **Planning**: Content plan generation with items, strategy summaries, and gaps.
- **Brand Profiling**: Basic brand profile storage (target audience, tone, etc.).
- **Demo Mode**: Pre-seeded data for demonstration.

## 4. Database Schema
- `content`: Core content records and metrics.
- `content_insight`: Derived insights and evidence.
- `content_plan`: High-level strategy plans.
- `content_plan_item`: Individual items within a plan.
- `brand_profile`: Creator/Brand identity.
- `memory_event`: Audit log for memory operations.
- `plan_result`: Feedback loop from executed plans.
- `daily_metric`: Time-series aggregated metrics.

## 5. API Endpoint Inventory
- `/api/analytics`: Performance data.
- `/api/brand`: Profile management.
- `/api/chat`: Interactive AI reasoning.
- `/api/content`: Content ingestion and retrieval.
- `/api/demo`: Seed data and demo flows.
- `/api/health`: System health checks.
- `/api/memory`: Memory operations.
- `/api/plans`: Strategy generation.

## 6. Tests Status
- **Suite**: Pytest based.
- **Coverage**: Tests exist for analytics, API, content, gaps, LLM fallback, memory, and plans.
- **State**:--- Functional but need expansion for the new requirements.

## 7. Bugs and Architectural Problems
- **Lack of Multi-tenancy**: No user authentication or creator-level data isolation.
- **Limited Ingestion**: Only text-based ingestion; missing image/video/CSV pipelines.
- **Missing Media Intelligence**: No FFmpeg, Whisper, or Vision model integrations.
- **Naive Analytics**: Basic arithmetic; missing statistical depth and baseline comparisons.
- **Syncing**: No official social platform API integrations (manual/mocked only).

## 8. Code to Retain
- The `llm_service.py` provider abstraction.
- The `memory_service.py` and Hindsight integration logic.
- The core relational schema for `Content` and `ContentPlan`.
- The clean FastAPI router structure.

## 9. Code to Refactor
- **Models**: Transition to a more robust tenant-aware schema.
- **Services**: Move from generic "services" to a layered domain architecture (Domain -> Application -> Infrastructure).
- **Frontend**: Transition from static pages to a more dynamic, state-driven SaaS dashboard.

## 10. Missing Functionality
- **Authentication**: Full AuthN/AuthZ system.
- **Media Intelligence**: Video/Image processing pipelines (the core "Content DNA").
- **Social Sync**: Actual YouTube/Instagram API connectors.
- **Pre-Publish Reviewer**: The core differentiator feature.
- **Experiment Engine**: Hypothesis tracking.

## 11. Recommended Migration Plan
1. **Foundation**: Implement Auth and Tenant isolation.
2. **Ingestion**: Build the Media Intelligence pipeline (FFmpeg/Whisper/Vision).
3. **Intelligence**: Develop the "Content DNA" and Pre-Publish Reviewer.
4. **Analytics**: Upgrade to evidence-based statistical analytics.
5. **Automation**: Implement background workers (Celery/Redis).
