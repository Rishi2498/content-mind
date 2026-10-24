# Verified Demo Runbook

## Required Environment Variables

| Variable | Description | Default |
|---|---|---|
| `CONTENTMIND_DEMO_MODE` | Enable demo mode (synthetic data only) | `false` |
| `SECRET_KEY` | JWT signing key | `dev-secret-key-12345` |
| `DATABASE_URL` | SQLite database URL | `sqlite:///./contentmind.db` |
| `ENVIRONMENT` | Environment name | `development` |

## Starting the Backend (Windows PowerShell)

```powershell
# 1. Activate the virtual environment
.\backend\.venv\Scripts\activate.ps1

# 2. Start the backend server
cd backend
python -m app.main
# Output will show: ContentMind API starting (env=development)
```

## Starting the Frontend

```powershell
cd frontend
npm install  # if not already installed
npm run dev  # or: npm run preview
```

## How to Enable Demo Mode

```powershell
# Set the environment variable
$env:CONTENTMIND_DEMO_MODE = "true"

# Or in a .env file:
# CONTENTMIND_DEMO_MODE=true
```

## How to Select a Creator

1. Start the backend and frontend
2. Navigate to `http://localhost:5173/demo`
3. Click one of the four profile buttons:
   - **Educational Creator** - B2B AI automation tutorials
   - **Fitness Creator** - Workout routines and progress tracking
   - **Food Creator** - Recipes and food photography
   - **Technology Creator** - Tech reviews and AI tools
4. The page will load 72 synthetic content items with profile-specific topic emphases

## How to Reset Demo Data

```powershell
# From the Demo page or API
POST /api/demo/reset

# Or via PowerShell
curl -X POST http://localhost:8000/api/demo/reset
```

## How to Execute the Full Workflow

### Step 1: Enter Demo Mode
Set `CONTENTMIND_DEMO_MODE=true` and navigate to the Demo page.

### Step 2: Select a Creator
Click one of the four creator profile buttons. The demo corpus loads with profile-specific topic weights.

### Step 3: Generate a Content Plan
1. Go to the Content Planner page (`/plans/generate`)
2. Set days (e.g., 7), posts per day (e.g., 2)
3. Optionally set a campaign focus theme
4. Click "Generate plan"
5. Verify 7 plan items are created with performance metrics

### Step 4: Edit and Save a Planned Item
1. Review the generated plan
2. Modify a plan item's title, description, or platform
3. Save the changes
4. Verify the update persists

### Step 5: Submit a Caption to the Pre-Publish Reviewer
1. Navigate to the Reviewer page (`/reviewer`)
2. Paste a draft post
3. Click "Review draft"
4. Verify hook_score, clarity_score, and brand_alignment are displayed (0-100 range)
5. Review suggestions with evidence and rationale

### Step 6: Confirm Score, Subscores, Evidence, and Suggestions
- Scores are integers in 0-100 range
- Engine field is "llm" or "heuristic"
- Every suggestion has a rationale and evidence field
- Degraded flag indicates if no LLM is configured

### Step 7: Open Analytics
1. Navigate to the Analytics page (`/analytics`)
2. Verify content items count matches the seeded data
3. Check engagement rate and CTR calculations
4. Compare with independent computed expected values

### Step 8: Ask Strategy Chat What Content Performed Best
1. Go to the Chat page (`/chat`)
2. Ask "What content performed best?"
3. Verify the answer is grounded in the selected creator's actual demo records
4. Check that cited memories reference specific content items

### Step 9: Verify Answer Is Grounded in Demo Records
1. The answer should reference specific content items, topics, or performance metrics
2. Check that memories_used list contains actual demo content citations
3. Unsupported claims (e.g., "proprietary algorithm") should be flagged

### Step 10: Save a Creator Preference in Memory
1. During the session, the memory system records the selected profile
2. Make a new planning request
3. Verify the saved preference (profile) is retrieved for the new request

### Step 11: Reset Demo Data
1. Click "Reset everything" on the Demo page
2. Verify all content, insights, plans, and memories are cleared
3. Re-seed the demo corpus to verify reset behavior is correct

## How to Run Every Test Suite

```powershell
# From the backend directory
python -m pytest tests/ai_evaluation.py -v  # AI evaluation suite (15/15 passing)
python -m pytest tests/ -q --ignore=tests/test_gemini_provider.py --ignore=tests/test_instagram.py  # Backend tests
cd frontend
npm run typecheck  # TypeScript check
npm run build  # Production build
```

## How to Interpret the AI Evaluation Report

The AI evaluation report contains test results for:

- **Relevance**: Keyword match between insight text and query topic, plus "performance"/"engagement"
- **Grounding**: Every insight must have a non-empty `evidence` field
- **Correctness**: `confidence` must be a number in [0, 1]
- **Consistency**: No duplicate insight texts
- **Duplicate Detection**: `len(texts) != len(set(texts))` flags duplicates
- **Unsupported Claims**: Insights with "proprietary" or ("algorithm" AND "your") in evidence

All 15 tests pass with the deterministic heuristic provider, ensuring zero network dependency. Results are synthetic demo data — not real LLM predictions.

## Features Verified vs Incomplete

### Verified Features (✅)
- Demo mode activation via `CONTENTMIND_DEMO_MODE=true`
- Four synthetic creator profiles (educational, fitness, food, technology)
- Profile-specific topic weightings and performance patterns
- Seed data creation with reproducible seeding (seed=20260929)
- Demo data reset (`POST /demo/reset`)
- Profile switching updates displayed data
- Demo data isolation from production user data
- AI evaluation suite runs without LLM keys
- Heuristic evaluation of LLM output schemas
- Frontend UI pages (Login, Add Content, Reviewer, Strategy Chat, Memory, Content Planner, Analytics, Instagram connect)
- Backend API endpoints for demo workflow

### Incomplete/Unverified Features (⚠️)
- Real Instagram OAuth flow (requires Meta App credentials and test Instagram account)
- Real LLM key-dependent features (all heuristic-only in demo mode)
- Production deployment with real database and Hindsight service
- Full media import and sync functionality

## Demo Data Provenance

All synthetic data is clearly marked with `source: "seed"` provenance tags. No generated figures are presented as actual Instagram results. Demo mode is activatable via `CONTENTMIND_DEMO_MODE=true` and works without a real Instagram connection or paid LLM key.