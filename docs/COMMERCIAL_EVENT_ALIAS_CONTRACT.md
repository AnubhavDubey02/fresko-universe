# Commercial Event and Party-Alias Contract

**Status:** implementation contract for the next shadow-replay slice

**Effective:** 2026-10-02
**Scope:** internal commercial truth only; no runtime change in this document.

## 1. Boundary

Add **Fresko Commercial Sale**, **Fresko Commercial Sale Line**, **Fresko Party
Alias Mapping**, and **Fresko Sale Outward Allocation**. A Sale is one
commercial event with many lines. Keep Fresko Deal as compatibility context,
not the ledger: its scalar lot/rate and legacy `dispatched_qty` cannot represent
multi-lot sales, unknown prices, or buckets. Existing Deals are not backfilled.
Outward remains the sole physical ledger.

`sale_at` is commercial event time. Each linked Outward retains its own
authoritative `movement_at`; there is no Sale movement timestamp used for
linkage. Optional `raw_movement_at` may preserve source wording, but is never
authoritative. Sale and movement dates may differ.

## 2. Exact DocTypes

All fields are server-controlled after creation. Frappe `name`, `owner`,
`creation`, `modified`, and `modified_by` also apply. Numeric fields use Frappe
`Data` for canonical decimal text (and optional display-only Currency/Float),
never binary-float identity. Services parse canonical decimal strings to
`Decimal`, reject exponent/NaN/infinite values, apply fixed currency/UOM scale,
and derive amount as `Decimal(qty) * Decimal(rate)`. Hashes use sorted field
names, normalized UTF-8 text, canonical decimal text, and ordered child rows.

### Fresko Commercial Sale (InnoDB, non-submittable)

| Field | Type | Required/nullability | Rule |
|---|---|---|---|
| `naming_series` | Select | required | `SALE-.YYYY.-.` |
| `company` | Link Company | required | ACL checked |
| `container` | Link Fresko Container | required | context |
| `sale_at` | Datetime | required | event time/timezone |
| `raw_movement_at` | Datetime | nullable | source-reported only; not linkage |
| `movement_status` | Select | required | `UNKNOWN`, `NOT_EVIDENCED`, `PARTIAL`, `EVIDENCED` |
| `raw_party_alias` | Data | nullable | null only with `party_state=UNKNOWN` |
| `party_state` | Select | required | `KNOWN`, `UNKNOWN`, `CONTRADICTED` |
| `alias_mapping` | Link Fresko Party Alias Mapping | nullable | approved mapping only |
| `customer` | Link Customer | nullable | approved mapping snapshot; may remain null |
| `alias_resolution` | Select | required | `UNKNOWN`, `REVIEW_PENDING`, `VERIFIED`, `REJECTED`, `SUPERSEDED` |
| `deal` | Link Fresko Deal | nullable | compatibility context only |
| `currency` | Link Currency | required | |
| `status` | Select | required | `DRAFT`, `REVIEW_PENDING`, `VERIFIED`, `APPROVED`, `REJECTED`, `SUPERSEDED`, `CANCELLED` |
| `source_evidence` | Link Fresko Evidence | required | immutable source anchor |
| `source_event_id` | Data | required | raw identifier |
| `source_event_key` | Data | required, unique | server idempotency identity |
| `payload_sha256` | Data | required | server digest |
| `prepared_by`, `prepared_at` | Link User, Datetime | required | maker |
| `verified_by`, `verified_at` | Link User, Datetime | nullable | Accounts |
| `approved_by`, `approved_at` | Link User, Datetime | nullable | Approver |
| `supersedes`, `superseded_by` | Link Fresko Commercial Sale | nullable | correction chain |
| `correction_reason` | Small Text | nullable | required for supersession |
| `as_of_recorded_at` | Datetime | required | capture/as-of |

Unique `(company, source_event_key)`; indexes `(container,sale_at)`,
`(alias_mapping,sale_at)`, `(customer,sale_at)`, `(status,sale_at)`, and
`source_evidence`.

### Fresko Commercial Sale Line (child)

