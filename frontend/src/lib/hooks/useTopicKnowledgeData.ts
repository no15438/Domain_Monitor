"use client";

import { useCallback, useEffect, useState } from "react";
import {
  fetchSnapshotDeltas,
  fetchSynthesisArtifact,
  fetchTemporalSnapshots,
  type SnapshotDelta,
  type SynthesisArtifact,
  type TemporalSnapshot,
} from "@/lib/api";

interface TopicKnowledgeData {
  snapshots: TemporalSnapshot[];
  deltas: SnapshotDelta[];
  overviewArtifact: SynthesisArtifact | null;
  loadingSnapshots: boolean;
  knowledgeError: string | null;
  refreshKnowledge: () => Promise<void>;
}

export function useTopicKnowledgeData(
  topicId: number | null,
): TopicKnowledgeData {
  const [snapshots, setSnapshots] = useState<TemporalSnapshot[]>([]);
  const [deltas, setDeltas] = useState<SnapshotDelta[]>([]);
  const [overviewArtifact, setOverviewArtifact] =
    useState<SynthesisArtifact | null>(null);
  const [loadingSnapshots, setLoadingSnapshots] = useState(false);
  const [knowledgeError, setKnowledgeError] = useState<string | null>(null);

  const refreshKnowledge = useCallback(async () => {
    if (topicId == null) return;
    setKnowledgeError(null);
    setLoadingSnapshots(true);
    try {
      const [snapshotRows, globalArtifact, deltaRows] = await Promise.all([
        fetchTemporalSnapshots(topicId),
        fetchSynthesisArtifact(topicId, "global-overview"),
        fetchSnapshotDeltas(topicId),
      ]);
      setSnapshots(snapshotRows);
      setOverviewArtifact(globalArtifact);
      setDeltas(deltaRows);
    } catch {
      setKnowledgeError(
        "Failed to load the knowledge workspace. Please retry.",
      );
    } finally {
      setLoadingSnapshots(false);
    }
  }, [topicId]);

  useEffect(() => {
    if (topicId == null) {
      setSnapshots([]);
      setDeltas([]);
      setOverviewArtifact(null);
      setKnowledgeError(null);
      return;
    }
    void refreshKnowledge();
  }, [topicId, refreshKnowledge]);

  return {
    snapshots,
    deltas,
    overviewArtifact,
    loadingSnapshots,
    knowledgeError,
    refreshKnowledge,
  };
}
