# Commercial Sale Runtime and Alias Architecture

**Status:** Implementation runtime documentation for the Commercial Sale slice
**Effective:** 2026-10-03
**Scope:** Server-side commercial event ledger, reusable alias mapping, and physical Outward allocation.

## 1. DocTypes, Numerical Integrity, and Immutability

Four DocTypes represent the commercial boundary:
1. `Fresko Commercial Sale` (InnoDB, non-submittable header)
2. `Fresko Commercial Sale Line` (child table)
3. `Fresko Party Alias Mapping` (InnoDB, reusable approved customer alias)
4. `Fresko Sale Outward Allocation` (InnoDB, explicit many-to-many commercial-to-physical link)

Numerical values (`qty`, `rate`, `amount`) are stored as Frappe `Data` plain decimal text (never binary floats). Services parse values using `Decimal` with fixed scale (quantity 6 places, rates/currency 2 places) and derive amounts strictly as `Decimal(qty) * Decimal(rate)`.
Each root record enforces immutable source identity via `source_payload`, `payload_sha256`, and `source_event_key`. Edits to source fields are forbidden; operational workflow changes append exactly one entry to `decision_history` and bump `version`.

## 2. Alias Mapping and Scope-Key Justification

- Raw party aliases are preserved verbatim (`raw_party_alias` / `raw_alias`), never overwritten or guessed from fuzzy spelling.
- Historical `(company, raw_alias, normalization_scope, proposed_customer)` tuples are intentionally non-unique; rejected and superseded decisions remain available.
- Active uniqueness is guaranteed by `active_alias_key = sha256(company, raw_alias, normalization_scope)`: exactly one approved mapping exists per raw alias in scope.
- Non-unique historical alias tuples are justified because remapping back to a prior customer reuses that tuple while deactivating the intermediate mapping (`active_alias_key=None`).
- Approving an alias conflict supersedes the prior mapping, reopens affected active Sales back to `REVIEW_PENDING`, clears customer snapshots, and opens `ALIAS_CONFLICT` exceptions.

## 3. Segregation of Duties and Role Workflow

Workflow transitions enforce strict separation of duties across distinct users:
- **Maker** (`Fresko Salesperson`; optional separately configured `Fresko Trader` is recognized): creates/submits Sale, proposes alias mappings, proposes rates, and proposes allocations. The 2026-10-04 pilot audit found that Trader recognition alone does not provide Evidence access or native Workspace/DocType permissions. Salesperson remains the supported installed maker capability; Trader-only workflow support is deferred rather than expanding authorization in this safety repair.
- **Verifier** (`Fresko Accounts`): verifies evidence and commercial assertions. Must not be the maker.
- **Approver** (`Fresko Approver`): approves or rejects. Must not be the maker or verifier.
- `System Manager`: technical visibility and reconciliation refresh; no routine business approval or break-glass mutation API is implemented.
Rate states strictly distinguish `PROPOSED` (maker input) from server-projected `FINAL` (active only upon Sale approval).

## 4. Locking Hierarchy and Atomic Concurrency

To prevent deadlocks and race conditions, transactions acquire pessimistic `FOR UPDATE` locks in fixed hierarchical order:
1. `tabCompany`
2. Lexicographically sorted `tabFresko Container` rows
3. Header documents (`Fresko Commercial Sale`, `Fresko Outward`)
4. Decision and allocation rows

Concurrent edits check `expected_version` raising `STALE_VERSION` on mismatch. Idempotent replays return existing records; altered payloads raise `IDEMPOTENCY_PAYLOAD_CONFLICT`. Unique races recover or raise `CONCURRENT_STATE_CONFLICT`.

Existing-record Commercial mutations dispatched by an HTTP request require an
explicit positive integer `expected_version` (integer or canonical ASCII decimal
string). Missing/blank tokens fail with `EXPECTED_VERSION_REQUIRED`; malformed
tokens fail with `INVALID_EXPECTED_VERSION`. Role/Supplier checks precede this
validation. A well-formed stale token still fails with `STALE_VERSION` under the
existing locks. All 15 versioned Sale/rate/alias/allocation facades apply this
boundary. New-record creation retains source-event idempotency.

