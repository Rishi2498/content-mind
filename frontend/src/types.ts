/** Mirrors the backend Pydantic schemas in backend/app/schemas.py. */

export interface HealthResponse {
  status: 'ok' | 'degraded'
  version: string
  memory: MemoryStatus
  llm: LLMStatus
  config: Record<string, unknown>
  database: {
    connected: boolean
    error: string | null
    content_count: number
    insight_count: number
  }
}

export interface MemoryStatus {
  backend: string
  available: boolean
  degraded: boolean
  configured: boolean
  bank: string
  memory_count: number
  observation_count: number
  document_count: number
  last_error: string | null
  message: string
}

export interface LLMStatus {
  available: boolean
  provider: string
  model: string
}

export interface GroupStat {
  key: string
  label: string
  count: number
  impressions: number
  engagements: number
  avg_engagement_rate: number
  median_engagement_rate: number
  avg_ctr: number
  index_vs_average: number
}

export interface TopicCoverage {
  topic: string
  count: number
  avg_engagement_rate: number
  index_vs_average: number
  days_since_published: number | null
}

export interface ContentItem {
  id: number
  title: string
  body: string
  platform: string
  content_type: string
  topic: string
  audience: string | null
  status: string
  source: string
  published_at: string
  impressions: number
  likes: number
  comments: number
  shares: number
  clicks: number
  engagement_rate: number
  ctr: number
  engagement_count: number
}

export interface AnalyticsResponse {
  content_count: number
  published_with_metrics: number
  total_impressions: number
  total_engagements: number
  total_clicks: number
  avg_engagement_rate: number
  median_engagement_rate: number
  avg_ctr: number
  top_topic: GroupStat | null
  top_platform: GroupStat | null
  top_content_type: GroupStat | null
  top_audience: GroupStat | null
  by_platform: GroupStat[]
  by_topic: GroupStat[]
  by_content_type: GroupStat[]
  by_audience: GroupStat[]
  topic_coverage: TopicCoverage[]
  over_time: { period: string; content_count: number; impressions: number; engagements: number; engagement_rate: number }[]
  date_range: Record<string, string | null>
  best_content: ContentItem[]
  worst_content: ContentItem[]
  warnings: string[]
}

export interface ContentGap {
  topic: string
  reason: string
  priority: 'high' | 'medium' | 'low'
  score: number
  coverage_count: number
  evidence: string[]
  suggested_formats: string[]
  adjacency: string[]
}

export interface GapResponse {
  gaps: ContentGap[]
  topics_covered: number
  content_items: number
  generated_at: string
  notes: string[]
}

export interface MemoryRecord {
  id: string
  text: string
  type: string
  kind: string
  context: string | null
  entities: string[]
  score: number
  document_id: string | null
  occurred_at: string | null
  backend: string
}

export interface MemoryRecallResponse {
  query: string
  memories: MemoryRecord[]
  backend: string
  degraded: boolean
  total_available: number | null
}

export interface LearnedInsight {
  id: string
  text: string
  category: string
  origin: string
  confidence: number
  evidence: string
  content_id: number | null
  created_at: string
}

export interface LearnedResponse {
  total: number
  memory_count: number
  content_analyzed: number
  insights: LearnedInsight[]
  categories: Record<string, LearnedInsight[]>
  degraded: boolean
  message: string
}

export interface PlanItem {
  id?: number
  date: string
  platform: string
  topic: string
  format: string
  title: string
  description: string
  reason: string
  memory_used: string[]
}

export interface ContentPlan {
  id?: number
  title: string
  strategy_summary: string
  start_date: string
  end_date: string
  date_range: string
  total_items: number
  used_memory: boolean
  used_historical: boolean
  gaps_considered: string[]
  items: PlanItem[]
}

export interface PlanGenerateResponse {
  plan: ContentPlan
  memory_used: MemoryRecord[]
  gaps: ContentGap[]
  context_summary: Record<string, unknown>
  explanation: string
}

