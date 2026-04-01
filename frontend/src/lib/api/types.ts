export interface Article {
  id: string;
  title: string;
  summary: string;
  content: string;
  source: string;
  url: string;
  tags: string;
  sentiment: "positive" | "negative" | "neutral";
  importance: number;
  source_type: string;
  topic_id: number | null;
  published_at: string;
  created_at: string;
  event_id: string;
  is_canonical: number;
  event_size: number;
  source_score: number;
  source_breakdown: string;
  topic_relevance: number;
  key_entities: string;
  topic_analysis: string;
  is_kept?: number;
  status?: "active" | "archived";
}

export interface TrendingDay {
  day: string;
  total: number;
  positive: number;
  neutral: number;
  negative: number;
  avg_importance: number;
  avg_relevance: number;
}

export interface TrendingData {
  days: number;
  daily: TrendingDay[];
  top_entities: { entity: string; count: number }[];
  avg_topic_relevance: number;
}

export interface Keyword {
  id: number;
  keyword: string;
  category: string;
  topic_id: number | null;
  is_active: number;
  created_at: string;
}

export interface ResearchConfig {
  angles: string[];
  entities: string[];
  geographic_scope: string[];
  sector_scope: string[];
}

export interface Topic {
  id: number;
  name: string;
  color: string;
  research_brief?: string;
  research_config?: string;
  is_active: number;
  created_at: string;
  /** Set when the topic is archived (hidden from the main list). */
  archived_at?: string | null;
}

export function parseResearchConfig(topic: Topic): ResearchConfig {
  const empty: ResearchConfig = {
    angles: [],
    entities: [],
    geographic_scope: [],
    sector_scope: [],
  };
  if (!topic.research_config) return empty;
  try {
    return { ...empty, ...JSON.parse(topic.research_config) };
  } catch {
    return empty;
  }
}

export interface TopicOverview extends Topic {
  article_count: number;
  important_count: number;
  sentiment: Record<string, number>;
  trend_delta: number;
  keywords: string[];
  top_headline: string | null;
}

export interface ResearchPlan {
  research_brief: string;
  keywords: string[];
  rss_feeds: { id?: number; url: string; label: string }[];
  angles: string[];
  entities: string[];
  geographic_scope: string[];
  sector_scope: string[];
}

export interface ChatTraceNode {
  id: string;
  type: "event" | "claim" | "snapshot" | "artifact";
  title: string;
  status: string;
}

export type KbLayer = "current_state" | "timeline" | "archive";

export interface ChatTraceMeta {
  // intent
  needs_current_state?: boolean;
  needs_timeline?: boolean;
  needs_archive?: boolean;
  time_window_days?: number;
  route_segments?: KbLayer[];
  route_label?: string;
  strategy_label?: string;
  // kb_hits
  retrieval_layers?: KbLayer[];
  hit_counts?: Partial<Record<KbLayer, number>>;
  total_nodes?: number;
  // vector_supplement / web_fallback
  used?: boolean;
  // answer_generation
  final_route_label?: string;
  vec_used?: boolean;
  web_used?: boolean;
  [key: string]: unknown;
}

export interface ChatTracePayload {
  kind: "intent" | "kb_hits" | "vector_supplement" | "web_fallback" | "answer_generation";
  label: string;
  state: "running" | "done" | "skipped";
  meta?: ChatTraceMeta;
  nodes?: ChatTraceNode[];
}

export interface ChatSource {
  id: string;
  title: string;
  url: string;
  type: "event" | "snapshot" | "artifact" | "web" | string;
}

export type ChatEvent =
  | { type: "status"; value: string }
  | { type: "content"; value: string }
  | { type: "trace"; value: ChatTracePayload }
  | { type: "sources"; value: ChatSource[] };

export interface ChatHistoryMessage {
  role: "user" | "assistant";
  content: string;
}

export interface Snapshot {
  id: number;
  topic_id: number;
  overview_content: string;
  stats_metadata: string;
  created_at: string;
}

export interface TemporalSnapshot {
  id: number;
  topic_id: number;
  window_type: string;
  window_start: string | null;
  window_end: string | null;
  summary_text: string;
  stats_metadata: string;
  snapshot_status: string;
  created_at: string;
}

export interface EvidenceSet {
  id: string;
  topic_id: number;
  event_id: string;
  claim_id?: string | null;
  title: string;
  summary: string;
  evidence_type: string;
  signal_type?: string;
  stance: string;
  confidence: number;
  support_score?: number;
  review_state: string;
  supporting_event_ids: string[];
  contradicting_event_ids: string[];
}