| Field | Type | Required/nullability | Rule |
|---|---|---|---|
| `line_key` | Data | required | unique within Sale |
| `item` | Link Item | required | |
| `container_lot` | Link Fresko Container Lot | nullable | authorized mapping only |
| `raw_lot_text` | Data | nullable | null only with `lot_state=UNKNOWN` |
| `lot_state` | Select | required | `KNOWN`, `UNKNOWN`, `CONTRADICTED` |
| `qty` | Data | nullable | canonical decimal; required if `qty_state=KNOWN` |
| `uom` | Link UOM | required | |
| `qty_state` | Select | required | `KNOWN`, `UNKNOWN`, `CONTRADICTED` |
| `price_state` | Select | required | `UNKNOWN`, `PROPOSED`, `FINAL`, `REJECTED` |
| `rate` | Data | nullable | canonical decimal; only proposed/final |
| `rate_basis` | Select | required | `RATE_ASSERTION`, `PRICE_BUCKET`, `NONE` |
| `amount` | Data | nullable | server-derived Decimal product |
| `bucket_key` | Data | nullable | required for PRICE_BUCKET; unique per Sale |
| `source_line_ref` | Data | nullable | raw source row |
| `evidence` | Link Fresko Evidence | required | line/rate evidence |

Unique `(parent,line_key)` and `(parent,bucket_key)` when bucket non-null;
indexes `(container_lot,price_state)` and `(price_state,source_line_ref)`.
Unknown raw lot/quantity is valid and opens an exception; no fabricated text.

### Fresko Party Alias Mapping (InnoDB, immutable decisions)

Fields: `company` (Link Company, required), `raw_alias` (Data, required),
`normalization_scope` (Select/Data, required: exact company/locale policy),
`normalized_alias` (Data, required, deterministic display key), `proposed_customer`
(Link Customer, required), `evidence` (Link Fresko Evidence, required),
`status` (Select, required: `PROPOSED`, `VERIFIED`, `APPROVED`, `REJECTED`,
`SUPERSEDED`), `proposed_by/at` (User/Datetime, required),
`verified_by/at` (User/Datetime, nullable), `approved_by/at` (User/Datetime,
nullable), `supersedes/superseded_by` (self Link, nullable),
`source_event_key` (Data, required, unique), `payload_sha256` (Data, required),
`reason` (Small Text, nullable), and `as_of_recorded_at` (Datetime, required).
Unique `(company, raw_alias, normalization_scope, proposed_customer)` and
index `(company, normalized_alias, status)`.

### Fresko Sale Outward Allocation (InnoDB)

Fields: `sale` (Link Sale, required), `sale_line_key` (Data, required),
`outward` (Link Fresko Outward, required), `outward_line_key` (Data, required),
`qty` (Data, required canonical decimal), `uom` (Link UOM, required),
`evidence` (Link Fresko Evidence, required), `state` (Select, required:
`PROPOSED`, `APPROVED`, `REJECTED`, `REVERSED`), `prepared_by/at`,
`approved_by/at`, `supersedes`, `source_event_key` (required unique), and
`payload_sha256` (required). Unique `(sale_line_key,outward_line_key)` per
active chain; indexes on `sale`, `outward`, and `state`. It is the only
sale-to-physical allocation truth and supports many-to-many links.

Price buckets may have known quantity/rate and remain `UNALLOCATED` because
source evidence does not map rates to GPs. They do not create allocations.

## 3. Evidence, rates, correction, and workflow

Rates: `UNKNOWN` no evidence, `PROPOSED` maker input, `FINAL` exact evidence
plus approval, `REJECTED` retained history. No spelling similarity, average, or
Deal rate confirms a customer/rate. Raw values are immutable. Every correction
creates a superseding record with reason/evidence/as-of; old records are never
edited/deleted. Conflicting alias remap supersedes and reopens review.

