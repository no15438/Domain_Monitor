"use client";

import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import {
  AlertTriangle,
  BarChart3,
  BookOpen,
  FileText,
  Loader2,
  RefreshCw,
  Sparkles,
  Database,
  Info,
} from "lucide-react";
import {
  type TrendingData,
  type Claim,
  type EvidenceSet,
} from "@/lib/api";
import { useStore } from "@/stores/useStore";
import EvolutionPanel from "./EvolutionPanel";
import { useTopicKnowledgeData } from "@/lib/hooks/useTopicKnowledgeData";
import {
  getClaimKindLabel,
  getClaimKindExplain,
  getClaimStatusLabel,
  getClaimStatusExplain,
  getReviewStateLabel,
  getSnapshotStatusLabel,
} from "@/lib/knowledgeLabels";
import { timeAgo } from "@/lib/utils";

function ClaimCard({ claim, evidence }: { claim: Claim; evidence: EvidenceSet[] }) {
  const [expandedSection, setExpandedSection] = useState<"explain" | "sources" | null>(null);

  const kindLabel = getClaimKindLabel(claim.claim_kind ?? claim.claim_type);
  const kindExplain = getClaimKindExplain(claim.claim_kind ?? claim.claim_type);
  const statusLabel = getClaimStatusLabel(claim.lifecycle_status ?? claim.status);
  const statusExplain = getClaimStatusExplain(claim.lifecycle_status ?? claim.status);
  
  const timeStr = (claim.last_refreshed_at ? timeAgo(claim.last_refreshed_at) : null) ?? "unknown";

  const claimEvidence = evidence.filter(e => 
    claim.supporting_evidence_ids?.includes(e.id) || 
    claim.evidence_ids?.includes(e.id)
  );

  return (
    <div className="rounded-md border border-border/50 bg-surface/60 p-3 flex flex-col gap-2">
      <div>
        <p className="text-[12px] font-semibold leading-snug">{claim.statement}</p>
        <p className="text-[11px] text-muted mt-1">{claim.summary}</p>
      </div>
      
      <div className="flex flex-wrap gap-1.5 items-center mt-1">
        {/* Badge 1: Kind & Status */}
        <button 
          onClick={() => setExpandedSection(expandedSection === "explain" ? null : "explain")}
          className={`flex items-center gap-1 px-1.5 py-0.5 rounded border text-[10px] transition-colors ${
            expandedSection === "explain" 
              ? "bg-accent/10 border-accent/20 text-accent" 
              : "border-border/50 bg-surface text-muted hover:text-foreground"
          }`}
        >
          {kindLabel} • {statusLabel}
          <Info className="w-3 h-3 ml-0.5 opacity-60" />
        </button>

        {/* Badge 2: Updated */}
        <div className="px-1.5 py-0.5 rounded border border-border/50 bg-surface text-[10px] text-muted">
          Updated {timeStr}
        </div>

        {/* Badge 3: Sources */}
        <button
          onClick={() => setExpandedSection(expandedSection === "sources" ? null : "sources")}
          className={`ml-auto flex items-center gap-1 px-1.5 py-0.5 rounded border text-[10px] transition-colors ${
            expandedSection === "sources"
              ? "bg-accent/10 border-accent/20 text-accent"
              : "border-border/50 bg-surface text-muted hover:text-foreground"
          }`}
        >
          <Database className="w-3 h-3" />
          {claimEvidence.length > 0 ? `${claimEvidence.length} Sources` : "Sources"}
        </button>
      </div>

      {/* Expanded Sections */}
      {expandedSection === "explain" && (
        <div className="mt-2 p-2 rounded bg-surface border border-border/50 text-[10px] space-y-1.5 animate-in fade-in slide-in-from-top-1">
          <div>
            <span className="font-semibold text-foreground">{kindLabel}:</span>{" "}
            <span className="text-muted">{kindExplain}</span>
          </div>
          <div>
            <span className="font-semibold text-foreground">{statusLabel}:</span>{" "}
            <span className="text-muted">{statusExplain}</span>
          </div>
        </div>
      )}

      {expandedSection === "sources" && (
        <div className="mt-2 p-2 rounded bg-surface border border-border/50 text-[10px] space-y-2 animate-in fade-in slide-in-from-top-1">
          {claimEvidence.length > 0 ? (
            claimEvidence.map(ev => (
              <div key={ev.id} className="border-b border-border/30 pb-1.5 last:border-0 last:pb-0">
                <div className="font-semibold text-foreground">{ev.title}</div>
                <div className="text-muted line-clamp-2 mt-0.5">{ev.summary}</div>
              </div>
            ))
          ) : (
            <div className="text-muted">No direct evidence loaded for this claim yet.</div>
          )}
        </div>
      )}
    </div>
  );
}

