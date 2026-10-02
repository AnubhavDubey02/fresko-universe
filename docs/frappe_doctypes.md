# Fresko Universe — Frappe DocType Design Memo

> **Historical specialist proposal — 15 September 2026.** Retained as design
> evidence. Use `docs/PHASE1_BLUEPRINT_FINAL.md` and `docs/DECISIONS.md` for
> current Phase 1 decisions. See `docs/CANONICAL_DOCUMENTS.md`.

**App:** `fresko_universe`  
**Target:** Frappe / ERPNext **v15**  
**Scope:** `Fresko Container` + `Fresko Deal` only  
**Date:** 15 September 2026  
**Status:** Design brief (no implementation codebase yet)  
**Source of truth:** `docs/FRESKO_UNIVERSE_CODEX_START_HERE.md` §§6–10, §30 Phase 1

---

## 0. Design intent

- ERPNext remains the system of record for Company, Customer, Supplier, Item, Batch, Warehouse, Currency, UOM, and (later) Sales Order / Delivery Note / Payment Entry.
- Custom DocTypes model produce-trade concepts ERPNext does not express cleanly: **container lifecycle**, **deal proposal + approval gate**, **buyer alias pending resolution**, **duplicate fingerprint**, and **explicit approval linkage**.
- Do **not** invent a parallel stock/accounting engine. Stock availability and rate-floor checks are stubs that will call into Fresko inventory/policy modules later; accounting documents are created at later lifecycle stages (out of scope here).
- **No silent edits:** once a deal reaches `APPROVED` / `AUTO_APPROVED` (or later commercial states), material fields are server-locked; rate/qty/buyer changes require a revision path + `Fresko Approval` link (DocType itself is Phase 1 sibling — only **link fields** are specified here).

**Out of scope for this memo:** WhatsApp ingestion, AI router, payments, QC, buyer-resolution engine, partner portal, Sales Order auto-creation policy.

---

## 1. Exact field tables

### 1.1 DocType: `Fresko Container`

| fieldname | label | fieldtype | options | reqd | unique | notes |
|-----------|-------|-----------|---------|------|--------|-------|
| `naming_series` | Series | Select | `FC-.YYYY.-.#####` | 1 | 0 | Standard Frappe naming; hidden on form if desired via `set_only_once` |
| `container_id` | Container ID | Data | — | 1 | 1 | Commercial/physical container identifier (e.g. shipping line / BL reference). Distinct from Frappe `name`. `in_list_view`, `in_standard_filter` |
| `supplier_partner` | Supplier / Partner | Link | `Supplier` | 1 | 0 | ERPNext Supplier; Chinese partner entity. `in_list_view`, `in_standard_filter` |
| `country_of_origin` | Country of Origin | Link | `Country` | 0 | 0 | Prefer Link over free text for reporting |
| `product` | Product | Link | `Item` | 1 | 0 | Primary produce Item for this container. V1: one primary product per container (multi-item deferred). `in_list_view` |
| `column_break_header` | — | Column Break | — | 0 | 0 | Layout |
| `arrival_date` | Arrival Date | Date | — | 1 | 0 | `in_list_view`, `in_standard_filter` |
| `inward_qty` | Inward Qty | Float | — | 1 | 0 | Physical inward; precision 3. Non-negative validated in `validate` |
| `unit` | Unit | Link | `UOM` | 1 | 0 | Typically Crate / Box / Kg — company UOM master |
| `landed_cost` | Landed Cost | Currency | `currency` | 0 | 0 | Total landed cost for container; management view, not GL posting by itself |
| `currency` | Currency | Link | `Currency` | 1 | 0 | Default company currency; options field on Currency fields |
| `section_status` | Status | Section Break | — | 0 | 0 | — |
| `status` | Status | Select | see §1.1.1 | 1 | 0 | Operational container status. `in_list_view`, `in_standard_filter`. Default `DRAFT` |
| `closing_status` | Closing Status | Select | see §1.1.2 | 1 | 0 | Settlement readiness. Default `OPEN`. `in_list_view` |
| `section_evidence` | Source Documents | Section Break | — | 0 | 0 | Collapsible |
| `source_documents` | Source Documents | Attach | — | 0 | 0 | Single primary attachment (BL / packing list). Prefer Attach for V1; multi-file via child table later if needed |
| `source_document_notes` | Document Notes | Small Text | — | 0 | 0 | Free-text pointers to Drive/WhatsApp evidence IDs (not a second SoR) |
| `section_audit` | Audit | Section Break | — | 0 | 0 | Collapsible; `permlevel` 1 for sensitive notes if needed |
| `closed_by` | Closed By | Link | `User` | 0 | 0 | Set only by close workflow; `read_only` |
| `closed_at` | Closed At | Datetime | — | 0 | 0 | `read_only` |
| `amended_from` | Amended From | Link | `Fresko Container` | 0 | 0 | Standard amend support if `is_submittable` enabled later; leave unused in V1 draft |

