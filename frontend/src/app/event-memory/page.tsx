"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type FormEvent } from "react";
import ThemeToggle from "@/components/ThemeToggle";
import { eventRequest, queryParams, safeEvidenceUrl, type EventResult, type HistoryResult, type JsonValue, type QueryResult, type QueryScope } from "@/lib/api/eventMemory";

const box = "rounded-xl border border-border bg-surface p-5";
const input = "w-full rounded-lg border border-border bg-background px-3 py-2 text-sm";
const button = "rounded-lg border border-border px-3 py-2 text-sm hover:bg-surface-hover disabled:opacity-40";
const names: Record<string, string> = { status: "Status", participants: "Participants", amount: "Amount", location: "Location", headline: "Headline" };
const values: Record<string, string> = { announced: "Announced", completed: "Completed", approved: "Approved", denied: "Denied", active: "Active", summary: "Summary", archived: "Archived", observation: "Observation", transition: "Transition", correction: "Correction" };
function valueText(value: JsonValue): string {
  if (typeof value === "string") return values[value] || value;
  if (Array.isArray(value)) return value.map(valueText).join("; ");
  if (value && typeof value === "object") {
    if (typeof value.name === "string") {
      const roles: Record<string, string> = { buyer: "Buyer", target: "Target", seller: "Seller" };
      return `${value.name}${typeof value.role === "string" ? ` (${roles[value.role] || value.role})` : ""}`;
    }
    if (typeof value.value === "number" && typeof value.currency === "string") {
      return `${value.value.toLocaleString("en-AU")}${value.unit === "million" ? " million" : typeof value.unit === "string" ? ` ${value.unit}` : ""} ${value.currency}`;
    }
  }
  return JSON.stringify(value);
}
function dateText(value: string) {
  return new Date(value).toLocaleString("en-AU", { timeZone: "Australia/Sydney", hour12: false });
}

