"use client";

import { useRef, useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Send, Trash2, X, Bot, User, Search, Globe, Sparkles } from "lucide-react";
import Markdown from "react-markdown";
import { useStore } from "@/stores/useStore";
import { streamChat } from "@/lib/api";

export default function ChatBot() {
  const {
    chatMessages,
    addChatMessage,
    appendToLastAssistant,
    clearChat,
    selectedArticle,
    setSelectedArticle,
    isChatLoading,
    setChatLoading,
    chatOpen,
    setChatOpen,
    activeTopicId,
  } = useStore();

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
  }, [chatMessages]);

  useEffect(() => {
    if (selectedArticle) {
      inputRef.current?.focus();
    }
  }, [selectedArticle]);

  async function handleSend() {
    const msg = input.trim();
    if (!msg || isChatLoading) return;

    const ctx = selectedArticle
      ? `Title: ${selectedArticle.title}\nSummary: ${selectedArticle.summary}\nContent: ${selectedArticle.content?.slice(0, 1000)}`
      : undefined;

    addChatMessage({ id: crypto.randomUUID(), role: "user", content: msg });
    setInput("");
    // Reset textarea height after clearing input
    if (inputRef.current) inputRef.current.style.height = "auto";
    setChatLoading(true);

    addChatMessage({ id: crypto.randomUUID(), role: "assistant", content: "" });

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    try {
      for await (const event of streamChat(msg, ctx, activeTopicId, controller.signal)) {
        if (controller.signal.aborted) break;
        if (event.type === "status") {
          setChatStatus(event.value);
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
    }
  }

  if (!chatOpen) return null;

  return (
    <div
      className="flex-4 min-w-[320px] flex flex-col border-l border-border bg-surface/95 overflow-hidden"
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

      {/* Article context banner */}
      <AnimatePresence>
        {selectedArticle && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="px-4 py-2 bg-accent/10 border-b border-accent/20 overflow-hidden"
          >
            <div className="flex items-start justify-between gap-2">
              <p className="text-[11px] text-accent-hover line-clamp-2">
                Context: {selectedArticle.title}
              </p>
              <button
                onClick={() => setSelectedArticle(null)}
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
            <p className="text-xs">
              Ask me anything about your monitored industries.
            </p>
            <p className="text-[10px] opacity-60">
              I can search local knowledge and the web.
            </p>
          </div>
        )}
        {chatMessages.map((msg) => {
          // Skip empty assistant bubbles while chatStatus is showing (avoid double indicator)
          if (msg.role === "assistant" && !msg.content && chatStatus) return null;
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
              <div
                className={`max-w-[85%] rounded-xl px-3 py-2 text-sm leading-relaxed ${
                  msg.role === "user"
                    ? "bg-accent text-white rounded-br-sm"
                    : "bg-surface-hover rounded-bl-sm"
                }`}
              >
                {msg.role === "assistant" ? (
                  <div className="chat-markdown">
                    <Markdown>{msg.content}</Markdown>
                  </div>
                ) : (
                  msg.content
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
        {/* Search status indicator */}
        {chatStatus && (
          <motion.div
            initial={{ opacity: 0, y: 5 }}
            animate={{ opacity: 1, y: 0 }}
            className="flex items-center gap-2 px-3 py-2 rounded-lg bg-surface text-xs text-muted"
          >
            {chatStatus === "searching_knowledge_base" && (
              <>
                <Search className="w-3.5 h-3.5 text-accent animate-pulse" />
                Searching knowledge base…
              </>
            )}
            {chatStatus === "searching_web" && (
              <>
                <Globe className="w-3.5 h-3.5 text-positive animate-spin" />
                Searching the web…
              </>
            )}
            {chatStatus === "generating" && (
              <>
                <Sparkles className="w-3.5 h-3.5 text-important animate-pulse" />
                Generating response…
              </>
            )}
          </motion.div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="p-3 border-t border-border">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleSend();
          }}
          className="flex items-end gap-2"
        >
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => {
              setInput(e.target.value);
              // Auto-expand height to fit content (max ~5 lines)
              e.target.style.height = "auto";
              e.target.style.height = `${Math.min(e.target.scrollHeight, 120)}px`;
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void handleSend();
              }
            }}
            placeholder={
              selectedArticle
                ? "Ask about this article…"
                : "Ask about industry trends…"
            }
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
