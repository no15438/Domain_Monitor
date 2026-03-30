import { IMPORTANCE_DECAY_RATE, IMPORTANCE_THRESHOLD } from "./constants";

/**
 * Applies exponential time decay to an importance score.
 * Mirrors the SQL formula: importance * EXP(-0.023 * days_old)
 */
export function effectiveImportance(importance: number, dateStr: string | null | undefined): number {
  if (!dateStr) return importance;
  const then = new Date(dateStr).getTime();
  if (isNaN(then)) return importance;
  const daysOld = (Date.now() - then) / (1000 * 60 * 60 * 24);
  return importance * Math.exp(-IMPORTANCE_DECAY_RATE * Math.max(0, daysOld));
}

/**
 * Returns true if an article should be considered "important" after time decay.
 */
export function isArticleImportant(importance: number, dateStr: string | null | undefined): boolean {
  return effectiveImportance(importance, dateStr) >= IMPORTANCE_THRESHOLD;
}

/**
 * Parses a tags field which may be a JSON array string or comma-separated string.
 */
export function parseTags(tags: string | null | undefined): string[] {
  if (!tags) return [];
  try {
    const parsed = JSON.parse(tags);
    if (Array.isArray(parsed)) return parsed.map(String).filter(Boolean);
  } catch {
    // fall through to comma-split
  }
  return tags.split(",").map((t) => t.trim()).filter(Boolean);
}

/**
 * Returns a human-readable time-ago label (e.g. "2h ago", "3d ago").
 * Handles SQLite "YYYY-MM-DD HH:MM:SS" format and ISO strings with or without Z.
 */
export function timeAgo(dateStr: string | null | undefined): string | null {
  if (!dateStr) return null;
  // Normalise: replace space separator, add UTC suffix when no timezone present
  let s = dateStr.trim().replace(" ", "T");
  if (!s.endsWith("Z") && !/[+-]\d{2}:\d{2}$/.test(s)) s += "Z";
  const then = new Date(s).getTime();
  if (isNaN(then)) return null;
  const diffMs = Date.now() - then;
  if (diffMs < 0) return "just now";
  const diffMin = Math.floor(diffMs / 60_000);
  if (diffMin < 1) return "just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffH = Math.floor(diffMin / 60);
  if (diffH < 24) return `${diffH}h ago`;
  const diffD = Math.floor(diffH / 24);
  if (diffD < 30) return `${diffD}d ago`;
  const diffMo = Math.floor(diffD / 30);
  return `${diffMo}mo ago`;
}