function EventDetail({ item, result, onSaved }: { item: EventResult; result: QueryResult; onSaved: () => void }) {
  const [history, setHistory] = useState<HistoryResult | null>(null);
  const [historyError, setHistoryError] = useState("");
  const [importance, setImportance] = useState(item.memory.importance);
  const [mode, setMode] = useState(item.memory.mode);
  const [pinned, setPinned] = useState(Boolean(item.memory.pinned));
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const savingRef = useRef(false);
  const activeRef = useRef(true);
  const historical = result.scope.mode === "historical";

  useEffect(() => {
    activeRef.current = true;
    const controller = new AbortController();
    const params = new URLSearchParams({ topic: result.scope.topic, known_at: result.scope.known_at });
    eventRequest<HistoryResult>(`/events/${encodeURIComponent(item.event.id)}/history?${params}`, { signal: controller.signal })
      .then(data => { if (!controller.signal.aborted) setHistory(data); })
      .catch(() => { if (!controller.signal.aborted) setHistoryError("Unable to load history. Select the event again to retry."); });
    return () => { activeRef.current = false; controller.abort(); };
  }, [item.event.id, result.scope.topic, result.scope.known_at]);

  async function save(event: FormEvent) {
    event.preventDefault();
    if (historical || savingRef.current || !reason.trim()) return;
    savingRef.current = true;
    setSaving(true); setSaveError("");
    try {
      await eventRequest(`/events/${encodeURIComponent(item.event.id)}/memory`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ topic: result.scope.topic, importance, mode, pinned, reason: reason.trim() }),
      });
      if (activeRef.current) onSaved();
    } catch (error) { if (activeRef.current) setSaveError(error instanceof Error ? error.message : "Unable to save. Please retry."); }
    finally { savingRef.current = false; if (activeRef.current) setSaving(false); }
  }

  return <article className={`${box} min-w-0 space-y-6`}>
    <div><p className="text-xs text-muted">Event details · {item.event.id}</p><h2 className="mt-1 text-xl font-semibold">{item.event.title}</h2></div>
    {Object.keys(item.fields).length === 0 && <p className="text-muted">No known fields are effective in this time range.</p>}
    <dl className="space-y-4">
      {Object.entries(item.fields).map(([name, field]) => <div key={name} className="border-b border-border pb-4 last:border-0">
        <dt className="text-sm text-muted">{names[name] || name}</dt>
        <dd className="mt-1 break-words text-sm">
          {field.status === "conflict" ? <div className="rounded-lg border border-important/40 bg-important/5 p-3">
            <strong className="text-important">Unresolved source conflict</strong>
            <ul className="mt-2 space-y-2">{field.alternatives.map(alt => <li key={alt.id}>
              {valueText(alt.value)} <span className="text-xs text-muted">· Evidence {item.citations.find(c => c.id === alt.evidence_id)?.source_key || alt.evidence_id}</span>
            </li>)}</ul>
          </div> : <div><p>{valueText(field.value)}</p><p className="mt-1 text-xs text-muted">Recorded values agree · {field.evidence_ids.length} evidence records (not externally verified)</p></div>}
        </dd>
      </div>)}
    </dl>
    <section><h3 className="font-semibold">Evidence for this state</h3>
      <ul className="mt-3 space-y-3">{item.citations.map(c => <li key={c.id} className="rounded-lg bg-background p-3 text-sm">
        {safeEvidenceUrl(c.url) ? <a className="text-accent underline" href={safeEvidenceUrl(c.url)} target="_blank" rel="noreferrer">{c.publisher} · {c.source_key} · revision {c.revision}</a> : <span>{c.publisher} · revision {c.revision}</span>}
        <p className="mt-1 text-xs text-muted">Published: {dateText(c.published_at)} · Known: {dateText(c.recorded_at)}</p>
      </li>)}</ul>
    </section>
    <details className="border-t border-border pt-4"><summary className="cursor-pointer font-semibold">History and original evidence</summary>
      <p className="my-3 text-xs text-muted">History known by the selected cutoff is shown for traceability. Earlier states do not describe the current state.</p>
      {historyError && <p role="alert">{historyError}</p>}
      {!history && !historyError && <p role="status">Loading…</p>}
      <ol className="space-y-3">{history?.assertions.map(a => <li key={a.id} className="border-l-2 border-accent/40 pl-3 text-sm">
        <p className="text-xs text-muted">Effective {dateText(a.valid_from)}{a.valid_to && ` to ${dateText(a.valid_to)}`} · Known {dateText(a.recorded_at)}</p>
        <p className="mt-1">{values[a.relation] || a.relation} · {names[a.field] || a.field}: {valueText(a.value)}</p>
        {a.reason && <p className="text-xs text-muted">{a.reason}</p>}
        <p className="text-xs text-muted">Evidence: {history.evidence.find(e => e.id === a.evidence_id)?.source_key} · assertion {a.id}</p>
      </li>)}</ol>
      {history?.evidence.map(e => <details key={e.id} className="mt-3 rounded-lg bg-background p-3 text-sm">
        <summary className="cursor-pointer">{e.source_key} · revision {e.revision} original text</summary><p className="mt-2 whitespace-pre-wrap break-words">{e.body}</p>
      </details>)}
      {history && <div className="mt-5"><h4 className="text-sm font-medium">Memory policy history</h4>{history.memory_history.map((p, i) => <p key={i} className="mt-2 text-xs text-muted">{dateText(p.recorded_at)} · {values[p.mode]} · Importance {p.importance} · {p.reason}</p>)}</div>}
    </details>
    <form onSubmit={save} className="border-t border-border pt-4">
      <h3 className="font-semibold">Memory policy</h3><p className="mt-1 text-xs text-muted">Adjust attention and display tier. History and evidence are always preserved.</p>
      {historical && <p className="mt-2 text-sm text-important">Historical view is read-only. Return to the current view to adjust the policy.</p>}
      <fieldset disabled={historical || saving} className="mt-3 space-y-3 disabled:opacity-60">
        <label className="block text-sm">Importance {Math.round(importance * 100)}%<input aria-label="Importance" className="mt-2 w-full" type="range" min="0" max="1" step="0.05" value={importance} onChange={e => setImportance(Number(e.target.value))} /></label>
        <label className="block text-sm">Tier<select className={`${input} mt-1`} value={mode} onChange={e => setMode(e.target.value as typeof mode)}>{["active", "summary", "archived"].map(m => <option key={m} value={m}>{values[m]}</option>)}</select></label>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={pinned} onChange={e => setPinned(e.target.checked)} />Pinned</label>
        <label className="block text-sm">Reason<input className={`${input} mt-1`} required maxLength={2000} value={reason} onChange={e => setReason(e.target.value)} placeholder="Explain why to retain, downweight, or archive" /></label>
        <button className={button} disabled={!reason.trim() || saving}>{saving ? "Saving…" : "Save memory policy"}</button>
      </fieldset>
      {saveError && <p role="alert" className="mt-2 text-negative">{saveError}</p>}
    </form>
  </article>;
}