export interface ChatResponse {
  answer: string
  confidence: string
  memory_count: number
  content_analyzed: number
  memories_used: MemoryRecord[]
  suggestions: string[]
  data_used: Record<string, unknown>
}

export interface ContentCreate {
  title: string
  body: string
  platform: string
  content_type: string
  topic: string
  audience?: string
  status?: string
  published_at?: string
  impressions: number
  likes: number
  comments: number
  shares: number
  clicks: number
  analyze?: boolean
}

export interface IngestResponse {
  content: ContentItem
  insights_extracted: number
  memories_written: number
  memory_backend: string
  degraded: boolean
  message: string
}

export interface DemoResetResponse {
  content_deleted: number
  insights_deleted: number
  plans_deleted: number
  memory_backend: string
  bank_cleared: boolean
  degraded: boolean
  message: string
}

// ---- Media (Phase 2) -----------------------------------------------------------

export interface MediaAsset {
  id: number
  filename: string
  mime_type: string
  file_size: number
  media_type: 'video' | 'image' | 'audio'
  status: 'uploaded' | 'processing' | 'ready' | 'failed'
  duration_seconds: number | null
  width: number | null
  height: number | null
  content_id: number | null
  created_at: string
  has_dna: boolean
  job_status: string | null
}

export interface MediaJob {
  id: number
  asset_id: number
  job_type: string
  status: 'pending' | 'processing' | 'completed' | 'failed'
  error: string
  steps: Record<string, { status: string; detail: string }>
  created_at: string
  completed_at: string | null
}

export interface ContentDNA {
  id: number
  asset_id: number
  content_id: number | null
  transcript: string
  language: string
  scene_description: string
  ocr_text: string
  visual_tags: string[]
  keyframe_analyses: Array<Record<string, unknown>>
  keyframes: number[]
  hook_score: number | null
  clarity_score: number | null
  brand_alignment: number | null
  created_at: string
  updated_at: string
}

export interface MediaAssetDetail extends MediaAsset {
  dna: ContentDNA | null
  jobs: MediaJob[]
}

export interface MediaAssetListResponse {
  items: MediaAsset[]
  total: number
  limit: number
  offset: number
}

export interface MediaUploadResponse {
  asset: MediaAsset
  job: MediaJob
  warnings: string[]
}

export interface MediaJobListResponse {
  items: MediaJob[]
  total: number
}

// ---- Reviewer (Phase 3) ---------------------------------------------------------

export interface ReviewerSuggestion {
  category: 'hook' | 'clarity' | 'brand' | 'structure' | 'cta' | 'topic'
  severity: 'critical' | 'improve' | 'nice_to_have'
  suggestion: string
  rationale: string
  evidence: string
}

export interface ReviewerResponse {
  hook_score: number
  clarity_score: number
  brand_alignment: number
  overall_score: number
  summary: string
  suggestions: ReviewerSuggestion[]
  evidence: string[]
  degraded: boolean
  engine: 'llm' | 'heuristic'
  review_id: number | null
}

export interface ContentReview {
  id: number
  content_id: number | null
  asset_id: number | null
  source: 'draft' | 'media'
  platform: string
  topic: string
  title: string
  draft_excerpt: string
  hook_score: number
  clarity_score: number
  brand_alignment: number
  overall_score: number
  suggestions: Array<Record<string, unknown>>
  evidence: string[]
  degraded: boolean
  engine: string
  created_at: string
}

export interface ReviewerHistoryResponse {
  items: ContentReview[]
  total: number
}

// ---------------------------------------------------------------------------
// Phase 4 — Performance intelligence
// ---------------------------------------------------------------------------
export interface MetricSnapshot {
  id: number
  source: string
  recorded_at: string
  days_since_published: number | null
  views: number | null
  impressions: number | null
  likes: number | null
  comments: number | null
  shares: number | null
  saves: number | null
  link_clicks: number | null
  watch_time_seconds: number | null
  avg_watch_duration_seconds: number | null
  audience_retention_pct: number | null
  ctr_pct: number | null
}

