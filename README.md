# agent-console

Independent read-only CAS console using Python standard-library HTTP and vanilla JS.
It consumes local versioned JSON/JSONL; default mode imports no runtime internals and executes no agents. No runtime credentials are needed. Component remote is still unset.

```powershell
uv sync --locked
uv run --locked --offline cas-console --data-dir <CAS-data-directory> --port 8765
uv run --locked --offline python -m unittest discover -s tests -v
uv build --offline
```

Use an existing data directory, for example umbrella `data/` after running local platform
checks. Server binds only `127.0.0.1`; open its printed loopback URL. Stop with Ctrl+C.
Runtime `cas-cli console` can launch this independently installed application.

Features: history/filtering, summary, session/provider metadata, results/validation,
event timeline with tool/hook/permission/subagent filters, native/derived usage provenance,
errors, approved artifact downloads, local capability catalog and context-aware comparison.
Missing native data is explicit. Default mode rejects mutation endpoints; no remote access or production claim.

Wheel packaging includes top-level static assets. Editable development falls back only
to this owning checkout's static directory; standalone wheels use packaged resources.
Schema copies match umbrella v1 contracts. See [acceptance evidence](docs/ACCEPTANCE.md).

## Opt-in coding task controls

The initial read-only description above applies to default mode. `--enable-tasks` enables create/start/stop and explicit continuation through the separately installed runtime; both packages must share one interpreter. No runtime dependency is required for default viewing. New controls require same-origin JSON/CSRF and fresh per-run model/session consent. The synthetic calc.py fixture has bounded read/write/fixed-test tools; no arbitrary shell or repository path. See umbrella docs/guides/CODING_CONSOLE.md for install/start, limits and offline-only evidence.

Subsequent live result: CAS-CODING-LIVE-001 used unchanged console `d3947eb` through the production UI, with one authorized native coding start, inspector and hash-matching diff/test downloads. No scripted adapter was injected for that run. See umbrella docs/research/CODING_E2E_RESULT_2026-10-14.md; this one-shot approval is consumed.
