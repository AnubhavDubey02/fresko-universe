# Fresko Universe — Accounting & Controls Design Memo

> **Historical specialist proposal — 15 September 2026.** Retained as design
> evidence. Use `docs/PHASE1_BLUEPRINT_FINAL.md` and `docs/DECISIONS.md` for
> current Phase 1 decisions. See `docs/CANONICAL_DOCUMENTS.md`.

**Role:** Accounting / Controls specialist  
**Scope:** Phase 1 — Fresko Container + Fresko Deal design review  
**Focus:** Auditability · Stock integrity · No silent modification of approved financial records  
**Date:** 15 September 2026  
**Status:** Design proposal (not implementation)  
**Source of truth for product principles:** `docs/FRESKO_UNIVERSE_CODEX_START_HERE.md`

---

## 0. Purpose and non-negotiables

This memo defines how Phase 1 DocTypes (`Fresko Container`, `Fresko Deal`, and supporting Approval / Evidence / Exception objects) must behave so that:

1. Every material change to an approved commercial or stock-affecting field leaves a complete revision trail.
2. Commercial commitments (deals) and physical movements (inward/outward) stay in separate ledgers and are reconciled by exception, never conflated.
3. Desk / API / WhatsApp ingestion cannot overwrite `approved_rate` or `approved_qty` (or equivalents) without a revision record.
4. Tax law, invoice timing, SO creation timing, direct-receipt semantics, rate-floor ownership, and credit limits remain **Anubhav / CA decisions** — not hard-coded by engineering.

**Mandatory revision fields** (from product brief §3.3; apply to every material correction of an approved financial/commercial record):

| Field | Meaning |
|---|---|
| `old_value` | Value before the change |
| `new_value` | Value after the change |
| `changed_by` | User / system actor who applied the change |
| `changed_at` | Timestamp (UTC stored; display in company TZ) |
| `reason` | Free-text mandatory for material corrections |
| `supporting_evidence` | Link(s) to Fresko Evidence / file / message |
| `approval_reference` | Link to Fresko Approval (or equivalent) when policy requires re-approval |

**Rejection criterion (hard):** Any pattern that lets Frappe Desk (or API) overwrite `approved_rate` / approved quantity on a Deal in status `APPROVED`, `AUTO_APPROVED`, `OUTWARD_PENDING`, `DISPATCHED`, `PARTIALLY_DISPATCHED`, `PAYMENT_PENDING`, `PARTIALLY_PAID`, `PAID`, or `RECONCILED` **without** writing a revision trail containing the fields above is a **controls defect** and must not ship.

---

## 1. Audit / revision strategy — Container and Deal

### 1.1 Principle

Use Frappe’s built-in Version / `track_changes` where it is **enough** (operational metadata, non-financial fields, pre-approval drafts).  
Introduce a **custom Fresko Deal Revision** child table / DocType where Frappe Version is **not enough** — specifically for post-approval financial/commercial fields that must carry reason, evidence, and optional re-approval.

Frappe Version alone typically records *what* changed and *who/when*, but does **not** reliably enforce:

- mandatory `reason`
- `supporting_evidence` linkage
- `approval_reference` when policy requires it
- blocking of silent Desk edits on locked fields

Therefore Version is complementary audit, not the sole control for approved financial truth.

### 1.2 Fresko Container

| Concern | Mechanism | Notes |
|---|---|---|
| Identity / header (`container_id`, supplier, product, arrival_date, unit, currency) | Frappe `track_changes` / Version | Edits after first inward posting should require role + reason via custom validation if they affect settlement identity |
| `inward_qty` / physical inward totals | **Controlled update path only** — not free Desk edit after INWARD_POSTED / OPEN | Change must create revision-style note or Exception + Evidence; prefer append of inward events over mutating a single scalar |
| `landed_cost` and cost components | Version + reason required once status ≥ OPEN / costs posted | Do not invent tax treatment here |
| `status` / `closing_status` | State machine in server code; Version on transition | Arbitrary Desk status jumps rejected |
| Source documents / evidence links | Append-only Evidence links | Never delete original evidence; soft-void only with reason |
| Settlement snapshot fields | Written by settlement workflow at close; treat as immutable snapshot | Re-open requires explicit Exception + new settlement version |

