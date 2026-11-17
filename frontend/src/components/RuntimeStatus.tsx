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
        if (!data.external_calls_enabled) setMessage("本地模式：话题、资料和事件记忆可用。新闻采集与 AI 生成功能尚未启用。");
        else if (!data.model_configured) setMessage("AI 服务尚未配置。设置模型服务后，可使用生成与对话功能。");
      }).catch(() => { /* The page provides its own connection error and retry. */ });
    return () => controller.abort();
  }, []);
  return message ? <div role="status" className="border-b border-border bg-accent/5 px-6 py-2 text-xs text-muted">{message}</div> : null;
}
