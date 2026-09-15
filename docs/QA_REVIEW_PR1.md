# QA Review — PR #1 Phase 0/1 Scaffold
Date: 15 Sep 2026
Scope: controllers + smoke/acceptance tests under fresko_universe
Verdict: **PASS WITH GAPS**

Adversarial re-attack of the finished Phase 0/1 scaffold against the eight locked focus areas (prior design QA folded as C3–C4 Revision, C6 Lot child, C7 soft ATS + concurrent lock, C8 message_id/fingerprint, C9 unresolved-buyer gate on Reconciled). Code root reviewed: `fresko_universe/fresko_universe/{deals,approvals,container,ats,rate_rules,constants,hooks,install}.py`, DocType controllers, JSON uniqueness/permissions, and tests. Unit smoke + constants tests run without bench; integration/acceptance tests require Frappe/ERPNext and were **not** executed end-to-end.

---

## Severity-ranked findings

### CRITICAL

#### F-C1 — `approvals.decide(APPROVE)` from `Countered` bypasses D4 `accept_counter`
- **Break attempt:** Approver COUNTERs a deal (`status=Countered`, `approved_rate=decision_rate`). Instead of salesperson calling `deals.accept_counter`, Approver (or any caller with Approver/SM) calls `approvals.decide(deal, "APPROVE", decision_rate=…, reason=…)`. Status check explicitly allows `Countered`; `set_status("Approved")` succeeds; ATS lock runs; deal becomes commercially Approved **without** originator/salesperson accept.
- **Code path:** `approvals.decide` lines allowing `deal.status not in ("Approval Required", "Proposed", "Countered")` guard; APPROVE branch → `deal.set_status("Approved")`. `DEAL_TRANSITIONS["Countered"]` includes `"Approved"`, so transition matrix does not save D4. Contrast: blueprint D4 / `deals.accept_counter` is the only documented accept path.
- **Fails closed?** **No** for D4. Counter path itself fails closed (COUNTER → Countered, not Approved). Accept bypass is open.
- **Residual gap:** Any Approver can force Approved from Countered at an arbitrary `decision_rate`, defeating “salesperson must accept counter.” Also allows re-APPROVE with a different rate while Countered without revision.
- **Required fix:** Remove `Countered` from `decide`’s allowed statuses (REJECT/CANCEL only if needed via dedicated methods). Route Countered → Approved exclusively through `accept_counter`. Add test `test_decide_approve_from_countered_rejected`.
- **Missing test:** `test_decide_cannot_approve_from_countered_must_use_accept_counter`

#### F-C2 — D10 oversell override roles include `Fresko Approver` (violates locked D10 + DEVIATIONS DV4)
- **Break attempt:** Fill lot ATS with Auto Approved deal. Second deal goes `Approval Required` (qty > ATS). Any user with role `Fresko Approver` calls `decide(..., "OVERSELL_OVERRIDE", reason=…)` or `decide(..., "APPROVE", oversell_override=1, …)`. Role gate uses `OVERSELL_OVERRIDE_ROLES`; deal becomes Approved; `OVERSELL_OVERRIDE` Exception opened; container can later approach close with commercial oversell.
- **Code path:** `constants.OVERSELL_OVERRIDE_ROLES = frozenset({"System Manager", "Fresko Approver", "Fresko Owner"})`; `approvals.decide` OVERSELL_OVERRIDE / `oversell_override` branch. **Conflict:** `docs/DEVIATIONS.md` DV4 claims `{System Manager}` only; DECISIONS/blueprint D10: “Owner/Admin only.” Smoke test `TestD10.test_roles` **encodes the wrong policy** by asserting Approver ∈ set.
- **Fails closed?** **No** vs D10. Mechanism (Exception + reason + Approval row) exists, but authorization is too wide.
- **Residual gap:** Every Approver can commercially oversell; `Fresko Owner` is named in the set but **not** created in `install._ensure_roles` / fixtures (only Salesperson/Approver/Accounts).
- **Required fix:** Set `OVERSELL_OVERRIDE_ROLES = frozenset({"System Manager"})` (or System Manager + explicit Fresko Owner after installing that role). Reject `oversell_override=1` on plain APPROVE unless same role set. Update DV4/smoke test to match. Test `test_approver_cannot_oversell_override`.
- **Missing test:** `test_d10_oversell_restricted_to_system_manager_not_approver`

