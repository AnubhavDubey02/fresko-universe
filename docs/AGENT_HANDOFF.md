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

## 2026-10-01 stabilization consolidation — Codex (Office/Cognizant environment)

### Exact repository state

- Working branch: `codex/integration-stabilization`
- Target/base: `phase2-evidence-durability`
- Base before migration proof: `df7d0fd5b1ac1672be5fe15a18916e70bbf9d79e`
- Incorporated migration-proof head: `845cf14e1480cacae4febbd9aea53f264f46bf9a`
- Stabilization implementation commit: `893f353` (`fix: stabilize evidence and legacy dispatch gates`)
- Handoff consolidation commit: `9dbc494` (`docs: update agent handoff for stabilization`)
- ATS CI corrective commit: `f6c255a` (`fix: refresh ATS reads after container lock`)
- Draft consolidation PR: https://github.com/AnubhavDubey02/fresko-universe/pull/7

PR #7 includes the PR #6 migration-proof commits, the useful PR #4 workflow hardening, and the stabilization implementation. PRs #4, #5, and #6 remain open at this snapshot. Do not close them merely from this handoff; repository-owner authorization controls closure and merge decisions.

### What changed in the stabilization commit

- CI now uses read-only permissions, Ubuntu 24.04, immutable action SHAs, disabled checkout credential persistence, disabled setup-node package-manager caching, and PR #6's full-history migration proof/failure logs.
- Date-like sender identifiers are compared as identifiers; datetime normalization is limited to `source_sent_at`.
- Message and attachment access-denied, identity-collision, payload-conflict, ordinal-validation, provenance-conflict, and capture-database-failure paths fail closed if their isolated audit attempt is not independently durable.
- `apply_rate_rules`, approval decisions, counter acceptance, release into the legacy dispatch state, and legacy dispatch writes use the container-first lock hierarchy.
- `RATE_FLOOR_BREACH` now opens once under the serialized rate transition and is linked/disposed through the approval lifecycle: in-band approval resolves it, authorized out-of-band approval waives it, rejection resolves it, counter keeps it in progress, and accepted counter resolves or waives it by the accepted rate.
- Combined oversell plus rate-breach approval preserves the structured `Approval.exception -> OVERSELL_OVERRIDE` link while recording the rate-breach disposition in its audited notes.
- `release_for_outward` remains as an API compatibility alias only. Every successful legacy release/dispatch response states `legacy_dispatch_transition=true`, `physical_outward_recorded=false`, and `phase2a_outward_authorized=false`.

The existing `Fresko Deal.dispatched_qty` remains a legacy cumulative scalar. New Phase 2A code must not use it as the physical Outward ledger.

### Verification completed locally

- Offline smoke suite: 139/139 passed at `f6c255a` (137/137 before the CI corrective tests).
- WhatsApp readiness fixtures: 19 validated.
- Readiness contract tests: 6/6 passed.
- Python compilation of every changed Python file: passed.
- `git diff --check`: passed; only local LF/CRLF conversion notices were emitted.

The test suite includes real two-connection Bench regressions for rate-rule serialization, counter acceptance, and lot dispatch concurrency. They were added but could not be executed locally because this device has no configured Frappe Bench/site.

### First PR #7 CI result and corrective action

GitHub Actions run https://github.com/AnubhavDubey02/fresko-universe/actions/runs/36862068554 tested implementation SHA `893f3535293ad1d9b0311145b85b701c664f614a`:

- Smoke unit passed.
- Bench initialization, pinned Frappe/ERPNext checkout, site creation, application installation, migration, and ERPNext test bootstrap all passed.
- The Bench suite ran 121 tests and had one failure: `test_concurrent_apply_rate_rules_serializes_on_container` observed two `Auto Approved` results instead of one `Auto Approved` plus one `Approval Required`.

This exposed a real production race rather than a bad expectation. A worker could establish an InnoDB REPEATABLE READ snapshot while probing its Deal, wait for the container lock, and then reuse the stale snapshot in the ordinary lot/reservation SELECTs. Commit `f6c255a` propagates `for_update=True` into both ATS child reads so they use current `FOR UPDATE` semantics after the container lock. It also adds focused offline coverage proving that mutation paths use locking reads while display ATS calls remain non-locking. Preserve the real two-connection Bench regression; do not weaken its expected statuses.