#### 1.1.1 `status` options (Container)

```
DRAFT
IN_TRANSIT
ARRIVED
IN_COLD_STORAGE
SELLING
CLOSING
CLOSED
CANCELLED
```

#### 1.1.2 `closing_status` options

```
OPEN
EXCEPTIONS_OPEN
READY_TO_CLOSE
CLOSED
REOPENED
```

**DocType meta (Container):**  
`module` = Fresko Universe · `autoname` = `naming_series:` · `is_submittable` = 0 (V1) · `track_changes` = 1 · `allow_rename` = 0 · `title_field` = `container_id` · `search_fields` = `container_id,supplier_partner,product,status`

---

### 1.2 DocType: `Fresko Deal`

| fieldname | label | fieldtype | options | reqd | unique | notes |
|-----------|-------|-----------|---------|------|--------|-------|
| `naming_series` | Series | Select | `FD-.YYYY.-.#####` | 1 | 0 | — |
| `deal_id` | Deal ID | Data | — | 0 | 1 | Optional commercial display ID; if left blank, mirror `name` in `before_insert`. Prefer unique index. `in_list_view` |
| `container` | Container | Link | `Fresko Container` | 1 | 0 | Parent commercial context. `in_list_view`, `in_standard_filter`, `in_preview` |
| `column_break_party` | — | Column Break | — | 0 | 0 | — |
| `customer` | Customer | Link | `Customer` | 0 | 0 | Set when buyer resolved. XOR with unresolved alias enforced in `validate` (at least one of customer / unresolved_buyer_alias required) |
| `unresolved_buyer_alias` | Unresolved Buyer Alias | Data | — | 0 | 0 | Preserve original ledger alias (e.g. `AZ/SSK`). Never destroy after resolution — keep historical alias. `in_list_view`, `in_standard_filter` |
| `section_product` | Product / Lot | Section Break | — | 0 | 0 | — |
| `product` | Product | Link | `Item` | 1 | 0 | Usually matches container product; allow override only with warning. `in_list_view` |
| `lot_batch` | Lot / Batch | Link | `Batch` | 0 | 0 | ERPNext Batch when mapped. Prefer Link for stock rules |
| `commercial_lot_no` | Commercial LOT No. | Data | — | 0 | 0 | Preserve original LOT string even if Batch `name` differs (codex §10) |
| `count_size` | Count / Size | Data | — | 0 | 0 | e.g. count 60 / size grade — free Data for V1; Select later if master stabilizes |
| `qty` | Qty | Float | — | 1 | 0 | Precision 3; must be > 0. `in_list_view` |
| `unit` | Unit | Link | `UOM` | 1 | 0 | Default from container.unit |
| `column_break_rate` | — | Column Break | — | 0 | 0 | — |
| `proposed_rate` | Proposed Rate | Currency | `currency` | 1 | 0 | Agent/WhatsApp proposed rate. Locked after leave `PROPOSED` except via revision |
| `approved_rate` | Approved Rate | Currency | `currency` | 0 | 0 | Set only by approval / auto-approve path. `read_only` on form; writable only via server methods. `in_list_view` |
| `currency` | Currency | Link | `Currency` | 1 | 0 | Default from container |
| `salesperson` | Salesperson | Link | `User` | 1 | 0 | Operational agent. Alternative: Link `Sales Person` if ERPNext HR/Selling masters preferred — **decision:** use `User` for V1 RBAC simplicity; map to Sales Person later if needed. `in_list_view`, `in_standard_filter` |
| `section_status` | Lifecycle | Section Break | — | 0 | 0 | — |
| `status` | Status | Select | see §1.2.1 | 1 | 0 | State machine only — no arbitrary UI jumps. Default `PROPOSED`. `in_list_view`, `in_standard_filter` |
| `approval_required` | Approval Required | Check | — | 0 | 0 | Set by rate-floor / policy rules. `read_only` after first save beyond PROPOSED |
| `approval_id` | Approval | Link | `Fresko Approval` | 0 | 0 | **Required for no-silent-edit acceptance.** Points to immutable approval decision record. `read_only` once set. See §1.3 |
| `section_source` | Source & Dedup | Section Break | — | 0 | 0 | Collapsible |
| `source_message_id` | Source Message ID | Data | — | 0 | 0 | WhatsApp / ingest message id for idempotency. Indexed. Not unique alone (forwarded copies) — pair with fingerprint |
| `duplicate_fingerprint` | Duplicate Fingerprint | Data | — | 0 | 1 | Hash of normalized (container, alias, lot, qty, rate, message_id or content). Unique when set. `read_only` after insert |
| `deal_created_at` | Created At (Business) | Datetime | — | 0 | 0 | Business event time (message timestamp). Distinct from Frappe `creation`. Default `now()` |
| `section_locks` | Post-approval locks | Section Break | — | 0 | 0 | Collapsible; desktop reconciliation |
| `material_fields_locked` | Material Fields Locked | Check | — | 0 | 0 | Server-set when status ∈ {APPROVED, AUTO_APPROVED} or beyond. `read_only` |
| `last_revision_reason` | Last Revision Reason | Small Text | — | 0 | 0 | Required when unlocking via controlled revise API (future). `permlevel` 1 |
| `amended_from` | Amended From | Link | `Fresko Deal` | 0 | 0 | Reserved if amend workflow enabled later |

