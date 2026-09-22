# Agent handoff

Status snapshot: 2026-09-22

Prepared by: Codex (Cognizant)

## Handoff publication

This handoff and the root `AGENTS.md` were added on the separate `codex/agent-handoff` branch and proposed to `phase2-evidence-durability` as draft PR #5: https://github.com/AnubhavDubey02/fresko-universe/pull/5.

Initial publication commits were `eb8eacd259e5de4998ae059188ac4e7ca508da06` and `2da45de7fab7fa3658556f453066599de4486f69`. The documentation-only GitHub Actions run https://github.com/AnubhavDubey02/fresko-universe/actions/runs/35705620935 succeeded: smoke completed in 6 seconds and the pinned bench completed in 5 minutes 20 seconds. Its Node.js 20 and `ubuntu-latest` annotations are expected because this branch inherits the Phase 2 workflow; the separate PR #4 contains the verified workflow hardening.

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

## 2026-09-22 independent review — ChatGPT

Reviewer/session label: ChatGPT (Personal review)

### Agent/session attribution convention

Multiple Codex environments may work on this repository. Preserve that distinction without implying employer authorship, sponsorship, approval, or ownership.

Use:
- Codex (Personal) — Codex work performed from Anubhav's personal environment/device.
- Codex (Office/Cognizant environment) — Codex work performed from Anubhav's office/Cognizant environment/device. This is an environment/session label only; it does NOT mean Cognizant authored, sponsored, approved, or owns the repository work.
- ChatGPT (Personal review) — independent review in Anubhav's personal ChatGPT project context.
- If environment is unknown, write "environment UNKNOWN"; never infer it.

Existing references saying "Codex (Cognizant)" should be interpreted and, in a later cleanup, renamed to "Codex (Office/Cognizant environment)".

### Review of AGENTS.md

The current lean AGENTS.md direction is sound. Preserve its reasoning-freedom language: future models must remain free to challenge historical recommendations when current code, persisted-state evidence, or reproducible tests disagree.

Add these two principles to AGENTS.md in the same documentation-only change:

1. A passing test suite proves only the assertions exercised by that suite. Do not infer semantic correctness, security closure, migration safety, or production readiness solely from green CI.

2. When practical, reproduce a suspected runtime defect before changing production behavior. Do not change runtime code solely because a historical document says behavior is wrong.

Keep AGENTS.md lean. Detailed architecture/history belongs in AGENT_HANDOFF.md and canonical project docs, not AGENTS.md.

### Branch / PR dependency finding

Observed repository graph during independent review:

- Phase 1 / PR #2 tip:
dbf6e2f57b8d250193d0db880ed3eb3bc9fbc8e3

- Phase 2 / PR #3 tip:
df7d0fd5b1ac1672be5fe15a18916e70bbf9d79e
based on Phase 1

- CI hardening / PR #4 tip:
4d98d72a0419b38ef426095aa0f61a1e042ab0ec
separate child of Phase 1

- AGENTS/handoff / PR #5:
based on Phase 2

Therefore PR #4's hardened workflow is NOT yet part of PR #3 merely because both are green.

If/when PR #4 is incorporated into Phase 1:
1. update Phase 2 from the resulting Phase 1 state;
2. rerun Phase 2 CI;
3. only then claim that Phase 2 inherits the hardened workflow.

Do not merge, retarget, rebase, force-push, or rewrite branches from this note alone. Repository-owner authorization still controls merge decisions.

### CI hardening review

PR #4's direction was independently reviewed and is technically coherent:

- top-level contents: read permission;
- Ubuntu 24.04 pinning;
- GitHub Actions pinned by immutable SHAs;
- checkout persist-credentials disabled;
- setup-node package-manager caching disabled.

Its smoke and pinned Frappe/MariaDB bench jobs were green when reviewed.

Important: green CI proves only those executed gates, not broader Phase 2 semantic correctness.

### Remaining Phase 2 proof / reconciliation work

Before treating PR #3 as complete or closing broader security findings:

1. Reconcile dated/canonical Phase 2 and security documentation against actual current PR #3 code, migrations, tests and CI.

FSEC-004/FSEC-005 must not be closed merely from commit titles or narrow corrective evidence.

2. Add or verify an upgrade/migration regression for existing historical Fresko Evidence Attempt rows across the change from Link-style references to Data identifier snapshots.

Prove:
- existing identifier values are preserved;
- historical values are not fabricated or reinterpreted;
- legacy NULL audit fingerprints remain NULL/UNKNOWN truthfully;
- permissions remain correct;
- migration succeeds against an existing-state fixture, not only a fresh site.

3. Review:
docs/phase2_readiness/F2_005_007_CORRECTIVE_EVIDENCE.md

Remove any unrelated/context-contaminated material before treating the document as canonical Phase 2 evidence.

4. Keep PR #3 draft/unmerged until those proof and reconciliation items are independently checked.

### Handoff maintenance rule

Update AGENT_HANDOFF.md after meaningful work units, for example:

- completed corrective slice;
- security re-review;
- migration proof;
- material architecture decision;
- branch/base change;
- merge.

Do not append noise after every command or ordinary test rerun.

Every meaningful entry should record:
- agent/session label;
- environment label when known;
- exact branch and SHA;
- what actually changed;
- what was independently verified;
- what remains UNKNOWN/PENDING.