### Exact-head verification result

GitHub Actions run https://github.com/AnubhavDubey02/fresko-universe/actions/runs/36868658419 passed against exact head `0d30a139cfe7f5945e73ef8ed8c6650e0db8d1e6`, which contains the stabilization implementation, ATS correction, and this consolidated handoff history:

- `Smoke unit (Gate 1 / D4 / constants)` passed in 8 seconds.
- `Bench install + migrate + run-tests (pinned v15)` passed in 5 minutes 22 seconds.
- The Bench job included the Phase 1-to-current migration followed by a second idempotence migration.
- The real MariaDB/Redis concurrency regressions, including the ATS rate-rule race, executed successfully.

This is the verified stabilization checkpoint. A later documentation-only descendant may record this result without changing runtime behavior; do not describe such a descendant itself as exact-head green unless its own checks complete.

### Locked direction after stabilization

The next product slice is Phase 2A: evidence-linked physical Outward plus append-only Field Assertions.

Add in the existing modular monolith:

- `Fresko Field Assertion` — immutable source-backed field claim with explicit provenance and supersession;
- `Fresko Outward` — physical movement header, independent of Deal, buyer, and rate;
- `Fresko Outward Line` — child rows for lot text/identity, quantity, UOM, and raw source values.

Physical posting must not require a Deal or price. Missing commercial mappings open exceptions while the physical movement remains truthful. Corrections use superseding assertions or compensating reversal Outward records; never edit posted source facts.

The existing Container snapshot must remain backward-compatible and gain additive physical, commercial, assertion, exception, and provenance sections. It must label `Fresko Deal.dispatched_qty` as `legacy_deal_dispatched_qty`, never as physical outward.

Payments and allocations are the next slice after Outward, not part of the first Phase 2A commit.

### Required real-world acceptance cases

- 447 Plum crates post as physical Outward with a null rate and an `OUTWARD_UNPRICED` exception.
- 180 Grapes crates remain unpriced unless an authorized verified/user-confirmed rate assertion exists.
- 92 crates at INR 700 may appear only as provisional INR 64,400; `Balance Sale`, `BALANCE / UNMAPPED`, and `NOT AVAILABLE` remain preserved source strings.
- Declared shipping quantity 3,060 versus operating inward 3,056 produces a four-unit variance and blocks reconciliation.
- The missing INR 101 payment remains an evidence exception and must not become a receipt.
- INR 350,000 with `Authorization InProcess` remains pending and must not enter cleared collections or allocation.

### Explicitly deferred backlog, not stabilization blockers

- Check production data for historical duplicate open `RATE_FLOOR_BREACH` rows; clean them only if present.
- Decide whether Phase 1 commercial approval must prohibit approver = Deal owner/salesperson. Phase 2A Outward maker-checker must prohibit self-posting.
- Add a dedicated fixture PII/secret/operational-identifier sanitization gate.
- Reconcile remaining stale canonical/security wording after exact-head CI evidence is available.
- Do not prioritize website work, partner portal, live WhatsApp/AI/OCR, Chatwoot, Activepieces, or Metabase ahead of the Outward and Payment ledgers.

### Credential and publication note

GitHub device authorization was completed for the repository owner and stored by GitHub CLI in the operating-system credential store. Dulwich receives the credential only in memory through an uncommitted helper outside the repository. No password, token, OAuth secret, credential file, or authenticated remote URL is present in this repository.

### Immediate next actions

1. Treat `0d30a139cfe7f5945e73ef8ed8c6650e0db8d1e6` and its passing run as the verified stabilization checkpoint.
2. Discuss the stacked-PR merge/consolidation choice with the repository owner before changing PR bases, closing predecessor PRs, or merging.
3. After that decision, start the Phase 2A Outward/Field Assertion branch from the verified checkpoint (or a documentation-only descendant).
4. Preserve existing migration proof, Evidence Attempt identifier semantics, ATS current-read semantics, and legacy API compatibility while building the new vertical slice.