**Container recommendation (Phase 1):**

- Enable `track_changes` on Fresko Container.
- Do **not** rely on Version alone for `inward_qty` or closing settlement figures.
- Prefer an event/append model for physical inward adjustments (e.g. inward correction event linked to Evidence) rather than silent overwrite of `inward_qty`.
- Custom “Container Revision” DocType is **optional in Phase 1** if inward corrections are modeled as append-only events + Exceptions; revisit if Desk users routinely need scalar corrections.

### 1.3 Fresko Deal

| Lifecycle stage | Mechanism |
|---|---|
| `PROPOSED`, `APPROVAL_REQUIRED`, `COUNTERED` (pre-approval commercial draft) | Frappe Version / `track_changes` is **enough** for field history. Proposed fields may still be edited by authorized roles. |
| Transition into `AUTO_APPROVED` / `APPROVED` | Immutable Fresko Approval record written. Deal copies decision into `approved_rate` / approved qty via **workflow method only**, not Desk form save. |
| Post-approval statuses (see §2) | **Fresko Deal Revision** required for any change to locked financial/commercial fields. Frappe Version remains as secondary technical audit. |
| Terminal: `CANCELLED`, `RECONCILED` | Cancellation / reopen only via controlled methods that write Revision + Exception as needed. |

### 1.4 Fresko Deal Revision (custom) — when Version is not enough

**Proposed shape (design):**

- Option A (preferred for Phase 1): Child table on Fresko Deal: `Fresko Deal Revision Item`
- Option B: Standalone DocType `Fresko Deal Revision` linked to Deal (better if approvals/reports need independent list views)

**Minimum fields:**

| Field | Type (conceptual) | Required |
|---|---|---|
| `deal` | Link → Fresko Deal | Yes |
| `fieldname` | Data (e.g. `approved_rate`, `qty`) | Yes |
| `old_value` | Data / JSON / Float as appropriate | Yes |
| `new_value` | Data / JSON / Float | Yes |
| `changed_by` | Link → User | Yes (system-set) |
| `changed_at` | Datetime | Yes (system-set) |
| `reason` | Small Text | Yes for material fields |
| `supporting_evidence` | Link / Table → Fresko Evidence | Yes for qty/rate/buyer/lot changes after approval |
| `approval_reference` | Link → Fresko Approval | When rate/qty policy requires re-approval |
| `prior_status` / `status_after` | Select | Recommended |
| `revision_type` | Select: CORRECTION / COUNTER_ACCEPTANCE / CANCEL_PARTIAL / SPLIT / OTHER | Recommended |

**Server rules:**

1. Locked fields (matrix §2) are **read-only on the Deal form** after lock status.
2. The only write path is a whitelisted method, e.g. `fresko.deals.apply_revision(...)`, which:
   - validates state + role
   - requires `reason` + evidence when configured
   - creates Approval if rate/qty crosses policy again
   - appends Deal Revision row
   - applies `new_value` to Deal
   - emits Exception type `RATE_CHANGED_AFTER_APPROVAL` / `MANUAL_OVERRIDE` / qty equivalent when material
3. Direct `doc.save()` from Desk that mutates locked fields must be rejected in `validate` / `before_save`.
4. API / WhatsApp ingestion must call the same revision path — no bypass.

### 1.5 What Frappe Version still does

- Catches accidental metadata edits (notes, salesperson, tags).
- Provides forensic “who touched the document” even when Revision is used.
- Does **not** satisfy the mandatory `reason` / `supporting_evidence` / `approval_reference` contract for approved financial fields.

### 1.6 Approval immutability

