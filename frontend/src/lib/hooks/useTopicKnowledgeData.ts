"use client";

import { useCallback, useEffect, useState } from "react";
import {
  fetchClaims,
  fetchEvidence,
  fetchEvolutionReportStatus,
  fetchSnapshotDeltas,
  fetchSynthesisArtifact,
  fetchTemporalSnapshots,
  postEvolutionReportGenerate,
  type Claim,
  type EvidenceSet,
  type SnapshotDelta,
  type SynthesisArtifact,
  type TemporalSnapshot,
} from "@/lib/api";
import { usePollingTask } from "./usePollingTask";

interface TopicKnowledgeData {
  claims: Claim[];
  evidence: EvidenceSet[];
  snapshots: TemporalSnapshot[];
  deltas: SnapshotDelta[];
  overviewArtifact: SynthesisArtifact | null;
  evolutionArtifact: SynthesisArtifact | null;
  loadingClaims: boolean;
  loadingEvidence: boolean;
  loadingSnapshots: boolean;
  loadingEvolution: boolean;
  generatingEvolution: boolean;
  knowledgeError: string | null;
  refreshKnowledge: () => Promise<void>;
  triggerEvolution: () => Promise<void>;
}

export function useTopicKnowledgeData(
  topicId: number | null,
): TopicKnowledgeData {
  const [claims, setClaims] = useState<Claim[]>([]);
  const [evidence, setEvidence] = useState<EvidenceSet[]>([]);
  const [snapshots, setSnapshots] = useState<TemporalSnapshot[]>([]);
  const [deltas, setDeltas] = useState<SnapshotDelta[]>([]);
  const [overviewArtifact, setOverviewArtifact] =
    useState<SynthesisArtifact | null>(null);
  const [evolutionArtifact, setEvolutionArtifact] =
    useState<SynthesisArtifact | null>(null);
  const [loadingClaims, setLoadingClaims] = useState(false);
  const [loadingEvidence, setLoadingEvidence] = useState(false);
  const [loadingSnapshots, setLoadingSnapshots] = useState(false);
  const [loadingEvolution, setLoadingEvolution] = useState(false);
  const [generatingEvolution, setGeneratingEvolution] = useState(false);
  const [knowledgeError, setKnowledgeError] = useState<string | null>(null);

  const refreshKnowledge = useCallback(async () => {
    if (topicId == null) return;
    setKnowledgeError(null);
    setLoadingClaims(true);
    setLoadingEvidence(true);
    setLoadingSnapshots(true);
    setLoadingEvolution(true);
    try {
      const [
        snapshotRows,
        claimRows,
        evidenceRows,
        globalArtifact,
        deltaRows,
        evolutionReport,
        evolutionStatus,
      ] = await Promise.all([
        fetchTemporalSnapshots(topicId),
        fetchClaims(topicId),
        fetchEvidence(topicId),
        fetchSynthesisArtifact(topicId, "global-overview"),
        fetchSnapshotDeltas(topicId),
        fetchSynthesisArtifact(topicId, "evolution-report"),
        fetchEvolutionReportStatus(topicId),
      ]);
      setSnapshots(snapshotRows);
      setClaims(claimRows);
      setEvidence(evidenceRows);
      setOverviewArtifact(globalArtifact);
      setDeltas(deltaRows);
      setEvolutionArtifact(evolutionReport);
      setGeneratingEvolution(evolutionStatus.generating);
    } catch {
      setKnowledgeError(
        "Failed to load the knowledge workspace. Please retry.",
      );
    } finally {
      setLoadingClaims(false);
      setLoadingEvidence(false);
      setLoadingSnapshots(false);
      setLoadingEvolution(false);
    }
  }, [topicId]);

  useEffect(() => {
    if (topicId == null) {
      setClaims([]);
      setEvidence([]);
      setSnapshots([]);
      setDeltas([]);
      setOverviewArtifact(null);
      setEvolutionArtifact(null);
      setGeneratingEvolution(false);
      setKnowledgeError(null);
      return;
    }
    void refreshKnowledge();
  }, [topicId, refreshKnowledge]);

  const refreshEvolutionOnly = useCallback(async () => {
    if (topicId == null) return;
    const [status, artifact, deltaRows] = await Promise.all([
      fetchEvolutionReportStatus(topicId),
      fetchSynthesisArtifact(topicId, "evolution-report"),
      fetchSnapshotDeltas(topicId),
    ]);
    setGeneratingEvolution(status.generating);
    setEvolutionArtifact(artifact);
    setDeltas(deltaRows);
  }, [topicId]);

  usePollingTask(generatingEvolution && topicId != null, refreshEvolutionOnly, 2000);

  const triggerEvolution = useCallback(async () => {
    if (topicId == null || generatingEvolution) return;
    const res = await postEvolutionReportGenerate(topicId);
    if (res.started || res.already_running) {
      setGeneratingEvolution(true);
    }
  }, [generatingEvolution, topicId]);

  return {
    claims,
    evidence,
    snapshots,
    deltas,
    overviewArtifact,
    evolutionArtifact,
    loadingClaims,
    loadingEvidence,
    loadingSnapshots,
    loadingEvolution,
    generatingEvolution,
    knowledgeError,
    refreshKnowledge,
    triggerEvolution,
  };
}
