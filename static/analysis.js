"use strict";
const byId = id => document.getElementById(id);
let csrf = "", busy = false, pendingPoll = null;
const fileSelections=[];
const element = (tag, text, className) => { const el = document.createElement(tag); if (text != null) el.textContent = text; if(className) el.className=className; return el; };
async function request(path, value) {
  const response = await fetch(path, value === undefined ? {} : {method:"POST",headers:{"Content-Type":"application/json","X-CAS-CSRF":csrf},body:JSON.stringify(value)});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Analysis request failed");
  return data;
}
function failure(error) { byId("error").textContent=error.message; byId("error").hidden=false; }
function button(text, action, className) { const el=element("button",text,className); el.addEventListener("click",()=>action().catch(failure)); return el; }
function renderJobs(jobs) {
  const target=byId("jobs"); target.replaceChildren();
  if(!jobs.length) target.append(element("p","No analysis yet."));
  for(const job of [...jobs].reverse()) {
    const card=element("article",null,"job"); card.append(element("p",job.status,"badge"),element("p",job.question),element("p",job.run_id || "Prepared — not started","muted"));
    const actions=element("div",null,"actions");
    if(job.status==="DRAFT" && job.mode!=="sdk") actions.append(button("Start offline analysis",()=>mutate(`/api/analysis/jobs/${job.job_id}/start`,{})));
    if(job.mode==="sdk") actions.append(button("Review SDK payload",()=>showPreview(job.job_id),"secondary"));
    if(job.status==="RUNNING") actions.append(button("Stop",()=>mutate(`/api/analysis/jobs/${job.job_id}/stop`,{}),"secondary"));
    if(job.status==="COMPLETED") actions.append(button("Open report",()=>showReport(job.job_id),"secondary"));
    if(job.run_id) { const link=element("a","Execution history ↗");link.href="/";actions.append(link); }
    if(job.recovery) card.append(element("p",job.recovery,"muted"));
    if(job.status==="FAILED" || job.status==="INTERRUPTED" || job.status==="CANCELLED") card.append(element("p","No accepted report. Source snapshots and run status remain available; this run will not replay.","muted"));
    card.append(actions);target.append(card);
  }
}
function renderReport(jobId,data) {
  byId("claims").replaceChildren();
  for(const claim of data.report.claims) {
    const card=element("article",null,"claim");card.append(element("strong",claim.id),element("p",claim.value));
    const link=element("a",`${claim.file}:${claim.line} · verified snapshot`);link.href=`/api/analysis/jobs/${encodeURIComponent(jobId)}/files/${encodeURIComponent(claim.file)}#L${claim.line}`;card.append(link);byId("claims").append(card);
  }
  byId("provenance").textContent=`${data.mode || "offline"} sample / ${data.report.claims.length} validated source facts / Run ${data.run_id} / Recorded queries: ${data.model_requests} / Model requests: ${data.real_model_requests===null ? "unverified" : (data.real_model_requests ?? data.model_requests)}`;
  byId("markdown").textContent=data.markdown;
  byId("download").href=`/api/analysis/jobs/${encodeURIComponent(jobId)}/download`;
  byId("report-panel").hidden=false;
}
async function showReport(jobId) { renderReport(jobId,await request(`/api/analysis/jobs/${jobId}/report`));byId("report-panel").scrollIntoView({block:"start",behavior:"smooth"}); }
async function showPreview(jobId) {
  const data=await request(`/api/analysis/jobs/${jobId}/preview`), panel=byId("sdk-preview");panel.replaceChildren();panel.hidden=false;
  panel.append(element("h2","SDK payload preview"),element("p",data.live_enabled ? "Separate approval required for this exact payload." : "Live gate closed. No SDK, model or authentication call is available."),element("p",`${data.model} / ${data.recipient} / ${data.limits.max_turns} turn / SDK budget threshold $${data.limits.max_budget_usd} / ${data.limits.timeout_seconds}s execution timeout`),element("pre",data.query_text));
  const live=element("input"),login=element("input");live.type=login.type="checkbox";live.checked=login.checked=false;
  const first=element("label","Authorize this exact synthetic payload and model request ");first.append(live);
  const second=element("label","Authorize existing subscription login reuse for this run ");second.append(login);
  const start=button("Start approved SDK analysis",()=>mutate(`/api/analysis/jobs/${jobId}/start`,{allow_live:live.checked===true,allow_existing_login:login.checked===true,snapshot_sha256:data.snapshot_sha256}));
  start.disabled=true;const update=()=>{start.disabled=!data.live_enabled || !live.checked || !login.checked;};live.addEventListener("change",update);login.addEventListener("change",update);
  panel.append(first,second,start);panel.scrollIntoView({block:"start",behavior:"smooth"});
}
async function refresh() {
  const data=await request("/api/analysis");csrf=data.csrf;
  if(!byId("repository").options.length) {
    for(const repo of data.repositories) {const option=element("option",repo.label);option.value=repo.id;byId("repository").append(option);}
    for(const [key,label] of Object.entries(data.questions)) {const option=element("option",label);option.value=key;byId("question").append(option);}
    for(const name of data.repositories[0].files) {const item=element("li"),label=element("label",name+" "),input=element("input");input.type="checkbox";input.checked=true;fileSelections.push({name,input});label.append(input);item.append(label);byId("approved-files").append(item);}
  }
  renderJobs(data.jobs);byId("prepare").disabled=false;
  clearTimeout(pendingPoll);
  if(data.jobs.some(job=>["STARTING","RUNNING","STOPPING"].includes(job.status))) pendingPoll=setTimeout(()=>refresh().catch(failure),350);
}
async function mutate(path,value) {
  if(busy) return;busy=true;byId("error").hidden=true;byId("prepare").disabled=true;
  try {await request(path,value);byId("status").textContent="Saved locally. Inspect run provenance for execution details.";await refresh();}
  finally {busy=false;byId("prepare").disabled=false;}
}
byId("prepare").addEventListener("click",()=>mutate("/api/analysis/jobs",{repository:byId("repository").value,question:byId("question").value,mode:byId("mode").value,files:fileSelections.filter(item=>item.input.checked).map(item=>item.name)}).catch(failure));
byId("refresh").addEventListener("click",()=>refresh().catch(failure));
refresh().catch(failure);
