# Reporting read contracts — Track C, 2026-10-10

`fresko_universe.report_contracts` defines eleven static report descriptors. It
returns read-operation proposals, not reports, authorization decisions or numbers.
It has no Frappe dependency, HTTP endpoint, database reads, tool dispatch or writes.

| Descriptor | Existing allowlisted read tool | Coverage |
|---|---|---|
| outward_reconciliation | outward_reconciliation | Physical Outward allocation/capacity and visible commercial links |
| sale_history | sale_as_of | Sale state at required cutoff, not an independent history export |
| buyer_receivables | customer_receivable | Company/customer receivable projection, preserving unknown subtotals |
| unallocated_collections | unallocated_collections | Approved eligible unapplied receipts; bank/cash distinctions remain in the service |
| bank_pending | bank_pending_collections | Pending bank receipts with unknown amounts retained by the service |
| money_exceptions | open_money_exceptions | Current open exceptions; this tool has no as-of argument |
| container_stock | None | NOT_IMPLEMENTED: catalog has no complete operating Inward/current-stock projection |
| lot_stock | None | NOT_IMPLEMENTED: catalog has no lot-stock aggregate |
| inward_outward | None | NOT_IMPLEMENTED: catalog has no complete physical movement ledger |
| source_lineage | None | NOT_IMPLEMENTED: no cross-document source-lineage aggregation |
| document_lineage | None | NOT_IMPLEMENTED: no lineage export |

The supplied candidate mapped stock and movement reports to commercial Container
reconciliation. That service describes commercial Sales and physical Outward
capacity; it does not provide operating Inward minus Outward stock or a complete
movement ledger. Those reports remain explicitly unsupported rather than labeling
an incomplete projection as inventory truth. Existing quantity assertions and
physical services are unchanged.

All six supported descriptors match the exact required/optional argument sets in
`ask_fresko.py`. Company arguments are derived from the supplied server-context
parameter, and explicit disagreement is denied. This pure parameter is not proof
of authentication: any future adapter must derive it from the actual session,
verify record membership/read permission, and dispatch through existing authorized
services. Record-based tools do not accept a Company parameter; they cannot safely
receive one just to suggest tenant enforcement. Supplier-first denial, Accounts /
Approver-only Money access and Evidence authorization remain native-service duties.
No client role, verified flag or arbitrary tool argument is accepted.

Identifiers and supplied nonempty as-of strings remain exact. Blank supplied
arguments require clarification, preventing a blank historical cutoff from
silently becoming a live proposal. Omitted optional as-of retains the existing
live-read convention. Calendar validity and timezone semantics remain enforced
by the native services; this contract does not manufacture timestamps.

Executed offline tests validate descriptors and proposal construction only.
They do not establish authenticated permission, native report values, MariaDB
concurrency, browser usability or staging readiness. Existing full native CI may
prove exercised core regressions; new reporting execution requires a reviewed
server adapter and role/company tests. No migration is required for this module.