Trusted direct Python calls outside an HTTP request retain the existing optional
`None` compatibility used by Bench fixtures and internal workflows. A supplied
blank value is never normalized to `None`. The request boundary uses the pinned
framework's server-established `frappe.local.request`, not client metadata.

## 5. Many-to-Many Allocations, Caps, and Reversals

- Commercial Sale lines link to physical Outward lines via `Fresko Sale Outward Allocation`.
- Active allocation chains enforce uniqueness on `active_allocation_key = sha256(sale, sale_line_key, outward, outward_line_key)`.
- Approval enforces caps on both sides: cumulative allocated quantity cannot exceed Sale line quantity or Outward line quantity (`ALLOCATION_OVERDRAW`).
- Outward physical validity requires an unreversed, `Posted` physical `OUTWARD`. If the physical Outward is reversed, the allocation effective state is projected as `PHYSICAL_REVERSED`.
- Sale corrections or alias remaps atomically reverse active allocations with compensation records (`REVERSED` state) and require compensation evidence.
- Price buckets (`PRICE_BUCKET`) and unmapped lots never form physical allocations; they remain unallocated with dedicated open exceptions.

## 6. Deterministic Projections and Access Boundaries

- `get_sale_as_of`, `get_container_reconciliation`, and `get_outward_reconciliation` project point-in-time truth from immutable source payloads and `decision_history` snapshots without mutating stored state.
- `get_sale_as_of` is explicitly historical: `projection_mode=HISTORICAL` and
  `version_at_cutoff` name the selected audit event; no `current_version` token
  is exposed. Existing audit snapshots are unchanged, including old rows.
- `get_sale_current` returns `projection_mode=LIVE`, actual locked current state
  and `current_version` for optimistic mutation. Its server cutoff is captured
  after current document locks. `get_container_reconciliation` is Live when the
  cutoff is omitted/blank, and Historical for any explicit cutoff, including a
  future date. The Container read captures one cutoff after parent locks.
- Workspace blank As Of means Live. An explicit cutoff makes the Workspace
  read-only: existing-record actions, preparation and open-dialog submissions are
  guarded, and current alias/allocation review queues are withheld. Historical
  audit versions are descriptive; they are not presented as mutation tokens.
  Live reloads replace selected Sale state/token with the newly accepted row.
- Reconciliation classifies `commercially_sold_qty`, `physically_allocated_qty`, `sold_not_physically_allocated_qty`, `priced_qty`, `unpriced_qty`, and `physical_qty` deterministically.
- All commercial APIs and DocType reads enforce server-side ACLs. Any role with "supplier" in its name is completely denied implemented Commercial Sale, Deal, Customer, alias, rate and amount paths, including source Evidence/Outward reads. Receivables, margins, Collections and expenses remain future ledgers.
- Existing internal roles have read access restricted: makers read assigned records; Accounts, Approver, and System Manager have internal visibility.

## Verification and remaining boundaries

Exact-head Smoke and pinned Bench are required before acceptance. Registered
proofs exercise Phase 1 plus a separate exact merged-main baseline upgrade and
idempotent second migrate, preserving selected legacy fields and creating zero
commercial rows. No implementation or proof converts historical Deals to Sales.

Read projections expose source Evidence/event identity; approved photo semantics
remain human review. For 92 at INR700, a Photo Evidence record, matching readable
File and separate role approval are required; fixture photos are synthetic.
Failed idempotency/overdraw calls roll back and return errors, without an
independently durable failure Exception. Persisted structural Exceptions describe
accepted records and refresh through controlled reconciliation. Periodic Integrity
Seal coverage remains its prior physical/assertion scope; commercial audit is
protected by the controlled controllers, not a new database-level integrity seal.
No accounting, Collection/Payment Allocation, UI, WhatsApp, or deployment is added.