export interface MetricSnapshotInput {
  views?: number | null
  impressions?: number | null
  likes?: number | null
  comments?: number | null
  shares?: number | null
  saves?: number | null
  link_clicks?: number | null
  watch_time_seconds?: number | null
  avg_watch_duration_seconds?: number | null
  audience_retention_pct?: number | null
  ctr_pct?: number | null
  source?: 'manual' | 'platform'
  recorded_at?: string | null
}

export interface PublishedPost {
  id: number
  content_id: number | null
  media_asset_id: number | null
  platform: string
  title: string
  external_id: string
  url: string
  published_at: string
  status: string
  created_at: string
  snapshot_count: number
  latest_snapshot: MetricSnapshot | null
}

export interface PublishedPostDetail extends PublishedPost {
  snapshots: MetricSnapshot[]
}

export interface PublishedPostListResponse {
  items: PublishedPost[]
  total: number
}

export interface PlatformAggregate {
  platform: string
  post_count: number
  posts_with_metrics: number
  total_views: number | null
  total_impressions: number | null
  avg_engagement_rate_per_view: number | null
  avg_engagement_rate_per_impression: number | null
  avg_ctr_pct: number | null
  avg_retention_pct: number | null
}

export interface AttributeAggregate {
  key: string
  post_count: number
  posts_with_views: number
  avg_views: number | null
  avg_engagement_rate_per_view: number | null
  median_views: number | null
}

export interface SnapshotTimeSeriesPoint {
  period: string
  snapshot_count: number
  total_views: number | null
  total_impressions: number | null
  avg_engagement_rate_per_view: number | null
}

export interface PostComparison {
  post_id: number
  title: string
  platform: string
  days_since_published: number | null
  views: number | null
  impressions: number | null
  engagement_count: number | null
  engagement_rate_per_view: number | null
  engagement_rate_per_impression: number | null
}

export interface PerformanceAnalyticsResponse {
  post_count: number
  posts_with_metrics: number
  date_range: { start: string | null; end: string | null }
  total_views: number | null
  total_impressions: number | null
  total_engagements: number | null
  avg_views: number | null
  avg_engagement_rate_per_view: number | null
  avg_engagement_rate_per_impression: number | null
  by_platform: PlatformAggregate[]
  by_topic: AttributeAggregate[]
  by_content_type: AttributeAggregate[]
  over_time: SnapshotTimeSeriesPoint[]
  top_posts: PostComparison[]
  warnings: string[]
}

export interface InsightEvidence {
  post_id: number | null
  title: string
  platform: string
  value: number | null
  note: string
}

export interface PerformanceInsight {
  key: string
  finding: string
  posts_analyzed: number
  metric: string
  comparison: string
  confidence: 'strong' | 'moderate' | 'weak' | 'insufficient'
  evidence: InsightEvidence[]
  observation_period: string
  limitations: string[]
  recommendation: string
  status: 'ok' | 'insufficient_data'
}

export interface InsightReportResponse {
  insights: PerformanceInsight[]
  posts_analyzed: number
  posts_with_metrics: number
  message: string
}

// ---- Strategy Agent (Phase 5) -----------------------------------------------------

export const STRATEGY_GOALS = ['education', 'awareness', 'community', 'leads', 'conversion'] as const
export type StrategyGoal = (typeof STRATEGY_GOALS)[number]

