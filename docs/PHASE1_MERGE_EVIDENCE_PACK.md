# Phase 1 Merge Evidence Pack — PR #2 RC Review (adversarial, read-only)

**Repo:** `AnubhavDubey02/fresko-universe`  
**Branch:** `phase1-doctype-scaffold`  
**Reviewer role:** Adversarial release-candidate (no merge; no product fixes in this pack)  
**Docs tip (this commit's parent tip before pack):** see §10  
**App-verified Gate 2 green SHA (immutable):** `d785b632803948d9b1b6c6a54423db143f50c0ca`  
**Later commits after app-verified SHA:** docs-only (`4fa84e3`, `73273cd`) — **do not treat docs tip as app-verified**.

This pack maps locked decisions and FSEC controls to **observed code + tests**. Items not found in implementation are marked **UNKNOWN / NOT IMPLEMENTED / NOT COVERED** — no inference of intent.

---

## 1. Locked decisions D1–D10 → implementation + tests

Canonical sources: `docs/DECISIONS.md`, `docs/OPEN_QUESTIONS.md`, `docs/PHASE1_BLUEPRINT_FINAL.md`.

| ID | Locked intent (summary) | Implementation (file:function) | Test(s) | Verdict |
|---|---|---|---|---|
| **D1** | No ERPNext Sales Order / DN / SLE on Deal approval in Phase 1; soft commercial reservation only | No SO/DN/SLE create paths under `fresko_universe/` (rg: no Sales Order / Delivery Note / Stock Entry / SLE writers). Approve paths: `approvals.decide`, `deals.apply_rate_rules`, `deals.accept_counter` mutate Fresko Deal / Approval / Exception only | Implicit via approve/auto-approve bench paths (`test_fresko_deal.test_in_band_auto_approves`, `test_approval_sets_approved_rate_keeps_proposed_rate`); **no positive “assert no SO created” test** | **IMPLEMENTED** (absence of writers). Positive “no SO row” assertion: **NOT COVERED** |
| **D2** | Exact ATS remaining-qty math for `Partially Dispatched` | Partial: `fresko_core.ats.commercial_qty_for_ats` returns `max(qty - dispatched, 0)` for Partially Dispatched | Smoke `TestATSMath.test_partial`; **OPEN** in `docs/OPEN_QUESTIONS.md` (“confirm at Phase 3”) | **PARTIAL / OPEN** — math coded; Phase 3 confirmation deferred |
| **D3** | PROPOSED does not reduce ATS; APPROVED / AUTO_APPROVED do; re-read ATS under lock before approval | `constants.ATS_REDUCING_STATUSES` excludes Proposed / Approval Required / Countered; includes Auto Approved / Approved (+ successors). Lock: `ats.available_to_sell(..., for_update=True)` → `SELECT … FOR UPDATE` on Container. Call sites: `deals.apply_rate_rules` (auto), `approvals.decide` (APPROVE), `deals.accept_counter`, material `apply_revision` qty/lot | `TestStateMachine.test_proposed_does_not_reduce_ats` / `test_approved_reduces_ats`; bench `test_available_to_sell_excludes_cancelled_includes_approved`; `test_concurrent_deals_*` | **IMPLEMENTED** (status sets + FOR UPDATE + sequential soft-route). True parallel race: see §3 |
| **D4** | COUNTERED requires originator/`salesperson_user` accept; Approver immediate different rate = APPROVE+decision_rate; SM must not accept on behalf | `approvals.decide`: COUNTER → Countered; decide blocked from Countered. `deals.accept_counter`: ACL `{owner} ∪ {salesperson_user}` only. G-M1: `salesperson_user` in `LOCKED_COMMERCIAL_FIELDS` | Smoke `TestD4AcceptCounterACL` (5), `TestD4SalespersonFieldLock`; bench `test_counter_requires_accept`, `test_decide_cannot_approve_from_countered_*`, `test_system_manager_cannot_accept_counter_unless_owner`; acceptance `test_d4_counter_requires_accept_before_approved` | **IMPLEMENTED** |
| **D5** | Rate-floor hierarchy: Lot override → Container+Count/Size → Container default; no buyer floor V1 | `rate_rules.resolve_rate_band` | Smoke `TestRateFloorD5` (incl. currency-0 fallthrough); `TestRateBandHierarchy`; Gate1 suite | **IMPLEMENTED** |
| **D6** | May approve with unresolved buyer; preserve `buyer_alias`; **open BUYER_UNRESOLVED**; block RECONCILED until Customer | Alias immutable: `FreskoDeal._validate_buyer_alias_immutable`. Open exception: `_maybe_open_buyer_unresolved` from **auto-approve** (`deals.apply_rate_rules`), **`approvals.decide` APPROVE**, and **`deals.accept_counter`** (after ATS + `set_status("Approved")`, before save/commit). Reconcile gate: `FreskoDeal._validate_reconciled_gate` (customer + open BUYER_UNRESOLVED) | Bench/acceptance `test_unresolved_buyer_blocks_reconciled` (auto/approve); bench `test_accept_counter_empty_customer_opens_buyer_unresolved` / `test_accept_counter_with_customer_no_buyer_unresolved`; smoke `TestD6AcceptCounterBuyerUnresolved` | **IMPLEMENTED** |
| **D7** | Physical inward: PR vs Stock Entry | — | — | **NOT IMPLEMENTED** (Phase 3 / OPEN_QUESTIONS) |
| **D8** | Project vs Accounting Dimension for container P&L | — | — | **NOT IMPLEMENTED** (Later / OPEN_QUESTIONS) |
| **D9** | GST / invoice timing | — | — | **NOT IMPLEMENTED** (CA / OPEN_QUESTIONS) |
| **D10** | Oversell override Owner/Admin only; reason + Approval + Exception; commercial OK; never physical dispatch beyond stock / silent negative stock | Role gate: `constants.OVERSELL_OVERRIDE_ROLES = {System Manager}` (no separate “Fresko Owner” role — Owner ≈ SM). `approvals.decide` OVERSELL_OVERRIDE / `oversell_override=1`. Exception `OVERSELL_OVERRIDE`. Physical: `deals.record_dispatch` + `FreskoDeal._enforce_dispatched_qty_lock` | Smoke `TestD10` / `TestD10Runtime`; constants `test_d10_oversell_system_manager_only`; bench `test_oversell_override_creates_exception` | **IMPLEMENTED** (commercial). Physical DN/SLE Phase 3 still N/A |

**Related merge gates (not numbered D\* but locked):**

| Gate | Implementation | Tests |
|---|---|---|
| **Gate 1** fail-closed empty rate policy | `rate_rules.policy_resolved` + `deals.apply_rate_rules` → Approval Required + `RATE_POLICY_MISSING` Exception; nullable rate cols via `install._ensure_gate1_nullable_rate_snapshots` | Smoke `TestGate1RatePolicyMissing` (5); bench `test_gate1_*` |
| **Gate 2** pinned bench CI | `.github/frappe-versions.json` + `scripts/ci_bench.sh` + `.github/workflows/ci.yml` | Run `34954607466` on `d785b63` — see §10 |

---

## 2. FSEC controls → actual enforcement points

Source ledger: `docs/security/SECURITY_FINDINGS.md`. Enforcement = runtime gate, not merely a test.

| ID | Status | Enforcement point (file:function) | Notes |
|---|---|---|---|
| **FSEC-001** | MITIGATED | `permissions.assert_can_apply_rate_rules` / `assert_can_cancel_deal` / `assert_can_record_dispatch` / `assert_can_request_revision` / `assert_can_read_ats_snapshot`; called from `deals.apply_rate_rules`, `cancel_deal`, `record_dispatch`, `request_revision`, `container.container_snapshot` **before** `ignore_permissions`. `accept_counter` ownership ACL inline; `approvals.decide` role gate | Residual: `ignore_permissions` after ACL by design; Approver cancel/dispatch any Deal |
| **FSEC-002** | MITIGATED | `permissions.assert_can_apply_revision`; `assert_approval_bound_for_revision`; `assert_approval_not_stale`; wired in `deals.apply_revision` | Residual: any Approver may apply bound APPROVE; Approval.approver identity not required to match session |
| **FSEC-003** | MITIGATED | `hooks.permission_query_conditions` / `has_permission` → `deal_permission_query`, `deal_has_permission`, `evidence_*` | Residual: DocType JSON still coarse write=1 for Salesperson; Container/Revision/Approval/Exception **lack** query/has_permission hooks; Evidence without `deal` allows Salesperson create/read/write |
| **FSEC-004** | OPEN | `fresko_evidence.FreskoEvidence.before_insert` hashes **path string**, not file bytes | No byte-hash enforcement |
| **FSEC-005** | OPEN | Deal `source_message_id` unique in JSON/validate; Evidence `message_id` **not** unique | No Evidence uniqueness enforcement |
| **FSEC-006** | OPEN | CI = smoke + bench only (`.github/workflows/ci.yml`) | No SAST/secret/dep advisory job |
| **FSEC-007** | OPEN | `docker-compose*.yml` / `scripts/ci_bench.sh` publish DB/Redis + default root/admin | Lab/CI only; not app runtime ACL |
| **FSEC-008** | OPEN | `deals.apply_rate_rules` out-of-band branch sets Approval Required **without** opening `RATE_FLOOR_BREACH` Exception (comment claims path) | Type exists in `EXCEPTION_TYPES` only |
| **FSEC-009** | OPEN | Root `.gitignore` gaps | Repo hygiene |
| **FSEC-010** | OPEN | No throttle on whitelist mutators | Relies on upstream UNKNOWN |
| **FSEC-011** | OPEN (tracking) | WhatsApp/OCR/LLM not in app code | Future |
| **FSEC-012** | OPEN | Approval/Revision/Evidence `track_changes=0` in DocType JSON | Append-only validators partially compensate |

---

## 3. Adversarial cases

| Case | Coverage | Evidence / risk if NOT COVERED |
|---|---|---|
| **Unauthorized role** (Accounts cancel / apply_rate / dispatch; stranger Salesperson cancel; non-Approver apply_revision) | **COVERED** | Smoke `TestFSEC001*`, `TestFSEC002*`; bench `test_fsec_permissions.*` |
| **Direct document/API bypass** (Desk `approved_rate`, `dispatched_qty`, illegal status, qty freeze in AR) | **COVERED** (Document.validate) | `test_desk_edit_approved_rate_rejected`, `test_dispatched_qty_desk_edit_rejected`, `test_illegal_status_transition_rejected`, `test_qty_frozen_in_approval_required`. **Residual risk:** `frappe.db.set_value` bypass of Document.validate acknowledged in `_enforce_dispatched_qty_lock` docstring — **NOT COVERED** as prevented |
| **Duplicate / replay** | **COVERED** (Deal-level) | Unique `source_message_id` + `duplicate_fingerprint`; `test_duplicate_*`. Fingerprint side-effects Evidence+Exception wrapped in bare `except` (`_raise_duplicate_fingerprint`) — side-effect failure can be swallowed (**NOT COVERED** that Exception always lands). Evidence.message_id uniqueness **NOT COVERED** (FSEC-005) |
| **Concurrent approval** | **PARTIAL** | Sequential soft-route: first auto-approves, second → AR then `decide(APPROVE)` throws (`test_concurrent_deals_*`). Uses `FOR UPDATE` on Container. **True multi-worker simultaneous decide:** **NOT COVERED** |
| **Stale state** | **PARTIAL** | `assert_approval_not_stale` blocks Approval reused on another Applied revision. Stale Deal status on long-lived Approval (deal cancelled then apply): **NOT COVERED** explicitly |
| **Partial failure** (Exception/Approval inserted, Deal not) | **NOT COVERED** | Multi-doc writes then `frappe.db.commit()`; no savepoint / rollback unit tests — see §4 |
| **Unresolved buyer** | **COVERED** | Auto/decide/`accept_counter` open BUYER_UNRESOLVED when customer empty; with customer set no exception; Reconciled blocked while open. Bench D6 accept_counter tests + smoke `TestD6AcceptCounterBuyerUnresolved` |
| **Oversell** | **COVERED** (commercial) | Approver denied; SM OVERSELL_OVERRIDE + Exception. Physical dispatch ceiling covered in `record_dispatch` / validate. Phase 3 DN/SLE: N/A |
| **Owner/Admin override** | **COVERED** as System Manager only | No dual-control; SM may delete Approvals (`FreskoApproval.on_trash`). D10 “Owner” ≠ separate role |

---

## 4. Failure cannot leave partially committed Deal / reservation / inventory

| Pattern | Observation |
|---|---|
| Soft reservation only | Phase 1 never posts SLE / Batch Bundle stock — inventory ledger partial commit **N/A** |
| ATS lock | `FOR UPDATE` on Container before ATS-sensitive approve/accept/revision qty |
| Explicit commits | `frappe.db.commit()` at end of `apply_rate_rules`, `accept_counter`, `cancel_deal`, `record_dispatch`, `apply_revision`, `decide` |
| Multi-doc sequences | e.g. `decide` OVERSELL: `_open_exception` → `_insert_approval` → Deal.save → commit; `apply_rate_rules`: Exception insert → Deal.save → `db.set_value` null fields → commit; `apply_revision`: Deal.save → Revision.save → optional Exception resolve → commit |
| Atomicity proof | **ASSUMPTION** — Frappe single transaction until explicit `frappe.db.commit()`; **NOT COVERED** mid-crash / forced-rollback test that Exception/Approval roll back with Deal |
| Fingerprint duplicate path | Throw after best-effort Evidence/Exception; bare except may leave **neither** side-effect nor second Deal — Deal blocked, audit trail **may be incomplete** |

---

## 5. State / certainty vocabulary (silent conversion flags)

| Token | Meaning in code | Silent certainty risk |
|---|---|---|
| **PROPOSED** | Initial Deal.status; does **not** reduce ATS | Low |
| **COUNTERED** | After `decide(COUNTER)`; counter lives on Approval.`decision_rate`; Deal.`approved_rate` stays **NULL** until `accept_counter`; **does not** reduce ATS | **FIXED (RC):** amount uses `proposed_rate` while Countered / approved_rate unset; accept copies decision_rate → approved_rate |
| **ACCEPTED / APPROVED** | Status string is **`Approved`** (and **`Auto Approved`**). No status named ACCEPTED; accept = `accept_counter` → Approved | Do not invent ACCEPTED status |
| **BUYER_UNRESOLVED** | Exception type (not a Deal.status). Opened on auto-approve / decide APPROVE / `accept_counter` when `customer` empty | Low — all commercial approve paths covered |
| **PENDING** | `Fresko Revision.status = Pending` (and payment statuses Payment Pending — different domain) | Avoid conflating Revision Pending with Deal Payment Pending |
| **UNKNOWN** | Not a Deal.status. Gate 1 uses SQL **NULL** for unresolved floor/ceiling/approved_rate (post-save `set_value`) | Currency 0 coerced to “unset” via `_optional_rate` — intentional Gate 1, but **0 is never a valid floor** by policy |
| Approval Required | Soft fail-closed / out-of-band / stock shortfall on auto path | Out-of-band does **not** open RATE_FLOOR_BREACH Exception (FSEC-008) — status certainty without matching exception signal |

---

## 6. Fields with multiple meanings / derived double-counts

| Field / signal | Multiple meanings / double-count risk |
|---|---|
| **`approved_rate`** | (a) Final commercial rate on Approved/Auto Approved; (b) **NULL while Countered** (counter on Approval.decision_rate); (c) forced NULL on Approval Required | RC corrected — see §5 |
| **`amount`** | `qty × proposed_rate` while Countered / approved_rate unset; else `qty × approved_rate` | RC corrected |
| **ATS `commercial_qty_for_ats`** | Partially Dispatched reserves `qty - dispatched` only (dispatched “freed” commercially while Phase 1 has no SLE) | Soft ATS vs physical stock can diverge — D2 OPEN |
| **Cancelled + dispatched** | Cancelled still reserves `dispatched_qty` in ATS | Intentional (QA cancel-after-partial); easy to double-count if dashboards also sum dispatched separately |
| **Container snapshot `approved_sold`** | Computed as `inward - ats` per lot | Must not be summed with Deal.qty from another query without status filters |
| **`rate_floor` / `rate_ceiling` on Deal** | Snapshots at `apply_rate_rules`; may be NULL (unset) vs 0 | Gate 1 nullable ALTER distinguishes unset |
| **`duplicate_fingerprint` vs `source_message_id`** | Two idempotency axes; fingerprint optional until auto-set on insert | Duplicate ingest may still create Deal if fingerprint inputs differ (alias/day) |
| **Exception type vs Deal status** | RATE_FLOOR_BREACH type unused on out-of-band path | Ops dashboards counting Exceptions under-count rate breaches |

---

## 7. Pre-existing data + migrations / backfills

| Item | Required? |
|---|---|
| Greenfield DocTypes | Fresh install via bench `install-app` + migrate |
| `patches/v1_0/` | **Empty** (only `__init__.py`) — **no numbered patches** |
| `after_install` / `after_migrate` | Ensures Fresko roles; **ALTER** Deal `approved_rate` / `rate_floor` / `rate_ceiling` to **NULL-able** (`install._ensure_gate1_nullable_rate_snapshots`) |
| Data backfill | **None coded** for pre-existing Deals/Containers (greenfield assumption) |
| If replaying Gate 1 on older site DBs | Must run migrate so nullable ALTER applies; otherwise NULL snapshots may fail / coerce to 0 — **UNKNOWN** without legacy-site fixture |

---

## 8. Concrete E2E examples (≥3) — from tests/code paths

### E2E-A — In-band auto-approve (ATS reduces; unresolved buyer)

1. **Input:** Container lot inward 100, defaults floor/ceiling set; Deal Proposed `qty=30`, `proposed_rate` in band, `customer` empty, `buyer_alias` set.  
2. **Call:** `deals.apply_rate_rules(deal)`.  
3. **Stored:** Deal.status=`Auto Approved`; `approved_rate`=`proposed_rate`; Fresko Exception `BUYER_UNRESOLVED` Open (via `_maybe_open_buyer_unresolved`).  
4. **Permissions:** Caller must pass `assert_can_apply_rate_rules` (owner Salesperson / Approver / SM).  
5. **ATS:** Lot ATS 100→70 (`test_available_to_sell_excludes_cancelled_includes_approved` / `test_in_band_auto_approves`).  
6. **Business:** Soft reservation only; no SO.

### E2E-B — Below floor → COUNTER → accept_counter (D4)

1. **Input:** Deal Proposed below floor → `apply_rate_rules` → `Approval Required` (no approved_rate).  
2. **Call:** `approvals.decide(..., COUNTER, decision_rate=11, reason=…)`.  
3. **Stored (corrected 2026-09-18):** Approval row decision=COUNTER with `decision_rate=11`; Deal.status=`Countered`; Deal.`approved_rate` remains **NULL**; ATS **unchanged** (Countered not reducing).
4. **Bypass attempt:** `decide(APPROVE)` from Countered → throw (must `accept_counter`).  
5. **Accept:** Owner/`salesperson_user` `accept_counter` → `Approved`; ATS reduces; `_maybe_open_buyer_unresolved` if `customer` empty. SM non-owner denied.  
6. **D6:** empty customer → open BUYER_UNRESOLVED; customer set → no new exception.

### E2E-C — Concurrent soft oversell then D10 override

1. **Input:** Two Proposed deals qty=80 on lot inward 100, in-band rates.  
2. **Call:** `apply_rate_rules(d1)` → Auto Approved; `apply_rate_rules(d2)` → Approval Required + STOCK_SHORTFALL Exception.  
3. **Call:** `decide(d2, APPROVE)` → throw ATS.  
4. **Override:** SM `decide(d2, OVERSELL_OVERRIDE, reason=…)` → Approved + Exception OVERSELL_OVERRIDE + Approval with oversell flag.  
5. **Approver-only oversell:** denied (`TestD10Runtime` / bench).  
6. **Physical:** `record_dispatch` still cannot exceed deal qty or lot inward sum of dispatched.

### E2E-D — Gate 1 empty policy (bonus)

Empty defaults/rules → Approval Required + RATE_POLICY_MISSING; floor/ceiling/approved_rate SQL NULL; proposed_rate preserved (`test_gate1_no_rate_rule_rate_policy_missing`).

---

## 9. Human overrides

| Override | Who | Audit trail | Reason required? | Can bypass invariants? |
|---|---|---|---|---|
| **D10 OVERSELL_OVERRIDE** | **System Manager** only (`OVERSELL_OVERRIDE_ROLES`) | Fresko Approval (decision OVERSELL_OVERRIDE, approver, decided_at) + Fresko Exception OVERSELL_OVERRIDE linked | **Yes** (`decide` requires reason) | **Yes** commercial ATS shortfall. **No** physical: dispatched_qty ≤ deal qty and ≤ lot inward residual |
| **Approval APPROVE with decision_rate** | Fresko Approver / SM | Approval row snapshots proposed/floor/ceiling/decision_rate | **Yes** | Sets commercial rate without COUNTER; still ATS-checked unless oversell |
| **accept_counter** | Deal **owner** or **salesperson_user** only (not SM/Approver on behalf) | Status transition + prior COUNTER Approval | No extra reason on accept (reason was on COUNTER) | Cannot skip ATS re-check; cannot steal via Desk `salesperson_user` change (commercial lock) |
| **apply_revision (material)** | Approver / SM + bound APPROVE/OVERSELL Approval + evidence when locked | Fresko Revision trail (old/new/reason/evidence/approval_reference); Applied freezes historical fields | **Yes** on request_revision | Changes approved_rate/qty/lot/customer under flags; qty/lot re-check ATS |
| **Approval delete** | System Manager (`on_trash`) | Frappe delete (track_changes=0 on Approval — weak Version trail, FSEC-012) | N/A | **Yes** can destroy append-only history if SM deletes |
| **Administrator / SM Desk** | SM passes `deal_has_permission` True | Document flags still enforce commercial locks / status machine unless whitelist flags set | — | SM still subject to server locks on commercial fields; **not** a free Desk bypass of `approved_rate` without flags |
| **db.set_value** | Any code path with DB access | None at Document layer | — | **Can** bypass Document.validate (documented residual) |

---

## 10. Exact commands, counts, CI pins

### Distinguish SHAs

| Label | SHA | Notes |
|---|---|---|
| **App-verified Gate 2 green** | `d785b632803948d9b1b6c6a54423db143f50c0ca` | Last commit that changed app/test code for Gate 2 green |
| **Docs tip before this evidence pack** | `73273cd66c4867326f7524629a5b110d22e5c1d9` | docs(security) only after `d785b63` |
| **This evidence pack commit** | *(filled at push)* | `docs: Phase 1 Merge Evidence Pack (RC review, no merge)` |
| **D6 fix tip (CI green)** | `3d9ac65a3aed0b64b9d02608b2fec392b40b8273` | `fix(D6): accept_counter opens BUYER_UNRESOLVED…`; smoke 58 + bench 61 |

### Immutable Gate 2 evidence (do not invent)

| Field | Value |
|---|---|
| Commit SHA | `d785b632803948d9b1b6c6a54423db143f50c0ca` |
| Run ID | `34954607466` |
| Workflow URL | https://github.com/AnubhavDubey02/fresko-universe/actions/runs/34954607466 |
| PR twin run | `34954609241` (same conclusion per `docs/GATE2_CI_RESULT.md`) |
| Smoke | **56 OK**, 0 fail, 0 error |
| Bench | **59 OK**, 0 fail, 0 error |
| Frappe pin | **v15.120.1** @ `9f8ae9cd25b6735be345da6cc12e9f5a96050c68` |
| ERPNext pin | **v15.121.2** @ `df8b7f9648c2ec4da12db8c4022edc8dd1018c6b` |

### Tip `3d9ac65` Phase1 CI (D6 fix) — watched 2026-09-15

| Field | Value |
|---|---|
| Commit SHA | `3d9ac65a3aed0b64b9d02608b2fec392b40b8273` |
| Run ID (push) | `34957061073` |
| Workflow URL | https://github.com/AnubhavDubey02/fresko-universe/actions/runs/34957061073 |
| PR twin run | `34957065131` (success; same tip) |
| Smoke | **58 OK**, 0 fail, 0 error (`Ran 58 tests in 0.037s`) |
| Bench | **61 OK**, 0 fail, 0 error (`Ran 61 tests in 4.122s` / `==> CI bench OK`) |
| Pins | Frappe **v15.120.1** / ERPNext **v15.121.2** (`pins OK`) |
| Notes | D6 `accept_counter` opens BUYER_UNRESOLVED before Approved save; Gate1/D4/D10 unchanged |

Prior immutable Gate 2 green on `d785b63` (smoke 56 / bench 59, run `34954607466`) remains valid for that SHA; tip evidence above supersedes counts for RC on `3d9ac65`.

### Commands (reproduce)

```bash
# Offline smoke (Gate 1 / D4 / FSEC offline / constants)
cd fresko_universe && python3 -m unittest tests.test_smoke_unit -v
# Expected: Ran 56 tests … OK

# Pin assert (as in CI)
python3 - <<'PY'
import json
from pathlib import Path
p = json.loads(Path(".github/frappe-versions.json").read_text())
assert p["frappe"]["sha"] == "9f8ae9cd25b6735be345da6cc12e9f5a96050c68"
assert p["erpnext"]["sha"] == "df8b7f9648c2ec4da12db8c4022edc8dd1018c6b"
print("pins OK", p["frappe"]["tag"], p["erpnext"]["tag"])
PY

# Full Gate 2 bench (CI / heavy local)
bash scripts/ci_bench.sh
# CI job runs: migrate + bench run-tests --app fresko_universe → 59 OK on d785b63
```

### Local re-check during this RC (smoke only; bench not re-run here)

```text
cd fresko_universe && python3 -m unittest tests.test_smoke_unit -v
→ Ran 56 tests in ~0.03s OK
PYTHONPATH=fresko_universe python3 -m unittest fresko_universe.tests.test_constants_and_fingerprint -v
→ Ran 13 tests OK (subset; not the Gate 2 bench total)
```

Bench **59** is taken from immutable CI run `34954607466` on `d785b63` — **not re-executed** in this read-only RC.

### Skips / failures

- Gate 2 tip `d785b63`: **0 failures, 0 errors, 0 skips reported** in `docs/GATE2_CI_RESULT.md`.  
- Intermediate red `f7db7c3`: FSEC fixture fingerprint collisions — fixed by test hygiene only on `d785b63` (Gate1/D4/D10 not weakened).

---

## RC conclusion (not a merge certificate)

**Do not merge.** Hold Phase 2. D6 Countered→Approved path fixed: `deals.accept_counter` calls `_maybe_open_buyer_unresolved` after ATS + `set_status("Approved")` (same as auto-approve / `decide(APPROVE)`), with bench + smoke coverage.

**ASSUMPTION (residual NOT COVERED):** multi-doc atomicity = Frappe single request transaction until explicit `frappe.db.commit()` — no mid-crash / forced-rollback test proving Exception/Approval roll back with Deal.  
**Residual (Anubhav-accepted, non-blocking):** `frappe.db.set_value` can bypass Document.validate (documented in `_enforce_dispatched_qty_lock` / Desk-bypass notes).

READY FOR INDEPENDENT REVIEW
