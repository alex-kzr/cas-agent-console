# agent-console

Independent read-only CAS console using Python standard-library HTTP and vanilla JS.
It consumes local versioned JSON/JSONL; it never imports runtime internals or executes
agents. No runtime credentials are needed. Component remote is still unset.

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
Missing native data is explicit. No mutation endpoints, remote access or production claim.

Wheel packaging includes top-level static assets. Editable development falls back only
to this owning checkout's static directory; standalone wheels use packaged resources.
Schema copies match umbrella v1 contracts. See [acceptance evidence](docs/ACCEPTANCE.md).