Fresko Approval records are **append-only / immutable after submit**. A counter or re-decision creates a **new** Approval linked to the Deal; it does not overwrite the prior Approval row. The Deal’s current `approved_rate` is always attributable to a specific Approval ID.

---

## 2. Field immutability matrix by Deal status

Legend:

- **E** = Editable by authorized role (normal form/API)
- **L** = Locked — change only via Fresko Deal Revision (+ Approval when required)
- **W** = Workflow-only (state machine / method; not free form edit)
- **—** = Not applicable / should be empty

Statuses follow brief §8. Intermediate statuses included for Phase 1 clarity.

| Field | PROPOSED | APPROVAL_REQUIRED | COUNTERED | REJECTED | AUTO_APPROVED | APPROVED | OUTWARD_PENDING | PARTIALLY_DISPATCHED | DISPATCHED | PAYMENT_PENDING | PARTIALLY_PAID | PAID | RECONCILED | CANCELLED |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `deal_id` / name | W | L | L | L | L | L | L | L | L | L | L | L | L | L |
| `container` | E | L* | L* | L | L | L | L | L | L | L | L | L | L | L |
| `customer` / resolved buyer | E | E† | E† | L | L | L | L | L | L | L | L | L | L | L |
| `unresolved_buyer_alias` | E | E | E | L | L‡ | L‡ | L‡ | L‡ | L‡ | L‡ | L‡ | L‡ | L‡ | L |
| `product` | E | L* | L* | L | L | L | L | L | L | L | L | L | L | L |
| `lot` / batch | E | E† | E† | L | L | L | L | L | L | L | L | L | L | L |
| `count_size` | E | E† | E† | L | L | L | L | L | L | L | L | L | L | L |
| `qty` (commercial / approved qty) | E | E† | E† | L | L | L | L | L | L | L | L | L | L | L |
| `proposed_rate` | E | E† | E§ | L | L¶ | L¶ | L¶ | L¶ | L¶ | L¶ | L¶ | L¶ | L¶ | L |
| `approved_rate` | — | — | —# | — | L | L | L | L | L | L | L | L | L | L |
| `currency` | E | L* | L* | L | L | L | L | L | L | L | L | L | L | L |
| `salesperson` | E | E | E | L | E/L** | E/L** | L | L | L | L | L | L | L | L |
| `status` | W | W | W | W | W | W | W | W | W | W | W | W | W | W |
| `source_message_id` | W/set-once | L | L | L | L | L | L | L | L | L | L | L | L | L |
| `duplicate_fingerprint` | W/set-once | L | L | L | L | L | L | L | L | L | L | L | L | L |
| `approval_id` / link | — | W | W | W | L | L | L | L | L | L | L | L | L | L |
| Dispatch links / outward qty allocated | — | — | — | — | E†† | E†† | E†† | L/Rev | L/Rev | L | L | L | L | L |
| Payment links | — | — | — | — | — | — | — | — | E†† | E†† | E†† | L | L | L |

**Footnotes**

- **L\*** — Changing container/product/currency after approval-required usually invalidates the approval context; prefer cancel + new deal, or Revision with forced re-approval. Phase 1 default: **lock** once `APPROVAL_REQUIRED` unless product owner opens.
- **†** — Editable only if still pre-decision; edits that change rate/qty/lot vs floor rules must re-run deterministic rules (may flip AUTO vs APPROVAL_REQUIRED).
- **‡** — Alias string is historical evidence; do not erase. Resolution to Customer after approval is allowed as identity enrichment **without** changing commercial qty/rate; log via Version + optional Revision if policy treats buyer change as material.
- **§** — On COUNTERED, agent/owner may adjust proposal toward counter; final acceptance writes new Approval.
- **¶** — `proposed_rate` retained as historical proposal; not used as live selling rate after approval.
- **#** — Counter decision rate lives on Approval; Deal `approved_rate` set only when counter is accepted / approved.
- **\*\*** — Salesperson correction post-approval: Version OK if non-financial; if commission/settlement depends on it → Revision + reason.
- **††** — Linking outward/payment is append of links / child rows via controlled methods, not free overwrite of approved commercial qty/rate.

