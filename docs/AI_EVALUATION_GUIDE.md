# AI Evaluation Guide

## Purpose
Repeatable evaluation of LLM outputs against a fixed rubric of criteria. All test data is synthetic and clearly labeled for demo mode. No real API keys required.

## Rubric Criteria

### 1. Relevance
- **Question**: Does the insight relate to the user's query topic?
- **Heuristic**: Keyword match between insight text and query topic, plus "performance" or "engagement"
- **Expected**: `true` if any insight keyword matches the query; `false` otherwise

### 2. Grounding
- **Question**: Is every insight traceable to evidence?
- **Heuristic**: Every insight must have a non-empty `evidence` field
- **Expected**: `true` if all insights have evidence; `false` if any are missing

### 3. Correctness
- **Question**: Does the output conform to structural constraints?
- **Heuristic**: `confidence` must be a number in [0, 1]; no `null` or out-of-range values
- **Expected**: `true` if all confidences valid; `false` otherwise

### 4. Consistency
- **Question**: Are there duplicate insight texts?
- **Heuristic**: Compare insight texts; `len(texts) == len(set(texts))` means no duplicates
- **Expected**: `true` if no duplicates; `false` if duplicates detected

### 5. Duplicate Detection
- **Question**: Does the output contain duplicate insights?
- **Heuristic**: `len(texts) != len(set(texts))` flags duplicates
- **Expected**: `true` if duplicates found; `false` if output is unique

### 6. Unsupported Claims
- **Question**: Are there claims without proper evidence (e.g., "proprietary algorithm")?
- **Heuristic**: Flag insights where `evidence` contains "proprietary" or ("algorithm" AND "your")
- **Expected**: `true` if unsupported claim detected; `false` otherwise

## Synthetic Test Data

All test JSON documents are synthetic with deterministic content:

| Document | Content | Provenance |
|---|---|---|
| `GOOD_JSON` | Performance insight: "Carousels outperform text posts on LinkedIn., 12% vs 4%" | Demo synthetic |
| `POOR_JSON` | Invalid JSON schema — triggers fallback | Demo synthetic |
| `UNSUPPORTED_CLAIM` | "Your engagement will double overnight., proprietary algorithm" | Demo synthetic |
| `DUPLICATE_INSIGHT` | Same insight text appearing twice | Demo synthetic |
| `CONSISTENT_JSON` | Single relevant insight about format performance | Demo synthetic |
| `RELEVANT_INSIGHT` | "Posts with carousels get 3x more comments., 12% vs 4%" | Demo synthetic |

## Evaluation Test Suite

See `backend/tests/ai_evaluation.py` for the complete test class:

- `TestEvaluationRelevance` — relevance tests with 3 parametrized cases
- `TestEvaluationGrounding` — grounding tests
- `TestEvaluationCorrectness` — correctness validation
- `TestEvaluationConsistency` — duplicate detection
- `TestEvaluationUnsupportedClaims` — unsupported claim detection
- `TestEvaluationSchemaValidation` — LLM JSON schema validation

All 15 tests pass with the deterministic heuristic provider, ensuring zero network dependency.

## Running the Evaluation Suite

```bash
# From the backend directory
python -m pytest tests/ai_evaluation.py -v
```

All tests use the deterministic heuristic provider (LLM_PROVIDER=heuristic),
ensuring zero network dependency.

## Output Example

```text
=================== test session starts ===================
...
test_grounding_with_good_json (TestEvaluationGrounding) PASSED
test_correctness_with_good_json (TestEvaluationCorrectness) PASSED
test_consistency_with_good_json (TestEvaluationConsistency) PASSED
test_unsupported_with_unsubstantiated_claim (TestEvaluationUnsupportedClaims) PASSED
...
```

## Notes

- **Heuristic-only**: All evaluation tests pass without an LLM API key, since they exercise the deterministic fallback path
- **Schema-first**: The `LLMContentAnalysis` and `LLMReviewResult` schemas enforce structure; the heuristic output must validate against them
- **Demo clarity**: When running in demo mode, all output files and test reports should include a header noting "Synthetic demo data — no real Instagram or LLM results"
- **Attribute access**: Helper functions access pydantic model attributes directly (e.g., `ins.insight`, `ins.evidence`, `ins.confidence`) rather than `.get()` method, since `LLMExtractedInsight` objects do not support dict-style access