---

### HIGH

#### F-H1 — Lot / container `inward_qty` can be lowered below approved commercial qty (silent negative ATS)
- **Break attempt:** Approve 80 on lot inward 100. Desk-edit Container lot `inward_qty` to 50 (Fresko Approver has Container write). `_validate_lots` only checks non-negative + sum==container.inward_qty. No compare to `approved_sold` / ATS. `available_to_sell` returns −30. Further OVERSELL or close math drifts; unreconciled commercial commitment.
- **Code path:** `FreskoContainer._validate_lots` / `_validate_inward_qty` (reason flag only blocks inward change in Selling/Closing/Closed when `inward_qty_change_reason` flag unset — Approver can still set flag or change lot rows if validation passes sum). No call to `approved_sold` / ATS floor.
- **Fails closed?** **No** for post-approval stock integrity. Pre-approval ATS checks fail closed.
- **Residual gap:** Commercial oversell via master-data edit without D10 Exception; Phase 3 physical dispatch will inherit negative ATS.
- **Required fix:** On lot/container inward decrease, require `inward_qty >= approved_sold(container, lot)` (and container sum ≥ sum approved). Prefer Exception `DATA_INTEGRITY` + Approver/SM reason. Test `test_lot_inward_cannot_drop_below_approved_sold`.
- **Missing test:** `test_lot_inward_cannot_drop_below_approved_sold`

#### F-H2 — `decide` allowed from `Proposed` skips `apply_rate_rules` (floor/ceiling snapshot bypass)
- **Break attempt:** Create Proposed deal below floor. Skip `apply_rate_rules`. Call `decide(..., "APPROVE", decision_rate=proposed, reason=…)`. Allowed status includes `Proposed`. Approval row may store null `rate_floor`/`rate_ceiling`; deal → Approved without band evaluation / STOCK_SHORTFALL auto-path.
- **Code path:** `approvals.decide` status allow-list; APPROVE branch sets rates from `decision_rate` or `proposed_rate` only.
- **Fails closed?** **Partial** — ATS still checked under `FOR UPDATE`; rate-band policy does **not** fail closed.
- **Residual gap:** Silent policy bypass of D5 auto vs approval-required split; audit Approval lacks floor snapshot.
- **Required fix:** Restrict `decide` to `Approval Required` only (and maybe Rejected recovery later). Force `apply_rate_rules` first. Test `test_decide_rejects_from_proposed`.
- **Missing test:** `test_decide_only_from_approval_required`

#### F-H3 — `test_fresko_deal.py` targets nonexistent `fresko_universe.api` and wrong concurrent semantics
- **Break attempt:** `bench run-tests --app fresko_universe` imports `fresko_deals/doctype/fresko_deal/test_fresko_deal.py` → `from fresko_universe.api import deals` → **ImportError**. Even if patched, `test_concurrent_deals_cannot_over_approve_lot_stock` expects `apply_rate_rules` to **throw** on second deal; live `deals.apply_rate_rules` sets `Approval Required` + Exception (acceptance test is correct). Also calls `transition_deal`, `apply_revision_approval`, `allow_oversell=` — APIs not in scaffold.
- **Code path:** Stale doctype test vs `deals.py` / `approvals.py` / `tests/test_phase1_acceptance.py`.
- **Fails closed?** N/A (test harness). **Merge risk:** PR claims bench tests; doctype suite will fail/crash.
- **Residual gap:** False confidence; duplicate divergent acceptance specs.
- **Required fix:** Delete or rewrite `test_fresko_deal.py` to import `fresko_universe.deals` / `fresko_universe.approvals` and match soft-ATS behavior. Single source of truth = `test_phase1_acceptance.py`.
- **Missing test:** N/A — fix drift; keep acceptance tests as canonical.

