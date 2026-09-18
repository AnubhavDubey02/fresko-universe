# Fresko Container + Fresko Deal — DocType Design (v1)

> **Superseded design draft — 15 September 2026.** Retained as historical
> evidence. The mandatory Revision path, Counter acceptance, and all other
> current Phase 1 decisions are governed by `docs/PHASE1_BLUEPRINT_FINAL.md` and
> `docs/DECISIONS.md`. See `docs/CANONICAL_DOCUMENTS.md`.

App: `fresko_universe`  
Target: Frappe / ERPNext **v15**  
Date: 2026-09-15  
Scope: Container + Deal only. Out of scope: WhatsApp, AI, payments, QC, buyer-resolution engine, partner portal, Fresko Approval DocType body (link stub only).

## Design principles (locked)

1. ERPNext is SoR for Customer, Supplier, Item, Batch, Warehouse, Company, Currency, UOM, Sales Person, User.
2. Custom DocTypes only for produce-trade concepts ERPNext does not model cleanly (container lifecycle + commercial deal state machine).
3. No parallel accounting DB. `landed_cost` on Container is **management/ops**; GL stays in Purchase Invoice / Landed Cost Voucher / Payment Entry later.
4. Commercial LOT No. preserved even when ERPNext Batch name differs.
5. No silent mutation of approved commercial fields; revisions need reason + actor (Version + optional later Fresko Revision).
6. Deal status transitions are server-validated only; UI cannot set illegal states.

---

## 1. Fresko Container

### Meta

| Property | Value |
|---|---|
| name | `Fresko Container` |
| module | Fresko Core |
| naming_rule | Expression / Naming Series |
| autoname | `naming_series:` |
| is_submittable | 0 (v1) — close via `closing_status`; submit can be added when Settlement DocType lands |
| track_changes | 1 |
| allow_rename | 0 |
| title_field | `container_no` |
| search_fields | `container_no,supplier,item,status` |
| default_view | List |

### Naming series

- Field: `naming_series` (Select, reqd, default `CON-.YYYY.-.`)
- Options: `CON-.YYYY.-.`
- Example name: `CON-2026-00042`
- Commercial/physical id: separate field `container_no` (shipping container number / internal label), unique per Company.

### Fields

| fieldname | label | fieldtype | options / link | reqd | default | read_only / rules | notes |
|---|---|---|---|---|---|---|---|
| naming_series | Series | Select | `CON-.YYYY.-.` | 1 | `CON-.YYYY.-.` | | Autoname |
| company | Company | Link | Company | 1 | user default | | Multi-company safe |
| container_no | Container No | Data | | 1 | | unique with company | Physical/shipping id; not DocType name |
| supplier | Supplier Partner | Link | Supplier | 1 | | | Prefer ERPNext Supplier over custom Partner |
| country_of_origin | Country of Origin | Link | Country | 0 | | | |
| item | Product | Link | Item | 1 | | | Primary produce item for this container |
| item_name | Item Name | Data | | 0 | | fetch_from `item.item_name`, read_only | |
| arrival_date | Arrival Date | Date | | 1 | | | |
| warehouse | Inward Warehouse | Link | Warehouse | 0 | | | Cold storage / receiving WH |
| inward_qty | Inward Qty | Float | | 1 | | | Physical inward; source of truth for qty math |
| uom | Unit | Link | UOM | 1 | | | Prefer crate/box/kg from Item default UOM |
| currency | Currency | Link | Currency | 1 | Company default | | |
| landed_cost | Landed Cost (Ops) | Currency | | 0 | | | **Ops estimate only** — not GL posting |
| status | Status | Select | see below | 1 | `Draft` | | Operational lifecycle |
| closing_status | Closing Status | Select | see below | 1 | `Open` | | Distinct from ops status |
| opening_notes | Opening Notes | Small Text | | 0 | | | |
| source_documents | Source Documents | Table | Fresko Container Source Document | 0 | | | Child: file refs / hashes later |
| amended_from | Amended From | Link | Fresko Container | 0 | | read_only, hidden until amend used | Reserved |

**status options:**  
`Draft` / `Expected` / `Arrived` / `In Cold Storage` / `Selling` / `Closing` / `Closed` / `Cancelled`

**closing_status options:**  
`Open` / `Ready to Close` / `Closed with Exceptions` / `Fully Reconciled` / `Cancelled`

