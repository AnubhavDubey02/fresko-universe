# Fresko Universe — Architecture Design Memo

**Audience:** Anubhav Dubey (product owner), Phase 1 implementers  
**Scope:** Phase 1 blueprint — **Fresko Container** and **Fresko Deal** only  
**Stack:** Frappe v15 + ERPNext v15 (Serial and Batch Bundle)  
**Date:** 15 September 2026  
**Status:** Blueprint (no Fresko repo / Drive / GitHub connected yet)  
**Source of truth for product intent:** `docs/FRESKO_UNIVERSE_CODEX_START_HERE.md`

---

## 0. Purpose and constraints

This memo answers one question for Phase 1:

> Which fields and behaviour belong in standard ERPNext objects vs custom Fresko DocTypes — for Container and Deal — without redesigning the product?

### Non-negotiables (inherited)

| Principle | Implication for this memo |
|-----------|---------------------------|
| ERPNext is System of Record | Accounting, stock ledger, parties, GL postings stay in ERPNext; Fresko links into them at the right lifecycle stage |
| Deterministic rules for accounting/stock | Deal approval and stock availability are code + workflow, not model confidence |
| AI proposes, never silently establishes financial truth | Out of Phase 1 scope here; architecture must leave hooks, not AI authority |
| Evidence / provenance | Container and Deal must be linkable to future Evidence/Approval without silent overwrite |
| No silent edits after approval | Approved Deal fields that affect qty/rate/party/lot require revision trail + re-approval rules |
| Free/OSS first; avoid microservices | Single Frappe custom app (`fresko_universe`); modular monolith |
| Prefer extending ERPNext | Custom DocTypes only where ERPNext would distort the produce-trade workflow |

### Explicitly out of this memo

WhatsApp ingestion, AI router, payments, QC, buyer-alias resolution, partner portal, Container Settlement, Exception engine (beyond noting future Link fields), Payment Entry posting rules, GST finalisation.

---

## 1. ERPNext reuse map

Prefer standard entities. Custom objects sit *beside* them and point *into* them when commercial or physical truth crystallises.

| Concept (produce trade) | ERPNext entity (v15) | Notes / Phase 1 stance |
|-------------------------|----------------------|------------------------|
| Legal trading entity | **Company** | One or more Companies as configured with CA; Fresko Container always belongs to a Company |
| Buying partner / Chinese supplier | **Supplier** | Link from Container; do not invent Partner DocType for Phase 1 identity |
| Buyer (resolved) | **Customer** | Deal links Customer when known; unresolved alias stays on Deal until Phase 7 |
| SKU / produce type (e.g. Plum) | **Item** | Stock item; enable **Has Batch No**; unit often Crate/Box via UOM |
| Commercial LOT No. (e.g. `41869`) | **Batch** (+ custom field) | See §5 — Batch is inventory identity; commercial LOT preserved explicitly |
| Batch pick on stock txn | **Serial and Batch Bundle** | v15 required path for batch qty on Stock Entry / DN / etc.; one Bundle per transaction, not reusable |
| Cold store / yard locations | **Warehouse** | Tree under Company; Container inward lands in a warehouse; do not encode “container as warehouse” unless Anubhav chooses that model |
| Approved commercial commitment | **Sales Order** (optional timing) | See §3 — recommended link target, not a substitute for Fresko Deal |
| Physical outward | **Delivery Note** | Later phase; Deal → DN when dispatch confirmed; consumes reservation if SO used |
| Billing / receivable recognition | **Sales Invoice** | Later; timing is CA decision (open) |
| Collections | **Payment Entry** | Later; never created from WhatsApp alone |
| Container inward / lot putaway / adjustments | **Stock Entry** | Material Receipt / Transfer / Issue as needed; Batch + Bundle on lines |
| Physical vs book stock correction | **Stock Reconciliation** | Exceptional close / count adjustments; not day-to-day deal flow |
| Container P&L slice / cost centre | **Accounting Dimension** (recommended) | e.g. dimension `fresko_container` or Cost Center per container; validate with CA before mandatory use |
| Party master attributes | Customer / Supplier custom fields | GSTIN, trade names, WhatsApp phone — extend masters; do not fork party DocTypes |
| Rate bands / floors | *Not* Price List alone | Price List can hold list rates; **policy floor/ceiling for approval** is Fresko rule data (future Approval / policy DocType), not ERPNext Price List semantics |
| Deal proposal / approval state machine | *No* Quotation-as-Deal | Quotation lacks produce-trade states (OUTWARD_PENDING, fingerprint, alias, evidence). Keep Fresko Deal |

