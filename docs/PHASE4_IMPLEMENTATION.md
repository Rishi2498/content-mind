# Phase 4 Implementation — Performance Intelligence & Learning

Status: complete and verified. All numbers below were produced by actually running the commands shown — not estimated.

## 1. Architecture & data relationships

Phase 4 adds a manual-first performance loop on top of Phases 1–3 without touching their schemas or behaviour:

```
PublishedPost (user-owned, optionally linked → Content / MediaAsset)
    └── MetricSnapshot (append-only, dated readings; every metric nullable)

Content ──→ ContentReview / ContentDNA ──→ review_vs_performance insight
StrategyContext.performance_hints ← insight_service.validated_experiment_hints()
    └── rendered into the planner LLM prompt + persisted plan caveats
```

- A `PublishedPost` represents a real published post. Links to `Content` and `MediaAsset` are optional (a post may predate ContentMind) and are validated to belong to the same user at registration time.
- `MetricSnapshot` rows are **append-only history**: adding a new snapshot never overwrites older ones. Aggregations use each post's **latest snapshot** in the requested window as its current state.
- NULL means **unknown / not collected** and is never coerced to 0. A genuine zero is stored as `0`. The UI renders unknown as `—`.
- Insight generation and the planner hook are deterministic and work with no LLM configured. No new services, queues, or databases were introduced.

## 2. Models & migrations

Two additive tables in `backend/app/models.py`:

| Model | Table | Key fields |
|---|---|---|
| `PublishedPost` | `published_post` | `user_id` (indexed), nullable `content_id` / `media_asset_id` (SET NULL), `platform`, `title`, `external_id`, `url`, `published_at`, `status` (`published`\|`archived`), timestamps; indexes on platform + published_at |
| `MetricSnapshot` | `metric_snapshot` | `post_id` (CASCADE, indexed), `user_id`, `source` (`manual`\|`platform`), `recorded_at`, `days_since_published` (nullable, computed at record time), nullable metrics: `views`, `impressions`, `likes`, `comments`, `shares`, `saves`, `link_clicks`, `watch_time_seconds`, `avg_watch_duration_seconds`, `audience_retention_pct` (0–100), `ctr_pct` (0–100) |

**Migration**: additive only, created by `init_db()` / `Base.metadata.create_all` at startup (the same mechanism used for Phase 2/3 tables — the project does not use Alembic). Existing tables, rows, and the dev database are untouched. Validation (`ge=0` counts/durations, `0–100` percentages) is enforced server-side by Pydantic (`MetricSnapshotInput`).

## 3. API endpoints (exact paths, from OpenAPI)

