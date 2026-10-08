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

### First exact-head GitHub verification

Draft PR #8 was created against `codex/integration-stabilization`: https://github.com/AnubhavDubey02/fresko-universe/pull/8.

GitHub Actions run https://github.com/AnubhavDubey02/fresko-universe/actions/runs/37019856650 passed against exact PR head `06763bafcb3f4e123aef3c17b5bade74efe3e76f`, which includes the contract, implementation, tests, migration proof, canonical-index update, and the dated checkpoint above:

- `Smoke unit (Gate 1 / D4 / constants)` passed in 6 seconds.
- `Bench install + migrate + run-tests (pinned v15)` passed in 6 minutes 12 seconds.
- The Bench job completed fresh installation/migration, the full application tests including the Phase 2A MariaDB concurrency cases, the Phase 1-to-current upgrade, and the second idempotence migration.

No runtime corrective commit was needed after this run. The documentation-only descendant that records this result still needs its own exact-head checks before it can supersede `06763ba` as the latest verified branch tip.

## 2026-10-02 business-decision lock after real-data review

This documentation checkpoint records repository-owner decisions made after the
read-only comparison of the Phase 2A model with the supplied Plum, Grapes, CA,
and operations-handover evidence. It does not claim runtime implementation,
authorize a merge, or rewrite the earlier evidence cut-offs.

Canonical detail is in
`docs/CANONICAL_BUSINESS_DECISIONS_2026-10-02.md`; the locked summary is in
`docs/DECISIONS.md`.

### Decisions locked

- INR 101 is a labour payment/outflow, not a customer receipt, and stays outside
  customer/Sohail collections, allocations, and receivables.
- INR 350,000 was received. Earlier pending evidence remains historical;
  received, bank-cleared, and allocated are still distinct states.
- The source context for 92 at INR 700 is Sohail's handwritten working supplied
  through photos. The exact photo must be linked and the rate role-approved
  before activation; the physical Outward is never rewritten.
- Buyer-alias mapping is role based: Trader/Salesperson proposes, Accounts
  verifies, and Fresko Approver approves first-time or conflicting mappings.
  Raw aliases and superseded mappings remain immutable history.
- A future supplier-facing user sees only its own approved published
  supplier/container settlement view. Per-sale rate/amount, customers, internal
  Deals, collections, receivables, margins, and internal expenses remain denied
  server side.
- A contract-specific Supplier Settlement Value, when authorized, is separate
  from internal actual sales and may never overwrite or masquerade as them.

### Implementation status and next step

No runtime, schema, permission, migration, fixture, or test behavior is changed
by this documentation checkpoint. PR #8 remains the focused physical-Outward
slice.

The next best implementation slice is a real-data shadow-replay gate: first add
the P0 fact boundaries needed to reproduce the Plum/Grapes cut-offs without
inference, then role-based alias approval, then Collection/Payment Allocation.
Excel remains the operational source of truth during the shadow pilot. Supplier
portal implementation stays after internal Supplier Invoice/Remittance/
Settlement ledgers and server-side isolation tests exist.

The pre-change branch tip for this documentation checkpoint was
`5e407a99d51c7d589022a64413c56e47867306cb`, whose exact-head GitHub Actions run
was green as previously recorded. Any commit containing this new documentation
still requires its own exact-head CI before it is described as green.

## 2026-10-03 real-data shadow-replay and quantity-boundary iteration

This is a focused local implementation checkpoint on
`codex/real-data-shadow-replay`, based on business-decision commit
`3998ca70ff044d48f83be4873fb3f0595336e679`. The implementation and replay
checkpoint through `ff4002f03e7532f9d227fea74cbac81ae5e37bcc` is pushed;
exact-head CI verification remains pending.

### Implemented

- Added a sanitized real-data shadow-replay manifest pinned to the reviewed
  Plum, Grapes, and CA workbook hashes/ranges. It reproduces the dated totals
  and rejects quantity-basis overwrite, pending-DO stock effects, INR 101
  collection contamination, INR 350,000 state conflation, invented GP/rate
  allocation, and unsupported 92-at-700 activation.
- The 92-at-700 source is explicitly a pending Sohail handwritten photo with no
  fabricated hash. It remains verification-pending until the exact photo and
  role approval are linked.
- Added immutable `Fresko Container Quantity Assertion` facts for
  `DECLARED_SHIPPING`, `CUSTOMS_DECLARED`, and `OPERATING_INWARD`, with evidence,
  canonical Decimal text, maker/checker, idempotency, locking, supersession, and
  read-only reconciliation projection.
- Declared 3,060 and operating inward 3,056 now coexist and project variance 4
  as `OPEN_VARIANCE` without changing Container.inward_qty, stock, or ATS.
- Added optional raw `gatepass_no`, `vehicle_no`, and `raw_party_name` to
  physical Outward. They participate in payload conflict detection, survive
  compensating reversal, and appear in physical snapshot provenance. Raw party
  text does not resolve Customer.
- Added migration proof for the new quantity assertion table/fields/options,
  unique key, zero fabricated facts, and preservation of existing Container
  inward/UOM values across two migrations.
- Added `docs/COMMERCIAL_EVENT_ALIAS_CONTRACT.md` as the reviewed contract for
  the next runtime slice: multi-lot Commercial Sale, many-to-many Sale/Outward
  allocation, unallocated price buckets, and Trader -> Accounts -> Approver
  reusable alias decisions. The contract is documentation only.

### Local verification

- Offline/unit/static suite: 153 tests passed.
- Real-data shadow replay: manifest validated; 17 tests passed.
- WhatsApp readiness: 19 fixtures validated; 6 contract tests passed.
- All 20 repository JSON files parsed.
- Relevant Python compilation and `git diff --check` passed; only local CRLF
  conversion warnings were emitted.
- New Bench integration tests cover quantity lifecycle, maker/checker,
  idempotency conflict, 3,060/3,056 projection, no inward mutation, unknown/UOM,
  supersession, cross-UOM behavior, and a two-connection competing activation.

### Remaining gates and intentional boundaries

- No local Frappe Bench/site exists, so the new integration/concurrency tests
  and twice-migrate upgrade proof remain **PENDING GitHub Actions**.
- The variance projection does not yet create a persistent `PHYSICAL_VARIANCE`
  Exception because the current exception helper is Outward-scoped. The app
  must not claim that exception opened, resolved, or waived.