#### F-H4 — Commercial qty/lot/container editable in `Approval Required` / `Proposed` after rules snapshot
- **Break attempt:** `apply_rate_rules` → Approval Required (below floor). Salesperson (Deal write) raises `qty` or swaps `lot_no` / `container` before `decide`. `_enforce_commercial_lock` only applies when status ∈ `COMMERCIAL_LOCK_STATUSES` (starts at Auto Approved/Approved/Countered). ATS at `decide` mitigates oversell; rate band / lot identity / buyer intent can still mutate without re-running rules or revision.
- **Code path:** `FreskoDeal._enforce_commercial_lock`; `COMMERCIAL_LOCK_STATUSES` omits `Proposed` and `Approval Required`.
- **Fails closed?** **Partial** — stock fail-closed at decide; commercial term mutation open.
- **Residual gap:** Approve different lot/qty than what Approver thought when opening the Approval Required queue; container membership re-validated on save (good) but silent bait-and-switch remains.
- **Required fix:** Freeze `qty`, `lot_no`, `container`, `container_lot`, `proposed_rate`, `count_size` once status leaves `Proposed` (or once `apply_rate_rules` runs), except via `request_revision`. Test `test_qty_frozen_after_approval_required`.
- **Missing test:** `test_commercial_fields_frozen_in_approval_required`

---

### MEDIUM

#### F-M1 — No whitelist cancel / outward / payment transition APIs
- Blueprint: transitions only via whitelist methods. Implemented whitelist paths only cover rate-rules → Auto/Approval Required, decide → Approved/Countered/Rejected, accept_counter → Approved, revision apply. **Cancelled** and all post-Approved ops statuses have **no** production method; Desk blocked by `allow_status_transition`. Acceptance tests force flags / `frappe.db.set_value` (container test), teaching a bypass.
- **Fails closed?** Yes for illegal Desk jumps; **ops stuck** without console flags.
- **Required fix:** Add `cancel_deal` / Phase-2 outward stubs; never document `db.set_value` as test setup for status.
- **Missing test:** `test_cancel_deal_whitelist_requires_reason`

#### F-M2 — `apply_revision` lets Approver/SM apply rate/qty without Approval document
- Commercial revision requires `approval_name` **or** Approver role — soft audit. Approver can change `approved_rate`/`qty` with only Fresko Revision row.
- **Code path:** `deals.apply_revision` commercial branch.
- **Required fix:** Always require linked Fresko Approval for rate/qty/lot; role alone insufficient.
- **Missing test:** `test_qty_revision_requires_approval_document`

#### F-M3 — Fingerprint day-boundary / missing `source_message_id` allows same commercial body next day
- `make_fingerprint` includes calendar day from `created_on`. Forwarded copy next day without message_id → new Deal. Unique indexes help same-day/same-id cases.
- **Fails closed?** Yes same day / same message_id; **partial** across days.
- **Required fix:** Phase 2 ingest: content-hash Evidence + optional multi-day soft match Exception (document as known residual).
- **Missing test:** `test_forwarded_copy_next_day_opens_duplicate_review_exception` (Phase 2)

#### F-M4 — Container `Fully Reconciled` ignores deal reconciliation / ATS residual
- `_validate_close_gate` blocks on listed open material Exceptions only; does not require deals Reconciled, ATS≈0, or no Approved-without-Customer.
- **Required fix:** Gate on open BUYER_UNRESOLVED already partial via exceptions; add ATS residual + non-terminal deals check before Fully Reconciled.
- **Missing test:** `test_fully_reconciled_blocked_when_approved_qty_remains`

#### F-M5 — `DEVIATIONS.md` DV4 does not match code (documentation lie)
- DV4 claims oversell = System Manager only; code + smoke test disagree. Reviewers trusting DEVIATIONS get false assurance.
- **Required fix:** Align doc ↔ constants ↔ tests (prefer tightening code to DV4).

#### F-M6 — `accept_counter` authorization hole when `salesperson_user` empty
- Non-originator Fresko Salesperson can accept if `salesperson_user` falsy (second throw skipped).
- **Required fix:** Require `user in {owner, salesperson_user}` unless Approver/SM; if salesperson_user empty, only owner or Approver/SM.
- **Missing test:** `test_other_salesperson_cannot_accept_counter`

#### F-M7 — Empty rate band auto-approves (`rate_in_band` True when floor & ceiling None)
- Misconfigured container → all Proposed deals Auto Approved if ATS OK.
- **Required fix:** Treat missing floor as Approval Required (policy) or throw on apply_rate_rules.
- **Missing test:** `test_missing_rate_floor_forces_approval_required`

#### F-M8 — Duplicate fingerprint side-effects swallowed
- `_raise_duplicate_fingerprint` bare `except Exception: log_error` then throw — Deal creation fails closed, but Evidence/Exception may be missing (acceptance asserts weakly: `after_ex or evidence count`).
- **Required fix:** Narrow except; fail closed if side-effects fail **or** re-raise after ensuring Exception. Strengthen acceptance assert both Evidence + Exception.