### Child table: Fresko Container Source Document

| fieldname | label | fieldtype | options | reqd | notes |
|---|---|---|---|---|---|
| document_type | Document Type | Select | `Bill of Lading` / `Packing List` / `Invoice` / `Gatepass` / `Other` | 1 | |
| attachment | Attachment | Attach | | 0 | |
| reference | External Reference | Data | | 0 | |
| content_hash | Content Hash | Data | | 0 | read_only when set; sha256 later |
| notes | Notes | Small Text | | 0 | |

### Links / indexes

- Unique: `(company, container_no)`
- Index: `status`, `arrival_date`, `supplier`, `item`
- Future parents: Deal → Container; Settlement → Container; QC → Container

### Permissions — Fresko Container

| Role | create | read | write | delete | submit | cancel | amend | export | report | share | email | print |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| System Manager | 1 | 1 | 1 | 1 | 0 | 0 | 0 | 1 | 1 | 1 | 1 | 1 |
| Fresko Approver | 1 | 1 | 1 | 0 | 0 | 0 | 0 | 1 | 1 | 0 | 1 | 1 |
| Fresko Accounts | 0 | 1 | 1* | 0 | 0 | 0 | 0 | 1 | 1 | 0 | 1 | 1 |
| Fresko Salesperson | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 1 |

\* Accounts write limited via `permission_query` / field-level later to landed_cost, notes, closing fields — not inward_qty rewrite without reason. v1: full write on Accounts; enforce material qty edits in `validate`.

If-owner: Salesperson none. Approver/Accounts use role, not only owner.

### Server hooks sketch — Fresko Container

```python
# fresko_universe/fresko_core/doctype/fresko_container/fresko_container.py

ALLOWED_STATUS = {
    "Draft": {"Expected", "Arrived", "Cancelled"},
    "Expected": {"Arrived", "Cancelled"},
    "Arrived": {"In Cold Storage", "Selling", "Cancelled"},
    "In Cold Storage": {"Selling", "Closing", "Cancelled"},
    "Selling": {"Closing", "Cancelled"},
    "Closing": {"Closed", "Selling"},  # reopen to Selling only with reason
    "Closed": set(),  # reopen only via controlled method
    "Cancelled": set(),
}

def validate(self):
    self._validate_inward_qty()
    self._validate_status_transition()
    self._validate_close_gate()

def _validate_inward_qty(self):
    if self.inward_qty is not None and self.inward_qty <= 0 and self.status not in ("Draft", "Expected", "Cancelled"):
        frappe.throw("Inward Qty must be > 0 once container has arrived")
    if not self.is_new() and self.has_value_changed("inward_qty"):
        old = self.get_db_value("inward_qty")
        if old and self.status in ("Selling", "Closing", "Closed"):
            # require reason in a comment / custom field before allowing
            if not self.flags.inward_qty_change_reason:
                frappe.throw("Cannot change Inward Qty after selling started without an explicit reason")

def _validate_status_transition(self):
    if self.is_new():
        return
    old = self.get_db_value("status")
    if old == self.status:
        return
    allowed = ALLOWED_STATUS.get(old, set())
    if self.status not in allowed:
        frappe.throw(f"Invalid status transition {old} → {self.status}")

def _validate_close_gate(self):
    if self.closing_status == "Fully Reconciled":
        # Settlement DocType later: block if unresolved material exceptions
        if self.status != "Closed":
            frappe.throw("Set Status to Closed before Fully Reconciled")

def on_update(self):
    # snapshot hook point for container stock metrics (computed, not stored blindly)
    pass
```

`on_submit` / `on_cancel`: N/A while `is_submittable=0`.

---

## 2. Fresko Deal

### Meta

| Property | Value |
|---|---|
| name | `Fresko Deal` |
| module | Fresko Deals |
| autoname | `naming_series:` |
| is_submittable | 0 (v1) — commercial lock via status + field read_only rules (Approval DocType + amend pattern later) |
| track_changes | 1 |
| allow_rename | 0 |
| title_field | `title` |
| search_fields | `container,customer,buyer_alias,lot_no,status,salesperson` |

### Naming series

- `naming_series` options: `DEAL-.YYYY.-.`
- Example: `DEAL-2026-01052`

### Fields

