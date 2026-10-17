"use strict";
const byId = id => document.getElementById(id);
let csrf = "", busy = false, pendingPoll = null;
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
    if(job.status==="DRAFT") actions.append(button("Start offline analysis",()=>mutate(`/api/analysis/jobs/${job.job_id}/start`,{})));
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
  byId("provenance").textContent=`Offline sample · ${data.report.claims.length} validated source facts · Run ${data.run_id} · Model requests: ${data.model_requests}`;
  byId("markdown").textContent=data.markdown;
  byId("download").href=`/api/analysis/jobs/${encodeURIComponent(jobId)}/download`;
  byId("report-panel").hidden=false;
}
async function showReport(jobId) { renderReport(jobId,await request(`/api/analysis/jobs/${jobId}/report`));byId("report-panel").scrollIntoView({block:"start",behavior:"smooth"}); }
async function refresh() {
  const data=await request("/api/analysis");csrf=data.csrf;
  if(!byId("repository").options.length) {
    for(const repo of data.repositories) {const option=element("option",repo.label);option.value=repo.id;byId("repository").append(option);}
    for(const [key,label] of Object.entries(data.questions)) {const option=element("option",label);option.value=key;byId("question").append(option);}
    for(const name of data.repositories[0].files) byId("approved-files").append(element("li",name));
  }
  renderJobs(data.jobs);byId("prepare").disabled=false;
  clearTimeout(pendingPoll);
  if(data.jobs.some(job=>["STARTING","RUNNING","STOPPING"].includes(job.status))) pendingPoll=setTimeout(()=>refresh().catch(failure),350);
}
async function mutate(path,value) {
  if(busy) return;busy=true;byId("error").hidden=true;byId("prepare").disabled=true;
  try {await request(path,value);byId("status").textContent="Saved locally. No model request was made.";await refresh();}
  finally {busy=false;byId("prepare").disabled=false;}
}
byId("prepare").addEventListener("click",()=>mutate("/api/analysis/jobs",{repository:byId("repository").value,question:byId("question").value}).catch(failure));
byId("refresh").addEventListener("click",()=>refresh().catch(failure));
refresh().catch(failure);