Transitions: `DRAFT -> REVIEW_PENDING` (Salesperson/Trader); `REVIEW_PENDING
-> VERIFIED` (Accounts); `VERIFIED -> APPROVED` or `VERIFIED -> REJECTED`
(Approver); explicit Approver reject may act from `REVIEW_PENDING` when evidence
is insufficient; `APPROVED -> SUPERSEDED` only through atomic correction;
conflict reopens `REVIEW_PENDING`; approval cancellation requires compensation.
The same propose/verify/approve sequence applies to Alias Mapping, rates, and
allocations. System Manager is not a routine approver.

The 92@700 line remains pending until the exact Sohail handwritten photo is
linked and approved; then Decimal arithmetic derives 64,400.

## 4. APIs and permissions

Server-only idempotent APIs: `create_sale`, `propose_alias_mapping`,
`verify_alias_mapping`, `approve_alias_mapping`, `reject_alias_mapping`,
`propose_rate`, `approve_rate`, `supersede_sale`,
`propose_sale_outward_allocation`, `approve_sale_outward_allocation`,
`get_sale_as_of`. Desk writes/deletes/imports are denied.

| Role | Read | Propose | Verify | Approve/reject |
|---|---|---|---|---|
| Fresko Salesperson/Trader | assigned sales/mappings | sale, alias, rate, allocation | no | no |
| Fresko Accounts | all internal records | no | alias/rate/allocation evidence | no |
| Fresko Approver | all internal records | no | no | Sale, Mapping, rate, allocation |
| System Manager | technical/audited | break-glass only | break-glass | not routine |

All report/export/attachment/API paths enforce these ACLs server side. Supplier
roles are denied Customer, aliases, Deals, per-sale rate/amount, Collections,
receivables, margins, and expenses; supplier settlement basis is separate.

## 5. Idempotency, concurrency, exceptions, migration

Canonical decimal payload hashing locks `(company, source_event_key)` first.
Same key/digest returns the record; changed digest raises
`IDEMPOTENCY_PAYLOAD_CONFLICT`. Sale/container locks serialize alias decisions,
approval, supersession, and allocations; version mismatch raises
`STALE_VERSION`; unique race raises `CONCURRENT_STATE_CONFLICT`. No partial
header/child transaction commits.

Deduplicated exceptions `(type,scope,as_of)`: `ALIAS_UNRESOLVED`,
`ALIAS_CONFLICT`, `RATE_UNKNOWN`, `RATE_EVIDENCE_MISSING`,
`PRICE_BUCKET_UNALLOCATED`, `LOT_UNKNOWN`, `PARTY_UNKNOWN`,
`MOVEMENT_TIME_UNKNOWN`, `SALE_WITHOUT_OUTWARD`, `OUTWARD_WITHOUT_SALE`,
`ALLOCATION_OVERDRAW`, `IDEMPOTENCY_PAYLOAD_CONFLICT`,
`CONCURRENT_STATE_CONFLICT`.

Deal remains compatibility context; `dispatched_qty` is never physical truth.
No automatic Deal migration. Shadow replay coexists with Excel and is reversible.
Excluded: accounting/payments, supplier portal, OCR/AI, automatic lot mapping,
and fabricated customer or physical allocation.

## 6. Deterministic tests

1. Plum `GP205537` / `MH-43-X-3299`: one Sale, lines 80 lot42076 + 20
   lot42074, total 100, Decimal rate 825, amount 82,500; two allocation rows
   only when corresponding Outward lines/evidence exist.
2. Different sale/outward dates preserve `sale_at` and each Outward `movement_at`.
3. Grapes 180 accepts buckets 47@1350 and 133@1300, amount 236,350, both
   unallocated when source does not map rates to GPs; no GP allocation is made.
4. 92@700 requires exact photo and role approval; derives 64,400.
5. Null raw alias/lot is accepted only with UNKNOWN state and corresponding
   exception; spelling-only alias remains unresolved.
6. Alias propose -> verify -> approve creates one immutable reusable Mapping;
   conflicting remap supersedes/reopens it.
7. Same idempotency key/digest replays; changed canonical decimal payload fails.
8. Concurrent approval/allocation has one winner and deterministic stale/error;
   no overdraw or duplicate active mapping exists.
9. Supplier requests for Customer, Deal, rates, amounts, Collections,
   receivables, margin, and expenses receive server-side denial.
