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
| MSG-UNIQ | Provider message uniqueness scope for FSEC-005 | **DESIGN RESOLVED 2026-09-18; IMPLEMENTATION PENDING** — versioned canonical scoped-message key plus original provider/account/conversation/message IDs and collision check; see `docs/phase2_readiness/WHATSAPP_FIXTURE_CONTRACT.md`. FSEC-005 remains OPEN. |
| — | Evidence retention period | Compliance |
| — | Pin exact Frappe/ERPNext versions | **CLOSED** — see `docs/VERSIONS.md` (Frappe v15.120.1 / ERPNext v15.121.2) |
| F2-002 | Circular expectation derivation in evidence provenance | **LOW / LATENT — investigated 2026-09-19, defect NOT demonstrated.** Two sites derive "expected" values from `observed_*`, which are computed from the actual file: `_load_manifest_data` fabricates `{"attachments":[{"expected_byte_count": observed, "expected_sha256": observed}]}` when the manifest file cannot be read and `source_payload` will not parse; `validate_completeness_provenance` adopts a prior attempt's `observed_*` as a provider declaration. Neither is reachable today — the fabricated entry carries no `file_name`/`provider_attachment_id`/`ordinal`, so both manifest consumers (`:513`, `:644`) reject it, and the provider-side query filters `operation IN ('MESSAGE_INGEST','ATTACHMENT_INGEST')` while `observed_*` are written only on `ATTACHMENT_VERIFY`. `_load_parent_payload` selects `observed_*` but never uses them. **Becomes live** if a single-entry fallback is added to the manifest matcher, or if `observed_*` start being written on ingest attempts. Production code deliberately left unchanged — no defect was reproduced. Guarded by `test_manifest_must_not_be_fabricated_from_observed_values`. |
| F2-003 | Evidence actor fallback fabricates provenance | **OPEN — reachable.** `evidence_service.py:241` `actor = frappe.session.user or "Administrator"`, written to `actor`, `owner` and `modified_by`. With no authenticated session (background webhook worker, scheduled job) an UNKNOWN actor silently becomes `Administrator`. Violates the never-fabricate-provenance rule. Not yet reproduced or fixed; must not be bundled into unrelated work. |

## Closed this gate cycle
| ID | Item | Resolution |
|---|---|---|
| F-M7 | Empty rate band auto-approve | Gate 1: `policy_resolved` fail-closed → AR + `RATE_POLICY_MISSING` |
| D4 tighter | SM/Approver accept_counter | Only `deal.owner` or `deal.salesperson_user` |
| Gate 2 pins | Frappe/ERPNext versions | `docs/VERSIONS.md` |