### What Phase 1 should *not* force into ERPNext documents

- Treating Fresko Deal as Sales Order from the first draft (distorts PROPOSED / APPROVAL_REQUIRED).
- Using Batch `name` as the only human-facing LOT string without a preserved commercial reference.
- Creating GL impact on Deal approve (approve ≠ invoice ≠ payment).
- Modelling container as a second stock ledger outside Bin / SLE.

---

## 2. What MUST be custom — Container and Deal

### 2.1 Why custom at all

ERPNext models **parties, items, batches, warehouses, and posted stock/accounting vouchers** well. It does **not** model:

- a shipment/container as an operational settlement unit with inward/sold/outward/pending ledgers,
- a produce-trade deal lifecycle that is distinct from order → delivery → invoice,
- commercial proposal + human rate approval before any SO,
- unresolved buyer aliases, message fingerprints, evidence linkage,
- “approved sold ≠ physical outward” as a first-class invariant.

Forcing those into Quotation/SO alone recreates the failure modes in the master brief (timing mismatch, silent rate edits, duplicate count risk).

### 2.2 Fresko Container — must be custom

**DocType:** `Fresko Container` (suggested name; implement in `fresko_universe`).

| Field / behaviour | Why not standard ERPNext alone |
|-------------------|--------------------------------|
| `container_id` / naming | Business shipment identity; not Project, not Purchase Order |
| `supplier_partner` → Supplier | OK as Link; container itself is not a Supplier doc |
| `country_of_origin`, `arrival_date`, `product` → Item | Shipment metadata; Item does not carry arrival shipment |
| `inward_qty`, `unit`, `landed_cost`, `currency` | Operational header for settlement maths; landed cost may later allocate via Stock Entry / Landed Cost Voucher — header still needed |
| `status`, `closing_status` | Domain state machine (open → selling → closing → closed); not SO status |
| `source_documents` / links to future Evidence | Provenance hub; Attachment alone is insufficient for typed evidence |
| Aggregates: available_to_sell, approved_sold, pending_outward, etc. | **Computed** from Deal + stock txns; store cached snapshot fields only if refresh is deterministic |
| Link to Accounting Dimension value | Optional; if dimension = container, store the dimension value Link/name |

**ERPNext links Container should own early:**

- `company` → Company  
- `supplier` → Supplier  
- `default_item` / product → Item (or child table of items if multi-SKU later)  
- `default_warehouse` → Warehouse  
- Optional: `inward_stock_entry` → Stock Entry (when Phase 1+ records inward)

**Do not put on Container in Phase 1:** QC timelines, settlement certificate math as mutable free-text, partner portal fields.

**Future Links (stub only):** `evidence` child / dynamic links; settlement DocType later.

### 2.3 Fresko Deal — must be custom

**DocType:** `Fresko Deal`.

| Field / behaviour | Why custom |
|-------------------|------------|
| Deal state machine (`PROPOSED` → `AUTO_APPROVED` / `APPROVAL_REQUIRED` → `APPROVED` / `COUNTERED` / `REJECTED` → `OUTWARD_PENDING` → …) | Not Quotation/SO workflow; transitions validated in Python |
| `proposed_rate` vs `approved_rate` | Must not overwrite; Approval (future) records decision immutably |
| `approval_required`, `approval_id` → future Fresko Approval | Link placeholder in Phase 1 schema |
| `unresolved_buyer_alias` + optional `customer` → Customer | Alias retention; Customer optional until resolved |
| `lot` commercial ref + `batch` → Batch | Dual identity (§5) |
| `count_size` / grade | Produce attribute; rarely a separate Item without SKU explosion — store on Deal (and optionally Item Attribute later) |
| `qty`, `unit`, `currency`, `salesperson` | Commercial proposal line |
| `container` → Fresko Container | Mandatory parent context |
| `source_message_id`, `duplicate_fingerprint` | Idempotency hooks for Phase 2 WhatsApp; useful even for manual entry |
| `sales_order` → Sales Order (nullable) | Created per §3 policy — Deal remains SoR for commercial approval |
| Revision / no silent edit after APPROVED | Custom validate + Amendment/Revision pattern; Frappe Version helps but business rules must block silent qty/rate/lot/customer changes |

