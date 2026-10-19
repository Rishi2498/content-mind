# Phase 3 Implementation — Pre-Publish Reviewer

Phase 3 makes ContentMind give creators actionable advice **before** they
publish. A draft (text) or a processed media asset is scored on three axes
(0-100): **hook**, **clarity**, and **brand alignment**. Each review returns
2-6 suggestions, and every suggestion carries evidence — a brand rule from
the account's BrandProfile or a learned memory recalled from the account's
own history — so advice is grounded, not generic.

## Architecture

```
POST /api/reviewer/review          (text draft)
  └─ reviewer_service.review_draft
       ├─ _get_brand               (active BrandProfile for the user)
       ├─ MemoryService.recall     (learned memories relevant to the draft)
       ├─ _llm_review              (LLM, strict LLMReviewResult JSON)
       │    └─ fallback ──────────► heuristic engine (deterministic)
       └─ persist ContentReview    (immutable iteration history)

POST /api/reviewer/media/{asset_id}   (media asset via its ContentDNA)
  └─ builds a synthetic draft from transcript + scene + OCR + tags
  └─ review_draft(...)  →  writes scores onto ContentDNA
                           (hook_score / clarity_score / brand_alignment,
                            previously NULL = not evaluated)
```

### Scoring

| Axis | What it measures | Heuristic signals (no LLM) |
|------|------------------|-----------------------------|
| Hook | Does the opener earn the next second? | Power openers (question/number/contrarian word), first-line length ≤ ~14 words, question mark, digits |
| Clarity | Skimmable and unambiguous? | Avg sentence length, filler words (`very`, `just`, `actually`…), total length |
| Brand alignment | Fits the brand voice and audience? | Token overlap with BrandProfile tone/description/audience, preferred-platform match, weak-CTA penalty |

Overall = hook×0.35 + clarity×0.35 + brand×0.30. When no brand profile
exists, brand alignment defaults to a neutral 55 (nothing to compare
against — deliberately not 0).

With `LLM_API_KEY` set, the LLM scores the same three axes and produces
suggestions that must cite evidence (brand rule or memory). On any LLM
failure the service falls back to the deterministic heuristic and marks the
response `degraded=true, engine="heuristic"` — it never 500s.

### Evidence

Suggestions cite their justification in the `evidence` field:

- **Brand rules**: `Brand rule (profile): tone = …` (from the user's active BrandProfile)
- **Learned memories**: top memories recalled via `MemoryService.recall` using the draft as query, attached both per-suggestion and in the response-level `evidence` list
- **Heuristic rules**: e.g. `Hook heuristic: long openers dilute the promise on scrolling feeds.`

### Iteration history

Every review is persisted as an immutable `ContentReview` row (scores,
suggestions JSON, evidence, engine, source=`draft`|`media`). The UI shows
recent reviews so creators can track score movement across edits.

### Media → DNA scores

`POST /api/reviewer/media/{asset_id}` reviews a processed asset using its
ContentDNA signals and **writes the scores back** onto
`ContentDNA.hook_score / clarity_score / brand_alignment` — the columns
that were explicitly NULL (= not evaluated) since Phase 2. This closes the
Phase 2 → Phase 3 loop: upload media, build DNA, then review it.

## API endpoints

| Method | Path | Purpose |
|--------|------|---------|
| POST   | `/api/reviewer/review` | Review a text draft; persists history |
| POST   | `/api/reviewer/media/{asset_id}` | Review a media asset's DNA; writes DNA scores |
| GET    | `/api/reviewer/reviews` | Paginated review history (own reviews only) |

All routes require a bearer token and are tenant-scoped. Reviewer rows
carry `user_id`; media review returns 404 for other tenants' assets.

## Models & migration

New table `content_review` (additive via `create_all` on startup; existing
data untouched). `ContentDNA`'s three nullable score columns are populated
on first media review.

## Testing

All LLM calls are mocked; the heuristic engine is exercised for real
(deterministic). No network, no paid API usage.

```bash
cd backend

# Full suite (Phase 1 + 2 + 3)
.venv/Scripts/python -m pytest tests/ -q

# Phase 3 only
.venv/Scripts/python -m pytest tests/test_reviewer.py -q
```

Frontend type-check and build:

```bash
cd frontend
node_modules/.bin/tsc.cmd --noEmit -p tsconfig.app.json
node_modules/.bin/vite.cmd build
```

Test coverage: heuristic score ranges and good-vs-weak discrimination,
brand-alignment lift, suggestion categories and evidence presence, LLM
result adoption (mocked), heuristic fallback on LLM unavailability, API
auth (401), history persistence, tenant isolation, media review writing
DNA scores, 404 on missing/foreign assets.

## Known limitations

- Heuristic brand alignment is lexical (token overlap); it cannot judge
  nuance. Configure `LLM_API_KEY` for real semantic review.
- The reviewer scores text signals only; it does not re-analyze media
  frames (that is Phase 2's vision pipeline — the reviewer consumes DNA).
- Memory-based evidence quality depends on what the account has taught the
  memory layer; new accounts see fewer cited memories.
- Reviews are immutable history; there is no edit/delete UI for past
  reviews (by design — score movement is the iteration signal).
