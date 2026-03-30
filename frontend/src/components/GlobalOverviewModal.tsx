"use client";

import { useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import ReactMarkdown from "react-markdown";
import { X, Sparkles, Loader2, RefreshCw } from "lucide-react";
import { useStore } from "@/stores/useStore";

export default function GlobalOverviewModal({
  topicId,
  onClose,
}: {
  topicId: number;
  onClose: () => void;
}) {
  const hydrateGlobalOverview = useStore((s) => s.hydrateGlobalOverview);
  const startGlobalOverviewGeneration = useStore((s) => s.startGlobalOverviewGeneration);
  const slice = useStore((s) => s.globalOverviewByTopic[topicId]);

  const content = slice?.content ?? "";
  const isGenerating = slice?.isGenerating ?? false;
  const [isChecking, setIsChecking] = useState(true);
  const closeBtnRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    setIsChecking(true);
    void hydrateGlobalOverview(topicId).finally(() => setIsChecking(false));
  }, [topicId, hydrateGlobalOverview]);

  useEffect(() => {
    closeBtnRef.current?.focus();
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  return (
    <AnimatePresence>
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-background/80 backdrop-blur-sm">
        <button
          type="button"
          className="absolute inset-0"
          aria-label="Close overview dialog"
          onClick={onClose}
        />
        <motion.div
          initial={{ opacity: 0, scale: 0.95, y: 20 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.95, y: 20 }}
          role="dialog"
          aria-modal="true"
          aria-labelledby="global-overview-title"
          className="w-full max-w-4xl max-h-[85vh] flex flex-col bg-surface border border-border rounded-xl shadow-2xl overflow-hidden"
        >
          <div className="flex items-center justify-between p-4 border-b border-border bg-surface-hover/30">
            <div className="flex items-center gap-2">
              <div className="p-1.5 rounded-lg bg-accent/20">
                <Sparkles className="w-5 h-5 text-accent" />
              </div>
              <h2 id="global-overview-title" className="text-lg font-bold">Global Overview</h2>
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => void startGlobalOverviewGeneration(topicId)}
                disabled={isGenerating || isChecking}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium text-muted hover:text-foreground hover:bg-surface-hover transition-colors disabled:opacity-40"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${isGenerating ? "animate-spin" : ""}`} />
                {isChecking ? "Checking..." : content ? "Regenerate" : "Generate"}
              </button>
              <button
                type="button"
                ref={closeBtnRef}
                onClick={onClose}
                className="p-1.5 rounded-md text-muted hover:text-foreground hover:bg-surface-hover transition-colors"
                title="Close (generation continues in background)"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
          </div>

          <div className="flex-1 overflow-y-auto p-6 md:p-8">
            {(isGenerating || isChecking) && !content && (
              <div className="flex flex-col items-center justify-center min-h-[200px] gap-4 text-muted">
                <Loader2 className="w-8 h-8 animate-spin text-accent" />
                <p className="text-sm text-center">
                  {isChecking && !isGenerating ? "Checking generation status..." : "Synthesizing global overview…"}
                  <br />
                  <span className="text-xs opacity-80">You can close this window; it will keep running and save when done.</span>
                </p>
              </div>
            )}

            {isGenerating && !!content && (
              <p className="text-xs text-muted mb-3 flex items-center gap-2">
                <Loader2 className="w-3.5 h-3.5 animate-spin text-accent shrink-0" />
                Updating overview… (safe to close this panel)
              </p>
            )}

            {!content && !isGenerating && !isChecking && (
              <div className="flex flex-col items-center justify-center min-h-[200px] gap-4 text-center">
                <div className="p-4 rounded-full bg-surface-hover">
                  <Sparkles className="w-8 h-8 text-muted" />
                </div>
                <div>
                  <h3 className="text-sm font-semibold mb-1">No Overview Generated Yet</h3>
                  <p className="text-xs text-muted max-w-sm">
                    Generate a macro-level guide based on historical snapshots and important articles.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => void startGlobalOverviewGeneration(topicId)}
                  className="px-4 py-2 mt-2 rounded-lg bg-accent text-accent-foreground text-sm font-medium hover:bg-accent/90 transition-colors"
                >
                  Generate Now
                </button>
              </div>
            )}

            {content && (
              <div className="ai-summary-content prose prose-invert prose-sm md:prose-base max-w-none">
                <ReactMarkdown>{content}</ReactMarkdown>
              </div>
            )}
          </div>
        </motion.div>
      </div>
    </AnimatePresence>
  );
}