- No maker/checker Desk screen exists for quantity assertions.
- Commercial Sale, alias mapping, Collections, Payment Allocation, supplier
  ledgers/portal, settlement, ERP posting, and CA output remain unimplemented.
- Excel remains the operational source of truth during the shadow pilot.

Next: run exact-head CI/Bench on the pushed branch and fix real failures without
weakening tests. Only after that gate should the Commercial Event/Alias contract
become runtime work; Collections/Payment Allocation remains the following
separate slice.

## 2026-10-03 PR #9 assurance correction iteration

This section supersedes only the over-broad current-state claims in the two
preceding 2026-10-02/03 sections. Historical source cut-offs remain preserved.

- ATS now caps aggregate commercial capacity at the lower of legacy Container
  inward and an active same-UOM `OPERATING_INWARD` assertion. It does not invent
  a lot-level shortage allocation; a cross-UOM operating fact fails closed.
- Compatibility fallback is labelled `LEGACY_UNVERIFIED`.
- `DUPLICATE_GATEPASS` is a review Exception, not a posting rejection. Raw
  values are preserved, normalized comparison is Container-scoped, the two
  Outwards are linked, and self/multi-line/reversal cases are excluded.
- CI now guards protected immutable DocTypes from direct `db.set_value`,
  `db_set`, and protected/dynamic write-SQL bypasses in runtime code.
- Bench coverage includes a sanitized Plum aggregate through real quantity and
  Outward services, System Manager maker/checker denial, and concurrent
  quantity activation versus Outward posting under the shared Container-first
  lock order.
- Fixtures use synthetic non-resolving source/member identifiers. The INR
  350,000 fixture remains `PENDING_EVIDENCE_BINDING`; no raw bank reference is
  committed. The 92-at-700 photo context remains pending.
- Role-based alias approval and supplier isolation are accepted principles;
  exact role transitions and supplier-visible fields remain **PROPOSED**.
- Structured QC is formally deferred. The interim shadow-pilot control is one
  dated photo folder per Container, which does not create structured QC facts.
- `PHYSICAL_VARIANCE` persistence, reusable schema-migration harness, and the
  periodic integrity checker are separate owner-authorized post-PR #9 PRs.
- Server Scripts disabled on a target site remains **UNKNOWN** because no
  deployment or real-data site is authorized or in scope.

The shadow manifest and INR examples are fixture-validator/decision behavior,
not Collection, Payment Allocation, accounting, bank-clearance, or runtime
financial behavior. Exact-head GitHub CI remains the merge gate for this
iteration; CI history is the record and no green-status ceremony commit is
required.

## 2026-10-03 landed stack and paused migration-harness handoff

This is a worktree checkpoint for the next coding agent. The repository owner
asked this session to stop because the current Codex allowance was nearly
exhausted. It does not claim that the work-in-progress files below are tested,
reviewed, committed, pushed, or ready to merge.

### Landed state

- PR #2 merged with merge commit
  `32b3f997b9c4e40b7ebb0eeaaeaccf3e9cf61fdf`.
- PR #7 merged with merge commit
  `20b50d3fbb7b0d93a0a31cdae0a7f7be860538ed`.
- PR #8 merged with merge commit
  `cabb379cade502824e2e737bb0aa628346fdf721`.
- PRs #3 through #6 were closed as superseded; their branches were retained.
- PR #9 exact head
  `37d1c3f2ea2e222ca4a8830548cdb6a9499ea6fa` passed GitHub Actions run
  `37082266645` (Smoke and pinned Bench) and merged with merge commit
  `d955e8ca4433663eebf94aabaf38d24947e243e5`.
- No business fact was newly marked CONFIRMED, no deployment or real database
  was touched, and no history rewrite, force-push, branch deletion, repository
  setting change, Commercial Sale, Collection, Allocation, or ERP posting was
  performed.

### Paused worktree state

- Current branch: `codex/reusable-migration-harness`.
- Base/current committed HEAD:
  `d955e8ca4433663eebf94aabaf38d24947e243e5` from `origin/main`.
- Three untracked draft files exist:
  `scripts/run_schema_migration_harness.py`,
  `scripts/schema_migration_proofs.json`, and
  `scripts/test_schema_migration_harness.py`.
- The draft attempts to centralize proof registration, site lifecycle, ordered
  stages, rollback, and failure propagation while preserving the two existing
  seeded proof modules. It was interrupted while applying the wider patch.
- **No CI workflow or Bench-script integration was applied.** The draft has
  not been run even through its offline tests. The next agent must inspect it
  as untrusted work in progress rather than assume it is correct.

### Authorized continuation order

1. Review the three untracked draft files. Complete the reusable migration
   harness narrowly, wire `scripts/ci_bench.sh` to one harness call per stage,
   add an offline CI validation, document its schema-PR-only rule, and run the
   full relevant local gates.
2. Commit and push only after review, open a small PR from `main`, and merge it
   only when Smoke and Bench are green at the exact head. Stop if the same CI
   issue fails twice.
3. From freshly updated `main`, implement persistent `PHYSICAL_VARIANCE` as a
   separate schema-changing PR using the reusable seeded harness. Do not infer
   or confirm quantities; use synthetic fixtures and deterministic links to
   the relevant quantity assertions.
4. From freshly updated `main`, implement the periodic protected-record hash
   integrity check as its own small PR.

Each new PR must start from merged `main`, not an unmerged PR. The standing
owner constraints remain in force: ask before marking any business fact
CONFIRMED, starting commercial/accounting runtime work, deploying, touching a
real database, deleting branches, rewriting history, force-pushing, changing
repository settings, or weakening a failing test. UNKNOWN/PENDING must remain
truthful rather than be converted into certainty.

## 2026-10-03 reusable migration harness completion (continuation step 1)

This section supersedes only the "Paused worktree state" above. The draft was
reviewed as untrusted work in progress and then completed on
`codex/reusable-migration-harness`.

- The review found that the draft's "fail the stage atomically" claim was false.
  Both proofs commit inside their own stages, so the harness now documents the
  real behavior: fail-fast in registry order, with a disposable upgrade site.
  Proof behavior is unchanged.
- `--validate-only` now also checks statically, without importing Frappe, that
  each proof defines all three stage functions. It fails when a
  `scripts/prove_*.py` module is unregistered or a path is registered twice.
- The draft's path-escape test wrote a file outside its temporary directory.
  It is now contained.
