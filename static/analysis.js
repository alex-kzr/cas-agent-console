"use strict";
const byId = id => document.getElementById(id);
const TERMINAL = new Set(["COMPLETED","FAILED","CANCELLED","INTERRUPTED"]);
const ACTIVE = new Set(["STARTING","RUNNING","STOPPING"]);
// selectSeq is one generation for report AND preview selections: the newest selection of either kind wins.
// unreconciled: a mutation's outcome is unknown and no state read has succeeded since; mutations stay locked.
let csrf = "", busy = false, unreconciled = false, pendingPoll = null, refreshSeq = 0, selectSeq = 0, previewJob = null;
const fileSelections=[], known=new Map();
const element = (tag, text, className) => { const el = document.createElement(tag); if (text != null) el.textContent = text; if(className) el.className=className; return el; };
async function request(path, value) {
  const response = await fetch(path, value === undefined ? {} : {method:"POST",headers:{"Content-Type":"application/json","X-CAS-CSRF":csrf},body:JSON.stringify(value)});
  let data;
  try { data = await response.json(); } catch (error) { throw new Error("Analysis request failed"); }
  if (!response.ok) throw new Error(data.error || "Analysis request failed"); // an error status does not prove nothing was applied
  return data;
}
function guard() { if (unreconciled) throw new Error("The last change is unconfirmed and the state could not be read. Press Refresh; nothing was retried."); }
function failure(error) { byId("error").textContent=error.message; byId("error").hidden=false; }
function button(text, action, className) { const el=element("button",text,className); el.addEventListener("click",()=>action().catch(failure)); return el; }
// A terminal state is final: a late non-terminal view of the same job never replaces it.
function settle(job) {
  const seen=known.get(job.job_id);
  if(seen && TERMINAL.has(seen.status) && !TERMINAL.has(job.status)) return seen;
  known.set(job.job_id,job);return job;
}
function renderJobs(jobs) {
  const target=byId("jobs"); target.replaceChildren();
  if(!jobs.length) target.append(element("p","No analysis yet."));
  for(const job of [...jobs].reverse()) {
    const card=element("article",null,"job"); card.append(element("p",job.status,"badge"),element("p",job.question),element("p",job.run_id || "Prepared — not started","muted"));
    const actions=element("div",null,"actions");
    if(job.status==="DRAFT" && job.mode!=="sdk") actions.append(button("Start offline analysis",()=>mutate(`/api/analysis/jobs/${job.job_id}/start`,{})));
    if(job.mode==="sdk") actions.append(button("Review SDK payload",()=>showPreview(job.job_id),"secondary"));
    if(job.status==="RUNNING") actions.append(button("Stop",()=>stop(job.job_id),"secondary"));
    if(job.status==="COMPLETED") actions.append(button("Open report",()=>showReport(job.job_id),"secondary"));
    if(job.run_id) { const link=element("a","Execution history ↗");link.href="/";actions.append(link); }
    if(job.recovery) card.append(element("p",job.recovery,"muted"));
    if(job.status==="FAILED" || job.status==="INTERRUPTED" || job.status==="CANCELLED") card.append(element("p","No accepted report. Source snapshots and run status remain available; this run will not replay.","muted"));
    card.append(actions);target.append(card);
  }
}
function renderReport(jobId,data) {
  byId("claims").replaceChildren();
  const findings=data.report.report_version===2, items=findings ? data.report.findings : data.report.claims;
  for(const item of items) {
    const card=element("article",null,"claim");
    if(findings) {
      card.append(element("strong",item.id),element("p",`Problem: ${item.problem}`),element("p",`Impact: ${item.impact}`),element("p",`Suggested fix: ${item.suggested_fix}`));
      const link=element("a",`${item.file}:${item.line} · selected snapshot`);link.href=`/api/analysis/jobs/${encodeURIComponent(jobId)}/files/${encodeURIComponent(item.file)}#L${item.line}`;card.append(link);
    } else {
      card.append(element("strong",item.id),element("p",item.value));
      const link=element("a",`${item.file}:${item.line} · verified snapshot`);link.href=`/api/analysis/jobs/${encodeURIComponent(jobId)}/files/${encodeURIComponent(item.file)}#L${item.line}`;card.append(link);
    }
    byId("claims").append(card);
  }
  if(findings && !items.length) byId("claims").append(element("p","No findings reported. This is not proof that the selected files are correct.","claim"));
  const subject=findings ? (items.length ? `${items.length} bounded findings (file, line and hash are checked; the prose is screened, not verified as correct)` : "No findings reported (not proof of correctness)") : `${items.length} validated source facts`;
  byId("provenance").textContent=`${data.mode || "offline"} sample / ${subject} / Run ${data.run_id} / Recorded queries: ${data.model_requests} / Model requests: ${data.real_model_requests===null ? "unverified" : (data.real_model_requests ?? data.model_requests)}`;
  byId("markdown").textContent=data.markdown;
  byId("download").href=`/api/analysis/jobs/${encodeURIComponent(jobId)}/download`;
  byId("report-panel").hidden=false;
}
// Only the newest request of a kind may render, or report an error; older answers are ignored.
// Ignoring an answer is local bookkeeping: it is not provider cancellation.
async function showReport(jobId) {
  const seq=++selectSeq;
  invalidatePreview(); // Selecting a report drops any shown preview, so no old start action stays valid.
  let data;
  try { data=await request(`/api/analysis/jobs/${jobId}/report`); } catch (error) { if(seq!==selectSeq) return; throw error; }
  if(seq!==selectSeq) return;
  renderReport(jobId,data);byId("report-panel").scrollIntoView({block:"start",behavior:"smooth"});
}
// Drops the shown preview and its consent. A pending preview fetch is cancelled by a new selection, not here.
function invalidatePreview() {
  previewJob=null;
  const panel=byId("sdk-preview");panel.replaceChildren();panel.hidden=true;
}
async function showPreview(jobId) {
  const seq=++selectSeq;
  invalidatePreview();
  let data;
  try { data=await request(`/api/analysis/jobs/${jobId}/preview`); } catch (error) { if(seq!==selectSeq) return; throw error; }
  if(seq!==selectSeq) return;
  const panel=byId("sdk-preview");panel.replaceChildren();panel.hidden=false;
  const context={jobId,snapshot:data.snapshot_sha256,profile:(known.get(jobId)||{}).profile};
  previewJob=context;
  panel.append(element("h2","SDK payload preview"),element("p",data.live_enabled ? "Separate approval required for this exact payload." : "Live gate closed. No SDK, model or authentication call is available."),element("p",`${data.model} / ${data.recipient} / ${data.limits.max_turns} turn / SDK budget threshold $${data.limits.max_budget_usd} / ${data.limits.timeout_seconds}s execution timeout`),element("pre",data.query_text));
  const live=element("input"),login=element("input");live.type=login.type="checkbox";live.checked=login.checked=false;
  const first=element("label","Authorize this exact synthetic payload and model request ");first.append(live);
  const second=element("label","Authorize existing subscription login reuse for this run ");second.append(login);
  const start=button("Start approved SDK analysis",async()=>{
    if(busy) return;
    const job=known.get(jobId);
    // Consent is bound to this preview, job, profile and snapshot; anything changed means approve again.
    if(previewJob!==context || !job || job.status!=="DRAFT" || job.snapshot_sha256!==data.snapshot_sha256 || job.profile!==context.profile) throw new Error("Preview is out of date. Reopen it and approve again.");
    guard(); // A locked page keeps the consent: nothing is sent and nothing is consumed.
    const body={allow_live:live.checked===true,allow_existing_login:login.checked===true,snapshot_sha256:data.snapshot_sha256};
    invalidatePreview(); // Consents are single use, even when the request fails.
    return mutate(`/api/analysis/jobs/${jobId}/start`,body);
  });
  start.disabled=true;const update=()=>{start.disabled=!data.live_enabled || !live.checked || !login.checked;};live.addEventListener("change",update);login.addEventListener("change",update);
  panel.append(first,second,start);panel.scrollIntoView({block:"start",behavior:"smooth"});
}
function apply(data) {
  csrf=data.csrf;
  if(!byId("repository").options.length) {
    for(const repo of data.repositories) {const option=element("option",repo.label);option.value=repo.id;byId("repository").append(option);}
    for(const [key,label] of Object.entries(data.questions)) {const option=element("option",label);option.value=key;byId("question").append(option);}
    for(const name of data.repositories[0].files) {const item=element("li"),label=element("label",name+" "),input=element("input");input.type="checkbox";input.checked=true;fileSelections.push({name,input});label.append(input);item.append(label);byId("approved-files").append(item);}
  }
  const jobs=data.jobs.map(settle);
  if(previewJob) {
    const job=known.get(previewJob.jobId);
    if(!job || job.status!=="DRAFT" || job.snapshot_sha256!==previewJob.snapshot || job.profile!==previewJob.profile) invalidatePreview();
  }
  if(unreconciled) { // A trustworthy state read is the only thing that unlocks mutations.
    unreconciled=false;byId("error").hidden=true;byId("status").textContent="State was read again; actions are available. Nothing was retried.";
  }
  renderJobs(jobs);byId("prepare").disabled=busy;
  clearTimeout(pendingPoll);pendingPoll=null;
  if(jobs.some(job=>ACTIVE.has(job.status))) pendingPoll=setTimeout(poll,350);
}
function poll() {
  pendingPoll=null;
  if(busy) { pendingPoll=setTimeout(poll,350);return; }
  refresh().catch(failure);
}
// Only the newest refresh may apply its result or its error.
async function refresh() {
  const seq=++refreshSeq;let data;
  try { data=await request("/api/analysis"); } catch (error) { if(seq!==refreshSeq) return; throw error; }
  if(seq!==refreshSeq) return;
  apply(data);
}
// One mutation at a time. The outcome is never retried: after success or failure the state is re-read.
// If the answer is missing or the re-read fails, mutations stay locked until a later read succeeds.
async function mutate(path,value,done) {
  if(busy) return;
  guard();
  busy=true;byId("error").hidden=true;byId("prepare").disabled=true;
  let failed=null;
  try { await request(path,value); } catch (error) { failed=error; }
  unreconciled=true; // Any answer, even an error status, may follow an applied change; only a successful state read unlocks.
  refreshSeq++; // A refresh that began before this answer may predate the change.
  try { await refresh(); } catch (error) { failed=failed||error; }
  finally { busy=false;byId("prepare").disabled=unreconciled; }
  if(failed) {
    byId("status").textContent=unreconciled ? "The request did not complete as expected and the state could not be read. Actions are locked until Refresh succeeds; nothing was retried."
      : "The request did not complete as expected. State was re-read and nothing was retried.";
    throw failed;
  }
  byId("status").textContent=done || "Saved locally. Inspect run provenance for execution details.";
}
async function stop(jobId) {
  try { await mutate(`/api/analysis/jobs/${jobId}/stop`,{},"Stop requested locally. The final state comes from the run record; provider-side cancellation is not claimed."); }
  catch (error) {
    // A run that already finished wins over a late stop; its rejection is not an error.
    const job=known.get(jobId);
    if(job && TERMINAL.has(job.status)) { byId("error").hidden=true;byId("status").textContent=`Run already ${job.status}; the stop had no effect.`;return; }
    throw error;
  }
  const job=known.get(jobId);
  if(job && job.status==="COMPLETED") byId("status").textContent="Run completed; the stop had no effect.";
}
function syncMode() {
  const review=byId("question").value==="review";
  if(review) byId("mode").value="sdk";
  for(const option of byId("mode").options || []) if(option.value==="offline") option.disabled=review;
}
byId("question").addEventListener("change",syncMode);
byId("prepare").addEventListener("click",()=>{syncMode();return mutate("/api/analysis/jobs",{repository:byId("repository").value,question:byId("question").value,mode:byId("mode").value,files:fileSelections.filter(item=>item.input.checked).map(item=>item.name)}).catch(failure);});
byId("refresh").addEventListener("click",()=>refresh().catch(failure));
refresh().catch(failure);
