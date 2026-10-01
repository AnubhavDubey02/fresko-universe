# Container Cycle to CA Contract

**Status:** Phase 2 product and accounting control contract  
**Effective:** 2026-10-01  
**Implementation base:** `5b8641168c2ddfea5e45e09491bdcdc18a186e60`  
**First delivery slice:** Fresko Field Assertion, Fresko Outward, and Fresko Outward Line

## 1. Purpose and authority

This contract connects the operational life of a produce container to a future
chartered-accountant-ready evidence package:

```text
Container -> Physical Inward -> Physical Outward
Container -> Commercial Deal / Approval
Physical Outward <-> optional Deal context
Collection -> Payment Allocation
Supplier Invoice -> Supplier Remittance -> FX / Bank Charges
Expense -> optional supplier/remittance links
All ledgers -> Exceptions -> Container Settlement -> CA-ready output
```

It defines the boundaries, evidence, reconciliation gates, correction rules, and
ownership of decisions across those stages. It is a control contract, not tax
advice and not permission to create ERPNext stock or accounting entries.

Every CA-facing number must be traceable to one of three things:

1. an as-of source fact;
2. an authorized operational interpretation of that source fact; or
3. a recorded CA/accounting decision.

Those three categories must never be silently conflated. Where this contract
conflicts with an older undated proposal, this dated contract controls Phase 2
implementation. Historical evidence remains historical evidence.

## 2. Current boundary

At the effective date:

- Container, Container Lot, Deal, Approval, Revision, Evidence, Evidence
  Attachment, Evidence Attempt, and Exception runtime foundations exist.
- Fresko Field Assertion, Fresko Outward, Fresko Outward Line, Collection,
  Payment Allocation, supplier invoice, remittance, FX/bank-charge, expense,
  settlement, and CA-package ledgers do not yet exist unless a later exact-head
  handoff records their implementation.
- `Fresko Deal.dispatched_qty` is a legacy compatibility scalar. It is not the
  physical movement ledger and must never be used to derive, backfill, or mutate
  Fresko Outward.
- Existing Excel files remain transitional source evidence for facts not yet
  represented by an implemented Fresko ledger. The app must not claim ownership
  of a ledger merely because it can display imported or provisional values.

## 3. Cut-off and time policy

Every operational report, reconciliation, settlement, and CA package must carry:

- `as_of` date and time;
- reporting period and timezone;
- source event/reported time;
- application capture time;
- verification or authorization time, when present; and
- the immutable record/version identifiers included in the view.

A later verification, classification, price, mapping, or bank result changes a
later snapshot. It does not rewrite what was known at an earlier cut-off and must
not be backdated into an earlier physical movement or settlement.

## 4. Truth layers and ownership

| Layer | Owns | Must not claim |
|---|---|---|
| Source truth | Raw Excel/document/bank/shipping/message values, source identifiers, files, hashes, wording, and reported timestamps | That a value is verified, authorized, cleared, allocated, or posted merely because it was observed |
| Fresko operational truth | Evidence-linked assertions, physical movements, commercial approvals, classifications, exceptions, supersessions, reversals, and reconciliations | Statutory accounting or tax treatment that belongs to ERPNext/CA review |
| ERP/CA accounting truth | Authorized accounting documents, tax treatment, financial posting, statutory books, and sign-off | That operational evidence can be discarded or rewritten after posting |

Rules across all layers:

- Preserve raw source values beside normalized values.
- Keep physical, commercial, collections, payables, expenses, and accounting
  ledgers separate.
- `UNKNOWN`, pending, provisional, disputed, and contradicted are visible states,
  never zero or success.
- Posted source truth is corrected through a superseding assertion or a
  compensating reversal, never an in-place mutation.
- A settlement is an immutable as-of control snapshot, not a rewrite of its
  source ledgers.

## 5. Lifecycle and ledger separation

```text
Evidence / Field Assertions
          |
Container -> Inward ----+----> Physical Outward ----+----> Collection -> Allocation
                        |                            |
                        +----> Deal / Approval ------+

Supplier Invoice -> Remittance -> FX / Bank Charges -> Expenses
          \________________________________________________/
                               |
                           Exceptions
                               |
                      Settlement snapshot
                               |
                         CA-ready output
```