#### 1.2.1 `status` options (Deal) — exact Select string

```
PROPOSED
AUTO_APPROVED
APPROVAL_REQUIRED
APPROVED
COUNTERED
REJECTED
OUTWARD_PENDING
DISPATCHED
PAYMENT_PENDING
PAID
RECONCILED
CANCELLED
PARTIALLY_DISPATCHED
PARTIALLY_PAID
DISPUTED
```

**DocType meta (Deal):**  
`module` = Fresko Universe · `autoname` = `naming_series:` · `is_submittable` = 0 (V1; state machine replaces submit) · `track_changes` = 1 (**mandatory**) · `allow_rename` = 0 · `title_field` = `deal_id` · `search_fields` = `deal_id,container,customer,unresolved_buyer_alias,status,commercial_lot_no` · index on `source_message_id`, `duplicate_fingerprint`, `status`, `container`

---

### 1.3 Approval link fields (no-silent-edit acceptance)

Phase 1 acceptance: *salesperson submits below floor → owner approves/counters → approval stored → approved deal cannot be silently edited.*

`Fresko Approval` DocType is **not** fully specified in this memo, but Deal **must** expose:

| On Deal | Purpose |
|---------|---------|
| `approval_required` | Flag set by rate-floor rule |
| `approval_id` | Link → `Fresko Approval` (immutable decision: APPROVE / REJECT / COUNTER, decision_rate, approver, timestamp, reason, policy_floor) |
| `approved_rate` | Written only from Approval.decision_rate (or proposed_rate on AUTO_APPROVE) |
| `material_fields_locked` | Prevents Desk edits to qty / rates / party / lot after approval |

**Hard rules (server):**