export default function MacroAnalysisPanel({
  activeTopicId,
  trending,
}: {
  activeTopicId: number | null;
  trending: TrendingData | null;
}) {
  const hydrateGlobalOverview = useStore((s) => s.hydrateGlobalOverview);
  const startGlobalOverviewGeneration = useStore((s) => s.startGlobalOverviewGeneration);
  const globalSlice = useStore((s) =>
    activeTopicId != null ? s.globalOverviewByTopic[activeTopicId] : undefined
  );
  const {
    snapshots,
    claims,
    evidence,
    deltas,
    overviewArtifact,
    evolutionArtifact,
    loadingSnapshots,
    loadingClaims,
    loadingEvidence,
    loadingEvolution,
    generatingEvolution,
    knowledgeError,
    refreshKnowledge,
    triggerEvolution,
  } = useTopicKnowledgeData(activeTopicId);

  const globalContent = overviewArtifact?.content ?? globalSlice?.content ?? "";
  const globalGenerating = globalSlice?.isGenerating ?? false;
  const [expandedSnapshotIds, setExpandedSnapshotIds] = useState<number[]>([]);

  useEffect(() => {
    if (activeTopicId == null) return;
    void hydrateGlobalOverview(activeTopicId);
  }, [activeTopicId, hydrateGlobalOverview]);

  const handleGenerate = () => {
    if (activeTopicId == null || globalGenerating) return;
    void startGlobalOverviewGeneration(activeTopicId);
  };

  const toggleSnapshot = (snapshotId: number) => {
    setExpandedSnapshotIds((current) =>
      current.includes(snapshotId)
        ? current.filter((id) => id !== snapshotId)
        : [...current, snapshotId],
    );
  };

  return (
    <div className="space-y-4">
      {knowledgeError ? (
        <div className="rounded-lg border border-important/30 bg-important/5 p-3">
          <div className="flex items-start gap-2">
            <AlertTriangle className="mt-0.5 h-4 w-4 text-important" />
            <div className="min-w-0 flex-1">
              <p className="text-xs font-semibold text-foreground">
                Knowledge workspace unavailable
              </p>
              <p className="mt-1 text-[11px] text-muted">{knowledgeError}</p>
            </div>
            <button
              onClick={() => void refreshKnowledge()}
              className="rounded-md px-2 py-1 text-[10px] font-medium text-accent hover:bg-accent/10"
            >
              Retry
            </button>
          </div>
        </div>
      ) : null}

      {/* Global Overview */}
      <div className="rounded-lg border border-border bg-surface shadow-sm p-3">
        <div className="flex items-center justify-between gap-2 mb-2">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted flex items-center gap-1.5">
            <Sparkles className="w-3.5 h-3.5 text-accent" />
            Knowledge Overview
          </h3>
          <button
            onClick={handleGenerate}
            disabled={globalGenerating}
            className="p-1 rounded text-muted hover:text-foreground hover:bg-surface-hover transition-colors disabled:opacity-40"
            title={globalContent ? "Regenerate" : "Generate global overview"}
          >
            <RefreshCw className={`w-3 h-3 ${globalGenerating ? "animate-spin" : ""}`} />
          </button>
        </div>

        {globalGenerating && (
          <div className="flex items-center gap-2 py-3">
            <Loader2 className="w-3.5 h-3.5 text-accent animate-spin" />
            <span className="text-[10px] text-muted">Synthesizing global overview…</span>
          </div>
        )}

        {globalContent ? (
          <div className="ai-summary-content text-xs">
            <ReactMarkdown>{globalContent}</ReactMarkdown>
          </div>
        ) : !globalGenerating ? (
          <button
            onClick={handleGenerate}
            className="w-full py-3 rounded-lg border border-dashed border-border text-center hover:border-accent/40 hover:bg-accent/5 transition-colors group"
          >
            <Sparkles className="w-4 h-4 text-muted group-hover:text-accent mx-auto mb-1" />
            <span className="text-[10px] text-muted group-hover:text-foreground">
              Generate Global Overview
            </span>
          </button>
        ) : null}
      </div>

      {/* Claims */}
      <div className="rounded-lg border border-border bg-surface shadow-sm p-3">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-muted flex items-center gap-1.5 mb-2">
          <FileText className="w-3.5 h-3.5" />
          Working Claims
        </h3>
        {loadingClaims ? (
          <p className="text-[10px] text-muted">Loading…</p>
        ) : claims.length === 0 ? (
          <p className="text-[10px] text-muted">No claims yet.</p>
        ) : (
          <div className="space-y-2">
            {claims.slice(0, 10).map((claim) => (
              <ClaimCard key={claim.id} claim={claim} evidence={evidence} />
            ))}
          </div>
        )}
      </div>

      {/* Evidence */}
      <div className="rounded-lg border border-border/60 bg-surface/40 p-3">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-muted flex items-center gap-1.5 mb-2">
          <Database className="w-3.5 h-3.5" />
          Evidence Sets
        </h3>
        {loadingEvidence ? (
          <p className="text-[10px] text-muted">Loading…</p>
        ) : evidence.length === 0 ? (
          <p className="text-[10px] text-muted">
            No supporting signals have been collected yet.
          </p>
        ) : (
          <div className="space-y-2">
            {evidence.slice(0, 10).map((item) => (
              <div key={item.id} className="rounded-md border border-border/50 bg-surface/60 p-2">
                <p className="text-[11px] font-semibold leading-snug">{item.title}</p>
                <p className="text-[10px] text-muted mt-1">{item.summary}</p>
                <div className="mt-1 text-[9px] text-muted space-y-0.5">
                  <div>Signal type: {item.signal_type ?? item.evidence_type}</div>
                  <div>Direction: {item.stance}</div>
                  <div>
                    Topic match: {Math.round(((item.support_score ?? item.confidence) || 0) * 100)}%
                  </div>
                  <div>{getReviewStateLabel(item.review_state)}</div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Temporal Snapshots */}
      <div className="rounded-lg border border-border/60 bg-surface/40 p-3">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-muted flex items-center gap-1.5 mb-2">
          <BookOpen className="w-3.5 h-3.5" />
          Snapshot Timeline
        </h3>
        {loadingSnapshots ? (
          <p className="text-[10px] text-muted">Loading…</p>
        ) : snapshots.length === 0 ? (
          <p className="text-[10px] text-muted">No temporal snapshots yet.</p>
        ) : (
          <div className="space-y-2">
            <div className="text-[10px] text-muted">
              Showing {Math.min(snapshots.length, 6)} of {snapshots.length} timeline updates
            </div>
            {snapshots.slice(0, 6).map((snapshot) => (
              <div key={snapshot.id} className="rounded-md border border-border/50 bg-surface/60 p-2">
                <div className="flex items-center justify-between gap-2 text-[10px] text-muted">
                  <span>{new Date(snapshot.created_at + "Z").toLocaleString()}</span>
                  <span>{getSnapshotStatusLabel(snapshot.snapshot_status)}</span>
                </div>
                <div
                  className={`mt-1 text-[11px] text-foreground whitespace-pre-wrap ${
                    expandedSnapshotIds.includes(snapshot.id) ? "" : "line-clamp-5"
                  }`}
                >
                  {snapshot.summary_text}
                </div>
                <button
                  onClick={() => toggleSnapshot(snapshot.id)}
                  className="mt-2 text-[10px] font-medium text-accent hover:underline"
                >
                  {expandedSnapshotIds.includes(snapshot.id) ? "Show less" : "Show full note"}
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      <EvolutionPanel
        deltas={deltas}
        artifact={evolutionArtifact}
        loading={loadingEvolution}
        generating={generatingEvolution}
        onGenerate={() => void triggerEvolution()}
      />

      {/* Macro Signals */}
      <div className="rounded-lg border border-border/60 bg-surface/40 p-3">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-muted flex items-center gap-1.5 mb-2">
          <BarChart3 className="w-3.5 h-3.5" />
          Macro Signals
        </h3>
        {trending ? (
          <div className="space-y-2">
            <div className="text-[10px] text-muted">
              Average Topic Match:{" "}
              <span className="text-foreground font-semibold">
                {Math.round((trending.avg_topic_relevance || 0) * 100)}%
              </span>
            </div>
            {trending.top_entities?.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {trending.top_entities.slice(0, 8).map((e) => (
                  <span
                    key={e.entity}
                    className="px-1.5 py-0.5 rounded text-[10px] bg-surface-hover text-muted"
                    title={`${e.entity}: ${e.count}`}
                  >
                    {e.entity}
                  </span>
                ))}
              </div>
            )}
          </div>
        ) : (
          <p className="text-[10px] text-muted">No macro signals yet.</p>
        )}
      </div>
    </div>
  );
}
