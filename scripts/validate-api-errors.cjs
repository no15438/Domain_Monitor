// Execute the real API helper; verify safe retries and readable server errors.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const ts = require(path.join(root, 'frontend/node_modules/typescript'));
let handler, calls = 0;
const toasts = [];
const code = ts.transpileModule(fs.readFileSync(path.join(root, 'frontend/src/lib/api/shared.ts'), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 }
}).outputText;
const moduleValue = {exports:{}};
vm.runInNewContext(code, {exports:moduleValue.exports, module:moduleValue, process:{env:{}},
  fetch:async(...args)=>{calls++;return handler(...args);},
  setTimeout:resolve=>resolve(), console,
  require:()=>({useStore:{getState:()=>({addToast:(message,level)=>toasts.push({message,level})})}})});
const {fetchWithRetry,safeJson}=moduleValue.exports;
const unavailable=()=>new Response(JSON.stringify({detail:'本地模式尚未启用 AI 服务'}),{status:503,headers:{'content-type':'application/json'}});
(async()=>{
  handler=unavailable;
  const result=await fetchWithRetry('/api/chat/tasks',{method:'POST'});
  assert.equal(calls,1,'Mutating actions must never retry automatically');
  const error=await safeJson(result,{status:'error',message:'Fallback'});
  assert.match(error.message,/本地模式/);
  assert.match(toasts[0].message,/本地模式/);
  calls=0;
  handler=()=>calls===1?unavailable():new Response('{}',{status:200});
  assert.equal((await fetchWithRetry('/api/topics')).status,200);
  assert.equal(calls,2);
  calls=0;handler=unavailable;
  await assert.rejects(()=>fetchWithRetry('/api/topics'),/本地模式/);
  assert.equal(calls,3,'Exhausted reads must report failure instead of an empty topic list');
  calls=0;handler=()=>{throw Error('Connection lost');};
  await assert.rejects(()=>fetchWithRetry('/api/chat/tasks',{method:'POST'}),/Connection lost/);
  assert.equal(calls,1,'Failed POST transport must not duplicate tasks');
  console.log(JSON.stringify({ok:true,checks:['POST never retried','server detail reaches toast','GET retries transient failure','exhausted GET throws server detail','POST network failure never retried']}));
})().catch(error=>{console.error(error);process.exitCode=1;});