The connecting arrows mean reconciliation relationships, not permission to
collapse records:

- Outward is a physical fact. It may exist without a Deal, buyer, rate, invoice,
  or receipt.
- A Deal is a commercial commitment. It is not proof of physical movement,
  invoicing, receipt, or allocation.
- A Collection is not cleared merely because a payment reference or
  authorization appears in a source.
- An Allocation cannot create or clear a Collection.
- Supplier invoice, remittance, FX difference, bank charge, and expense are
  separate facts and must not be silently netted.
- Exceptions are first-class control records, not hidden report warnings.

## 6. Common evidence envelope

Every material Phase 2 record or assertion must expose, directly or through
immutable links:

- container and lot identity, including original raw lot text and normalized
  mapping when one is authorized;
- source type, source record identifier, source file/message identifier, and
  content hash where applicable;
- source event/reported time, capture time, and verification time;
- raw value, normalized value, UOM, and currency where applicable;
- provenance class: `VERIFIED_SOURCE`, `USER_CONFIRMED`, `PROVISIONAL`,
  `UNRESOLVED`, or `CONTRADICTED`;
- authenticated maker, checker/approver, decision time, and reason;
- superseded assertion or reversal reference when correcting a fact;
- deterministic idempotency identity for repeated source delivery; and
- linked exception and completeness status for unresolved or contradictory data.

Client-supplied actor, server timestamp, hash, verification state, approval, and
supersession metadata are never trusted as authoritative merely because they are
present in a request.

## 7. Stage contract

| Stage | Operational states | Minimum evidence | Release/reconciliation gate | Accounting handoff |
|---|---|---|---|---|
| Container | Draft -> Arrived -> Selling -> Closing -> Closed, with explicit cancellation/reopen paths | Container identity, supplier/partner source, product context, arrival/cut-off evidence | Operational close follows the currently implemented physical/commercial controls and material-exception gate; it does not pretend that future cash/cost ledgers already exist | Container dimension and reporting period; no automatic ledger posting |
| Physical Inward | Asserted -> Review Pending -> Posted; Reversed by compensation | Container, raw/mapped lot, quantity, UOM, event time, source, maker/checker | Quantity and lot identity verified or variance exception remains open | Proposed ERP stock mapping remains CA/ERP decision |
| Field Assertion | Draft -> Review Pending -> Active -> Superseded; Rejected is terminal from review | Field subject, raw and normalized value, source/evidence link, effective time, provenance, maker/checker | Maker cannot activate their own assertion; at most one unambiguous active assertion for a scoped fact and cut-off; conflicts fail closed | Supplies traceable interpretation, never a journal by itself |
| Physical Outward | Draft -> Review Pending -> Posted; Reversed by a compensating Outward | Container, line quantities/UOM, raw/mapped lot, movement time, source identity, maker/checker | Maker cannot self-post; an authorized mapped lot cannot overdraw; missing lot/Deal/buyer/rate opens deterministic exceptions but does not falsify movement | Proposed delivery/stock mapping remains CA/ERP decision |
| Commercial Deal | Proposed -> Approval Required/Auto Approved/Approved/Countered/Rejected -> later commercial states | Proposal source, buyer alias/customer if known, quantity, rate assertion, policy snapshot, Approval/Revision | Approval rules, ATS, revision, and unresolved-buyer controls remain separate from Outward | Proposed SO/DN/SI timing remains CA/business decision |
| Collection | Reported -> Verification Pending -> Cleared/Rejected/Reversed | Bank-account scope, payer/source wording, reference, amount/currency, value date, bank-clearing evidence | Only independent bank evidence may establish Cleared | Cleared cash schedule; no automatic Payment Entry |
| Payment Allocation | Proposed -> Approved -> Applied/Reversed | Cleared Collection, target receivable/deal/invoice, amount, approver, rationale | Total applied cannot exceed cleared unallocated amount; reversal is append-only | Allocation schedule and proposed ERP mapping |
| Supplier Invoice | Captured -> Verified/Disputed -> Approved/Reversed | Original invoice, supplier, currency, line purpose, classification, approval | Duplicate and source-integrity checks; unresolved dispute remains visible | Payables schedule; no automatic Purchase Invoice |
| Supplier Remittance / FX / Bank Charges | Instructed -> Bank Pending -> Settled/Failed/Reversed | Payment instruction, supplier-currency amount, bank debit, rate source/date, charge evidence | Bank settlement and FX/charge components reconcile independently | Separate remittance, FX, and bank-charge schedules |
| Expense | Reported -> Verified -> Approved -> Paid/Reversed | Original evidence, payee, purpose, class, amount/currency, approval, payment evidence | Classification and payment status independently verified | Expense schedule with CA-owned account/tax mapping |
| Exception | Open -> In Progress -> Resolved/Waived/Cancelled | Deterministic type/key, affected record, evidence, owner, status, decision/reason | Resolution or waiver preserves history and authorization | Open/closed exception register included in every relevant package |
| Container Settlement | Draft -> Ops Reviewed -> Accounts Reviewed -> CA Ready -> Finalized | Frozen record IDs, as-of cut-off, all schedules, variances, reviewers, CA decisions | No hidden provisional amount; every material variance resolved, waived, or explicitly open | Immutable CA-ready evidence package; final posting remains external until authorized |