**ERPNext links Deal should use:**

- `customer` → Customer (when resolved)  
- `item` → Item  
- `batch` → Batch  
- `warehouse` → Warehouse (source for availability check)  
- `company` → Company (usually from Container)  
- `sales_order` → Sales Order (when created)  
- Later: `delivery_note`, payment links

**Future Links (do not design fully):**

- `approval` → Fresko Approval  
- `evidence` → Fresko Evidence (Dynamic Link / child)  
- Buyer Alias DocType (Phase 7)

### 2.4 What stays *out* of custom and on ERPNext

| Concern | Owner |
|---------|--------|
| Actual qty in Bin / SLE | ERPNext stock |
| Batch quantity integrity; no negative batch stock (v15) | ERPNext Serial/Batch + Bundle |
| Customer outstanding, GL | ERPNext accounts |
| Submitted DN / SI / PE immutability | ERPNext submit/cancel/amend |
| Permissions framework | Frappe roles (Fresko roles wrap these) |

### 2.5 Minimal Phase 1 behaviour (deterministic)

On Deal save/submit transitions:

1. Container exists and is open for selling.  
2. Lot/Batch belongs to Container (Fresko validation — Batch custom field or Container–Batch child).  
3. Qty ≤ **available_to_sell** under chosen reservation policy (§4).  
4. Rate vs floor → `AUTO_APPROVED` vs `APPROVAL_REQUIRED` (floor source is open decision).  
5. Fingerprint uniqueness when provided.  
6. After `APPROVED` / `AUTO_APPROVED`: block silent edits to qty, rates, item, batch, customer; require explicit revision path.

Stock **ledger** movement does **not** occur on Deal approve (physical truth is inward Stock Entry / outward DN later).

---

## 3. Recommendation: Sales Order on Deal approve vs wait until dispatch

Master brief open question (Section 35): *Whether every approved deal should immediately create a Sales Order or only after dispatch confirmation.*

### Option A — Create Sales Order on Deal approve (recommended default for Phase 1 blueprint)

**Flow:** `APPROVED` / `AUTO_APPROVED` → create/submit Sales Order (Draft→Submitted per policy) linked on Deal → optional Stock Reservation Entry against SO → later DN against SO → SI as CA directs.

| Pros | Cons |
|------|------|
| Uses ERPNext native reserved qty / Stock Reservation (v15) for batch-aware hold | SO exists before physical outward; cancelled deals need SO cancel/amend discipline |
| Clear commercial commitment document for accounts users | Risk of SO clutter if many deals never dispatch |
| Delivery Note mapping and partial dispatch are standard | Requires resolved **Customer** — blocked deals with only alias need a holding Customer or delay SO |
| Aligns “approved sold” with an ERP document without posting stock | Invoice timing still separate (good) |

### Option B — Wait until dispatch to create Sales Order (or skip SO and DN-only)

**Flow:** Approved Deal holds commercial truth in Fresko only → on dispatch create SO+DN or DN only → invoice later.

| Pros | Cons |
|------|------|
| Fewer ERP documents if deals die before outward | **Cannot** use standard SO stock reservation; must implement Fresko soft-reserve (§4 Option Soft) |
| Matches “order book timing ≠ dispatch timing” narrative | Harder for accounts to see pipeline in ERPNext reports |
| Avoids SO when Customer still unresolved | Higher custom code; easier to diverge from SoR |

### Option C — Hybrid (SO on approve only when Customer resolved + rate approved; else hold)

Practical compromise: same as A when `customer` is set; if only alias, stay `APPROVED` with Fresko soft-reserve until Customer confirmed, then create SO.

### Blueprint recommendation

**Prefer Option A (SO on approve), with Hybrid gate for unresolved Customer.**

- Deal remains the **commercial approval SoR**.  
- Sales Order is the **ERP commitment + reservation vehicle**, not a replacement for Deal.  
- Delivery Note remains the **physical outward** document (Phase 3).  
- Do **not** auto-create Sales Invoice on approve.

### Needs Anubhav decision

Mark **OPEN — Anubhav**: confirm A vs B vs Hybrid, and whether SO may be created against a temporary “Unresolved Buyer” Customer (discouraged) or must wait for confirmation.

---

## 4. Stock reservation semantics (approved but not dispatched)

### Ledgers to keep distinct (from brief)

