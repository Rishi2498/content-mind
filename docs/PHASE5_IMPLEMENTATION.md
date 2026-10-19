# Phase 5 — Content Strategy Agent

## Summary

A personalized, evidence-backed content strategy generator. Every number the
creator sees is computed from **their own stored records** — no invented
stats, no guaranteed-reach claims. When data is missing, the agent says so
and produces explicit *hypotheses* rather than fake findings.

## Architecture

```
StrategyProfile ──┐
BrandProfile ─────┤
Content DNA ──────┤
Content / Plans ──┼──► gather_evidence() ──► StrategyEvidence
Reviews ──────────┤         │
Phase 4 metrics ──┤         ▼
Insights ─────────┤  build_recommendations()
Memory ───────────┘         │
                            ▼
              StrategyRecommendation rows (persisted)
                            │
                            ▼
              LLM summary (optional, never required)
```

Each evidence source is gathered **independently** — a memory provider outage
or missing performance table never breaks generation; it degrades and reports
`warnings` + `evidence_sources`.

## Data model (3 additive tables)

| Table | Purpose |
|---|---|
| `strategy_profile` | Creator preferences: niche, topics, audience, goals, pillars, avoid-list, frequency, constraints, rolling feedback_preferences. **Separate from BrandProfile** (create_all cannot ALTER existing tables; BrandProfile already holds voice/tone/formats/platforms). |
| `strategy_recommendation` | One recommendation per row. Immutable generation-time fields (evidence, confidence, hypothesis flag) are never rewritten; creator edits land in `edited_*` columns + a `status` lifecycle (`proposed → accepted|edited|rejected|deferred → completed`). |
| `experiment` | Tracks a hypothesis: what was changed (variation), intended metric, actual result. A completed experiment is framed as a **single observation**, never proof of causality. |

## API surface (`/api/strategy`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/profile` | Current profile (empty defaults if unset) |
| PUT | `/profile` | Create/update (one active per user) |
| POST | `/generate` | Generate recommendations for a week/month period |
| GET | `/recommendations` | List, filter by `status`, paginated |
| PATCH | `/recommendations/{id}` | Edit fields / transition status |
| POST | `/recommendations/{id}/feedback` | Accept/reject/defer/complete; optional explicit preference persistence |
| GET | `/experiments` | List experiments |
| POST | `/experiments` | Create (optionally linked to a recommendation) |
| PATCH | `/experiments/{id}` | Update status / record actual result |
| GET | `/lessons` | Memory lessons + completed-experiment observations |

## Evidence classes

1. **Evidence-backed** (`is_hypothesis=False`): only when the user has
   recorded post metrics. Carries `sample_size`, `observation_period`,
   Phase-4 confidence label (`strong ≥10`, `moderate 5–9`, `weak 2–4`,
   `insufficient <2`), and cited evidence rows (post titles + platform).
2. **Hypothesis** (`is_hypothesis=True`): used when there is no sufficient
   performance data for a topic. Carries a learning-oriented `test_method`
   and is never presented as a finding.

## Learning loop

- `generate_strategy` remembers up to 5 curated statements + a niche summary
  to long-term memory (Hindsight when configured, local fallback otherwise).
- A **single rejection** is stored on the recommendation only — it does NOT
  become a permanent profile preference unless the creator explicitly passes
  `update_preferences=True`.
- `build_lessons` surfaces memory-recalled strategy lessons + completed
  experiments, each explicitly labelled "a single observation, not proof of
  causality."

## Verification

- **Backend**: 174 passed (146 pre-existing + 28 new Phase 5 tests in
  `backend/tests/test_strategy_agent.py`). Covers profile CRUD + validation,
  empty-state honesty, hypothesis/evidence distinction, avoid-topic respect,
  recommendation cap, lifecycle edits, tenant isolation (404 on foreign IDs),
  auth (401), memory-failure degradation (generate still 200s), experiment
  lifecycle, lessons non-causal framing.
- **Frontend**: `tsc --noEmit` clean; `vite build` green.
- **OpenAPI**: all 10 strategy endpoints registered under `/api/strategy`.
