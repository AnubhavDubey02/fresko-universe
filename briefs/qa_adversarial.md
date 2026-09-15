# Fresko Universe — Adversarial QA Design Memo

**Audience:** Phase 1 implementers (Fresko Container + Fresko Deal on ERPNext v15)  
**Author role:** Adversarial QA specialist  
**Date:** 15 September 2026  
**Status:** Design gate for fail-closed behaviour before coding Deal/Container guards  
**Source of truth:** `docs/FRESKO_UNIVERSE_CODEX_START_HERE.md` (esp. §§3, 7–11, 21, 22, 30 Phase 1)

---

## 0. Purpose and scope

This memo attacks the **proposed Phase 1** Fresko Container + Fresko Deal design:

- Custom DocTypes on **ERPNext v15 / Frappe**
- **Fresko Deal** fields of interest: `proposed_rate`, `approved_rate`, status machine including `PROPOSED` / `APPROVAL_REQUIRED` / `APPROVED` / `OUTWARD_PENDING` / `DISPATCHED` (and related), `source_message_id`, `duplicate_fingerprint`, `unresolved_buyer_alias`, lot/batch link, container link
- Deterministic rules: rate floor, stock availability, duplicate/idempotency, no silent edits of approved financial truth

**Goal:** For each attack, define how the system must **fail closed**, which **Fresko Exception** type (from the brief list) applies when an exception is the correct product outcome (vs hard reject), and a **named automated test** that will catch regressions.

Exception types referenced (brief §21):

`OUTWARD_WITHOUT_DEAL`, `DEAL_WITHOUT_OUTWARD`, `RATE_BELOW_FLOOR`, `RATE_CHANGED_AFTER_APPROVAL`, `QTY_EXCEEDS_AVAILABLE_STOCK`, `LOT_OVERDRAWN`, `DUPLICATE_MESSAGE`, `DUPLICATE_GATEPASS`, `PAYMENT_REPORTED_NOT_VERIFIED`, `PAYMENT_UNMATCHED`, `BUYER_UNRESOLVED`, `QC_EVIDENCE_MISSING`, `COMPLAINT_WITHOUT_QC_HISTORY`, `CONTAINER_QTY_NOT_RECONCILED`, `SETTLEMENT_VALUE_MISMATCH`, `MANUAL_OVERRIDE`

---

## 1. Design assumptions under test

These are the behaviours Phase 1 is expected to implement. Attacks below try to violate them.

| # | Assumption |
|---|------------|
| A1 | Same WhatsApp `message_id` never creates a second financially consequential Deal. |
| A2 | Near-duplicate / forward with new `message_id` but same commercial fingerprint is detected via `duplicate_fingerprint` (or equivalent). |
| A3 | Approval / auto-approve must refuse when deal qty > lot `available_to_sell` (reservation semantics may be provisional; oversell is still forbidden). |
| A4 | Lot belongs to exactly one Container; Deal.container must match Lot.container (or fail closed). |
| A5 | After approval, `approved_rate` (and other approved commercial fields) cannot be silently mutated via Desk, REST, or amend without revision + reason + trail (and often re-approval). |
| A6 | A Deal may carry `unresolved_buyer_alias`, but **cannot** reach financially final / dispatch-eligible states without a confirmed Customer (or an explicit, audited override that raises `BUYER_UNRESOLVED` / `MANUAL_OVERRIDE`). |
| A7 | Partial dispatch must update commercial vs physical ledgers without double-counting cancelled remainder as both sold and cancelled, or as both pending and dispatched. |

Fail-closed means: **prefer reject / block transition / open exception** over allowing a quiet ledger lie.

---

## 2. Attack scenarios

### Scenario 1 — Duplicate WhatsApp orders

**Threat:** Operator or webhook retries, or a forwarded message, create two Deals for one commercial intent → double stock reservation, double sales, false partner realisation.

#### 1a. Retry same `message_id`

