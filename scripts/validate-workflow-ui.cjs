// Real React component/store checks with controlled network boundaries; no paid calls.
// Usage: node scripts/validate-workflow-ui.cjs /path/to/matching/react-test-renderer/node_modules
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const deps = path.resolve(process.argv[2] || 'frontend/node_modules');
const React = require(path.join(deps, 'react'));
const Renderer = require(path.join(deps, 'react-test-renderer'));
const ts = require(path.join(deps, 'typescript'));
const { act } = React;
global.IS_REACT_ACT_ENVIRONMENT = true;
let state;
let timer = 0;
const calls = [];
const apiOverrides = {};
const api = new Proxy({}, { get: (_, key) => apiOverrides[key] || (() => { throw Error('Unexpected API: ' + String(key)); }) });
function load(file, imports = {}, globals = {}) {
  const source = fs.readFileSync(path.join(root, file), 'utf8');
  const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText;
  const module = { exports: {} };
  vm.runInNewContext(code, { module, exports: module.exports, URL, URLSearchParams, AbortController, Date, console,
    setTimeout: () => ++timer, clearTimeout() {}, setInterval: () => ++timer, clearInterval() {},
    process: { env: {} }, ...globals, require: name => imports[name] || require(path.join(deps, name)),
  }, { filename: file });
  return module.exports;
}
const { useStore } = load('frontend/src/stores/useStore.ts', {
  zustand: { create: () => initializer => {
    const get = () => state;
    const set = change => { state = { ...state, ...(typeof change === 'function' ? change(state) : change) }; };
    state = initializer(set, get, {});
    const hook = selector => selector ? selector(state) : state;
    hook.getState = get; hook.setState = set;
    return hook;
  } },
  'zustand/middleware': { persist: init => init }, '@/lib/api': api,
});
const eventApi = load('frontend/src/lib/api/eventMemory.ts');
const network = [];
const workflowApi = load('frontend/src/lib/api/workflow.ts', { './shared': { BASE: '', fetchWithRetry: async (url, options) => {
  network.push({ url, options }); return { ok: false, status: 409, json: async () => ({ detail: 'Candidate changed; refresh review' }) };
} } });
function deferred() { let resolve; const promise = new Promise(r => { resolve = r; }); return { resolve, promise }; }
let slow = false;
const pending = [];
const result = topic => ({ updates: [{ id: `u-${topic}`, event_id: `e-${topic}`, title: `Release ${topic}`, kind: 'observation', field: 'status', previous_value: null, value: 'available', valid_from: '2026-01-01T00:00:00Z', recorded_at: '2026-01-02T00:00:00Z', review_status: 'machine_only', source_count: 1 }], events: [], pending_count: 0, coverage: { model: 'ModelRelease', version: 1, authority: 'eventkb' } });
const detail = topic => ({ state: { event: { id: `e-${topic}`, title: `Release ${topic}`, topic: `topic:${topic}`, kind: 'ModelRelease' }, fields: { status: { status: 'confirmed', value: 'available', assertion_ids: ['a1'], evidence_ids: ['s1'] } }, has_conflicts: false, valid_at: '2026-01-01T00:00:00Z', known_at: '2026-01-02T00:00:00Z' }, history: { assertions: [] }, evidence: [{ id: 's1', publisher: 'Original publisher', revision: 'hash-1', published_at: '2026-01-01T00:00:00Z', recorded_at: '2026-01-02T00:00:00Z', url: 'javascript:bad()', body: 'The original source says this release is available.', passages: [{ quote: 'this release is available', field: 'status' }] }], model_version: 1, expected_version: `hash-${topic}` });
const workflow = {
  ...workflowApi,
  fetchMemoryUpdates: async topic => {
    if (!slow) return result(topic);
    const task = deferred(); pending.push({ topic, ...task }); return task.promise;
  },
  fetchMemoryCandidates: async () => ({ candidates: [] }),
  fetchMemoryDetail: async topic => detail(topic),
  reviewMemoryCandidate: async (topic, candidate, body) => { calls.push({ topic, candidate, body }); },
};
const icons = new Proxy({}, { get: () => props => React.createElement('svg', props) });
let sourceUpdate;
const updateTimers = new Map();
const components = load('frontend/src/components/UpdatesPanel.tsx', {
  '@/stores/useStore': { useStore }, '@/lib/api': { createSSEConnection: callback => { sourceUpdate = callback; return { close() {} }; } },
  '@/lib/api/eventMemory': eventApi, '@/lib/api/workflow': workflow,
  './EventFeed': () => React.createElement('div', null, 'Original source feed'), 'lucide-react': icons,
}, {
  setInterval: (callback, ms) => { const id = ++timer; updateTimers.set(id, { callback, ms }); return id; },
  clearInterval: id => updateTimers.delete(id),
});
const chat = load('frontend/src/components/ChatBot.tsx', {
  '@/stores/useStore': { useStore }, '@/lib/api': {}, '@/lib/api/eventMemory': eventApi,
  'lucide-react': icons, 'framer-motion': { motion: new Proxy({}, { get: () => props => React.createElement('div', props) }), AnimatePresence: ({ children }) => children },
  'react-markdown': ({ components, children }) => components.p({ children }), 'remark-gfm': () => {},
});
function content(node) { return node.children.map(child => typeof child === 'string' ? child : content(child)).join(''); }
function button(rendered, text) { return rendered.root.findAllByType('button').find(b => content(b).includes(text)); }
const checks = [];
function pass(name) { checks.push(name); }
(async () => {
  await assert.rejects(() => workflowApi.reviewMemoryCandidate(1, 'candidate 1', { action: 'accept', reason: 'review', expected_version: 'v1' }), /Candidate changed/);
  assert.match(network[0].url, /candidate%201/); pass('Review conflicts preserve server reason and encode candidate IDs');
  useStore.getState().setActiveTopicId(1);
  let rendered;
  await act(async () => { rendered = Renderer.create(React.createElement(components.default, { key: 1 })); });
  assert.ok(button(rendered, 'Release 1')); assert.match(JSON.stringify(rendered.toJSON()), /Machine only/); pass('Topic opens on changes with honest machine review status');
  await act(async () => button(rendered, 'Release 1').props.onClick());
  assert.match(JSON.stringify(rendered.toJSON()), /this release is available/);
  assert.equal(rendered.root.findAllByType('a').length, 0); pass('Event detail retains exact evidence and rejects unsafe source URLs');
  await act(async () => button(rendered, 'Ask AI').props.onClick());
  assert.equal(state.eventMemoryScope.event_id, 'e-1'); assert.equal(state.chatOpen, true);
  assert.match(JSON.stringify(rendered.toJSON()), /Original evidence/); pass('Asking keeps selected facts visible and sends a stable event scope');
  apiOverrides.createChatTask = async (...args) => { calls.push({ chat: args }); };
  useStore.setState({ hydrateChatConversation: async () => {}, ensureChatTaskPoll() {} });
  await state.startChatTask('What changed?');
  assert.equal(calls.at(-1).chat[4].event_id, 'e-1'); assert.equal(state.eventMemoryScope.event_id, 'e-1'); pass('Follow-up requests preserve explicit event scope');
  slow = true;
  useStore.getState().setActiveTopicId(2);
  assert.equal(state.eventMemoryScope, null); pass('Topic switch clears event memory chat scope');
  await act(async () => rendered.update(React.createElement(components.default, { key: 2 })));
  assert.doesNotMatch(JSON.stringify(rendered.toJSON()), /Release 1/);
  const old = pending.at(-1);
  useStore.getState().setActiveTopicId(3);
  await act(async () => rendered.update(React.createElement(components.default, { key: 3 })));
  await act(async () => pending.at(-1).resolve(result(3)));
  await act(async () => old.resolve(result(2)));
  assert.match(JSON.stringify(rendered.toJSON()), /Release 3/); assert.doesNotMatch(JSON.stringify(rendered.toJSON()), /Release 2/); pass('Late requests cannot restore another Topic changes');
  const beforeSearch = pending.length;
  await act(async () => rendered.root.findByType('form').props.onSubmit({ preventDefault() {} }));
  assert.equal(pending.length, beforeSearch + 1);
  await act(async () => pending.at(-1).resolve(result(3)));
  await act(async () => rendered.root.findByType('form').props.onSubmit({ preventDefault() {} }));
  assert.equal(pending.length, beforeSearch + 2);
  await act(async () => pending.at(-1).resolve(result(3)));
  assert.match(JSON.stringify(rendered.toJSON()), /Release 3/); pass('Submitting the same search refreshes instead of leaving a blank list');
  await act(async () => button(rendered, 'Sources').props.onClick());
  assert.match(JSON.stringify(rendered.toJSON()), /Original source feed/); pass('Original source reading remains available');
  await act(async () => rendered.unmount());
  const candidate = { id: 'c1', topic_id: 3, event_id: 'e-3', title: 'Review release', developer: 'Lab', model: 'Model', version: '1', status: 'available', valid_from: null, quote: 'Explicit source text', relation: 'transition', target_id: 'a-old', review_status: 'pending', issues: ['Unknown time'], expected_version: 'hash-old', source: { body: 'Explicit source text' } };
  await act(async () => { rendered = Renderer.create(React.createElement(components.CandidateReviewCard, { candidate, topicId: 3, onChanged() {} })); });
  assert.equal(button(rendered, 'Accept').props.disabled, true);
  const reason = rendered.root.findByProps({ placeholder: 'Explain the evidence and your decision' });
  await act(async () => reason.props.onChange({ target: { value: 'Time is still unsupported' } }));
  await act(async () => button(rendered, 'Keep unresolved').props.onClick());
  assert.equal(calls.at(-1).body.expected_version, 'hash-3'); assert.equal(calls.at(-1).body.action, 'defer'); assert.equal(calls.at(-1).body.target_id, 'a-old'); pass('Unknown time stays unresolved; review includes displayed target and stale-version token');
  await act(async () => rendered.root.findByProps({ placeholder: '2026-11-18T09:00:00Z' }).props.onChange({ target: { value: '2026-01-01T00:00:00Z' } }));
  await act(async () => rendered.root.findByProps({ value: 'Lab' }).props.onChange({ target: { value: 'New Lab' } }));
  await act(async () => button(rendered, 'Accept').props.onClick());
  assert.equal(calls.at(-1).body.expected_version, 'new'); assert.equal(calls.at(-1).body.event_id, null); pass('Correcting identity to a new event does not reuse the previous event token');
  await act(async () => rendered.root.findByProps({ value: 'New Lab' }).props.onChange({ target: { value: 'Lab' } }));
  await act(async () => rendered.root.findByProps({ placeholder: 'Choose an existing event' }).props.onChange({ target: { value: 'e-3' } }));
  await act(async () => button(rendered, 'Accept').props.onClick());
  assert.equal(calls.at(-1).body.expected_version, 'hash-3'); assert.equal(calls.at(-1).body.event_id, 'e-3'); pass('Selecting an existing event loads and reviews its current state before acceptance');
  await act(async () => rendered.unmount());
  const source = { id: 'S1', title: 'Original announcement', type: 'evidence', quote: 'Exact quoted source text', revision: 'r1', publisher: 'Lab', url: 'https://example.invalid/release' };
  await act(async () => { rendered = Renderer.create(React.createElement(chat.ChatRichText, { content: 'Available [S1]. Unsupported [S99].', sources: [source] })); });
  assert.equal(rendered.root.findAllByType('button').length, 1); assert.match(JSON.stringify(rendered.toJSON()), /\[S99\]/); pass('Only source-bound citations become evidence controls');
  await act(async () => rendered.root.findByType('button').props.onClick());
  assert.match(JSON.stringify(rendered.toJSON()), /Exact quoted source text/); assert.equal(rendered.root.findByType('a').props.href, source.url); pass('Answer citation opens retained original quotation and revision');
  await act(async () => rendered.unmount());
  apiOverrides.fetchCachedSummary = async () => ({ content: 'Old briefing', generated_at: null, event_memory_stale: true, event_memory_notice: 'Event evidence changed after this briefing.' });
  apiOverrides.fetchLiveSummaryStatus = async () => ({ generating: false, status: 'idle' });
  await state.hydrateLiveSummary(3);
  assert.equal(state.liveSummaryByTopic[3].eventMemoryStale, true); assert.match(state.liveSummaryByTopic[3].eventMemoryNotice, /Event evidence changed/);
  apiOverrides.fetchInsightSummary = async () => ({ total_articles: 0, important_count: 0, source_distribution: {}, sentiment_distribution: {}, top_events: [] });
  apiOverrides.fetchTopicInsight = async () => ({ article_count: 0, previous_count: 0, trend_delta: 0, sentiment_distribution: {}, top_tags: [] });
  apiOverrides.fetchTrending = async () => ({ daily: [], top_entities: [], avg_topic_relevance: 0 });
  const Analysis = load('frontend/src/components/AnalysisPanel.tsx', {
    '@/stores/useStore': { useStore }, '@/lib/api': api, '@/lib/utils': { timeAgo: () => 'Earlier' }, 'lucide-react': icons,
    './MacroAnalysisPanel': () => null, './AnalysisRichText': ({ content }) => React.createElement('p', null, content),
  }).default;
  await act(async () => { rendered = Renderer.create(React.createElement(Analysis)); });
  assert.match(JSON.stringify(rendered.toJSON()), /Event evidence changed after this briefing/); assert.match(JSON.stringify(rendered.toJSON()), /Old briefing/); pass('Briefing hydration and visible notice preserve evidence freshness');
  await act(async () => rendered.unmount());
  const overviewArtifact = { id: 'overview-3', topic_id: 3, content: 'Saved overview', event_memory_stale: true, event_memory_notice: 'Event evidence changed after this overview. Regenerate to include the latest event memory.' };
  const overviewRequests = [];
  const knowledgeApi = load('frontend/src/lib/api/knowledge.ts', {
    './shared': { BASE: '', safeJson: response => response.json() },
  }, { fetch: async (url, options) => { overviewRequests.push({ url, options }); return { json: async () => ({ artifact: overviewArtifact }) }; } });
  const overview = await knowledgeApi.fetchGlobalOverview(3);
  assert.equal(overview.event_memory_stale, true); assert.equal(overview.event_memory_notice, overviewArtifact.event_memory_notice);
  assert.match(overviewRequests[0].url, /synthesis\/global-overview$/); assert.equal(overviewRequests[0].options.cache, 'no-store');
  let overviewReads = 0; let overviewGenerations = 0;
  apiOverrides.fetchGlobalOverview = async () => { overviewReads++; return overview; };
  apiOverrides.fetchGlobalOverviewStatus = async () => ({ generating: false, status: 'idle' });
  apiOverrides.postGlobalOverviewGenerate = async () => { overviewGenerations++; return { started: true }; };
  await state.hydrateGlobalOverview(3);
  assert.equal(state.globalOverviewByTopic[3].eventMemoryStale, true); assert.equal(state.globalOverviewByTopic[3].eventMemoryNotice, overviewArtifact.event_memory_notice);
  pass('Global overview artifact API mapping and hydration retain evidence freshness');
  apiOverrides.fetchEvents = async () => ({ events: [] });
  apiOverrides.fetchSynthesisArtifact = async () => null;
  apiOverrides.fetchEvolutionReportStatus = async () => ({ generating: false, status: 'idle' });
  const Macro = load('frontend/src/components/MacroAnalysisPanel.tsx', {
    '@/stores/useStore': { useStore }, '@/lib/api': api, '@/lib/utils': { timeAgo: () => 'Earlier' }, 'lucide-react': icons,
    '@/lib/knowledgeLabels': {}, '@/lib/hooks/useTopicKnowledgeData': { useTopicKnowledgeData: () => ({ snapshots: [], deltas: [], overviewArtifact: null, loadingSnapshots: false, knowledgeError: null, refreshKnowledge: async () => {} }) },
    './AnalysisRichText': ({ content }) => React.createElement('p', null, content),
  }).default;
  await act(async () => { rendered = Renderer.create(React.createElement(Macro, { activeTopicId: 3, trending: null })); });
  assert.match(JSON.stringify(rendered.toJSON()), /Event evidence changed after this overview/); assert.match(JSON.stringify(rendered.toJSON()), /Saved overview/);
  const beforeRefresh = overviewReads;
  state.refreshInsights();
  await act(async () => rendered.update(React.createElement(Macro, { activeTopicId: 3, trending: null })));
  assert.equal(overviewReads, beforeRefresh + 1); assert.equal(overviewGenerations, 0);
  pass('Global overview visibly warns and refreshes saved freshness without regeneration');
  await act(async () => rendered.unmount());
  slow = false;
  const overviewAndUpdates = () => React.createElement(React.Fragment, null, React.createElement(components.default, { key: 'updates' }), React.createElement(Macro, { key: 'macro', activeTopicId: 3, trending: null }));
  await act(async () => { rendered = Renderer.create(overviewAndUpdates()); });
  const beforeSourceUpdate = overviewReads;
  await act(async () => sourceUpdate());
  await act(async () => rendered.update(overviewAndUpdates()));
  assert.equal(overviewReads, beforeSourceUpdate + 1);
  const periodic = [...updateTimers.values()].find(item => item.ms === 30000);
  assert.ok(periodic);
  const beforePoll = overviewReads;
  await act(async () => periodic.callback());
  assert.equal(overviewReads, beforePoll + 1); assert.equal(overviewGenerations, 0);
  pass('Collection SSE and periodic reads refresh global overview freshness without AI generation');
  await act(async () => rendered.unmount());
  console.log(JSON.stringify({ ok: true, count: checks.length, checks, limit: 'Isolated React/store/API checks; browser and backend E2E tested separately' }, null, 2));
})().catch(e => { console.error(e); process.exitCode = 1; });
