"use client";

export function getClaimKindLabel(kind: string | null | undefined): string {
  switch ((kind ?? "").toLowerCase()) {
    case "observation":
      return "Observed pattern";
    case "forecast":
      return "Forward-looking view";
    case "trend":
      return "Trend view";
    case "structural":
      return "Structural view";
    default:
      return "Working view";
  }
}

export function getClaimKindExplain(kind: string | null | undefined): string {
  switch ((kind ?? "").toLowerCase()) {
    case "observation":
      return "A pattern observed from recent signals, not necessarily a long-term conclusion.";
    case "forecast":
      return "A predictive view based on current data and trends.";
    case "trend":
      return "An ongoing directional shift observed over time.";
    case "structural":
      return "A fundamental or systemic change in the domain.";
    default:
      return "A working hypothesis currently being evaluated.";
  }
}

export function getClaimStatusLabel(status: string | null | undefined): string {
  switch ((status ?? "").toLowerCase()) {
    case "active":
      return "Current view";
    case "stale":
      return "Needs refresh";
    case "inactive":
      return "Dormant view";
    case "superseded":
      return "Replaced view";
    default:
      return "Working view";
  }
}

export function getClaimStatusExplain(status: string | null | undefined): string {
  switch ((status ?? "").toLowerCase()) {
    case "active":
      return "This view is currently considered valid and supported by recent signals.";
    case "stale":
      return "This view has not been supported by recent signals and may need re-evaluation.";
    case "inactive":
      return "This view is no longer actively tracked or supported.";
    case "superseded":
      return "This view has been replaced by a more recent or accurate claim.";
    default:
      return "The current status of this view is still being determined.";
  }
}

export function getFreshnessLabel(status: string | null | undefined): string {
  switch ((status ?? "").toLowerCase()) {
    case "fresh":
      return "Recently refreshed";
    case "stale":
      return "No recent support";
    case "replaced":
      return "Replaced by a newer view";
    default:
      return "Refresh state unknown";
  }
}

export function getReviewStateLabel(state: string | null | undefined): string {
  switch ((state ?? "").toLowerCase()) {
    case "machine_only":
      return "Machine-only review";
    case "human_reviewed":
      return "Human reviewed";
    case "confirmed":
      return "Confirmed";
    default:
      return "Review status unknown";
  }
}

export function getSnapshotStatusLabel(status: string | null | undefined): string {
  switch ((status ?? "").toLowerCase()) {
    case "final":
      return "Ready";
    case "draft":
      return "Draft";
    default:
      return "Status unknown";
  }
}
