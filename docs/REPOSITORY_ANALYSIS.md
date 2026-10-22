# Use the offline read-only analysis page

The additive `agent_console.repository_analysis` entry runs inside this console
application and reuses its history reader and security headers. Default `cas-console`
and existing coding controls are unchanged; they do not automatically enable analysis.
Runtime and console must be installed in the same environment for this optional entry.

From the umbrella checkout on the pinned Windows environment:

```powershell
& 'C:/Users/admin/.pyenv/pyenv-win/versions/3.12.9/python.exe' -B -I -S ./tools/run_repository_analysis.py --data-dir "$env:TEMP/cas-repository-analysis-mvp" --port 8766
```

Open `http://127.0.0.1:8766/analysis`. Use a fresh directory on first start. Reopening
the same initialized directory preserves history; an unrelated existing directory is
refused rather than inspected or overwritten. Ctrl+C stops the server/local work.
Installed-package alternative: `python -m agent_console.repository_analysis --data-dir <fresh-directory> --port 8766`.

1. Select **Tiny Shop · approved local sample** and an overview/functions question.
   Only README.md and inventory.py are available; your real projects are not opened.
2. Select **Prepare analysis**. It saves a draft and does not execute anything.
3. Select **Start offline analysis**. This runs the fixed application fixture with no
   Claude/model/auth call or repository upload. New live parameters are rejected.
4. Select **Open report**. Inspect source-validated title/function facts. Each reference
   opens an immutable approved source snapshot at its exact definition line.
5. Select **Download report + sources** for a ZIP with Markdown, structured provenance
   and both source snapshots. References resolve relative to the bundled `files/`.
6. Reload or open **Execution history** to inspect saved canonical records. Reload
   never starts/replays work. Failed/cancelled/interrupted runs have no accepted report.

The page uses same-origin loopback requests, CSRF tokens, strict bounded JSON bodies,
safe text rendering and explicit file IDs; no arbitrary path/command/model is accepted.
The report and ZIP endpoints revalidate canonical status, claims and source hashes.
The source viewer escapes text and retains line anchors. Existing readonly history
remains available on `/`, with coding mutation endpoints disabled in this entry.

This is an offline fixture-backed vertical slice, not general repository or live
Claude analysis. The output is explicitly labeled scripted/application evidence. A
Python-only controlled producer tests error/Stop paths; no CLI/provider flag exposes it.
Native model/cost data remains unavailable. Local Stop does not assert server/native
cancellation. The broader live/data/security gates remain separate.

Backend regression: `tests/test_repository_analysis_http.py`. DOM regression:
`node tests/analysis_ui.test.cjs`. The umbrella `tools/repository_analysis_browser_qa.py`
uses real Chromium, a fresh data directory, only loopback page requests and no model.
All three analysis static assets are included by the existing wheel packaging rules.


## Default-closed SDK path (mock verified)

The same analysis page now accepts explicit nonempty checkbox selection of the two
allowlisted Tiny Shop files. Preparation captures only selected synthetic bytes with
per-file and combined SHA-256. Paths, links, duplicates, changed content and files over
8 KiB are rejected; aggregate source limit is 16 KiB. No arbitrary repository path or
upload is accepted. Legacy offline create/start requests remain supported.

Choose SDK payload preview, prepare a draft, then Review SDK payload. The literal
query, fixed model, recipient and limits are displayed with two fresh unchecked
consents. SDK Start remains disabled while the source gate is false; the backend
rejects even crafted consent requests before run claims or provider construction.
There is no CLI/environment/API switch that activates it.

SnapshotSDKAdapter delegates to the existing SupervisedClaudeAdapter and Executor.
One query/turn, USD 0.02 SDK threshold, 30-second executor timeout, text-only tools
and empty SDK workspace are enforced. One SDK attempt is consumed per dedicated
analysis directory. Strict bounded JSON parsing and independent heading/AST, path,
line/hash/coverage checks decide report acceptance. Native success alone is insufficient.
Accepted reports/checkpoints and selected sources survive restart and export as ZIP.
Mock reports explicitly identify mock provenance and zero real model requests.

