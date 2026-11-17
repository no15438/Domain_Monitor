// Exercise the real page with React. Mock only its network and framework shell.
// Usage: node scripts/validate-event-memory-ui.cjs /path/to/node_modules
// Requires matching react-test-renderer (19.2.4) in that dependency directory.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const deps = path.resolve(process.argv[2] || 'frontend/node_modules');
const root = path.resolve(__dirname, '..');
const React = require(path.join(deps, 'react'));
const Renderer = require(path.join(deps, 'react-test-renderer'));
const ts = require(path.join(deps, 'typescript'));
global.IS_REACT_ACT_ENVIRONMENT = true;
const { act } = React;
let delayQueries = false;
const queries = [];
const saves = [];
const response = data => ({ ok: true, json: async () => data });
function deferred() {
  let resolve;
  const promise = new Promise(r => { resolve = r; });
  return { promise, resolve };
}
function payload(url) {
  const topic = url.searchParams.get('topic');
  return {
    scope: { topic, valid_at: url.searchParams.get('valid_at') || '2026-11-17T09:00:00Z', known_at: '2026-11-17T09:00:00Z', mode: url.searchParams.has('valid_at') ? 'historical' : 'current' },
    total: 1, truncated: false,
    results: [{ event: { id: topic, title: `Event ${topic}`, topic, kind: 'event' }, fields: { status: { status: 'confirmed', value: `State ${topic}`, evidence_ids: [], alternatives: [] } },
      citations: [], memory: { mode: 'active', importance: .5, pinned: 0 }, has_conflicts: false }],
  };
}
async function fetchMock(input, options = {}) {
  const url = new URL(input, 'http://localhost');
  if (url.pathname.endsWith('/topics')) return response({ topics: ['one', 'two'] });
  if (url.pathname.endsWith('/query')) {
    const pending = deferred();
    queries.push({ url, ...pending });
    if (!delayQueries) pending.resolve(response(payload(url)));
    // Ignore AbortSignal to reproduce a transport that delivers a cancelled response.
    return pending.promise;
  }
  if (url.pathname.endsWith('/history')) return response({ assertions: [], evidence: [], memory_history: [] });
  if (url.pathname.endsWith('/memory') && options.method === 'POST') {
    const pending = deferred(); saves.push({ ...pending, body: JSON.parse(options.body) }); return pending.promise;
  }
  throw new Error(`Unexpected request: ${url}`);
}
function load(relative, imports = {}) {
  const source = fs.readFileSync(path.join(root, relative), 'utf8');
  const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2020, esModuleInterop: true } }).outputText;
  const module = { exports: {} };
  vm.runInNewContext(code, { module, exports: module.exports, URL, URLSearchParams, AbortController, process: { env: {} }, fetch: fetchMock,
    require: name => imports[name] || require(path.join(deps, name)), console }, { filename: relative });
  return module.exports;
}
const api = load('frontend/src/lib/api/eventMemory.ts');
const Page = load('frontend/src/app/event-memory/page.tsx', {
  '@/lib/api/eventMemory': api,
  '@/components/ThemeToggle': () => null,
  'next/link': ({ children, href }) => React.createElement('a', { href }, children),
}).default;

(async () => {
  let rendered;
  await act(async () => { rendered = Renderer.create(React.createElement(Page)); });
  const text = () => JSON.stringify(rendered.toJSON());
  const topicSelect = () => rendered.root.findAllByType('select')[0];
  const switchTopic = value => act(async () => topicSelect().props.onChange({ target: { value } }));
  assert.match(text(), /Event one/);
  delayQueries = true;
  await switchTopic('two');
  assert.doesNotMatch(text(), /Event one/); // Hide stale details immediately.
  const older = queries.at(-1);
  await switchTopic('one');
  const newer = queries.at(-1);
  await act(async () => newer.resolve(response(payload(newer.url))));
  await act(async () => older.resolve(response(payload(older.url))));
  assert.match(text(), /Event one/);
  assert.doesNotMatch(text(), /Event two/); // Late response cannot replace the latest scope.

  const reason = rendered.root.findByProps({ placeholder: 'Explain why to retain, downweight, or archive' });
  await act(async () => reason.props.onChange({ target: { value: 'Synthetic review' } }));
  let pendingSave;
  await act(async () => { pendingSave = rendered.root.findAllByType('form')[1].props.onSubmit({ preventDefault() {} }); });
  assert.equal(saves.length, 1);
  assert.equal(saves[0].body.topic, 'one');
  delayQueries = false;
  await switchTopic('two');
  await act(async () => { saves[0].resolve(response({})); await pendingSave; });
  assert.equal(topicSelect().props.value, 'two');
  assert.match(text(), /Event two/);
  assert.doesNotMatch(text(), /Event one/);
  assert.doesNotMatch(text(), /Memory policy saved/); // Completion from an unmounted detail stays silent.

  const date = rendered.root.findAllByProps({ type: 'datetime-local' })[0];
  await act(async () => date.props.onInput({ currentTarget: { value: '2026-01-15T12:00' } }));
  await act(async () => rendered.root.findAllByType('form')[0].props.onSubmit({ preventDefault() {} }));
  assert.ok(queries.at(-1).url.searchParams.get('valid_at'));
  assert.match(text(), /Historical view/);
  assert.equal(rendered.root.findByType('fieldset').props.disabled, true);
  assert.equal(api.safeEvidenceUrl('javascript:alert(1)'), undefined);
  await act(async () => rendered.unmount());
  process.stdout.write(JSON.stringify({ ok: true, checks: ['stale details hidden immediately', 'late query ignored', 'late save cannot revert topic', 'native date input applied; history read-only', 'unsafe source URL rejected'], scope: 'real React page; mocked network; complements live browser checks' }) + '\n');
})().catch(error => { console.error(error); process.exitCode = 1; });