| | |
|---|---|
| **Attack steps** | 1. Ingest WhatsApp payload `message_id=wamid.AAA` → creates Deal D1 (`PROPOSED` or beyond). 2. Re-deliver identical webhook (Meta retry / client double-post) with same `message_id=wamid.AAA`. 3. Observe whether a second Deal D2 is created or stock reserved twice. |
| **Expected fail-closed behaviour** | Ingestion is idempotent on `source_message_id` (unique constraint or Evidence/ingest ledger). Second call returns the existing Deal (or no-op success) and **does not** create D2, reserve stock again, or fire a second approval. Persist Evidence once; subsequent attempts attach to same evidence chain. |
| **Exception type** | `DUPLICATE_MESSAGE` — optional/telemetry if a second attempt is logged as an exception for ops visibility; **must not** create a second commercial Deal. Prefer hard idempotent reject/no-op over soft “create then exception.” |
| **Automated test** | `test_ingest_retry_same_message_id_is_idempotent` — Assert: after two ingest calls with identical `message_id`, `frappe.db.count("Fresko Deal", {"source_message_id": mid}) == 1`; stock `available_to_sell` decreased at most once; second response references same `deal_id`. |

#### 1b. Forward with new `message_id`, same content

| | |
|---|---|
| **Attack steps** | 1. Ingest order text `Rehan 50 crate 41869 650` as `wamid.AAA` → Deal D1. 2. Forward/resend same commercial text from another chat as `wamid.BBB`. 3. Confirm whether D2 is auto-created and approved path continues. |
| **Expected fail-closed behaviour** | Compute `duplicate_fingerprint` over normalized commercial keys (e.g. container/lot, qty, rate, buyer alias/customer, unit, day window, content hash). New `message_id` with matching fingerprint → **do not auto-approve / do not silently create a second open reservation**. Open `DUPLICATE_MESSAGE` exception (or hold Deal in review) until a human confirms “same order” (link/merge) vs “intentional second order.” |
| **Exception type** | `DUPLICATE_MESSAGE` |
| **Automated test** | `test_forwarded_message_new_id_same_fingerprint_raises_duplicate` — Assert: second ingest with different `message_id` and same fingerprint creates at most a pending review Deal **or** zero new open reservations; creates Exception type `DUPLICATE_MESSAGE`; approved_sold / available_to_sell unchanged until human resolve. |

#### 1c. Near-duplicate (typo / spacing / rate drift)

| | |
|---|---|
| **Attack steps** | 1. Deal D1 from `Rehan 50 / 41869 / 650`. 2. Submit `Rehaan 50 crate 41869 650` or `Rehan 50 41869 649` within a short window. 3. Attempt auto-approval of both. |
| **Expected fail-closed behaviour** | Fingerprint uses normalized alias + exact commercial numerics where material. Near-matches (alias fuzzy, rate ±1, same lot/qty) route to human review, not auto-approve. Exact numeric mismatch on qty/rate is **not** fuzzy-merged for financial fields (brief §15). Soft similarity → review + optional exception, never silent merge that alters qty/rate. |
| **Exception type** | `DUPLICATE_MESSAGE` (near-dupe review); if both somehow approved and oversell → also `QTY_EXCEEDS_AVAILABLE_STOCK` / `LOT_OVERDRAWN` |
| **Automated test** | `test_near_duplicate_alias_spelling_requires_human_review` — Assert: second proposal with alias variant + same lot/qty/rate does not `AUTO_APPROVED`; status is review/`APPROVAL_REQUIRED` or Exception `DUPLICATE_MESSAGE`; no double reservation without explicit confirm. |

---

### Scenario 2 — Insufficient lot stock (approve more than `available_to_sell`)

**Threat:** Race or Desk approval sells more crates than the lot can support → container close cannot reconcile; partner overstatement.

