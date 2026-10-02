# Canonical business decisions — 2026-10-02

**Status:** Locked by the repository owner for forward implementation

**Scope:** Operational classification of the INR 101, INR 350,000, and
92-at-INR-700 cases; buyer-alias approval; and future supplier-facing access.

## 1. Authority and time boundary

These are later authorized business decisions. They supersede conflicting
current-state interpretations in documents dated 2026-10-01 or earlier, but do
not erase the older source wording or what was known at an earlier cut-off.

The decisions are operational authority for product design and acceptance
tests. They are not substitutes for attaching the transaction, bank, photo,
contract, or accounting evidence to production records. Source facts,
user-confirmed interpretation, independent bank clearance, and CA/statutory
treatment remain separate.

## 2. Locked transaction and pricing classifications

### BD-101 — INR 101 is a labour payment

- The INR 101 case discussed in the real-data review is an amount **paid for
  labour**. It is not a customer receipt and is not part of Sohail/customer
  collections.
- It must be excluded from collection totals, customer allocation, receivables,
  and cleared-customer-cash reporting.
- Capture it as a labour-related outflow/expense-payment classification with
  `USER_CONFIRMED` provenance until the exact payment evidence is attached.
- Final expense account, payee, tax treatment, and bank reconciliation remain
  evidence/Accounts/CA decisions; they must not be inferred from the amount.
- Any conflicting workbook or message interpretation remains preserved as
  historical source evidence and is marked superseded or contradicted, not
  deleted.

### BD-350 — INR 350,000 was received

- The INR 350,000 case discussed in the real-data review is now classified as
  **received**. It must no longer be presented as currently pending merely
  because an earlier source showed `Authorization InProcess`.
- Production capture must bind this decision to the exact transaction identity.
  The reviewed audited workbook associates the case with reference
  `625819349281`; that reference must be verified when the Collection ledger is
  implemented.
- `received` is an operational classification. Independent bank evidence still
  controls a separate `Cleared` state, and allocation to a customer/container
  requires its own authorized record.
- The earlier pending state remains reproducible at its earlier evidence
  cut-off. The received state is a later state/assertion, not a backdated edit.

### BD-92-700 — source is Sohail's handwritten working

- The business context for `92 × INR 700 = INR 64,400` is Sohail's handwritten
  manual working supplied through photos, including the price.
- The original photo, raw handwriting/transcription, quantity, rate, source
  message/photo identity, and source time must be preserved.
- INR 64,400 is deterministic arithmetic, not independent evidence of a sale or
  payment.
- Until the exact photo is linked and the rate is approved through the role
  workflow, use `SOURCE_IDENTIFIED / VERIFICATION_PENDING`; do not silently map
  the 92 crates to a buyer, lot, gatepass, payment, or final settlement.
- After evidence linkage and approval, record the price as a later commercial
  assertion. Do not mutate the earlier physical Outward.

## 3. Locked buyer-alias approval workflow

Buyer/customer alias mapping is role based:

1. **Fresko Salesperson / Trader** proposes a mapping from the immutable raw
   party string to a Customer.
2. **Fresko Accounts** verifies the mapping against commercial/payment evidence.
3. **Fresko Approver** approves or rejects first-time and conflicting mappings.

Rules:

- preserve the raw source party name forever;
- never auto-confirm a mapping from spelling similarity alone;
- an approved unambiguous alias may be suggested/reused later;
- a conflicting remap reopens review and creates a superseding decision;
- posted financial attribution is never silently rewritten;
- System Manager configures access and has an audited break-glass path, but is
  not the routine business approver; and
- unresolved mappings remain `UNKNOWN` or `REVIEW_PENDING` and cannot reach a
  final customer reconciliation state.

## 4. Locked supplier-facing access boundary

A future external supplier role, provisionally named **Fresko Supplier Viewer**,
must use a purpose-built portal/API. It must not receive Fresko Desk access to
internal Deal, Collection, Customer, receivable, margin, or expense records.

### Supplier may see

- only containers/shipments belonging to that authenticated supplier;
- supplier invoice, remittance, balance, quantity, quality, shortage, claim,
  and contractually authorized settlement information; and
- only a published, approved, versioned supplier statement.

### Supplier must not see

- customer identity or buyer aliases;
- per-sale rate or per-sale amount;
- internal collections, allocations, receivables, margins, or profit; or
- internal actual/provisional expense detail unless expressly included in the
  supplier contract and approved publication policy.

### Integrity rule

Internal actual sales must never be changed, overwritten, or relabelled to
produce a supplier-facing number. If a supplier contract uses a different
calculation basis, store it separately as **Supplier Settlement Basis/Value**,
with formula/basis, contract reference, source values, preparer, verifier,
approver, effective time, and publication version. Do not call it `Sales` unless
the contract defines it as sales. Contractual/legal disclosure requirements
always control what may be withheld or presented.

Publication workflow:

1. Fresko Accounts prepares the statement.
2. Trader verifies the commercial/container context.
3. Fresko Approver authorizes publication.
4. Supplier sees only the authorized published version.

All row and field restrictions must be enforced server side. Hiding a field in
the browser is not an access-control boundary. Export, API, report, attachment,
and direct-document access must obey the same policy and be audited.

## 5. Implementation consequence and next best slice

This decision record changes no runtime behavior by itself. Supplier portal work
remains after the internal ledgers it depends on.

The next best implementation step is a **real-data shadow-replay gate** before
adding more independent features:

1. define versioned source fixtures/expected totals for the Plum and Grapes
   cut-offs without committing confidential originals unless authorized;
2. add the missing P0 fact boundaries needed by that replay: declared versus
   operating quantity, commercial event header/lines, raw gatepass/vehicle/party,
   quantity-bearing price assertions, and as-of semantics;
3. implement role-based alias proposal/verification/approval;
4. then implement Collection and Payment Allocation using transaction identity,
   raw status, received/cleared separation, and the locked INR 101/350,000 cases;
5. run a shadow pilot while Excel remains the operational source of truth; and
6. begin supplier portal work only after Supplier Invoice/Remittance/Settlement
   truth and server-side isolation tests exist.

Minimum acceptance assertions for these locked decisions:

- INR 101 contributes zero to customer collections and is shown as a
  labour-related outflow with its provenance/state;
- INR 350,000 is shown as received, with earlier pending history preserved and
  bank-cleared/allocation states kept separate;
- 92 at INR 700 appears only when the exact Sohail photo evidence is linked and
  the role approval is recorded;
- alias approval requires propose -> verify -> approve and preserves the raw
  alias plus supersession history; and
- a supplier user receives a server-side denial for every internal per-sale
  amount/rate, Customer, Collection, receivable, margin, and internal Deal path.

