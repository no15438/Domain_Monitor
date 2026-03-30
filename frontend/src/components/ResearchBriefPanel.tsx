"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import {
  FileText,
  Sparkles,
  Plus,
  X,
  Rss,
  Save,
  ChevronDown,
  ChevronRight,
  Loader2,
  Tag,
  PanelLeftClose,
  PanelLeftOpen,
  Compass,
  Building2,
  Globe2,
  Factory,
  Send,
} from "lucide-react";
import { useStore } from "@/stores/useStore";
import {
  updateTopicBrief,
  updateResearchConfig,
  generateResearchPlan,
  fetchKeywords,
  addKeyword,
  removeKeyword,
  fetchTopicFeeds,
  addTopicFeed,
  removeTopicFeed,
  parseResearchConfig,
  type TopicFeed,
  type ResearchConfig,
  type Topic,
} from "@/lib/api";

interface Props {
  topic: Topic;
  collapsed: boolean;
  onToggle: () => void;
}

type SectionKey = "keywords" | "feeds" | "angles" | "entities" | "geo" | "sector";

function ChipList({
  items,
  onRemove,
  onAdd,
  placeholder,
  accentClass = "bg-accent/15 text-accent-hover",
}: {
  items: { id: string; label: string }[];
  onRemove: (id: string) => void;
  onAdd: (val: string) => void;
  placeholder: string;
  accentClass?: string;
}) {
  const [adding, setAdding] = useState(false);
  const [val, setVal] = useState("");

  function handleSubmit() {
    const v = val.trim();
    if (!v) return;
    onAdd(v);
    setVal("");
    setAdding(false);
  }

  return (
    <div className="space-y-1.5">
      <div className="flex flex-wrap gap-1.5">
        {items.map((it) => (
          <span
            key={it.id}
            className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium ${accentClass}`}
          >
            {it.label}
            <button onClick={() => onRemove(it.id)} className="hover:text-negative transition-colors">
              <X className="w-2.5 h-2.5" />
            </button>
          </span>
        ))}
      </div>
      {adding ? (
        <form onSubmit={(e) => { e.preventDefault(); handleSubmit(); }} className="flex items-center gap-1">
          <input
            autoFocus
            value={val}
            onChange={(e) => setVal(e.target.value)}
            placeholder={placeholder}
            className="flex-1 px-2 py-1 rounded-md text-xs bg-background border border-border focus:border-accent outline-none"
          />
          <button type="submit" className="px-2 py-1 rounded-md text-xs bg-accent text-white hover:bg-accent-hover">
            Add
          </button>
          <button type="button" onClick={() => setAdding(false)} className="text-muted hover:text-foreground">
            <X className="w-3 h-3" />
          </button>
        </form>
      ) : (
        <button onClick={() => setAdding(true)} className="inline-flex items-center gap-1 text-[11px] text-muted hover:text-foreground transition-colors">
          <Plus className="w-3 h-3" />
          Add
        </button>
      )}
    </div>
  );
}

function Section({
  title,
  icon: Icon,
  count,
  isOpen,
  onToggle,
  children,
}: {
  title: string;
  icon: React.ElementType;
  count: number;
  isOpen: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="border-t border-border">
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-2 px-3 py-2 text-[10px] uppercase tracking-wider text-muted font-semibold hover:bg-surface-hover transition-colors"
      >
        {isOpen ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
        <Icon className="w-3 h-3" />
        {title}
        <span className="ml-auto text-[10px] font-normal">{count}</span>
      </button>
      {isOpen && <div className="px-3 pb-3">{children}</div>}
    </div>
  );
}

export default function ResearchBriefPanel({ topic, collapsed, onToggle }: Props) {
  const { activeTopicId, keywords, setKeywords } = useStore();
  const [brief, setBrief] = useState(topic.research_brief ?? "");
  const [config, setConfig] = useState<ResearchConfig>(() => parseResearchConfig(topic));
  const [saved, setSaved] = useState(true);
  const [saving, setSaving] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [promptInput, setPromptInput] = useState("");
  const [feeds, setFeeds] = useState<TopicFeed[]>([]);
  const [openSections, setOpenSections] = useState<Set<SectionKey>>(
    new Set(["keywords", "angles"]),
  );
  const saveTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => {
    setBrief(topic.research_brief ?? "");
    setConfig(parseResearchConfig(topic));
    setSaved(true);
  }, [topic]);

  useEffect(() => {
    if (activeTopicId != null) {
      fetchTopicFeeds(activeTopicId).then((d) => setFeeds(d.feeds)).catch((e) => { if (process.env.NODE_ENV === "development") console.warn("[fetch]", e); });
    }
  }, [activeTopicId]);

  const toggle = (key: SectionKey) =>
    setOpenSections((prev) => {
      const next = new Set(prev);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });

  const debouncedSaveBrief = useCallback(
    (val: string) => {
      setSaved(false);
      if (saveTimer.current) clearTimeout(saveTimer.current);
      saveTimer.current = setTimeout(async () => {
        if (activeTopicId == null) return;
        setSaving(true);
        await updateTopicBrief(activeTopicId, val);
        setSaving(false);
        setSaved(true);
      }, 1200);
    },
    [activeTopicId],
  );

  function handleBriefChange(val: string) {
    setBrief(val);
    debouncedSaveBrief(val);
  }

  async function handleManualSave() {
    if (activeTopicId == null) return;
    setSaving(true);
    if (saveTimer.current) clearTimeout(saveTimer.current);
    await updateTopicBrief(activeTopicId, brief);
    setSaving(false);
    setSaved(true);
  }

  async function persistConfig(updated: ResearchConfig) {
    setConfig(updated);
    if (activeTopicId != null) {
      await updateResearchConfig(activeTopicId, updated);
    }
  }

  // ── AI Generate Full Plan ──
  async function handleGenerate() {
    if (activeTopicId == null || !promptInput.trim()) return;
    setGenerating(true);
    const res = await generateResearchPlan(activeTopicId, promptInput.trim());
    if (res.status === "ok" && res.plan) {
      setBrief(res.plan.research_brief);
      setSaved(true);
      setConfig({
        angles: res.plan.angles ?? [],
        entities: res.plan.entities ?? [],
        geographic_scope: res.plan.geographic_scope ?? [],
        sector_scope: res.plan.sector_scope ?? [],
      });
      const kwData = await fetchKeywords(activeTopicId);
      setKeywords(kwData.keywords);
      const feedData = await fetchTopicFeeds(activeTopicId);
      setFeeds(feedData.feeds);
      setPromptInput("");
      setOpenSections(new Set(["keywords", "angles", "entities", "feeds"]));
    }
    setGenerating(false);
  }

  // ── Keyword CRUD ──
  async function handleAddKw(kw: string) {
    if (activeTopicId == null) return;
    await addKeyword(kw, "", activeTopicId);
    const data = await fetchKeywords(activeTopicId);
    setKeywords(data.keywords);
  }

  async function handleRemoveKw(id: string) {
    await removeKeyword(Number(id));
    if (activeTopicId != null) {
      const data = await fetchKeywords(activeTopicId);
      setKeywords(data.keywords);
    }
  }

  // ── Feed CRUD ──
  async function handleAddFeed(url: string) {
    if (activeTopicId == null) return;
    await addTopicFeed(activeTopicId, url);
    const d = await fetchTopicFeeds(activeTopicId);
    setFeeds(d.feeds);
  }

  async function handleRemoveFeed(id: string) {
    await removeTopicFeed(Number(id));
    if (activeTopicId != null) {
      const d = await fetchTopicFeeds(activeTopicId);
      setFeeds(d.feeds);
    }
  }

  // ── Config array CRUD helpers ──
  function addToConfig(key: keyof ResearchConfig, val: string) {
    const updated = { ...config, [key]: [...config[key], val] };
    persistConfig(updated);
  }

  function removeFromConfig(key: keyof ResearchConfig, val: string) {
    const updated = { ...config, [key]: config[key].filter((v) => v !== val) };
    persistConfig(updated);
  }

  // ── Collapsed State ──
  if (collapsed) {
    return (
      <div className="w-10 shrink-0 border-r border-border bg-surface flex flex-col items-center pt-3 gap-3">
        <button onClick={onToggle} className="p-1.5 rounded-lg text-muted hover:text-foreground hover:bg-surface-hover transition-colors" title="Expand research panel">
          <PanelLeftOpen className="w-4 h-4" />
        </button>
        <div className="w-5 h-5 rounded-md bg-accent/15 flex items-center justify-center">
          <FileText className="w-3 h-3 text-accent" />
        </div>
      </div>
    );
  }

  return (
    <div className="w-[280px] shrink-0 border-r border-border bg-surface flex flex-col overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2.5 border-b border-border bg-surface">
        <div className="flex items-center gap-2 min-w-0">
          <FileText className="w-4 h-4 text-accent shrink-0" />
          <span className="text-xs font-semibold tracking-tight truncate">Research Brief</span>
        </div>
        <button onClick={onToggle} className="p-1 rounded text-muted hover:text-foreground hover:bg-surface-hover transition-colors" title="Collapse">
          <PanelLeftClose className="w-3.5 h-3.5" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto">
        {/* AI Generate Prompt */}
        <div className="p-3 border-b border-border bg-linear-to-b from-accent/5 to-transparent">
          <label className="text-[10px] uppercase tracking-wider text-muted font-semibold mb-1.5 flex items-center gap-1">
            <Sparkles className="w-3 h-3 text-accent" />
            AI Research Setup
          </label>
          <p className="text-[11px] text-muted mb-2 leading-relaxed">
            Describe what you want to research — AI will generate keywords, RSS feeds, angles, entities and more.
          </p>
          <div className="flex gap-1.5">
            <textarea
              value={promptInput}
              onChange={(e) => setPromptInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleGenerate();
                }
              }}
              placeholder="Describe what you want to research…"
              rows={2}
              className="flex-1 px-2.5 py-1.5 text-xs leading-relaxed rounded-lg bg-background border border-border focus:border-accent outline-none resize-none placeholder:text-muted/50"
            />
            <button
              onClick={handleGenerate}
              disabled={generating || !promptInput.trim()}
              className="self-end p-2 rounded-lg bg-accent text-white hover:bg-accent-hover disabled:opacity-40 transition-colors shrink-0"
              title="Generate research plan"
            >
              {generating ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
            </button>
          </div>
          {generating && (
            <p className="text-[10px] text-accent mt-1.5 animate-pulse">
              AI is generating your research plan…
            </p>
          )}
        </div>

        {/* Research Direction (editable brief) */}
        <div className="p-3">
          <label className="text-[10px] uppercase tracking-wider text-muted font-semibold mb-1.5 block">
            Research Direction
          </label>
          <textarea
            value={brief}
            onChange={(e) => handleBriefChange(e.target.value)}
            placeholder="Your refined research direction will appear here after AI generation, or write it manually…"
            className="w-full h-24 px-2.5 py-2 text-xs leading-relaxed rounded-lg bg-background border border-border focus:border-accent outline-none resize-none placeholder:text-muted/50"
          />
          <div className="flex items-center justify-between mt-1">
            <span className="text-[10px] text-muted">
              {saving ? "Saving…" : saved ? "✓ Saved" : "Unsaved"}
            </span>
            {!saved && (
              <button
                onClick={handleManualSave}
                className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium text-muted hover:text-foreground hover:bg-surface-hover transition-colors"
              >
                <Save className="w-3 h-3" />
                Save
              </button>
            )}
          </div>
        </div>

        {/* Keywords */}
        <Section title="Keywords" icon={Tag} count={keywords.length} isOpen={openSections.has("keywords")} onToggle={() => toggle("keywords")}>
          <ChipList
            items={keywords.map((kw) => ({ id: String(kw.id), label: kw.keyword }))}
            onRemove={handleRemoveKw}
            onAdd={handleAddKw}
            placeholder="keyword…"
          />
        </Section>

        {/* Research Angles */}
        <Section title="Research Angles" icon={Compass} count={config.angles.length} isOpen={openSections.has("angles")} onToggle={() => toggle("angles")}>
          <div className="space-y-1.5">
            {config.angles.map((a, i) => (
              <div key={`${a}-${i}`} className="flex items-start gap-2 text-[11px] px-2 py-1.5 rounded bg-background group leading-relaxed">
                <span className="text-accent font-semibold shrink-0 mt-0.5">{i + 1}.</span>
                <span className="flex-1">{a}</span>
                <button
                  onClick={() => removeFromConfig("angles", a)}
                  className="opacity-0 group-hover:opacity-100 text-muted hover:text-negative transition-opacity shrink-0 mt-0.5"
                >
                  <X className="w-3 h-3" />
                </button>
              </div>
            ))}
            <AddItemInline placeholder="New research angle…" onAdd={(v) => addToConfig("angles", v)} />
          </div>
        </Section>

        {/* Key Entities */}
        <Section title="Key Entities" icon={Building2} count={config.entities.length} isOpen={openSections.has("entities")} onToggle={() => toggle("entities")}>
          <ChipList
            items={config.entities.map((e) => ({ id: e, label: e }))}
            onRemove={(id) => removeFromConfig("entities", id)}
            onAdd={(v) => addToConfig("entities", v)}
            placeholder="entity…"
            accentClass="bg-amber-500/15 text-amber-600 dark:text-amber-400"
          />
        </Section>

        {/* Geographic Scope */}
        <Section title="Geographic Scope" icon={Globe2} count={config.geographic_scope.length} isOpen={openSections.has("geo")} onToggle={() => toggle("geo")}>
          <ChipList
            items={config.geographic_scope.map((g) => ({ id: g, label: g }))}
            onRemove={(id) => removeFromConfig("geographic_scope", id)}
            onAdd={(v) => addToConfig("geographic_scope", v)}
            placeholder="region…"
            accentClass="bg-emerald-500/15 text-emerald-600 dark:text-emerald-400"
          />
        </Section>

        {/* Sector Scope */}
        <Section title="Sector Scope" icon={Factory} count={config.sector_scope.length} isOpen={openSections.has("sector")} onToggle={() => toggle("sector")}>
          <ChipList
            items={config.sector_scope.map((s) => ({ id: s, label: s }))}
            onRemove={(id) => removeFromConfig("sector_scope", id)}
            onAdd={(v) => addToConfig("sector_scope", v)}
            placeholder="sector…"
            accentClass="bg-violet-500/15 text-violet-600 dark:text-violet-400"
          />
        </Section>

        {/* RSS Feeds */}
        <Section title="RSS Feeds" icon={Rss} count={feeds.length} isOpen={openSections.has("feeds")} onToggle={() => toggle("feeds")}>
          <div className="space-y-1.5">
            {feeds.length === 0 && (
              <p className="text-[11px] text-muted">No feeds configured.</p>
            )}
            {feeds.map((f) => (
              <div key={f.id} className="flex items-center gap-2 text-[11px] px-2 py-1 rounded bg-background group">
                <Rss className="w-3 h-3 text-accent shrink-0" />
                <span className="truncate flex-1" title={f.feed_url}>
                  {f.label || f.feed_url}
                </span>
                <button
                  onClick={() => handleRemoveFeed(String(f.id))}
                  className="opacity-0 group-hover:opacity-100 text-muted hover:text-negative transition-opacity"
                >
                  <X className="w-3 h-3" />
                </button>
              </div>
            ))}
            <AddItemInline placeholder="https://example.com/rss" onAdd={handleAddFeed} />
          </div>
        </Section>
      </div>
    </div>
  );
}

function AddItemInline({ placeholder, onAdd }: { placeholder: string; onAdd: (v: string) => void }) {
  const [adding, setAdding] = useState(false);
  const [val, setVal] = useState("");

  function handleSubmit() {
    const v = val.trim();
    if (!v) return;
    onAdd(v);
    setVal("");
    setAdding(false);
  }

  if (!adding) {
    return (
      <button onClick={() => setAdding(true)} className="inline-flex items-center gap-1 text-[11px] text-muted hover:text-foreground transition-colors">
        <Plus className="w-3 h-3" />
        Add
      </button>
    );
  }

  return (
    <form onSubmit={(e) => { e.preventDefault(); handleSubmit(); }} className="flex items-center gap-1">
      <input
        autoFocus
        value={val}
        onChange={(e) => setVal(e.target.value)}
        placeholder={placeholder}
        className="flex-1 px-2 py-1 rounded-md text-xs bg-background border border-border focus:border-accent outline-none"
      />
      <button type="submit" className="px-2 py-1 rounded-md text-xs bg-accent text-white hover:bg-accent-hover">
        Add
      </button>
      <button type="button" onClick={() => setAdding(false)} className="text-muted hover:text-foreground">
        <X className="w-3 h-3" />
      </button>
    </form>
  );
}