---

### LOW

#### F-L1 — `container_lot` revision is effectively a no-op
- `_validate_lot_belongs_to_container` always rewrites `container_lot` from `lot_no`. Revising `container_lot` alone cannot retarget lot.
- **Fix:** Disallow `container_lot` in `request_revision` allowed_fields; require `lot_no`.

#### F-L2 — `Fresko Owner` in oversell roles but not installed
- `install.ROLES` / fixtures omit Owner.

#### F-L3 — Close gate exception list omits `OTHER` (in `MATERIAL_EXCEPTION_TYPES`)
- Open OTHER does not block Fully Reconciled.

#### F-L4 — Lot override early-return can drop container ceiling
- `resolve_rate_band`: if only floor override set, returns `(floor, None)` and never merges container ceiling.

#### F-L5 — Smoke `TestD10` freezes incorrect oversell policy
- See F-C2.

---

### INFO

#### F-I1 — Physical oversell / outward children deferred to Phase 3
- D10 “never physical dispatch beyond stock” cannot be enforced yet (no DN/outward child). `dispatched_qty` exists for ATS math but no whitelist dispatch API. Judge: Phase 1 leaves an intentional hole; commercial D10 Exception path is the interim control — currently too weak (F-C2).

#### F-I2 — `frappe.db.set_value` bypasses Document.validate
- Platform residual. Acceptance container test uses set_value to force status — do not ship that pattern as supported API.

#### F-I3 — Unique DB indexes on `source_message_id` / `duplicate_fingerprint`
- JSON `unique: 1` — concurrent duplicate inserts fail closed at DB even if TOCTOU races `db.exists`. Good.

---

## Attack matrix (8 focus areas)

### 1. Duplicate fingerprint (same message_id / fingerprint / forwarded copy)
| | |
|---|---|
| **Break attempt** | Retry same `source_message_id`; second Deal same alias/container/lot/qty/rate/uom/day; forward without message_id same day; forward next day |
| **Code path** | `FreskoDeal._validate_idempotency_keys`, `_raise_duplicate_fingerprint`, `make_fingerprint`; JSON unique on both fields |
| **Fails closed?** | **Yes** for same message_id and same-day fingerprint (validate throw + unique index). Evidence/Exception best-effort (F-M8). **Partial** next-day forward (F-M3) |
| **Residual gap** | Cross-day duplicate commercial body; ingest not in Phase 1 |
| **Required fix** | Harden side-effects; Phase 2 soft match |
| **Missing test** | `test_concurrent_duplicate_fingerprint_db_unique`; `test_forwarded_copy_next_day_…` |

### 2. Concurrent oversell (ATS / lot stock)
| | |
|---|---|
| **Break attempt** | Two Proposed in-band deals qty 40+40 on inward 50; parallel `apply_rate_rules`; or dual `decide` on Approval Required |
| **Code path** | `ats.available_to_sell(..., for_update=True)` → `SELECT … FOR UPDATE` on Container; `ATS_ACTIVE_STATUSES` excludes Proposed/Approval Required/Countered; `apply_rate_rules` / `decide` / `accept_counter` re-read under lock |
| **Fails closed?** | **Yes** under InnoDB + single-request transaction (second sees reduced ATS → Approval Required or throw). Soft ATS intentional (C7) |
| **Residual gap** | Inward master edit after approve (F-H1); no true integration concurrency test in unit suite |
| **Required fix** | F-H1; optional bench thread test |
| **Missing test** | Real concurrent/`FOR UPDATE` race under bench |

### 3. Wrong lot/container membership
| | |
|---|---|
| **Break attempt** | Deal `lot_no` not on container; point `container_lot` at another row; change container while Proposed |
| **Code path** | `FreskoDeal._validate_lot_belongs_to_container` |
| **Fails closed?** | **Yes** on save when lot_no∉container lots; syncs container_lot to matching row |
| **Residual gap** | Container switch in Proposed/Approval Required (F-H4); container_lot revision noop (F-L1) |
| **Required fix** | Freeze container after Proposed; disallow orphan container_lot revisions |
| **Missing test** | `test_container_change_blocked_after_approval_required` |

