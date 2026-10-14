# Implementation handoff

Start with sanitized v1 task/scenario fixtures, safe record reading and loopback HTTP endpoints. Package static/index.html, styles.css and app.js with the app; no React/Vite or build framework. Acceptance includes corrupt/partial data, timeline, tool/hook/permission/subagent detail, usage provenance, errors, artifacts, comparison and stored-XSS tests.

This repository has no tests or runtime code yet. Add meaningful deterministic tests
before integration behavior; live SDK tests are a separate opt-in tier. Record exact
commands and prerequisites here when they exist. Read the umbrella requirements,
contract v1 proposal, security guide and scenario catalog before implementation.
Preserve the repository boundary and independent dependency history. No orchestration
framework or speculative provider abstraction is permitted by SPEC.
