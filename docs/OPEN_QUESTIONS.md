# OPEN_QUESTIONS — Fresko Universe

## Locked by Anubhav (2026-09-15)
D1, D3, D4, D5, D6, D10 — see DECISIONS.md.

## Still open
| ID | Question | Notes |
|---|---|---|
| D2 | Exact ATS remaining-qty math for PARTIALLY_DISPATCHED | Implement per blueprint; confirm at Phase 3 |
| D7 | Physical inward: Purchase Receipt vs Stock Entry | Phase 3 |
| D8 | Project vs Accounting Dimension for container P&L | Later |
| D9 | GST / invoice timing | CA |
| — | Legal entity / partner accounting model | CA |
| — | Direct receipt meaning | Payments phase |
| CHA-VERIFY | CHA bill verification before payment | **PENDING** — require shipment-specific receipts and exemption checks. Approximately ₹80,000 excess payment is user-reported and **not independently verified**. No CHA module is part of this Phase 1 repair. |
| — | Credit/exposure limits | Later |
| — | WhatsApp production number / templates | Phase 2 |
| MSG-UNIQ | Provider message uniqueness scope for FSEC-005 | **PENDING** — choose either a composite unique key `(provider, provider_account_id, conversation_id, provider_message_id)` or one canonical scoped-message key. Do not impose global uniqueness on the current bare `message_id` until this is decided. |
| — | Evidence retention period | Compliance |
| — | Pin exact Frappe/ERPNext versions | **CLOSED** — see `docs/VERSIONS.md` (Frappe v15.120.1 / ERPNext v15.121.2) |

## Closed this gate cycle
| ID | Item | Resolution |
|---|---|---|
| F-M7 | Empty rate band auto-approve | Gate 1: `policy_resolved` fail-closed → AR + `RATE_POLICY_MISSING` |
| D4 tighter | SM/Approver accept_counter | Only `deal.owner` or `deal.salesperson_user` |
| Gate 2 pins | Frappe/ERPNext versions | `docs/VERSIONS.md` |
