# Money reconciliation runtime

## Scope and operating boundary

The money ledger is an internal, evidence-backed operational record for
Collections, Payment Allocations, Receivable Adjustments, and Adjustment
Applications. Its calculations use decimal text and preserve unknown values;
it does not execute or post bank payments, create ERPNext accounting/GL
entries, decide statutory or CA treatment, ingest provider feeds, or publish
supplier statements. The shadow workflow does not replace the operational
source of truth. Supplier portal work remains out of scope.

Only Fresko Accounts and Fresko Approver can read the internal money ledger.
Supplier roles are denied even when combined with an internal role. Accounts
prepares and verifies; the preparer cannot verify their own record. Fresko
Approver approves, rejects, and reverses, and must differ from both preparer
and verifier. A salesperson alone cannot access the pooled money records.
Desk permissions are backed by server-side permission hooks and service guards.
Direct document writes, deletes, and renames are rejected; approved operations
run through controlled methods with versioned audit history.

## Runtime API

The whitelisted read methods in `fresko_universe.money` are:

- `get_collection_position(name, as_of=None)`
- `get_sale_receivable(sale, as_of=None)`
- `get_container_receivable(container, as_of=None)`
- `get_customer_receivable(customer, company, as_of=None)`
- `get_unallocated_collections(company, as_of=None)`
- `get_bank_pending_collections(company, as_of=None)`
- `get_open_money_exceptions(company)`

These return deterministic projections at the requested site-local cutoff.
Amounts are decimal strings, grouped by currency; incomplete pricing and
unknown amounts remain explicitly unknown. Projections are views of captured
and approved records, not evidence that a receipt is independently cleared or
that a customer settlement is final. One `as_of` cutoff is used for effective
and recorded time; projections identify captured-subset coverage and must not
be presented as a complete historical balance.
`get_open_money_exceptions` is a current-state list of open money exceptions;
exception status history is not projected as of a past cutoff.

The whitelisted write workflow in `fresko_universe.money` is:

1. Accounts calls `create_collection`, then `submit_collection`.
2. A different Accounts user calls `verify_collection`.
3. A different Fresko Approver calls `approve_collection` or `reject_collection`.
4. Accounts may propose allocations or receivable adjustments/applications;
   Accounts verifies them and a distinct Approver approves or rejects them.
5. An Approver may reverse an approved record with a reason and supporting
   Evidence. Corrections create superseding records and preserve prior source
   values and decisions.

Mutations use `expected_version` where the method accepts it. Reusing an
idempotency key with the same canonical source payload returns the prior
record; reusing it with different content is rejected. Collection transaction
identity and allocation/application capacity are checked under database locks.
Allocations cannot exceed a cleared eligible receipt, a sale's approved gross
commercial value, or an adjustment's remaining capacity. Future-effective
receipts are not available for allocation before their effective time.
Container parking consumes receipt capacity without reducing any sale or
customer receivable; there is no implicit FIFO or proportional split. An
approved non-cash receivable adjustment requires a classified adjustment, an
explicit debt-discharge agreement reference, and supporting Evidence. Applying
it creates no cash and does not imply bank clearance.

## Receipt and source evidence policy

Keep source statements, interpretations, operational receipt classification,
bank clearance, and allocation separate. Bind a source record to its supporting
Fresko Evidence. The service stores an evidence snapshot, including available
file identity and byte hash, with the source record and each decision that cites
Evidence. Referenced money evidence files cannot be modified or deleted through
the application. A snapshot establishes what the application observed; it does
not independently establish completeness or bank truth.

The recorded owner decisions constrain treatment of the referenced cases:

- INR 101 is a labour payment/outflow, not a customer receipt. Exclude it from
  customer collections, allocations, receivables, and cleared-customer-cash
  totals. Expense account, payee, tax, and bank treatment remain evidence and
  Accounts/CA decisions.
- The owner-stated INR 350,000 receipt remains
  `PENDING_EVIDENCE_BINDING` until exact bank Evidence is attached. Operational
  `received`, bank `Cleared`, and customer/container allocation are distinct
  states. Do not backdate the later receipt assertion into the earlier pending
  view.
- The possible 92-at-INR-700 handwritten-photo context remains pending until
  the exact photo is linked and the rate approved. INR 64,400 arithmetic does
  not prove a sale or payment.

Bank receipt / RTGS evidence can support a `RECEIVED` operational
classification, but `BANK_CLEARED` remains a separate approved state requiring
bank account, reference, amount, and bound source Evidence. A pending bank
receipt may be captured and an allocation proposed for review, but it cannot be
approved or consume funds until eligible. A cash declaration can be received
and approved for allocation without a bank deposit; a slip is optional
supporting Evidence. A later bank deposit for cash is movement evidence, not a
second receipt or a conversion of the original channel. Unknown amounts or
directions, outflows, and internal transfers never become customer receipts.

Collection correction uses `supersede_collection` with a new source event,
reason, source Evidence, and explicit changed values. The accepted record stays
active until the successor is approved; then compensation/reversal and
transaction-identity transfer are atomic. A pending or contradictory source
proposal cannot silently rewrite accepted receipt truth. Payment allocation
reversal releases allocation capacity; it is not a refund or outgoing ERP
posting.

These cases are policy boundaries, not seeded ledger facts. Do not put original
bank references, customer-identifying data, source messages, workbook rows, or
source photos in Git. Keep any authorized raw source in its controlled Evidence
store; repository examples and migration sentinels must be synthetic and
non-resolving. Preserve raw source values in immutable payloads; normalized
keys are for matching and idempotency, not replacements for source identity.

## Migration proof boundary

The registered proof `money_reconciliation_ledger` is defined in
`scripts/prove_money_upgrade.py`. Its exact merged-commercial baseline is
`b140b800b021c4317931e37a723a140740b2fc4c`. The baseline proof reuses existing
synthetic Phase 1 fixtures without adding rows to the legacy Deal or Container
fixtures. The current-main seed uses synthetic source/history sentinels and
captures selected commercial and physical source columns before migration.
The first and second migrate stages require zero new rows in all four money
DocTypes and preserve the captured legacy values. These sentinels test schema
preservation only; they are not financial acceptance, receipt evidence, or
operating records. The proof's existence and offline validation do not establish
a successful pinned Bench upgrade; that requires the migration harness to run
against the declared exact baseline and candidate.

## Authority

Business classifications and supplier boundary follow
`docs/CANONICAL_BUSINESS_DECISIONS_2026-10-02.md` and `docs/DECISIONS.md`.
This runtime guide describes the implemented internal slice and does not
authorize live ingestion, bank integration, payment execution, accounting
posting, or supplier publication.