### 4. Post-approval rate/qty edit without revision
| | |
|---|---|
| **Break attempt** | Desk edit `approved_rate`/`qty` on Auto Approved; API save without flags |
| **Code path** | `_enforce_commercial_lock` + `allow_approval_write` / `allow_commercial_revision`; `approved_rate` JSON read_only; `deals.request_revision` / `apply_revision` |
| **Fails closed?** | **Yes** for Desk/document save after commercial lock (acceptance `test_desk_edit_approved_rate_rejected`). **Partial** — Approver can apply revision without Approval doc (F-M2); `db.set_value` bypass (F-I2) |
| **Residual gap** | Soft revision audit; unlocked fields pre-lock (F-H4) |
| **Required fix** | F-M2, F-H4 |
| **Missing test** | `test_post_approval_qty_edit_requires_revision` |

### 5. Unresolved buyer (Reconciled / commercial progression)
| | |
|---|---|
| **Break attempt** | Auto Approve with `customer` empty; drive to Paid; set Reconciled; waive Exception without Customer |
| **Code path** | `_maybe_open_buyer_unresolved`; `_validate_reconciled_gate` (requires customer + no open BUYER_UNRESOLVED) |
| **Fails closed?** | **Yes** on Reconciled (C9/D6 as locked). Approved/Outward without Customer **allowed by design** |
| **Residual gap** | Phase 1 has no SO/invoice yet — C9 SO/party-ledger block N/A until Phase 3; Fully Reconciled may still ignore deal-level buyer if Exception waived incorrectly but customer check remains |
| **Required fix** | Keep gate; add SO hooks in Phase 3; F-M4 |
| **Missing test** | `test_reconciled_still_blocked_if_customer_cleared` |

### 6. Counter without accept
| | |
|---|---|
| **Break attempt** | COUNTER then Desk → Outward Pending; COUNTER then `decide(APPROVE)`; COUNTER then accept by wrong user |
| **Code path** | `decide` COUNTER → Countered; `accept_counter`; transition matrix blocks Outward from Countered; **F-C1** decide APPROVE from Countered |
| **Fails closed?** | **Partial** — Desk Outward blocked (**yes**); D4 accept path exists (**yes**); decide bypass (**no**, F-C1) |
| **Residual gap** | F-C1, F-M6 |
| **Required fix** | F-C1 primary |
| **Missing test** | `test_decide_cannot_approve_from_countered_must_use_accept_counter` |

### 7. D10 physical oversell
| | |
|---|---|
| **Break attempt** | OVERSELL_OVERRIDE as Approver; approve qty > ATS; later (Phase 3) dispatch beyond stock; lower inward (F-H1) |
| **Code path** | `approvals.decide` OVERSELL_OVERRIDE → Exception Critical + Approved; no SLE/DN in Phase 1 |
| **Fails closed?** | **No** vs D10 role intent (F-C2). Commercial oversell is explicit + Exception (**partial**). Physical dispatch **deferred** Phase 3 (F-I1) |
| **Residual gap** | Role inflation; inward edit; no physical cap yet |
| **Required fix** | F-C2, F-H1; Phase 3 dispatch ≤ remaining |
| **Missing test** | `test_d10_oversell_restricted_to_system_manager_not_approver` |

### 8. Illegal status jumps
| | |
|---|---|
| **Break attempt** | Desk Proposed → Reconciled; Countered → Outward Pending; Closed container reopen |
| **Code path** | `FreskoDeal._validate_status_transition` requires `flags.allow_status_transition` + `DEAL_TRANSITIONS`; `FreskoContainer._validate_status_transition` |
| **Fails closed?** | **Yes** on Document.save without flag / illegal edge. **Partial** — no cancel whitelist (F-M1); set_value bypass (F-I2) |
| **Residual gap** | Production cannot Cancel without new API or flag abuse |
| **Required fix** | Whitelist cancel; ban set_value in tests |
| **Missing test** | Covered partially by `test_illegal_status_transition_rejected` |

---

## What tests cover vs miss

### Ran successfully (no bench)
| Suite | Result |
|---|---|
| `tests/test_smoke_unit.py` (`unittest`) | **12 OK** |
| `fresko_universe/tests/test_constants_and_fingerprint.py` (`unittest`) | **10 OK** |
| `pytest` | **Not installed** — used unittest instead |
| `test_phase1_acceptance.py` | **Not run** — requires Frappe bench / ERPNext site |
| `test_fresko_deal.py` / `test_fresko_container.py` | **Not run** — bench; deal test would ImportError on `fresko_universe.api` |

