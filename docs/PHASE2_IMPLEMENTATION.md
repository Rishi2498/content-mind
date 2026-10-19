# Phase 2 Implementation — Advanced Ingestion & Media Intelligence

Phase 2 adds a media pipeline to ContentMind: users upload video, image, or
audio files; the backend extracts metadata, keyframes, and speech; a vision
LLM analyses frames (scene + OCR); and everything is combined into a
structured **Content DNA** record. A Content record can then be created from
the DNA with one click.

## Architecture

```
POST /api/media/upload
  └─ media_storage.save_upload        (path-confined, size-limited, streamed)
       └─ create MediaAsset + MediaJob (status=pending)
            └─ BackgroundTasks → process_asset()
                 ├─ ffmpeg_service.probe            (duration/streams)
                 ├─ ffmpeg_service.extract_keyframes (video only; image = itself)
                 ├─ ffmpeg_service.extract_audio     (video w/ audio → 16 kHz WAV)
                 ├─ transcription_service.transcribe (API whisper → local → degrade)
                 ├─ vision_service.analyze_keyframes (vision LLM, scene+OCR+tags)
                 └─ content_dna_service.build_dna    (merge + synthesis)
```

Every step's outcome (`ok | failed | skipped | degraded`) is recorded in
`MediaJob.steps` (JSON) so the UI can show exactly what happened. Steps
degrade independently: a failed transcription does not abort vision analysis.

### Background processing (approved deviation from Redis + Celery)

The original roadmap called for Redis + Celery. Per the approved Phase 2
plan, processing uses **FastAPI `BackgroundTasks` plus a `MediaJob` status
table** — no external broker. The orchestration is isolated in
`media_service.enqueue_processing`, so swapping to Celery/Redis later is a
single-function change.

Limitation: background tasks do not survive a process restart. On startup
(`lifespan`), `recover_stale_jobs` marks any job stuck in
`processing/pending` as `failed` with step `recovery: failed`, and its asset
as `failed`. No orphaned "processing" states remain.

### Transcription (hybrid)

Controlled by `WHISPER_PROVIDER`:

| Value    | Behaviour |
|----------|-----------|
| `auto`   | Use the OpenAI-compatible `/audio/transcriptions` API when `LLM_API_KEY` is set; else try local `faster-whisper` if installed; else degrade (metadata-only). |
| `api`    | Force the API path; degrade if unavailable. |
| `local`  | Force the local model; degrade if unavailable. |
| `none`   | Skip transcription entirely. |

No transcription path raises; all return a `TranscriptionResult` with
`provider` and `degraded` flags.

### Vision + OCR (single call)

Each keyframe (JPEG) is sent to the vision-capable LLM via the existing
OpenAI-compatible provider (base64 data URL, `complete_vision`). The model
returns a strict `LLMImageAnalysis`: scene description, on-screen text
(OCR), visual tags, dominant colors, text-heavy flag. There is no separate
Tesseract dependency; OCR quality depends on the configured vision model.

An image upload is treated as a single keyframe (the image itself), so the
image pipeline and video pipeline share one code path.

### Content DNA

`ContentDNA` (one row per asset) stores:

- `transcript`, `language`
- `scene_description`, `ocr_text`, `visual_tags`
- `keyframe_analyses` (per-frame JSON), `keyframes` (indexes)
- `hook_score`, `clarity_score`, `brand_alignment` — **NULL = not evaluated**
  (Phase 3 implements real scoring; NULL is deliberately not 0)
- `raw_analysis` (most recent synthesis: title suggestion, topic, summary,
  key points)

`POST /api/media/assets/{id}/content` creates a linked `Content` record
(source=`media`) using optional overrides or the synthesis suggestion.

## API endpoints

| Method | Path | Purpose |
|--------|------|---------|
| POST   | `/api/media/upload` | Multipart upload (`file`, `analyze`); returns asset + job |
| GET    | `/api/media/assets` | List own assets (`media_type`, `status`, pagination) |
| GET    | `/api/media/assets/{id}` | Asset detail + DNA + jobs |
| DELETE | `/api/media/assets/{id}` | Delete asset, DNA, jobs, and stored file |
| GET    | `/api/media/jobs` | List own jobs |
| GET    | `/api/media/jobs/{id}` | Job detail with step results |
| POST   | `/api/media/assets/{id}/content` | Create Content from DNA |

