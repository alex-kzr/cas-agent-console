/* Finite text tasks. No remote execution, auth URL, credential or approval endpoint. */
(() => {
  'use strict';
  const panel = document.getElementById('working-session-panel');
  if (!panel) return;
  const list = document.getElementById('working-session-list');
  const status = document.getElementById('working-session-status');
  let csrf = null, busy = false, refreshSequence = 0;
  const node = (tag, text, cls) => { const e = document.createElement(tag); if (text !== undefined) e.textContent = text; if (cls) e.className = cls; return e; };
  async function post(path, value) {
    const response = await fetch(path, {method:'POST',headers:{'Content-Type':'application/json','X-CAS-CSRF':csrf},body:JSON.stringify(value)});
    if (!response.ok) throw new Error('Action rejected. Refresh the session; do not retry a consumed run.');
    return response.json();
  }
  function action(label, fn) {
    const b=node('button',label); b.type='button';
    b.addEventListener('click', async () => { if(busy)return;busy=true;b.disabled=true;
      try { const reply=await fn();status.textContent=reply?.reason==='WORKING_SESSION_BUSY' ? 'Another session is running. Wait for it to finish, then run this task.' : reply?.reason==='WORKING_SESSION_INPUT_REQUIRES_NEW_TASK' ? 'This older task cannot be run as saved. Create a new task without credentials.' : 'Saved. Status updates appear below.'; }
      catch (_) { status.textContent='Action rejected or outcome uncertain. Refresh; never replay a consumed run.'; }
      finally { busy=false;b.disabled=false;await refresh(); }
    }); return b;
  }
  function render(session) {
    const card=node('article',undefined,'card');card.append(node('h3',session.title),node('p',`${session.status} · cleanup ${session.cleanup}`));
    for(const task of session.tasks) card.append(node('h4',task.title),node('pre',task.prompt));
    for(const result of session.results) card.append(node('h4',`${result.stage}: ${result.result}`),node('pre',result.text));
    const base='/api/working-sessions/'+encodeURIComponent(session.session_id);
    if(session.status==='DRAFT' && session.tasks.length<2) {
      const title=node('input');title.maxLength=80;title.placeholder='Task title';title.setAttribute('aria-label','Task title');
      const prompt=node('textarea');prompt.maxLength=2048;prompt.placeholder='Non-sensitive text task (UTF-8 limit 2048 bytes)';prompt.setAttribute('aria-label','Task instructions');
      card.append(title,prompt,action('Add task',()=>post(base+'/tasks',{title:title.value,prompt:prompt.value})));
    }
    if(session.status==='DRAFT' && session.tasks.length>=1 && session.tasks.length<=2)card.append(action('Freeze plan and show local command',()=>post(base+'/prepare',{})));
    if(session.status==='PREPARED') {
      card.append(node('p','Prepared hash: '+session.plan_hash),node('p',session.local_auth_mode ? 'Use the configured local owner account. The temporary profile is removed after the session.' : 'Review scope and obtain one exact approval before using this command. One private login; detach Ctrl-P then Ctrl-Q after CAS_LOGIN_READY.'),node('pre',session.local_command));
      if(session.local_auth_mode)card.append(action('Run task',()=>post(base+'/run',{plan_hash:session.plan_hash})));
      card.append(action('Show exact scope',async()=>{const response=await fetch(base+'/scope');if(!response.ok)throw new Error();const scope=document.getElementById('working-session-scope');scope.textContent=JSON.stringify(await response.json(),null,2);scope.hidden=false;}));
    }
    if(['DRAFT','PREPARED','STARTING','LOGIN_REQUIRED','RUNNING','CANCEL_REQUESTED','ENDING'].includes(session.status)) {
      card.append(action('End session',()=>post(base+'/end',{plan_hash:session.plan_hash})));
      if(['STARTING','LOGIN_REQUIRED','RUNNING'].includes(session.status))card.append(action('Cancel remaining work',()=>post(base+'/cancel',{plan_hash:session.plan_hash})));
    }
    if(session.code)card.append(node('p',session.code==='WORKING_SESSION_RESULT_UNAVAILABLE' ? 'The provider reported success, but no usable result was saved. The attempt will not run again automatically.' : session.code));
    if(session.launch_error)card.append(node('p',session.launch_error));
    return card;
  }
  async function refresh() {
    if(panel.contains(document.activeElement) && ['INPUT','TEXTAREA'].includes(document.activeElement.tagName))return;
    const sequence=++refreshSequence;
    try {const response=await fetch('/api/working-sessions');if(!response.ok)return;const data=await response.json();if(!data.enabled)return;
      if(sequence!==refreshSequence || busy)return;
      csrf=data.csrf;panel.hidden=false;list.replaceChildren(...data.sessions.map(render));
    } catch (_) {status.textContent='Session state unavailable. Refresh before taking another action.';}
  }
  document.getElementById('create-working-session').addEventListener('click', async()=>{if(busy)return;busy=true;
    try {await post('/api/working-sessions',{title:'Working session'});}catch(_){status.textContent='Session creation rejected.';}finally{busy=false;await refresh();}
  });
  refresh();setInterval(()=>{if(!busy)refresh();},1500);
})();
