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
} from "lucide-react";
import type { TopicOverview } from "@/lib/api";
import { updateTopic, deleteTopic } from "@/lib/api";
import Link from "next/link";
import { TOPIC_COLORS } from "@/lib/constants";

const COLORS = TOPIC_COLORS;

interface TopicCardProps {
  topic: TopicOverview;
  onUpdated: (id: number, patch: { name?: string; color?: string }) => void;
  onDeleted: (id: number) => void;
}

export default function TopicCard({ topic, onUpdated, onDeleted }: TopicCardProps) {
  const total = topic.article_count;
  const sentTotal = Object.values(topic.sentiment).reduce((a, b) => a + b, 0) || 1;
  const posPct = ((topic.sentiment.positive ?? 0) / sentTotal) * 100;
  const neuPct = ((topic.sentiment.neutral ?? 0) / sentTotal) * 100;
  const negPct = ((topic.sentiment.negative ?? 0) / sentTotal) * 100;

  const [editing, setEditing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [editName, setEditName] = useState(topic.name);
  const [editColor, setEditColor] = useState(topic.color);
  const [saving, setSaving] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editing) inputRef.current?.focus();
  }, [editing]);

  function startEdit(e: React.MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    setEditName(topic.name);
    setEditColor(topic.color);
    setEditing(true);
    setConfirming(false);
  }

  async function saveEdit(e: React.MouseEvent | React.FormEvent) {
    e.preventDefault();
    e.stopPropagation();
    const name = editName.trim();
    if (!name) return;
    setSaving(true);
    await updateTopic(topic.id, { name, color: editColor });
    onUpdated(topic.id, { name, color: editColor });
    setSaving(false);
    setEditing(false);
  }

  function cancelEdit(e: React.MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    setEditing(false);
  }

  function startDelete(e: React.MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    setConfirming(true);
    setEditing(false);
  }

  async function confirmDelete(e: React.MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    await deleteTopic(topic.id);
    onDeleted(topic.id);
  }

  function cancelDelete(e: React.MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    setConfirming(false);
  }

  return (
    <Link href={editing || confirming ? "#" : `/topic/${topic.id}`} onClick={editing || confirming ? (e) => e.preventDefault() : undefined}>
      <motion.div
        whileHover={{ scale: editing || confirming ? 1 : 1.02, y: editing || confirming ? 0 : -2 }}
        whileTap={{ scale: editing || confirming ? 1 : 0.98 }}
        className="group relative p-5 rounded-2xl border border-border bg-surface hover:border-accent/40 transition-colors cursor-pointer h-full flex flex-col"
      >
        {/* Delete confirmation overlay */}
        <AnimatePresence>
          {confirming && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="absolute inset-0 rounded-2xl bg-surface/95 backdrop-blur-sm z-10 flex flex-col items-center justify-center gap-3 p-4"
            >
              <Trash2 className="w-8 h-8 text-negative/70" />
              <p className="text-sm font-medium text-center">Delete <span className="text-foreground">{topic.name}</span>?</p>
              <p className="text-xs text-muted text-center">All articles and data for this topic will be removed.</p>
              <div className="flex gap-2 mt-1">
                <button
                  onClick={confirmDelete}
                  className="px-4 py-1.5 rounded-lg text-xs font-medium bg-negative text-white hover:bg-negative/80 transition-colors"
                >
                  Delete
                </button>
                <button
                  onClick={cancelDelete}
                  className="px-4 py-1.5 rounded-lg text-xs font-medium border border-border text-muted hover:text-foreground hover:bg-surface-hover transition-colors"
                >
                  Cancel
                </button>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Header: color dot + name / edit form */}
        <div className="flex items-start gap-2.5 mb-3">
          {editing ? (
            <form onSubmit={saveEdit} className="flex-1 flex flex-col gap-2" onClick={(e) => e.stopPropagation()}>
              {/* Color picker */}
              <div className="flex gap-1.5 flex-wrap">
                {COLORS.map((c) => (
                  <button
                    key={c}
                    type="button"
                    onClick={(e) => { e.stopPropagation(); setEditColor(c); }}
                    className={`w-4 h-4 rounded-full transition-transform ${
                      editColor === c ? "scale-125 ring-2 ring-white/70" : "opacity-50 hover:opacity-100"
                    }`}
                    style={{ backgroundColor: c }}
                  />
                ))}
              </div>
              {/* Name input */}
              <div className="flex gap-1.5">
                <input
                  ref={inputRef}
                  value={editName}
                  onChange={(e) => setEditName(e.target.value)}
                  className="flex-1 px-2 py-1 rounded-lg text-sm bg-background border border-accent outline-none"
                  onClick={(e) => e.stopPropagation()}
                />
                <button
                  type="submit"
                  disabled={saving || !editName.trim()}
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
            </form>
          ) : (
            <>
              <span
                className="w-3 h-3 rounded-full shrink-0 mt-0.5"
                style={{ backgroundColor: topic.color }}
              />
              <h2 className="text-base font-semibold truncate flex-1">{topic.name}</h2>
              {/* Action buttons — visible on hover */}
              <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity ml-auto shrink-0">
                <button
                  onClick={startEdit}
                  className="p-1 rounded-md text-muted hover:text-foreground hover:bg-surface-hover transition-colors"
                  title="Rename / change color"
                >
                  <Pencil className="w-3.5 h-3.5" />
                </button>
                <button
                  onClick={startDelete}
                  className="p-1 rounded-md text-muted hover:text-negative hover:bg-negative/10 transition-colors"
                  title="Delete topic"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
                <ArrowRight className="w-4 h-4 text-muted ml-0.5" />
              </div>
            </>
          )}
        </div>

        {/* Keywords */}
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

        {/* Top headline */}
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

        {/* Stats row */}
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
                  topic.trend_delta > 0 ? "text-positive" : topic.trend_delta < 0 ? "text-negative" : "text-muted"
                }`}
              >
                {topic.trend_delta > 0 ? "+" : ""}{topic.trend_delta}
              </span>
            </div>
          </div>
        )}

        {/* Sentiment bar */}
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