Stop uses actual local task cancellation and existing owned-process cleanup. CANCELLED
requires confirmed empty cleanup; unknown cleanup/timeout is INTERRUPTED. Neither
status proves provider cancellation or stopped billing. Invalid reports and raw SDK
errors are not published as accepted reports; public errors use safe codes. Source
snapshots are revalidated before checkpoint/export. No replay or retry is automatic.

## Review findings and request ordering

The **review** question uses report version 2 (see `docs/contracts/ANALYSIS_FINDINGS.md`):
bounded prose problem/impact/suggested fix with a selected file, real line and hash.
It needs SDK mode, so the page switches the mode for you and the offline sample never
fabricates a review. The page shows file:line links to the snapshot and states that the
prose is screened, not verified as correct. Overview/functions reports render as before.

A review may report no findings; the page then shows "No findings reported" and says this
is not proof that the selected files are correct.

Request ordering on this page: only the newest refresh answer is rendered, and report and
preview selections share one generation, so the newest selection of either kind wins and
older answers and their errors are dropped silently (this is not provider cancellation).
Selecting a report drops a shown preview and its consent.
One mutation runs at a time; after any failed or unknown mutation the page re-reads state
and never replays it. If the re-read also fails, mutations stay
locked (prepare/start/stop refused locally, no automatic retry) until an explicit Refresh
succeeds; this includes HTTP error statuses such as 500, because a server failure can follow an
applied change. A terminal status is not replaced by a late non-terminal view, and a
Stop rejected because the run already finished is reported as such. Preview consents are
single use and bound to the job, profile and snapshot; a changed job hides the preview.
Stop is described as a local request, not proof of provider cancellation.

DOM regression for these: `node tests/analysis_races.test.cjs` (delayed fetches released
by the test, no timers).

## Fixed mean.py review scope (CURRENT, 2026-10-22; gate closed, NOT_READY)

The mode **Synthetic mean.py review (own gate, closed)** prepares exactly one fixed synthetic
file, `mean.py` (122 bytes), and the review question. Selecting the mode shows
"Mean review selection (fixed): mean.py" and hides the Tiny Shop file list, whose checkbox
state is untouched and applies again for the other modes. Legacy modes are unchanged.

Review SDK payload for this scope lists, as plain text (`textContent`), the profile id,
model, selected file with bytes and hash, instruction/query hashes, tools (none), retries (0),
SDK version, transport, gate name, the full fingerprint, whether the scope is still current,
and **every** bound the profile defines (one `bound: <name>` row each, including
`budget_usd`, all time, count and byte bounds). It states that the USD value is an SDK
threshold and not a billing, invoice or quota cap, that one logical query is made while
hidden provider retries are not observable, that `finalize_seconds` is an accounting
allowance rather than an enforced timer, that the watchdog is cooperative, and that
provider-side cancellation and deletion are not claimed.

Start stays disabled while the scope gate is closed, and a crafted click is refused locally
("The live gate is closed. Nothing was sent."). Consent is bound to the preview, job, profile,
snapshot and scope fingerprint; a server `scope_current: false` or a changed job scope hides
the preview and rejects the start before any request. Consent is single use even when the
request fails, and a double click sends one request. A late preview answer never replaces a
newer selection.

Regression (written, **NOT_RUN** until the coordinator records evidence):
`node tests/analysis_races.test.cjs` (scoped scenarios at the end) and
`tests/test_repository_analysis_http.py::test_mean_scope_creation_preview_and_closed_gate_over_http`
(synthetic data and the closed gate only; no model, auth or native process). Fresh builds and
browser acceptance are also NOT_RUN. Details: the runtime `docs/REVIEW_READINESS.md`.

Live/native/auth behavior has not been exercised for this path. The single future
scope and fresh-session review handoff live in the umbrella
`docs/review/REPOSITORY_ANALYSIS_SDK_2026-10-17.md`. Keep the gate closed pending that
review and separate explicit approval. No new framework/dependency is introduced.
