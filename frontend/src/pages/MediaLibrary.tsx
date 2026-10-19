import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'

import { api, apiErrorMessage } from '../api'
import { Card, Chip, EmptyState, ErrorNote, SectionHeader, Spinner } from '../components/ui'
import type { MediaAsset, MediaAssetDetail, MediaAssetListResponse } from '../types'

const ACCEPT = '.mp4,.mov,.m4v,.webm,.avi,.mkv,.jpg,.jpeg,.png,.webp,.gif,.bmp,.mp3,.wav,.m4a,.aac,.ogg,.flac'
const MAX_MB = 500

const STEP_LABELS: Record<string, string> = {
  ffmpeg_probe: 'Metadata probe',
  keyframes: 'Keyframe extraction',
  audio_extract: 'Audio extraction',
  transcribe: 'Transcription',
  vision: 'Vision analysis',
  dna: 'Content DNA',
  recovery: 'Crash recovery',
}

function statusTone(status: string) {
  if (status === 'ready' || status === 'completed' || status === 'ok') return 'success' as const
  if (status === 'processing' || status === 'pending' || status === 'degraded') return 'warning' as const
  if (status === 'failed') return 'error' as const
  return 'default' as const
}

function fmtBytes(bytes: number) {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${bytes} B`
}

function fmtDuration(seconds: number | null) {
  if (seconds == null) return '—'
  const m = Math.floor(seconds / 60)
  const s = Math.round(seconds % 60)
  return `${m}:${String(s).padStart(2, '0')}`
}

export function MediaLibrary() {
  const [assets, setAssets] = useState<MediaAsset[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [dragOver, setDragOver] = useState(false)
  const [selected, setSelected] = useState<MediaAssetDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [pollHandle, setPollHandle] = useState<number | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const load = useCallback(async () => {
    try {
      const { data } = await api.get<MediaAssetListResponse>('/media/assets', { params: { limit: 50 } })
      setAssets(data.items)
      setTotal(data.total)
      setError(null)
    } catch (err) {
      setError(apiErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  // poll while any asset is still processing
  useEffect(() => {
    const needsPoll = assets.some((a) => a.status === 'processing' || a.status === 'uploaded')
    if (needsPoll && pollHandle == null) {
      const id = window.setInterval(() => {
        void load()
        if (selected) void loadDetail(selected.id, true)
      }, 2500)
      setPollHandle(id)
    } else if (!needsPoll && pollHandle != null) {
      window.clearInterval(pollHandle)
      setPollHandle(null)
    }
    return () => {
      if (pollHandle != null) window.clearInterval(pollHandle)
    }
  }, [assets, selected, pollHandle, load])

  async function loadDetail(id: number, silent = false) {
    if (!silent) setDetailLoading(true)
    try {
      const { data } = await api.get<MediaAssetDetail>("/media/assets/" + id)
      setSelected(data)
    } catch (err) {
      if (!silent) setError(apiErrorMessage(err))
    } finally {
      if (!silent) setDetailLoading(false)
    }
  }

  async function uploadFile(file: File, analyze = true) {
    if (file.size > MAX_MB * 1024 * 1024) {
      setUploadError(`File is larger than ${MAX_MB} MB.`)
      return
    }
    setUploading(true)
    setUploadError(null)
    try {
      const form = new FormData()
      form.append('file', file)
      form.append('analyze', String(analyze))
      await api.post('/media/upload', form, { timeout: 120_000 })
      await load()
    } catch (err) {
      setUploadError(apiErrorMessage(err))
    } finally {
      setUploading(false)
    }
  }

  function onFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (file) void uploadFile(file)
    e.target.value = ''
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault()
    setDragOver(false)
    const file = e.dataTransfer.files?.[0]
    if (file) void uploadFile(file)
  }

  async function remove(id: number) {
    if (!window.confirm('Delete this asset and its extracted data?')) return
    try {
      await api.delete(`/media/assets/${id}`)
      setSelected(null)
      await load()
    } catch (err) {
      setError(apiErrorMessage(err))
    }
  }

  return (
    <>
      <SectionHeader
        title="Media Library"
        subtitle="Upload videos, images, or audio. ContentMind extracts metadata, transcribes speech, analyses frames, and builds Content DNA."
      />

      <div className="grid gap-5 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <Card
            className={`transition-colors ${dragOver ? 'border-primary-500' : ''}`}
            hover
          >
            <div
              onDragOver={(e) => {
                e.preventDefault()
                setDragOver(true)
              }}
              onDragLeave={() => setDragOver(false)}
              onDrop={onDrop}
              className="flex flex-col items-center justify-center gap-3 py-8 text-center"
            >
              <div className="flex h-12 w-12 items-center justify-center rounded-full border border-border-medium text-lg text-text-tertiary">
                +
              </div>
              <div>
                <div className="text-sm font-medium">Drop a file here, or</div>
                <div className="mt-0.5 text-xs text-text-tertiary">
                  Video, image, or audio · up to {MAX_MB} MB
                </div>
              </div>
              <input
                ref={fileRef}
                type="file"
                accept={ACCEPT}
                className="hidden"
                onChange={onFileChange}
              />
              <button
                type="button"
                className="btn btn-primary"
                disabled={uploading}
                onClick={() => fileRef.current?.click()}
              >
                {uploading ? 'Uploading…' : 'Choose file'}
              </button>
              {uploading && <Spinner label="Storing and enqueueing analysis…" />}
            </div>
          </Card>

          {uploadError && <ErrorNote message={uploadError} />}
          {error && <ErrorNote message={error} />}

          {loading ? (
            <Card>
              <Spinner label="Loading assets…" />
            </Card>
          ) : assets.length === 0 ? (
            <EmptyState
              title="No media yet"
              body="Upload a video or image to see transcription, vision analysis, and Content DNA appear here."
            />
          ) : (
            <div className="space-y-2.5">
              <div className="flex items-baseline justify-between text-xs text-text-tertiary">
                <span>
                  {total} asset{total === 1 ? '' : 's'}
                </span>
              </div>
              {assets.map((asset) => (
                <Card
                  key={asset.id}
                  hover
                  className={`cursor-pointer ${selected?.id === asset.id ? 'border-primary-500/60' : ''}`}
                >
                  <button
                    type="button"
                    className="w-full text-left"
                    onClick={() => void loadDetail(asset.id)}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="truncate text-sm font-medium">{asset.filename}</div>
                        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-text-tertiary">
                          <span className="uppercase">{asset.media_type}</span>
                          <span>{fmtBytes(asset.file_size)}</span>
                          {asset.media_type === 'video' && <span>{fmtDuration(asset.duration_seconds)}</span>}
                          {asset.width != null && asset.height != null && (
                            <span>
                              {asset.width}×{asset.height}
                            </span>
                          )}
                          <span>{new Date(asset.created_at).toLocaleDateString()}</span>
                        </div>
                      </div>
                      <div className="flex shrink-0 items-center gap-2">
                        {asset.has_dna && <Chip tone="primary">DNA</Chip>}
                        <Chip tone={statusTone(asset.status)}>{asset.status}</Chip>
                      </div>
                    </div>
                  </button>
                </Card>
              ))}
            </div>
          )}

        </div>

        <div className="space-y-4">
          {detailLoading ? (
            <Card>
              <Spinner label="Loading asset…" />
            </Card>
          ) : selected ? (
            <AssetDetail asset={selected} onDelete={() => void remove(selected.id)} />
          ) : (
            <Card>
              <h2 className="text-sm font-semibold">How it works</h2>
              <ol className="mt-3 space-y-2.5 text-sm text-text-tertiary">
                {[
                  'The file is stored safely and probed for duration and streams.',
                  'Keyframes are extracted and analysed with the vision model.',
                  'Speech is transcribed (API or local fallback).',
                  'Transcript + frames are combined into Content DNA.',
                  'You can then create a Content record from the DNA.',
                ].map((step, i) => (
                  <li key={step} className="flex gap-2.5">
                    <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-border-medium text-[0.65rem] text-text-tertiary">
                      {i + 1}
                    </span>
                    {step}
                  </li>
                ))}
              </ol>
              <p className="mt-4 text-[0.68rem] text-text-tertiary">
                Processing runs in the background. The job panel shows each step's outcome.
              </p>
            </Card>
          )} 
        </div>
      </div>
    </>  )
}

function AssetDetail({ asset, onDelete }: { asset: MediaAssetDetail; onDelete: () => void }) {
  const [creating, setCreating] = useState(false)
  const [created, setCreated] = useState<number | null>(null)
  const [createError, setCreateError] = useState<string | null>(null)
  const latestJob = asset.jobs[0]

  async function createContent() {
    setCreating(true)
    setCreateError(null)
    try {
      const { data } = await api.post<{ id: number }>(`/media/assets/${asset.id}/content`, {
        title: undefined,
        analyze: true,
      })
      setCreated(data.id)
    } catch (err) {
      setCreateError(apiErrorMessage(err))
    } finally {
      setCreating(false)
    }
  }

  return (
    <>
      <Card>
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="truncate text-sm font-semibold">{asset.filename}</div>
            <div className="mt-1 text-xs text-text-tertiary">
              {asset.media_type} · {fmtBytes(asset.file_size)}
              {asset.duration_seconds != null && ` · ${fmtDuration(asset.duration_seconds)}`}
            </div>
          </div>
          <Chip tone={statusTone(asset.status)}>{asset.status}</Chip>
        </div>

        {latestJob && (
          <div className="mt-4">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-text-tertiary">Pipeline steps</h3>
            <div className="mt-2 space-y-1.5">
              {Object.entries(latestJob.steps).map(([key, step]) => (
                <div key={key} className="flex items-center justify-between gap-2 text-xs">
                  <span className="text-text-tertiary">{STEP_LABELS[key] ?? key}</span>
                  <span className="flex items-center gap-2">
                    {step.detail && <span className="max-w-[10rem] truncate text-text-tertiary">{step.detail}</span>}
                    <Chip tone={statusTone(step.status)}>{step.status}</Chip>
                  </span>
                </div>
              ))}
            </div>
            {latestJob.status === 'processing' && (
              <div className="mt-3">
                <Spinner label="Processing…" />
              </div>
            )}
            {latestJob.error && (
              <p className="mt-3 text-xs text-warning-500">{latestJob.error}</p>
            )}
          </div>
        )}
      </Card>

      {asset.dna && (
        <Card>
          <h3 className="text-sm font-semibold">Content DNA</h3>
          {asset.dna.transcript && (
            <div className="mt-3">
              <div className="text-xs font-semibold uppercase tracking-wider text-text-tertiary">
                Transcript {asset.dna.language && `(${asset.dna.language})`}
              </div>
              <p className="mt-1 max-h-40 overflow-y-auto whitespace-pre-wrap text-sm text-text-tertiary">
                {asset.dna.transcript}
              </p>
            </div>
          )}
          {asset.dna.scene_description && (
            <div className="mt-3">
              <div className="text-xs font-semibold uppercase tracking-wider text-text-tertiary">Scenes</div>
              <p className="mt-1 text-sm text-text-tertiary">{asset.dna.scene_description}</p>
            </div>
          )}
          {asset.dna.ocr_text && (
            <div className="mt-3">
              <div className="text-xs font-semibold uppercase tracking-wider text-text-tertiary">On-screen text</div>
              <p className="mt-1 whitespace-pre-wrap text-sm text-text-tertiary">{asset.dna.ocr_text}</p>
            </div>
          )}
          {asset.dna.visual_tags.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-1.5">
              {asset.dna.visual_tags.map((tag) => (
                <Chip key={tag} tone="primary">{tag}</Chip>
              ))}
            </div>
          )}
          <div className="mt-4 flex flex-wrap gap-1.5 text-[0.68rem] text-text-tertiary">
            <span>hook {asset.dna.hook_score ?? 'not evaluated'}</span>
            <span>·</span>
            <span>clarity {asset.dna.clarity_score ?? 'not evaluated'}</span>
            <span>·</span>
            <span>brand {asset.dna.brand_alignment ?? 'not evaluated'}</span>
          </div>
        </Card>
      )}

      <Card>
        {created != null ? (
          <div className="text-sm">
            <span className="text-success-600 dark:text-success-400">Content record created.</span>{' '}
            <Link to="/content" className="text-primary-400 hover:underline">
              Open in library →
            </Link>
          </div>
        ) : (
          <>
            {createError && <div className="mb-3"><ErrorNote message={createError} /></div>}
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                className="btn btn-primary"
                disabled={creating || !asset.has_dna || asset.status !== 'ready'}
                onClick={() => void createContent()}
              >
                {creating ? 'Creating…' : 'Create content from DNA'}
              </button>
              <button type="button" className="btn btn-secondary" onClick={onDelete}>
                Delete asset
              </button>
            </div>
            {!asset.has_dna && (
              <p className="mt-2 text-xs text-text-tertiary">
                DNA is still being built. This becomes available once processing finishes.
              </p>
            )}
          </>
        )}
      </Card>
    </>
  )
}