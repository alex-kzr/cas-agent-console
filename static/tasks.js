"use strict";
(() => {
  const element = id => document.getElementById(id);
  let token = null, chosen = null, pending = false, timer = null;
  const terminal = new Set(["COMPLETED", "FAILED", "INTERRUPTED", "CANCELLED"]);
  function status(message) { element("control-status").textContent = message; }
  async function post(path, body) {
    if (pending) throw new Error("An operation is already pending.");
    pending = true;
    try {
      const response = await fetch(path, {method:"POST", credentials:"same-origin",
        headers:{"Content-Type":"application/json", "X-CAS-CSRF":token}, body:JSON.stringify(body)});
      const result = await response.json();
      if (!response.ok) throw new Error(result.error);
      return result;
    } finally { pending = false; }
  }
  function button(text, action) {
    const result = document.createElement("button"); result.textContent = text;
    result.addEventListener("click", () => action().catch(error => status(error.message)));
    return result;
  }
  function consent(task) {
    chosen = task.task_id;
    element("consent-live").checked = element("consent-login").checked = false;
    element("consent-task").textContent = `One run for ${task.task_id}${task.resumes_run_id ? " continuing " + task.resumes_run_id : " in a new disposable fixture"}`;
    element("run-consent").hidden = false;
  }
  async function refresh() {
    let delay = 1500;
    try {
    const response = await fetch("/api/control", {cache:"no-store"});
    if (!response.ok) throw new Error("Task control unavailable");
    const info = await response.json();
    element("task-controls").hidden = !info.enabled;
    if (!info.enabled) { delay = 0; return; }
    document.querySelector('.local').textContent = 'Local · Task control enabled';
    if (info.execution_mode === 'scripted-test-only') document.querySelector('.notice').textContent = 'SCRIPTED OFFLINE TEST HARNESS — no Claude authentication or model calls. These records verify application behavior only.';
    document.querySelector('footer span').textContent = 'Versioned local evidence · Explicit per-run task controls';
    token = info.csrf;
    const container = element("control-tasks"); container.replaceChildren();
    for (const task of info.tasks) {
      const card = document.createElement("article"), title = document.createElement("p");
      card.className = "card";
      title.textContent = `${task.task_id} — ${task.status}`; card.append(title);
      if (task.recovery) {
        const recovered = document.createElement('p');
        recovered.textContent = `Recovered after restart: ${task.recovery.reason}. No automatic replay.`;
        card.append(recovered);
      }
      if (task.status === "DRAFT") card.append(button("Review and start", async () => consent(task)));
      if (["STARTING", "RUNNING"].includes(task.status)) card.append(button("Stop run", async () => {
        await post(`/api/tasks/${task.task_id}/stop`, {}); status("Stop requested; waiting for owned-tree cleanup."); await refresh();
      }));
      if (task.run_id) {
        const detail = document.createElement("p"); detail.textContent = `Run: ${task.run_id}`; card.append(detail);
        card.append(button('Inspect result and artifacts', async () => window.inspect(task.run_id)));
        if (terminal.has(task.status)) {
          const continuation = task.continuation;
          const reason = document.createElement('p');
          reason.textContent = continuation?.reason || 'Local continuation eligibility is unavailable.';
          card.append(reason);
          const prepare = button('Prepare continuation', async () => {
            const next = await post('/api/tasks', {resumes_run_id:task.run_id});
            await refresh(); consent(next);
          });
          prepare.disabled = continuation?.eligible !== true;
          prepare.title = reason.textContent;
          card.append(prepare);
        }
      }
      container.append(card);
    }
    } catch (error) { delay = 5000; throw error; }
    finally {
      clearTimeout(timer);
      if (delay) timer = setTimeout(() => refresh().catch(error => status(error.message)), delay);
    }
  }
  element("create-task").addEventListener("click", async () => {
    try { const task = await post("/api/tasks", {}); await refresh(); consent(task); }
    catch (error) { status(error.message); }
  });
  element("resume-task").addEventListener("click", async () => {
    try { const task = await post("/api/tasks", {resumes_run_id:element("resume-run").value.trim()}); await refresh(); consent(task); }
    catch (error) { status(error.message); }
  });
  element("dismiss-consent").addEventListener("click", () => { chosen = null; element("run-consent").hidden = true; });
  element("start-task").addEventListener("click", async () => {
    if (!chosen || !element("consent-live").checked || !element("consent-login").checked) {
      status("Both explicit per-run approvals are required."); return;
    }
    const id = chosen; chosen = null; element("run-consent").hidden = true;
    element("consent-live").checked = element("consent-login").checked = false;
    try { await post(`/api/tasks/${id}/start`, {allow_live:true, allow_existing_login:true}); status("Run started. Inspect run history for result, diff and tests."); await refresh(); }
    catch (error) { status(error.message); await refresh(); }
  });
  refresh().catch(error => status(error.message));
})();
