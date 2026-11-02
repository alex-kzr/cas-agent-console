/* Actual product UI -> pipe-only transport -> actual Python Handler/store/backend. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const readline = require('node:readline');
const vm = require('node:vm');
let sequence=0;
const pending=new Map();
readline.createInterface({input:process.stdin}).on('line',line=>{
  const response=JSON.parse(line),entry=pending.get(response.id);
  if(!entry)return;
  pending.delete(response.id);
  response.error?entry.reject(new Error(response.error)):entry.resolve(response.value);
});
function rpc(op,value={}) {
  const id=++sequence;
  return new Promise((resolve,reject)=>{pending.set(id,{resolve,reject});process.stdout.write(JSON.stringify({id,op,...value})+'\n');});
}
class Element {
  constructor(tag='div'){this.tagName=tag.toUpperCase();this.children=[];this.listeners={};this.hidden=false;this.value='';this._text='';}
  set textContent(value){this._text=String(value);this.children=[];}
  get textContent(){return this._text+this.children.map(x=>x.textContent).join('');}
  set innerHTML(_){throw new Error('UNSAFE_HTML');}
  append(...items){for(const item of items){item.parent=this;this.children.push(item);}}
  replaceChildren(...items){this.children=[];this.append(...items);}
  addEventListener(name,fn){this.listeners[name]=fn;}
  setAttribute(name,value){this[name]=value;}
  contains(target){for(let p=target;p;p=p.parent)if(p===this)return true;return false;}
  click(){return this.listeners.click?.();}
}
const source=fs.readFileSync(process.argv[2],'utf8');
function boot() {
  const ids=Object.fromEntries(['working-session-panel','working-session-list','working-session-status','working-session-scope','create-working-session'].map(x=>[x,new Element()]));
  ids['working-session-panel'].append(...Object.values(ids).filter(x=>x!==ids['working-session-panel']));
  const document={getElementById:id=>ids[id],createElement:tag=>new Element(tag),activeElement:new Element('body')};
  let interval;
  const inflight=new Set(),calls=[];
  const fetch=(path,request)=>{
    calls.push({path,method:request?.method||'GET'});
    const result=rpc('http',{path,method:request?.method||'GET',body:request?.body||'',headers:request?.headers||{}}).then(value=>({ok:value.status>=200&&value.status<300,status:value.status,json:async()=>value.body}));
    inflight.add(result);result.finally(()=>inflight.delete(result));return result;
  };
  vm.runInNewContext(source,{document,fetch,setInterval:fn=>{interval=fn;return 1;},console});
  function all(root=ids['working-session-panel']){return[root,...root.children.flatMap(x=>all(x))];}
  async function drain(){for(let round=0;round<12;round++){await Promise.all([...inflight]);await Promise.resolve();}assert.equal(inflight.size,0);}
  return {ids,calls,all,drain,text:()=>ids['working-session-list'].textContent,button:label=>all().find(x=>x.tagName==='BUTTON'&&x.textContent===label),refresh:async()=>{interval();await drain();}};
}
async function activeCase(mode,when,action='Cancel remaining work',cleanupFailure=false){
  const setup=await rpc('setup',{mode,cleanupFailure});
  let app=boot();await app.drain();
  assert.ok(app.text().includes('PREPARED'));
  await rpc('start');await app.refresh();assert.ok(app.text().includes('First offline result'));
  assert.deepEqual(await rpc('guard_checks'),{rejected:4,state_unchanged:true});
  if(when!=='before_second')await rpc('start_second');
  if(when==='completion_race')await rpc('complete_second');
  const activeSnapshot=await rpc('snapshot');
  await rpc('reopen');app=boot();await app.drain();
  assert.equal((await rpc('snapshot')).synthetic_queries,activeSnapshot.synthetic_queries);
  assert.ok(app.text().includes('RUNNING'));
  await app.refresh();
  const button=app.button(action);assert.ok(button,action);
  const click=button.click();button.click();await click;await app.drain();
  const route=action==='End session'?'/end':'/cancel';
  assert.equal(app.calls.filter(x=>x.path.endsWith(route)).length,1,'duplicate click must send one intent');
  const pendingState=await rpc('snapshot');
  assert.ok(['CANCEL_REQUESTED','ENDING'].includes(pendingState.status));
  assert.equal(pendingState.intent_matches_plan,true);
  assert.ok(app.text().includes(pendingState.status));
  await rpc('enter_cleanup');await app.refresh();
  assert.equal((await rpc('snapshot')).cleanup,'PENDING');
  assert.ok(app.text().includes('First offline result'));
  await rpc('settle');
  const done=await rpc('snapshot');await app.refresh();
  const expected=cleanupFailure?'INTERRUPTED':when==='completion_race'?'COMPLETED':'CANCELLED';
  assert.equal(done.status,expected);assert.ok(app.text().includes(expected));
  assert.equal(done.cleanup,cleanupFailure?'UNCONFIRMED':'CONFIRMED');
  assert.equal(done.synthetic_queries,when==='before_second'?1:2);
  assert.equal(done.results,when==='completion_race'?2:1);
  assert.ok(app.text().includes('First offline result'));
  assert.equal(app.button('Cancel remaining work'),undefined);
  // A stale button after completion must not restart work or corrupt terminal history.
  await button.click();await app.drain();assert.equal((await rpc('snapshot')).status,expected);
  await rpc('reopen');app=boot();await app.drain();assert.ok(app.text().includes(expected));
  const replay=await rpc('try_replay');assert.equal(replay.blocked,true);
  const final=await rpc('snapshot');assert.equal(final.synthetic_queries,done.synthetic_queries);assert.equal(final.backend_runs,1);
  await rpc('record_case',{caseName:mode,expected,when,action,duplicate_posts:1});
}
async function main(){
  await activeCase('cancel-before-second','before_second');
  await activeCase('cancel-during-second','during_second');
  await activeCase('completion-wins-late-cancel','completion_race');
  await activeCase('end-during-second','during_second','End session');
  await activeCase('cancel-cleanup-unconfirmed','during_second','Cancel remaining work',true);
  for(const prepared of [false,true]){
    await rpc('setup',{mode:prepared?'end-prepared':'end-draft',draft:!prepared});
    const app=boot();await app.drain();
    await app.button('End session').click();await app.drain();
    const state=await rpc('snapshot');assert.equal(state.status,'CLOSED');assert.equal(state.synthetic_queries,0);assert.equal(state.claim_exists,false);
    await rpc('reopen');await app.refresh();assert.ok(app.text().includes('CLOSED'));
    assert.equal((await rpc('try_replay')).blocked,true);
    await rpc('record_case',{caseName:prepared?'end-prepared':'end-draft',expected:'CLOSED'});
  }
  await rpc('finish');process.stdin.destroy();
}
main().catch(async error=>{process.stderr.write(error.stack+'\n');try{await rpc('failed',{message:error.message});}catch(_){}process.stdin.destroy();process.exitCode=1;});
