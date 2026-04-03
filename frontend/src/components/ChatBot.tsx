"use client";

import { Fragment, useRef, useEffect, useState, useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Send, Trash2, X, Bot, User,
  ChevronDown, ChevronRight, CheckCircle2, CircleDashed,
  ExternalLink,
} from "lucide-react";
import { useStore } from "@/stores/useStore";
import { streamChat } from "@/lib/api";
import type { ChatTracePayload, ChatSource } from "@/lib/api";

// ─── Chat-rich text with inline source chips ─────────────────────────────────

const CHAT_INLINE_RE =
  /\*\*(.+?)\*\*|\*([^*\n]+?)\*|\[([^\]]{1,120})\]\[([A-Z]\d+)\]|\[([A-Z]\d+)\]|\[([^\]]{2,120})\]/g;

function normalizeSourceLabel(value: string): string {
  return value
    .toLowerCase()
    .replace(/[—–-]/g, " ")
    .replace(/[^a-z0-9\u4e00-\u9fa5]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function truncateLabel(value: string, max = 28): string {
  return value.length > max ? `${value.slice(0, max - 1)}…` : value;
}

function resolveSourceMatch(label: string, sourceId: string | undefined, sources: ChatSource[]) {
  if (sourceId) {
    const exact = sources.find((source) => source.id.toUpperCase() === sourceId.toUpperCase());
    if (exact) return exact;
  }

  const normalizedLabel = normalizeSourceLabel(label);
  if (!normalizedLabel) return undefined;

  return sources.find((source) => {
    const normalizedTitle = normalizeSourceLabel(source.title);
    return (
      normalizedTitle === normalizedLabel ||
      normalizedTitle.includes(normalizedLabel) ||
      normalizedLabel.includes(normalizedTitle)
    );
  });
}

/**
 * Determines if a ChatSource should trigger in-app navigation instead of an
 * external link. Returns the raw entity id (e.g. the event id string without
 * the "event:" prefix) when navigation is applicable, otherwise null.
 */
function parseInternalNav(
  source: ChatSource | undefined,
): { kind: "event" | "snapshot" | "artifact"; rawId: string } | null {
  if (!source) return null;
  // If the source has a real http(s) URL, prefer external link; skip nav.
  if (source.url && /^https?:\/\//i.test(source.url)) return null;

  const id = source.id;
  if (id.startsWith("event:")) return { kind: "event", rawId: id.slice("event:".length) };
  if (id.startsWith("snapshot:")) return { kind: "snapshot", rawId: id.slice("snapshot:".length) };
  if (id.startsWith("artifact:")) return { kind: "artifact", rawId: id.slice("artifact:".length) };
  return null;
}

type OnNavigate = (source: ChatSource, nav: NonNullable<ReturnType<typeof parseInternalNav>>) => void;

function renderChatInline(
  text: string,
  sources: ChatSource[],
  keyPrefix: string,
  onNavigate: OnNavigate,
): React.ReactNode[] {
  const parts: React.ReactNode[] = [];
  const re = new RegExp(CHAT_INLINE_RE.source, "g");
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = re.exec(text)) !== null) {
    if (match.index > lastIndex) parts.push(text.slice(lastIndex, match.index));

    if (match[1] !== undefined) {
      parts.push(
        <strong key={`${keyPrefix}-b${match.index}`}>
          {renderChatInline(match[1], sources, `${keyPrefix}-b${match.index}`, onNavigate)}
        </strong>
      );
    } else if (match[2] !== undefined) {
      parts.push(
        <em key={`${keyPrefix}-i${match.index}`}>
          {renderChatInline(match[2], sources, `${keyPrefix}-i${match.index}`, onNavigate)}
        </em>
      );
    } else {
      const label = (match[3] ?? match[5] ?? match[6] ?? "").trim();
      const sourceId = match[4];
      const matchedSource = resolveSourceMatch(label, sourceId, sources);
      // Any bracket token this regex already matched should render as a chip (long titles
      // like event headlines must not fall through as plain text).
      const isBracketCitation = (match[3] ?? match[5] ?? match[6]) !== undefined;
      if (
        !matchedSource &&
        !sourceId &&
        (!isBracketCitation || label.trim().length < 2)
      ) {
        parts.push(match[0]);
        lastIndex = match.index + match[0].length;
        continue;
      }
      const displayLabel = truncateLabel(matchedSource?.title || label || sourceId || "Source");
      const nav = parseInternalNav(matchedSource);

      const chip = (
        <span className="inline-flex items-center gap-1 rounded-full border border-accent/25 bg-accent/8 px-1.5 py-0.5 text-[10px] font-medium text-accent/90 align-baseline">
          <span>{displayLabel}</span>
          {!matchedSource?.title && (matchedSource?.url || sourceId) && (
            <span className="text-[9px] opacity-60">{sourceId ?? null}</span>
          )}
          {matchedSource?.url && !nav && <ExternalLink className="w-2.5 h-2.5 shrink-0 opacity-60" />}
        </span>
      );

      if (matchedSource?.url && !nav) {
        // External link — open in new tab
        parts.push(
          <a
            key={`${keyPrefix}-c${match.index}`}
            href={matchedSource.url}
            target="_blank"
            rel="noreferrer"
            title={matchedSource.title}
            className="chat-cite-link mx-0.5 inline-flex align-baseline"
            onClick={(e) => e.stopPropagation()}
          >
            {chip}
          </a>,
        );
      } else if (nav && matchedSource) {
        // Internal navigation — switch tab + highlight knowledge object
        parts.push(
          <button
            key={`${keyPrefix}-c${match.index}`}
            type="button"
            title={matchedSource.title}
            className="chat-cite-link mx-0.5 inline-flex cursor-pointer items-baseline border-0 bg-transparent p-0 font-inherit text-inherit"
            onClick={(e) => { e.stopPropagation(); onNavigate(matchedSource, nav); }}
          >
            {chip}
          </button>,
        );
      } else {
        // No URL, no nav — passive chip
        parts.push(
          <span
            key={`${keyPrefix}-c${match.index}`}
            title={matchedSource?.title ?? label}
            className="chat-cite-link mx-0.5 inline-flex align-baseline"
          >
            {chip}
          </span>,
        );
      }
    }

    lastIndex = match.index + match[0].length;
  }

  if (lastIndex < text.length) parts.push(text.slice(lastIndex));
  return parts.length ? parts : [text];
}

function renderChatBlocks(
  content: string,
  sources: ChatSource[],
  onNavigate: OnNavigate,
): React.ReactNode[] {
  const lines = content.split("\n");
  const blocks: React.ReactNode[] = [];
  let listItems: React.ReactNode[] = [];
  let listOrdered = false;
  let paraLines: string[] = [];
  let key = 0;

  const flushPara = () => {
    if (paraLines.length === 0) return;
    const text = paraLines.join(" ").trim();
    if (text) {
      blocks.push(
        <p key={key++}>
          {renderChatInline(text, sources, `p${key}`, onNavigate).map((node, index) => (
            <Fragment key={index}>{node}</Fragment>
          ))}
        </p>,
      );
    }
    paraLines = [];
  };

  const flushList = () => {
    if (listItems.length === 0) return;
    blocks.push(listOrdered ? <ol key={key++}>{listItems}</ol> : <ul key={key++}>{listItems}</ul>);
    listItems = [];
  };

  for (const rawLine of lines) {
    const trimmed = rawLine.trim();

    if (!trimmed) {
      flushList();
      flushPara();
      continue;
    }

    const headingMatch = trimmed.match(/^(#{1,6})\s+(.+)$/);
    if (headingMatch) {
      flushList();
      flushPara();
      const level = Math.min(headingMatch[1].length, 4);
      const headingText = renderChatInline(headingMatch[2], sources, `h${level}-${key}`, onNavigate).map(
        (node, index) => <Fragment key={index}>{node}</Fragment>,
      );
      if (level === 1) blocks.push(<h1 key={key++}>{headingText}</h1>);
      else if (level === 2) blocks.push(<h2 key={key++}>{headingText}</h2>);
      else if (level === 3) blocks.push(<h3 key={key++}>{headingText}</h3>);
      else blocks.push(<h4 key={key++}>{headingText}</h4>);
      continue;
    }

    const ulMatch = trimmed.match(/^[-*]\s+(.+)$/);
    if (ulMatch) {
      flushPara();
      if (listOrdered) flushList();
      listOrdered = false;
      listItems.push(
        <li key={key++}>
          {renderChatInline(ulMatch[1], sources, `li${key}`, onNavigate).map((node, index) => (
            <Fragment key={index}>{node}</Fragment>
          ))}
        </li>,
      );
      continue;
    }

    const olMatch = trimmed.match(/^\d+\.\s+(.+)$/);
    if (olMatch) {
      flushPara();
      if (!listOrdered && listItems.length > 0) flushList();
      listOrdered = true;
      listItems.push(
        <li key={key++}>
          {renderChatInline(olMatch[1], sources, `li${key}`, onNavigate).map((node, index) => (
            <Fragment key={index}>{node}</Fragment>
          ))}
        </li>,
      );
      continue;
    }

    flushList();
    paraLines.push(trimmed);
  }

  flushList();
  flushPara();
  return blocks;
}

function ChatRichText({ content, sources }: { content: string; sources: ChatSource[] }) {
  const activeTopicId = useStore((s) => s.activeTopicId);
  const setAnalysisTab = useStore((s) => s.setAnalysisTab);
  const setSelectedKnowledgeEvent = useStore((s) => s.setSelectedKnowledgeEvent);
  const setChatOpen = useStore((s) => s.setChatOpen);

  const onNavigate = useMemo<OnNavigate>(
    () => (_source, nav) => {
      if (nav.kind === "event") {
        if (activeTopicId != null) setAnalysisTab(activeTopicId, "overview");
        setSelectedKnowledgeEvent(nav.rawId, _source.title || null);
        setChatOpen(false);
        // Scroll the event row into view after the panel has had a chance to render
        setTimeout(() => {
          const el = document.querySelector(`[data-knowledge-event-id="${nav.rawId}"]`);
          el?.scrollIntoView({ behavior: "smooth", block: "nearest" });
        }, 120);
      }
      // snapshot / artifact: handled in a later iteration
    },
    [activeTopicId, setAnalysisTab, setSelectedKnowledgeEvent, setChatOpen],
  );

  const blocks = useMemo(
    () => renderChatBlocks(content, sources, onNavigate),
    [content, sources, onNavigate],
  );
  return <div className="chat-markdown">{blocks}</div>;
}

// ─── RAG path thinking bar ────────────────────────────────────────────────────

const KB_LAYER_LABELS: Record<string, string> = {
  current_state: "Current state",
  timeline: "Timeline",
  archive: "Historical background",
};

/**
 * Single-line summary of the actual RAG execution path.
 * During loading: shows the current in-progress stage.
 * After done: reads `final_route_label` from answer_generation meta for the
 * true path (e.g. "Knowledge base (Current state + Timeline) → Generate answer"),
 * falling back to reconstructing it from the individual trace states.
 */
function buildRouteSummary(traces: ChatTracePayload[], isLoading: boolean): string {
  const genT = traces.find((t) => t.kind === "answer_generation");
  const vecT = traces.find((t) => t.kind === "vector_supplement");
  const webT = traces.find((t) => t.kind === "web_fallback");
  const kbHits = traces.find((t) => t.kind === "kb_hits");

  if (traces.length === 0) return "Analyzing your question…";

  if (isLoading) {
    if (genT?.state === "running") return "Generating answer…";
    if (vecT?.state === "running") return "Running vector supplement…";
    if (webT?.state === "running") return "Searching the web…";
    if (kbHits) {
      const n = kbHits.meta?.total_nodes ?? kbHits.nodes?.length ?? 0;
      const layers = (kbHits.meta?.retrieval_layers ?? []) as string[];
      const layerText = layers.map((l) => KB_LAYER_LABELS[l] ?? l).join(" + ");
      if (layerText && n > 0) return `Retrieved ${layerText} — ${n} records, consolidating…`;
      if (n > 0) return `Knowledge base hit ${n} records, consolidating…`;
      return "Consolidating knowledge base results…";
    }
    return "Searching knowledge base…";
  }

  // Prefer the explicit final_route_label emitted by backend
  const finalLabel = genT?.meta?.final_route_label as string | undefined;
  if (finalLabel) return finalLabel;

  // Fallback: reconstruct from individual traces
  const layers = (kbHits?.meta?.retrieval_layers ?? []) as string[];
  const parts: string[] = [];
  if (layers.length > 0) {
    const layerText = layers.map((l) => KB_LAYER_LABELS[l] ?? l).join(" + ");
    parts.push(`Knowledge base (${layerText})`);
  }
  if (vecT?.meta?.used) parts.push("Vector supplement");
  if (webT?.meta?.used) parts.push("Web search");
  if (parts.length === 0) parts.push("General retrieval");
  parts.push("Generate answer");
  return parts.join(" → ");
}

type HighLevelStep = { key: string; text: string; running: boolean };

/**
 * 3-4 high-level steps for the expanded view.
 * Only actually-executed stages are shown; skipped ones are omitted.
 */
function buildHighLevelSteps(traces: ChatTracePayload[], isLoading: boolean): HighLevelStep[] {
  const steps: HighLevelStep[] = [];
  const intent = traces.find((t) => t.kind === "intent");
  const kbHits = traces.find((t) => t.kind === "kb_hits");
  const vecT   = traces.find((t) => t.kind === "vector_supplement");
  const webT   = traces.find((t) => t.kind === "web_fallback");
  const genT   = traces.find((t) => t.kind === "answer_generation");

  // Step 1: intent classification
  if (intent) {
    const routeLabel = intent.meta?.route_label as string | undefined;
    steps.push({
      key: "intent",
      text: routeLabel ? `Classify question → Path: ${routeLabel}` : "Classify question",
      running: false,
    });
  } else if (isLoading) {
    steps.push({ key: "intent", text: "Classifying question…", running: true });
  }

  // Step 2: structured KB retrieval
  if (kbHits) {
    const layers = (kbHits.meta?.retrieval_layers ?? []) as string[];
    const counts = kbHits.meta?.hit_counts ?? {};
    const total = kbHits.meta?.total_nodes ?? kbHits.nodes?.length ?? 0;
    if (layers.length > 0) {
      const detail = layers
        .map((l) => {
          const n = (counts as Record<string, number>)[l];
          const label = KB_LAYER_LABELS[l] ?? l;
          return n != null ? `${label} (${n})` : label;
        })
        .join(", ");
      steps.push({
        key: "kb",
        text: `Knowledge base: ${detail} — ${total} total`,
        running: false,
      });
    } else {
      steps.push({
        key: "kb",
        text: total > 0 ? `Knowledge base — ${total} records` : "Knowledge base (no matches)",
        running: false,
      });
    }
  } else if (intent && isLoading) {
    steps.push({ key: "kb", text: "Searching knowledge base…", running: true });
  }

  // Step 3: supplemental retrieval — only when actually triggered
  const vecRunning = vecT?.state === "running";
  const vecDone    = vecT?.meta?.used === true;
  const webRunning = webT?.state === "running";
  const webDone    = webT?.meta?.used === true;

  if (vecRunning) {
    steps.push({ key: "supp", text: "Running vector supplement…", running: true });
  } else if (webRunning) {
    steps.push({ key: "supp", text: "Searching the web…", running: true });
  } else if (vecDone && webDone) {
    steps.push({ key: "supp", text: "Vector supplement + live web search", running: false });
  } else if (vecDone) {
    steps.push({ key: "supp", text: "Vector supplement", running: false });
  } else if (webDone) {
    steps.push({ key: "supp", text: "Live web search", running: false });
  }
  // if neither used nor running: omit step entirely

  // Step 4: answer generation — use isLoading as the source of truth for the spinner,
  // not genT.state (which stays "running" until the backend emits the done event).
  if (!isLoading && steps.length > 0) {
    steps.push({ key: "gen", text: "Generate answer", running: false });
  } else if (genT?.state === "running") {
    steps.push({ key: "gen", text: "Generating answer…", running: true });
  } else if (kbHits && isLoading && !genT) {
    steps.push({ key: "gen", text: "Preparing answer…", running: true });
  }

  return steps;
}

function ThinkingBar({
  traces,
  isLoading,
}: {
  traces: ChatTracePayload[];
  isLoading: boolean;
}) {
  const [expanded, setExpanded] = useState(false);

  if (traces.length === 0 && !isLoading) return null;

  const summary = buildRouteSummary(traces, isLoading);
  const steps   = buildHighLevelSteps(traces, isLoading);

  return (
    <div className="mb-3">
      <button
        onClick={() => setExpanded((v) => !v)}
        disabled={steps.length === 0}
        className="flex items-center gap-1.5 text-left group disabled:cursor-default"
      >
        <span className="shrink-0">
          {isLoading ? (
            <CircleDashed className="w-3.5 h-3.5 text-accent/60 animate-spin" />
          ) : (
            <CheckCircle2 className="w-3.5 h-3.5 text-positive/70" />
          )}
        </span>
        <span className={`text-[11px] ${isLoading ? "text-muted/75 italic" : "text-muted/65"}`}>
          {summary}
        </span>
        {steps.length > 0 && (
          <span className="shrink-0 text-muted/30 group-hover:text-muted/60 transition-colors">
            {expanded ? (
              <ChevronDown className="w-3 h-3" />
            ) : (
              <ChevronRight className="w-3 h-3" />
            )}
          </span>
        )}
      </button>

      <AnimatePresence>
        {expanded && steps.length > 0 && (
          <motion.div
            key="steps"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="overflow-hidden"
          >
            <div className="mt-1.5 ml-5 border-l border-border/40 pl-3 space-y-1.5 pb-0.5">
              {steps.map((step) => (
                <div key={step.key} className="flex items-center gap-1.5 text-[10px] text-muted/60">
                  {step.running ? (
                    <CircleDashed className="w-2.5 h-2.5 shrink-0 text-accent/55 animate-spin" />
                  ) : (
                    <CheckCircle2 className="w-2.5 h-2.5 shrink-0 text-positive/45" />
                  )}
                  <span>{step.text}</span>
                </div>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function ChatBot({
  layout = "desktop",
}: {
  layout?: "desktop" | "mobile";
}) {
  const {
    chatMessagesByTopic,
    chatTraceByTopic,
    chatSourcesByTopic,
    addChatMessage,
    appendToLastAssistant,
    clearChat,
    appendChatTrace,
    clearChatTrace,
    setChatSources,
    selectedArticle,
    setSelectedArticle,
    selectedEventContext,
    setSelectedEventContext,
    isChatLoading,
    setChatLoading,
    chatOpen,
    setChatOpen,
    activeTopicId,
  } = useStore();

  const chatMessages = chatMessagesByTopic[String(activeTopicId ?? "null")] ?? [];
  const chatTraces = chatTraceByTopic?.[String(activeTopicId ?? "null")] ?? [];
  const chatSources = chatSourcesByTopic?.[String(activeTopicId ?? "null")] ?? [];
  const isMobile = layout === "mobile";

  const [input, setInput] = useState("");
  const [chatStatus, setChatStatus] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    return () => { abortRef.current?.abort(); };
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatMessages, chatTraces, chatStatus]);

  useEffect(() => {
    if (selectedArticle || selectedEventContext) {
      inputRef.current?.focus();
    }
  }, [selectedArticle, selectedEventContext]);

  const hasContext = !!(selectedArticle || selectedEventContext);
  const contextTitle = selectedEventContext?.title ?? selectedArticle?.title ?? "";

  function buildContextString(): string | undefined {
    if (selectedEventContext) {
      const ec = selectedEventContext;
      return [
        `[Event] ${ec.title}`,
        ec.canonical_source ? `Source: ${ec.canonical_source}` : "",
        ec.canonical_url ? `URL: ${ec.canonical_url}` : "",
        ec.first_seen_at ? `First seen: ${ec.first_seen_at}` : "",
        ec.last_seen_at && ec.last_seen_at !== ec.first_seen_at ? `Last seen: ${ec.last_seen_at}` : "",
        `Sentiment: ${ec.sentiment} | Importance: ${ec.importance} | Sources covering: ${ec.source_count}`,
        ec.tags ? `Tags: ${ec.tags}` : "",
        ec.canonical_key_entities ? `Key Entities: ${ec.canonical_key_entities}` : "",
        ec.canonical_topic_analysis ? `AI Analysis: ${ec.canonical_topic_analysis}` : "",
        `Summary: ${ec.summary}`,
        ec.canonical_content ? `Content: ${ec.canonical_content.slice(0, 1200)}` : "",
      ].filter(Boolean).join("\n");
    }
    if (selectedArticle) {
      return [
        `Title: ${selectedArticle.title}`,
        `Source: ${selectedArticle.source} | URL: ${selectedArticle.url}`,
        `Published: ${selectedArticle.published_at}`,
        `Sentiment: ${selectedArticle.sentiment} | Importance: ${selectedArticle.importance}`,
        selectedArticle.tags ? `Tags: ${selectedArticle.tags}` : "",
        selectedArticle.key_entities ? `Key Entities: ${selectedArticle.key_entities}` : "",
        selectedArticle.topic_analysis ? `AI Analysis: ${selectedArticle.topic_analysis}` : "",
        `Summary: ${selectedArticle.summary}`,
        `Content: ${(selectedArticle.content ?? "").slice(0, 1200)}`,
      ].filter(Boolean).join("\n");
    }
    return undefined;
  }

  async function handleSend() {
    const msg = input.trim();
    if (!msg || isChatLoading) return;

    const ctx = buildContextString();
    const historyToSend = chatMessages.slice(-20).map((m) => ({
      role: m.role,
      content: m.content,
    }));

    addChatMessage({ id: crypto.randomUUID(), role: "user", content: msg });
    setInput("");
    clearChatTrace(activeTopicId);
    if (inputRef.current) inputRef.current.style.height = "auto";
    setChatLoading(true);
    addChatMessage({ id: crypto.randomUUID(), role: "assistant", content: "" });

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    try {
      for await (const event of streamChat(msg, ctx, activeTopicId, controller.signal, historyToSend)) {
        if (controller.signal.aborted) break;
        if (event.type === "status") {
          setChatStatus(event.value);
        } else if (event.type === "trace") {
          appendChatTrace(activeTopicId, event.value);
        } else if (event.type === "sources") {
          setChatSources(activeTopicId, event.value);
        } else {
          setChatStatus(null);
          appendToLastAssistant(event.value);
        }
      }
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") { /* intentional */ }
      else appendToLastAssistant("\n\n*[Error: failed to get response]*");
    } finally {
      setChatLoading(false);
      setChatStatus(null);
      setSelectedArticle(null);
      setSelectedEventContext(null);
    }
  }

  if (!chatOpen) return null;

  // Find the index of the last assistant message so we can attach trace/sources to it
  const lastAssistantIdx = (() => {
    for (let i = chatMessages.length - 1; i >= 0; i--) {
      if (chatMessages[i].role === "assistant") return i;
    }
    return -1;
  })();

  return (
    <div
      className={`flex flex-col bg-surface shadow-sm overflow-hidden ${
        isMobile
          ? "h-full min-h-0 w-full"
          : "flex-4 min-w-[320px] border-l border-border"
      }`}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border">
        <div className="flex items-center gap-2">
          <Bot className="w-4 h-4 text-accent" />
          <span className="text-sm font-semibold">AI Assistant</span>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={clearChat}
            className="p-1.5 rounded-md text-muted hover:text-foreground hover:bg-surface-hover transition-colors"
            title="Clear chat"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={() => setChatOpen(false)}
            className="p-1.5 rounded-md text-muted hover:text-foreground hover:bg-surface-hover transition-colors"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Context banner */}
      <AnimatePresence>
        {hasContext && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="px-4 py-2 bg-accent/10 border-b border-accent/20 overflow-hidden"
          >
            <div className="flex items-start justify-between gap-2">
              <p className="text-[11px] text-accent-hover line-clamp-2">
                {selectedEventContext ? "Event context: " : "Context: "}{contextTitle}
              </p>
              <button
                onClick={() => { setSelectedArticle(null); setSelectedEventContext(null); }}
                className="text-muted hover:text-foreground shrink-0"
              >
                <X className="w-3 h-3" />
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-4">
        {chatMessages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-muted text-center gap-2">
            <Bot className="w-10 h-10 opacity-30" />
            <p className="text-xs">Ask me anything about your monitored industries.</p>
            <p className="text-[10px] opacity-60">I can search local knowledge and the web.</p>
          </div>
        )}

        {chatMessages.map((msg, idx) => {
          const isLastAssistant = idx === lastAssistantIdx;
          const showTrace = isLastAssistant && (chatTraces.length > 0 || isChatLoading);

          return (
            <div
              key={msg.id}
              className={`flex gap-2.5 ${msg.role === "user" ? "justify-end" : ""}`}
            >
              {msg.role === "assistant" && (
                <div className="w-6 h-6 rounded-full bg-accent/15 flex items-center justify-center shrink-0 mt-0.5">
                  <Bot className="w-3.5 h-3.5 text-accent" />
                </div>
              )}

              <div className={`max-w-[85%] ${msg.role === "user" ? "" : "flex-1"}`}>
                {/* Thinking bar — shown above the bubble for last assistant */}
                {showTrace && (
                  <ThinkingBar
                    traces={chatTraces}
                    isLoading={isChatLoading || !!chatStatus}
                  />
                )}

                {/* Message bubble */}
                {msg.content && (
                  <div
                    className={`rounded-xl px-3 py-2 text-sm leading-relaxed ${
                      msg.role === "user"
                        ? "bg-accent text-white rounded-br-sm"
                        : "bg-surface-hover rounded-bl-sm"
                    }`}
                  >
                    {msg.role === "assistant" ? (
                      <ChatRichText content={msg.content} sources={isLastAssistant ? chatSources : []} />
                    ) : (
                      msg.content
                    )}
                  </div>
                )}
              </div>

              {msg.role === "user" && (
                <div className="w-6 h-6 rounded-full bg-surface-hover flex items-center justify-center shrink-0 mt-0.5">
                  <User className="w-3.5 h-3.5 text-muted" />
                </div>
              )}
            </div>
          );
        })}

        {/* Loading state when no assistant message yet */}
        {isChatLoading && lastAssistantIdx === -1 && (
          <div className="flex gap-2.5">
            <div className="w-6 h-6 rounded-full bg-accent/15 flex items-center justify-center shrink-0 mt-0.5">
              <Bot className="w-3.5 h-3.5 text-accent" />
            </div>
            <div className="flex-1">
              <ThinkingBar traces={chatTraces} isLoading />
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="p-3 border-t border-border">
        <form
          onSubmit={(e) => { e.preventDefault(); handleSend(); }}
          className="flex items-end gap-2"
        >
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => {
              setInput(e.target.value);
              e.target.style.height = "auto";
              e.target.style.height = `${Math.min(e.target.scrollHeight, 120)}px`;
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void handleSend();
              }
            }}
            placeholder={selectedArticle ? "Ask about this article…" : "Ask about industry trends…"}
            rows={1}
            className="flex-1 resize-none rounded-lg px-3 py-2 text-sm bg-background border border-border focus:border-accent outline-none placeholder:text-muted/60 overflow-y-auto"
            style={{ maxHeight: "120px" }}
          />
          <button
            type="submit"
            disabled={isChatLoading || !input.trim()}
            className="p-2.5 rounded-lg bg-accent text-white hover:bg-accent-hover disabled:opacity-40 transition-colors"
          >
            <Send className="w-4 h-4" />
          </button>
        </form>
      </div>
    </div>
  );
}
