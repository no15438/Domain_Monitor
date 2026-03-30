"use client";

import { useEffect } from "react";

export function usePollingTask(
  enabled: boolean,
  task: () => Promise<void> | void,
  intervalMs: number,
) {
  useEffect(() => {
    if (!enabled) return;
    let active = true;

    const run = async () => {
      if (!active) return;
      await task();
    };

    void run();
    const timer = window.setInterval(() => {
      void run();
    }, intervalMs);

    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [enabled, intervalMs, task]);
}