### 2.1 Fields that always require `approval_reference` on Revision (proposed policy)

Subject to Anubhav confirmation of rate-floor ownership (§6):

- Decrease or increase of `approved_rate`
- Increase of approved commercial `qty` (stock impact)
- Decrease of approved `qty` after any outward linked (may need split/cancel semantics)
- Change of `lot` after approval (lot overdraw risk)
- Buyer change when credit/exposure rules apply (**CA / Anubhav**)

### 2.2 Container field locks (summary)

| Container field | Before inward posted | After inward / OPEN | After SETTLEMENT_CLOSED |
|---|---|---|---|
| Identity (id, supplier, product) | E | L / Revision-or-Exception | L |
| `inward_qty` | E | Controlled correction only | L |
| Landed cost inputs | E | Reason + Version; material → Exception | L (snapshot) |
| Status / closing | W | W | W (reopen = explicit) |

---

## 3. Stock integrity rules (formulas marked provisional)

Commercial approval ≠ physical outward. Continuous container (and lot) metrics must be computed from **distinct event streams**.

### 3.1 Definitions (Phase 1)

| Metric | Meaning | Primary source ledger |
|---|---|---|
| `physical_inward` | Quantity received into controlled warehouse/cold storage for the container (sum of inward events) | Physical |
| `approved_sold` | Sum of commercial qty on Deals in approved-or-later statuses, excluding cancelled commercial qty | Commercial |
| `physical_outward` | Sum of verified gatepass / outward / DN movements linked to container/lots | Physical |
| `pending_outward` | Approved commercial qty not yet matched to physical outward | Bridge (commercial − matched outward) |
| `cancelled` | Commercial qty cancelled after approval (or voided proposals that never approved — usually excluded from approved_sold) | Commercial |
| `available_to_sell` | Quantity that may still be newly approved | Derived |
| `unsold` | Quantity inward not covered by approved commercial positions (policy-dependent) | Derived |

### 3.2 Provisional formulas

> **PROVISIONAL — do not hard-code as financial truth without Anubhav sign-off.**  
> These are engineering proposals to prevent double-counting. Exact reservation semantics (whether APPROVED reserves stock) are an open question in brief §35.

#### A. Physical inward

```text
physical_inward = Σ inward_event.qty   # for container (and per lot)
```

Corrections: prefer negative adjustment events with Evidence, not silent edit of the original inward row.

#### B. Approved sold

```text
approved_sold = Σ deal.approved_qty
  WHERE deal.status IN (
    AUTO_APPROVED, APPROVED, OUTWARD_PENDING,
    PARTIALLY_DISPATCHED, DISPATCHED,
    PAYMENT_PENDING, PARTIALLY_PAID, PAID, RECONCILED
  )
  # CANCELLED deals contribute 0 to approved_sold;
  # partial cancel reduces approved_qty via Revision, or uses cancelled bucket below
```

**PROVISIONAL alternative:** track `approved_qty` immutable and maintain `cancelled_qty` on deal; then  
`net_approved_sold = approved_qty - cancelled_qty`. Prefer one model; do not mix.

#### C. Physical outward

```text
physical_outward = Σ outward_event.qty
  WHERE outward verified / posted for container (and lot)
```

Outward without Deal ID → Exception `OUTWARD_WITHOUT_DEAL` (still counts in physical_outward).

#### D. Pending outward

```text
# PROVISIONAL
pending_outward = Σ (deal.net_approved_qty - deal.matched_outward_qty)
  WHERE deal in approved-or-later non-cancelled
  AND (deal.net_approved_qty - deal.matched_outward_qty) > 0
```

#### E. Cancelled (commercial)

```text
# PROVISIONAL
cancelled = Σ deal.cancelled_qty   # post-approval cancellations only
```

#### F. Available to sell