export default function EventMemoryPage() {
  const [topics, setTopics] = useState<string[]>([]);
  const [topic, setTopic] = useState("");
  const [query, setQuery] = useState("");
  const [valid, setValid] = useState("");
  const [known, setKnown] = useState("");
  const [archived, setArchived] = useState(false);
  const [scope, setScope] = useState<QueryScope | null>(null);
  const [response, setResponse] = useState<QueryResult | null>(null);
  const [loadedScope, setLoadedScope] = useState<QueryScope | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    eventRequest<{ topics: string[] }>("/topics", { signal: controller.signal }).then(data => {
      if (controller.signal.aborted) return;
      setTopics(data.topics);
      if (data.topics.length) {
        setTopic(data.topics[0]); setScope({ topic: data.topics[0], q: "", valid_at: "", known_at: "", include_archived: false });
      } else setLoading(false);
    }).catch(() => { if (!controller.signal.aborted) { setError("The event service is unavailable. Please retry."); setLoading(false); } });
    return () => controller.abort();
  }, [refresh]);

  useEffect(() => {
    if (!scope) return;
    const controller = new AbortController();
    setLoading(true); setError(""); setResponse(null); setSelected(null);
    eventRequest<QueryResult>(`/query?${queryParams(scope)}`, { signal: controller.signal }).then(data => {
      if (controller.signal.aborted) return;
      setResponse(data); setLoadedScope(scope); setSelected(data.results[0]?.event.id || null);
    }).catch(() => { if (!controller.signal.aborted) setError("Unable to load events for this time. Check the dates or retry."); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [scope]);

  function apply(event: FormEvent) {
    event.preventDefault(); setNotice("");
    setScope({ topic, q: query.trim(), valid_at: valid ? new Date(valid).toISOString() : "", known_at: known ? new Date(known).toISOString() : "", include_archived: archived });
  }
  function current() {
    setValid(""); setKnown(""); setNotice("");
    setScope({ topic, q: query.trim(), valid_at: "", known_at: "", include_archived: archived });
  }
  const result = loadedScope === scope ? response : null;
  const item = result?.results.find(e => e.event.id === selected);
  return <div className="min-h-full">
    <header className="flex flex-wrap items-center gap-4 border-b border-border bg-surface px-6 py-4">
      <Link href="/" prefetch={false} className="text-sm text-accent">← Domain Monitor</Link><div className="flex-1" /><ThemeToggle />
    </header>
    <main className="mx-auto max-w-7xl space-y-5 p-5 md:p-8">
      <div><p className="text-xs uppercase tracking-widest text-accent">Domain Monitor · Event Memory</p><h1 className="mt-2 text-2xl font-semibold">Event Memory</h1><p className="mt-2 text-sm text-muted">Track changes to an event and reconstruct its facts and evidence over time.</p></div>
      <form onSubmit={apply} className={`${box} space-y-4`}>
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          <label className="text-sm">Topic<select className={`${input} mt-1`} value={topic} onChange={e => { const next = e.target.value; setTopic(next); setQuery(""); setValid(""); setKnown(""); setArchived(false); setNotice(""); setScope({ topic: next, q: "", valid_at: "", known_at: "", include_archived: false }); }}><option value="" disabled>Select topic</option>{topics.map(t => <option key={t}>{t}</option>)}</select></label>
          <label className="text-sm">Search<input className={`${input} mt-1`} value={query} onChange={e => setQuery(e.target.value)} placeholder="Event name or confirmed field value" /></label>
          <label className="text-sm">Effective at (local time)<input className={`${input} mt-1`} type="datetime-local" value={valid} onInput={e => setValid(e.currentTarget.value)} onChange={e => setValid(e.target.value)} /></label>
          <label className="text-sm">Known by (local time)<input className={`${input} mt-1`} type="datetime-local" value={known} onInput={e => setKnown(e.currentTarget.value)} onChange={e => setKnown(e.target.value)} /></label>
        </div>
        <div className="flex flex-wrap items-center gap-3"><label className="mr-auto flex items-center gap-2 text-sm"><input type="checkbox" checked={archived} onChange={e => setArchived(e.target.checked)} />Include archived events</label><button className={button} disabled={!topic}>Search</button><button className={button} type="button" onClick={current} disabled={!topic}>Back to now</button></div>
        <p className="text-xs text-muted">Leave dates blank for now. Effective time selects the state at that time; known-by time limits the evidence available to reconstruct it.</p>
      </form>
      {notice && <p role="status" className="text-sm text-positive">{notice}</p>}
      {loading && <p role="status" className={box}>Loading events…</p>}
      {error && <div role="alert" className={box}><p>{error}</p><button className={`${button} mt-3`} onClick={() => scope ? setScope({ ...scope }) : setRefresh(n => n + 1)}>Retry</button></div>}
      {!loading && !error && !result && <p className={box}>No events are available yet.</p>}
      {result && <>
        <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted"><strong className="text-foreground">{result.scope.mode === "current" ? "Current view" : "Historical view"} · {result.total} events</strong><span>Effective: {dateText(result.scope.valid_at)}</span><span>Known by: {dateText(result.scope.known_at)} (Sydney time)</span></div>
        {result.truncated && <p className="text-sm text-important">Showing the first 100 events. Narrow your search for more specific results.</p>}
        {result.results.length === 0 ? <p className={box}>No matching events. Clear the search, adjust the dates, or include archived events.</p> : <div className="grid items-start gap-5 lg:grid-cols-[300px_minmax(0,1fr)]">
          <nav aria-label="Event list" className="space-y-3">{result.results.map(e => <button key={e.event.id} onClick={() => setSelected(e.event.id)} aria-pressed={selected === e.event.id} className={`${box} w-full text-left ${selected === e.event.id ? "ring-2 ring-accent" : "hover:bg-surface-hover"}`}>
            <p className="font-semibold">{e.event.title}</p><p className="mt-2 text-xs text-muted">{values[e.memory.mode]} · Importance {Math.round(e.memory.importance * 100)}% {e.memory.pinned ? "· Pinned" : ""}</p>
            <p className={`mt-2 text-sm ${e.has_conflicts ? "text-important" : "text-accent"}`}>{e.has_conflicts ? "Unresolved source conflict" : e.fields.status ? valueText(e.fields.status.value) : "View fields"}</p>
          </button>)}</nav>
          {item && <EventDetail key={`${item.event.id}:${result.scope.valid_at}:${result.scope.known_at}`} item={item} result={result} onSaved={() => { setNotice("Memory policy saved. Event history and evidence are preserved."); setScope(currentScope => currentScope === scope ? { ...currentScope! } : currentScope); }} />}
        </div>}
      </>}
    </main>
  </div>;
}
