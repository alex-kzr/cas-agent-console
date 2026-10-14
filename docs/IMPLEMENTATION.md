# Implementation status

The first local agent-console implementation is available. Its README defines exact install,
test and build commands; package dependencies are independently locked. No remote has
been configured and no model call or external publication was performed.

See umbrella docs/review/IMPLEMENTATION.md for cross-component evidence and remaining
limitations. Application changes belong in this repository, shared contracts and research
conclusions in umbrella. Offline test results never establish native SDK/model behavior.

## Opt-in task control

Default read-only mode remains independent. With `--enable-tasks` and runtime installed in the same environment, same-origin/token-gated controls create/start/stop the bounded coding fixture and prepare explicit continuation with fresh consent. Actual browser QA used a test-only injected scripted adapter; it verifies application wiring, not native model/session behavior. See umbrella docs/review/CODING_CONSOLE.md and docs/contracts/CONTROL_API.md.
