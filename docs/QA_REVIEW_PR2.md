# QA Review — PR #2 Re-attack 9ffab5f (canonical tip)

**Date:** 15 Sep 2026  
**SHA verified:** `9ffab5f58a3951af08e178761c713fe5c5c3e845`  
(`git checkout 9ffab5f…`; `git log -1` → `9ffab5f fix(controls): D4 accept_counter ACL + Approver oversell runtime smoke`)  
**Ancestry:** `3abc861` → `568b22f` (F-H5/H6 flag align) → `9ffab5f` (F-M6 ACL tighten + runtime smoke).  
**Verdict:** **PASS**

Adversarial re-attack of F-H5/F-H6 closure on current PR #2 tip. Prior CRITICAL/HIGH (F-C1/C2, F-H1–H6) are **FIXED** in code. No new CRITICAL/HIGH found. Residual MEDIUM/LOW from Phase 1 remain non-blocking for scaffold merge. Unit smoke + fingerprint suites pass without bench; acceptance/doctype suites not executed (require Frappe site).

---

## Fix verification table

| ID | Prior finding | Status @ 9ffab5f | Evidence |
|---|---|---|---|
| **F-C1** | `decide(APPROVE)` from Countered bypasses `accept_counter` | **FIXED** | `approvals.decide`: guard `deal.status != "Approval Required"`; Countered → throw to `accept_counter`. |
| **F-C2** | `OVERSELL_OVERRIDE_ROLES` includes Approver | **FIXED** | `constants.OVERSELL_OVERRIDE_ROLES = frozenset({"System Manager"})`. Runtime smoke `TestD10Runtime` asserts Approver cannot OVERSELL_OVERRIDE / oversell flag. |
| **F-H1** | Lot/container inward can drop below `approved_sold` | **FIXED** | `_validate_inward_vs_approved_sold` + lot-delete guard (`Cannot remove lot … approved_sold > 0`). |
| **F-H2** | `decide` from Proposed skips `apply_rate_rules` | **FIXED** | `approvals.decide` rejects Proposed with apply_rate_rules message. |
| **F-H3** | `test_fresko_deal.py` bad imports / concurrent semantics | **FIXED** | Imports `fresko_universe.deals` / `approvals`; soft-ATS concurrent path unchanged. |
| **F-H4** | qty/lot/container editable in Approval Required | **FIXED** | `COMMERCIAL_LOCK_STATUSES` includes `"Approval Required"`. |
| **F-H5** | `allow_applied_write` ≠ `allow_revision_apply`; return omits `supporting_evidence` | **FIXED** | See below. |
| **F-H6** | `allow_dispatched_qty_write` ≠ `allow_dispatch_write` | **FIXED** | See below. |

---

## F-H5 — FIXED

- **Prior break:** `deals.apply_revision` set `rev.flags.allow_applied_write`; `FreskoRevision.validate` required `allow_revision_apply` → Pending→Applied always threw. Return dict lacked `supporting_evidence` → acceptance KeyError.
- **Closure @ 568b22f (held on tip):**
  - `deals.apply_revision` L306: `rev.flags.allow_revision_apply = True`
  - `fresko_revision.py` validate L45/L50: `self.flags.get("allow_revision_apply")`
  - Return L313–320 includes `"supporting_evidence": rev.supporting_evidence`
  - No remaining `allow_applied_write` in deals/revision sources
- **Smoke:** `TestFlagContracts.test_apply_revision_uses_allow_revision_apply`
- **Residual (not HIGH):** deal is saved before revision marked Applied (ordering); fail-closed for trail if rev.save fails mid-request. Prefer single transaction / reverse order in follow-up — not a flag mismatch.

## F-H6 — FIXED

- **Prior break:** `set_dispatched_qty` set `allow_dispatched_qty_write`; live `_enforce_dispatched_qty_lock` only honored `allow_dispatch_write`. Dead `_validate_dispatched_qty` never called from validate.
- **Closure @ 568b22f (held on tip):**
  - `set_dispatched_qty` L324–326: compat shim → `return record_dispatch(...)`
  - `record_dispatch` L166: `deal.flags.allow_dispatch_write = True`
  - `FreskoDeal._enforce_dispatched_qty_lock` L232/L235: checks `allow_dispatch_write` only
  - Dead `_validate_dispatched_qty` / `allow_dispatched_qty_write` removed from deal + deals
- **Smoke:** `TestFlagContracts.test_dispatch_flag_unified_to_allow_dispatch_write`
- **Residual (LOW):** shim return shape now matches `record_dispatch` (`name`, `dispatched_qty`, `status`) — no longer returns `qty`. No callers in-repo assert old keys.

---

## Follow-ups closed on this tip (not new HIGH)

