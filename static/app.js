"use strict";
const $ = id => document.getElementById(id);
let records = [], selected = new Set(), events = [], currentRun = null, nextSeq = 0, selectionEpoch = 0;
let historyLoading = false;
const eventRequests = new Set();
const label = run => run.scenario_id || "Manual task";
const pretty = data => data == null ? "Unavailable — no evidence recorded" : JSON.stringify(data, null, 2);
function node(tag, text, className) { const el = document.createElement(tag); if (text != null) el.textContent = text; if (className) el.className = className; return el; }
async function api(path) { const response = await fetch(path, {cache:"no-store"}); const data = await response.json(); if (!response.ok) throw new Error(data.error || "Unable to read local evidence"); return data; }
function fail(error) { $("error").textContent = error.message; $("error").hidden = false; }
function warnings(id, messages) { $(id).replaceChildren(...messages.map(message => node("p", message, "warning"))); }
function renderRuns() {
  const visible = records.filter(run => $("filter").value === "all" || run.kind === $("filter").value);
  $("runs").replaceChildren(); $("empty").hidden = visible.length > 0;
  $("count").textContent = `${visible.length} loaded executions`;
  for (const run of visible) {
    const row = node("tr"), title = node("td"), button = node("button", label(run));
    button.addEventListener("click", () => inspect(run.run_id).catch(fail)); title.append(button, node("small", run.run_id.slice(0, 18) + "…"));
    const status = node("td"); status.append(node("span", run.status, `badge ${run.status}`));
    const check = node("input"); check.type = "checkbox"; check.checked = selected.has(run.run_id); check.setAttribute("aria-label", `Compare ${run.run_id}`);
    check.addEventListener("change", () => { if (check.checked) selected.add(run.run_id); else selected.delete(run.run_id); $("compare").disabled = selected.size !== 2; });
    const compare = node("td"); compare.append(check);
    const duration = run.usage?.application?.duration_ms;
    row.append(title, node("td", run.kind), status, node("td", new Date(run.started_at || run.created_at).toLocaleString()), node("td", duration == null ? "Unknown" : `${duration} ms`), compare);
    $("runs").append(row);
  }
  $("completed").textContent = records.filter(run => run.status === "COMPLETED").length;
  $("attention").textContent = records.filter(run => ["FAILED", "INTERRUPTED"].includes(run.status)).length;
  // Never sum native cumulative/resumed costs without a verified scope model.
  $("cost").textContent = "Unknown";
}
async function history(reset = true) {
  if (historyLoading) return;
  historyLoading = true; $("refresh").disabled = true; $("more").disabled = true;
  try {
  $("error").hidden = true;
  if (reset) { records = []; selected.clear(); $("compare").disabled = true; }
  const result = await api(`/api/runs?offset=${records.length}&limit=100`);
  records.push(...result.runs); $("total").textContent = result.total;
  $("more").hidden = records.length >= result.total;
  warnings("warnings", result.warnings || []); renderRuns();
  } finally { historyLoading = false; $("refresh").disabled = false; $("more").disabled = false; }
}
function card(title, value) { const item = node("div", null, "card"); item.append(node("small", title), node("strong", value)); return item; }
async function inspect(runId) {
  const epoch = ++selectionEpoch;
  currentRun = runId; events = []; nextSeq = 0;
  const data = await api(`/api/runs/${runId}`), run = data.run;
  if (epoch !== selectionEpoch) return;
  $("detail-title").textContent = label(run); $("detail").hidden = false;
  $("detail-summary").replaceChildren(card("Status", run.status), card("Evidence", run.evidence_status), card("Provider", run.provider.name), card("Authentication mode", run.configuration?.execution_mode === "offline" ? "Offline - no authentication" : (run.configuration?.auth_mode || "Unknown - legacy record")));
  $("result").textContent = pretty(data.result ? {summary:data.result.summary, validation:data.result.validation, assertions:data.assertions} : null);
  $("session").textContent = pretty({session_id:run.session_id, provider:run.provider, resumes_run_id:run.resumes_run_id, retry_of_run_id:run.retry_of_run_id});
  $("usage").textContent = pretty(run.usage); $("errors").textContent = run.error ? pretty(run.error) : "No recorded error";
  $("artifacts").replaceChildren();
  for (const artifact of data.artifacts?.artifacts || []) {
    const link = node("a", `${artifact.path} · ${artifact.size_bytes} bytes`);
    link.href = `/api/runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(artifact.artifact_id)}`;
    link.setAttribute("download", ""); $("artifacts").append(node("p", null)); $("artifacts").lastChild.append(link);
  }
  if (!data.artifacts?.artifacts?.length) $("artifacts").textContent = "No registered artifacts";
  warnings("detail-warnings", data.warnings || []); await loadEvents(); $("detail").scrollIntoView({block:"start"});
}
async function loadEvents() {
  if (!currentRun) return;
  const epoch = selectionEpoch, runId = currentRun;
  const requestKey = `${epoch}:${nextSeq}`;
  if (eventRequests.has(requestKey)) return;
  eventRequests.add(requestKey); $("more-events").disabled = true;
  try {
  const page = await api(`/api/runs/${runId}/events?after_seq=${nextSeq}&limit=200`);
  if (epoch !== selectionEpoch || runId !== currentRun) return;
  events.push(...page.events); nextSeq = page.next_seq; $("more-events").hidden = !page.more;
  for (const message of page.warnings || []) $("detail-warnings").append(node("p", message, "warning")); renderEvents();
  } finally { eventRequests.delete(requestKey); if (epoch === selectionEpoch) $("more-events").disabled = false; }
}
function renderEvents() {
  $("timeline").replaceChildren(); const filter = $("event-filter").value;
  for (const event of events.filter(item => filter === "all" || item.type.startsWith(filter) || item.source === filter)) {
    const entry = node("details", null, "event"), summary = node("summary", `${event.seq} · ${event.type}`);
    entry.append(summary, node("small", `${event.timestamp} · ${event.source}`), node("pre", pretty(event.payload))); $("timeline").append(entry);
  }
  if (!$("timeline").children.length) $("timeline").textContent = "No observed events for this filter; activity may be unavailable.";
}
async function capabilities() {
  const target = $("capability-cards"); target.replaceChildren();
  try { const catalog = await api("/api/capabilities"); for (const scenario of catalog.scenarios) target.append(card(scenario.title, `${scenario.evidence_status} · ${scenario.execution_mode}`)); }
  catch (error) { target.append(node("p", `${error.message}. Run a local platform scenario to create a catalog.`, "warning")); }
}
function compare() {
  const [a,b] = [...selected].map(id => records.find(run => run.run_id === id));
  const target = $("comparison-content"); target.replaceChildren();
  const context = run => JSON.stringify({provider:run.provider, kind:run.kind, scenario:run.scenario_id, config:run.configuration, limits:run.limits});
  target.append(node("p", context(a) === context(b) ? "Matching recorded execution context. Native costs still require scope review." : "Different provider, model, platform, kind, scenario or configuration. This comparison is descriptive; do not rank cost or quality.", "warning"));
  const table = node("table"), head = node("tr"); for (const value of ["Field",a.run_id.slice(0,8),b.run_id.slice(0,8)]) head.append(node("th",value)); table.append(head);
  for (const [field,get] of [["Status",r=>r.status],["Kind",r=>r.kind],["Session",r=>r.session_id || "Unavailable"],["Validation",r=>r.validation.status],["Duration",r=>`${r.usage?.application?.duration_ms ?? "Unknown"} ms`],["SDK estimate",r=>r.usage?.sdk?.total_cost_usd ?? "Unknown"]]) {
    const row = node("tr"); row.append(node("td",field),node("td",get(a)),node("td",get(b))); table.append(row);
  }
  target.append(table); $("comparison").hidden = false; $("comparison").scrollIntoView({block:"start"});
}
$("refresh").addEventListener("click",()=>history().catch(fail)); $("more").addEventListener("click",()=>history(false).catch(fail));
$("filter").addEventListener("change",renderRuns); $("event-filter").addEventListener("change",renderEvents); $("more-events").addEventListener("click",()=>loadEvents().catch(fail));
$("compare").addEventListener("click",compare); $("close-detail").addEventListener("click",()=>{$("detail").hidden=true;}); $("close-compare").addEventListener("click",()=>{$("comparison").hidden=true;});
for (const [button,view,other] of [["history-tab","history","capabilities"],["capabilities-tab","capabilities","history"]]) $(button).addEventListener("click",()=>{ $(view).hidden=false; $(other).hidden=true; $("history-tab").classList.toggle("active",view==="history"); $("capabilities-tab").classList.toggle("active",view==="capabilities"); if(view==="capabilities") capabilities().catch(fail); });
history().catch(fail);
