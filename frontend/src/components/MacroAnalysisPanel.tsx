"use client";

import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Archive,
  BarChart3,
  BookmarkCheck,
  Bookmark,
  BookOpen,
  ChevronDown,
  ChevronUp,
  FileText,
  GitBranch,
  Loader2,
  RefreshCw,
  Sparkles,
  Radio,
  Trash2,
  Users,
  MessageSquare,
  X,
} from "lucide-react";
import {
  getClaimKindLabel,
  getClaimStatusLabel,
} from "@/lib/knowledgeLabels";
import {
  type TrendingData,
  type EventCluster,
  type EventClaimSummary,
  type SynthesisArtifact,
} from "@/lib/api";
import {
  fetchEvents,
  fetchEventClaims,
  archiveEvent,
  deleteEvent,
  toggleEventKept,
  fetchEvolutionReportStatus,
  fetchSynthesisArtifact,
  postEvolutionReportGenerate,
} from "@/lib/api";
import { useStore } from "@/stores/useStore";
import { useTopicKnowledgeData } from "@/lib/hooks/useTopicKnowledgeData";
import {
  getSnapshotStatusLabel,
} from "@/lib/knowledgeLabels";
import { timeAgo } from "@/lib/utils";
import { updateClaimStatus, deleteClaim } from "@/lib/api";
import AnalysisRichText from "./AnalysisRichText";


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
  const getActionState = useStore((s) => s.getActionState);
  const refreshKey = useStore((s) => s.insightRefreshKey);
  const selectedKnowledgeEventId = useStore((s) => s.selectedKnowledgeEventId);
  const setSelectedKnowledgeEvent = useStore((s) => s.setSelectedKnowledgeEvent);
  const setSelectedEventContext = useStore((s) => s.setSelectedEventContext);

  const {
    snapshots,
    deltas,
    overviewArtifact,
    loadingSnapshots,
    knowledgeError,
    refreshKnowledge,
  } = useTopicKnowledgeData(activeTopicId);

  // Prefer globalSlice (kept in sync by polling) over overviewArtifact (loaded once at mount)
  const globalContent = (globalSlice?.content || overviewArtifact?.content) ?? "";
  // Citations come from the slice (updated after every poll tick) or fall back to the artifact metadata
  const globalCitations =
    (globalSlice?.citations?.length ? globalSlice.citations : undefined) ??
    overviewArtifact?.metadata?.citations ??
    [];
  const globalGenerating =
    (globalSlice?.isGenerating ?? false) ||
    (activeTopicId != null &&
      getActionState(`task:global-overview:${activeTopicId}`).status === "running");
  const evolutionActionRunning =
    activeTopicId != null &&
    getActionState(`task:evolution-report:${activeTopicId}`).status === "running";
  const [expandedSnapshotIds, setExpandedSnapshotIds] = useState<number[]>([]);
  const [evolutionArtifact, setEvolutionArtifact] = useState<SynthesisArtifact | null>(null);
  const [evolutionGenerating, setEvolutionGenerating] = useState(false);
  const [evolutionLoading, setEvolutionLoading] = useState(false);

  // Build a Map<snapshotId, SnapshotDelta> for quick lookup in the timeline
  const deltaBySnapshotId = useMemo(() => {
    const map = new Map<number, typeof deltas[0]>();
    for (const d of deltas) {
      if (d.to_snapshot_id != null) map.set(d.to_snapshot_id, d);
    }
    return map;
  }, [deltas]);

  // ── Events list state ──────────────────────────────────────────────────────
  const [events, setEvents] = useState<EventCluster[]>([]);
  const [eventsLoading, setEventsLoading] = useState(false);

  // ── Event CRUD state ───────────────────────────────────────────────────────
  // Two-step delete: stores the eventId pending confirmation
  const [pendingDeleteEventId, setPendingDeleteEventId] = useState<string | null>(null);

  // ── Per-event claims expand state ─────────────────────────────────────────
  const [expandedClaimsId, setExpandedClaimsId] = useState<string | null>(null);
  const [claimsCache, setClaimsCache] = useState<Record<string, EventClaimSummary[] | null>>({});

  // ── Claim CRUD state ───────────────────────────────────────────────────────
  const [pendingDeleteClaimId, setPendingDeleteClaimId] = useState<string | null>(null);
  const [updatingClaimId, setUpdatingClaimId] = useState<string | null>(null);

  const uniqueEvents = useMemo(() => {
    const seen = new Set<string>();
    return events.filter((ev) => {
      if (!ev.id || seen.has(ev.id)) return false;
      seen.add(ev.id);
      return true;
    });
  }, [events]);

  useEffect(() => {
    if (activeTopicId == null) return;
    let cancelled = false;
    setEventsLoading(true);
    fetchEvents(activeTopicId, 30, 0, "relevance", "active")
      .then((data) => { if (!cancelled) setEvents(data.events); })
      .catch((e) => { if (process.env.NODE_ENV === "development") console.warn("[events]", e); })
      .finally(() => { if (!cancelled) setEventsLoading(false); });
    return () => { cancelled = true; };
  }, [activeTopicId, refreshKey]);

  useEffect(() => {
    if (activeTopicId == null) {
      setEvolutionArtifact(null);
      setEvolutionGenerating(false);
      setEvolutionLoading(false);
      return;
    }
    let cancelled = false;
    setEvolutionLoading(true);
    Promise.all([
      fetchSynthesisArtifact(activeTopicId, "evolution-report"),
      fetchEvolutionReportStatus(activeTopicId),
    ])
      .then(([artifact, status]) => {
        if (cancelled) return;
        setEvolutionArtifact(artifact);
        setEvolutionGenerating(status.generating);
        if (!status.generating) {
          useStore
            .getState()
            .endAction(
              `task:evolution-report:${activeTopicId}`,
              status.status === "error" ? "error" : "success",
              status.error ?? null,
              status.result_summary ?? null,
            );
        }
      })
      .catch(() => {
        if (!cancelled) setEvolutionGenerating(false);
      })
      .finally(() => {
        if (!cancelled) setEvolutionLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [activeTopicId, refreshKey]);

  useEffect(() => {
    if (activeTopicId == null || !evolutionGenerating) return;
    let cancelled = false;
    const timer = setInterval(() => {
      void Promise.all([
        fetchEvolutionReportStatus(activeTopicId),
        fetchSynthesisArtifact(activeTopicId, "evolution-report"),
      ])
        .then(([status, artifact]) => {
          if (cancelled) return;
          setEvolutionGenerating(status.generating);
          if (artifact) setEvolutionArtifact(artifact);
          if (!status.generating) {
            useStore
              .getState()
              .endAction(
                `task:evolution-report:${activeTopicId}`,
                status.status === "error" ? "error" : "success",
                status.error ?? null,
                status.result_summary ?? null,
              );
          }
        })
        .catch(() => {
          if (!cancelled) setEvolutionGenerating(false);
        });
    }, 1800);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [activeTopicId, evolutionGenerating]);

  useEffect(() => {
    if (activeTopicId == null) return;
    void hydrateGlobalOverview(activeTopicId);
  }, [activeTopicId, hydrateGlobalOverview]);

  const handleGenerate = () => {
    if (activeTopicId == null || globalGenerating) return;
    void startGlobalOverviewGeneration(activeTopicId);
  };

  const handleGenerateEvolution = () => {
    if (activeTopicId == null || evolutionGenerating) return;
    // Reset any stale persisted action state before starting
    useStore.getState().beginAction(`task:evolution-report:${activeTopicId}`);
    setEvolutionGenerating(true);
    void postEvolutionReportGenerate(activeTopicId).catch(() => {
      useStore
        .getState()
        .endAction(
          `task:evolution-report:${activeTopicId}`,
          "error",
          "Failed to start evolution report generation",
        );
      setEvolutionGenerating(false);
    });
  };

  const toggleSnapshot = (snapshotId: number) => {
    setExpandedSnapshotIds((current) =>
      current.includes(snapshotId)
        ? current.filter((id) => id !== snapshotId)
        : [...current, snapshotId],
    );
  };

  function handleSelectEvent(ev: EventCluster) {
    const isAlreadySelected = selectedKnowledgeEventId === ev.id;
    if (isAlreadySelected) {
      setSelectedKnowledgeEvent(null);
      setSelectedEventContext(null);
    } else {
      setSelectedKnowledgeEvent(ev.id, ev.title);
      setSelectedEventContext({
        event_id: ev.id,
        title: ev.title,
        summary: ev.summary,
        canonical_source: ev.canonical_source ?? null,
        canonical_url: ev.canonical_url ?? null,
        source_count: ev.source_count,
        sentiment: ev.sentiment,
        importance: ev.importance,
        tags: ev.tags,
        first_seen_at: ev.first_seen_at ?? null,
        last_seen_at: ev.last_seen_at ?? null,
      });
    }
  }

  function handleToggleClaims(e: React.MouseEvent, eventId: string) {
    e.stopPropagation();
    if (expandedClaimsId === eventId) {
      setExpandedClaimsId(null);
      return;
    }
    setExpandedClaimsId(eventId);
    if (!(eventId in claimsCache)) {
      setClaimsCache((prev) => ({ ...prev, [eventId]: null }));
      fetchEventClaims(eventId)
        .then((claims) => setClaimsCache((prev) => ({ ...prev, [eventId]: claims })))
        .catch(() => setClaimsCache((prev) => ({ ...prev, [eventId]: [] })));
    }
  }

  // ── Event CRUD handlers ────────────────────────────────────────────────────

  function handleToggleKept(e: React.MouseEvent, ev: EventCluster) {
    e.stopPropagation();
    const newKept = ev.is_kept ? 0 : 1;
    setEvents((prev) =>
      prev.map((item) => item.id === ev.id ? { ...item, is_kept: newKept } : item)
    );
    void toggleEventKept(ev.id, newKept === 1).catch(() => {
      // Revert on failure
      setEvents((prev) =>
        prev.map((item) => item.id === ev.id ? { ...item, is_kept: ev.is_kept } : item)
      );
    });
  }

  function handleArchiveEvent(e: React.MouseEvent, ev: EventCluster) {
    e.stopPropagation();
    setEvents((prev) => prev.filter((item) => item.id !== ev.id));
    if (selectedKnowledgeEventId === ev.id) {
      setSelectedKnowledgeEvent(null);
      setSelectedEventContext(null);
    }
    void archiveEvent(ev.id).catch(() => {
      // Revert on failure
      setEvents((prev) => [...prev, ev]);
    });
  }

  function handleDeleteEventRequest(e: React.MouseEvent, eventId: string) {
    e.stopPropagation();
    if (pendingDeleteEventId === eventId) {
      // Confirmed — execute delete
      setPendingDeleteEventId(null);
      setEvents((prev) => prev.filter((item) => item.id !== eventId));
      if (selectedKnowledgeEventId === eventId) {
        setSelectedKnowledgeEvent(null);
        setSelectedEventContext(null);
      }
      void deleteEvent(eventId);
    } else {
      setPendingDeleteEventId(eventId);
      // Auto-cancel confirmation after 3s
      setTimeout(() => setPendingDeleteEventId((cur) => cur === eventId ? null : cur), 3000);
    }
  }

  // ── Claim CRUD handlers ────────────────────────────────────────────────────

  function handleUpdateClaimStatus(
    e: React.MouseEvent,
    eventId: string,
    claimId: string,
    newStatus: string,
  ) {
    e.stopPropagation();
    setUpdatingClaimId(claimId);
    updateClaimStatus(claimId, newStatus)
      .then(() => {
        setClaimsCache((prev) => {
          const claims = prev[eventId];
          if (!claims) return prev;
          return {
            ...prev,
            [eventId]: claims.map((c) =>
              c.id === claimId ? { ...c, status: newStatus, lifecycle_status: newStatus } : c
            ),
          };
        });
      })
      .catch(() => {/* silently ignore */})
      .finally(() => setUpdatingClaimId(null));
  }

  function handleDeleteClaimRequest(e: React.MouseEvent, eventId: string, claimId: string) {
    e.stopPropagation();
    if (pendingDeleteClaimId === claimId) {
      setPendingDeleteClaimId(null);
      setClaimsCache((prev) => {
        const claims = prev[eventId];
        if (!claims) return prev;
        return { ...prev, [eventId]: claims.filter((c) => c.id !== claimId) };
      });
      void deleteClaim(claimId);
    } else {
      setPendingDeleteClaimId(claimId);
      setTimeout(() => setPendingDeleteClaimId((cur) => cur === claimId ? null : cur), 3000);
    }
  }

  // Reset expanded state when topic changes
  useEffect(() => {
    setExpandedClaimsId(null);
    setClaimsCache({});
    setPendingDeleteEventId(null);
    setPendingDeleteClaimId(null);
  }, [activeTopicId]);

  return (
    <div className="space-y-4">

      {/* ── Events (Knowledge Objects) ─────────────────────────────────────── */}
      <div className="rounded-lg border border-border bg-surface shadow-sm p-3">
        <div className="flex items-center justify-between gap-2 mb-3">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted flex items-center gap-1.5">
            <Radio className="w-3.5 h-3.5 text-accent" />
            Events
          </h3>
          {selectedKnowledgeEventId && (
            <button
              onClick={() => { setSelectedKnowledgeEvent(null); setSelectedEventContext(null); }}
              className="flex items-center gap-1 text-[10px] text-accent hover:text-accent-hover transition-colors"
            >
              <X className="w-3 h-3" />
              Clear filter
            </button>
          )}
        </div>

        {eventsLoading ? (
          <div className="flex items-center gap-2 py-3">
            <Loader2 className="w-3.5 h-3.5 text-accent animate-spin" />
            <span className="text-[10px] text-muted">Loading events…</span>
          </div>
        ) : uniqueEvents.length === 0 ? (
          <p className="text-[10px] text-muted py-2">
            No multi-source events yet. Events appear when 2+ sources cover the same story.
          </p>
        ) : (
          <div className="space-y-1.5">
            {uniqueEvents.map((ev) => {
              const isSelected = selectedKnowledgeEventId === ev.id;
              const isKept = ev.is_kept === 1;
              const isPendingDelete = pendingDeleteEventId === ev.id;
              return (
                <div
                  key={ev.id}
                  role="button"
                  tabIndex={0}
                  onClick={() => handleSelectEvent(ev)}
                  onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); handleSelectEvent(ev); } }}
                  className={`w-full text-left rounded-md p-2.5 border transition-all group cursor-pointer ${
                    isSelected
                      ? "border-accent/40 bg-accent/8"
                      : "border-border/50 bg-surface/60 hover:border-accent/20 hover:bg-accent/4"
                  }`}
                >
                  <p className={`text-[11px] font-semibold leading-snug line-clamp-2 ${isSelected ? "text-accent" : "text-foreground"}`}>
                    {ev.title}
                  </p>
                  {ev.summary && (
                    <p className="text-[10px] text-muted mt-0.5 line-clamp-2 leading-snug">
                      {ev.summary}
                    </p>
                  )}
                  <div className="flex items-center gap-2 mt-1.5 flex-wrap">
                    <span className="flex items-center gap-1 text-[9px] text-muted">
                      <Users className="w-2.5 h-2.5" />
                      {ev.source_count} sources
                    </span>
                    {ev.last_seen_at && (
                      <span className="text-[9px] text-muted">
                        {timeAgo(ev.last_seen_at)}
                      </span>
                    )}

                    {/* Action buttons — visible on hover */}
                    <div className="hidden group-hover:flex items-center gap-1 ml-auto">
                      {/* Ask AI */}
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          handleSelectEvent(ev);
                          useStore.getState().setChatOpen(true);
                        }}
                        className="flex items-center gap-0.5 text-[9px] text-accent/70 hover:text-accent transition-colors px-1"
                        title="Ask AI about this event"
                      >
                        <MessageSquare className="w-2.5 h-2.5" />
                      </button>
                      {/* Bookmark */}
                      <button
                        onClick={(e) => handleToggleKept(e, ev)}
                        className={`text-[9px] transition-colors px-1 ${isKept ? "text-accent" : "text-muted hover:text-accent"}`}
                        title={isKept ? "Remove bookmark" : "Bookmark event"}
                      >
                        {isKept
                          ? <BookmarkCheck className="w-2.5 h-2.5" />
                          : <Bookmark className="w-2.5 h-2.5" />
                        }
                      </button>
                      {/* Archive */}
                      <button
                        onClick={(e) => handleArchiveEvent(e, ev)}
                        className="text-[9px] text-muted hover:text-foreground transition-colors px-1"
                        title="Archive event"
                      >
                        <Archive className="w-2.5 h-2.5" />
                      </button>
                      {/* Delete (two-step) */}
                      <button
                        onClick={(e) => handleDeleteEventRequest(e, ev.id)}
                        className={`text-[9px] transition-colors px-1 ${
                          isPendingDelete
                            ? "text-red-500 font-medium"
                            : "text-muted hover:text-red-400"
                        }`}
                        title={isPendingDelete ? "Click again to confirm delete" : "Delete event"}
                      >
                        {isPendingDelete ? (
                          <span className="text-[9px]">Confirm?</span>
                        ) : (
                          <Trash2 className="w-2.5 h-2.5" />
                        )}
                      </button>
                    </div>

                    {/* Claims toggle — always visible */}
                    <button
                      onClick={(e) => handleToggleClaims(e, ev.id)}
                      className={`flex items-center gap-0.5 text-[9px] transition-colors ${
                        expandedClaimsId === ev.id
                          ? "text-accent"
                          : "text-muted hover:text-foreground"
                      } ${!uniqueEvents.some(() => true) ? "ml-auto" : ""}`}
                      style={{ marginLeft: "auto" }}
                      title={expandedClaimsId === ev.id ? "Hide key judgments" : "Show key judgments"}
                    >
                      <FileText className="w-2.5 h-2.5" />
                      Claims
                      {expandedClaimsId === ev.id
                        ? <ChevronUp className="w-2.5 h-2.5 ml-0.5" />
                        : <ChevronDown className="w-2.5 h-2.5 ml-0.5" />
                      }
                    </button>
                  </div>

                  {/* ── Inline Claims Panel ── */}
                  {expandedClaimsId === ev.id && (
                    <div
                      className="mt-2 pt-2 border-t border-border/40"
                      onClick={(e) => e.stopPropagation()}
                    >
                      {claimsCache[ev.id] === null ? (
                        <div className="flex items-center gap-1.5 py-1">
                          <Loader2 className="w-3 h-3 text-accent animate-spin" />
                          <span className="text-[10px] text-muted">Loading claims…</span>
                        </div>
                      ) : (claimsCache[ev.id] ?? []).length === 0 ? (
                        <p className="text-[10px] text-muted py-1">
                          No key judgments yet for this event.
                        </p>
                      ) : (
                        <div className="space-y-2">
                          <p className="text-[9px] uppercase tracking-wider text-muted font-semibold flex items-center gap-1">
                            <FileText className="w-2.5 h-2.5" />
                            Key Judgments
                          </p>
                          {(claimsCache[ev.id] ?? []).map((claim) => {
                            const effectiveStatus = claim.lifecycle_status ?? claim.status;
                            const staleness = claim.staleness_status ?? "fresh";
                            const isSuperseded = effectiveStatus === "superseded" || effectiveStatus === "inactive" || staleness === "replaced";
                            const isPendingDeleteClaim = pendingDeleteClaimId === claim.id;
                            const isUpdating = updatingClaimId === claim.id;
                            return (
                              <div
                                key={claim.id}
                                className={`rounded-md border p-2 space-y-0.5 transition-opacity ${
                                  isSuperseded
                                    ? "border-border/20 bg-surface/40 opacity-50"
                                    : "border-border/40 bg-surface/80"
                                }`}
                              >
                                <p className={`text-[11px] font-medium leading-snug ${
                                  isSuperseded ? "text-muted line-through" : "text-foreground"
                                }`}>
                                  {claim.statement}
                                </p>
                                {claim.summary && !isSuperseded && (
                                  <p className="text-[10px] text-muted leading-snug">
                                    {claim.summary}
                                  </p>
                                )}
                                <div className="flex flex-wrap items-center gap-1.5 mt-1">
                                  {claim.claim_kind && (
                                    <span className="px-1.5 py-0.5 rounded border border-border/50 text-[9px] text-muted bg-surface">
                                      {getClaimKindLabel(claim.claim_kind)}
                                    </span>
                                  )}
                                  <span className={`px-1.5 py-0.5 rounded border text-[9px] ${
                                    isSuperseded
                                      ? "border-border/30 text-muted/60 bg-surface"
                                      : effectiveStatus === "active" && staleness === "fresh"
                                        ? "border-green-500/30 text-green-600 bg-green-500/5"
                                        : staleness === "stale" || effectiveStatus === "stale"
                                          ? "border-yellow-500/30 text-yellow-600 bg-yellow-500/5"
                                          : "border-border/50 text-muted bg-surface"
                                  }`}>
                                    {isSuperseded ? "Superseded" : getClaimStatusLabel(effectiveStatus)}
                                  </span>
                                  {claim.evidence_count > 1 && (
                                    <span className="text-[9px] text-muted">
                                      {claim.evidence_count} evidence
                                    </span>
                                  )}

                                  {/* Claim CRUD actions */}
                                  <div className="flex items-center gap-1 ml-auto">
                                    {isUpdating ? (
                                      <Loader2 className="w-3 h-3 text-accent animate-spin" />
                                    ) : (
                                      <>
                                        {effectiveStatus !== "active" && (
                                          <button
                                            onClick={(e) => handleUpdateClaimStatus(e, ev.id, claim.id, "active")}
                                            className="text-[9px] text-green-600 hover:text-green-500 transition-colors px-1 py-0.5 rounded hover:bg-green-500/10"
                                            title="Mark as active"
                                          >
                                            ✓ Confirm
                                          </button>
                                        )}
                                        {effectiveStatus !== "rejected" && (
                                          <button
                                            onClick={(e) => handleUpdateClaimStatus(e, ev.id, claim.id, "rejected")}
                                            className="text-[9px] text-red-400 hover:text-red-500 transition-colors px-1 py-0.5 rounded hover:bg-red-500/10"
                                            title="Reject this claim"
                                          >
                                            ✗ Reject
                                          </button>
                                        )}
                                        <button
                                          onClick={(e) => handleDeleteClaimRequest(e, ev.id, claim.id)}
                                          className={`text-[9px] transition-colors px-1 py-0.5 rounded ${
                                            isPendingDeleteClaim
                                              ? "text-red-500 font-medium bg-red-500/10"
                                              : "text-muted hover:text-red-400 hover:bg-red-500/10"
                                          }`}
                                          title={isPendingDeleteClaim ? "Click again to confirm" : "Delete claim"}
                                        >
                                          {isPendingDeleteClaim ? "Sure?" : <Trash2 className="w-2.5 h-2.5" />}
                                        </button>
                                      </>
                                    )}
                                  </div>
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

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

      {/* Knowledge Overview + Evolution — merged panel */}
      <div className="rounded-lg border border-border bg-surface shadow-sm p-3 space-y-3">
        {/* Header row */}
        <div className="flex items-center justify-between gap-2">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted flex items-center gap-1.5">
            <Sparkles className="w-3.5 h-3.5 text-accent" />
            Knowledge Overview
          </h3>
          <div className="flex items-center gap-1">
            <button
              onClick={handleGenerateEvolution}
              disabled={evolutionGenerating}
              className="p-1 rounded text-muted hover:text-foreground hover:bg-surface-hover transition-colors disabled:opacity-40"
              title={evolutionArtifact?.content ? "Regenerate evolution narrative" : "Generate evolution narrative"}
            >
              <GitBranch
                className={`w-3 h-3 ${evolutionGenerating ? "animate-pulse" : ""}`}
              />
            </button>
            <button
              onClick={handleGenerate}
              disabled={globalGenerating}
              className="p-1 rounded text-muted hover:text-foreground hover:bg-surface-hover transition-colors disabled:opacity-40"
              title={globalContent ? "Regenerate overview" : "Generate global overview"}
            >
              <RefreshCw className={`w-3 h-3 ${globalGenerating ? "animate-spin" : ""}`} />
            </button>
          </div>
        </div>

        {/* Overview loading */}
        {globalGenerating && (
          <div className="flex items-center gap-2 py-1">
            <Loader2 className="w-3.5 h-3.5 text-accent animate-spin" />
            <span className="text-[10px] text-muted">Synthesizing global overview…</span>
          </div>
        )}

        {/* Overview content */}
        {globalContent ? (
          <AnalysisRichText content={globalContent} citations={globalCitations} />
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

        {/* Evolution section — always visible */}
        <div className="border-t border-border/40" />
        <div className="space-y-1.5">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-muted flex items-center gap-1">
            <GitBranch className="w-3 h-3" />
            Evolution Narrative
          </p>
          {(evolutionLoading || evolutionGenerating) && (
            <div className="flex items-center gap-2 py-1">
              <Loader2 className="w-3.5 h-3.5 text-accent animate-spin" />
              <span className="text-[10px] text-muted">Building evolution narrative…</span>
            </div>
          )}
          {evolutionArtifact?.content ? (
            <AnalysisRichText
              content={evolutionArtifact.content}
              citations={evolutionArtifact.metadata?.citations}
            />
          ) : !evolutionGenerating && !evolutionLoading ? (
            <button
              onClick={handleGenerateEvolution}
              className="w-full py-2.5 rounded-lg border border-dashed border-border text-center hover:border-accent/40 hover:bg-accent/5 transition-colors group"
            >
              <GitBranch className="w-3.5 h-3.5 text-muted group-hover:text-accent mx-auto mb-1" />
              <span className="text-[10px] text-muted group-hover:text-foreground">
                Generate Evolution Narrative
              </span>
            </button>
          ) : null}
        </div>
      </div>


      {/* Snapshot Timeline — with inline deltas */}
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
            {snapshots.slice(0, 6).map((snapshot) => {
              const delta = deltaBySnapshotId.get(snapshot.id);
              const timelineTs = snapshot.window_end || snapshot.created_at;
              return (
                <div key={snapshot.id} className="rounded-md border border-border/50 bg-surface/60 p-2">
                  <div className="flex items-center justify-between gap-2 text-[10px] text-muted">
                    <span>{new Date(timelineTs + "Z").toLocaleString()}</span>
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

                  {/* Inline delta summary */}
                  {delta && (
                    <div className="mt-2 pt-2 border-t border-border/30">
                      {delta.change_summary && (
                        <p className="text-[10px] text-muted italic leading-snug mb-1.5">
                          {delta.change_summary}
                        </p>
                      )}
                      <div className="flex flex-wrap gap-1">
                        {delta.new_event_ids.length > 0 && (
                          <span className="px-1.5 py-0.5 rounded text-[9px] bg-green-500/10 text-green-600 border border-green-500/20">
                            +{delta.new_event_ids.length} new
                          </span>
                        )}
                        {delta.resolved_event_ids.length > 0 && (
                          <span className="px-1.5 py-0.5 rounded text-[9px] bg-muted/10 text-muted border border-border/40">
                            -{delta.resolved_event_ids.length} resolved
                          </span>
                        )}
                        {(delta.strengthened_claim_ids.length + delta.weakened_claim_ids.length + delta.superseded_claim_ids.length) > 0 && (
                          <span className="px-1.5 py-0.5 rounded text-[9px] bg-accent/8 text-accent/80 border border-accent/20">
                            ~{delta.strengthened_claim_ids.length + delta.weakened_claim_ids.length + delta.superseded_claim_ids.length} claims
                          </span>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

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