- `scripts/ci_bench.sh` makes one harness call per stage, replacing the six
  per-proof calls. The Smoke job runs the offline validation and its tests.
- The schema-changing-PR rule lives in `docs/SCHEMA_MIGRATION_PROOFS.md`.
- Local offline evidence covers Smoke, all four `scripts` suites, and every
  validator, run on an LF checkout with Python 3.10. On a Windows
  `core.autocrlf=true` checkout, the shadow-fixture repository-decision hash
  check fails because of CRLF conversion. That is an environment artifact, not
  a regression. `ci_bench.sh` was not run locally. Exact-head GitHub Smoke and
  pinned Bench remain the merge gate.

Continuation steps 2-4 above are unchanged.

## 2026-10-03 persistent PHYSICAL_VARIANCE (continuation step 3)

### Implemented

- Fresko Exception schema extended with five new read-only fields after
  `related_outward`: `declared_quantity_assertion` (Link), `operating_quantity_assertion`
  (Link), `variance_quantity` (Data), `variance_uom` (Link to UOM), `variance_key`
  (Data, unique). No data migration patch; Frappe model sync adds columns as NULL.
- Exception controller (`fresko_exception.py`) gains a quantity-scoped PHYSICAL_VARIANCE
  validation path: requires container, two distinct assertion links, non-empty non-zero
  `variance_quantity`, `variance_uom`, `variance_key`, and `flags.in_quantity_service`.
  Mutual exclusion prevents a row from carrying both outward and quantity links. All five
  new fields are immutable once set. Outward-scoped existing behaviour is unchanged.
- `quantity_assertion_service.py` gains `_ensure_physical_variance` (internal, called
  after successful ACTIVATE in `review_quantity_assertion`), `ensure_physical_variance`
  (public, checker role), and `resolve_physical_variance` (RESOLVE/WAIVE with notes).
  Variance key is sha256 of canonical JSON identity. Race replay via UniqueValidationError
  re-read. Never closes or modifies older variance exceptions.
- Projection (`quantity_reconciliation_projection`) adds `physical_variance_exception`
  key (read-only lookup by variance_key for the projected pair; None for legacy/unresolved).
  Updated `todo` strings to reflect that exceptions are now created automatically.
- Whitelisted wrappers `ensure_physical_variance` and `resolve_physical_variance` added
  to `quantity_assertion.py`.
- Close gate (`fresko_container.py:_validate_close_gate`) already blocks on
  PHYSICAL_VARIANCE by container — no change needed.
- Migration proof `scripts/prove_physical_variance_upgrade.py` registered in
  `schema_migration_proofs.json` as id `physical_variance_exception`. Seeds one synthetic
  legacy OTHER exception on Phase 1 baseline, verifies five new columns exist with types,
  unique index on `variance_key`, seeded row unchanged, new columns NULL, zero rows with
  non-null `variance_key`, count unchanged. Second-migrate idempotent.
- Bench integration tests in `test_container_quantity_assertion.py`:
  `TestPhysicalVarianceException` class with 13 tests covering 3060 vs 3056, reverse
  activation order, idempotency, equal quantities, declared-only, legacy fallback,
  cross-UOM, supersession, close gate, WAIVE/replay/different-decision, blank notes,
  direct insert without flag, immutability, maker-only role.
- Offline static contract tests in `test_quantity_assertion_static.py`:
  `TestPhysicalVarianceStaticContract` with 7 checks covering schema fields, controller
  guard, service functions, wrappers, upgrade proof, projection key, inward_qty safety.

### CTO review hardening

- Quantity-scope fields are accepted only on `PHYSICAL_VARIANCE`, so a Desk row of
  another type cannot pre-claim a pair's `variance_key`. Service key lookups also
  filter on the exception type.
- `variance_quantity` must be a finite, non-zero decimal.
- The Container is immutable on a quantity-scoped variance. The resolve service
  re-checks it after taking the Container lock.
- A quantity-scoped variance cannot be deleted (`on_trash`); it can only be
  resolved or waived with notes.
- The close-gate Bench test routes `Selling -> Closing -> Closed` and matches the
  gate message, so an unrelated transition error cannot pass it vacuously.
- The upgrade-proof seed row has no Container link, so no dangling link is
  fabricated.

### Not implemented

- No auto-close of older PHYSICAL_VARIANCE exceptions when a new pair resolves.
- No legacy-fallback persistence (Container.inward_qty is not used as operating source
  for exception creation; only real active OPERATING_INWARD assertions).
- No Desk UI for the five new fields beyond read-only display.
- No inference of quantities, UOM, or timestamps.

### Bench evidence

PENDING CI. Offline gates (harness, protected-doctype, smoke, static, py_compile,
json.load) are the local merge evidence. Exact-head GitHub Bench remains the merge gate.

## 2026-10-03 LF pinning and schema-change detector

- PR #12 (merge `eed62be`) added `.gitattributes`. Text is LF on every platform
  and workbooks/images are binary. Renormalization changed no stored bytes. The
  hash-pinned shadow fixture now validates on a Windows `autocrlf=true` checkout.
- `scripts/check_schema_snapshot.py` and the committed `scripts/schema_snapshot.json`
  make the schema-changing-PR rule automatic. The Smoke job fails when the
  snapshot is stale, or when a pull request changes persisted schema relative to
  the base branch's snapshot without registering a new migration proof.
  `--update` refuses an unproven change. See `docs/SCHEMA_MIGRATION_PROOFS.md`.
- The detector covers declared schema only, not proof adequacy. Exact-head
  Smoke and pinned Bench remain the merge gate.
- Next authorized step: the periodic protected-record integrity checker. Its
  design is a separate baseline ledger: the checker hashes each record's
  immutable stored fields the first time it sees the record, then compares later
  reads against that baseline. It does not recompute the creation-time
  `payload_sha256`, because that hashes the request input as supplied and the
  database returns dates and decimals in a different format, so a recompute
  would raise false alarms. The checker detects post-baseline changes only and
  is a schema change with its own proof.

## 2026-10-03 protected-record integrity checker (continuation step 4)

### What it does

A periodic integrity checker runs daily (Frappe scheduler) and is also
callable on demand by System Manager or Fresko Approver. It scans every
Fresko Outward, Fresko Field Assertion, and Fresko Container Quantity
Assertion record. On first observation it creates a Fresko Integrity Seal
containing a canonical SHA-256 hash of the record's immutable stored fields
as read from the database. Later runs re-read with the same canonical reader
and compare.