These state names are the intended control language. Detailed Frappe transitions
may add technical failure/retry states but must not weaken the gates above.

## 8. Phase 2A physical contract

### 8.1 Fresko Field Assertion

- Represents one source-backed or authorized claim about a scoped field.
- Preserves raw and normalized values, provenance, effective time, source time,
  and evidence linkage.
- Becomes immutable after activation/verification.
- A correction creates a new assertion linked through `supersedes`; it never
  edits or deletes the prior assertion.
- Concurrent corrections must not leave two ambiguous active assertions for the
  same scope and cut-off.

### 8.2 Fresko Outward

- Represents a physical movement header for one Container and event.
- Posting must not require a Deal, Customer/buyer, or rate.
- It owns movement provenance, posting/reversal state, maker/checker controls,
  source identity, and deterministic replay behavior.
- A posted Outward is immutable. A quantity, lot, or provenance correction uses
  a compensating reversal plus, when required, a replacement Outward.
- Replaying the same source identity and same payload is idempotent; a changed
  payload under that identity fails closed and records a durable conflict.

### 8.3 Fresko Outward Line

- Is a child row of Fresko Outward.
- Preserves raw lot text even when a Batch or Container Lot mapping is absent.
- Carries quantity and UOM as physical facts.
- May link to a Deal or authorized rate/buyer assertion only as optional
  reconciliation context. Those links cannot be required for posting and cannot
  become the physical source of truth.

### 8.4 Deterministic exceptions

Posting truthful physical movement is allowed while commercial context is
missing. The posting opens one exception per deterministic scope, including:

- `OUTWARD_UNPRICED` when no authorized rate assertion applies;
- `OUTWARD_WITHOUT_DEAL` when no Deal is linked or matched;
- `BUYER_UNRESOLVED` when buyer identity is required for a later commercial gate
  but is not yet mapped;
- `LOT_UNRESOLVED` when raw lot text has no authorized physical mapping; and
- `PHYSICAL_VARIANCE` when inward/outward/reversal quantities do not reconcile.

Missing values remain null/unknown. No exception handler may synthesize a zero
rate, buyer, Deal, inward quantity, or financial posting.

No-overdraw is enforced against an authorized mapped lot. A source-backed known
quantity whose lot mapping is unresolved posts into an explicit unmapped physical
bucket, opens `LOT_UNRESOLVED`, is excluded from mapped-lot ATS/residual math, and
blocks lot-level physical reconciliation until it is mapped or otherwise
explicitly dispositioned.

## 9. Reconciliation model

Each layer reconciles independently before the Container can advance:

1. **Physical:** inward by lot minus posted Outward plus compensating reversals
   equals the as-of physical balance, or a visible variance exception exists.
2. **Commercial:** Deal commitments and approved rates reconcile to optional
   Outward links without replacing physical quantities or inferring movement.
3. **Collections:** reported, verification-pending, cleared, reversed, allocated,
   and unallocated amounts remain separate.