| | |
|---|---|
| **Attack steps** | 1. Lot L1: `available_to_sell = 40`. 2. Create Deal A qty=30 → approve (or leave `OUTWARD_PENDING` reserving 30). 3. Concurrently create Deal B qty=20 for same lot → attempt approve / auto-approve. 4. Variant: single Deal qty=50 when available=40. 5. Variant: two Desk users approve A and B in parallel without DB-level locking. |
| **Expected fail-closed behaviour** | Stock check runs inside the **same transactional boundary** as status transition to `APPROVED` / `AUTO_APPROVED` / reservation. Deal B (or oversized Deal) is rejected or stays `APPROVAL_REQUIRED`/`PROPOSED` with rule reason; **must not** reach `APPROVED` if `qty > available_to_sell` after accounting for other approved/pending reservations per defined Phase 1 reservation rule. Prefer DB row lock / `SELECT … FOR UPDATE` on lot stock snapshot or atomic decrement. Opening Exception is allowed **in addition to** blocking approval when an override path exists; override requires `MANUAL_OVERRIDE` + reason + actor. |
| **Exception type** | `QTY_EXCEEDS_AVAILABLE_STOCK`; if lot inward exceeded by cumulative approved → also `LOT_OVERDRAWN` |
| **Automated test** | `test_approve_deal_qty_exceeds_available_to_sell_is_rejected` — Assert: approving qty=50 when available=40 raises `ValidationError` (or Fresko rule error); Deal status not in `{APPROVED, AUTO_APPROVED, OUTWARD_PENDING}`; Exception `QTY_EXCEEDS_AVAILABLE_STOCK` recorded if product policy creates exceptions on blocked attempts; `available_to_sell` unchanged. Companion: `test_concurrent_approvals_cannot_oversell_lot` — two parallel approve RPCs for 30+20 on available=40 → exactly one succeeds, one fails; final reserved ≤ 40. |

---

### Scenario 3 — Wrong container (lot belongs to A, deal points to B)

**Threat:** Salesperson selects wrong container header while typing a known lot from another shipment → cross-container stock/P&L contamination.

| | |
|---|---|
| **Attack steps** | 1. Container A owns Lot `41869`. 2. Container B exists (different shipment). 3. Create/update Deal with `lot=41869` and `container=B` via Desk and via `POST /api/resource/Fresko Deal`. 4. Attempt approve and outward link under B. |
| **Expected fail-closed behaviour** | Validate on validate/save and again on approve: `Lot.container == Deal.container`. Mismatch → hard `ValidationError`; no approval, no stock movement against B, no partner view under B. Prefer auto-deriving container from lot (read-only field) to remove the attack surface; if both fields are user-editable, mismatch is always fatal. |
| **Exception type** | Prefer **hard reject** (no financial event). If a mismatch is discovered post-facto (data import), raise a severe exception — closest fit `CONTAINER_QTY_NOT_RECONCILED` or treat as integrity fault logged as `MANUAL_OVERRIDE` only if an authorized repair path is used. Do **not** use soft `BUYER_UNRESOLVED`-style continue. |
| **Automated test** | `test_deal_lot_container_mismatch_rejected_on_validate` — Assert: insert/update Deal with lot of container A and container=B raises validation; document not saved (or not submitted); no Exception needed for clean reject path. Also: `test_approve_blocks_when_lot_container_diverges` if container can be edited after draft. |

---

### Scenario 4 — Changed sale rate after approval

**Threat:** After owner approval, someone edits rate on Desk, patches via API, or “amends” to rewrite history → silent P&L change (violates §3.3 No silent edits).

#### 4a. Desk edit

| | |
|---|---|
| **Attack steps** | 1. Deal approved at `approved_rate=600` (or counter decision_rate). 2. As System Manager / Accounts / Salesperson, open Desk and change `approved_rate` to `550` (or `proposed_rate` after approval). 3. Save without revision DocType. |
| **Expected fail-closed behaviour** | Field permissions + server `validate`/`on_update`: approved commercial fields are immutable except through `Fresko Approval` / revision API that stores old_value, new_value, changed_by, changed_at, reason, evidence, approval_reference. Direct Desk save must fail. |
| **Exception type** | `RATE_CHANGED_AFTER_APPROVAL` if a change is attempted or if an audit job detects drift; successful authorized revision may also log `MANUAL_OVERRIDE` when policy requires elevated override. |
| **Automated test** | `test_desk_edit_approved_rate_is_rejected` — Assert: `doc.approved_rate = 550; doc.save()` on APPROVED deal raises; DB value remains 600; optional Exception `RATE_CHANGED_AFTER_APPROVAL` on attempt. |

#### 4b. API patch

| | |
|---|---|
| **Attack steps** | 1. `PUT/PATCH /api/resource/Fresko Deal/{name}` with `{"approved_rate": 550}` using a token that has write permission on the DocType. 2. Also try `frappe.client.set_value`. |
| **Expected fail-closed behaviour** | Same server-side immutability as Desk — REST must not bypass hooks. Permission alone is insufficient; state machine + field lock apply. |
| **Exception type** | `RATE_CHANGED_AFTER_APPROVAL` |
| **Automated test** | `test_api_patch_approved_rate_is_rejected` — Assert: REST/`set_value` cannot change `approved_rate` post-approval; response 417/417-equivalent or ValidationError; DB unchanged. |

