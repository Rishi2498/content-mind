# Phase 2 Implementation - Advanced Ingestion & Media Intelligence

Phase 2 adds a media pipeline to ContentMind: users upload video, image, or
audio files; the backend extracts metadata, keyframes, and speech; a vision
LLM analyses frames (scene + OCR); and everything is combined into a
structured **Content DNA** record. A Content record can then be created from
the DNA when real analysis signals exist.

## Architecture

```
POST /api/media/upload
  -> media_storage.save_upload        (path-confined, size-limited, streamed)
       -> create MediaAsset + MediaJob (status=pending)
            -> BackgroundTasks -> process_asset()
                 -> ffmpeg_service.probe            (duration/streams)
                 -> ffmpeg_service.extract_keyframes (video only; image = itself)
                 -> ffmpeg_service.extract_audio     (video w/ audio -> 16 kHz WAV)
                 -> transcription_service.transcribe (API whisper -> local -> unavailable)
                 -> vision_service.analyze_keyframes (vision LLM, scene+OCR+tags)
                 -> content_dna_service.build_dna    (merge + synthesis)
```

Every step records a status plus a safe user-facing message and technical
detail in `MediaJob.steps` (JSON):

- `completed` - the step ran and produced its result.
- `failed` - the step ran but produced no usable result.
- `degraded` - a usable result exists, but something was incomplete.
- `skipped` - the step was intentionally not attempted.
- `not_applicable` - the step does not apply to this media type.

Steps degrade independently: a failed transcription does not abort vision
analysis, and a failed vision call does not erase a previous successful
analysis during a retry.

## Honest status model

**Asset statuses:** `uploaded | processing | ready | partial | failed`

- `ready` - all applicable analysis steps completed and Content DNA exists.
- `partial` - Content DNA exists, but at least one applicable step failed or
  degraded. Partial results remain usable and retryable.
- `failed` - no usable Content DNA exists.

Metadata/probe success alone never makes an asset `ready`. A vision failure is
never reported as a successful empty analysis. Scores with no supporting text
are `null` ("not evaluated"), never fabricated zeros.

**Job statuses:** `pending | processing | completed | failed`. A completed job
can still describe partial analysis; read the step statuses and the asset
status for the full picture.

## Background processing

The original roadmap called for Redis + Celery. Processing uses **FastAPI
`BackgroundTasks` plus a `MediaJob` status table** - no external broker. The
orchestration is isolated in `media_service.enqueue_processing`, so swapping
to Celery/Redis later is a single-function change.

Limitation: background tasks do not survive a process restart. On startup
(`lifespan`), `recover_stale_jobs` marks any job stuck in `processing/pending`
as `failed` with a `recovery` step. Its asset becomes `partial` if prior DNA
exists, otherwise `failed`.

## Vision + OCR (single call)

Each keyframe is sent to the vision-capable LLM through the provider
abstraction:

- `LLM_PROVIDER=gemini` uses `GEMINI_API_KEY` and the official `google-genai`
  SDK.
- `LLM_PROVIDER=openai` uses any OpenAI-compatible endpoint configured with
  `LLM_API_KEY` and `LLM_BASE_URL`.
- `VISION_MODEL` overrides the model used for images; otherwise `LLM_MODEL`
  is used.

The model returns a strict `LLMImageAnalysis`: scene description, on-screen
text (OCR), visual tags, dominant colors, and a text-heavy flag. Provider
errors are classified as `configuration`, `auth`, `rate_limit`, `timeout`,
`unavailable`, `network`, `invalid_request`, or `invalid_response`; raw
provider bodies and credentials are never exposed.

An empty `LLMImageAnalysis` is treated as a failed step, not a success. This
prevents an all-optional schema from turning `{}` into a fake analysis.

## Retry analysis

`POST /api/media/assets/{id}/retry` starts a fresh job without re-uploading.

- While a pending/processing job exists, the endpoint returns that job with
  `deduplicated: true` instead of queueing duplicates.
- The original file must still exist; otherwise the API returns `409`.
- Successful transcript/scene/OCR/tag data from an earlier run is preserved
  when a retry step fails. A temporary provider outage does not erase working
  analysis.
- The per-process lock makes the check-then-create safe within one worker.
  For multiple workers, add a database-level partial unique index on active
  jobs.

## Content DNA

`ContentDNA` (one row per asset) stores:

- `transcript`, `language`
- `scene_description`, `ocr_text`, `visual_tags`
- `keyframe_analyses` (per-frame JSON), `keyframes` (indexes)
- `hook_score`, `clarity_score`, `brand_alignment` - **NULL = not evaluated**
- `raw_analysis` - latest synthesis plus a nested `insights` object

The public DNA response adds an `insights` view:

- summary, topic, main message, content format
- key points and strategy signals
- recommendations with the evidence they are based on
- per-axis score objects (`value`, `status`, `meaning`, `source`, `reason`)
- brand-profile status and audience

Hook/clarity are evaluated from the transcript or on-screen text only. Brand
alignment is evaluated only when an active brand profile has usable guidance.
These are defined heuristic estimates, not measured performance.

`POST /api/media/assets/{id}/content` creates a linked `Content` record
(source=`media`) using optional overrides or the synthesis suggestion. It is
only allowed for `ready`/`partial` assets with real analysis signals.

## API endpoints

