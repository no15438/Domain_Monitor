"use client";

import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import {
  BarChart3,
  BookOpen,
  Clock3,
  Loader2,
  RefreshCw,
  Sparkles,
  ChevronDown,
  ChevronUp,
  Check,
  X,
  Edit3,
  Trash2,
  ExternalLink,
  Bookmark,
  Database,
} from "lucide-react";
import {
  fetchSnapshots,
  fetchKeptArticles,
  updateSnapshot,
  deleteSnapshot,
  updateArticle,
  deleteArticle,
  toggleArticleKept,
  type Snapshot,
  type TrendingData,
  type Article,
} from "@/lib/api";
import { useStore } from "@/stores/useStore";

function tagsJsonToComma(tags: string): string {
  try {
    const arr = JSON.parse(tags || "[]");
    return Array.isArray(arr) ? arr.join(", ") : "";
  } catch {
    return "";
  }
}

function parseTagsArray(tags: string): string[] {
  try {
    const arr = JSON.parse(tags || "[]");
    return Array.isArray(arr) ? arr : [];
  } catch {
    return [];
  }
}

export default function MacroAnalysisPanel({
  activeTopicId,
  trending,
}: {
  activeTopicId: number | null;
  trending: TrendingData | null;
}) {
  const hydrateGlobalOverview = useStore((s) => s.hydrateGlobalOverview);
  const startGlobalOverviewGeneration = useStore((s) => s.startGlobalOverviewGeneration);
  const globalSlice = useStore((s) =>
    activeTopicId != null ? s.globalOverviewByTopic[activeTopicId] : undefined
  );

  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [loadingSnapshots, setLoadingSnapshots] = useState(false);
  const [keptArticles, setKeptArticles] = useState<Article[]>([]);
  const [loadingArticles, setLoadingArticles] = useState(false);
  const [showArticles, setShowArticles] = useState(true);

  useEffect(() => {
    if (activeTopicId == null) return;
    setLoadingSnapshots(true);
    setLoadingArticles(true);
    void hydrateGlobalOverview(activeTopicId);
    fetchSnapshots(activeTopicId)
      .then((rows) => setSnapshots(rows))
      .finally(() => setLoadingSnapshots(false));
    fetchKeptArticles(activeTopicId)
      .then((arts) => setKeptArticles(arts))
      .finally(() => setLoadingArticles(false));
  }, [activeTopicId, hydrateGlobalOverview]);

  const globalContent = globalSlice?.content ?? "";
  const globalGenerating = globalSlice?.isGenerating ?? false;

  const handleGenerate = () => {
    if (activeTopicId == null || globalGenerating) return;
    void startGlobalOverviewGeneration(activeTopicId);
  };

  const handleSnapshotDeleted = (id: number) =>
    setSnapshots((prev) => prev.filter((s) => s.id !== id));

  const handleSnapshotUpdated = (id: number, content: string) =>
    setSnapshots((prev) => prev.map((s) => (s.id === id ? { ...s, overview_content: content } : s)));

  const handleArticleDeleted = (id: string) =>
    setKeptArticles((prev) => prev.filter((a) => a.id !== id));

  const handleArticleUnkept = (id: string) =>
    setKeptArticles((prev) => prev.filter((a) => a.id !== id));

  return (
    <div className="space-y-4">
      {/* Global Overview */}
      <div className="rounded-lg border border-border/60 bg-surface/40 p-3">
        <div className="flex items-center justify-between gap-2 mb-2">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted flex items-center gap-1.5">
            <Sparkles className="w-3.5 h-3.5 text-accent" />
            Global Overview
          </h3>
          <button
            onClick={handleGenerate}
            disabled={globalGenerating}
            className="p-1 rounded text-muted hover:text-foreground hover:bg-surface-hover transition-colors disabled:opacity-40"
            title={globalContent ? "Regenerate" : "Generate global overview"}
          >
            <RefreshCw className={`w-3 h-3 ${globalGenerating ? "animate-spin" : ""}`} />
          </button>
        </div>

        {globalGenerating && (
          <div className="flex items-center gap-2 py-3">
            <Loader2 className="w-3.5 h-3.5 text-accent animate-spin" />
            <span className="text-[10px] text-muted">Synthesizing global overview…</span>
          </div>
        )}

        {globalContent ? (
          <div className="ai-summary-content text-xs">
            <ReactMarkdown>{globalContent}</ReactMarkdown>
          </div>
        ) : !globalGenerating ? (
          <button
            onClick={handleGenerate}
            className="w-full py-3 rounded-lg border border-dashed border-border text-center hover:border-accent/40 hover:bg-accent/5 transition-colors group"
          >
            <Sparkles className="w-4 h-4 text-muted group-hover:text-accent mx-auto mb-1" />
            <span className="text-[10px] text-muted group-hover:text-foreground">
              Generate Global Overview
            </span>
          </button>
        ) : null}
      </div>

      {/* Historical Snapshots */}
      <div className="rounded-lg border border-border/60 bg-surface/40 p-3">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-muted flex items-center gap-1.5 mb-2">
          <BookOpen className="w-3.5 h-3.5" />
          Historical Snapshots
        </h3>
        {loadingSnapshots ? (
          <p className="text-[10px] text-muted">Loading…</p>
        ) : snapshots.length === 0 ? (
          <p className="text-[10px] text-muted">No snapshots yet.</p>
        ) : (
          <div className="space-y-2">
            {snapshots.map((s) => (
              <SnapshotRow
                key={s.id}
                snapshot={s}
                topicId={activeTopicId!}
                onDeleted={handleSnapshotDeleted}
                onUpdated={handleSnapshotUpdated}
              />
            ))}
          </div>
        )}
      </div>

      {/* Core Articles (Knowledge Base) */}
      <div className="rounded-lg border border-border/60 bg-surface/40 p-3">
        <button
          onClick={() => setShowArticles((v) => !v)}
          className="w-full flex items-center justify-between gap-1.5 mb-2"
        >
          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted flex items-center gap-1.5">
            <Database className="w-3.5 h-3.5" />
            Core Articles
            {keptArticles.length > 0 && (
              <span className="text-[9px] bg-accent/15 text-accent px-1 py-0.5 rounded font-bold">
                {keptArticles.length}
              </span>
            )}
          </h3>
          {showArticles ? (
            <ChevronUp className="w-3.5 h-3.5 text-muted" />
          ) : (
            <ChevronDown className="w-3.5 h-3.5 text-muted" />
          )}
        </button>

        {showArticles && (
          <>
            {loadingArticles ? (
              <p className="text-[10px] text-muted">Loading…</p>
            ) : keptArticles.length === 0 ? (
              <p className="text-[10px] text-muted">
                No core articles yet. Right-click articles and save to Knowledge Base.
              </p>
            ) : (
              <div className="space-y-2">
                {keptArticles.map((art) => (
                  <ArticleRow
                    key={art.id}
                    article={art}
                    onDeleted={handleArticleDeleted}
                    onUnkept={handleArticleUnkept}
                  />
                ))}
              </div>
            )}
          </>
        )}
      </div>

      {/* Macro Signals */}
      <div className="rounded-lg border border-border/60 bg-surface/40 p-3">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-muted flex items-center gap-1.5 mb-2">
          <BarChart3 className="w-3.5 h-3.5" />
          Macro Signals
        </h3>
        {trending ? (
          <div className="space-y-2">
            <div className="text-[10px] text-muted">
              Avg Topic Relevance:{" "}
              <span className="text-foreground font-semibold">
                {Math.round((trending.avg_topic_relevance || 0) * 100)}%
              </span>
            </div>
            {trending.top_entities?.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {trending.top_entities.slice(0, 8).map((e) => (
                  <span
                    key={e.entity}
                    className="px-1.5 py-0.5 rounded text-[10px] bg-surface-hover text-muted"
                    title={`${e.entity}: ${e.count}`}
                  >
                    {e.entity}
                  </span>
                ))}
              </div>
            )}
          </div>
        ) : (
          <p className="text-[10px] text-muted">No macro signals yet.</p>
        )}
      </div>
    </div>
  );
}

