"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, ArrowRight, Check, ChevronDown, FileText, Loader2, MessageSquare, RefreshCw, Search, X } from "lucide-react";
import { useStore } from "@/stores/useStore";
import EventFeed from "./EventFeed";
import { createSSEConnection } from "@/lib/api";
import { safeEvidenceUrl } from "@/lib/api/eventMemory";
import {
  fetchMemoryCandidates, fetchMemoryDetail, fetchMemoryUpdates, memoryValue, reviewMemoryCandidate,
  type UpdatesResponse, type WorkflowCandidate, type WorkflowDetail, type WorkflowState,
} from "@/lib/api/workflow";

const inputClass = "w-full rounded-lg border border-border bg-background px-2.5 py-2 text-xs outline-none focus:border-accent";
const buttonClass = "inline-flex items-center justify-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs hover:bg-surface-hover disabled:opacity-40";

function time(value?: string | null) {
  if (!value) return "Unknown";
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? value : parsed.toLocaleString("en-AU", { dateStyle: "medium", timeStyle: "short" });
}

function label(value: string) {
  const names: Record<string, string> = { observation: "New evidence", new_event: "New event", transition: "Field changed", correction: "Correction", conflict: "Conflict", machine_only: "Machine only", reviewed: "Human reviewed", accepted: "Human reviewed" };
  return names[value] ?? value.replaceAll("_", " ");
}