| Ledger | Meaning |
|--------|---------|
| Physical inward | Stock Entry / PR into Warehouse + Batch |
| Approved sold | Sum of Deal qty in approved-like states not cancelled |
| Physical outward | Delivery Note / issue |
| Pending outward | Approved sold − dispatched (on those deals) |
| Available to sell | Inward − approved sold − adjustments (policy-defined) |

**Invariant:** Approving a Deal must **not** post a stock ledger decrease. It only constrains what can still be sold and, if configured, what ERPNext marks reserved.

### Option Soft — Fresko-only reservation (always required as source of commercial truth)

- On approve: increment Container/Batch **approved_sold** / reduce **available_to_sell** via Fresko queries (or maintained balance table).  
- Reject oversell in Deal validate.  
- No Bin.reserved_qty change unless Option ERP also applied.

Use Soft even if ERP reservation is enabled — Soft is what the produce UI and exceptions reason about.

### Option ERP — ERPNext Stock Reservation against Sales Order (v15)

If Option A/Hybrid creates an SO:

1. Enable Stock Reservation in Stock Settings (environment config).  
2. On SO submit (or explicit “Reserve Stock”), create **Stock Reservation Entry** for Item + Warehouse + Batch (reservation based on Serial and Batch where applicable).  
3. Reserved qty increases; **actual** qty unchanged.  
4. Delivery Note against SO consumes reservation (including partial DN — use current v15 patches; reservation + batch validation is actively maintained upstream).  
5. Deal cancel / reject after approve → cancel reservation + cancel/amend SO under permissioned workflow (no silent qty edit).

**v15 constraint:** Serial/Batch items **cannot** go negative even if Allow Negative Stock is on. Oversell must be blocked before submit.

### Recommended Phase 1 semantics

| State | Soft (Fresko) | ERP reservation |
|-------|---------------|-----------------|
| PROPOSED / APPROVAL_REQUIRED | No reserve (or soft hold optional — default **no**) | None |
| APPROVED / AUTO_APPROVED / OUTWARD_PENDING | Soft-reserve qty on Container+Batch | If SO exists: Stock Reservation Entry |
| DISPATCHED (full) | Soft released into outward; pending→0 | Reservation consumed via DN |
| CANCELLED | Soft release | Cancel SRE + SO |

**Needs Anubhav decision:** Soft-only vs Soft+ERP; whether PROPOSED deals may soft-hold briefly; oversell policy (hard block vs exception with owner override).

---

## 5. Lot → ERPNext Batch while preserving commercial LOT No.

### Problem

Commercial lots arrive as human strings (`41869`). ERPNext **Batch** `name` is the inventory key used in stock transactions and, in v15, referenced from **Serial and Batch Bundle** rows. Auto naming series (e.g. `BATCH-.####`) may not equal the commercial LOT. Collisions across containers/items are possible if LOT strings repeat.

### Recommended mapping (v15-aware)

```
Commercial LOT No.  →  custom field on Batch:  commercial_lot_no  (Data, indexed)
                       optional: fresko_container (Link → Fresko Container)

ERPNext Batch.name  →  stable unique inventory id
                       Prefer: set Batch name = commercial LOT when globally unique
                       Else:   BATCH-{container_id}-{lot} or hash-suffixed name
                               while commercial_lot_no = "41869"

Stock transactions  →  always select Batch; system creates a fresh
                       Serial and Batch Bundle per Stock Entry / DN line
                       (bundles are not reusable across transactions)
```

### Rules

1. **Item** for produce: `Has Batch No` = 1; decide `Automatically Create New Batch` carefully — for import lots, **manual Batch create at inward** is safer so commercial LOT is set correctly.  
2. Fresko Deal stores:  
   - `commercial_lot_no` (Data; what agents type / WhatsApp extracts)  
   - `batch` (Link → Batch; resolved deterministically from Container + commercial_lot_no)  
3. Never destroy or overwrite the commercial LOT string that appeared on evidence.  
4. Availability checks: by **Batch** (+ Warehouse), scoped to Container via Batch.`fresko_container` or Container–Lot child table.  
5. UI search: filter Batch by `commercial_lot_no` and Container, not by forcing users to memorise internal Batch.name when it differs.  
6. Traceability: use ERPNext Batch + Serial and Batch Traceability for stock path; Fresko drill-down for commercial Deal/Approval/Evidence path.

### Container–Lot registration

At inward (Phase 1 or early Phase 3):