#### 4c. Amend / cancel-and-recreate abuse

| | |
|---|---|
| **Attack steps** | 1. Use ERPNext-style amend pattern (or cancel Deal and create new with same `source_message_id` / fingerprint) to “fix” rate to 550 while keeping old outward links. 2. Or amend only rate without new Approval record. |
| **Expected fail-closed behaviour** | Amend of approved Deal either forbidden in Phase 1, or creates a **new revision chain**: prior approved values remain queryable; new rate requires fresh Approval; linked outward/payment still point at immutable commercial snapshot or explicit supersession. Cancelled original must release reservation; new Deal re-checks stock and rate floor. Silent amend that rewrites history is forbidden. |
| **Exception type** | `RATE_CHANGED_AFTER_APPROVAL`; if cancel/recreate duplicates message → `DUPLICATE_MESSAGE` |
| **Automated test** | `test_amend_approved_deal_requires_revision_and_reapproval` — Assert: amend/cancel-recreate without new Approval cannot yield an APPROVED deal at a new rate with same commercial identity; revision table (or Approval child) contains old/new; or operation raises. |

---

### Scenario 5 — Unresolved buyer (approved with only alias, no Customer)

**Threat:** Alias-only deals (`AZ/SSK`, `Rehan`) reach `APPROVED` / dispatch / receivable without Customer → unbillable debt, broken party ledger, partner opacity.

| | |
|---|---|
| **Attack steps** | 1. Create Deal with `unresolved_buyer_alias="AZ/SSK"`, `customer` empty. 2. Propose rate inside floor → attempt `AUTO_APPROVED` or owner Approve. 3. Advance toward `OUTWARD_PENDING` / `DISPATCHED` / payment matching. 4. Variant: confirm alias later to wrong Customer after dispatch. |
| **Expected fail-closed behaviour** | Phase 1 policy (recommended hard gate): **cannot leave `PROPOSED`/`APPROVAL_REQUIRED` into `APPROVED`/`AUTO_APPROVED`** without linked Customer **or** an explicit owner override that: (a) keeps Deal flagged, (b) creates Exception `BUYER_UNRESOLVED`, (c) blocks ERPNext Sales Invoice / Payment Entry matching until resolved. Soft-allow for draft/proposal is OK; soft-allow for dispatch is not. Alias string always preserved (never destroyed). |
| **Exception type** | `BUYER_UNRESOLVED` (required while alias-only past commercial gate); override trail → `MANUAL_OVERRIDE` |
| **Automated test** | `test_approve_without_customer_blocked_or_raises_buyer_unresolved` — Assert: approve with empty customer and only alias either raises ValidationError **or** (if override role) creates Exception `BUYER_UNRESOLVED` and Deal remains non-final / non-invoiceable; `test_dispatch_blocked_while_buyer_unresolved` — cannot reach `DISPATCHED` while exception open / customer null. |

---

### Scenario 6 — Partial dispatch (20 of 50; cancel remainder; double-count risk)

**Threat:** Partial outward + cancel remainder double-counts crates in sold, cancelled, pending, or outward ledgers → classic “3104 vs 3193 vs 3196” close failure.

