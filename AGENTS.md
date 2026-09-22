# Repository guidance for coding agents

## Purpose

This file gives ChatGPT, Codex, Cortex, and other contributors a short orientation. It is not a substitute for inspecting the current repository, branch graph, pull requests, tests, and dated project documents.

This file does not prescribe a model, reasoning budget, chain-of-thought style, agent count, tool choice, or implementation approach. Use the full reasoning and verification available to you. Challenge any recommendation here when current code or evidence supports a better conclusion.

## Start here

1. Read `docs/AGENT_HANDOFF.md` for the latest dated repository and pull-request snapshot.
2. Use `docs/CANONICAL_DOCUMENTS.md` to find the current authority for product decisions, dependencies, security, source provenance, and CI evidence.
3. Check the exact branch tip and live pull-request checks before relying on a recorded status. A green ancestor is not proof for a later commit.
4. Read the implementation and relevant tests before changing behavior. Historical design documents are context, not executable truth.

## Working principles

- Preserve existing work and history. Use a separate branch for a separate contribution unless the user explicitly directs otherwise.
- Do not merge, close, retarget, force-push, or rewrite another contributor's work without explicit authorization.
- Keep source evidence, interpretation, confirmed facts, and expected outcomes distinct.
- Treat missing or uncertain evidence as UNKNOWN or PENDING, never as zero, success, matched, received, or verified.
- Keep AI output advisory. Deterministic rules, source evidence, and authorized human decisions control financial and inventory truth.
- Never commit credentials, tokens, personal data, external archives, or production secrets.
- Record test evidence against immutable commit SHAs and report failures honestly.
- Prefer focused changes and tests that match the actual risk. Do not weaken a test merely to obtain a green result.

## Current handoff

The dated operational handoff is `docs/AGENT_HANDOFF.md`. Update it by appending a new dated section or by clearly marking superseded facts; do not silently rewrite historical claims.