4. **Payables and costs:** supplier invoices, remittances, FX, bank charges, and
   expenses remain separately traceable before any management total is shown.
5. **Settlement:** the frozen as-of schedules, their differences, open
   exceptions, waivers, and CA decisions form one reproducible snapshot.

Unknown rate, buyer, cash status, or financial classification is excluded from
cleared cash, allocation, realized revenue/cost, and final reconciled monetary
totals. A source-backed known physical quantity remains in the physical schedule
even when its rate, buyer, or lot mapping is unknown. An unknown lot mapping is
shown in the unmapped physical bucket and blocks lot-level reconciliation. All
unknown or provisional attributes remain visible in a separate unresolved
schedule. There are no manual plug values or silent cross-ledger netting.

## 10. Required release gates

| Gate | Required before passing |
|---|---|
| Physical reconciliation | Lot-level inward, Outward, reversals, and variances explicitly reconcile or remain owned open exceptions |
| Commercial reconciliation | Deal commitments are shown separately from physical movements; no rate, buyer, or movement is inferred |
| Cash clearance | Independent bank evidence confirms cleared status; authorization-pending items are excluded |
| Allocation | Allocation total does not exceed cleared, unallocated funds and every reversal is traceable |
| Payable/cost review | Supplier invoice, remittance, FX, bank charge, and expense remain separately reconcilable |
| Settlement | Cut-off is frozen; every material variance has an owner and status; no hidden provisional amount exists |
| CA-ready | Evidence register, mappings, schedules, exceptions, decisions, reviewers, and cut-off metadata are complete |

No package may be labelled fully reconciled while a material unresolved
exception remains. An authorized waiver may permit progression only when the
waiver, owner, reason, materiality basis, and affected totals are explicit.

## 11. CA-ready package

A CA-ready package is an immutable dated export containing:

- Container and master-data snapshot;
- source evidence and Field Assertion register;
- physical inward, Outward, reversal, and variance schedules;
- Deal/Approval/Revision and buyer-mapping schedule;
- Collection, clearance, allocation, and reversal schedules;
- supplier invoice, remittance, FX, bank-charge, and expense schedules;
- reconciliation results and open/resolved/waived exception register;
- currency, UOM, cut-off, and effective-date rules used;
- proposed ERP mappings clearly marked `CA_DECISION_REQUIRED` where unresolved;
- maker/checker/approver and change/supersession/reversal audit trail; and
- CA decision and sign-off log.

The package does not itself create a Purchase Receipt, Stock Entry, Delivery
Note, Sales Invoice, Payment Entry, Journal Entry, GST return, tax treatment, or
statutory book entry.

## 12. Roles and segregation of duties

- **Operations maker:** captures evidence, assertions, and Draft movements.
- **Operations checker/approver:** verifies evidence and posts movement; cannot
  post their own Phase 2A movement.
- **Accounts:** verifies collections, costs, allocations, cut-off, and
  reconciliation; does not rewrite physical facts.
- **System Manager:** maintains technical access and has an audited break-glass
  path, not an invisible business override.
- **CA/accounting authority:** owns account, document, tax, FX-accounting,
  materiality, cut-off, and statutory decisions.

Every waiver, reversal, break-glass action, and finalization records the actor,
role, time, reason, affected facts, and evidence.

## 13. Time-bounded acceptance cases

These examples are historical or point-in-time cases. They are not claims of
today's live balances and are not implemented merely by appearing here.

- **447 Plum crates:** at the historical physical-movement cut-off, record 447
  Outward with rate null and one `OUTWARD_UNPRICED` exception. A later authorized
  rate, if evidenced, is a later Field Assertion and cannot rewrite the earlier
  movement or earlier snapshot.
- **180 Grapes crates:** preserve the historical unpriced Outward state. Later
  authorized rates exist for the final 180, but the repository does not yet
  contain enough canonical evidence here to invent the rate, source, or effective
  time. When supplied, represent them as later source-backed assertions.
- **92 crates at INR 700:** INR 64,400 is provisional unless and until the rate,
  quantity, and scope are authorized. Preserve `Balance Sale`,
  `BALANCE / UNMAPPED`, and `NOT AVAILABLE` as source strings where applicable.