| fieldname | label | fieldtype | options / link | reqd | default | read_only / rules | notes |
|---|---|---|---|---|---|---|---|
| naming_series | Series | Select | `DEAL-.YYYY.-.` | 1 | `DEAL-.YYYY.-.` | | |
| company | Company | Link | Company | 1 | | fetch from container when set | |
| title | Title | Data | | 0 | | read_only, set in validate | e.g. `Rehan · 50 · 41869` |
| container | Container | Link | Fresko Container | 1 | | | |
| customer | Customer | Link | Customer | 0 | | | Empty until alias resolved |
| buyer_alias | Buyer Alias | Data | | 1 | | **never wipe** after create | Original commercial alias |
| item | Product | Link | Item | 1 | | prefer fetch from container.item | |
| batch | Batch | Link | Batch | 0 | | | ERPNext Batch when mapped |
| lot_no | Commercial Lot No | Data | | 1 | | | Preserve even if Batch name differs |
| count_size | Count / Size | Data | | 0 | | | e.g. count pack |
| qty | Qty | Float | | 1 | | | |
| uom | UOM | Link | UOM | 1 | | fetch from container.uom | |
| proposed_rate | Proposed Rate | Currency | | 1 | | locked after leave PROPOSED* | |
| approved_rate | Approved Rate | Currency | | 0 | | set only by approval path | Never overwrite silently |
| currency | Currency | Link | Currency | 1 | | fetch from container | |
| amount | Amount | Currency | | 0 | | read_only | `qty * (approved_rate or proposed_rate)` |
| salesperson | Salesperson | Link | Sales Person | 0 | | | ERPNext Sales Person |
| salesperson_user | Salesperson User | Link | User | 0 | | | For permission if_owner patterns |
| status | Status | Select | see below | 1 | `Proposed` | server-only transitions | |
| approval_required | Approval Required | Check | | 0 | 0 | set by rules engine | |
| approval | Approval | Link | Fresko Approval | 0 | | read_only | Stub until Approval DocType exists — create empty DocType shell or use Data `approval_id` temporarily |
| source_message_id | Source Message ID | Data | | 0 | | read_only once set, unique where set | Idempotency key (WhatsApp later) |
| duplicate_fingerprint | Duplicate Fingerprint | Data | | 0 | | read_only once set, unique where set | Hash of alias+lot+qty+rate+container+day |
| created_on | Created On | Datetime | | 0 | Now | read_only | Explicit; also use creation |
| rate_floor | Rate Floor (Snapshot) | Currency | | 0 | | read_only | Snapshot at propose time |
| rate_ceiling | Rate Ceiling (Snapshot) | Currency | | 0 | | read_only | Optional |
| cancel_reason | Cancel Reason | Small Text | | 0 | | reqd when → Cancelled | |
| amended_from | Amended From | Link | Fresko Deal | 0 | | read_only | |

\* After status leaves `Proposed`, `proposed_rate`, `qty`, `lot_no`, `buyer_alias`, `container`, `item` are read_only except via controlled revision API.

### Status options (exact machine)

Primary:

`Proposed` → `Auto Approved` | `Approval Required`  
`Approval Required` → `Approved` | `Countered` | `Rejected`  
`Approved` | `Auto Approved` | `Countered`† → `Outward Pending`  
`Outward Pending` → `Dispatched` | `Partially Dispatched` | `Cancelled`  
`Dispatched` | `Partially Dispatched` → `Payment Pending`  
`Payment Pending` → `Paid` | `Partially Paid` | `Disputed`  
`Paid` | `Partially Paid` → `Reconciled`  
Also: → `Cancelled` / `Disputed` from allowed nodes below.

† `Countered` means approver set a decision rate; treat commercially like Approved once `approved_rate` is set (decision_rate). Salesperson must accept counter in a later phase; **v1:** Countered with `approved_rate` set may move to Outward Pending.

**Select options string:**

```
Proposed
Auto Approved
Approval Required
Approved
Countered
Rejected
Outward Pending
Dispatched
Partially Dispatched
Payment Pending
Paid
Partially Paid
Reconciled
Cancelled
Disputed
```

### Child tables (v1)

None required for Deal v1. Evidence / dispatch / payment links arrive as separate DocTypes with Link → Fresko Deal.

Optional later: `Fresko Deal Revision` child for old/new/reason — until then rely on `track_changes` + forbid field edits in `validate`.

