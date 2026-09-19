# Phase 1 — Container + Deal architecture (ERPNext v15)

> **Superseded architecture proposal — 15 September 2026.** Retained as
> historical evidence. Its Sales-Order-on-approval recommendation was rejected
> by locked decision D1; the final blueprint requires soft reservation only.
> See `docs/CANONICAL_DOCUMENTS.md`.

Date: 15-Sep-2026  
Scope: Fresko Container + Fresko Deal only (Approval/Evidence linkage for acceptance scenario).  
Stack assumption: Frappe v15 + ERPNext v15 (Serial and Batch Bundle). Greenfield `fresko_universe` app.  
Source: `docs/FRESKO_UNIVERSE_CODEX_START_HERE.md`

## 1. ERPNext reuse map

| Concept | Use standard ERPNext | How Fresko links |
|---|---|---|
| Legal entity | **Company** | Container belongs to Company |
| Confirmed buyer | **Customer** | Deal.customer when alias resolved |
| Origin / Chinese partner | **Supplier** | Container.supplier_partner |
| SKU / produce type | **Item** (has_batch_no) | Deal.item; count/size/grade TBD (open) |
| Commercial LOT | **Batch** + Serial and Batch Bundle on stock txs | Store commercial lot no. on Batch (or custom field); never lose commercial LOT even if Batch name differs |
| Cold store / location | **Warehouse** | Inward and outward stock location |
| Physical inward | **Purchase Receipt** or **Stock Entry** (Material Receipt) | Linked from Container; creates batch stock |
| Commercial commitment | **Sales Order** | Created only after Deal approved (see §3) |
| Physical outward | **Delivery Note** | Created on dispatch; against SO when SO exists |
| Cleared money in | **Payment Entry** | Phase 4; not Phase 1 core |
| Tax invoice | **Sales Invoice** | Deferred — GST timing open |
| Container P&L slice | Prefer **Project** (= Container) or Accounting Dimension | Open decision |

Do **not** model Deal lifecycle, WhatsApp provenance, dual rates, or approval counters as native SO fields alone.

## 2. What MUST be custom (and why)

### Fresko Container — custom
ERPNext has no first-class “imported produce shipment lifecycle” that spans inward, commercial sales, outward, QC, settlement, and partner close. PR/SE cover stock inward only. Container holds operational identity, status, inward qty, closing status, landed-cost rollup hooks, and is the parent for lot/deal/settlement views.

### Fresko Deal — custom
Must carry: proposed vs approved rate, salesperson, WhatsApp `source_message_id`, duplicate fingerprint, unresolved buyer alias, Fresko state machine (`PROPOSED` → `APPROVAL_REQUIRED` / `AUTO_APPROVED` → …), and links to Approval/Evidence. A Sales Order is too late (commitment after approval), too rigid for alias-unresolved buyers, and is the wrong place for AI-proposed fields. Codex rule: commercial ledger ≠ physical ledger; a deal is not automatically outward.

### Fresko Approval — custom (Phase 1 companion)
Immutable decision row: rule trigger, requested rate, floor/ceiling, `APPROVE` / `REJECT` / `COUNTER`, decision_rate, approver, timestamp, reason. Required for acceptance scenario. Do not only overwrite `proposed_rate` or rely on Version Log.

### Fresko Evidence — custom (Phase 1 companion)
Polymorphic provenance: type, file/ref, message_id, sha256, parser_version, extraction_json, confidence, human_verified. Standard File attachments lack this chain. Link Evidence → Deal (and → Approval when the decision cites evidence).

**Not custom:** Company, Customer, Supplier, Item, Batch, Warehouse, Payment Entry, GL. Stock movement truth stays in ERPNext stock documents.

## 3. When Deal creates Sales Order vs Delivery Note

**Recommendation (target pattern):**