- **3,060 versus 3,056:** preserve declared shipping quantity 3,060 and operating
  inward 3,056 as distinct facts. Open a four-unit `PHYSICAL_VARIANCE` and block
  reconciliation until resolved or explicitly waived.
- **INR 101:** the current authorized operational classification is
  labour-related at its classification/evidence time. Preserve its earlier
  ambiguity as historical evidence, but exclude INR 101 from customer/Sohail
  collections, receipts, cleared cash, and allocations. This classification
  does not establish that the amount was paid or cleared, that it was a supplier
  remittance, or that a labour expense/payable account is final. Without separate
  payment evidence its settlement state remains `UNKNOWN` or `PENDING`; final
  expense/payable account and tax treatment remain CA decisions.
- **INR 350,000 `Authorization InProcess`:** pending at that evidence cut-off and
  excluded from cleared collections and allocation. A later clearance may be
  recognized only from later source evidence as a later event; it is not inferred
  or backdated.

## 14. Phase gates

### Phase 2A — physical truth and assertions

Deliver only Fresko Field Assertion, Fresko Outward, and Fresko Outward Line,
their permissions, exceptions, reports/snapshot additions, migrations, and
tests. Prove independence from Deal/buyer/rate, deterministic unpriced handling,
append-only corrections, idempotent replay, concurrency safety, maker-checker,
and the legacy `dispatched_qty` boundary.

### Phase 2B — collections and allocations

Add Collection and Payment Allocation ledgers with independent bank clearance,
reversal, over-allocation protection, and payer/customer ambiguity controls. The
INR 101 classification and INR 350,000 authorization cases are mandatory
boundaries.

### Phase 2C — supplier and cost cycle

Add Supplier Invoice, Remittance, FX, Bank Charge, and Expense schedules without
silent netting or inferred classifications.

### Phase 2D — settlement and CA package

Add frozen Container Settlement snapshots, cross-ledger reconciliations, CA
decision workflow, and reproducible CA-ready export.

Each phase requires exact-head smoke and pinned Frappe/ERPNext/MariaDB Bench
evidence. A green ancestor or a fixture validator is not proof of a later runtime
slice.

## 15. Decisions reserved for CA/business authorization

Do not hard-code these without recorded authority:

- legal entity and supplier/customer/partner treatment;
- Purchase Receipt versus Stock Entry for inward;
- Sales Order, Delivery Note, Sales Invoice, and GST/tax timing;
- payment-clearance definition and bank-reconciliation policy;
- supplier-invoice duplicate, dispute, and approval policy;
- FX rate source, translation date, and realized/unrealized treatment;
- bank-charge, withholding, and other tax treatment;
- container/project/cost-centre dimension and allocation basis;
- settlement materiality threshold, waiver authority, and sign-off format; and
- retention, privacy, and external-sharing rules for CA packages.

Until decided, the relevant field or mapping remains `UNKNOWN`, `PENDING`, or
`CA_DECISION_REQUIRED` and is visible in the exception/decision register.

## 16. Explicit non-goals

This contract and the first Phase 2A slice do not authorize:

- automatic ERPNext stock, general-ledger, invoice, Payment Entry, tax, or
  journal posting;
- live WhatsApp ingestion, AI/OCR truth, website, partner portal, Chatwoot,
  Activepieces, or Metabase work;
- inferred prices, receipts, expense classes, party mappings, tax treatment, or
  FX values;
- conversion of historical Excel rows into new physical movements without
  source identity, cut-off, review, and idempotency controls;
- mutation or deletion of posted evidence, assertions, movements, allocations,
  or settlements; or
- a claim that green application tests replace CA review or statutory books.

## 17. Implementation traceability

Every Phase 2 implementation PR must identify:

1. the contract clauses it implements;
2. the DocTypes, APIs, permissions, migrations, and reports changed;
3. the smoke and Bench tests that prove each implemented invariant;
4. the exact commit SHA and GitHub Actions run;
5. remaining `UNKNOWN`, `PENDING`, and `CA_DECISION_REQUIRED` items; and
6. confirmation that no predecessor PR was merged, retargeted, or closed without
   repository-owner authorization.
