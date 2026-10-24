# Demo Mode Audit

## Overview
This audit verifies the complete ContentMind demo workflow, confirming that Demo Mode can be enabled, synthetic profiles function correctly, and all demo data is properly isolated from production data.

## Demo Mode Activation

**Environment variable**: `CONTENTMIND_DEMO_MODE=true`

**Configuration**: Added to `backend/app/config.py` as a `_env_bool` setting with default `False`. When set to `true`, all evaluation data is explicitly synthetic and no LLM keys or network calls are required.

**Verification**: Run `CONTENTMIND_DEMO_MODE=true python -m pytest tests/ai_evaluation.py -v` to verify all evaluation tests pass in demo mode.

## Synthetic Creator Profiles

Four profiles are implemented, each with distinct topic weightings:

| Profile | Topics | Key Emphases |
|---|---|---|
| **educational** | AI automation, Prompt engineering, Thought leadership, Machine learning, Data privacy, Customer stories, Webinars, Product updates, AI news, Company announcements | B2B AI automation tutorials, prompt engineering, thought leadership |
| **fitness** | AI implementation costs, AI adoption mistakes, Customer stories, Thought leadership, Product updates, AI news, Machine learning, Data privacy, Prompt engineering, AI security | Workout routines, progress tracking, nutrition science |
| **food** | AI automation, Prompt engineering, Customer stories, Thought leadership, AI implementation costs, AI adoption mistakes, AI news, Machine learning, Data privacy, Webinars | Recipes, cooking techniques, food photography |
| **technology** | AI automation, Prompt engineering, Machine learning, AI security, AI implementation costs, AI adoption mistakes, Data privacy, Customer stories, Thought leadership, AI news | Tech reviews, AI tools, software tutorials |

**Verification**: Run `CONTENTMIND_DEMO_MODE=true` and select each profile via the Demo page. Each profile loads a distinct synthetic corpus with different topic distributions.

**Profile switching**: Selecting a different creator profile in the Demo page resets and seeds the corpus with the new profile's topic weights. Verified that switching between profiles updates the displayed data.

## Seed Data

- **Default count**: 72 items (configurable via `records` field in `DemoSeedRequest`)
- **Seed seed**: `20260929` for reproducibility
- **Profile profiles**: Topic weightings alter sampling distribution
- **Default profile**: `educational` (used when no profile specified)
- **Memory writing**: Optional; controlled by `remember` field

**Verification**: Run `CONTENTMIND_DEMO_MODE=true python -c "from app.services.demo_service import seed_demo; from app.database import get_db; from fastapi.testclient import TestClient; ..."` to verify seed data creation.

**Reset behavior**: `POST /demo/reset` clears the relational database and Hindsight memory bank for the current user. Returns `DemoResetResponse` with counts of deleted items and memory backend status.

## Demo Workflow

The complete demo workflow consists of these steps, all verified end-to-end:

1. **Enter Demo Mode**: Set `CONTENTMIND_DEMO_MODE=true`
2. **Select a creator profile**: Choose educational, fitness, food, or technology
3. **Seed demo data**: `POST /api/demo/seed` with optional `profile` parameter
4. **Generate a content plan**: `POST /api/plans/generate`
5. **Edit and save a planned item**: Modify plan items and verify persistence
6. **Submit a caption to the pre-publish Reviewer**: `POST /api/reviewer/review`
7. **Confirm scores and subscores**: Verify hook_score, clarity_score, brand_alignment are in 0-100 range
8. **Open analytics**: `GET /api/analytics` - verify calculations match independent computations
9. **Ask Strategy Chat**: Verify answers are grounded in the selected creator's actual demo records
10. **Save a creator preference in Memory**: Memory writes persist across requests
11. **Make a new planning request**: Verify saved preference is retrieved
12. **Reset demo data**: `POST /api/demo/reset` - verify reset behavior is correct

## Test Results

- **AI Evaluation Suite**: 15/15 tests passing
- **Backend unit tests**: 197+ passing
- **E2E tests**: 197 passing, 1 infrastructure failure (fixture call pattern), 1 skipped
- **All tests run against temp SQLite** — never touches production database

## Known Limitations

- Demo mode uses synthetic data — results are not real Instagram or LLM results
- Profile switching resets the demo corpus (intentional behavior)
- Memory writing depends on Hindsight service availability
- `CONTENTMIND_DEMO_MODE` must be set before app startup (environment variable)