1. **PROPOSED / APPROVAL_REQUIRED** — no SO, no DN, no stock movement.
2. **APPROVED / AUTO_APPROVED** (and Customer resolved) — create and submit **Sales Order** with qty, `approved_rate`, Item, Batch/lot refs, Warehouse, Project/Container link, and `Fresko Deal` link. This is the ERP commercial commitment.
3. **DISPATCHED** (physical outward confirmed) — create **Delivery Note** against that SO (Serial and Batch Bundle). DN is physical ledger; never invent DN on approval.
4. **Sales Invoice** — later, per GST/invoice-timing decision.

**Phase 1 acceptance minimum:** Deal + immutable Approval are sufficient commercial SoR for the below-floor scenario. SO wiring may land immediately after the acceptance path works, but the product rule “no silent edit after approval” lives on Deal/Approval first.

**If Customer unresolved:** Deal may reach `APPROVED` commercially only if business allows; **block SO** until Customer confirmed (raise Exception / buyer-unresolved). Do not invent a fake Customer silently.

## 4. Stock reservation for approved-not-dispatched deals

**Recommendation: dual-layer, soft-first.**

| Layer | When | Effect |
|---|---|---|
| **Fresko soft reservation** | On `APPROVED` / `AUTO_APPROVED` | Increase container/lot `approved_sold` / `pending_outward`; decrease `available_to_sell`. Drives `QTY_EXCEEDS_AVAILABLE_STOCK`. Always on in Phase 1. |
| **ERPNext hard reservation** | When SO is submitted | Use ERPNext v15 SO stock reservation / reserved qty against Item+Batch+Warehouse so Desk/other docs cannot oversell the same batch. |
| **Physical stock** | Only on DN (or Stock Entry outward) | Approval never posts stock. |

Cancel / reject / approved revision that reduces qty must release both soft and hard reservation. Soft reservation alone is acceptable for the Phase 1 acceptance test if SO is deferred; do not pretend DN “holds” stock.

## 5. Approval + Evidence for acceptance scenario

`salesperson submits 50 crates below floor → owner approval → stored → no silent edit`:

1. Create Deal `PROPOSED` with Evidence (WhatsApp/source) linked.
2. Deterministic rules → `APPROVAL_REQUIRED` (rate below floor).
3. Owner decision writes **Fresko Approval** (immutable). Deal gets `approval_id`, `approved_rate` = decision_rate (or counter rate), status `APPROVED` / `COUNTERED` / `REJECTED`. Keep `proposed_rate` unchanged.
4. Post-approval: money/qty material fields on Deal are locked. Any change requires a revision path that stores old/new/actor/time/reason/`approval_reference` + Evidence — never silent Desk edit of approved values.
5. Optional: create SO after step 3 when Customer resolved.

## 6. Open decisions for Anubhav

1. Confirm SO-on-approval vs SO-on-dispatch (architecture recommends SO-on-approval when Customer resolved).
2. Soft-only reservation for Phase 1 vs soft + ERP hard reservation from day one.
3. Container P&L: Project-per-container vs Accounting Dimension.
4. Lot ↔ Batch: strict 1:1 vs Batch name separate from `commercial_lot_no`.
5. Count/size/grade: Item variants / attributes vs fields only on Deal.
6. May a Deal be `APPROVED` with unresolved buyer alias (SO blocked) or must Customer exist first?
7. Rate-floor grain: container / lot / count / buyer (Codex §35).
8. Container inward document: Purchase Receipt vs Stock Entry Material Receipt.
9. GST / Sales Invoice timing (Codex §35 — out of Phase 1 coding, but affects SO field design).

## Tradeoffs (short)

- **Custom Deal + late SO** preserves WhatsApp/approval workflow without distorting ERPNext; cost is two commercial objects to keep in sync after approval.
- **SO-on-approval** reuses ERP reservation and receivables tooling earlier; cost is unresolved-buyer and below-floor counter flows must not corrupt SO.
- **Soft reservation without SO** is enough for produce ops available-to-sell; without ERP hard reservation, parallel Desk stock docs can still oversell until SO exists.