### Covered (by design of acceptance/smoke — many unexecuted on this box)
- Duplicate message_id / fingerprint throw paths (acceptance)
- Lot not on container
- Below-floor → Approval Required; approve keeps proposed_rate
- Desk approved_rate edit rejected
- Revision apply trail (acceptance; soft Approver path)
- Unresolved buyer blocks Reconciled
- Illegal Desk status jump
- Soft ATS: Proposed excluded; sequential second deal → Approval Required; decide ATS throw
- D4 happy path Counter → accept_counter
- Fully Reconciled blocked with open Exception
- Constants: Countered transitions, ATS sets, fingerprint shape, D5 hierarchy (unit)
- Layout/DocType JSON names (smoke)

### Missed / weak
- **decide from Countered** (F-C1) — not attacked
- **D10 Approver oversell** — smoke asserts wrong allow
- Concurrent true parallelism / FOR UPDATE under load
- Inward qty drop below approved_sold (F-H1)
- decide from Proposed (F-H2)
- Freeze fields in Approval Required (F-H4)
- Revision without Approval document (F-M2)
- Cancel whitelist; next-day fingerprint
- Stale `test_fresko_deal.py` API surface (`transition_deal`, `apply_revision_approval`, `allow_oversell`)
- Acceptance buyer test forces status with flags (does not prove production path to Paid)

---

## Residual risks before merge / before Phase 2

**Before merge (blockers / should-fix):**
1. Close F-C1 (D4 bypass) and F-C2 (D10 roles) — control regressions vs locked decisions.
2. Repair or remove `test_fresko_deal.py` (F-H3) so `bench run-tests` is not dead on import.
3. Align `DEVIATIONS.md` DV4 with code (or code with DV4).
4. Prefer fixing F-H1 (inward vs approved_sold) before any Selling-environment demo — silent negative ATS.

**Before Phase 2 (WhatsApp ingest):**
- Harden fingerprint side-effects; define cross-day duplicate policy; wire ingest to unique message_id + fingerprint only.
- Add cancel whitelist; freeze commercial fields after Proposed/rules.

**Before Phase 3 (outward / SO / SLE):**
- Physical cap vs ATS; dispatched child lines; SO/party-ledger block while BUYER_UNRESOLVED (C9 extension); remove reliance on `dispatched_qty` free-edits without status machine.
- Do not treat Phase 1 OVERSELL Exception as permission to ship — D10 physical rule still open (F-I1).

---

## Recommended fixes (ordered)

1. **F-C1:** `decide` must not accept `Countered` for APPROVE/COUNTER/OVERSELL; only `accept_counter` → Approved. Add rejection test.
2. **F-C2:** `OVERSELL_OVERRIDE_ROLES = {"System Manager"}` (+ Owner only after role exists). Fix smoke TestD10; add negative Approver test. Sync DV4.
3. **F-H3:** Rewrite/delete stale `test_fresko_deal.py`; make `test_phase1_acceptance.py` the only integration suite.
4. **F-H1:** Reject lot/container inward decrease below `approved_sold`.
5. **F-H2:** `decide` only from `Approval Required`.
6. **F-H4:** Extend commercial lock (or explicit freeze) to post-`apply_rate_rules` / non-Proposed.
7. **F-M2:** Commercial `apply_revision` requires Approval link always.
8. **F-M1:** Add `cancel_deal` whitelist; stop using `db.set_value` for status in tests.
9. **F-M5/M6/M7/M8:** Doc alignment, accept_counter ACL, missing floor policy, fingerprint side-effect hardening.
10. Phase 2/3 items: ingest duplicates, outward ≤ ATS, SO block on unresolved buyer.

---

## PR skim note
`gh pr view 1 --repo AnubhavDubey02/fresko-universe` succeeded. PR body claims D10 “Owner/Admin only” and smoke tests OK; local smoke **passed** (12) but **code currently allows Fresko Approver oversell**, contradicting PR summary and DV4. Bench install/run-tests still unchecked on this runner.

---

*Fresko adversarial QA — independent attack of PR #1 Phase 0/1 scaffold. No production code modified except this report.*