If a payload hash or terminal-state hash no longer matches the sealed
baseline, or the record has been deleted, the checker opens a Critical
DATA_INTEGRITY Fresko Exception and records the mismatch on the seal.

### Baseline-ledger rationale

The creation-time `payload_sha256` hashes the *request input as supplied*
(e.g. `str(movement_at)` as typed by the caller), so recomputing it from DB
rows would raise FALSE integrity alarms (dates and decimals round-trip
through MariaDB in a different format). Instead, a separate baseline ledger
hashes the record's stored fields the first time the checker observes them,
using a deterministic canonical reader. This detects post-first-seal changes
only.

### Explicit limitations

- First run seals current state as baseline; does not prove pre-baseline
  integrity.
- Evidence/Attachment hashing is out of scope.
- Daily schedule needs a running Frappe scheduler; no deployment done.
- Migration never seals or blesses anything.

### Files added/changed

- `fresko_universe/fresko_universe/fresko_core/doctype/fresko_integrity_seal/`
  (DocType JSON, controller, `__init__.py`)
- `fresko_universe/fresko_universe/fresko_core/services/integrity_service.py`
- `fresko_universe/fresko_universe/integrity.py` (whitelist facade)
- `fresko_universe/fresko_universe/permissions.py`
  (`assert_can_run_integrity_check`)
- `fresko_universe/fresko_universe/hooks.py` (scheduler_events daily)
- `scripts/prove_integrity_seal_upgrade.py` and
  `scripts/schema_migration_proofs.json` (registered last as
  `integrity_seal_ledger`)
- `scripts/check_protected_doctype_writes.py` (added seal to protected set)
- `scripts/schema_snapshot.json` (updated)
- `fresko_universe/fresko_universe/tests/test_integrity_check.py` (9 Bench
  integration cases)
- `fresko_universe/tests/test_integrity_static.py` (7 offline static checks)

### Bench CI

PENDING CI. Offline gates (harness --validate-only, schema snapshot, smoke,
static, protected-doctype, py_compile, json.load) are the local evidence.
Exact-head GitHub Smoke and pinned Bench remain the merge gate.
### CTO review hardening

- After a record's terminal state (Posted, Rejected or Superseded) is sealed,
  each later run hashes the terminal fields whatever the current status. A
  direct write that moves a Posted Outward back to Draft therefore reports
  `TERMINAL_CHANGED` instead of looking non-terminal and counting as unchanged.
- Legitimate service transitions (submit, post, review, supersede) change only
  status and actor fields, which are outside the sealed payload. They seal the
  terminal state once and raise no mismatch.
- `RECORD_MISSING` exceptions cite the sealed payload hash.
### Known limitations (stated, not hidden)

- Only changes made after the first seal are detected. The first run treats the
  current state as the baseline.
- `Active` is not a sealed terminal state, because legitimate supersession
  later changes it. A direct write moving an `Active` assertion back to
  `Draft`/`Review Pending` is therefore not detected; its payload fields still
  are.
- The seal ledger is protected only at the application layer (service flag,
  immutability, `on_trash`, protected-write guard). A database-level actor who
  deletes or rewrites seal rows can defeat it. A raw-deleted seal is silently
  re-created as a new baseline.
- A Field Assertion first sealed after its Outward is gone gets a seal with no
  Container, so its integrity Exception blocks no Container close gate.
- Each run reads every protected record, with several queries per record. Use
  `limit` or batch the reads before large volumes.
- Integer, decimal and float values are canonicalized to one normalized decimal
  text, so a driver returning `Decimal` instead of `float` cannot raise a false
  alarm.

## 2026-10-03 PR #14 integrity audit-context correction and CI evidence

- PR #14 remained on `codex/protected-record-integrity-check`, based on merged
  `main` at `8c9bcdb9dcc70e884afa1f7c2faa56b23c22f183`.
- Runs #137 and #138 failed on the earlier Outward-line DocType/table-name
  defect. Run #139 (`37110405347`) tested
  `822a962c446cbccc6e1d2bafe7f3bf1fda854ac2`: Smoke passed, while Bench ran
  175 tests with one failure because a correctly Container-linked
  `DATA_INTEGRITY` Exception omitted the Container identifier from its
  human-readable description. These failed runs remain historical evidence.
- Commit `8c7a32e76130cb3d81fc49d228b563d49d998703` makes the description include
  `for Container <identifier>` only when the checker already knows the
  Container. It does not change hashes, mismatch kinds, severity, structured
  links, idempotency, seal state, or Container close-gate behavior. The
  existing Bench assertion was preserved.
- Local verification at that commit passed: the migration registry, protected
  write guard, real-data shadow replay, schema snapshot against `origin/main`,
  41 script tests, 169 app/offline tests, Python compilation, and
  `git diff --check`.
- Exact-head GitHub Actions run `37120995299` passed at
  `8c7a32e76130cb3d81fc49d228b563d49d998703`: Smoke passed in 7 seconds and
  pinned Frappe/ERPNext Bench passed in 6 minutes 26 seconds. The successful
  Bench step includes the app integration tests and all four registered
  Phase-1-to-current proofs through first migrate and idempotent second
  migrate.
- The integrity checker's previously documented limitations remain unchanged.
  No business fact was confirmed, no test was weakened, and no deployment or
  real operational database was touched.

## 2026-10-03 Commercial Sale backend slice and role controls handoff

- Continuing from user checkpoint and merged `main` at `579a8465f363105eb6e78c15cb173156e2c0df93`.
- User explicitly authorizes the Commercial Sale runtime slice:
  - Implements four DocTypes: `Fresko Commercial Sale`, `Fresko Commercial Sale Line`, `Fresko Party Alias Mapping`, `Fresko Sale Outward Allocation`.
  - Pure string decimal parsing (`Decimal`) for all numeric fields; no float corruption.
  - Immutable source payloads (`source_payload`, `payload_sha256`, `source_event_key`) and append-only versioned `decision_history`.
  - Reusable party alias mapping with approved `active_alias_key` and non-unique historical tuple justification.
  - Three-role segregation of duties (Maker Salesperson/Trader -> Verifier Accounts -> Approver) across distinct users; System Manager excluded from routine approvals.
  - Rate state distinguishes immutable maker `PROPOSED` from server-projected `FINAL`.
  - Pessimistic locking sequence: `Company` -> sorted `Container` -> `Sale`/`Outward` -> decisions.
  - Many-to-many Sale-to-Outward allocation with dual-sided caps, physical Outward validity, and compensation reversals on correction.
  - Server-side ACLs deny supplier roles access to internal commercial, deal, and customer records; master read restricted to internal roles.
  - Operational boundaries preserved: INR 101 labour outflow; INR 350,000 pending bank evidence; 92@700 pending handwritten photo + role approval; 3,060 declared vs 3,056 operating physical capacity. Collections, payments, UI, live WhatsApp ingestion, ERP posting, and deployment remain out of scope.
  - Registered fifth migration proof `commercial_sale_ledger` (`scripts/prove_commercial_sale_upgrade.py`).
