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

export type ChatEvent =
  | { type: "status"; value: string }
  | { type: "content"; value: string };

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
  sources?: { source_type: string; source_id: string }[];
}

export interface CachedSummary {
  content: string | null;
  generated_at: string | null;
  snapshot_id?: number | null;
  stats_metadata?: string | null;
}

export interface InsightSummary {
  total_articles: number;
  important_count: number;
  source_distribution: Record<string, number>;
  sentiment_distribution: Record<string, number>;
  top_events: Article[];
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
