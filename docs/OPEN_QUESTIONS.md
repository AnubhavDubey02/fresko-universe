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
| — | Credit/exposure limits | Later |
| — | WhatsApp production number / templates | Phase 2 |
| — | Evidence retention period | Compliance |
| — | Pin exact Frappe/ERPNext versions | **CLOSED** — see `docs/VERSIONS.md` (Frappe v15.120.1 / ERPNext v15.121.2) |

## Closed this gate cycle
| ID | Item | Resolution |
|---|---|---|
| F-M7 | Empty rate band auto-approve | Gate 1: `policy_resolved` fail-closed → AR + `RATE_POLICY_MISSING` |
| D4 tighter | SM/Approver accept_counter | Only `deal.owner` or `deal.salesperson_user` |
| Gate 2 pins | Frappe/ERPNext versions | `docs/VERSIONS.md` |