All routes require a bearer token (`401` otherwise) and are scoped to `current_user.id`. Prefix: `/api/performance` (router tag `performance`).

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/performance/posts` | Register a published post. Body: `PublishedPostCreate` (platform, published_at required; title/url/external_id/content_id/media_asset_id/initial_snapshot optional). `404` if linked content/media belongs to another user or doesn't exist. Returns `PublishedPostRead` (`201`). |
| `GET` | `/api/performance/posts` | List posts. Query: `platform`, `limit` (1–200, default 50), `offset`. Returns `{items, total}`. |
| `GET` | `/api/performance/posts/{post_id}` | Post detail with full snapshot history (`PublishedPostDetail`). `404` if not owned. |
| `PATCH` | `/api/performance/posts/{post_id}` | Update title / url / external_id / status. |
| `DELETE` | `/api/performance/posts/{post_id}` | Delete post (snapshots cascade). `204`. |
| `POST` | `/api/performance/posts/{post_id}/snapshots` | Append a metric snapshot (`MetricSnapshotInput`). History is never overwritten. `201`. |
| `GET` | `/api/performance/analytics` | Dashboard aggregates. Query: `start`, `end` (ISO-8601), `platform`. Returns `PerformanceAnalyticsResponse`. |
| `GET` | `/api/performance/compare/{platform}` | Same-platform post comparison with comparable observation windows. Query: `max_age_gap_days` (1–90, default 7). |
| `GET` | `/api/performance/insights` | Evidence-based insight report (`InsightReportResponse`). |

Request/response field names match the TypeScript interfaces in `frontend/src/types.ts` exactly.

**Untrusted input**: URLs are accepted only when `http(s)` with a host; anything else (`javascript:`, `ftp:`, bare strings) is stored as empty string. The backend **never fetches** submitted URLs. `external_id` is length-capped and stripped of non-printable characters. Neither is used to make outbound requests.

## 4. Metric definitions & rate denominators

Fixed per field; denominators are **never interchanged**:

| Metric | Definition | Denominator |
|---|---|---|
| `engagement_rate_per_view` | `(likes + comments + shares) / views` | views |
| `engagement_rate_per_impression` | `(likes + comments + shares) / impressions` | impressions |
| `ctr_pct` | **platform-reported only** | as the platform defines it |
| `avg_views` | mean of non-null latest-snapshot views | — |

- A post missing the denominator for a rate is **excluded from that rate only**, not treated as 0.
- `ctr_pct` is never derived from `link_clicks / views` because platforms disagree on the denominator (view vs impression); only creator-entered/platform-reported CTR is shown.
- Engagement is exactly `likes + comments + shares`. Saves and link clicks are tracked but not folded into engagement (documented choice).
- `days_since_published` is computed from `published_at` to `recorded_at` at snapshot creation.

## 5. Supported metrics & limitations

Supported (all nullable): views, impressions, likes, comments, shares, saves, link clicks, watch time (total + average), audience retention %, CTR %.

Limitations:
- Manual entry only — no scraping, no platform API calls, no credentials stored (platform integrations are Phase 6).
- Cross-platform metrics are never pooled into one rate; per-platform aggregates are computed separately and the platform insight explicitly states that platforms define views/impressions differently.
- Post age, posting time, and audience size are not controlled for; comparisons use `days_since_published` windows (`compare` endpoint) where possible.

## 6. Insight generation & confidence rules

`insight_service.build_insight_report` computes five deterministic analyses from stored data only — no invented posts, metrics, or evidence:

1. `topic_performance` — per-platform mean engagement-per-view by linked Content topic.
2. `format_performance` — same, by content type.
3. `platform_performance` — side-by-side per-platform means (never pooled).
4. `cta_performance` — keyword-detected CTA markers in linked Content bodies vs those without.
5. `review_vs_performance` — association between pre-publish review scores (ContentReview.overall_score, or ContentDNA.hook_score when no review exists) and later engagement per view.

Confidence labels (posts with a usable metric for that comparison):

| Label | Sample size |
|---|---|
| `strong` | ≥ 10 |
| `moderate` | 5–9 |
| `weak` | 2–4 (directional only) |
| `insufficient` | < 2 → `status: "insufficient_data"` |

Every insight carries: plain-language finding, `posts_analyzed`, the exact metric + comparison, evidence rows (post id/title/platform/value), observation period, limitations (including alternative explanations and "association, not causation"), and an experiment recommendation. Insufficient data produces an explicit `insufficient_data` state naming how many more posts are needed.

**Reviewer-score integrity**: only posts that HAVE a review (or DNA hook score) enter the correlation; missing scores are excluded, never backfilled or treated as zero. The finding text states it is an association, not a prediction; no viral predictions are made.

## 7. Environment variables

**None added.** Phase 4 uses no new configuration. Existing variables (`LLM_API_KEY` etc.) are unaffected; the insight and planner-integration engines are fully deterministic and never call an LLM.

## 8. Frontend

- Route: `/performance` (requires auth; nav entry "Performance — Real results & insights").
- Page: `frontend/src/pages/Performance.tsx` — summary stat cards, platform/date-range filters, published-posts list, post detail panel with full snapshot history table, append-snapshot form (blank = unknown), register-post form, insights section (confidence chips, n= counts, evidence rows, collapsible limitations, experiment recommendations), and useful empty/loading/validation-error/API-error states.
- Unknown metrics render as `—` (visually distinct from a real `0`). No chart or number is hardcoded; everything derives from API responses. Empty state directs the creator to register a post.
- Types: `frontend/src/types.ts` (Phase 4 section mirrors backend schemas).

## 9. Planner integration

`insight_service.validated_experiment_hints(db, user_id)` returns at most 3 insights with `status: "ok"` and `confidence` moderate/strong. `strategy_service.build_strategy_context` attaches them as `StrategyContext.performance_hints` (default `[]`; wrapped in try/except so a failure can never break plan generation). They are:
- rendered into the LLM prompt as a "VALIDATED PERFORMANCE EXPERIMENTS" section (instructed to treat as experiments, not guarantees),
- persisted as plan caveats (`generate_plan_for_user`, capped at 2 hint caveats, total caveats capped at 8).

With no/insufficient performance data the hints list is empty and planner behaviour is byte-for-byte unchanged (existing plan tests pass unmodified).

## 10. Tests & verified results

```
backend:  .venv\Scripts\python.exe -m pytest tests/ -q          → 146 passed (106 existing + 40 new)
          .venv\Scripts\python.exe -m pytest tests/test_performance.py -q → 40 passed
frontend: node_modules\.bin\tsc.cmd --noEmit -p tsconfig.app.json → 0 errors
          node_modules\.bin\vite.cmd build                       → built in 255ms
```

New coverage (`backend/tests/test_performance.py`): input validation (negative counts, >100 percentages, bad dates, non-HTTP URLs), post registration + listing + platform filter + pagination, append-only snapshot history (backdated snapshots don't change "latest"), missing-vs-zero semantics (`views: 0` counts, omitted stays null, aggregates exclude unknowns), rate denominators (per-view vs per-impression computed separately; CTR never derived), empty datasets and no-snapshot warnings, date filters, same-platform comparison, auth (`401`) and tenant isolation (posts/snapshots/analytics/insights all invisible across users; foreign post → `404`), unknown linked records → `404`, insufficient-sample insight states, actual-review association with real ContentReview rows, and service units (URL sanitiser, confidence boundaries).

No existing test was modified, weakened, or skipped. No paid API calls, live accounts, or network access are required (LLM provider forced to heuristic in conftest).

## 11. Migration & DB notes

- Additive-only: two new tables (`published_post`, `metric_snapshot`) created via `create_all` at startup. No existing table, column, or row was altered or dropped.
- Dev database backup from earlier phases (`backend/contentmind.db.bak-phase1`) remains valid; no restore was needed.

## 12. Future work (platform integrations)

- Phase 6 connectors (YouTube Data API etc.) should write `MetricSnapshot` rows with `source: "platform"` through the same service functions — the manual path already exercises every field.
- OAuth credential storage, rate limiting, and per-platform metric mapping tables are deliberately out of scope here.
- A "sync now" background job would mirror the Phase 2 `MediaJob` pattern (status table + `BackgroundTasks`).