function isoDate(value: string) { return value ? new Date(value).toISOString() : ""; }
function localDateInput(value?: string) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return "";
  return new Date(date.valueOf() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

export function CandidateReviewCard({ candidate, topicId, onChanged, events = [] }: { candidate: WorkflowCandidate; topicId: number; onChanged: () => void; events?: WorkflowState[] }) {
  const [edit, setEdit] = useState({ developer: candidate.developer || "", model: candidate.model || "", version: candidate.version || "", status: candidate.status || "announced", valid_from: candidate.valid_from || "", quote: candidate.quote || "", event_id: candidate.event_id || "", relation: candidate.relation || "observation", target_id: candidate.target_id || "" });
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [target, setTarget] = useState<WorkflowDetail | null>(null);
  const [targetLoading, setTargetLoading] = useState(false);
  const [targetError, setTargetError] = useState("");
  const sourceUrl = safeEvidenceUrl(candidate.source?.url || "");
  useEffect(() => {
    if (!edit.event_id) { setTarget(null); setTargetLoading(false); setTargetError(""); return; }
    const controller = new AbortController();
    setTarget(null); setTargetLoading(true); setTargetError("");
    void fetchMemoryDetail(topicId, edit.event_id, "", "", controller.signal).then(detail => { if (!controller.signal.aborted) setTarget(detail); }).catch(e => { if (!controller.signal.aborted) setTargetError(e instanceof Error ? e.message : "Could not load the selected event."); }).finally(() => { if (!controller.signal.aborted) setTargetLoading(false); });
    return () => controller.abort();
  }, [topicId, edit.event_id]);
  const reviewVersion = edit.event_id ? target?.state.event.id === edit.event_id ? target.expected_version : undefined : "new";
  async function decide(action: "accept" | "reject" | "defer") {
    if (!reason.trim() || saving) return;
    setSaving(true); setError("");
    try {
      if (action === "accept" && !reviewVersion) throw new Error("Inspect the selected event's current state before accepting.");
      await reviewMemoryCandidate(topicId, candidate.id, { ...edit, action, reason: reason.trim(), expected_version: reviewVersion || candidate.expected_version, valid_from: edit.valid_from || null, event_id: edit.event_id || null, target_id: edit.target_id || null });
      onChanged();
    } catch (e) { setError(e instanceof Error ? e.message : "Review could not be saved. Refresh before trying again."); }
    finally { setSaving(false); }
  }
  return <article className="rounded-xl border border-border bg-surface p-4">
    <div className="mb-2 flex items-start justify-between gap-2"><h3 className="text-sm font-semibold">{candidate.title || "Extraction needs review"}</h3><span className="shrink-0 rounded bg-important/10 px-2 py-1 text-[10px] text-important">{label(candidate.review_status)}</span></div>
    {candidate.issues?.length > 0 && <ul className="mb-3 list-disc space-y-1 pl-4 text-xs text-important">{candidate.issues.map((issue, i) => <li key={i}>{issue}</li>)}</ul>}
    <details className="mb-3 rounded-lg border border-border p-3 text-xs" open><summary className="cursor-pointer font-medium">Original source · {candidate.source?.publisher || "Unknown publisher"}</summary><p className="mt-2 whitespace-pre-wrap text-muted">{candidate.source?.body || candidate.quote || "No source text was captured."}</p>{sourceUrl && <a className="mt-2 inline-block text-accent underline" href={sourceUrl} target="_blank" rel="noreferrer">Open original source</a>}</details>
    {targetLoading && <p className="mb-3 text-xs text-muted">Loading the current event before review…</p>}
    {targetError && <p role="alert" className="mb-3 text-xs text-negative">{targetError}</p>}
    {target && <div className="mb-3 rounded-lg border border-border bg-background p-3 text-xs"><p className="font-medium">Current event: {target.state.event.title}</p><p className="mt-1">Current business state: {memoryValue(target.state.fields.status?.value)}</p>{target.state.has_conflicts && <p className="mt-1 text-important">This event has unresolved conflicting values.</p>}{target.expected_version !== candidate.expected_version && <p className="mt-1 text-important">Event state changed. Compare the current value before accepting.</p>}<p className="mt-1 text-[10px] text-muted">The review will be checked against this displayed version.</p></div>}
    <div className="grid gap-3 sm:grid-cols-2">
      {([['developer', 'Developer'], ['model', 'Model family'], ['version', 'Exact release version']] as const).map(([key, title]) => <label key={key} className="text-xs">{title}<input className={`${inputClass} mt-1`} value={edit[key]} onChange={e => setEdit({ ...edit, [key]: e.target.value, event_id: "", target_id: "", relation: "observation" })} /></label>)}
      <label className="text-xs">Business state<select className={`${inputClass} mt-1`} value={edit.status} onChange={e => setEdit({ ...edit, status: e.target.value })}>{["announced", "available", "withdrawn"].map(s => <option key={s}>{s}</option>)}</select></label>
      <label className="text-xs sm:col-span-2">Effective time, with timezone<input className={`${inputClass} mt-1`} value={edit.valid_from} placeholder="2026-11-18T09:00:00Z" onChange={e => setEdit({ ...edit, valid_from: e.target.value })} /><span className="mt-1 block text-[10px] text-muted">Use a time supported by the source. Leave unknown times unresolved.</span></label>
      <label className="text-xs sm:col-span-2">Supporting quotation<textarea className={`${inputClass} mt-1 min-h-20`} value={edit.quote} onChange={e => setEdit({ ...edit, quote: e.target.value })} /></label>
    </div>
    <details className="mt-3 text-xs"><summary className="cursor-pointer text-muted">Identity and replacement</summary><div className="mt-2 grid gap-3">
      <label>Associate with an event, or leave blank to create<input className={`${inputClass} mt-1`} list={`candidate-events-${candidate.id}`} value={edit.event_id} onChange={e => setEdit({ ...edit, event_id: e.target.value })} placeholder="Choose an existing event" /><datalist id={`candidate-events-${candidate.id}`}>{events.map(event => <option key={event.event.id} value={event.event.id}>{event.event.title}</option>)}</datalist></label>
      <label>Relation<select className={`${inputClass} mt-1`} value={edit.relation} onChange={e => setEdit({ ...edit, relation: e.target.value })}>{["observation", "transition", "correction"].map(s => <option key={s}>{s}</option>)}</select></label>
      <label>Assertion being replaced<input className={`${inputClass} mt-1`} list={`candidate-targets-${candidate.id}`} value={edit.target_id} onChange={e => setEdit({ ...edit, target_id: e.target.value })} placeholder="Required for a transition or correction" /><datalist id={`candidate-targets-${candidate.id}`}>{target?.history.assertions.filter(a => a.field === "status").map(assertion => <option key={assertion.id} value={assertion.id}>{memoryValue(assertion.value)} · {time(assertion.valid_from)}</option>)}</datalist></label>
    </div></details>
    <label className="mt-3 block text-xs">Review reason<textarea required className={`${inputClass} mt-1`} value={reason} onChange={e => setReason(e.target.value)} placeholder="Explain the evidence and your decision" /></label>
    <p className="mt-2 text-[10px] text-muted">Acceptance validates this version against the current event. A changed event requires a fresh review.</p>
    {error && <p role="alert" className="mt-2 text-xs text-negative">{error}</p>}
    <div className="mt-3 flex flex-wrap gap-2">{([['accept', 'Accept'], ['defer', 'Keep unresolved'], ['reject', 'Reject']] as const).map(([action, title]) => <button key={action} className={buttonClass} disabled={!reason.trim() || saving || (action === "accept" && (!edit.valid_from.trim() || targetLoading || !reviewVersion))} onClick={() => void decide(action)}>{saving ? <Loader2 className="h-3 w-3 animate-spin" /> : action === "accept" ? <Check className="h-3 w-3" /> : null}{title}</button>)}</div>
  </article>;
}

export function MemoryEventDetail({ detail, onAsk }: { detail: WorkflowDetail; onAsk: () => void }) {
  const state = detail.state;
  return <section className="space-y-4 rounded-xl border border-accent/30 bg-accent/5 p-4" aria-label="Event facts and evidence">
    <div className="flex items-start justify-between gap-2"><div><h3 className="text-sm font-semibold">{state.event.title}</h3><p className="mt-1 text-[10px] text-muted">{state.event.kind} · Domain model v{detail.model_version} · {state.event.id}</p></div><button className={buttonClass} onClick={onAsk}><MessageSquare className="h-3 w-3" />Ask AI</button></div>
    <p className="text-[10px] text-muted">Effective at {time(state.valid_at)} · Known by {time(state.known_at)}</p>
    {state.has_conflicts && <p className="rounded bg-important/10 p-2 text-xs text-important">Conflicting stored values remain unresolved. No automatic winner has been selected.</p>}
    <dl className="grid gap-2">{Object.entries(state.fields).map(([field, data]) => <div key={field} className="rounded-lg border border-border bg-surface p-3"><dt className="text-[10px] uppercase tracking-wide text-muted">{field.replaceAll("_", " ")}</dt><dd className="mt-1 text-sm">{data.status === "conflict" ? (data.alternatives || []).map(a => memoryValue(a.value)).join(" / ") : memoryValue(data.value)}</dd><p className="mt-1 text-[10px] text-muted">{data.status === "conflict" ? "Conflicting evidence" : "No conflicting stored values"}</p></div>)}</dl>
    <div><h4 className="mb-2 text-xs font-semibold">Original evidence</h4><div className="space-y-2">{detail.evidence.map(source => {
      const url = safeEvidenceUrl(source.url);
      return <details key={source.id} className="rounded-lg border border-border bg-surface p-3" open><summary className="cursor-pointer text-xs font-medium">{source.publisher} · Published {time(source.published_at)}</summary>
        {source.passages?.map((p, i) => <blockquote key={i} className="mt-2 whitespace-pre-wrap border-l-2 border-accent pl-3 text-xs leading-relaxed">{p.quote}</blockquote>)}
        <p className="mt-2 break-all text-[10px] text-muted">Revision {source.revision} · Captured {time(source.recorded_at)}{source.content_status ? ` · ${source.content_status.replaceAll("_", " ")}` : ""}</p>
        <details className="mt-2 text-xs"><summary className="cursor-pointer text-muted">Retained source text</summary><p className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap leading-relaxed">{source.body}</p></details>
        {url && <a href={url} target="_blank" rel="noreferrer" className="mt-2 inline-block text-xs text-accent underline">Open original source</a>}
      </details>;
    })}{detail.evidence.length === 0 && <p className="text-xs text-muted">No supporting source is available in this time scope.</p>}</div></div>
    <details className="text-xs"><summary className="cursor-pointer font-medium">Assertion history</summary><div className="mt-2 space-y-2">{detail.history.assertions.map(a => <div className="rounded-lg border border-border bg-surface p-2" key={a.id}><p>{label(a.relation)} · {a.field}: {memoryValue(a.value)}</p><p className="mt-1 text-[10px] text-muted">Effective {time(a.valid_from)} · Recorded {time(a.recorded_at)}</p><p className="mt-1 break-all text-[10px] text-muted">{a.id}{a.target_id && ` · Replaces ${a.target_id}`}</p>{a.reason && <p className="mt-1 text-muted">{a.reason}</p>}</div>)}</div></details>
  </section>;
}

export default function UpdatesPanel({ layout = "desktop" }: { layout?: "desktop" | "mobile" }) {
  const topicId = useStore(s => s.activeTopicId);
  const refreshKey = useStore(s => s.insightRefreshKey);
  const scope = useStore(s => s.eventMemoryScope);
  const setScope = useStore(s => s.setEventMemoryScope);
  const setChatOpen = useStore(s => s.setChatOpen);
  const refreshInsights = useStore(s => s.refreshInsights);
  const hydrateLiveSummary = useStore(s => s.hydrateLiveSummary);
  const hydrateGlobalOverview = useStore(s => s.hydrateGlobalOverview);
  const [view, setView] = useState<"updates" | "sources" | "review">("updates");
  const [data, setData] = useState<UpdatesResponse | null>(null);
  const [candidates, setCandidates] = useState<WorkflowCandidate[]>([]);
  const [query, setQuery] = useState("");
  const [appliedQuery, setAppliedQuery] = useState("");
  const [valid, setValid] = useState(localDateInput(scope?.valid_at));
  const [known, setKnown] = useState(localDateInput(scope?.known_at));
  const [dates, setDates] = useState({ valid: scope?.valid_at || "", known: scope?.known_at || "" });
  const [selected, setSelected] = useState<string | null>(scope?.event_id || null);
  const [detail, setDetail] = useState<WorkflowDetail | null>(null);
  const [error, setError] = useState("");
  const [detailError, setDetailError] = useState("");
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    if (topicId == null) return;
    const sse = createSSEConnection(() => { setVersion(v => v + 1); refreshInsights(); });
    const poll = setInterval(() => { setVersion(v => v + 1); void hydrateLiveSummary(topicId); void hydrateGlobalOverview(topicId); }, 30000);
    return () => { sse.close(); clearInterval(poll); };
  }, [topicId, refreshInsights, hydrateLiveSummary, hydrateGlobalOverview]);

  useEffect(() => {
    if (topicId == null) { setData(null); setCandidates([]); setLoading(false); return; }
    if (view === "sources") return;
    const controller = new AbortController();
    setLoading(true); setError("");
    void Promise.all([fetchMemoryUpdates(topicId, appliedQuery, dates.valid, dates.known, controller.signal), fetchMemoryCandidates(topicId, controller.signal)]).then(([updates, pending]) => {
      if (controller.signal.aborted) return;
      setData(updates); setCandidates(pending.candidates);
    }).catch(e => { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : "Could not load event memory."); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [topicId, appliedQuery, dates, view, version, refreshKey]);

  useEffect(() => {
    if (topicId == null || !selected) { setDetail(null); return; }
    const controller = new AbortController();
    setDetail(null); setDetailLoading(true); setDetailError("");
    void fetchMemoryDetail(topicId, selected, dates.valid, dates.known, controller.signal).then(value => { if (!controller.signal.aborted) setDetail(value); }).catch(e => { if (!controller.signal.aborted) setDetailError(e instanceof Error ? e.message : "Could not load event evidence."); }).finally(() => { if (!controller.signal.aborted) setDetailLoading(false); });
    return () => controller.abort();
  }, [topicId, selected, dates, version]);

  function applyScope() {
    try { setDates({ valid: isoDate(valid), known: isoDate(known) }); setData(null); setSelected(null); setDetail(null); setScope(null); }
    catch { setError("Enter valid dates before applying the time scope."); }
  }
  const pending = candidates.filter(c => ["pending", "deferred", "failed"].includes(c.review_status));
  const historic = !!(dates.valid || dates.known);
  return <div className={`${layout === "mobile" ? "w-full" : "flex-[3] min-w-[300px] border-r border-border"} flex h-full min-h-0 flex-col bg-background`}>
    <div className="shrink-0 border-b border-border bg-surface p-3">
      <div className="flex flex-wrap items-center gap-1">{([['updates', 'Updates'], ['sources', 'Sources'], ['review', `Review${data?.pending_count ? ` (${data.pending_count})` : ''}`]] as const).map(([key, title]) => <button key={key} onClick={() => setView(key)} className={`rounded-lg px-3 py-2 text-xs font-medium ${view === key ? "bg-accent text-white" : "text-muted hover:bg-surface-hover"}`}>{title}</button>)}<button title="Refresh event memory" className={`${buttonClass} ml-auto px-2`} onClick={() => setVersion(v => v + 1)}><RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} /></button></div>
      {view === "updates" && <><form className="mt-3 flex gap-2" onSubmit={e => { e.preventDefault(); setAppliedQuery(query); setData(null); setSelected(null); setDetail(null); setScope(null); setVersion(v => v + 1); }}><label className="sr-only" htmlFor="memory-search">Search event facts</label><input id="memory-search" className={inputClass} value={query} onChange={e => setQuery(e.target.value)} placeholder="Search a model, developer or event…" /><button className={buttonClass} type="submit"><Search className="h-3.5 w-3.5" /><span className="sr-only">Search</span></button></form><details className="mt-2 text-xs"><summary className="cursor-pointer text-muted">Time scope{historic ? " · Historical view" : " · Current"}</summary><div className="mt-2 grid gap-2 sm:grid-cols-2"><label>Effective at<input type="datetime-local" className={`${inputClass} mt-1`} value={valid} onChange={e => setValid(e.target.value)} /></label><label>Known by<input type="datetime-local" className={`${inputClass} mt-1`} value={known} onChange={e => setKnown(e.target.value)} /></label></div><p className="mt-2 text-[10px] text-muted">Dates use your local timezone. Known by excludes information recorded later.</p><div className="mt-2 flex gap-2"><button className={buttonClass} onClick={applyScope}>Apply time scope</button><button className={buttonClass} onClick={() => { setValid(""); setKnown(""); setDates({ valid: "", known: "" }); setData(null); setSelected(null); setDetail(null); setScope(null); }}>Current view</button></div></details></>}
    </div>
    {view === "sources" ? <EventFeed layout="mobile" /> : <div className="flex-1 space-y-3 overflow-y-auto p-3">
      {error && <div role="alert" className="rounded-lg border border-negative/30 bg-negative/5 p-3 text-xs text-negative">{error}</div>}
      {loading && !data && <div className="flex items-center justify-center gap-2 p-8 text-xs text-muted"><Loader2 className="h-4 w-4 animate-spin" />Loading event memory…</div>}
      {view === "review" ? <>{historic && <p className="text-xs text-muted">Reviews apply to current evidence, independently of the historical view.</p>}{pending.map(candidate => topicId != null && <CandidateReviewCard key={`${candidate.id}-${candidate.expected_version}`} topicId={topicId} candidate={candidate} events={data?.events || []} onChanged={() => { setVersion(v => v + 1); refreshInsights(); }} />)}{!loading && pending.length === 0 && <div className="p-8 text-center text-sm text-muted"><Check className="mx-auto mb-2 h-6 w-6" />No candidates need review.</div>}</> : <>
        <p className="text-[10px] leading-relaxed text-muted">Model releases · Event memory v{data?.coverage.version || 1}. Other coverage remains available in Sources and Briefing. Machine-only observations have not been externally verified.</p>
        {selected && <><div className="flex items-center justify-between"><p className="text-xs font-semibold">Selected event</p><button aria-label="Close selected event" className={buttonClass} onClick={() => { setSelected(null); setDetail(null); setScope(null); }}><X className="h-3 w-3" /></button></div>{detailLoading && <p className="text-xs text-muted">Loading original evidence…</p>}{detailError && <p role="alert" className="text-xs text-negative">{detailError}</p>}{detail && <MemoryEventDetail detail={detail} onAsk={() => { setScope({ event_id: detail.state.event.id, title: detail.state.event.title, valid_at: dates.valid || undefined, known_at: dates.known || undefined }); setChatOpen(true); }} />}</>}
        {data?.updates.map(update => <button key={update.id} onClick={() => setSelected(update.event_id)} className={`block w-full rounded-xl border p-4 text-left transition-colors hover:border-accent/50 ${selected === update.event_id ? "border-accent/40 bg-accent/5" : "border-border bg-surface"}`}><div className="flex flex-wrap items-center gap-2 text-[10px]"><span className="rounded bg-accent/10 px-2 py-1 text-accent">{label(update.kind)}</span><span className="text-muted">{label(update.review_status)}</span><span className="ml-auto text-muted">{time(update.recorded_at)}</span></div><h3 className="mt-2 text-sm font-semibold">{update.title}</h3><p className="mt-2 flex flex-wrap items-center gap-2 text-xs"><span className="text-muted">{update.field?.replaceAll("_", " ")}</span>{update.previous_value !== null && update.previous_value !== undefined && <><span>{memoryValue(update.previous_value)}</span><ArrowRight className="h-3 w-3 text-muted" /></>}<span className="font-medium">{memoryValue(update.value)}</span></p><p className="mt-2 text-[10px] text-muted">Effective {time(update.valid_from)} · {update.source_count || 1} source record{update.source_count === 1 ? "" : "s"} · Inspect evidence</p></button>)}
        {!loading && data?.updates.length === 0 && <div className="rounded-xl border border-dashed border-border p-6 text-center"><FileText className="mx-auto mb-3 h-6 w-6 text-muted" /><h3 className="text-sm font-semibold">No accepted changes in this scope</h3><p className="mt-2 text-xs leading-relaxed text-muted">Collection preserves sources first. Model release facts appear here when identity, supporting text and effective time are established.</p>{pending.length > 0 && <button className={`${buttonClass} mt-3`} onClick={() => setView("review")}><AlertTriangle className="h-3 w-3" />Review {pending.length} unresolved candidate{pending.length === 1 ? "" : "s"}</button>}</div>}
        <details className="text-xs text-muted"><summary className="flex cursor-pointer items-center gap-1"><ChevronDown className="h-3 w-3" />Domain model</summary><p className="mt-2 leading-relaxed">ModelRelease v1 tracks developer, model family, exact version and availability. Business state, evidence support, review and attention are handled separately. Dates require source support; conflicting observations remain visible.</p></details>
      </>}
    </div>}
  </div>;
}
