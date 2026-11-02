const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname,'../static/working-sessions.js'),'utf8');
class Element {
  constructor(tag='div'){this.tagName=tag.toUpperCase();this.children=[];this.listeners={};this.hidden=false;this.value='';this._text='';}
  set textContent(v){this._text=String(v);this.children=[];}
  get textContent(){return this._text+this.children.map(x=>x.textContent).join('');}
  set innerHTML(_){throw new Error('Unsafe HTML rendering');}
  append(...items){for(const item of items){item.parent=this;this.children.push(item);}}
  replaceChildren(...items){this.children=[];this.append(...items);}
  addEventListener(name,fn){this.listeners[name]=fn;}
  setAttribute(name,value){this[name]=value;}
  contains(target){for(let p=target;p;p=p.parent)if(p===this)return true;return false;}
  click(){return this.listeners.click?.();}
}
const flush=async()=>{for(let i=0;i<8;i++)await Promise.resolve();};
function boot(session,options={}){
  const ids=Object.fromEntries(['working-session-panel','working-session-list','working-session-status','working-session-scope','create-working-session'].map(x=>[x,new Element()]));
  ids['working-session-panel'].append(ids['working-session-list'],ids['working-session-status'],ids['working-session-scope'],ids['create-working-session']);
  ids['working-session-panel'].hidden=true;ids['working-session-scope'].hidden=true;
  const document={getElementById:id=>ids[id],createElement:tag=>new Element(tag),activeElement:new Element('body')};
  const calls=[];let interval,firstResolve,held=Boolean(options.holdFirst),state=structuredClone(session);
  const response=data=>({ok:true,json:async()=>structuredClone(data)});
  const fetch=async(url,request)=>{
    calls.push({url,request});
    if(!request){
      if(url.endsWith('/scope'))return response({manifest_sha256:'f'.repeat(64),approved:false});
      const data={enabled:true,csrf:'synthetic-csrf',sessions:[state]};
      if(held){held=false;return new Promise(resolve=>{firstResolve=()=>resolve(response(data));});}
      return response(data);
    }
    const value=JSON.parse(request.body);
    assert.equal(request.headers['X-CAS-CSRF'],'synthetic-csrf');
    if(url.endsWith('/tasks'))state.tasks.push({task_id:'synthetic',...value});
    if(url.endsWith('/prepare'))Object.assign(state,{status:'PREPARED',plan_hash:'f'.repeat(64),local_command:"& 'C:/private/python.exe' -m agent_runtime working-session run 'fixed-id'"});
    if(url.endsWith('/cancel')){assert.equal(value.plan_hash,state.plan_hash);state.status='CANCEL_REQUESTED';}
    if(url.endsWith('/end'))state.status='ENDING';
    if(url.endsWith('/run') && options.busyRun)return response({accepted:false,reason:'WORKING_SESSION_BUSY'});
    if(url.endsWith('/run') && options.legacyInput)return response({accepted:false,reason:'WORKING_SESSION_INPUT_REQUIRES_NEW_TASK'});
    return response(state);
  };
  vm.runInNewContext(source,{document,fetch,setInterval:fn=>{interval=fn;return 1;},console});
  function all(root=ids['working-session-panel']){return [root,...root.children.flatMap(x=>all(x))];}
  return {ids,document,calls,all,tick:()=>interval(),resolveFirst:()=>firstResolve(),setState:value=>{state=structuredClone(value);},button:label=>all().find(x=>x.tagName==='BUTTON'&&x.textContent===label)};
}
const draft={session_id:'fixed-id',title:'Work <img onerror=evil>',status:'DRAFT',cleanup:'NOT_STARTED',plan_hash:null,tasks:[],results:[],code:null};
test('text rendering and edit focus survive polling',async()=>{
  const app=boot(draft);await flush();assert.equal(app.ids['working-session-panel'].hidden,false);
  const title=app.all().find(x=>x.tagName==='INPUT');const prompt=app.all().find(x=>x.tagName==='TEXTAREA');
  title.value='Task';prompt.value='<script>synthetic</script>';app.document.activeElement=prompt;
  const before=app.calls.length;app.tick();await flush();assert.equal(app.calls.length,before);assert.equal(prompt.value,'<script>synthetic</script>');
  app.document.activeElement=new Element('body');await app.button('Add task').click();await flush();
  assert.deepEqual(JSON.parse(app.calls.find(x=>x.request).request.body),{title:'Task',prompt:'<script>synthetic</script>'});
  assert.ok(app.ids['working-session-list'].textContent.includes('<script>synthetic</script>'));
});
test('prepare only, scope persists and no remote execution action exists',async()=>{
  const app=boot({...draft,tasks:[{title:'A',prompt:'a'},{title:'B',prompt:'b'}]});await flush();
  await app.button('Freeze plan and show local command').click();await flush();assert.ok(app.ids['working-session-list'].textContent.includes('private/python.exe'));
  await app.button('Show exact scope').click();await flush();assert.equal(app.ids['working-session-scope'].hidden,false);assert.ok(app.ids['working-session-scope'].textContent.includes('false'));
  assert.ok(!app.calls.some(x=>/\/(run|login|approve|restart)$/.test(x.url)));
});
test('cancel is one bounded intent and result text is inert',async()=>{
  const app=boot({...draft,status:'RUNNING',plan_hash:'a'.repeat(64),tasks:[{title:'A',prompt:'a'},{title:'B',prompt:'b'}],results:[{stage:'first',result:'PASS',text:'<script>never execute</script>'}]});await flush();
  const button=app.button('Cancel remaining work');const first=button.click();button.click();await first;await flush();
  assert.equal(app.calls.filter(x=>x.url.endsWith('/cancel')).length,1);assert.ok(app.ids['working-session-list'].textContent.includes('CANCEL_REQUESTED'));
  assert.ok(app.ids['working-session-list'].textContent.includes('<script>never execute</script>'));
});
test('stale polling response cannot roll completed history back',async()=>{
  const app=boot(draft,{holdFirst:true});app.setState({...draft,status:'COMPLETED',cleanup:'CONFIRMED'});app.tick();await flush();app.resolveFirst();await flush();
  assert.ok(app.ids['working-session-list'].textContent.includes('COMPLETED'));assert.ok(!app.button('Add task'));
});
test('one task can freeze and zero or three cannot',async()=>{
  for(const count of [0,1,3]) {
    const tasks=Array.from({length:count},(_,i)=>({title:String(i),prompt:'synthetic '+i}));
    const app=boot({...draft,tasks});await flush();
    assert.equal(Boolean(app.button('Freeze plan and show local command')),count===1);
    if(count===1){await app.button('Freeze plan and show local command').click();await flush();assert.ok(app.ids['working-session-list'].textContent.includes('Prepared hash:'));assert.equal(app.calls.filter(x=>x.url.endsWith('/prepare')).length,1);}
    assert.ok(!app.calls.some(x=>/\/(run|login|approve|restart)$/.test(x.url)));
  }
});
test('second genuine task can still be added before freeze',async()=>{
  const app=boot({...draft,tasks:[{title:'One',prompt:'synthetic one'}]});await flush();
  assert.ok(app.button('Add task'));assert.ok(app.button('Freeze plan and show local command'));
  app.all().find(x=>x.tagName==='INPUT').value='Second';app.all().find(x=>x.tagName==='TEXTAREA').value='synthetic second';
  await app.button('Add task').click();await flush();assert.ok(!app.button('Add task'));assert.ok(app.button('Freeze plan and show local command'));
  assert.equal(app.calls.filter(x=>x.url.endsWith('/tasks')).length,1);
});
test('local owner can run a frozen task once from its card',async()=>{
  const app=boot({...draft,status:'PREPARED',local_auth_mode:true,plan_hash:'a'.repeat(64),local_command:'local command',tasks:[{title:'A',prompt:'a'}]});
  await flush();const button=app.button('Run task');assert.ok(button);
  const first=button.click();button.click();await first;await flush();
  assert.equal(app.calls.filter(x=>x.url.endsWith('/run')).length,1);
  assert.deepEqual(JSON.parse(app.calls.find(x=>x.url.endsWith('/run')).request.body),{plan_hash:'a'.repeat(64)});
});
test('missing result is explained without suggesting an automatic retry',async()=>{
  const app=boot({...draft,status:'FAILED',code:'WORKING_SESSION_RESULT_UNAVAILABLE'});await flush();
  assert.ok(app.ids['working-session-list'].textContent.includes('no usable result was saved'));
  assert.ok(app.ids['working-session-list'].textContent.includes('will not run again automatically'));
});
test('a busy owner is explained without presenting the task as started',async()=>{
  const app=boot({...draft,status:'PREPARED',local_auth_mode:true,plan_hash:'a'.repeat(64),local_command:'local command',tasks:[{title:'A',prompt:'a'}]},{busyRun:true});
  await flush();await app.button('Run task').click();await flush();
  assert.ok(app.ids['working-session-status'].textContent.includes('Another session is running'));
  assert.equal(app.calls.filter(x=>x.url.endsWith('/run')).length,1);
});
test('legacy task requiring replacement is explained',async()=>{
  const app=boot({...draft,status:'PREPARED',local_auth_mode:true,plan_hash:'a'.repeat(64),local_command:'local command',tasks:[{title:'A',prompt:'a'}]},{legacyInput:true});
  await flush();await app.button('Run task').click();await flush();
  assert.ok(app.ids['working-session-status'].textContent.includes('Create a new task without credentials'));
});