## 2026-10-01 independent live-review corrections — accepted by repository owner

This section supersedes only the current-status interpretations identified below. It does not rewrite or invalidate the historical observations earlier in this handoff.

### Latest exact-head green checkpoint

- Exact head: `313d275c37e051f2e57d2e731e7cf5add4d72694`
- GitHub Actions run: https://github.com/AnubhavDubey02/fresko-universe/actions/runs/36869705722
- Result: both `Smoke unit (Gate 1 / D4 / constants)` and `Bench install + migrate + run-tests (pinned v15)` passed.
- The root `AGENTS.md` from PR #5 is now carried forward on the integration branch so the handoff's repository-guidance reference is complete.
- Current dated status and temporal corrections are recorded in `docs/CANONICAL_STATUS_ADDENDUM_2026-10-01.md`.

This supersedes the earlier wording that treated `0d30a139cfe7f5945e73ef8ed8c6650e0db8d1e6` as the latest exact-head verified checkpoint. Any descendant created by these documentation-only corrections still requires its own exact-head run before it is described as green.

### Time-bounded acceptance-example corrections

These business examples are inputs for future Phase 2A/later acceptance coverage. The stabilization checkpoint does not implement them, prove the live balances, or contain executable cases for these exact values in the current 19-case WhatsApp readiness corpus.

- 447 unpriced Plum crates is a historical intermediate state demonstrating that physical Outward can precede price. It is not an assertion that the crates remain unpriced today.
- 180 unpriced Grapes crates is also a historical intermediate state. Later authorized rates exist for the final 180; preserve the earlier unpriced event and represent later pricing as a new source-backed, authorized assertion without backdating it into the physical movement.
- INR 101 is now classified as labour-related. It must remain outside customer/Sohail collections and customer receipt/allocation totals. This is a payment-classification boundary case, not merely a missing or unidentified receipt.
- INR 350,000 with `Authorization InProcess` is pending at that evidence time only. Do not infer later clearance without later source evidence.
- The provisional 92 × INR 700 and the 3,060-versus-3,056 comparison remain time-bounded evidence cases under the rules in the canonical-status addendum.

### Corrected next actions

The earlier immediate-next-action list is superseded by this sequence:

1. Keep PR #7 documentation/governance corrections separate from Phase 2A implementation and rerun full exact-head CI.
2. Do not merge, retarget, or close predecessor PRs without repository-owner authorization.
3. After the corrected stabilization head is green, create a focused Phase 2A branch from `313d275` or its documentation-only green descendant.
4. Before substantial Phase 2A coding, create `docs/CONTAINER_CYCLE_TO_CA_CONTRACT.md` on that focused branch.
5. Implement only `Fresko Field Assertion`, `Fresko Outward`, and `Fresko Outward Line` in the first Phase 2A slice, preserving the physical/commercial/collection boundaries above.

## 2026-10-02 Phase 2A physical-Outward foundation — Codex (Office/Cognizant environment)

This is a new dated implementation checkpoint. It does not rewrite the earlier stabilization history or authorize any merge, retarget, closure, or force-push of predecessor PRs.

### Branch, base, and commits

- Focused branch: `codex/phase2a-outward-assertions`
- Base: documentation-only green stabilization descendant `5b8641168c2ddfea5e45e09491bdcdc18a186e60`
- Base GitHub Actions run: https://github.com/AnubhavDubey02/fresko-universe/actions/runs/36881032528
- Business-contract commit: `556bb165f04e5dfa96deb4e8dc28888a556cb010`
- Implementation commit: `67b107cdb2b302a156143bc41c962f74e3e39bc6`
- Contract: `docs/CONTAINER_CYCLE_TO_CA_CONTRACT.md`

The contract was committed before substantial runtime coding. It connects Container, physical inward, Outward, Deal, future Collection/Allocation, supplier/cost/FX/expense ledgers, Exceptions, settlement, and CA-ready output while keeping their truth layers separate.

### Implemented in the first slice

