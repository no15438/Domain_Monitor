"use client";

import { useState, useRef, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  TrendingUp,
  TrendingDown,
  Minus,
  Newspaper,
  AlertTriangle,
  ArrowRight,
  Pencil,
  Trash2,
  Check,
  X,
  Archive,
  ArchiveRestore,
  GripVertical,
} from "lucide-react";
import type { DraggableAttributes, DraggableSyntheticListeners } from "@dnd-kit/core";
import type { TopicOverview } from "@/lib/api";
import {
  updateTopic,
  deleteTopic,
  archiveTopic,
  unarchiveTopic,
} from "@/lib/api";
import Link from "next/link";
import { TOPIC_COLORS } from "@/lib/constants";
import { useStore } from "@/stores/useStore";

const COLORS = TOPIC_COLORS;

type Overlay =
  | null
  | "save"
  | "archive"
  | "delete"
  | "restore";

interface TopicCardProps {
  topic: TopicOverview;
  variant?: "active" | "archived";
  onUpdated: (id: number, patch: { name?: string; color?: string }) => void;
  onDeleted: (id: number) => void;
  onArchived?: (id: number) => void;
  onRestored?: (id: number) => void;
  // Drag-and-drop props (optional — only set when sortable is enabled)
  dragHandleListeners?: DraggableSyntheticListeners;
  dragHandleAttributes?: DraggableAttributes;
  isDragging?: boolean;
}