1. Transition into `APPROVED` requires `approval_id` set and Approval.decision ∈ {APPROVE, COUNTER}.
2. Transition into `AUTO_APPROVED` requires `approval_required = 0` and `approved_rate = proposed_rate` (no Approval row, or system Approval with rule_trigger AUTO).
3. After lock: Desk `save` that changes `qty`, `proposed_rate`, `approved_rate`, `customer`, `unresolved_buyer_alias`, `lot_batch`, `commercial_lot_no`, `product`, `container` → `frappe.throw` unless called from whitelisted revise method that creates a new Approval + revision audit.
4. Frappe `track_changes` alone is insufficient — combine with field-level `read_only` + `validate` lock check.

---

## 2. Naming series proposals

| DocType | Series | Example `name` | Notes |
|---------|--------|----------------|-------|
| Fresko Container | `FC-.YYYY.-.#####` | `FC-2026-00042` | Year-scoped; company prefix optional later (`FC-.YY.-.####`) |
| Fresko Deal | `FD-.YYYY.-.#####` | `FD-2026-01087` | Dense sequence; do not embed container id in name (use Link) |

**Alternatives considered (reject for V1):**

- `autoname: field:container_id` — collisions across years / re-imports; keep commercial id as Data.
- `hash` autoname — poor ops UX on mobile list views.

**Implementation:** add series rows via fixtures or `setup.py` / `after_install` using `frappe.db.set_value` / Naming Series DocType. Roles that create documents need Create on DocType; series itself is System Manager maintained.

---

## 3. Links to ERPNext DocTypes

| Fresko field | ERPNext DocType | Why |
|--------------|-----------------|-----|
| `supplier_partner` | **Supplier** | Partner / Chinese supplier master; accounting payables later |
| `product` | **Item** | SKU / produce item; stock & batch settings |
| `unit` | **UOM** | Qty UOM consistency with Item defaults |
| `currency` | **Currency** | Multi-currency rates / company default |
| `country_of_origin` | **Country** | Standard geography master |
| `customer` | **Customer** | Resolved buyer; receivables later |
| `lot_batch` | **Batch** | ERPNext batch tracking (§10); keep `commercial_lot_no` parallel |
| `salesperson` | **User** | RBAC + `owner`-like audit; optional future Link to **Sales Person** |
| `closed_by` | **User** | Closure actor |
| *(future, not on these forms yet)* | Warehouse, Sales Order, Delivery Note, Sales Invoice, Payment Entry, Company | Linked at outward / invoice / payment stages — do not force on Deal create |

**Explicit non-links (defer):** do not Link Deal → Sales Order in V1 create path until open question §35 (SO timing) is decided.

---

## 4. Permission matrix

Roles: **Fresko Salesperson**, **Fresko Approver**, **Fresko Accounts**, **System Manager**.  
**Guest:** no permissions on either DocType.

Legend: C=create, R=read, W=write, D=delete, S=submit (N/A V1), Am=amend, Re=report, Ex=export, Im=import, Pr=print, E=email, Sh=share — Frappe perm flags.

### 4.1 Fresko Container

| Role | select | read | write | create | delete | report | export | import | print | email | share | If Owner | permlevel |
|------|--------|------|-------|--------|--------|--------|--------|--------|-------|-------|-------|----------|-----------|
| Fresko Salesperson | 1 | 1 | 0 | 0 | 0 | 1 | 0 | 0 | 1 | 0 | 0 | — | 0 only |
| Fresko Approver | 1 | 1 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | — | 0; write closing fields |
| Fresko Accounts | 1 | 1 | 1 | 0 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | — | 0 + 1 (landed_cost) |
| System Manager | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | — | all |
| Guest | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | — | — |

**Notes:** Salesperson is read-only on Container (needs stock context, not master edits). Approver owns open/close. Accounts may adjust `landed_cost` at permlevel 1.

### 4.2 Fresko Deal

| Role | select | read | write | create | delete | report | export | import | print | email | share | If Owner | permlevel |
|------|--------|------|-------|--------|--------|--------|--------|--------|-------|-------|-------|----------|-----------|
| Fresko Salesperson | 1 | 1 | 1 | 1 | 0 | 1 | 0 | 0 | 1 | 0 | 0 | 1 (optional) | 0; cannot edit locked fields / cannot set status past PROPOSED→APPROVAL_REQUIRED except via API |
| Fresko Approver | 1 | 1 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | — | 0; may set status via approval methods; write `approved_rate` only through Approval flow |
| Fresko Accounts | 1 | 1 | 1 | 0 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | — | 0; payment-side status transitions later; V1 read + limited write on reconciliation fields |
| System Manager | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | — | all |
| Guest | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | — | — |

**Role assignment guidance:** map ERPNext “Sales User” ≠ Fresko Salesperson — create dedicated Role fixtures. Never grant Salesperson Delete. Never grant Guest Select.

**Field permlevels (Deal):**

| permlevel | Fields | Who writes |
|-----------|--------|------------|
| 0 | Most operational fields | Salesperson (pre-lock), Approver |
| 1 | `approved_rate`, `approval_id`, `material_fields_locked`, `last_revision_reason` | Approver / System Manager only |

---

## 5. Server-side hooks sketch

Python controllers under:

```
fresko_universe/fresko_universe/doctype/fresko_container/fresko_container.py
fresko_universe/fresko_universe/doctype/fresko_deal/fresko_deal.py
```

Shared helpers (suggested):

```
fresko_universe/fresko_universe/deals/state_machine.py
fresko_universe/fresko_universe/deals/rules.py
fresko_universe/fresko_universe/deals/fingerprint.py
```

### 5.1 Deal lifecycle state machine (validate in code)

Allowed transitions:

```
PROPOSED → AUTO_APPROVED | APPROVAL_REQUIRED | CANCELLED
APPROVAL_REQUIRED → APPROVED | COUNTERED | REJECTED | CANCELLED
COUNTERED → APPROVAL_REQUIRED | APPROVED | REJECTED | CANCELLED
AUTO_APPROVED | APPROVED → OUTWARD_PENDING | CANCELLED | DISPUTED
OUTWARD_PENDING → DISPATCHED | PARTIALLY_DISPATCHED | CANCELLED | DISPUTED
PARTIALLY_DISPATCHED → DISPATCHED | CANCELLED | DISPUTED
DISPATCHED → PAYMENT_PENDING | DISPUTED
PAYMENT_PENDING → PAID | PARTIALLY_PAID | DISPUTED
PARTIALLY_PAID → PAID | DISPUTED
PAID → RECONCILED | DISPUTED
DISPUTED → (return to prior commercial state only via Approver + reason)  # document explicitly
REJECTED, CANCELLED, RECONCILED → ∅ (terminal)
```

Terminals: `CANCELLED`, `REJECTED`, `RECONCILED`, and interruption terminals `PARTIALLY_DISPATCHED`, `PARTIALLY_PAID`, `DISPUTED` (DISPUTED is interruptive — may leave with reason).

### 5.2 Hook sketch — `Fresko Deal`