export interface Claim {
  id: string;
  topic_id: number;
  claim_type: string;
  claim_kind?: string;
  statement: string;
  summary: string;
  status: string;
  lifecycle_status?: string;
  supporting_evidence_ids: string[];
  evidence_ids?: string[];
  supersedes_claim_id?: string | null;
  last_validated_at: string;
  last_refreshed_at?: string;
  decay_policy: string;
  staleness_status: string;
  freshness?: string;
}

/** Lightweight claim summary embedded inside an event card. */
export interface EventClaimSummary {
  id: string;
  statement: string;
  summary: string;
  status: string;
  claim_kind?: string;
  lifecycle_status?: string;
  staleness_status?: string;
  freshness?: string;
  last_refreshed_at?: string;
  evidence_count: number;
}

export interface EventRecord {
  id: string;
  topic_id: number;
  event_key: string;
  title: string;
  summary: string;
  status: string;
  canonical_article_id?: string | null;
  first_seen_at: string;
  last_seen_at: string;
  novelty_window_end?: string | null;
  stability_score: number;
  fact_confidence: number;
  supersedes_event_id?: string | null;
}

export interface SnapshotDelta {
  id: number;
  topic_id: number;
  from_snapshot_id?: number | null;
  to_snapshot_id: number;
  change_summary: string;
  new_event_ids: string[];
  resolved_event_ids: string[];
  strengthened_claim_ids: string[];
  weakened_claim_ids: string[];
  superseded_claim_ids: string[];
  created_at: string;
}

export interface SynthesisArtifact {
  id: string;
  topic_id: number;
  artifact_type: string;
  title: string;
  content: string;
  status: string;
  version: number;
  generated_at: string;
  metadata?: {
    citations?: AnalysisCitation[];
    [key: string]: unknown;
  };
  sources?: { source_type: string; source_id: string }[];
}

export interface AnalysisCitation {
  id: string;
  type: "article" | "event";
  title: string;
  url: string;
}

export interface CachedSummary {
  content: string | null;
  generated_at: string | null;
  snapshot_id?: number | null;
  stats_metadata?: string | null;
  citations?: AnalysisCitation[];
}

// ── Event cluster (聚类事件实体) ──────────────────────────
// Returned by /api/events. Represents a cluster of articles about the same event,
// backed by events_v2 (when available) joined with the canonical article.

export interface ClusterSource {
  id: string;
  title: string;
  source: string;
  url: string;
  published_at: string | null;
  source_score: number;
  source_type: string;
  is_canonical: number;
}

/** Preview source — one row in the preview_sources JSON from /api/events list */
export interface PreviewSource {
  source: string;
  title: string;
  url: string;
  source_score: number;
}

/** Lightweight event card summary returned by GET /api/events (list view). */
export interface EventCluster {
  id: string;                             // events_v2.id or articles.event_id
  topic_id: number | null;
  title: string;                          // event-level title (falls back to canonical article title)
  summary: string;                        // event-level summary (falls back to canonical article summary)
  status: "active" | "archived";         // driven by canonical article status
  event_status: string;                   // knowledge-lifecycle status from events_v2
  canonical_article_id: string | null;
  canonical_url: string | null;
  canonical_source: string | null;
  source_type: string | null;
  source_score: number;
  sentiment: "positive" | "negative" | "neutral";
  importance: number;
  tags: string;
  is_kept: number;
  published_at: string | null;
  created_at: string | null;
  first_seen_at: string | null;
  last_seen_at: string | null;
  stability_score: number;
  fact_confidence: number;
  source_count: number;                   // total articles in this cluster
  /** Top 2 non-canonical sources for card preview (JSON string or null). */
  preview_sources?: string | PreviewSource[] | null;
}

/** Full event detail returned by GET /api/events/{event_id}.
 *  Contains all EventCluster fields plus canonical article full text and sources. */
export interface EventDetail extends EventCluster {
  canonical_content: string | null;
  canonical_key_entities: string | null;
  canonical_topic_analysis: string | null;
  sources: ClusterSource[];
}

export interface InsightSummary {
  total_articles: number;
  important_count: number;
  source_distribution: Record<string, number>;
  sentiment_distribution: Record<string, number>;
  top_events: EventCluster[];
}

export interface TopicInsight {
  window_hours: number;
  article_count: number;
  previous_count: number;
  trend_delta: number;
  sentiment_distribution: Record<string, number>;
  top_tags: { tag: string; count: number }[];
}

export interface TopicFeed {
  id: number;
  topic_id: number;
  feed_url: string;
  label: string;
  is_active: number;
  created_at: string;
}