```text
# PROVISIONAL — assumes approved deals reserve stock
available_to_sell = physical_inward
                    - approved_sold_net_of_cancel
                    - other_reservations  # if any
```

If business decides approved deals do **not** reserve until dispatch, replace with:

```text
# PROVISIONAL ALTERNATE — reserve only on OUTWARD_PENDING / dispatch allocate
available_to_sell = physical_inward - physical_outward - allocated_pending_do
```

**MUST remain Anubhav decision** which alternate is live (§6 / brief §35).

#### G. Unsold

```text
# PROVISIONAL — closing-oriented
unsold = physical_inward - physical_outward - physical_remaining_adjustment
# OR commercially:
unsold_commercial = physical_inward - approved_sold_net_of_cancel
```

These two “unsold” notions **must not be silently equated**. UI should label:

- `unsold_physical` (still in warehouse)
- `unsold_commercial` (never approved for sale)

### 3.3 Invariants to exception-check (not silent plugs)

| Check | Exception type (from brief §21) |
|---|---|
| `physical_outward` row with no approved Deal | `OUTWARD_WITHOUT_DEAL` |
| New approval would make `approved_sold > available` under chosen reservation rule | `QTY_EXCEEDS_AVAILABLE_STOCK` |
| Lot outward > lot inward | `LOT_OVERDRAWN` |
| Duplicate gatepass / outward fingerprint | `DUPLICATE_GATEPASS` |
| At close: inward ≠ outward + remaining (+ named adjustments) | `CONTAINER_QTY_NOT_RECONCILED` |
| Edit after dispatch without Revision | `MANUAL_OVERRIDE` / `RATE_CHANGED_AFTER_APPROVAL` |

### 3.4 Explicit non-equality

```text
approved_sold  ≠  physical_outward     # by design
proposed qty   ≠  approved qty         # until Approval
WhatsApp claim ≠  stock movement       # evidence only
```

---

## 4. Idempotency — `duplicate_fingerprint` + `source_message_id` (design only)

### 4.1 Goal

Never create a second financial/commercial Deal (or double stock reservation) when the same WhatsApp (or other) event is retried, redelivered, or forwarded internally.

### 4.2 `source_message_id`

- Persist the provider message ID (e.g. Meta WhatsApp `wamid` / message id) on ingestion Evidence and on Deal when a Deal is created from that message.
- Unique constraint (or idempotent upsert) on ingestion event table: `(provider, source_message_id)`.
- Re-delivery of the same `source_message_id` → return existing Evidence / Deal reference; **do not** create a new Deal.
- `source_message_id` is **set-once** and locked after create (§2).

### 4.3 `duplicate_fingerprint`

Purpose: catch near-duplicates that are **not** the same message id (e.g. user resends same order text, or parallel channels).

**Proposed fingerprint inputs (PROVISIONAL composition — tune with Anubhav):**

```text
fingerprint = hash(
  normalized_buyer_alias,
  container_id or lot,
  qty,
  proposed_rate,
  unit,
  calendar_day(source_timestamp),   # or message date
  salesperson / sender_id           # optional
)
```

Store on Deal as `duplicate_fingerprint`.

**Enforcement options (choose in implementation; design stance):**

1. **Hard block** if an open/approved Deal with same fingerprint exists within window T → Exception `DUPLICATE_MESSAGE`, no new Deal.
2. **Soft flag** → create Deal in review state with Exception, human confirms distinctness.

Phase 1 recommendation: **hard block on exact `source_message_id`; soft/hard policy flag on fingerprint** configurable, default soft+Exception for fingerprint-only collisions so legitimate same-day repeat orders are not impossible.

### 4.4 Interaction rules

| Scenario | Expected behavior |
|---|---|
| Webhook retry, same `source_message_id` | Idempotent no-op; same Deal |
| New message id, same fingerprint | Exception / policy; do not silently merge financials |
| Revision of existing Deal | Does **not** mint new fingerprint identity; fingerprint stays historical; revisions trail handles change |
| Cancelled Deal, user sends again | New message id → new Deal allowed; fingerprint may match cancelled — policy may allow |

