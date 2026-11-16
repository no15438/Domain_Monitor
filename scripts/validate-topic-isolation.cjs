// Run copied TypeScript in an isolated hook/store harness. No server, storage or network.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = process.argv[2];
// Optional compiler path permits read-only reuse of an existing installation.
const ts = require(process.argv[3] || path.join(root, 'frontend/node_modules/typescript'));
function compile(file, resolver) {
  const code = ts.transpileModule(fs.readFileSync(path.join(root, file), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2020 }
  }).outputText;
  const exports = {};
  new Function('require', 'exports', code)(resolver, exports);
  return exports;
}
let state;
const unexpectedAPI = new Proxy({}, { get: (_, key) => () => { throw Error('Unexpected API: ' + String(key)); } });
const {useStore} = compile('frontend/src/stores/useStore.ts', name => {
  if (name === 'zustand') return {create: () => initializer => {
    const get = () => state;
    const set = change => { state = {...state, ...(typeof change === 'function' ? change(state) : change)}; };
    state = initializer(set, get, {});
    const hook = () => state;
    hook.getState = get; hook.setState = set;
    return hook;
  }};
  if (name === 'zustand/middleware') return {persist: init => init};
  if (name === '@/lib/api') return unexpectedAPI;
  throw Error(name);
});
useStore.setState({activeTopicId:1, articles:[{id:'old',topic_id:1}], selectedArticle:{id:'old'}, selectedEventContext:{event_id:'old'}, selectedKnowledgeEventId:'old',selectedKnowledgeEventTitle:'Old',highlightedEventId:'old'});
useStore.getState().setActiveTopicId(2);
for (const field of ['selectedArticle','selectedEventContext','selectedKnowledgeEventId','selectedKnowledgeEventTitle','highlightedEventId']) assert.equal(state[field],null,field);
assert.deepEqual(state.articles,[]);
assert.equal(state.activeTopicId,2);
useStore.getState().setActiveTopicId(null);
assert.equal(state.activeTopicId,null);

let effects=[], callbacks=[], slots=[], calls=[], index=0;
const hookMock={
  useState: initial => { const i=index++;slots[i]=typeof initial==='function'?initial():initial;return [slots[i],v=>{slots[i]=typeof v==='function'?v(slots[i]):v}]; },
  useEffect: effect => effects.push(effect),
  useCallback: callback => {callbacks.push(callback);return callback},
  useMemo: fn => fn(),useRef:()=>({current:null})
};
const {default:EventFeed} = compile('frontend/src/components/EventFeed.tsx', name => {
  if(name==='react')return hookMock;
  if(name==='react/jsx-runtime')return {jsx:()=>null,jsxs:()=>null,Fragment:()=>null};
  if(name==='@/stores/useStore')return {useStore};
  if(name==='@/lib/api')return {
    fetchArticles:()=>{calls.push('fetch');return Promise.resolve({articles:[],total:0})},
    createSSEConnection:()=>{calls.push('sse');return {close(){}}}
  };
  return new Proxy({}, {get:()=>()=>null});
});
(async()=>{
  EventFeed({});
  const cleanup=effects.map(effect=>effect()).filter(f=>typeof f==='function');
  for(const cb of callbacks)await cb();
  assert.deepEqual(calls,[], 'No topic must make zero fetch/SSE calls');
  assert.deepEqual(state.articles,[]);
  assert.equal(slots[0],false,'loading cleared');
  assert.equal(slots[1],null,'error cleared');
  assert.equal(slots[2],null,'load-more error cleared');
  assert.equal(slots[4],false,'load-more loading cleared');
  assert.equal(slots[5],0,'active total cleared');
  assert.equal(slots[6],0,'loaded count cleared');
  assert.equal(slots[8],'closed','SSE closed');
  assert.deepEqual(slots[9],[],'archive articles cleared');
  assert.equal(slots[10],0,'archive count cleared');
  cleanup.forEach(f=>f());
  effects=[];callbacks=[];index=0;slots=[];calls=[];
  useStore.setState({activeTopicId:2});
  EventFeed({});
  const activeCleanup=effects.map(effect=>effect()).filter(f=>typeof f==='function');
  assert.equal(calls.filter(c=>c==='fetch').length,2,'Topic still loads active feed and archive count');
  assert.equal(calls.filter(c=>c==='sse').length,1,'Topic still opens SSE');
  activeCleanup.forEach(f=>f());
  console.log(JSON.stringify({ok:true,checks:['topic switch clears stale context','null topic makes zero fetch/SSE calls','null topic clears UI state','selected topic still fetches and streams'],limit:'Isolated hook/store behavior; not a browser E2E test'}));
})().catch(e=>{console.error(e);process.exitCode=1});