All routes require a bearer token and are scoped to the authenticated user.
Responses never expose storage paths or raw exception details; job `error`
fields contain sanitized messages only.

## Environment variables (media)

| Variable | Default | Meaning |
|----------|---------|---------|
| `FFMPEG_PATH` | `ffmpeg` | ffmpeg binary (name on PATH or absolute path) |
| `FFPROBE_PATH` | `ffprobe` | ffprobe binary |
| `MEDIA_UPLOADS_DIR` | `backend/uploads` | Upload root (per-user subdirs `user_{id}/`) |
| `MEDIA_MAX_VIDEO_MB` | `500` | Size cap for video/audio uploads |
| `MEDIA_MAX_IMAGE_MB` | `25` | Size cap for image uploads |
| `MEDIA_FFMPEG_TIMEOUT` | `300` | Hard timeout (seconds) for each ffmpeg/ffprobe call |
| `MEDIA_KEYFRAME_COUNT` | `4` | Number of keyframes to extract from video |
| `WHISPER_PROVIDER` | `auto` | `auto` \| `api` \| `local` \| `none` |
| `WHISPER_API_MODEL` | `whisper-1` | Model name sent to the transcription API |
| `WHISPER_LOCAL_MODEL` | `base` | faster-whisper model size (if installed) |
| `VISION_MODEL` | *(empty → `LLM_MODEL`)* | Optional override for vision requests |

`GET /api/health` reports a `media` section (upload limits, whisper policy).

## Supported media types

- **Video**: `.mp4 .mov .m4v .webm .avi .mkv` (or `video/*` MIME)
- **Image**: `.jpg .jpeg .png .webp .gif .bmp` (or `image/*` MIME)
- **Audio**: `.mp3 .wav .m4a .aac .ogg .flac` (or `audio/*` MIME)

Unknown extensions fall back to `video` so ffprobe still gets a chance; a
file ffprobe cannot read fails the `ffmpeg_probe` step (degraded/failed) and
the job still completes with whatever steps succeeded.

## Setup

1. Install ffmpeg/ffprobe and ensure they are on `PATH` (or set
   `FFMPEG_PATH`/`FFPROBE_PATH`). Without them, probe/keyframe/audio steps
   are marked failed/skipped and the pipeline still completes (degraded).
2. Backend: no new Python dependencies are required for the default
   (API-vision, no-local-whisper) configuration. Optional local
   transcription: `pip install faster-whisper`.
3. Frontend: no new dependencies. The Media Library is at `/media`.

## Database migration

Phase 2 adds three tables — `media_asset`, `media_job`, `content_dna` — via
SQLAlchemy `create_all` on startup (additive; existing tables and data are
untouched). No Alembic; no destructive migration. `content_dna.user_id` and
`media_*` rows carry `user_id` foreign keys for tenant isolation.

## Testing

All AI calls are mocked in tests (no network, no paid API usage). FFmpeg is
exercised for real when the binary is present; those tests skip automatically
if it is missing.

```bash
cd backend

# Full suite (Phase 1 + Phase 2)
.venv/Scripts/python -m pytest tests/ -q

# Phase 2 only
.venv/Scripts/python -m pytest tests/test_media_storage.py tests/test_media_ai.py tests/test_media_api.py -q
```

Frontend type-check and build:

```bash
cd frontend
node_modules/.bin/tsc.cmd --noEmit -p tsconfig.app.json
node_modules/.bin/vite.cmd build
```

## Known limitations

- Background jobs are in-process; a hard crash loses in-flight work (jobs are
  marked failed on next startup). Swap `enqueue_processing` for Celery/Redis
  when horizontal scaling is needed.
- OCR and scene understanding depend on the configured vision model; no
  offline OCR is provided.
- Local transcription (`faster-whisper`) is optional and not installed by
  default; the default path is the API when `LLM_API_KEY` is set, otherwise
  metadata-only mode.
- Reviewer scores on Content DNA are NULL until Phase 3.