```python
# fresko_deal.py (sketch — not production code)

import frappe
from frappe.model.document import Document
from fresko_universe.deals.state_machine import assert_transition, TERMINAL
from fresko_universe.deals.rules import check_rate_floor, check_stock_availability
from fresko_universe.deals.fingerprint import build_duplicate_fingerprint

MATERIAL_FIELDS = {
    "qty", "proposed_rate", "approved_rate", "customer",
    "unresolved_buyer_alias", "lot_batch", "commercial_lot_no",
    "product", "container", "unit",
}

class FreskoDeal(Document):
    def before_insert(self):
        if not self.deal_created_at:
            self.deal_created_at = frappe.utils.now_datetime()
        if not self.duplicate_fingerprint:
            self.duplicate_fingerprint = build_duplicate_fingerprint(self)
        # unique constraint will reject true duplicates

    def validate(self):
        self._validate_party()
        self._validate_qty()
        self._validate_state_transition()
        self._enforce_no_silent_edit()
        self._apply_rule_stubs()

    def before_save(self):
        # Normalize alias trim; ensure currency from container if empty
        if self.container and not self.currency:
            self.currency = frappe.db.get_value(
                "Fresko Container", self.container, "currency"
            )
        if self.unresolved_buyer_alias:
            self.unresolved_buyer_alias = self.unresolved_buyer_alias.strip()

    def on_update(self):
        # Side effects: notify approver queue when entering APPROVAL_REQUIRED
        # (implementation deferred — stub hook point)
        if self.has_value_changed("status"):
            if self.status == "APPROVAL_REQUIRED":
                self._enqueue_approval_notification()  # stub
            if self.status in ("APPROVED", "AUTO_APPROVED"):
                self.db_set("material_fields_locked", 1, update_modified=False)

    def _validate_party(self):
        if not self.customer and not self.unresolved_buyer_alias:
            frappe.throw("Either Customer or Unresolved Buyer Alias is required.")

    def _validate_qty(self):
        if self.qty is None or self.qty <= 0:
            frappe.throw("Qty must be greater than zero.")

    def _validate_state_transition(self):
        if self.is_new():
            if self.status != "PROPOSED":
                frappe.throw("New deals must start in PROPOSED.")
            return
        old = self.get_doc_before_save()
        if not old:
            return
        if old.status == self.status:
            return
        assert_transition(old.status, self.status)  # throws if illegal
        if self.status == "APPROVED" and not self.approval_id:
            frappe.throw("APPROVED requires approval_id (Fresko Approval link).")

    def _enforce_no_silent_edit(self):
        if self.is_new():
            return
        old = self.get_doc_before_save()
        if not old:
            return
        locked = old.material_fields_locked or old.status in {
            "APPROVED", "AUTO_APPROVED", "OUTWARD_PENDING", "DISPATCHED",
            "PAYMENT_PENDING", "PAID", "RECONCILED",
            "PARTIALLY_DISPATCHED", "PARTIALLY_PAID",
        }
        if not locked:
            return
        # Allow status-only / non-material updates; block material field mutation
        for f in MATERIAL_FIELDS:
            if self.get(f) != old.get(f):
                frappe.throw(
                    f"Cannot silently edit '{f}' after approval. "
                    "Use revision + Fresko Approval."
                )

    def _apply_rule_stubs(self):
        """Called while status is PROPOSED (or re-eval on COUNTERED resubmit)."""
        if self.status not in ("PROPOSED", "COUNTERED"):
            return
        # --- rate floor stub ---
        floor_result = check_rate_floor(self)  # returns {ok, floor, ceiling, decision}
        # --- stock availability stub ---
        stock_result = check_stock_availability(self)  # returns {ok, available, reasons}
        if not stock_result.get("ok"):
            frappe.throw(stock_result.get("reasons") or "Insufficient available stock.")
        if floor_result.get("decision") == "AUTO_APPROVE":
            self.approval_required = 0
            # status move happens via explicit method submit_deal(), not raw save
        elif floor_result.get("decision") == "APPROVAL_REQUIRED":
            self.approval_required = 1
```

### 5.3 Rule stubs (deterministic)

```python
# rules.py stubs

def check_rate_floor(deal) -> dict:
    """
    V1 stub: read policy floor from Container/Item/Company setting (TBD open Q §35).
    If proposed_rate < floor → APPROVAL_REQUIRED.
    If within band → AUTO_APPROVE.
    Never auto-write approved_rate here — caller/workflow does.
    """
    floor = _get_policy_floor(deal)  # placeholder
    if deal.proposed_rate is None:
        return {"ok": False, "decision": "REJECT", "reasons": ["missing rate"]}
    if floor is not None and deal.proposed_rate < floor:
        return {
            "ok": True,
            "decision": "APPROVAL_REQUIRED",
            "floor": floor,
            "ceiling": None,
        }
    return {"ok": True, "decision": "AUTO_APPROVE", "floor": floor, "ceiling": None}


def check_stock_availability(deal) -> dict:
    """
    V1 stub: available_to_sell = inward - approved_sold - reserved (formula TBD §10/§35).
    Do not treat deal as physical outward.
    """
    available = _stub_available_qty(deal.container, deal.lot_batch, deal.commercial_lot_no)
    if available is None:
        return {"ok": True, "available": None, "reasons": ["stock check deferred"]}
    if deal.qty > available:
        return {
            "ok": False,
            "available": available,
            "reasons": [f"Qty {deal.qty} exceeds available {available}"],
        }
    return {"ok": True, "available": available, "reasons": []}
```

