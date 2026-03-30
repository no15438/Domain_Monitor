import { Minus, TrendingDown, TrendingUp } from "lucide-react";

export const sentimentConfig = {
  positive: { icon: TrendingUp, color: "text-positive", bg: "bg-positive/10" },
  negative: { icon: TrendingDown, color: "text-negative", bg: "bg-negative/10" },
  neutral: { icon: Minus, color: "text-muted", bg: "bg-muted/10" },
} as const;

export function shouldShowTrackingPin(isPinned: boolean) {
  return isPinned;
}
