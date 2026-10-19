import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'

import { api, apiErrorMessage } from '../api'
import { useAuth } from '../context/AuthContext'
import { startInstagramConnect } from '../utils/connect'
import { parseOAuthCallback } from '../utils/oauth'
import {
  Card,
  CardHeader,
  Chip,
  EmptyState,
  ErrorNote,
  PageHeader,
  PreviewTile,
  SegmentedControl,
  Skeleton,
  Stat,
  SuccessNote,
} from '../components/ui'
import type {
  InstagramAccountInsights,
  InstagramConnection,
  InstagramPost,
  InstagramSyncJob,
} from '../types'

type ChipTone = 'default' | 'primary' | 'success' | 'warning' | 'error'

const STATUS_TONE: Record<string, ChipTone> = {
  connected: 'success',
  disconnected: 'default',
  error: 'error',
  pending: 'primary',
  running: 'primary',
  succeeded: 'success',
  partially_succeeded: 'warning',
  failed: 'error',
}

const SYNC_STATUS_LABEL: Record<string, string> = {
  pending: 'Pending',
  running: 'Running',
  succeeded: 'Succeeded',
  partially_succeeded: 'Partial',
  failed: 'Failed',
}

const POSTS_PER_PAGE = 25

export function Instagram() {
  const navigate = useNavigate()
  const { logout } = useAuth()
  const [searchParams, setSearchParams] = useSearchParams()

  const [connections, setConnections] = useState<InstagramConnection[]>([])
  const [selectedConnection, setSelectedConnection] = useState<InstagramConnection | null>(null)
  const [posts, setPosts] = useState<InstagramPost[]>([])
  const [syncJobs, setSyncJobs] = useState<InstagramSyncJob[]>([])
  const [insights, setInsights] = useState<InstagramAccountInsights | null>(null)
  const [loading, setLoading] = useState(true)
  const [syncing, setSyncing] = useState(false)
  const [connecting, setConnecting] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [insightsPeriod, setInsightsPeriod] = useState<'day' | 'week' | 'days_28'>('day')
  const [postsPage, setPostsPage] = useState(0)
  const [postsTotal, setPostsTotal] = useState(0)

  // Handle OAuth callback query params (?connected / ?error / ?error_code)
  useEffect(() => {
    const result = parseOAuthCallback(searchParams)
    if (result.status === 'none') return

    setSearchParams({}, { replace: true })
    if (result.status === 'connected') {
      setNotice(`Successfully connected Instagram account! (ID: ${result.connectionId})`)
      loadConnections()
    } else if (result.status === 'cancelled') {
      setNotice(result.message)
    } else {
      setError(result.message)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams, setSearchParams])

  const loadConnections = useCallback(async () => {
    try {
      const resp = await api.get('/instagram/connections')
      setConnections(resp.data.items)
    } catch (e) {
      setError(apiErrorMessage(e))
    } finally {
      setLoading(false)
    }
  }, [])

  const loadPosts = useCallback(async (connectionId: number, offset: number) => {
    try {
      const resp = await api.get(
        `/instagram/connections/${connectionId}/posts?limit=${POSTS_PER_PAGE}&offset=${offset}`,
      )
      setPosts(resp.data.items)
      setPostsTotal(resp.data.total)
    } catch (e) {
      setError(apiErrorMessage(e))
    }
  }, [])

  const loadConnectionDetails = useCallback(
    async (connectionId: number, page = 0) => {
      try {
        const [connResp, jobsResp] = await Promise.all([
          api.get(`/instagram/connections/${connectionId}`),
          api.get(`/instagram/connections/${connectionId}/sync-history?limit=10`),
        ])
        setSelectedConnection(connResp.data)
        setSyncJobs(jobsResp.data.items)
        setPostsPage(page)
        await loadPosts(connectionId, page * POSTS_PER_PAGE)
      } catch (e) {
        setError(apiErrorMessage(e))
      }
    },
    [loadPosts],
  )

  const loadInsights = useCallback(async () => {
    if (!selectedConnection) return
    try {
      const resp = await api.get(
        `/instagram/connections/${selectedConnection.id}/insights?period=${insightsPeriod}`,
      )
      setInsights(resp.data)
    } catch (e) {
      // Insights may fail due to permissions; don't show as global error
      console.warn('Failed to load insights:', apiErrorMessage(e))
      setInsights(null)
    }
  }, [selectedConnection, insightsPeriod])

  const handleSync = useCallback(async () => {
    if (!selectedConnection || syncing) return
    setSyncing(true)
    setError('')
    setNotice('')
    try {
      const resp = await api.post<{ job: InstagramSyncJob; connection_id: number }>(
        `/instagram/connections/${selectedConnection.id}/sync`,
        { max_posts: 50 },
      )
      setSyncJobs((prev) => [resp.data.job, ...prev])
      await loadConnectionDetails(selectedConnection.id, 0)
      setNotice('Sync completed successfully!')
    } catch (e) {
      setError(apiErrorMessage(e))
    } finally {
      setSyncing(false)
    }
  }, [selectedConnection, syncing, loadConnectionDetails])

  const handleDisconnect = useCallback(async () => {
    if (!selectedConnection) return
    if (!window.confirm(`Disconnect @${selectedConnection.username}? This will remove stored tokens and stop syncs.`)) {
      return
    }
    try {
      await api.delete(`/instagram/connections/${selectedConnection.id}`)
      setNotice(`Disconnected @${selectedConnection.username}`)
      setSelectedConnection(null)
      setPosts([])
      setSyncJobs([])
      setInsights(null)
      await loadConnections()
    } catch (e) {
      setError(apiErrorMessage(e))
    }
  }, [selectedConnection, loadConnections])

  const handleConnect = useCallback(async () => {
    setConnecting(true)
    setError('')
    // Authorize is a protected JSON endpoint: the API client fetches it with
    // the JWT, then we hand the browser to Meta (a direct navigation would
    // carry no token). See startInstagramConnect for the tested logic.
    await startInstagramConnect({
      requestAuthorize: () => api.get('/instagram/authorize'),
      navigate: (path) => navigate(path),
      assign: (url) => {
        window.location.href = url
      },
      onSessionExpired: () => {
        setConnecting(false)
        logout()
      },
      onError: (message) => {
        setConnecting(false)
        setError(message)
      },
    })
  }, [navigate, logout])

  useEffect(() => {
    loadConnections()
  }, [loadConnections])

  useEffect(() => {
    loadInsights()
  }, [loadInsights])

  const goToPage = (page: number) => {
    if (!selectedConnection) return
    setPostsPage(page)
    loadPosts(selectedConnection.id, page * POSTS_PER_PAGE)
  }

  if (loading) {
    return (
      <>
        <PageHeader title="Instagram" subtitle="Connect your professional account to sync media and metrics" />
        <div className="grid gap-4 sm:grid-cols-2">
          <Skeleton className="h-28" />
          <Skeleton className="h-28" />
        </div>
      </>
    )
  }

  const lastJob = syncJobs[0]

  return (
    <>
      <PageHeader
        eyebrow="Channels"
        title="Instagram"
        subtitle="Connect your Instagram Professional account to automatically import media and sync performance metrics."
        actions={
          <button className="btn btn-primary" onClick={handleConnect} disabled={connecting}>
            {connecting ? (
              <>
                <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white" />
                Connecting…
              </>
            ) : connections.length === 0 ? (
              'Connect Instagram'
            ) : (
              'Add another account'
            )}
          </button>
        }
      />

      {error && <div className="mb-5"><ErrorNote message={error} /></div>}
      {notice && <div className="mb-5"><SuccessNote message={notice} /></div>}

      {/* Connections */}
      {connections.length === 0 ? (
        <EmptyState
          icon="◎"
          title="No Instagram accounts connected"
          body="Connect an Instagram Professional account to start importing media and syncing metrics. You'll be redirected to Meta for authorization."
          action={
            <button className="btn btn-primary" onClick={handleConnect} disabled={connecting}>
              Connect Instagram
            </button>
          }
        />
      ) : (
        <div className="mb-5 grid gap-4 sm:grid-cols-2">
          {connections.map((conn) => {
            const selected = selectedConnection?.id === conn.id
            return (
              <button
                key={conn.id}
                type="button"
                onClick={() => loadConnectionDetails(conn.id)}
                className={`card text-left transition-all ${
                  selected
                    ? 'border-primary-500 ring-1 ring-primary-500 dark:border-primary-400'
                    : 'hover:border-border-strong'
                }`}
              >
                <div className="flex items-center gap-4 p-5">
                  {conn.profile_picture_url ? (
                    <img
                      src={conn.profile_picture_url}
                      alt={conn.username}
                      className="h-12 w-12 shrink-0 rounded-full object-cover ring-2 ring-white dark:ring-ink-800"
                    />
                  ) : (
                    <PreviewTile seed={conn.username} label={`@${conn.username[0]?.toUpperCase() ?? '?'}`} className="h-12 w-12 shrink-0 rounded-full text-sm" />
                  )}
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="truncate text-sm font-semibold text-text-primary">@{conn.username}</span>
                      <Chip tone={STATUS_TONE[conn.status] ?? 'default'}>
                        {conn.status === 'connected' ? 'Active' : conn.status}
                      </Chip>
                    </div>
                    <div className="mt-1 truncate text-xs text-text-tertiary">
                      {conn.account_type} · {conn.media_count ?? '?'} posts ·{' '}
                      {conn.followers_count?.toLocaleString() ?? '?'} followers
                    </div>
                    {conn.last_sync_at && (
                      <div className="mt-1 text-[0.68rem] text-text-quaternary">
                        Last sync: {new Date(conn.last_sync_at).toLocaleString()}
                      </div>
                    )}
                  </div>
                </div>
              </button>
            )
          })}
        </div>
      )}

      {/* Selected connection workspace */}
      {selectedConnection && (
        <div className="space-y-5">
          {/* Account header */}
          <Card className="overflow-hidden">
            <div className="flex flex-wrap items-center gap-4 p-5">
              {selectedConnection.profile_picture_url ? (
                <img
                  src={selectedConnection.profile_picture_url}
                  alt={selectedConnection.username}
                  className="h-14 w-14 rounded-full object-cover ring-2 ring-white dark:ring-ink-800"
                />
              ) : (
                <PreviewTile
                  seed={selectedConnection.username}
                  label={`@${selectedConnection.username[0]?.toUpperCase() ?? '?'}`}
                  className="h-14 w-14 rounded-full"
                />
              )}
              <div className="min-w-0 flex-1">
                <h2 className="text-lg font-semibold text-text-primary">@{selectedConnection.username}</h2>
                <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-text-tertiary">
                  <span>{selectedConnection.account_type}</span>
                  <span aria-hidden="true">·</span>
                  <span>{selectedConnection.media_count ?? '?'} posts</span>
                  <span aria-hidden="true">·</span>
                  <span>{selectedConnection.followers_count?.toLocaleString() ?? '?'} followers</span>
                  <span aria-hidden="true">·</span>
                  <span>{selectedConnection.follows_count?.toLocaleString() ?? '?'} following</span>
                </div>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <button className="btn btn-primary" onClick={handleSync} disabled={syncing}>
                  {syncing ? (
                    <>
                      <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white" />
                      Syncing…
                    </>
                  ) : (
                    'Sync now'
                  )}
                </button>
                <button
                  className="btn btn-ghost text-error-600 hover:bg-error-50 dark:text-error-400"
                  onClick={handleDisconnect}
                >
                  Disconnect
                </button>
              </div>
            </div>

            <div className="grid gap-4 border-t border-border-light px-5 py-4 dark:border-border-medium sm:grid-cols-2 xl:grid-cols-4">
              <Stat label="Posts examined" value={lastJob?.posts_examined ?? 0} hint="last sync" />
              <Stat label="Posts imported" value={lastJob?.posts_imported ?? 0} hint="last sync" tone="brand" />
              <Stat label="Snapshots created" value={lastJob?.snapshots_created ?? 0} hint="last sync" />
              <Stat
                label="Last sync status"
                value={lastJob ? SYNC_STATUS_LABEL[lastJob.status] ?? lastJob.status : 'Never'}
                tone={lastJob ? (STATUS_TONE[lastJob.status] ?? 'default') : 'default'}
                hint={lastJob ? new Date(lastJob.started_at).toLocaleString() : 'no syncs yet'}
              />
            </div>
          </Card>

          {/* Account insights */}
          <Card>
            <CardHeader>
              <div>
                <h2 className="text-sm font-semibold text-text-primary">Account insights</h2>
                <p className="mt-0.5 text-xs text-text-tertiary">Aggregate metrics from Meta's API</p>
              </div>
              <SegmentedControl<'day' | 'week' | 'days_28'>
                size="sm"
                ariaLabel="Insights period"
                value={insightsPeriod}
                onChange={setInsightsPeriod}
                options={[
                  { value: 'day', label: 'Day' },
                  { value: 'week', label: 'Week' },
                  { value: 'days_28', label: '28 days' },
                ]}
              />
            </CardHeader>
            {insights ? (
              <div className="grid gap-4 p-5 sm:grid-cols-2 lg:grid-cols-5">
                <Stat label="Impressions" value={insights.impressions?.toLocaleString() ?? '—'} tone="brand" />
                <Stat label="Reach" value={insights.reach?.toLocaleString() ?? '—'} />
                <Stat label="Profile views" value={insights.profile_views?.toLocaleString() ?? '—'} />
                <Stat label="Followers" value={insights.follower_count?.toLocaleString() ?? '—'} tone="success" />
                <Stat label="Website clicks" value={insights.website_clicks?.toLocaleString() ?? '—'} />
              </div>
            ) : (
              <div className="px-5 pb-5">
                <EmptyState
                  icon="◌"
                  title="No insights available"
                  body="Insights require appropriate permissions and may not be available for all account types."
                />
              </div>
            )}
          </Card>

          {/* Sync history */}
          <Card>
            <CardHeader>
              <div>
                <h2 className="text-sm font-semibold text-text-primary">Sync history</h2>
                <p className="mt-0.5 text-xs text-text-tertiary">Recent sync jobs for this account</p>
              </div>
              <Chip>{syncJobs.length}</Chip>
            </CardHeader>
            {syncJobs.length === 0 ? (
              <div className="px-5 pb-5">
                <EmptyState icon="⟳" title="No sync history" body="Trigger a sync to see history here." />
              </div>
            ) : (
              <div className="divide-y divide-border-light dark:divide-border-medium">
                {syncJobs.map((job) => (
                  <div key={job.id} className="flex flex-wrap items-center gap-x-4 gap-y-2 px-5 py-3.5">
                    <Chip tone={STATUS_TONE[job.status] ?? 'default'}>
                      {SYNC_STATUS_LABEL[job.status] ?? job.status}
                    </Chip>
                    <span className="text-xs text-text-secondary">{new Date(job.started_at).toLocaleString()}</span>
                    {job.completed_at && (
                      <span className="text-[0.68rem] text-text-quaternary">
                        (ended {new Date(job.completed_at).toLocaleTimeString()})
                      </span>
                    )}
                    <div className="ml-auto flex flex-wrap items-center gap-4 text-xs tabular-nums text-text-tertiary">
                      <span>Examined: {job.posts_examined}</span>
                      <span>Imported: {job.posts_imported}</span>
                      <span>Snapshots: {job.snapshots_created}</span>
                      {job.error_category && (
                        <span className="font-medium text-warning-600 dark:text-warning-400">
                          Error: {job.error_category}
                        </span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Card>

          {/* Imported posts */}
          <Card className="overflow-hidden">
            <CardHeader>
              <div>
                <h2 className="text-sm font-semibold text-text-primary">Imported posts</h2>
                <p className="mt-0.5 text-xs text-text-tertiary">
                  Showing {posts.length} of {postsTotal} posts
                </p>
              </div>
            </CardHeader>

            {posts.length === 0 ? (
              <div className="px-5 pb-5">
                <EmptyState
                  icon="▣"
                  title="No posts imported yet"
                  body="Run a sync to import your Instagram media. Only IMAGE, VIDEO, and CAROUSEL_ALBUM types are supported."
                />
              </div>
            ) : (
              <>
                <div className="divide-y divide-border-light dark:divide-border-medium">
                  {posts.map((post) => (
                    <div key={post.id} className="flex flex-wrap items-start gap-4 px-5 py-4">
                      <PreviewTile seed={post.external_id || post.title || String(post.id)} className="h-14 w-14 shrink-0 text-sm" />
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="truncate text-sm font-medium text-text-primary">
                            {post.title || '(no caption)'}
                          </span>
                          <Chip>{post.platform}</Chip>
                        </div>
                        <div className="mt-0.5 text-xs text-text-tertiary">
                          {new Date(post.published_at).toLocaleString()} · {post.external_id}
                        </div>
                        {post.latest_snapshot && (
                          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs tabular-nums text-text-secondary">
                            {post.latest_snapshot.views !== null && <span>Views: {post.latest_snapshot.views.toLocaleString()}</span>}
                            {post.latest_snapshot.impressions !== null && (
                              <span>Impressions: {post.latest_snapshot.impressions.toLocaleString()}</span>
                            )}
                            {post.latest_snapshot.likes !== null && <span>Likes: {post.latest_snapshot.likes.toLocaleString()}</span>}
                            {post.latest_snapshot.comments !== null && <span>Comments: {post.latest_snapshot.comments.toLocaleString()}</span>}
                            {post.latest_snapshot.shares !== null && <span>Shares: {post.latest_snapshot.shares.toLocaleString()}</span>}
                            {post.latest_snapshot.saves !== null && <span>Saves: {post.latest_snapshot.saves.toLocaleString()}</span>}
                          </div>
                        )}
                        {post.url && (
                          <a
                            href={post.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="mt-1.5 inline-block text-xs font-semibold text-primary-600 hover:underline dark:text-primary-400"
                          >
                            View on Instagram →
                          </a>
                        )}
                      </div>
                    </div>
                  ))}
                </div>

                {postsTotal > POSTS_PER_PAGE && (
                  <div className="flex items-center justify-center gap-3 border-t border-border-light px-5 py-3 dark:border-border-medium">
                    <button
                      className="btn btn-ghost btn-sm"
                      onClick={() => goToPage(Math.max(0, postsPage - 1))}
                      disabled={postsPage === 0}
                    >
                      ← Previous
                    </button>
                    <span className="text-xs tabular-nums text-text-tertiary">
                      Page {postsPage + 1} of {Math.ceil(postsTotal / POSTS_PER_PAGE)}
                    </span>
                    <button
                      className="btn btn-ghost btn-sm"
                      onClick={() => goToPage(Math.min(Math.ceil(postsTotal / POSTS_PER_PAGE) - 1, postsPage + 1))}
                      disabled={postsPage >= Math.ceil(postsTotal / POSTS_PER_PAGE) - 1}
                    >
                      Next →
                    </button>
                  </div>
                )}
              </>
            )}
          </Card>
        </div>
      )}
    </>
  )
}
