# DECISIONS — Fresko Universe

## 2026-09-15 — Phase 1 Container/Deal blueprint (Chief of Staff)

- ERPNext/Frappe v15 assumed (Serial and Batch Bundle); greenfield `fresko_universe`.
- Custom: Container (+ Lot child), Deal, Approval, Revision, Evidence (min), Exception (min).
- Phase 1: soft commercial reservation only; no SO/DN/SLE on approve.
- Fresko Revision mandatory for post-approval commercial changes.
- Lot membership enforced via Container Lot child; commercial lot_no preserved beside Batch.
- Unique source_message_id + duplicate_fingerprint when set.
- Unresolved buyer may APPROVE with BUYER_UNRESOLVED open; block RECONCILED until Customer.
- See `PHASE1_BLUEPRINT_FINAL.md` for full lock list C1–C10.

## 2026-09-15 — Anubhav locked decisions (blueprint approved)

- **D1:** No ERPNext Sales Order on Deal approval in Phase 1. Fresko Deal is operational commercial record. Clean SO/DN boundary for Phase 3.
- **D3:** PROPOSED does not reduce ATS. APPROVED and AUTO_APPROVED do. Re-read ATS under transactional/concurrency protection immediately before approval.
- **D4:** COUNTERED requires explicit acceptance by deal originator/salesperson before becoming APPROVED. Approver who wants an immediate different rate must APPROVE with that decision_rate (not COUNTER).
- **D5:** Rate-floor hierarchy: Lot override → Container + Product + Count/Size → Container default. No buyer-specific floor in V1.
- **D6:** May approve with unresolved buyer alias; preserve alias permanently; open BUYER_UNRESOLVED; block final invoice/reconciliation until Customer mapped.
- **D10:** Oversell override Owner/Admin only; reason + Approval + Exception; may allow commercial commitment; must never allow physical dispatch beyond stock or silent negative stock.
- Frappe/ERPNext v15 pinned for Gate 2 CI — see `docs/VERSIONS.md` (was provisional until bench install).
- Container Lot links to ERPNext Batch; must not compete as inventory SoR.

## 2026-09-15 — Merge gates (Anubhav)

- Hold merge of PR #2 until Gate 1 + Gate 2 complete; no Phase 2.
- **Gate 1:** Missing rate policy is fail-closed — no AUTO_APPROVE when floor/ceiling unresolved; APPROVAL_REQUIRED + RATE_POLICY_MISSING.
- **Gate 2:** Reproducible CI/Docker bench with pinned Frappe+ERPNext v15; migrate + run-tests must pass.
- **D4:** accept_counter only originator/salesperson; Approver must not accept on behalf.

- **F-M7 closed:** empty-band auto-approve is no longer residual; Gate 1 enforces `policy_resolved` + `RATE_POLICY_MISSING`.
- **Versions pinned:** Frappe `v15.120.1` / ERPNext `v15.121.2` — see `docs/VERSIONS.md` (provisional → pinned for Gate 2 CI).