| Method | Path | Purpose |
|--------|------|---------|
| POST   | `/api/media/upload` | Multipart upload (`file`, `analyze`); returns asset + job |
| GET    | `/api/media/assets` | List own assets (`media_type`, `status`, pagination) |
| GET    | `/api/media/assets/{id}` | Asset detail + DNA insights + jobs |
| GET    | `/api/media/assets/{id}/file` | Owner-only original-file preview (JWT required) |
| POST   | `/api/media/assets/{id}/retry` | Queue analysis again; idempotent while active |
| DELETE | `/api/media/assets/{id}` | Delete asset, DNA, jobs, and stored file |
| GET    | `/api/media/jobs` | List own jobs |
| GET    | `/api/media/jobs/{id}` | Job detail with step results |
| POST   | `/api/media/assets/{id}/content` | Create Content from usable DNA |

All routes require a bearer token and are scoped to the authenticated user.
Responses never expose storage paths or raw provider/exception details. The
preview endpoint only renders browser-safe image/video/audio MIME types inline;
anything else is served as an attachment with `X-Content-Type-Options: nosniff`.

## Environment variables (media)

| Variable | Default | Meaning |
|----------|---------|---------|
| `LLM_PROVIDER` | `openai` | `gemini`, `openai`, `heuristic`, or `none` |
| `GEMINI_API_KEY` | *(empty)* | Required for `LLM_PROVIDER=gemini` |
| `LLM_API_KEY` | *(empty)* | Required for `LLM_PROVIDER=openai` |
| `LLM_MODEL` | `gpt-4o-mini` | Text model; also default vision model |
| `VISION_MODEL` | *(empty -> `LLM_MODEL`)* | Optional vision-model override |
| `FFMPEG_PATH` | `ffmpeg` | ffmpeg binary (name on PATH or absolute path) |
| `FFPROBE_PATH` | `ffprobe` | ffprobe binary |
| `MEDIA_UPLOADS_DIR` | `backend/uploads` | Upload root (per-user `user_{id}/` dirs) |
| `MEDIA_MAX_VIDEO_MB` | `500` | Size cap for video/audio uploads |
| `MEDIA_MAX_IMAGE_MB` | `25` | Size cap for image uploads |
| `MEDIA_FFMPEG_TIMEOUT` | `300` | Hard timeout (seconds) for each ffmpeg/ffprobe call |
| `MEDIA_KEYFRAME_COUNT` | `4` | Number of keyframes to extract from video |
| `WHISPER_PROVIDER` | `auto` | `auto`, `api`, `local`, or `none` |
| `WHISPER_API_MODEL` | `whisper-1` | Model name for the transcription API |
| `WHISPER_LOCAL_MODEL` | `base` | faster-whisper model size (if installed) |

`GET /api/health` reports a `media` section. It includes whether vision is
configured and the effective vision model, without exposing keys. Startup also
logs missing-provider warnings and marks interrupted media jobs.

## Supported media types

- **Video**: `.mp4 .mov .m4v .webm .avi .mkv` (or `video/*` MIME)
- **Image**: `.jpg .jpeg .png .webp .gif .bmp` (or `image/*` MIME)
- **Audio**: `.mp3 .wav .m4a .aac .ogg .flac` (or `audio/*` MIME)

Unknown extensions fall back to `video` so ffprobe gets a chance. Audio-only
assets mark keyframe extraction and vision as `not_applicable`; images mark
audio extraction and transcription as `not_applicable`.

## Setup

1. Install ffmpeg/ffprobe and ensure they are on `PATH` (or set
   `FFMPEG_PATH`/`FFPROBE_PATH`). Without them, probe/keyframe/audio steps
   fail honestly and the asset becomes partial/failed instead of appearing
   fully analyzed.
2. Set `LLM_PROVIDER=gemini` and `GEMINI_API_KEY`, or configure an
   OpenAI-compatible provider. Without a provider, uploads are still stored
   and can be retried after configuration.
3. Backend: no new Python dependencies are required for the default
   API-vision configuration. Optional local transcription:
   `pip install faster-whisper`.
4. Frontend: no new dependencies. The Media Library is at `/media` and
   includes blob-based authenticated previews, honest per-step status, retry,
   and DNA insights.

## Database migration

Phase 2 adds three tables - `media_asset`, `media_job`, `content_dna` - via
SQLAlchemy `create_all` on startup (additive; existing tables and data are
untouched). No Alembic migration is required for the current schema. New
non-column status values (`partial`) and JSON step fields require no DDL.

## Testing

All AI calls are mocked in tests (no network, no paid API usage). FFmpeg is
exercised for real when the binary is present; those tests skip automatically
if it is missing.

```bash
cd backend

# Full suite (Phase 1 + Phase 2)
.venv/Scripts/python -m pytest tests/ -q

# Phase 2 only
.venv/Scripts/python -m pytest tests/test_media_storage.py tests/test_media_ai.py tests/test_media_api.py tests/test_content_dna.py tests/test_gemini_provider.py -q
```

Frontend:

```bash
cd frontend
npm run build
npm run lint
npm run test
```

## Known limitations

- Background jobs are in-process; a hard crash loses in-flight work (jobs are
  marked failed on next startup). Swap `enqueue_processing` for Celery/Redis
  when horizontal scaling is needed.
- OCR and scene understanding depend on the configured vision model; no
  offline OCR is provided.
- Local transcription (`faster-whisper`) is optional and not installed by
  default. When transcription is unavailable, video/audio assets are
  `partial` rather than pretending to be complete.
- Retry deduplication is guaranteed per process. Use a database partial
  unique index before running multiple workers.
- DNA quality scores are heuristic estimates from available text, not
  measured performance metrics. They are null when no supporting text exists.
- Original uploads and extracted work files live on local disk. Deployments
  without persistent storage lose media on restart or redeploy; point
  `MEDIA_UPLOADS_DIR` at a persistent volume in production.
- The Media Library preview downloads the original as an authenticated blob,
  so very large videos may take time to appear and use browser memory.