### 4.5 Out of Phase 1 detail

Gatepass/outward idempotency should mirror this pattern (outward fingerprint + source doc id) in Phase 3; mention only so Deal design does not assume outward uniqueness lives on Deal alone.

---

## 5. Separation of commercial vs physical ledgers

### 5.1 Two ledgers (Phase 1 minimum)

| Ledger | Owns | Typical DocTypes / events |
|---|---|---|
| **Commercial ledger** | What was agreed to sell, at what approved rate/qty, cancellations, approved revisions | Fresko Deal, Fresko Approval, Fresko Deal Revision |
| **Physical ledger** | What entered / left warehouse or cold storage | Container inward events, outward/gatepass/DO records (Phase 3), ERPNext Stock Entry / Delivery Note when mapped |

Collection, Expense, and QC ledgers exist in the broader architecture (brief §27) but are out of Phase 1 depth except where Deal/Container design must not block them.

### 5.2 Rules

1. **Deal approval never posts stock outward.** It may reserve (if policy says so) in a commercial reservation layer, but ERPNext stock issue / Delivery Note happens on physical confirmation.
2. **Physical outward never invents `approved_rate`.** Rate comes from linked Deal / Approval; missing link → Exception, not AI guess.
3. **Container snapshot** always shows both ledgers side by side:

   - Commercial: `approved_sold`, `cancelled`, `pending_outward` (bridge)
   - Physical: `physical_inward`, `physical_outward`, remaining

4. **Reconciliation** = comparison producing named Exceptions; never a single plugged “adjustment” without category.
5. **ERPNext mapping timing** (SO / DN / SI) is deliberately **not** decided here (§6). Custom Fresko records remain operational truth until an authorized posting step creates ERPNext docs.

### 5.3 Deal ↔ Container relationship

- Deal always links to Container (and lot when known).
- Container aggregates are **computed or periodically snapshotted** from child events/deals — not manually typed totals that can diverge.
- Closing settlement (§7 of brief / Container Settlement) reads both ledgers; unresolved material Exceptions block “fully reconciled” presentation.

---

## 6. Controls risks and items that MUST remain Anubhav / CA decisions

Engineering must implement **hooks and fields**, not legal conclusions. Do not invent tax law.

| Topic | Why it stays with Anubhav / CA | Phase 1 engineering stance |
|---|---|---|
| **GST / tax configuration** | Entity-specific; invoice place-of-supply; produce exemptions/rates — legal | No hard-coded GST rates or tax templates presented as advice; leave ERPNext tax setup to CA |
| **Invoice timing** | When taxable supply is recognized vs deal/dispatch | Do not auto-create Sales Invoice on Deal approve |
| **Sales Order creation timing** | Whether every approved Deal → immediate SO, or only after dispatch | Configurable flag defaulting to **off / manual** until decided (brief §35) |
| **Direct receipt** | Who is credited; exclusion from agent settlement; audit meaning | Provide explicit auditable boolean/amount fields + Evidence; **do not** invent settlement math as final |
| **Rate-floor ownership** | Container vs lot vs count vs buyer-specific floors; who may edit floors | Implement floor as data + rule engine input; ownership/workflow of floor master = Anubhav |
| **Credit / exposure limits** | Per-buyer limits, blocks, overrides | Fields + rule hooks; limit values and override policy = Anubhav |
| **Stock reservation semantics** | Whether APPROVED reserves `available_to_sell` | Two provisional formulas in §3; pick one before production stock rules |
| **Legal entities / partner accounting model** | Who books revenue/COGS/partner balance | Dimensions/links only; no assumed JV automation |
| **Closing treatment of residual crates** | e.g. commercial closing lines without lot/vehicle map (see Drive ledger warning) | Must be labeled PROVISIONAL / USER_CONFIRMED in data provenance — never silent “sold” |

### 6.1 Controls risks (Phase 1 watchlist)