- Added `Fresko Outward`, `Fresko Outward Line`, and rate-scoped `Fresko Field Assertion` DocTypes with controlled service-only mutation, maker/checker separation, append-only audit fields, and read-only Desk records.
- Physical Outward posting does not require a Deal, buyer, customer, or rate. An optional same-Container Deal is reconciliation context only and is checked through Deal ACLs.
- Posted physical quantities are derived only from posted Outward plus full compensating reversals. `Fresko Deal.dispatched_qty` remains compatibility-only and is neither read nor written by the physical ledger.
- Raw source event/line identifiers and raw lot, quantity, UOM, and rate strings are preserved verbatim beside normalized fields.
- Source identity plus identical payload is idempotent. A changed Outward payload under the same identity fails closed and records a `COMMITTED_INDEPENDENT` `Fresko Evidence Attempt` with operation `OUTWARD_CREATE` and conflict outcome.
- Unpriced Outward is permitted and opens `OUTWARD_UNPRICED`. Missing commercial context opens `OUTWARD_WITHOUT_DEAL`; unmapped source-backed lot quantity opens `LOT_UNRESOLVED`.
- A known rate assertion requires currency, rate UOM, effective time, evidence, and maker/checker review. Rate UOM must match its line or every line for a header assertion. Corrections supersede an active assertion; they do not mutate it.
- Container-first locking plus current reads protect mapped-lot and whole-Container physical capacity, concurrent posting, reversal uniqueness, assertion activation, and multi-line unpriced resolution. Cross-UOM arithmetic is rejected until an authorized conversion model exists.
- Container inward quantity, lot quantity, and UOM cannot be changed below or against net posted physical truth.
- The additive Container API now separates physical, commercial, assertion, exception, and provenance sections. It labels the legacy Deal dispatch scalar explicitly and includes live `as_of`, timezone, version, record IDs, and raw line provenance. It also states `LIVE_OPERATIONAL`, `is_frozen=false`, `is_reconciliation_snapshot=false`, and `is_ca_ready=false`.
- The Phase 1-to-current upgrade proof migrates twice, verifies all three new tables/critical fields/options/unique reversal link, proves no Outward or Assertion is fabricated, and proves an exact legacy `dispatched_qty=3.25` remains unchanged.

### Verification completed locally

- Offline smoke suite: 150/150 passed.
- WhatsApp readiness fixtures: 19 validated.
- Readiness contract tests: 6/6 passed.
- All 13 DocType JSON files parsed successfully.
- Relevant application/test/migration Python compilation passed.
- `git diff --check` passed; only local LF/CRLF conversion notices were emitted.
- An independent final team review found no concrete release blocker or likely pinned-Frappe/MariaDB syntax failure.

The new Bench suite contains 19 integration cases, including real two-connection races for competing physical posts, distinct reversals, initial rate assertions, superseding rate assertions, and concurrent completion of two line rates. This device has no configured Frappe Bench/site, so those tests and the twice-migrate proof remain **PENDING GitHub Actions** at this checkpoint. Do not call `67b107c` exact-head green until its own workflow completes.

### Explicit first-slice boundaries and next increments

- Field Assertion is rate-only in this slice; it is not yet a generic fact framework.
- The 3,060 declared-shipping versus 3,056 operating-inward case is not yet represented by a declared-quantity fact or an executable `PHYSICAL_VARIANCE` workflow. The exception type and close gate exist, but no variance should be claimed opened, resolved, or waived.
- There is no purpose-built maker/checker Desk UI or report page yet. The operational surface is controlled whitelisted services plus read-only DocTypes and the Container snapshot.
- Buyer mapping/commercial matching, Collections, Payment Allocation, INR 101 labour classification/payment treatment, any later evidence for INR 350,000 clearance, supplier invoice/remittance, FX/bank charges, expenses, Container Settlement, CA package generation, and ERP/accounting postings remain unimplemented.
- The current snapshot is a live operational view, not a frozen reconciliation, settlement, statutory, or CA-ready output.
- No predecessor PR was merged, retargeted, closed, rebased, or force-pushed by this work.

Next: publish this branch as a draft PR targeted to `codex/integration-stabilization`, run the full pinned workflow, fix real failures without weakening race expectations, then record exact-head CI evidence. After that, the next practical increment is a small internal Desk pilot surface plus declared-shipping/inward variance capture; payments/allocations remain a separate later slice.
