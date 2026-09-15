# Controls Review — PR1 Phase 0/1 Scaffold

**Reviewer:** Fresko Controls  
**Scope:** Server-side invariants for Fresko Container + Deal (+ Approval, Revision, Evidence, Exception)  
**Sources:** local `/workspace/fresko-universe-repo` (branch at review: `phase1-doctype-scaffold`; CoS brief cited `phase-0-1-scaffold` / PR #1), `docs/PHASE1_BLUEPRINT_FINAL.md`, `docs/DECISIONS.md`, `docs/DEVIATIONS.md`, `docs/CONTROLS_PHASE1_CONTAINER_DEAL.md`  
**Review time:** 15 Sep 2026  

---

## Verdict: **CONDITIONAL**

Core control shape is present and largely matches the Conditional Pass locked into the blueprint (Revision DocType, commercial lock flags, Approval append-only validate, ATS under `FOR UPDATE`, D3/D4/D5/D6 intent, no SO/DN/SLE on approve).

**Do not merge as-is.** Fix the blockers below first. Should-fix items may ship immediately after blockers if tracked.

---

## Invariant scorecard

| # | Invariant | Result | Notes |
|---|---|---|---|
| 1 | No silent Desk edits of approved commercial fields | **PASS** | `FreskoDeal._enforce_commercial_lock` + `allow_approval_write` / `allow_commercial_revision` flags |
| 2 | Status only via whitelist methods | **PASS** | `allow_status_transition` required; `DEAL_TRANSITIONS` enforced |
| 3 | Fresko Revision trail fields | **PASS (schema)** / **CONDITIONAL (path)** | Fields present; apply path too loose (see B2) |
| 4 | Approval append-only | **PASS** | `validate` blocks edits; SM delete still allowed (S1) |
| 5 | ATS (D3) — Proposed/AR/Countered do not reserve | **PASS** | `ATS_REDUCING_STATUSES` / `ATS_ACTIVE_STATUSES` exclude them; partial uses remaining qty |
| 6 | Concurrency before approve | **PASS** | `available_to_sell(..., for_update=True)` locks Container row |
| 7 | D4 counter-accept before Approved | **PASS (intent)** / **CONDITIONAL** | `accept_counter` exists; Approver/SM can accept on behalf (S2) |
| 8 | D5 rate floors | **PASS** | Lot override → count rule → container default; snapshot on `apply_rate_rules` |
| 9 | D6 BUYER_UNRESOLVED | **PASS** | Opens on approve; blocks Reconciled; `buyer_alias` immutable |
| 10 | D10 oversell override | **FAIL in working tree** | See **B1** |
| 11 | No SO / DN / SLE on approve | **PASS** | No posting hooks found |
| 12 | Idempotency keys | **PASS** | Unique checks + duplicate fingerprint side-effects |
| 13 | Evidence immutability | **PASS** | Hash/message_id/file/external_ref frozen once set |
| 14 | Automated control tests runnable | **FAIL / broken** | See **B3** |

---

## Blockers (must fix before merge)

### B1 — D10 / DV4 regression: Approver can oversell

**Locked rules**

- Anubhav **D10:** oversell override Owner/Admin only; reason + Approval + Exception.  
- **DV4:** `OVERSELL_OVERRIDE_ROLES = {System Manager}` — Fresko Approver alone cannot oversell.

**Observed (working tree `fresko_universe/constants.py`)**

```text
OVERSELL_OVERRIDE_ROLES = frozenset({"System Manager", "Fresko Approver", "Fresko Owner"})
```

`HEAD` commit still had `{"System Manager"}` only. Working/staged tree **widens** the role set. Smoke test `TestD10.test_roles` asserts Approver **is** in the set — that encodes the wrong policy.

**Also:** `Fresko Owner` is not in role fixtures (`hooks.py` fixtures only Salesperson / Approver / Accounts). Dead role name ≠ control.

**Required fix**

1. Restore `OVERSELL_OVERRIDE_ROLES = frozenset({"System Manager"})` (or Explicit Anubhav-named Owner role once it exists — **not** Fresko Approver).  
2. Assert Approver **∉** `OVERSELL_OVERRIDE_ROLES` in unit tests.  
3. Keep Exception + reason + Approval row on override (already present in `approvals.decide`).  
4. Align `DEVIATIONS.md` DV4 with code before merge.

### B2 — Commercial Revision can apply without Approval + evidence

Controls / blueprint: post-approval `qty` / `approved_rate` / lot changes require **Revision + Approval** with `supporting_evidence` when material.

**Observed (`deals.apply_revision`)**

- Approver / System Manager may apply commercial revisions **without** `approval_reference`.  
- `supporting_evidence` is optional on `request_revision` / DocType.  
- `test_phase1_acceptance.test_revision_plus_approval_changes_rate_with_trail` calls `apply_revision(rev)` with **no** Approval — so the “plus approval” test does not prove the control.

**Required fix**

1. For `approved_rate`, `qty`, `lot_no`, `container_lot`: require `approval_reference` (or create Approval in the same transaction) before `Applied`. Role alone is insufficient.  
2. Require `supporting_evidence` for those fields after commercial lock.  
3. Rewrite the acceptance test to create Approval → link → apply, and assert trail fields including `approval_reference` + evidence.  
4. After `Applied`, freeze Revision historical fields (`old_value`, `new_value`, `reason`, `fieldname`, `parent_*`) — not only `old_value`.

### B3 — Control tests / API surface inconsistency

**Observed**

- `fresko_deals/.../test_fresko_deal.py` imports `fresko_universe.api.deals` — **module does not exist**.  
- Calls `transition_deal`, `apply_revision_approval`, `allow_oversell=` which are **not** on current `deals.py` / `approvals.decide` (param is `oversell_override`).  
- `test_concurrent_deals_cannot_over_approve_lot_stock` expects `ValidationError` on second `apply_rate_rules`, but implementation soft-routes ATS shortfall to **Approval Required** + `STOCK_SHORTFALL` (no throw). Concurrent safety still exists at **approve** time; the test does not match the method.

**Required fix**

1. Single public API module (or update all tests to `fresko_universe.deals` / `fresko_universe.approvals`).  
2. Either hard-fail auto-approve when `qty > ATS`, **or** change concurrent test to: second deal → Approval Required, then `decide(APPROVE)` throws without override.  
3. Ensure §I blueprint tests actually execute under `bench run-tests`.

---

## Should-fix (non-blocking if B1–B3 land)

### S1 — Approval / Revision delete

SM may delete Approval (`on_trash` allows SM) and Revision (permission `delete: 1`). Prefer **cancel-only** in production; delete disabled except emergency with audit.

### S2 — D4 accept_counter by Approver

Anubhav D4: originator/salesperson must explicitly accept COUNTER. Code allows Fresko Approver / System Manager to accept on behalf. Tighten to originator/`salesperson_user`/`owner` only; Approver who wants immediate rate must **APPROVE** with `decision_rate` (already documented in `decide`).

### S3 — Container inward after Selling

Change of `inward_qty` after Selling requires `flags.inward_qty_change_reason` but **does not** write `Fresko Revision`. Prefer Revision row for auditability.

### S4 — Auto-approve stock shortfall UX

In-band + ATS fail → Approval Required + `STOCK_SHORTFALL`. Acceptable if Approver cannot approve without D10 override; document so ops do not confuse with rate-floor Approval Required.

### S5 — Lock granularity

`FOR UPDATE` is on Container, not Lot row. Acceptable for Phase 1 if all ATS paths share that lock (they do). Prefer Lot-level lock when reservation ledger arrives.

### S6 — Open `OVERSELL_OVERRIDE` blocks Fully Reconciled

Good fail-closed posture; ensure Exception can be **Resolved** with documented acceptance so legitimate D10 commitments can close after review (not silent delete).

---

## What is solid (do not regress)

1. **Commercial lock** on approved fields; Desk edit of `approved_rate` throws (`test_desk_edit_approved_rate_rejected` design is correct).  
2. **Status machine** refuses Desk jumps without `allow_status_transition`.  
3. **COUNTER keeps `proposed_rate`**; sets `approved_rate` only as counter offer awaiting accept (D4).  
4. **ATS formula** excludes Proposed / Approval Required / Countered / Cancelled; includes Disputed (DV5); partial remaining qty (DV6).  
5. **No ERPNext SO/DN/SLE** on approve (D1).  
6. **D5 hierarchy** implemented in `rate_rules.resolve_rate_band`.  
7. **D6** buyer unresolved exception + Reconciled gate + immutable `buyer_alias`.  
8. **Fingerprint / source_message_id** uniqueness.  
9. **Revision DocType** has `old_value`, `new_value`, `changed_by`, `changed_at`, `reason`, `supporting_evidence`, `approval_reference`.  
10. **Evidence** content immutability.

---

## CA / Anubhav items still not hard-coded (correct)

GST / invoice timing (D9), Project vs dimension (D8), physical inward posting form (D7) — still deferred. Keep it that way.

---

## Required merge gate checklist

- [ ] B1 D10 roles restored; Approver cannot oversell; tests assert that  
- [ ] B2 commercial Revision requires Approval + evidence; Applied revisions immutable  
- [ ] B3 tests import real modules; concurrent/ATS expectations match code; §I suite green  
- [ ] DV4 / DECISIONS text match shipped constants  
- [ ] Re-run Controls spot-check on final PR tip before merge  

---

## Sign-off

| Item | Decision |
|---|---|
| Overall | **CONDITIONAL** |
| Merge now? | **No** |
| After B1–B3 | Controls can re-review to PASS (scaffold) |