export default function TopicCard({
  topic,
  variant = "active",
  onUpdated,
  onDeleted,
  onArchived,
  onRestored,
  dragHandleListeners,
  dragHandleAttributes,
  isDragging = false,
}: TopicCardProps) {
  const addToast = useStore((s) => s.addToast);
  const total = topic.article_count;
  const sentTotal = Object.values(topic.sentiment).reduce((a, b) => a + b, 0) || 1;
  const posPct = ((topic.sentiment.positive ?? 0) / sentTotal) * 100;
  const neuPct = ((topic.sentiment.neutral ?? 0) / sentTotal) * 100;
  const negPct = ((topic.sentiment.negative ?? 0) / sentTotal) * 100;

  const [editing, setEditing] = useState(false);
  const [overlay, setOverlay] = useState<Overlay>(null);
  const [editName, setEditName] = useState(topic.name);
  const [editColor, setEditColor] = useState(topic.color);
  const [saving, setSaving] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editing) inputRef.current?.focus();
  }, [editing]);

  const blockNav = editing || overlay !== null;

  function startEdit(e: React.MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    setEditName(topic.name);
    setEditColor(topic.color);
    setEditing(true);
    setOverlay(null);
  }

  function requestSaveConfirm(e?: React.MouseEvent) {
    e?.preventDefault();
    e?.stopPropagation();
    const name = editName.trim();
    if (!name) return;
    setOverlay("save");
  }

  async function doSaveEdit() {
    const name = editName.trim();
    if (!name) return;
    setSaving(true);
    const r = await updateTopic(topic.id, { name, color: editColor });
    setSaving(false);
    if (r.status === "error") {
      addToast("Could not save changes — please try again", "error");
      setOverlay(null);
      return;
    }
    onUpdated(topic.id, { name, color: editColor });
    setEditing(false);
    setOverlay(null);
  }

  function cancelEdit(e: React.MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    setEditing(false);
    setOverlay(null);
  }

  async function doArchive(e: React.MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    const r = await archiveTopic(topic.id);
    if (r.status === "error") {
      addToast("Could not archive topic — please try again", "error");
      return;
    }
    onArchived?.(topic.id);
    setOverlay(null);
  }

  async function doRestore(e: React.MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    const r = await unarchiveTopic(topic.id);
    if (r.status === "error") {
      addToast("Could not restore topic — please try again", "error");
      return;
    }
    onRestored?.(topic.id);
    setOverlay(null);
  }

  async function doDelete(e: React.MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    const r = await deleteTopic(topic.id);
    if (r.status === "error") {
      addToast("Could not delete topic — please try again", "error");
      return;
    }
    onDeleted(topic.id);
    setOverlay(null);
  }

  function cancelOverlay(e: React.MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    setOverlay(null);
  }

  return (
    <Link
      href={blockNav ? "#" : `/topic/${topic.id}`}
      onClick={blockNav ? (e) => e.preventDefault() : undefined}
    >
      <motion.div
        whileHover={{ scale: blockNav || isDragging ? 1 : 1.02, y: blockNav || isDragging ? 0 : -2 }}
        whileTap={{ scale: blockNav || isDragging ? 1 : 0.98 }}
        className={`group relative p-5 rounded-xl border bg-surface shadow-sm hover:shadow hover:border-accent/40 transition-all cursor-pointer h-full flex flex-col ${
          isDragging ? "border-accent/60 shadow-lg" : "border-border"
        }`}
      >
        <AnimatePresence>
          {overlay === "save" && (
            <motion.div
              key="save"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="absolute inset-0 rounded-xl bg-surface/95 backdrop-blur-sm z-10 flex flex-col items-center justify-center gap-3 p-4"
            >
              <Pencil className="w-8 h-8 text-accent/80" />
              <p className="text-sm font-medium text-center">
                Save changes to <span className="text-foreground">{topic.name}</span>?
              </p>
              <p className="text-xs text-muted text-center">
                Name will become “{editName.trim()}” and the color you selected will apply.
              </p>
              <div className="flex gap-2 mt-1">
                <button
                  type="button"
                  disabled={saving}
                  onClick={() => void doSaveEdit()}
                  className="px-4 py-1.5 rounded-lg text-xs font-medium bg-accent text-white hover:bg-accent-hover transition-colors disabled:opacity-50"
                >
                  {saving ? "Saving…" : "Save"}
                </button>
                <button
                  type="button"
                  onClick={cancelOverlay}
                  className="px-4 py-1.5 rounded-lg text-xs font-medium border border-border text-muted hover:text-foreground hover:bg-surface-hover transition-colors"
                >
                  Cancel
                </button>
              </div>
            </motion.div>
          )}
          {overlay === "archive" && (
            <motion.div
              key="archive"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="absolute inset-0 rounded-xl bg-surface/95 backdrop-blur-sm z-10 flex flex-col items-center justify-center gap-3 p-4"
            >
              <Archive className="w-8 h-8 text-muted" />
              <p className="text-sm font-medium text-center">
                Archive <span className="text-foreground">{topic.name}</span>?
              </p>
              <p className="text-xs text-muted text-center">
                It will disappear from your main list. Data stays in the database until you restore or delete it permanently.
              </p>
              <div className="flex gap-2 mt-1">
                <button
                  type="button"
                  onClick={doArchive}
                  className="px-4 py-1.5 rounded-lg text-xs font-medium bg-muted text-foreground hover:bg-muted/80 transition-colors"
                >
                  Archive
                </button>
                <button
                  type="button"
                  onClick={cancelOverlay}
                  className="px-4 py-1.5 rounded-lg text-xs font-medium border border-border text-muted hover:text-foreground hover:bg-surface-hover transition-colors"
                >
                  Cancel
                </button>
              </div>
            </motion.div>
          )}
          {overlay === "restore" && (
            <motion.div
              key="restore"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="absolute inset-0 rounded-xl bg-surface/95 backdrop-blur-sm z-10 flex flex-col items-center justify-center gap-3 p-4"
            >
              <ArchiveRestore className="w-8 h-8 text-accent/80" />
              <p className="text-sm font-medium text-center">
                Restore <span className="text-foreground">{topic.name}</span> to the main list?
              </p>
              <div className="flex gap-2 mt-1">
                <button
                  type="button"
                  onClick={doRestore}
                  className="px-4 py-1.5 rounded-lg text-xs font-medium bg-accent text-white hover:bg-accent-hover transition-colors"
                >
                  Restore
                </button>
                <button
                  type="button"
                  onClick={cancelOverlay}
                  className="px-4 py-1.5 rounded-lg text-xs font-medium border border-border text-muted hover:text-foreground hover:bg-surface-hover transition-colors"
                >
                  Cancel
                </button>
              </div>
            </motion.div>
          )}
          {overlay === "delete" && (
            <motion.div
              key="delete"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="absolute inset-0 rounded-xl bg-surface/95 backdrop-blur-sm z-10 flex flex-col items-center justify-center gap-3 p-4"
            >
              <Trash2 className="w-8 h-8 text-negative/70" />
              <p className="text-sm font-medium text-center">
                Permanently delete <span className="text-foreground">{topic.name}</span>?
              </p>
              <p className="text-xs text-muted text-center">
                This removes the topic and all related articles, events, and knowledge data. This cannot be undone.
              </p>
              <div className="flex gap-2 mt-1">
                <button
                  type="button"
                  onClick={doDelete}
                  className="px-4 py-1.5 rounded-lg text-xs font-medium bg-negative text-white hover:bg-negative/80 transition-colors"
                >
                  Delete permanently
                </button>
                <button
                  type="button"
                  onClick={cancelOverlay}
                  className="px-4 py-1.5 rounded-lg text-xs font-medium border border-border text-muted hover:text-foreground hover:bg-surface-hover transition-colors"
                >
                  Cancel
                </button>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        <div className="flex items-start gap-2.5 mb-3">
          {editing ? (
            <div
              className="flex-1 flex flex-col gap-2"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex gap-1.5 flex-wrap">
                {COLORS.map((c) => (
                  <button
                    key={c}
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      setEditColor(c);
                    }}
                    className={`w-4 h-4 rounded-full transition-transform ${
                      editColor === c ? "scale-125 ring-2 ring-white/70" : "opacity-50 hover:opacity-100"
                    }`}
                    style={{ backgroundColor: c }}
                  />
                ))}
              </div>
              <div className="flex gap-1.5">
                <input
                  ref={inputRef}
                  value={editName}
                  onChange={(e) => setEditName(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      requestSaveConfirm();
                    }
                  }}
                  className="flex-1 px-2 py-1 rounded-lg text-sm bg-background border border-accent outline-none"
                  onClick={(e) => e.stopPropagation()}
                />
                <button
                  type="button"
                  disabled={saving || !editName.trim()}
                  onClick={requestSaveConfirm}
                  className="p-1.5 rounded-lg bg-accent/20 text-accent hover:bg-accent/30 disabled:opacity-40 transition-colors"
                >
                  <Check className="w-3.5 h-3.5" />
                </button>
                <button
                  type="button"
                  onClick={cancelEdit}
                  className="p-1.5 rounded-lg text-muted hover:text-foreground hover:bg-surface-hover transition-colors"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>
          ) : (
            <>
              <span
                className="w-3 h-3 rounded-full shrink-0 mt-0.5"
                style={{ backgroundColor: topic.color }}
              />
              <h2 className="text-base font-semibold truncate flex-1">{topic.name}</h2>
              <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity ml-auto shrink-0">
                {dragHandleListeners && (
                  <button
                    type="button"
                    {...dragHandleListeners}
                    {...dragHandleAttributes}
                    onClick={(e) => { e.preventDefault(); e.stopPropagation(); }}
                    className="p-1 rounded-md text-muted hover:text-foreground hover:bg-surface-hover transition-colors cursor-grab active:cursor-grabbing"
                    title="Drag to reorder"
                  >
                    <GripVertical className="w-3.5 h-3.5" />
                  </button>
                )}
                <button
                  onClick={startEdit}
                  className="p-1 rounded-md text-muted hover:text-foreground hover:bg-surface-hover transition-colors"
                  title="Rename / change color"
                >
                  <Pencil className="w-3.5 h-3.5" />
                </button>
                {variant === "active" ? (
                  <button
                    onClick={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      setOverlay("archive");
                      setEditing(false);
                    }}
                    className="p-1 rounded-md text-muted hover:text-foreground hover:bg-surface-hover transition-colors"
                    title="Archive topic"
                  >
                    <Archive className="w-3.5 h-3.5" />
                  </button>
                ) : (
                  <button
                    onClick={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      setOverlay("restore");
                      setEditing(false);
                    }}
                    className="p-1 rounded-md text-muted hover:text-accent hover:bg-accent/10 transition-colors"
                    title="Restore to main list"
                  >
                    <ArchiveRestore className="w-3.5 h-3.5" />
                  </button>
                )}
                <button
                  onClick={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    setOverlay("delete");
                    setEditing(false);
                  }}
                  className="p-1 rounded-md text-muted hover:text-negative hover:bg-negative/10 transition-colors"
                  title="Delete permanently"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
                <ArrowRight className="w-4 h-4 text-muted ml-0.5" />
              </div>
            </>
          )}
        </div>

        {!editing && variant === "archived" && (
          <p className="text-[10px] text-muted uppercase tracking-wide mb-2">Archived</p>
        )}

        {!editing && topic.keywords.length > 0 && (
          <div className="flex flex-wrap gap-1 mb-3">
            {topic.keywords.slice(0, 4).map((kw) => (
              <span
                key={kw}
                className="px-2 py-0.5 rounded-full text-[10px] bg-surface-hover text-muted"
              >
                {kw}
              </span>
            ))}
            {topic.keywords.length > 4 && (
              <span className="px-2 py-0.5 rounded-full text-[10px] bg-surface-hover text-muted">
                +{topic.keywords.length - 4}
              </span>
            )}
          </div>
        )}

        {!editing && topic.top_headline && (
          <p className="text-xs text-muted leading-relaxed line-clamp-2 mb-3 flex-1">
            {topic.top_headline}
          </p>
        )}
        {!editing && !topic.top_headline && (
          <p className="text-xs text-muted/50 italic mb-3 flex-1">
            No articles yet. Click to set up keywords and fetch.
          </p>
        )}

        {!editing && (
          <div className="flex items-center gap-3 mb-3">
            <div className="flex items-center gap-1">
              <Newspaper className="w-3 h-3 text-muted" />
              <span className="text-xs font-medium">{total}</span>
              <span className="text-[10px] text-muted">articles</span>
            </div>
            {topic.important_count > 0 && (
              <div className="flex items-center gap-1">
                <AlertTriangle className="w-3 h-3 text-important" />
                <span className="text-xs font-medium text-important">{topic.important_count}</span>
              </div>
            )}
            <div className="flex items-center gap-1 ml-auto">
              {topic.trend_delta > 0 ? (
                <TrendingUp className="w-3 h-3 text-positive" />
              ) : topic.trend_delta < 0 ? (
                <TrendingDown className="w-3 h-3 text-negative" />
              ) : (
                <Minus className="w-3 h-3 text-muted" />
              )}
              <span
                className={`text-[10px] font-medium ${
                  topic.trend_delta > 0
                    ? "text-positive"
                    : topic.trend_delta < 0
                      ? "text-negative"
                      : "text-muted"
                }`}
              >
                {topic.trend_delta > 0 ? "+" : ""}
                {topic.trend_delta}
              </span>
            </div>
          </div>
        )}

        {!editing && sentTotal > 0 && total > 0 && (
          <div className="flex h-1.5 rounded-full overflow-hidden bg-surface-hover">
            <div className="bg-positive" style={{ width: `${posPct}%` }} />
            <div className="bg-muted/40" style={{ width: `${neuPct}%` }} />
            <div className="bg-negative" style={{ width: `${negPct}%` }} />
          </div>
        )}
      </motion.div>
    </Link>
  );
}