### 5.4 Duplicate fingerprint

```python
# fingerprint.py

import hashlib

def build_duplicate_fingerprint(deal) -> str:
    parts = [
        (deal.container or "").strip().lower(),
        (deal.unresolved_buyer_alias or deal.customer or "").strip().lower(),
        (deal.commercial_lot_no or deal.lot_batch or "").strip().lower(),
        f"{float(deal.qty or 0):.3f}",
        f"{float(deal.proposed_rate or 0):.4f}",
        (deal.source_message_id or "").strip(),
    ]
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
```

On unique conflict → throw friendly “Duplicate deal fingerprint; possible replay.”

### 5.5 Container hooks (minimal)

```python
class FreskoContainer(Document):
    def validate(self):
        if self.inward_qty is not None and self.inward_qty < 0:
            frappe.throw("Inward Qty cannot be negative.")
        if self.closing_status == "CLOSED" and self.status != "CLOSED":
            frappe.throw("closing_status CLOSED requires status CLOSED.")
        # Refuse CLOSE when open deal exceptions exist — stub call to exception engine later
```

### 5.6 Whitelisted workflow methods (preferred over raw status edits)

```python
@frappe.whitelist()
def submit_deal(deal_name: str):
    """PROPOSED → AUTO_APPROVED | APPROVAL_REQUIRED after rules."""

@frappe.whitelist()
def apply_approval_decision(deal_name: str, approval_name: str):
    """Sets approval_id, approved_rate, status APPROVED|COUNTERED|REJECTED."""
```

Salesperson UI should call these methods, not set `status` freely in Desk.

---

## 6. Suggested JSON DocType structure notes (Frappe-compatible)

Place fixtures/exports at:

```
fresko_universe/fresko_universe/doctype/fresko_container/fresko_container.json
fresko_universe/fresko_universe/doctype/fresko_deal/fresko_deal.json
```

**JSON shape conventions (v15):**

- Top-level keys: `name`, `module`, `doctype`=`DocType`, `engine`=`InnoDB`, `field_order` (list of fieldnames), `fields` (array of field dicts), `permissions`, `actions`, `links`, `states` (optional Status Indicator).
- Each field dict minimally: `fieldname`, `fieldtype`, `label`; plus `options`, `reqd`, `unique`, `read_only`, `in_list_view`, `in_standard_filter`, `in_preview`, `permlevel`, `default`, `precision`, `collapsible`, `hidden`, `set_only_once` as needed.
- Use `"default": "PROPOSED"` on Deal.status; `"default": "DRAFT"` / `"OPEN"` on Container status fields.
- Currency fields: `"options": "currency"` (fieldname of the Link Currency field on same DocType).
- Float precision: `"precision": "3"` for qty.
- For Select options, use newline-separated string in `options`.
- Enable `"track_changes": 1`, `"track_seen": 1` (optional), `"sort_field": "modified"`, `"sort_order": "DESC"`.
- `"quick_entry": 1` on Deal for mobile create (see §7).
- `"image_field"`: omit (QC photos live on Fresko Evidence later).
- Child tables: none in V1 for these two DocTypes (`source_documents` = Attach).
- Document Links (Desk sidebar): add Link from Container → Deal (`link_doctype` Fresko Deal, `link_fieldname` container).
- Status Indicator (`states`): color map e.g. PROPOSED=orange, APPROVAL_REQUIRED=red, APPROVED=green, DISPATCHED=blue, RECONCILED=dark grey, CANCELLED=grey.

**Do not** set `"is_submittable": 1` in V1 — submit workflow would fight the custom state machine; revisit if amend/cancel semantics are desired later.

**Fixtures:** export Roles + Role Profile + Naming Series + DocType (if not in app) via `hooks.py` `fixtures`.

---

## 7. Mobile-friendly form layout hints

Optimize for salesperson phone + approver quick action; richer desktop for accounts.

### 7.1 Fresko Deal — Quick Entry + sections

**Enable Quick Entry** with only:

