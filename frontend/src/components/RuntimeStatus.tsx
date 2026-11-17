"use client";

import { useEffect, useState } from "react";

export default function RuntimeStatus() {
  const [message, setMessage] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    const base = process.env.NEXT_PUBLIC_API_BASE?.replace(/\/$/, "") || "";
    fetch(`${base}/api/runtime`, { signal: controller.signal, cache: "no-store" })
      .then(response => response.ok ? response.json() : null)
      .then(data => {
        if (!data || controller.signal.aborted) return;
        if (!data.external_calls_enabled) setMessage("Local mode: topics, documents, and event memory are available. News collection and AI generation are not enabled.");
        else if (!data.model_configured) setMessage("AI is not configured. Configure a model provider to enable generation and chat.");
      }).catch(() => { /* The page provides its own connection error and retry. */ });
    return () => controller.abort();
  }, []);
  return message ? <div role="status" className="border-b border-border bg-accent/5 px-6 py-2 text-xs text-muted">{message}</div> : null;
}
