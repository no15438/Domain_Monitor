"use client";

import { useState } from "react";
import { GitBranch, Loader2, RefreshCw } from "lucide-react";
import type { SnapshotDelta, SynthesisArtifact } from "@/lib/api";
import AnalysisRichText from "./AnalysisRichText";

export default function EvolutionPanel({
  deltas,
  artifact,
  loading,
  generating,
  onGenerate,
}: {
  deltas: SnapshotDelta[];
  artifact: SynthesisArtifact | null;
  loading: boolean;
  generating: boolean;
  onGenerate: () => void;
}) {
  const [showAllDeltas, setShowAllDeltas] = useState(false);
  const visibleDeltas = showAllDeltas ? deltas : deltas.slice(0, 5);

  return (
    <div className="rounded-lg border border-border bg-surface shadow-sm p-3 space-y-3">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-muted flex items-center gap-1.5">
          <GitBranch className="w-3.5 h-3.5" />
          Evolution
        </h3>
        <button
          onClick={onGenerate}
          disabled={generating}
          className="p-1 rounded text-muted hover:text-foreground hover:bg-surface-hover transition-colors disabled:opacity-40"
          title="Generate evolution report"
        >
          <RefreshCw className={`w-3 h-3 ${generating ? "animate-spin" : ""}`} />
        </button>
      </div>

      {loading ? (
        <div className="flex items-center gap-2 text-[10px] text-muted">
          <Loader2 className="w-3.5 h-3.5 animate-spin" />
          Loading evolution context...
        </div>
      ) : null}

      {artifact?.content ? (
        <AnalysisRichText
          content={artifact.content}
          citations={artifact.metadata?.citations}
        />
      ) : !generating ? (
        <p className="text-[10px] text-muted">
          No evolution report yet. Generate one after a few snapshots exist.
        </p>
      ) : null}

      {deltas.length > 0 && (
        <div className="space-y-2">
          <div className="flex items-center justify-between gap-2 text-[10px] uppercase tracking-wider text-muted">
            <span>Recent Timeline Changes</span>
            <span className="normal-case tracking-normal">
              Showing {visibleDeltas.length} of {deltas.length}
            </span>
          </div>
          {visibleDeltas.map((delta) => (
            <div key={delta.id} className="rounded-md border border-border bg-surface-hover/50 p-2">
              <p className="text-[10px] text-foreground font-medium">{delta.change_summary}</p>
              <div className="mt-1 text-[9px] text-muted space-y-0.5">
                <div>New events: {delta.new_event_ids.length}</div>
                <div>Resolved events: {delta.resolved_event_ids.length}</div>
                <div>Strengthened claims: {delta.strengthened_claim_ids.length}</div>
                <div>Weakened claims: {delta.weakened_claim_ids.length}</div>
                <div>Superseded claims: {delta.superseded_claim_ids.length}</div>
              </div>
            </div>
          ))}
          {deltas.length > 5 ? (
            <button
              onClick={() => setShowAllDeltas((current) => !current)}
              className="text-[10px] font-medium text-accent hover:underline"
            >
              {showAllDeltas ? "Show fewer changes" : "Show all changes"}
            </button>
          ) : null}
        </div>
      )}
    </div>
  );
}