| Item | Status | Notes |
|---|---|---|
| F-M1 `cancel_deal` duplicate | **FIXED** | Single `def cancel_deal` @ deals.py L102; idempotent already-Cancelled return kept. Outward/payment stubs still open (Phase later). |
| F-M6 `accept_counter` empty salesperson_user | **FIXED** @ 9ffab5f | Owner / assigned `salesperson_user` / **System Manager only** — Approver no longer privileged on accept path (`deals.py` L77–85). |
| F-H1 lot-delete bypass | **FIXED** @ 568b22f | Container validate blocks removing lots with `approved_sold > 0`. |

---

## New CRITICAL / HIGH

**None.**

No regressions introduced by flag-align or ACL tighten that elevate to HIGH/CRITICAL under adversarial review.

---

## Severity-ranked residuals (still open, non-blocking)

### MEDIUM

| ID | Summary | Notes @ 9ffab5f |
|---|---|---|
| F-M3 | Cross-day fingerprint | Unchanged; Phase 2. |
| F-M4 | Fully Reconciled ignores ATS residual / non-terminal deals | Close gate still exception-list only. |
| F-M7 | Empty rate band auto-approves | **CLOSED Gate 1:** `policy_resolved` + `RATE_POLICY_MISSING` → Approval Required. |
| F-M8 | Duplicate fingerprint side-effects swallowed | Bare `except` in `_raise_duplicate_fingerprint`. |

### LOW / INFO

- **F-L1** `container_lot` revision still noop (rewritten from `lot_no`).
- **F-L4** Lot override early-return can drop container ceiling (`resolve_rate_band`).
- **F-L-dispatch-return** `set_dispatched_qty` shim return no longer includes `qty`.
- **F-I1** Physical oversell / DN deferred Phase 3; `record_dispatch` lot inward ceiling interim.
- **F-I2** `frappe.db.set_value` bypass remains platform residual.
- **F-I-rev-order** `apply_revision` mutates deal before marking revision Applied.

---

## Six-scenario matrix status

| # | Scenario | Status @ 9ffab5f | Notes |
|---|---|---|---|
| 1 | Duplicate fingerprint | **HOLD** | Cross-day F-M3; side-effect F-M8 |
| 2 | Concurrent oversell | **HOLD** | Soft ATS + FOR UPDATE; decide throw without override |
| 3 | Wrong lot/container | **HOLD** | Lot∉container throws; AR freezes (F-H4) |
| 4 | Post-approval rate/qty edit | **HOLD** | Desk lock + **apply_revision path live** (F-H5 fixed) |
| 5 | Unresolved buyer | **HOLD** | Reconciled gate + BUYER_UNRESOLVED |
| 6 | Counter without accept | **HOLD** | F-C1 fixed; F-M6 ACL tightened (SM-only privileged) |
| + | D10 oversell | **HOLD** commercial | SM-only + runtime Approver smoke; physical Phase 3 |
| + | Illegal status jumps | **HOLD** | `allow_status_transition` + matrix; single `cancel_deal` |

---

## Tests run

| Suite | Command | Result |
|---|---|---|
| Smoke (no bench) | `cd fresko_universe && python3 -m unittest tests.test_smoke_unit -v` | **23 OK** (D10 runtime, F-H5/H6 flag contracts, F-M6 ACL, lot-delete, trail freeze) |
| Fingerprint / constants | `PYTHONPATH=fresko_universe python3 -m unittest fresko_universe.tests.test_constants_and_fingerprint -v` | **12 OK** (F-H4 + D10 asserts) |
| `test_phase1_acceptance.py` | bench required | **Not run** |
| `test_fresko_deal.py` / container | bench required | **Not run** |

---

## Merge recommendation

**PASS — recommend merge** of PR #2 tip `9ffab5f` for Phase 0/1 doctype scaffold.

- F-C1/C2 and F-H1–H6 closures verified in source; Controls B2 revision+approval path no longer dead.
- F-M6 accept_counter ACL and F-M1 cancel_deal dedupe closed as follow-ups.
- Remaining MEDIUM (M3/M4/M7/M8) and LOW/INFO are Phase 2/3 or polish — not PR2 merge blockers.
- Still run `bench run-tests --app fresko_universe` before calling production-green.

**Ordered follow-ups (non-blocking):** (1) bench revision/dispatch acceptance; (2) F-M7 empty band; (3) F-M4 reconcile gate; (4) F-M8 fingerprint side-effects; (5) Phase 2 ingest fingerprint; (6) Phase 3 physical D10.

---

## Prior tip notes (historical)

- **3abc861:** PASS WITH GAPS — F-C1/C2 + F-H1–H4 FIXED; F-H5/H6 OPEN (flag mismatches).
- **568b22f:** F-H5/H6 flag align + supporting_evidence return + dispatch unify + cancel dedupe + lot-delete F-H1.
- **9ffab5f (this tip):** F-M6 Approver removed from `accept_counter`; D10 Approver runtime smoke + contract tests.

*Fresko adversarial QA — PR #2 re-attack on `9ffab5f`. Canonical verdict for current tip.*