- Status: Code IMPLEMENTED; exact-head Smoke and pinned Bench CI remain PENDING. Read functions are evolving; no final completeness or passing tests are asserted merely because code was written.


## 2026-10-04 — Money/Reconciliation and native workspace candidate

- Commercial PR #15 merged at main `b140b800b021c4317931e37a723a140740b2fc4c`; post-merge run [37143711405](https://github.com/AnubhavDubey02/fresko-universe/actions/runs/37143711405) succeeded.
- Candidate branch: `codex/money-reconciliation`, based on that exact main. Four money roots, service-only workflow, evidence byte snapshots, many-to-many payment/adjustment applications, dual-cutoff projections, supplier isolation, compensation on commercial corrections, and controlled receipt Exceptions are implemented.
- Native Pages: `fresko-workspace` and `fresko-money`; deterministic Ask Fresko read catalog. No provider/WhatsApp/OCR/deployment or new dependency.
- Sixth registered migration proof `money_reconciliation_ledger` preserves prior records and creates zero money rows. CI also upgrades from the exact merged commercial baseline and repeats migration. These database proofs are PENDING until candidate CI runs.
- Local verification at candidate checkpoint: 210 app/offline tests and 41 script tests passed; operations UI Node VM harness passed. 33 new real Bench money tests compile but have not run locally; no local Bench executable. Both money and operations Page VM harnesses pass; final exact-head gates are PENDING.
- Documentation: `docs/MONEY_RECONCILIATION_RUNTIME.md`, `docs/OPERATIONS_WORKSPACE.md`. Private Drive review/agent usage ledger remain outside Git.
- Resume from actual branch/status and live checks. A candidate or a passing ancestor is not a shipping claim. Current candidate requires Smoke + pinned Bench, all six first/second migration proofs, exact-commercial-baseline upgrade/rerun, and independent review before integration.


## 2026-10-03 — PR #16 first CI failure and runtime repairs

- PR #16 first head `5ad6acc45b2ff6b7a37edd3dd82d650879e83222`, run [37147557055](https://github.com/AnubhavDubey02/fresko-universe/actions/runs/37147557055): Smoke passed; pinned Bench ran 252 tests with zero failures and five errors. Four errors came from missing File-hook method arguments; Collection supersession failed because a parent ID was written into a child-only successor Link. Migration proofs were not reached in this run.
- Repairs accept Frappe File-hook invocation, retain parent correction lineage without cross-type child links, and apply the same rule to adjustment compensation. Unchanged proposal replay returns the original audit record after parent reversal/correction; blank optional form links are normalized and contradictory Container parking targets rejected. Container/customer projections retain partial known gross subtotals while full totals remain unknown. The Exceptions read endpoint accepts the native Page POST call.
- Independent Luna review reproduced the retry and compensation defects and added actual-helper regressions. Local verification: 215 app/offline tests, 41 script tests, both Node UI harnesses, schema/fixture/protected-write gates, Python/JSON parsing and diff checks passed. The money Bench module now has 39 methods; local Bench remains unavailable. Fresh exact-head CI and all six migration proofs remain required before integration.


## 2026-10-03 — PR #16 shared File identity correction

