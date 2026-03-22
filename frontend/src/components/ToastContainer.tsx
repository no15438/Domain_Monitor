"use client";

import { X, AlertTriangle, Info, AlertCircle } from "lucide-react";
import { useStore } from "@/stores/useStore";

const ICON_MAP = {
  error: AlertCircle,
  warn: AlertTriangle,
  info: Info,
} as const;

const STYLE_MAP = {
  error: "bg-negative/10 border-negative/40 text-negative",
  warn: "bg-important/10 border-important/40 text-important",
  info: "bg-accent/10 border-accent/40 text-accent",
} as const;

export default function ToastContainer() {
  const toasts = useStore((s) => s.toasts);
  const dismiss = useStore((s) => s.dismissToast);

  if (toasts.length === 0) return null;

  return (
    <div
      role="alert"
      aria-live="polite"
      aria-atomic="false"
      className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 max-w-sm"
    >
      {toasts.map((t) => {
        const Icon = ICON_MAP[t.level];
        return (
          <div
            key={t.id}
            role="status"
            className={`flex items-start gap-2 px-3 py-2.5 rounded-lg border text-xs animate-slide-in-right shadow-lg backdrop-blur-sm ${STYLE_MAP[t.level]}`}
          >
            <Icon className="w-3.5 h-3.5 shrink-0 mt-0.5" aria-hidden="true" />
            <span className="flex-1 leading-relaxed">{t.message}</span>
            <button
              onClick={() => dismiss(t.id)}
              aria-label="Dismiss notification"
              className="shrink-0 opacity-60 hover:opacity-100"
            >
              <X className="w-3 h-3" aria-hidden="true" />
            </button>
          </div>
        );
      })}
    </div>
  );
}