1. Create/find Batch with `commercial_lot_no` + Container link.  
2. Stock Entry (Material Receipt) with Serial and Batch Bundle for that Batch and qty.  
3. Container `inward_qty` updated from submitted stock (or validated against it).

This keeps **physical inward** in ERPNext SLE and **commercial lot identity** explicit for agents and partners.

---

## 6. Suggested link graph (Phase 1)

```
Company
  └─ Warehouse(s)
  └─ Fresko Container ──→ Supplier, Item, Warehouse
         │                    └─ Batch (commercial_lot_no, fresko_container)
         │                         └─ Stock Entry (+ Serial and Batch Bundle) [inward]
         └─ Fresko Deal ──→ Customer?, Item, Batch, Warehouse
                │              proposed_rate / approved_rate / state machine
                ├─ (future) Fresko Approval
                ├─ (future) Fresko Evidence
                └─ Sales Order? ──→ Stock Reservation Entry?
                                      └─ (later) Delivery Note (+ new Bundle)
                                      └─ (later) Sales Invoice → Payment Entry
```

Accounting Dimension (optional): tag SO/DN/SI/Stock Entry with Container for P&L — configure with CA; not required to ship Deal state machine.

---

## 7. Open decisions for Anubhav

Do not silently decide these in code:

| # | Decision | Options / notes | Blocks |
|---|----------|-----------------|--------|
| D1 | **SO timing** | A on approve / B on dispatch / Hybrid (recommended Hybrid+A) | Reservation design, accounts UX |
| D2 | **Reservation mode** | Soft-only vs Soft+ERP Stock Reservation | Oversell enforcement mechanism |
| D3 | **Unresolved Customer** | Allow APPROVED without SO vs mandatory Customer before approve vs holding Customer | Option A feasibility |
| D4 | **Batch naming** | Batch.name = commercial LOT when unique vs always prefixed with container_id | Inward tooling, labels |
| D5 | **Warehouse model** | One cold-store WH + Batch/Container dimension vs WH-per-container | Stock Entry patterns |
| D6 | **Rate floor source** | Per Company / Container / Item / Lot / Count / Buyer | AUTO_APPROVED vs APPROVAL_REQUIRED |
| D7 | **Accounting Dimension** | Use Container as dimension now vs Cost Center vs defer to Phase 4+ | Reporting setup |
| D8 | **Legal entity / GST / invoice timing** | CA input — not hard-coded in Phase 1 | SI creation hooks later |
| D9 | **Oversell / owner override** | Hard block only vs permissioned override + Exception | Validate() strictness |
| D10 | **Multi-item containers** | Single Item per Container in Phase 1 vs child items | Container schema |

---

## 8. Implementation notes for Phase 1 coding (non-redesign)

1. Custom app module split inside monolith: `fresko_core` (Container), `fresko_deals` (Deal + state machine); Approval/Evidence DocTypes can be stub Link fields or empty DocTypes without WhatsApp/AI.  
2. All writes via Frappe ORM / whitelisted methods — no bypass of permissions.  
3. Use Frappe document Version + explicit revision fields for approved Deal corrections; require `reason` (+ future evidence_id).  
4. Unit tests: state transitions, oversell, fingerprint idempotency, batch/container mismatch, silent-edit blocked after approve.  
5. Re-check ERPNext v15.x patch level for Stock Reservation + batch DN behaviour before enabling Soft+ERP in production.  
6. Do not introduce Supabase or a second SoR.  
7. Preserve this memo; log Anubhav resolutions into `docs/DECISIONS.md` when the repo is initialised.

---

## 9. Summary

| Layer | Owner |
|-------|--------|
| Shipment unit, deal lifecycle, rates pending approval, alias, fingerprints | **Custom:** Fresko Container, Fresko Deal |
| Parties, Item, Batch inventory, Warehouse, SLE, SO/DN/SI/PE, Bundle | **ERPNext v15** |
| Commercial LOT string | **Batch.commercial_lot_no** (+ Deal field); Batch.name = inventory key |
| Approved-not-dispatched | Soft-reserve on Fresko; optionally ERP Stock Reservation via SO |
| SO creation moment | **Recommend on approve (Hybrid if Customer unresolved)** — **Anubhav to confirm** |

ERPNext remains the ledger. Fresko Container and Deal are the operational spine that ERPNext never modelled cleanly — linked in, not replaced.

