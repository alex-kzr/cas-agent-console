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
