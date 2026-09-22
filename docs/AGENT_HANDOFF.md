# Agent handoff

Status snapshot: 2026-09-22

Prepared by: Codex (Cognizant)

## Purpose and reasoning freedom

This is a factual handoff for future ChatGPT, Codex, Cortex, and human contributors. It records what was observed and changed in one working session. It is not a command to repeat the same approach, and it does not limit a future model's reasoning depth, tools, architecture choices, or ability to disagree. Re-check every time-sensitive fact against the live repository.

## Repository topology observed

- `main` does not yet contain the Phase 1 application work.
- PR #2, `phase1-doctype-scaffold` into `main`, was open and unmerged. Its observed tip was `dbf6e2f57b8d250193d0db880ed3eb3bc9fbc8e3`.
- PR #3, `phase2-evidence-durability` into `phase1-doctype-scaffold`, was a draft with nine commits. Its observed tip was `df7d0fd5b1ac1672be5fe15a18916e70bbf9d79e`.
- PR #4, `codex/ci-repo-hardening` into `phase1-doctype-scaffold`, was created as a draft during this session. It contains one commit and one changed file.
- No merge, force-push, branch rewrite, pull-request closure, or change to `main`, `phase1-doctype-scaffold`, or `phase2-evidence-durability` was performed by Codex (Cognizant).

Live links:

- PR #2: https://github.com/AnubhavDubey02/fresko-universe/pull/2
- PR #3: https://github.com/AnubhavDubey02/fresko-universe/pull/3
- PR #4: https://github.com/AnubhavDubey02/fresko-universe/pull/4

## Work performed by Codex (Cognizant)

A separate branch, `codex/ci-repo-hardening`, was created from the Phase 1 tip. Commit `4d98d72a0419b38ef426095aa0f61a1e042ab0ec` changes only `.github/workflows/ci.yml`.

The workflow change:

- adds top-level `permissions: contents: read`;
- pins both jobs to `ubuntu-24.04` instead of `ubuntu-latest`;
- pins `actions/checkout` to `3d3c42e5aac5ba805825da76410c181273ba90b1` (v7.0.1);
- sets `persist-credentials: false` for both checkout steps;
- pins `actions/setup-python` to `5fda3b95a4ea91299a34e894583c3862153e4b97` (v7.0.0);
- pins `actions/setup-node` to `820762786026740c76f36085b0efc47a31fe5020` (v7.0.0);
- sets `package-manager-cache: false` for setup-node;
- pins `actions/upload-artifact` to `043fb46d1a93c77aae656e7c1c64a875d1fc6a0a` (v7.0.1); and
- updates the runner note to name Ubuntu 24.04.

The existing Frappe and ERPNext application pins were not changed:

- Frappe v15.120.1: `9f8ae9cd25b6735be345da6cc12e9f5a96050c68`
- ERPNext v15.121.2: `df8b7f9648c2ec4da12db8c4022edc8dd1018c6b`

## Verification performed

PR #4 triggered GitHub Actions run https://github.com/AnubhavDubey02/fresko-universe/actions/runs/35702519790.

Observed result:

- overall status: success;
- smoke job: 4 seconds;
- pinned Frappe bench job: 4 minutes 23 seconds;
- no Node.js 20 deprecation annotation;
- no `ubuntu-latest` migration annotation; and
- no artifacts or application-code changes.

The preceding Phase 1 and Phase 2 runs were also green when inspected, but still used the older action tags and `ubuntu-latest`:

- PR #2 run: https://github.com/AnubhavDubey02/fresko-universe/actions/runs/35469165517
- PR #3 run at its observed tip: https://github.com/AnubhavDubey02/fresko-universe/actions/runs/35645270394

## Phase 2 context that must be reconciled

The canonical index and several security/readiness documents predate all implementation commits on PR #3. They correctly preserve historical decisions, but their status language may lag the active branch.

In particular:

- `docs/CANONICAL_DOCUMENTS.md`, `docs/DECISIONS.md`, and `docs/phase2_readiness/WHATSAPP_FIXTURE_CONTRACT.md` describe Phase 2 runtime work as pending or on hold.
- `docs/security/SECURITY_FINDINGS.md` records FSEC-004 and FSEC-005 as open at its documented review tip.
- PR #3 contains later implementation, tests, and corrective evidence related to evidence byte hashing, scoped message identity, durability, provenance, and bounded independent persistence.
- `docs/phase2_readiness/F2_005_007_CORRECTIVE_EVIDENCE.md` records implementation SHA `f8486921bab12198c8623ce1db36086fbf8f8b44`, a successful pinned bench run, 123 smoke tests, 119 bench tests, 19 readiness fixtures, and 6 readiness-contract tests. That document explicitly says broader security findings are not closed by the narrow pass.

A future contributor should therefore compare the current PR #3 tip, code, migrations, tests, CI logs, and security ledger before declaring any finding closed or adding more Phase 2 behavior. Do not infer closure from a commit title or a dated document alone.

## Recommended next inquiry

Keep PR #4 focused on CI hardening. Do not add Phase 2 code to `codex/ci-repo-hardening`.

For Phase 2 work, start from a new `codex/` branch based on the then-current `phase2-evidence-durability` tip, after confirming that PR #3 is still the intended base. First perform an independent review of the nine PR #3 commits and reconcile the open findings and dated documentation. Then choose one verified issue, write or preserve a reproducing test, implement the narrowest coherent fix, and run the smoke plus pinned bench gates.

This recommendation is not an authorization to merge PR #2, PR #3, or PR #4. Merge decisions remain with the repository owner.

## Canonical reading order

1. `docs/CANONICAL_DOCUMENTS.md`
2. `docs/DECISIONS.md`
3. `docs/OPEN_QUESTIONS.md`
4. `docs/VERSIONS.md` and `.github/frappe-versions.json`
5. `docs/security/SECURITY_FINDINGS.md` and `docs/security/SECURITY_TESTING.md`
6. `docs/phase2_readiness/WHATSAPP_FIXTURE_CONTRACT.md`
7. `docs/phase2_readiness/CLOSEOUT_REVIEW.md`
8. `docs/phase2_readiness/F2_005_007_CORRECTIVE_EVIDENCE.md`
9. `docs/GATE2_CI_RESULT.md`
10. `docs/SOURCES.md`

The large `docs/FRESKO_UNIVERSE_CODEX_START_HERE.md` remains valuable product and architecture history. Read it as dated context alongside the canonical index, not as a replacement for inspecting the current code.

## Environment and credential note

This session used the signed-in GitHub web interface because local terminal elevation was unavailable. No password, token, API key, OAuth secret, or user credential was requested, copied into repository content, or committed. GitHub Actions supplied the reproducible smoke and bench verification.