export interface StrategyProfile {
  id: number
  niche: string
  topics: string[]
  target_audience: string
  audience_needs: string
  goals: string[]
  content_pillars: string[]
  avoid_topics: string[]
  publishing_frequency: string
  constraints: string
  feedback_preferences: string[]
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface StrategyProfileUpsert {
  niche?: string
  topics?: string[]
  target_audience?: string
  audience_needs?: string
  goals?: string[]
  content_pillars?: string[]
  avoid_topics?: string[]
  publishing_frequency?: string
  constraints?: string
}

export interface StrategyGenerateRequest {
  period: 'week' | 'month'
  days?: number | null
  posts_per_week?: number | null
  platforms?: string[]
  goals?: string[]
  constraints?: string
  start_date?: string | null
}

export type RecommendationStatus =
  | 'proposed'
  | 'accepted'
  | 'edited'
  | 'rejected'
  | 'deferred'
  | 'completed'

export interface Recommendation {
  id: number
  plan_id: number | null
  sequence_day: number
  pillar: string
  topic: string
  format: string
  platform: string
  working_title: string
  hook: string
  audience: string
  objective: string
  cta: string
  production_notes: string
  is_hypothesis: boolean
  reason: string
  evidence: string[]
  sample_size: number | null
  observation_period: string
  confidence: 'strong' | 'moderate' | 'weak' | 'insufficient'
  success_metric: string
  test_method: string
  status: RecommendationStatus
  edited_title: string
  edited_hook: string
  edited_notes: string
  feedback_note: string
  created_at: string
  updated_at: string
}

export interface RecommendationUpdate {
  status?: RecommendationStatus
  edited_title?: string
  edited_hook?: string
  edited_notes?: string
  feedback_note?: string
}

export interface StrategyGenerateResponse {
  plan_id: number | null
  period: string
  summary: string
  recommendations: Recommendation[]
  evidence_sources: Record<string, boolean>
  warnings: string[]
  memory_degraded: boolean
}

export interface FeedbackRequest {
  status?: 'accepted' | 'rejected' | 'deferred' | 'completed'
  note?: string
  update_preferences?: boolean
}

export interface Experiment {
  id: number
  recommendation_id: number | null
  title: string
  hypothesis: string
  variation: string
  intended_metric: string
  status: 'planned' | 'running' | 'completed'
  actual_result: string
  result_note: string
  completed_at: string | null
  created_at: string
  updated_at: string
}

export interface ExperimentCreate {
  recommendation_id?: number | null
  title?: string
  hypothesis?: string
  variation?: string
  intended_metric?: string
}

export interface ExperimentUpdate {
  status?: 'planned' | 'running' | 'completed'
  actual_result?: string
  result_note?: string
}

export interface Lesson {
  text: string
  kind: string
  confidence: string
  evidence: string[]
  source: 'memory' | 'experiment'
}

export interface LessonsResponse {
  lessons: Lesson[]
  message: string
  memory_degraded: boolean
}

// --------------------------------------------------------------------------------------
// Phase 6 — Instagram (Meta) Integration
// --------------------------------------------------------------------------------------

export interface InstagramAuthUrlResponse {
  authorize_url: string
  state: string
}

export interface InstagramCallbackRequest {
  code: string
  state: string
}

export interface InstagramConnection {
  id: number
  instagram_account_id: string
  username: string
  account_type: string
  media_count: number | null
  followers_count: number | null
  follows_count: number | null
  profile_picture_url: string
  status: string
  scopes: string[]
  expires_at: string | null
  last_refreshed_at: string | null
  last_sync_at: string | null
  last_sync_status: string
  last_sync_error: string
  created_at: string
  updated_at: string
}

export interface InstagramConnectionListResponse {
  items: InstagramConnection[]
  total: number
}

export interface InstagramSyncJob {
  id: number
  connection_id: number
  status: string
  started_at: string
  completed_at: string | null
  posts_examined: number
  posts_imported: number
  snapshots_created: number
  error_category: string
  error_message: string
  created_at: string
}

export interface InstagramSyncJobListResponse {
  items: InstagramSyncJob[]
  total: number
}

export interface InstagramSyncTriggerRequest {
  max_posts?: number
}

export interface InstagramSyncTriggerResponse {
  job: InstagramSyncJob
  connection_id: number
}

export interface InstagramPost {
  id: number
  external_id: string
  platform: string
  title: string
  url: string
  published_at: string
  status: string
  snapshot_count: number
  latest_snapshot: MetricSnapshot | null
}

export interface InstagramPostListResponse {
  items: InstagramPost[]
  total: number
  limit: number
  offset: number
}

export interface InstagramAccountInsights {
  account_id: string
  username: string
  period: string
  impressions: number | null
  reach: number | null
  profile_views: number | null
  follower_count: number | null
  website_clicks: number | null
  collected_at: string
}