1. **Desk power-user bypass** — System Manager edits Deal via standardize/migrate; mitigate with `validate` locks + Revision API + periodic audit report of Version rows lacking Revision for locked fields.
2. **Import scripts / bulk update** — Same locks must run in `before_save`, not only client scripts.
3. **Conflating proposed and approved rate in UI** — Show both; only `approved_rate` feeds commercial ledger.
4. **Double counting** — Counting CANCELLED in `approved_sold`, or counting outward as sold without Deal.
5. **Idempotency gaps** — Creating Deal before persisting ingestion unique key.
6. **Silent AI writes** — AI/parser must never write `approved_rate` or status ≥ APPROVED.
7. **Settlement plugs** — Any container close that forces inward = sold without Exception register fails controls review.

---

## 7. Rejection criteria — patterns that must not ship

A PR / DocType design is **rejected** if any of the following are true:

1. **Silent overwrite:** Frappe Desk (or REST resource PUT/POST) can change `approved_rate` or approved commercial `qty` on a Deal in  
   `APPROVED | AUTO_APPROVED | OUTWARD_PENDING | PARTIALLY_DISPATCHED | DISPATCHED | PAYMENT_PENDING | PARTIALLY_PAID | PAID | RECONCILED`  
   without inserting a Fresko Deal Revision row that includes  
   `old_value`, `new_value`, `changed_by`, `changed_at`, `reason`, `supporting_evidence`, and `approval_reference` when policy requires it.

2. **Client-only lock:** Field read-only is enforced only in Desk JS / Form UI, not in server `validate` / whitelisted method.

3. **Approval mutation:** Existing Fresko Approval document is edited in place to change `decision_rate` instead of appending a new Approval.

4. **Version-only excuse:** Relying solely on Frappe Version history as satisfying the mandatory revision field contract for post-approval rate/qty.

5. **Ledger conflation:** A single field or posting path that sets physical outward from Deal approval (or sets `approved_rate` from gatepass) without explicit mapping workflow.

6. **Idempotent hole:** Ingestion can create two Deals for one `source_message_id`.

7. **Tax/SO invention:** Code path auto-submits Sales Invoice or asserts GST treatment without CA-configured ERPNext tax templates and an explicit Anubhav decision on timing.

8. **Unavailable stock without Exception:** Approvals that push `approved_sold` over available under the chosen reservation rule without raising `QTY_EXCEEDS_AVAILABLE_STOCK`.

---

## 8. Phase 1 acceptance checks (controls view)

Aligned to brief §30 Phase 1 acceptance scenario:

1. Salesperson submits 50 crates below floor → Deal enters `APPROVAL_REQUIRED` (or equivalent); `proposed_rate` stored; `approved_rate` empty.
2. Owner counters/approves → **new** Fresko Approval immutable row; Deal `approved_rate` set only by workflow; status → `APPROVED` / accepted counter path.
3. Attempt to edit `approved_rate` or `qty` from Desk → **blocked**; only `apply_revision` with full revision fields succeeds; Exception raised when material.
4. Frappe Version shows technical history; Deal Revision shows business reason/evidence/approval reference.
5. Container snapshot can display provisional `physical_inward` / `approved_sold` / bridges without claiming they are equal.
6. Duplicate webhook with same `source_message_id` does not create a second Deal.

---

## 9. Document control

| Item | Value |
|---|---|
| Memo | `briefs/controls.md` |
| Author role | Accounting / Controls specialist (agent) |
| Depends on | `docs/FRESKO_UNIVERSE_CODEX_START_HERE.md` §§3, 7–10, 21–22, 27, 30, 35 |
| Next owners | Engineering (DocType + validate locks); Anubhav/CA (table in §6) |
| Explicitly not decided here | GST law, invoice/SO timing, direct-receipt settlement math, rate-floor master ownership, credit limit values, final stock reservation choice |

**Changelog**

- 2026-09-15 — Initial Phase 1 Container + Deal controls design memo.