| | |
|---|---|
| **Attack steps** | 1. Approved Deal qty=50, status `OUTWARD_PENDING`. 2. Record dispatch qty=20 → expect `PARTIALLY_DISPATCHED` (or equivalent) with pending=30. 3. Cancel remainder 30. 4. Attack variants: (i) cancel full 50 while 20 already outward; (ii) second dispatch of 20 without reducing pending; (iii) re-open cancel and dispatch again; (iv) container snapshot sums `approved_sold + cancelled + outward` inconsistently. |
| **Expected fail-closed behaviour** | Maintain **distinct quantities** on the Deal (or child Dispatch lines): `qty_approved`, `qty_dispatched`, `qty_pending_outward`, `qty_cancelled` with invariant: `qty_approved = qty_dispatched + qty_pending_outward + qty_cancelled` (Phase 1 may implement a subset; invariant must hold for implemented fields). Cancel remainder may only cancel **pending**, never already-dispatched qty, without a reverse outward / exception workflow. Container snapshot uses named categories (brief §2, §27) — no plug figure. Double post of same gatepass → `DUPLICATE_GATEPASS` (Phase 3-ish, but Deal must not increment dispatched twice for same evidence). |
| **Exception type** | On invariant break: `CONTAINER_QTY_NOT_RECONCILED` and/or `DEAL_WITHOUT_OUTWARD` / over-dispatch analogue; duplicate outward evidence → `DUPLICATE_GATEPASS`; forced repair → `MANUAL_OVERRIDE` |
| **Automated test** | `test_partial_dispatch_then_cancel_remainder_preserves_qty_invariant` — Assert: after dispatch 20 and cancel 30 on approved 50: dispatched=20, cancelled=30, pending=0; `approved == dispatched + pending + cancelled`; container snapshot `approved_sold` / `physical_outward` / `cancelled` / `pending_outward` do not double-count the 20. Also: `test_cancel_cannot_include_already_dispatched_qty` — cancel 50 after dispatch 20 raises; `test_second_dispatch_same_evidence_does_not_double_count` if evidence id present. |

---

## 3. Cross-cutting controls (apply to all scenarios)

1. **Server-side only:** Never trust Desk client or WhatsApp parser for stock, uniqueness, or immutability.
2. **State machine:** Illegal transitions (`PROPOSED` → `DISPATCHED`, `REJECTED` → `APPROVED` without new proposal, etc.) raise validation errors.
3. **Evidence retention:** Every blocked attack that came from WhatsApp still stores Evidence; financial Deal is what must not duplicate.
4. **Roles:** Salesperson cannot self-approve below floor or clear `BUYER_UNRESOLVED` / `RATE_CHANGED_AFTER_APPROVAL`.
5. **Tests run in Frappe test runner** (`frappe.get_doc` / `frappe.db` assertions), not only unit-mocked fingerprint helpers — include at least one DB integration test per scenario above.
6. **Concurrency:** Scenarios 2 and 6 need explicit parallel or transactional tests; sequential tests alone will miss oversell races.

---

## 4. Suggested pytest / Frappe test method registry

| Scenario | Test method name | Assertion summary |
|----------|------------------|-------------------|
| 1a | `test_ingest_retry_same_message_id_is_idempotent` | One Deal per `source_message_id`; stock reserved once |
| 1b | `test_forwarded_message_new_id_same_fingerprint_raises_duplicate` | `DUPLICATE_MESSAGE`; no second open reservation |
| 1c | `test_near_duplicate_alias_spelling_requires_human_review` | No auto-approve; review or exception |
| 2 | `test_approve_deal_qty_exceeds_available_to_sell_is_rejected` | Approve blocked; `QTY_EXCEEDS_AVAILABLE_STOCK` |
| 2 | `test_concurrent_approvals_cannot_oversell_lot` | Parallel approve: reserved ≤ available |
| 3 | `test_deal_lot_container_mismatch_rejected_on_validate` | Save/approve fails on lot↔container mismatch |
| 4a | `test_desk_edit_approved_rate_is_rejected` | `approved_rate` immutable; DB unchanged |
| 4b | `test_api_patch_approved_rate_is_rejected` | REST/`set_value` cannot mutate approved rate |
| 4c | `test_amend_approved_deal_requires_revision_and_reapproval` | Amend needs revision + re-approval trail |
| 5 | `test_approve_without_customer_blocked_or_raises_buyer_unresolved` | No silent approve on alias-only |
| 5 | `test_dispatch_blocked_while_buyer_unresolved` | Cannot `DISPATCHED` without Customer / closed exception |
| 6 | `test_partial_dispatch_then_cancel_remainder_preserves_qty_invariant` | `approved = dispatched + pending + cancelled` |
| 6 | `test_cancel_cannot_include_already_dispatched_qty` | Cancel of dispatched qty rejected |
| 6 | `test_second_dispatch_same_evidence_does_not_double_count` | Same evidence id does not double outward |

