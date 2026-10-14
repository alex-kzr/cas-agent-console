# Local console acceptance and remaining gates

Default mode is a read-only local evidence reader. `--enable-tasks` separately opts into
fixed coding-fixture controls and requires runtime and console in the same environment.
Starting either server mode performs no model call; each production control start still
needs explicit per-run model and existing-session consents. No test provider flag exists
in the production CLI.

## Recorded acceptance

The initial 11-test HTTP reader suite covered history/detail/static, safe host/origin,
default-mode mutation rejection, IDs/pagination/traversal, malformed/partial/unsupported
records, cross-run identity, artifact integrity/download headers and remote-bind denial.
Subsequent recorded console suites contain 13 passing HTTP/API tests, including control
token/origin/body handling and default-disabled controls. These are historical suite counts,
not a claim about the size of every future checkout's test suite.

Headless Chromium acceptance uses actual temporary offline records and an explicitly
injected scripted adapter with owned Python fixture processes. It covers:

- History, inspector, timelines, artifact download, compatible comparison and catalog.
- Stored untrusted strings rendered as literal text, zero page errors and mobile overflow checks.
- Control create, missing-consent refusal, start, fixed source/tests/diff, explicit new-run
  continuation with new consents, Stop and observed owned process-tree cleanup.
- Restart recovery from a stale control record to canonical completion without replay;
  missing-session continuation disabled with an explicit reason.
- Native/derived usage values kept separate, unknown/invalid data preserved as unavailable
  and resumed/subagent deltas withheld. Seven Node DOM assertions execute the actual app.

The synthetic harness is labeled offline. It cannot establish native resume, permission
callback coverage, hidden context isolation or billing. Scripted output is not a model
result. Independent code reviews corrected and rechecked their findings.

Evidence is in umbrella `docs/review/`: `CODING_CONSOLE.md`, `SESSION_RECOVERY_2026-10-14.md`
and `OBSERVABILITY_DIAGNOSTICS_2026-10-14.md`, with sanitized JSON/PNG under `evidence/`.
The separately authorized native coding positive is recorded independently in
`docs/research/CODING_E2E_RESULT_2026-10-14.md`; its consumed approval permits no repeat.

## Reproduction and boundaries

In the existing console environment, run `python -m unittest discover -s tests -v` and
`node tests/usage_comparison.test.cjs` from this component. Browser harness commands and
their exact evidence are documented in the owning umbrella review reports. No native
auth/model check is a prerequisite for the offline tests.

The umbrella `docs/guides/OFFLINE_OPERATIONS.md` documents a new-data offline scenario and
report export. Reader mode can inspect those records without task control. Do not use a
production Start button as an offline setup check.

Full S-02 acceptance remains open: actual component remotes and authorized recursive
clone/install, a separately scoped practical repository/documentation model task, broader
native histories/tool/hook/subagent coverage, isolation and operations/security gates.
The current refresh-consent question awaits an operator decision; it does not imply native
resume is technically impossible. Local loopback acceptance does not certify remote or
multi-user deployment, retention automation, backup/restore or production readiness.