### Links / uniqueness

- Unique where not null: `source_message_id`
- Unique where not null: `duplicate_fingerprint`
- Index: `container`, `status`, `customer`, `lot_no`, `salesperson_user`

### Permissions — Fresko Deal

| Role | create | read | write | delete | export | report | if_owner | notes |
|---|---|---|---|---|---|---|---|---|
| System Manager | 1 | 1 | 1 | 1 | 1 | 1 | 0 | Full |
| Fresko Approver | 1 | 1 | 1 | 0 | 1 | 1 | 0 | Approve / counter / reject via methods |
| Fresko Accounts | 0 | 1 | 0 | 0 | 1 | 1 | 0 | Read for recon; payment DocTypes later write |
| Fresko Salesperson | 1 | 1 | 1 | 0 | 0 | 1 | 1 | Create/propose; write only while Proposed / own docs |

Use `has_permission` to block Salesperson write when status ∉ {`Proposed`} except attaching non-commercial notes (phase later).

### Server hooks sketch — Fresko Deal

```python
# fresko_universe/fresko_deals/doctype/fresko_deal/fresko_deal.py

TRANSITIONS = {
    "Proposed": {"Auto Approved", "Approval Required", "Cancelled"},
    "Approval Required": {"Approved", "Countered", "Rejected", "Cancelled"},
    "Auto Approved": {"Outward Pending", "Cancelled", "Disputed"},
    "Approved": {"Outward Pending", "Cancelled", "Disputed"},
    "Countered": {"Outward Pending", "Cancelled", "Disputed"},  # v1: after approved_rate set
    "Rejected": {"Cancelled"},  # terminal-ish
    "Outward Pending": {"Dispatched", "Partially Dispatched", "Cancelled", "Disputed"},
    "Dispatched": {"Payment Pending", "Disputed"},
    "Partially Dispatched": {"Dispatched", "Payment Pending", "Cancelled", "Disputed"},
    "Payment Pending": {"Paid", "Partially Paid", "Disputed", "Cancelled"},
    "Paid": {"Reconciled", "Disputed"},
    "Partially Paid": {"Paid", "Reconciled", "Disputed"},
    "Reconciled": set(),
    "Cancelled": set(),
    "Disputed": {"Outward Pending", "Payment Pending", "Cancelled"},  # resolve paths narrow later
}

COMMERCIAL_LOCK_STATUSES = {
    "Auto Approved", "Approved", "Countered", "Outward Pending",
    "Dispatched", "Partially Dispatched", "Payment Pending",
    "Paid", "Partially Paid", "Reconciled",
}

LOCKED_FIELDS = {
    "container", "buyer_alias", "item", "lot_no", "qty",
    "proposed_rate", "uom", "company",
}

def validate(self):
    self._set_title()
    self._fetch_defaults_from_container()
    self._validate_qty()
    self._validate_lot_belongs_to_container()  # stub: lot_no non-empty; Batch link optional
    self._validate_status_transition()
    self._enforce_commercial_lock()
    self._compute_amount()
    self._validate_fingerprint_unique()

def before_insert(self):
    if not self.duplicate_fingerprint:
        self.duplicate_fingerprint = self._make_fingerprint()
    if self.status != "Proposed":
        frappe.throw("New deals must start as Proposed")

def _make_fingerprint(self):
    # deterministic; WhatsApp path will include message id separately
    raw = "|".join([
        self.container or "",
        (self.buyer_alias or "").strip().lower(),
        self.lot_no or "",
        frappe.format(self.qty or 0),
        frappe.format(self.proposed_rate or 0),
        str(self.creation or frappe.utils.nowdate())[:10],
    ])
    return frappe.utils.sha256_hash(raw)

def _enforce_commercial_lock(self):
    if self.is_new():
        return
    old_status = self.get_db_value("status")
    if old_status in COMMERCIAL_LOCK_STATUSES or self.status in COMMERCIAL_LOCK_STATUSES:
        for f in LOCKED_FIELDS:
            if self.has_value_changed(f) and not self.flags.allow_commercial_revision:
                frappe.throw(f"Cannot change {f} after commercial approval without revision flow")
        if self.has_value_changed("approved_rate") and not self.flags.allow_approval_write:
            frappe.throw("approved_rate can only be set by the approval decision path")

def _validate_status_transition(self):
    if self.is_new():
        return
    old = self.get_db_value("status")
    if old == self.status:
        return
    if self.status not in TRANSITIONS.get(old, set()):
        frappe.throw(f"Invalid deal status {old} → {self.status}")

def _compute_amount(self):
    rate = self.approved_rate if self.approved_rate is not None else self.proposed_rate
    self.amount = (self.qty or 0) * (rate or 0)

def on_update(self):
    pass

# Whitelisted methods (not raw status UI edits):
@frappe.whitelist()
def apply_rate_rules(deal_name):
    """Set approval_required / Auto Approved from floor rules; snapshot floor/ceiling."""
    ...

@frappe.whitelist()
def apply_approval_decision(deal_name, decision, decision_rate=None, reason=None):
    """Only Fresko Approver. Writes immutable Approval row (when DocType exists), sets approved_rate, status."""
    ...
```