Recommended module path (when app exists):  
`fresko_universe/fresko_universe/tests/test_deal_adversarial_qa.py`  
(or split `test_deal_idempotency.py`, `test_deal_stock_guards.py`, `test_deal_immutability.py`).

---

## 5. Residual risks Phase 1 Container/Deal cannot fully close

Phase 1 delivers Container, Deal, Approval, Evidence, Exception, QC Event DocTypes, rate-floor, stock availability, revision/audit, basic forms (brief §30). The following **cannot be fully closed** without later modules; document them as known residual risk, not as “handled.”

| Residual risk | Why Phase 1 is insufficient | Needs module / phase |
|---------------|-----------------------------|----------------------|
| **Physical outward without Deal** | No cold-storage outward import/link yet; cannot systematically raise `OUTWARD_WITHOUT_DEAL` from gatepass feeds. | Phase 3 — outward + reconciliation |
| **Duplicate gatepass / DO** | Deal-side qty invariant helps, but physical register duplicates need outward DocTypes + evidence dedupe. | Phase 3 — `DUPLICATE_GATEPASS` |
| **True available_to_sell vs warehouse truth** | Phase 1 may use Fresko lot counters only; ERPNext Batch/Stock Entry sync and multi-warehouse cold-storage authority come later. Race with external Excel stock still possible. | Phase 3 + ERPNext stock integration |
| **Payment screenshot = “paid”** | No payment state machine; approved Deals can still be verbally marked paid outside system. | Phase 4 — payments |
| **Buyer identity confidence / wrong confirm** | Alias field + block helps; candidate scoring, GST/phone evidence, confirm/reject workflow absent — wrong Customer link after the fact remains a residual. | Phase 7 — identity |
| **WhatsApp production idempotency at edge** | Deal fields exist, but Meta webhook signature verification, attachment id ledger, and ingest service are Phase 2. | Phase 2 — WhatsApp ingestion |
| **QC-linked commercial disputes** | QC Event DocType may exist, but complaint↔deal↔credit workflows and `COMPLAINT_WITHOUT_QC_HISTORY` automation are later. | Phase 5 — QC |
| **Container settlement certificate / partner view** | Snapshot arithmetic can be unit-tested in Phase 1; signed close, bilingual portal, and blocking close on open exceptions need Phase 8. | Phase 8 — partner + settlement |
| **AI mis-extraction creating plausible near-dupes** | Fingerprint helps; Tier-2/3 extraction errors need AI router + human correction capture. | Phase 6 — AI router |
| **Credit / exposure limits per buyer** | Open question (§35); not a Phase 1 deliverable — approved alias/Customer can still over-extend. | Policy decision + later rules |
| **Tax / SO timing** | Whether approve creates Sales Order immediately is unresolved; adversarial tests above must not assume GL finality. | CA input + accounting mapping |
| **Silent ERPNext native amend on linked SO/DN/SI** | Even if Fresko Deal is locked, linked standard documents could be amended unless hooks span those DocTypes. | Careful Phase 1–3 integration design |
| **Clock / timezone / “same day” fingerprint window** | Near-dupe windows are heuristic; determined attackers can wait out the window with a new `message_id`. | Operational policy + Phase 2/3 tuning |
| **Authorized malicious approver** | Fail-closed stops accidents and low-privilege abuse; a compromised Owner role can still approve oversell via `MANUAL_OVERRIDE` if that path exists — detect via audit, not prevent absolutely. | Audit export, dual-control later |

---

## 6. Pass / fail gate for Phase 1

Phase 1 Deal/Container design is **not ready to merge** until:

1. All Scenario 1–6 **fail-closed** behaviours are implemented or explicitly deferred with residual-risk entries (Section 5).
2. Named tests in Section 4 exist and pass in CI (concurrent oversell test included).
3. Exception types used match brief §21 names (no silent inventing of parallel enums).
4. No path allows approved rate or approved qty rewrite without revision trail (`old_value` / `new_value` / actor / time / reason / evidence).

**Working slogan for reviewers:** *If an attack succeeds quietly, the ledger lied. Prefer a red exception over a green wrong number.*

---

## 7. Changelog

| Date | Change |
|------|--------|
| 2026-09-15 | Initial adversarial QA memo for Phase 1 Container + Deal attacks (scenarios 1–6), exception mapping, test registry, residual risks. |
