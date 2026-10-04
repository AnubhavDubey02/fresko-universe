# Pilot safety closure and provider Evidence contract

Effective 2026-10-04. Bounded Implementation 01, based on merged main
`335974c6562dbb91b56ba0df0f3457483e3fb1da` and the
[Fresko Real Operations Implementation Dossier](https://docs.google.com/document/d/11CAdqUIMqDOMHaw-mn2br9oPz9vbVXcThoDh4mB3rbk/edit).

## Fully Reconciled materiality

`fresko_core/services/close_policy.py` owns the current Exception vocabulary and
materiality classification. Container validation checks current database state;
it never refreshes reconciliation or edits Physical, Commercial or Money rows.
Only **Open** and **In Progress** exceptions block. Resolved, Waived and Cancelled
rows retain their existing workflow meaning; this repair adds no waiver authority.

| Classification | Types | Closing behavior |
| --- | --- | --- |
| Existing material controls | BUYER_UNRESOLVED, DUPLICATE_MESSAGE, OVERSELL_OVERRIDE, STOCK_SHORTFALL, RATE_FLOOR_BREACH, RATE_POLICY_MISSING, OUTWARD_UNPRICED, OUTWARD_WITHOUT_DEAL, LOT_UNRESOLVED, DUPLICATE_GATEPASS, PHYSICAL_VARIANCE, DATA_INTEGRITY | Block for the affected Container at every severity. No existing control is weakened. |
| Commercial structural uncertainty | ALIAS_UNRESOLVED, ALIAS_CONFLICT, RATE_UNKNOWN, RATE_EVIDENCE_MISSING, PRICE_BUCKET_UNALLOCATED, LOT_UNKNOWN, PARTY_UNKNOWN, MOVEMENT_TIME_UNKNOWN, SALE_WITHOUT_OUTWARD, OUTWARD_WITHOUT_SALE, ALLOCATION_OVERDRAW | Block for the affected Container at every severity; missing identity, price, quantity/movement mapping or allocation integrity cannot become reconciliation success. |
| Contextual operational issues | OTHER, IDEMPOTENCY_PAYLOAD_CONFLICT, CONCURRENT_STATE_CONFLICT | Block when explicitly Material or Critical. Info, Low, Medium and High alone do not establish financial materiality. Rejected attempts are not fabricated into Exceptions. |
| Receipt issues | MONEY_UNALLOCATED, BANK_PENDING, RECEIPT_AMOUNT_UNKNOWN, RECEIPT_DIRECTION_UNKNOWN | Block only when preserved receipt context or a relevant active proposal identifies this Container, under the rules below. |

Explicit Material/Critical severity also blocks future scoped exception types;
regression coverage requires classification of every current DocType enum.

## Money attribution

Money Exceptions are Company/Collection scoped. A company match, payer spelling,
matching amount/date or mutable live Evidence link does not establish Container
attribution. The gate uses the immutable Collection `evidence_snapshot.container`
recorded at capture, with matching Collection and Exception Company.

For BANK_PENDING and receipt amount/direction defects, explicit Payment Allocation
Container links in DRAFT, REVIEW_PENDING, VERIFIED or APPROVED also establish
current relevance. REJECTED, REVERSED and SUPERSEDED proposals do not. A receipt
can identify several Containers; no first-allocation rule is used.

For MONEY_UNALLOCATED, allocation to one Sale or Container does **not** assign the
receipt's remainder there. Only explicit direct Exception scope or the preserved
receipt source Container attributes the residual. Pooled/unscoped receipts remain
unresolved company work, without inventing Container ownership.

The gate acquires Company before Container, then uses current locking reads.
Validation returns only a generic close-denied error, without revealing restricted
receipt IDs, amounts, descriptions or counts. Money permissions and Supplier
denial retain their existing behavior.

## Meaning and limits

This gate checks current material Exceptions at save time. It does not certify
zero debt, full supplier/expense settlement, a frozen CA package or completeness
of uncaptured sources. In particular, CONTAINER_UNAPPLIED parking consumes receipt
capacity without settling a Sale and can leave no MONEY_UNALLOCATED Exception.
Making parking or outstanding receivables additional closure conditions requires
a separate business decision. Later authorized ledger changes can reopen issues;
this repair does not automatically rewrite an already closed Container label.
No numeric threshold or new waiver policy is introduced. UNKNOWN/PENDING values
remain unchanged.

## Evidence aggregation and future provider entry

Attachment states remain PENDING, VERIFYING, CAPTURED, FAILED_RETRYABLE,
FAILED_PERMANENT, PARTIAL, HASH_MISMATCH and SUPERSEDED. Child CONFLICT is not a
state. Aggregation preserves a parent CONFLICT established by integrity handling;
PARTIAL/HASH_MISMATCH/FAILED_PERMANENT remain incomplete. COMPLETE still requires a
finalized manifest and all expected current attachments captured with readback.

Future authenticated live-provider adapters **must** call the non-whitelisted
`evidence_service.ingest_provider_message_evidence`, after their own signature and
account verification. All four provider/account/conversation/message IDs must be
nonempty strings before any writes. Accepted opaque IDs are preserved exactly;
no trimming, case folding, numeric coercion, guessed IDs or fallback is allowed.
Only documented source inputs are accepted; caller capture/verification metadata
is not part of this interface. In particular, caller manifest finalization/count
are rejected; this entry retains UNKNOWN/-1 so a forged zero attachment manifest
cannot become COMPLETE. Trusted manifest finalization belongs to a separate
server-controlled path. The existing `ingest_message_evidence` remains the
historical/offline path and can preserve unknown identity. This is a service
contract with tests, not a live webhook, downloader or provider integration.

## Role vocabulary audit

Installed/native maker capability remains Fresko Salesperson. Commercial services
recognize optional Fresko Trader, but a Trader-only account lacks compatible
Evidence access and native Workspace/DocType permissions. Recognition does not
establish a supported Trader-only end-to-end workflow. No Trader role is installed
or permissions expanded here. Use the supported Salesperson capability; decide
any Trader-only support separately. Accounts/Approver segregation and mixed
Supplier denial remain enforced by their existing services.

## Verification boundary

Offline regressions execute actual service functions against stubs. Pinned Bench
regressions exercise persisted exception policy, the real three-person Money
workflow, preserved source context, replay/conflict, no ledger mutation and a
second writer after an earlier transaction snapshot. All existing six migration
proofs remain required. No DocType, field, schema snapshot or patch changes are
needed. Neither these checks nor this packet provide browser/deployment proof.