### Rate-rule behavior (deterministic, no AI)

On save while `Proposed` (or via `apply_rate_rules`):

1. Load floor/ceiling for container/item/lot (config DocType later; v1: Company defaults or Container-level custom fields `default_rate_floor` / `default_rate_ceiling` optional).
2. If `proposed_rate` inside band → `status = Auto Approved`, `approved_rate = proposed_rate`, `approval_required = 0`.
3. If below floor or above ceiling → `status = Approval Required`, `approval_required = 1`, leave `approved_rate` empty.
4. Stock availability check (approved sold + this qty ≤ inward − cancelled): if fail → throw or force Approval Required + exception (Exception DocType later).

### Stock reservation note (open question)

Brief §35: reservation semantics undecided. **v1 recommendation:** do **not** create Stock Entry / Sales Order on Auto Approved. Only compute soft `available_to_sell` on Container snapshot. Link Delivery Note / SO when Outward phase is built.

---

## 3. Roles to create (custom)

| Role | Purpose |
|---|---|
| `Fresko Salesperson` | Propose deals, read containers/stock snapshot |
| `Fresko Approver` | Own/authorized rate decisions, container close |
| `Fresko Accounts` | Reconciliation read; payment matching later |

Map ERPNext `Sales User` / `Accounts User` only if you want inheritance; prefer Fresko-prefixed roles for clear matrices.

---

## 4. hooks.py entries (sketch)

```python
# fresko_universe/hooks.py
doc_events = {
    "Fresko Container": {
        "validate": "fresko_universe.fresko_core.doctype.fresko_container.fresko_container.validate",
        "on_update": "fresko_universe.fresko_core.doctype.fresko_container.fresko_container.on_update",
    },
    "Fresko Deal": {
        "validate": "fresko_universe.fresko_deals.doctype.fresko_deal.fresko_deal.validate",
        "before_insert": "fresko_universe.fresko_deals.doctype.fresko_deal.fresko_deal.before_insert",
        "on_update": "fresko_universe.fresko_deals.doctype.fresko_deal.fresko_deal.on_update",
    },
}
```

(Prefer controller methods on the Document class over string hooks when using standard DocType Python files.)

---

## 5. Explicit non-goals in this design

- No WhatsApp webhook fields beyond `source_message_id` placeholder.
- No AI confidence fields on Deal.
- No Payment Entry creation.
- No QC fields.
- No buyer Candidate / Alias master (only `buyer_alias` + optional `customer` link).
- No partner portal permissions.
- No GL from `landed_cost`.

---

## 6. Open questions (do not silently decide)

1. Should Auto Approved deals reserve stock hard or soft? (**soft** recommended for v1)
2. Is `Countered` auto-accepted or must salesperson confirm?
3. Create empty `Fresko Approval` DocType shell now so Link options resolve, or use Data `approval_id` until Phase 1 Approval lands?
4. Rate floor grain: Company / Container / Item / Lot / Count?
5. When (if ever) does Deal create Sales Order vs only at Dispatch?

---

## 7. Implementation order inside Phase 1

1. Roles + Module Def  
2. Fresko Container + child Source Document  
3. Empty Fresko Approval shell (for Link)  
4. Fresko Deal + transitions + commercial lock  
5. `apply_rate_rules` + `apply_approval_decision` whitelists  
6. Desk workspace: Containers, My Deals, Pending Approvals  