function SnapshotRow({
  snapshot,
  topicId,
  onDeleted,
  onUpdated,
}: {
  snapshot: Snapshot;
  topicId: number;
  onDeleted: (id: number) => void;
  onUpdated: (id: number, content: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [content, setContent] = useState(snapshot.overview_content);
  const [isSaving, setIsSaving] = useState(false);

  let statsStr = "";
  try {
    const stats = JSON.parse(snapshot.stats_metadata);
    statsStr = `${stats.total_articles} articles · ${stats.important_count} important`;
    if (stats.trend_delta !== undefined)
      statsStr += ` · ${stats.trend_delta > 0 ? "+" : ""}${stats.trend_delta} trend`;
  } catch {
    // ignore
  }

  const handleSave = async () => {
    setIsSaving(true);
    const ok = await updateSnapshot(snapshot.id, content);
    if (ok) {
      onUpdated(snapshot.id, content);
      setIsEditing(false);
    }
    setIsSaving(false);
  };

  const handleDelete = async () => {
    if (!confirm("Delete this snapshot permanently?")) return;
    const ok = await deleteSnapshot(snapshot.id, topicId);
    if (ok) onDeleted(snapshot.id);
  };

  return (
    <div className="rounded-md border border-border/50 bg-surface/60 overflow-hidden">
      {/* header row */}
      <div className="flex items-center gap-2 px-2 py-1.5">
        <button
          onClick={() => { if (!isEditing) setExpanded((v) => !v); }}
          className="flex-1 text-left"
        >
          <div className="text-[10px] text-muted flex items-center gap-1">
            <Clock3 className="w-3 h-3 shrink-0" />
            {new Date(snapshot.created_at + "Z").toLocaleString()}
          </div>
          {statsStr && (
            <p className="text-[9px] text-muted/70 mt-0.5">{statsStr}</p>
          )}
        </button>
        <div className="flex items-center gap-0.5 shrink-0">
          {isEditing ? (
            <>
              <button
                onClick={handleSave}
                disabled={isSaving}
                className="p-1 rounded text-emerald-500 hover:bg-emerald-500/10 transition-colors"
              >
                <Check className="w-3 h-3" />
              </button>
              <button
                onClick={() => { setContent(snapshot.overview_content); setIsEditing(false); }}
                className="p-1 rounded text-muted hover:bg-surface-hover transition-colors"
              >
                <X className="w-3 h-3" />
              </button>
            </>
          ) : (
            <>
              <button
                onClick={() => { setExpanded(true); setIsEditing(true); }}
                className="p-1 rounded text-muted hover:text-foreground hover:bg-surface-hover transition-colors"
                title="Edit"
              >
                <Edit3 className="w-3 h-3" />
              </button>
              <button
                onClick={handleDelete}
                className="p-1 rounded text-red-500 hover:bg-red-500/10 transition-colors"
                title="Delete"
              >
                <Trash2 className="w-3 h-3" />
              </button>
              <button
                onClick={() => setExpanded((v) => !v)}
                className="p-1 rounded text-muted hover:text-foreground hover:bg-surface-hover transition-colors"
              >
                {expanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
              </button>
            </>
          )}
        </div>
      </div>

      {/* expanded content */}
      {expanded && (
        <div className="border-t border-border/40 px-2 py-2">
          {isEditing ? (
            <textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              className="w-full h-48 p-2 rounded bg-background border border-border text-[11px] resize-y focus:outline-none focus:border-accent"
            />
          ) : (
            <div className="prose prose-sm prose-invert max-w-none text-[11px] text-muted leading-relaxed whitespace-pre-wrap">
              {content}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ArticleRow({
  article,
  onDeleted,
  onUnkept,
}: {
  article: Article;
  onDeleted: (id: string) => void;
  onUnkept: (id: string) => void;
}) {
  const [isEditing, setIsEditing] = useState(false);
  const [title, setTitle] = useState(article.title);
  const [summary, setSummary] = useState(article.summary || "");
  const [tagsStr, setTagsStr] = useState(tagsJsonToComma(article.tags));
  const [isSaving, setIsSaving] = useState(false);

  const handleSave = async () => {
    setIsSaving(true);
    const tags = tagsStr.split(",").map((t) => t.trim()).filter(Boolean);
    const ok = await updateArticle(article.id, title, summary, tags);
    if (ok) setIsEditing(false);
    setIsSaving(false);
  };

  const handleDelete = async () => {
    if (!confirm("Delete this article permanently?")) return;
    const ok = await deleteArticle(article.id);
    if (ok) onDeleted(article.id);
  };

  const handleRemoveKept = async () => {
    const ok = await toggleArticleKept(article.id, false);
    if (ok) onUnkept(article.id);
  };

  return (
    <div className="rounded-md border border-border/50 bg-surface/60 p-2">
      <div className="flex items-start gap-2">
        <div className="flex-1 min-w-0">
          {isEditing ? (
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="w-full px-1.5 py-0.5 mb-1 bg-background border border-border rounded text-[11px] font-semibold focus:outline-none focus:border-accent"
            />
          ) : (
            <p className="text-[11px] font-semibold leading-snug line-clamp-2 mb-0.5">{title}</p>
          )}
          <div className="text-[9px] text-muted flex items-center gap-1.5 flex-wrap">
            <span className="uppercase">{article.source || "web"}</span>
            <span>·</span>
            <span>Score {article.importance}/10</span>
            {article.published_at && (
              <>
                <span>·</span>
                <span>{article.published_at.slice(0, 10)}</span>
              </>
            )}
          </div>
        </div>
        <div className="flex items-center gap-0.5 shrink-0">
          {isEditing ? (
            <>
              <button onClick={handleSave} disabled={isSaving} className="p-1 rounded text-emerald-500 hover:bg-emerald-500/10">
                <Check className="w-3 h-3" />
              </button>
              <button onClick={() => setIsEditing(false)} className="p-1 rounded text-muted hover:bg-surface-hover">
                <X className="w-3 h-3" />
              </button>
            </>
          ) : (
            <>
              {article.url && (
                <a href={article.url} target="_blank" rel="noreferrer" className="p-1 rounded text-muted hover:bg-surface-hover hover:text-accent">
                  <ExternalLink className="w-3 h-3" />
                </a>
              )}
              <button onClick={handleRemoveKept} title="Remove from Knowledge Base" className="p-1 rounded text-accent hover:bg-surface-hover">
                <Bookmark className="w-3 h-3 fill-current" />
              </button>
              <button onClick={() => setIsEditing(true)} className="p-1 rounded text-muted hover:bg-surface-hover hover:text-foreground">
                <Edit3 className="w-3 h-3" />
              </button>
              <button onClick={handleDelete} className="p-1 rounded text-red-500 hover:bg-red-500/10">
                <Trash2 className="w-3 h-3" />
              </button>
            </>
          )}
        </div>
      </div>

      {isEditing && (
        <div className="mt-2 space-y-1.5">
          <textarea
            value={summary}
            onChange={(e) => setSummary(e.target.value)}
            className="w-full h-16 p-1.5 rounded bg-background border border-border text-[10px] resize-y focus:outline-none focus:border-accent"
            placeholder="Summary…"
          />
          <input
            value={tagsStr}
            onChange={(e) => setTagsStr(e.target.value)}
            className="w-full px-1.5 py-0.5 bg-background border border-border rounded text-[10px] focus:outline-none focus:border-accent"
            placeholder="Tags (comma separated)…"
          />
        </div>
      )}

      {!isEditing && summary && (
        <p className="text-[10px] text-muted mt-1 line-clamp-2 leading-relaxed">{summary}</p>
      )}
      {!isEditing && parseTagsArray(article.tags).length > 0 && (
        <div className="flex flex-wrap gap-1 mt-1">
          {parseTagsArray(article.tags).slice(0, 4).map((tag) => (
            <span key={tag} className="px-1 py-0.5 rounded text-[9px] bg-surface-hover text-muted">
              {tag}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