- Run [37148698924](https://github.com/AnubhavDubey02/fresko-universe/actions/runs/37148698924) at `e1236773c081cfcf19f008180ab78ee0313d106b`: Smoke passed; Bench ran 258 tests with one failure and one cleanup error in the same File-byte binding case. Earlier hook/correction failures were repaired. Migration gates were not reached.
- Pinned Frappe `save_file` can reuse a content URL across distinct attached File documents. Money evidence now selects the uniquely attached Evidence File, accepts a unique legacy URL record, and rejects ambiguous candidates; source binding and read ACLs share the same resolver. Tests retain exact File identity and actual-byte assertions, explicitly create shared-URL attachments, and clean only their synthetic sources.
- Independent Luna reviewed the resolver and added ambiguity/selected-ACL regressions. 218 app/offline tests pass locally; 39 money Bench methods compile. A fresh exact-head Smoke + pinned Bench and migration run is still required.


## 2026-10-03 — PR #16 pinned Attach-field correction

- Run [37149479176](https://github.com/AnubhavDubey02/fresko-universe/actions/runs/37149479176) at `f4ec6900ae06fd94a95047d528dbfeb136082cba`: Smoke passed; 258 Bench tests, zero failures and one File-identity ambiguity error. Pinned `attach_files_to_document` requires the attachment field as well as parent identity, and creates a field-specific reference when an existing upload omits it.
- The source fixture now passes `df="file"` and asserts the exact shared-URL File ID set after both Evidence saves. The resolver prefers the exact Evidence `file` attachment, then a unique parent-only or legacy URL match; same-specificity ambiguity still rejects. This narrow framework escalation was independently checked, with no skipped tests or weakened identity assertions. Fresh exact-head CI remains required.

## 2026-10-04 — Implementation 01 pilot safety repair candidate

- Base/current merged main verified live: `335974c6562dbb91b56ba0df0f3457483e3fb1da`.
- Branch: `codex/pilot-safety-debt`, reused clean managed worktree; original dirty checkout preserved.
- Reproduced old close gate admitting all eight specifically requested current Commercial/Money types, unreachable child CONFLICT branch, and incomplete provider identity reaching unscoped legacy insert (offline actual-function reproduction).
- Added current explicit policy and Company-before-Container/current-read validation with receipt attribution; no ledger refresh or source mutation. Provider guard is non-whitelisted; historical ingest retained. No persisted schema changes; six existing proofs remain required.
- Astra reviewed design; native Gemini 3.8 Flash produced the bounded pure policy/offline tests; Codex integrated and added database acceptance. Luna independently reviews the actual candidate diff. Exact-head pinned CI and review findings govern acceptance, not this candidate note.
- Local complete offline/static: 222 tests passed; scripts: 41 passed; fixture/write/schema guards and both actual-source JavaScript harnesses passed. Pinned Bench/all migration proofs still require exact-head CI; final SHA/counts/run URLs will be supplied from immutable CI evidence.
- Governing repair/limits: `docs/PILOT_SAFETY_CLOSE_POLICY.md`. No next milestone started. Next recommended bounded packet is deployment packaging and real browser baseline, after this packet is green and reviewed.


## 2026-10-04 — Implementation 02 preparation

Post-PR17 main is `104c488fa0765a7b13b1c99d553b3be65b36c848`; main CI
[37193221292](https://github.com/AnubhavDubey02/fresko-universe/actions/runs/37193221292)
is green. Work starts on `codex/deployment-browser-baseline`.

Current deployment/browser/recovery authority is
`docs/STAGING_DEPLOYMENT_BROWSER_BASELINE.md`. The user selected a new Frappe
Cloud private bench but has no account/site connected and has prohibited paid
purchases without approval. Complete preparation and review before the account
connection/billing checkpoint. Temporary loopback/CI browser and restore sites
are synthetic verification environments, not deployed Cloud staging. Preserve
all previous handoff entries as historical evidence.

Local baseline verification: 270 pinned Bench tests, 222 application/static
tests, 49 script tests and both Node UI harnesses pass. Native browser execution
is being completed; candidate files and these counts do not establish exact-head
GitHub green or Cloud deployment. No DocType schema change is intended.

### Implementation 02 — browser-derived Commercial repair

Native Sale submission reproduced `STALE_VERSION`: historical snapshots omitted
version and JavaScript null arrived as an empty form token. The runtime now
distinguishes Live `current_version` from Historical `version_at_cutoff`;
explicit Workspace cutoffs are read-only. All 15 existing-record Commercial
HTTP mutations require valid tokens after role checks. Direct Python `None`
compatibility and existing immutable audit snapshots remain unchanged.

Minimal accompanying repairs preserve native Page filters, use actual allocation
queue fields and reject obsolete Money/Workspace read responses. Independent
Luna review covered the runtime contract, packaging and synthetic recovery guards;
Astra reviewed the version design. No posted Physical/Commercial/Money truth or
persisted schema is changed to manufacture reconciliation.

Preparation checks: 228 application/static tests, 49 script tests, both Node
harnesses and schema/write guards pass; focused Commercial Bench is 49/49.
A complete rerun on the reused local site failed on durable legacy fixture
collisions (275 tests; 3 failures, 10 errors). The full gate is being repeated
on a new isolated site, with no assertion weakened. Pinned Frappe only propagates
test failure exit status when `CI` is set, now explicit in the CI launcher.
Native acceptance is continuing on a clean synthetic restored site; earlier
partial Sales/alias decisions are preserved. Exact-head CI, completed browser
flows and hosting evidence must be recorded before final acceptance.

Fresh-site result for preparation commit
`26f8cd51702786f662d8a7a8ba0a9c4710a8ae1c`: installation and migration succeeded;
275 pinned Bench tests passed in 605.661 seconds, zero failures/errors. This
replaces the reused-site failure as the current local complete-test evidence;
it remains separate from exact-head GitHub and hosting acceptance.

Draft PR #18 is open. Exact-head run `37209321660` at `26f8cd5` passed Smoke,
275 pinned Bench tests and all six migration proofs on first and second migrate.
The overall Bench job failed in native browser acceptance (three timeouts and a
Supplier denial assertion); the recovery CI step did not execute. Subsequent
native harness repairs and missing race/replay coverage require a new exact-head
run and independent review. No merge or Cloud deployment is claimed.

Follow-up focused native checks passed: delayed actual Workspace/Money responses
preserve the newer cutoff; historical/receivable/exception views and stale Money
tokens preserve approved truth; exact Collection source replay returns one
record; Supplier and mixed-role direct URL/API denial holds. The harness now
fails required missing workflow IDs/skips and preserves a rejected artifact
destination. Complete fresh desktop/mobile CI and final independent review
remain required; existing approved desktop synthetic records were preserved.

Mobile harness investigation reproduced Escape closing the Collection dialog
after Customer selection and Tab opened its Datetime picker. Native dialog-heading
click dismisses only the picker and retains Customer. The Page/dialog-aware Link
getter remains required on both paths. Partial 390/360 allocation proposals are
preserved; complete acceptance uses a fresh fixture instead of recreating them.

Exact-head run `37229099731` at `b89e9e1` passed Smoke (228 app/static plus
49 script tests), 275 pinned Bench tests and all six first/second migration
proofs, including exact Commercial/Money baseline upgrades. Native desktop,
360/390 financial workflows, dialog preservation, actual delayed-response races
and Supplier/mixed denials passed. Seven browser tests ran in 507.353 seconds;
one saved Container-receivable check failed, zero errors/skips. Recovery was not
reached. The Link helper was reading visible input before native validation and
its change callback completed. It now waits for the committed Control state.
Clean-fixture Container/Customer debt assertions are 4000/12000; legacy local
unpriced drafts are not acceptance truth. A separate native unpriced Sale read
asserts null gross/debt and PENDING before rate approval. No app runtime/schema
change accompanies this harness repair; a fresh exact-head complete gate is
required before deployment-ref publication.

## 2026-10-06 PR 18 GCP staging and Supplier security checkpoint

GCP staging is live at `https://fresko-staging.34.93.162.135.sslip.io`
(project `project-86f9787f-03f9-4f7e-b10`, VM `fresko-staging-vm`,
`asia-south1-a`). The dated 2026-10-05 report proves source
`f593990dc3457bfa5c54e9c0524c2f7cd974cd11`, app export
`afea097fe5ada1e1f390e4b6b12daf08ee6876ba`, pinned Frappe/ERPNext,
275 VM Bench tests, seven external browser tests, a GCS encrypted
download/decrypt roundtrip and a separate isolated four-component restore.
It does not prove a later source. See
`docs/STAGING_DEPLOYMENT_BROWSER_BASELINE.md` for the staging infrastructure,
manual off-VM replication and restore limits. The earlier Frappe Cloud
pending state is superseded for this GCP deployment, while a physical touch
device and disruptive reboot test remain pending.

A live Supplier check on that deployed source reproduced mixed-role Evidence
child list disclosure: 14 Attachments and 45 Attempts returned through list
requests, although individual documents denied access. The PR 18 source
repair now adds an authenticated HTTP Supplier guard and child list/document
hooks. Exact-head CI, immutable export publication and live retesting of
Supplier/API-key denial, Accounts private Evidence access and the three
operator accounts are still required before claiming closure. Administrator
is denied by the HTTP guard when carrying Supplier; trusted offline
Administrator Evidence hooks retain their existing bootstrap exception.
The three old operator credentials are held in an owner-only private handoff;
the current rotation vault remains an owner-only recovery copy. Never print,
commit or include passwords in artifacts.

## 2026-10-06 PR 18 browser harness repair checkpoint

The exact-head CI run 37395548094 on commit 5f25019a10b54620cd6e64da91dafbdf3ef1e06e
passed Smoke unit, Bench initialization, app installation, migrations, backend Fresko
tests (275 passed), and migration proofs, but failed at the browser gate (1 failure, 5 errors).
Root cause diagnosis established:
1. `test_supplier_and_mixed_denials`: BrowserSession._authenticate previously waited for
   the browser URL to leave `/login`. Under the new HTTP Supplier guard, navigation to
   internal Desk routes is denied at the HTTP boundary, causing the browser to remain
   on `/login` or render 403. The harness now supports `expect_desk=False` for Supplier
   identities and verifies authenticated session state via `frappe.auth.get_logged_user`
   which is explicitly permitted for authentication verification.
2. `test_desktop`, `test_mobile_360`, `test_mobile_390`: Following sale creation, the native
   workspace issues a `frappe.msgprint` alert alongside dialog hiding. Without explicit
   dismissal, the message modal and backdrop obstructed the subsequent click on the
   `[data-tab-id="sales"]` navigation element, triggering a 30s actionability timeout.
   `inspect()` now dismisses pending messages and purges orphaned backdrops, and `scenario()`
   waits for dialogs to hide and dismisses messages after operational creation steps.
3. `test_saved_state_historical_receivables_and_exceptions`: Failed due to missing saved
   progress after `test_desktop` timed out prematurely.

All offline unit tests (228/228) and script suites (49/49) pass. No financial or
commercial runtime semantics, money calculations, or database schemas were altered.

## 2026-10-06 PR 18 browser harness login synchronization repair

Exact-head CI run 37403417243 confirmed that the modal dismissal and backdrop purge
resolved all 6 core workflow tests (`test_desktop`, `test_mobile_360`, `test_mobile_390`,
`test_native_links_preserve_collection_dialog`, `test_saved_state_delayed_real_responses`,
and `test_saved_state_historical_receivables_and_exceptions`). The only remaining failure
was `test_supplier_and_mixed_denials` at `browser_support.py:_authenticate:47`.
Root cause:
- `BrowserSession._authenticate` used `page.wait_for_function` with an async promise that
  resolved to false on the first frame before the login AJAX call arrived. Playwright's
  `wait_for_function` treated the fulfilled promise as completing the wait, causing
  immediate assertion against `frappe.auth.get_logged_user` before session cookies settled.
- Repaired `_authenticate` to explicitly synchronize on the login POST response (`cmd=login`)
  via `expect_response`, and poll `context.request.get` for `frappe.auth.get_logged_user`
  with bounded retries until the session identity matches the expected user.
- Offline unit tests (228/228) and script suites (49/49) remain fully green.

## 2026-10-08 PR 19 Fresko Clear Operator UX P0 implementation checkpoint

Branch `flash/operator-ux-p0` created from merged `main` at `c01707708c69d880a829ebf670a2cfc8e76edb42`.
PR #18 is confirmed merged; post-merge CI run 37420490326 passed 100% green.

PR #19 P0 Implementation scope and contract reconciliation:
1. Architecture & Capabilities:
   - Implemented single deliberate `extend_bootinfo` hook in `fresko_universe/boot.py` exporting `bootinfo.fresko = {persona, capabilities, default_route, is_operator}`.
   - Enforced Supplier-first denial precedence: any role containing "supplier" immediately returns `persona: "supplier_denied"`, empty capabilities, and `is_operator: False`.
   - Preserved System Manager standard technical Frappe desk (`is_operator: False`, `default_route: "Workspaces"`).
   - Applied command-specific operational capabilities across Salesperson, Accounts, and Approver roles, with Approver > Accounts > Salesperson landing precedence and a safe non-operator fallback.
   - Guaranteed zero financial balances or counts in boot data.
2. Shell Branding & Desk Chrome Suppression:
   - Added SVG brand assets (`fresko-logo.svg`, `fresko-favicon.svg`).
   - Implemented scoped `fresko_shell.css` suppressing technical Desk chrome (`.search-bar`, `.dropdown-help`, `.dropdown-notifications`, `.layout-side-section`, `.page-breadcrumbs`) strictly when `body.fresko-operator-shell` is present. System Manager retains standard Frappe chrome.
   - Implemented `fresko_login.css` with clean produce-trade styling.
   - Implemented `fresko_shell.js` with reversible user-scoped router guard (`fresko_initial_routed_<user>`), dynamic soft-keyboard collision avoidance, and body class tagging.
3. Needs My Action Feed Service (`operator_service.py`):
   - Created `fresko_universe.fresko_core.services.operator_service` strictly using `frappe.get_list` and authorized read getters.
   - Enforced AST-guarded prohibition on `frappe.db.sql`, `frappe.get_all`, and `ignore_permissions=True`.
   - Enforced Supplier-first denial, permitted company validation, and individual record read permission checks.
   - Scoped linked Evidence authorization: restricted evidence references are omitted (`evidence_state: "RESTRICTED"`).
   - Rebuilt action feed lifecycle states (`REVIEW_PENDING` collections, derived `eligible_available_amount`, non-cash bank clearance, actual `Open`/`In Progress` exceptions, superseding sale revision rate proposals, approved-but-unpriced sales).
   - Pure segregation-of-duties `check_action_eligibility` enforcing maker-verifier-approver isolation and read-only historical projections.
4. UI & Workspace Integration:
   - Integrated "Needs My Action" tab and Linear-style split pane (60% action feed left, 40% details & evidence inspector right) into `fresko_workspace.js` and `fresko_workspace.css`.
   - Mobile touch targets meet the >= 44px (>= 48px primary) floor, with full horizontal overflow containment.
5. Verification Evidence:
   - 260/260 offline smoke and contract unit tests pass (including 32/32 tests in `tests.test_operator_contract` covering boot capabilities, AST bans, segregation of duties, positive company scoping, strictly live-only enforcement, and schema field mapping).
   - 49/49 script tests pass under WSL Linux.
   - Node VM offline UI test suites pass (`test_workspace_ui.cjs`, `test_money_ui.cjs`).
   - Protected DocType write guard, schema migration proofs, and schema snapshot checks pass.


## 2026-10-08 PR 19 QA remediation pass — Operator UX P0 defect closure

Branch: `flash/operator-ux-p0`
Draft PR: #19 (https://github.com/AnubhavDubey02/fresko-universe/pull/19)
Base commit: `c01707708c69d880a829ebf670a2cfc8e76edb42` (PR #18 merged `main`)

Addressed all defect findings from the independent QA audit without modifying database schema, financial calculation rules, or Supplier deny-first invariants:

1. **FR-QA-008 (Native 403 Page Heading Preservation)**:
   - Scoped `.page-card-head::after` ("Produce Trade OS") and `.page-card` styling in `fresko_universe/public/css/fresko_login.css` strictly to `body.login-page`, `body[data-route="login"]`, `.for-login`, and `.page-card.for-login`.
   - Native Frappe error pages (such as 403 Not Permitted `<span class="page-card-title">Not Permitted</span>`) retain their original DOM title and accessible names without pseudo-element decoration.

2. **FR-QA-009 (Outward Schema Alignment)**:
   - Removed nonexistent `version` field from `Fresko Outward` query in `operator_service.py`. No synthetic version token is generated for physical movements.

3. **FR-QA-010 (Real Workflow Status and Verification Tracking)**:
   - Querying real persisted `status` and `state` columns, along with `prepared_by`, `proposed_by`, `verified_by`, and `verified_at` across Collections, Aliases, Allocations, and Payment Allocations.
   - Removed synthetic `"PROPOSED"` fallback in `check_action_eligibility`; missing workflow state fails closed with `"Missing workflow status"`.

4. **FR-QA-011 (Strict Segregation of Duties for Outward Allocations)**:
   - In `check_action_eligibility("approve_sale_outward_allocation")`: enforced `state == "PROPOSED"`, prior recorded Accounts verification (`verified_by` nonempty), distinct maker/verifier (`maker != verifier`), and distinct approver (`actor not in (maker, verifier)`).

5. **FR-QA-012 (Accurate Outward Capacity Computation)**:
   - Implemented `compute_outward_capacity(outward_name, active_company)`: reads physical lines, verifies reversals, sums active approved allocations (`state == "APPROVED"` and not reversed).
   - Handles restricted linked sales without exposing identity or inflating free capacity.
   - Fully allocated outwards (`remaining <= 0`) are excluded from `unassigned_outwards`.

6. **FR-QA-013 (Mobile Money Navigation Scope)**:
   - Added `allowed_routes` (`fresko-workspace`, `fresko-money`) to `bootinfo["fresko"]` based on command capabilities (`view_operations`, `view_money`).
   - Shell mobile navigation bar checks both `capabilities.includes('view_money')` and `allowed_routes.includes('fresko-money')`.

7. **FR-QA-014 (Feed Live-Only State & Return to Live)**:
   - In `fresko_workspace.js`: when `as_of_value` is active, `get_operator_action_feed` is suppressed. Displays read-only notice "Needs My Action is Live-Only" with a functional "Return to Live" button that clears the cutoff filter.

8. **FR-QA-015 (Count and Completeness Contract)**:
   - Feed metadata exposes `records_loaded`, `actionable_records`, `blocked_records`, `informational_records`, `truncated`, `completeness_state`, and `all_clear`.
   - `all_clear` is strictly `True` only when `actionable_records == 0` and `truncated` is `False`. Counts deduplicate distinct records by `doc_ref`.

9. **FR-QA-016 (Target Dispatch & State Re-Verification)**:
   - For Outward allocation proposals (`propose_commercial_allocation`): switches directly to the `outwards` tab and inspects the specific outward.
   - For allocation reviews (`verify_sale_outward_allocation`, `approve_sale_outward_allocation`): fetches fresh state via `frappe.client.get` before action execution, failing closed if status has transitioned.
   - For money actions: writes target record to `sessionStorage` and routes to `fresko-money`.

10. **FR-QA-019 (Confidential Sale Title Redaction)**:
    - In `operator_service.py`: checks `frappe.has_permission("Fresko Commercial Sale", doc=al.sale, ptype="read")`. If unauthorized, redacts title to `[Restricted Sale]`.

11. **FR-QA-020 (Action Card Keyboard Accessibility)**:
    - In `fresko_workspace.js`: `.fresko-action-card` elements have `role="button"`, `tabindex="0"`, and Enter/Space `keydown` listeners.

12. **UI Polish & Resilience (FR-QA-002, 003, 004, 005)**:
    - Idempotent panel rendering across all tabs (`content_panel.innerHTML = ''`).
    - Workflow actions strictly role-scoped (Salesperson for Prepare/Submit, Accounts for Verify, Approver for Approve).
    - `+ Prepare Sale` disabled in historical cutoff mode.
    - Alias queue network failures display error alert with a functional "Retry" button.

Verification Evidence:
- 275/275 offline Python unit tests pass (100% green, `test_operator_contract.py` extended with 47 tests).
- 49/49 script tests pass under WSL Linux.
- Node VM UI tests pass: `test_workspace_ui.cjs` (14 assertions) and `test_money_ui.cjs`.
- Schema checks pass: `check_protected_doctype_writes.py`, `validate_real_data_shadow_fixture.py`, `check_schema_snapshot.py` (24 DocTypes, 6 proofs).
- Exact-Head CI Run 37794614508 (commit 2325f1f):
  - Smoke unit (Gate 1 / D4 / constants): PASS in 12s
  - Bench install + migrate + run-tests (pinned v15): PASS in 25m23s (275/275 pinned bench tests, migrations, desktop/mobile 390px/360px browser acceptance, Supplier/Mixed denial tests, and synthetic recovery proofs 100% green).