1. `container`  
2. `unresolved_buyer_alias` (or `customer`)  
3. `commercial_lot_no`  
4. `qty`  
5. `proposed_rate`  
6. `salesperson` (default `frappe.session.user`)

Full form sections (top → bottom):

| Section | Fields | Mobile note |
|---------|--------|-------------|
| **Header** (no label) | naming_series (hidden), deal_id (read_only), status (indicator) | Status badge prominent |
| **Party** | container, customer, unresolved_buyer_alias | Single column on narrow screens; alias first for WhatsApp-origin deals |
| **Product / Lot** | product, commercial_lot_no, lot_batch, count_size, qty, unit | Lot + qty adjacent |
| **Rate** | proposed_rate, approved_rate (read_only), currency, approval_required, approval_id | approved_rate visually muted until set |
| **People** | salesperson, deal_created_at | — |
| **Source & Dedup** (collapsible) | source_message_id, duplicate_fingerprint | Hidden in Quick Entry |
| **Locks** (collapsible) | material_fields_locked, last_revision_reason | Approver/desktop |

**UX rules:**

- Default `salesperson` = session user.  
- Hide `naming_series` from non–System Manager.  
- Use Frappe **Depends On**: show `approval_id` when `approval_required` or status in approved set.  
- List view columns: `deal_id`, `container`, `unresolved_buyer_alias`/`customer`, `qty`, `proposed_rate`, `approved_rate`, `status`.  
- Prefer workspace shortcut **New Deal** → Quick Entry, not full Desk tree.

### 7.2 Fresko Container — form layout

| Section | Fields |
|---------|--------|
| **Identity** | container_id, supplier_partner, country_of_origin, product |
| **Arrival** | arrival_date, inward_qty, unit, landed_cost, currency |
| **Status** | status, closing_status |
| **Documents** (collapsible) | source_documents, source_document_notes |
| **Close audit** (collapsible) | closed_by, closed_at |

List view: `container_id`, `product`, `arrival_date`, `inward_qty`, `status`, `closing_status`.

Salesperson: open Container read-only from Deal link for stock context — do not bury them in Container edit.

### 7.3 Approval card alignment (UI later)

Desktop/mobile approval card should read from Deal + linked Approval:

`Buyer | Qty | Lot | Proposed | Floor | Available stock | [Approve] [Counter] [Reject]`

Those buttons call `apply_approval_decision`, never free-edit `approved_rate`.

---

## 8. Acceptance scenario mapping (Phase 1)

| Step | System behavior |
|------|-----------------|
| Salesperson creates Deal qty=50, proposed_rate below floor | `validate` → `approval_required=1`; `submit_deal` → status `APPROVAL_REQUIRED` |
| Owner decides | Creates/links `Fresko Approval`; `apply_approval_decision` sets `approval_id`, `approved_rate`, status `APPROVED` or `COUNTERED`/`REJECTED` |
| Attempt silent edit of approved qty/rate | `_enforce_no_silent_edit` throws; `track_changes` retains history |
| Duplicate WhatsApp replay | Same `duplicate_fingerprint` → unique violation / explicit throw |

---

## 9. Open decisions (do not silently hard-code)

From codex §35, still blocking full rule implementation:

1. Rate-floor ownership (container vs lot vs count vs buyer).  
2. Stock reservation semantics for approved-but-not-dispatched deals.  
3. Whether `salesperson` should later Link to ERPNext **Sales Person**.  
4. Whether `is_submittable` should replace part of the state machine in a later phase.  
5. Timing of Sales Order creation (not on these DocTypes yet).

---

## 10. File deliverable checklist

- [x] Field tables — Container + Deal  
- [x] Naming series  
- [x] ERPNext Link map  
- [x] Permission matrix (4 roles + Guest none)  
- [x] Hooks sketch (validate / before_save / on_update + stubs)  
- [x] JSON DocType notes  
- [x] Mobile / Quick Entry layout  
- [x] Approval link fields for no-silent-edit  

**Next implementation slice (not this memo):** scaffold `bench new-app fresko_universe`, add DocType JSONs + empty controllers, Role fixtures, then implement `state_machine.assert_transition` with unit tests.
