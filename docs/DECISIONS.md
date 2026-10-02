# DECISIONS — Fresko Universe

## 2026-09-18 — Readiness design closeout (delegated technical decision)

- Following Anubhav's delegation, MSG-UNIQ design selects a versioned canonical
  scoped-message key, retaining all four original identifiers and checking them
  on duplicate-key hits. Serialization, collision, missing-ID, and attachment
  rules are in `docs/phase2_readiness/WHATSAPP_FIXTURE_CONTRACT.md`.
- FSEC-004 byte-hash/readback and FSEC-005 uniqueness remain **OPEN** until
  implemented and tested; a design decision does not close a security finding.
- Source summaries, extracted fields, identity matches, and settlement evidence
  are separate. Archive file presence does not establish application capture.
- This decision adds no dependency, provider integration, or runtime schema.
  Phase 2 implementation and merging PR #2 remain on hold.

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
- **D4 tighter:** `accept_counter` only `deal.owner` or `deal.salesperson_user` — System Manager must not accept on behalf.

## 2026-09-15 — Dependency Sovereignty / Free-Forever (LOCKED)

Anubhav locked dependency policy:

1. Prefer OSI permissive (MIT, Apache-2.0, BSD, ISC).
2. GPL only with documented obligations.
3. No critical dependence on source-available / fair-code / open-core commercial functionality without explicit approval.
4. Record URL, license, exact version/commit, purpose in `docs/THIRD_PARTY.md`.
5. Pin exact versions/SHAs.
6. Strategic deps: Fresko-controlled fork or immutable source archive.
7. Preserve copyright / LICENSE / NOTICE.
8. No Fresko business logic inside upstream forks unless unavoidable — adapters / custom app.
9. Provider integrations behind Fresko-owned interfaces.
10. Upstream updates optional; must run last approved version.
11. Before major greenfield: search mature OSS + license/security/maintenance review.
12. Before adopt: compare maintenance cost vs engineering saved.

**Process:** do not add dependencies automatically. Propose with function → candidate → license → maturity → code saved → risks → fork strategy → recommendation.

Canonical docs: `docs/DEPENDENCY_POLICY.md`, `docs/THIRD_PARTY.md`.

## 2026-09-15 — Security & Red Team Engineer (LOCKED)

Permanent independent role: **Fresko Security** (Security & Red Team Engineer).

- Not a dependency scanner alone — continuous adversarial + senior AppSec review.
- Independent of implementers; implementer claims are not proof of security.
- Owns `docs/security/` ledger (architecture, threat model, permission matrix, findings, testing, baseline).
- CRITICAL blocks production; HIGH normally blocks unless authorized human acceptance recorded.
- AI inputs untrusted; AI must never become financial/inventory/accounting truth without deterministic controls.
- No autonomous production destructive actions (delete data, rotate prod secrets, disable services, attack third parties, mutate financials) without explicit authorization.
- Initial assignment: baseline assessment of CURRENT repo with MUST FIX NOW / BEFORE PRODUCTION / LATER HARDENING backlog and concrete evidence.

## 2026-09-15 — ChatGPT independent review blockers (Phase 1 hold)

Implemented on `phase1-doctype-scaffold` without merge / without Phase 2:

1. **Commercial immutability:** `COMMERCIAL_LOCK_STATUSES` includes Cancelled, Rejected, Disputed (plus existing post-Proposed locks). Desk write remains Salesperson=Proposed-only; Accounts read-only.
2. **Approval↔Revision bind:** Fresko Approval.`revision` + `consumed`; `approvals.create_revision_approval`; material `apply_revision` rejects Deal-only Approvals; stale old_value + consume replay guards.
3. **Phase 1 Revision boundary:** `REVISION_ELIGIBLE_FIELDS` is the canonical server allowlist and is enforced by request, DocType controller, and apply. Container reassignment is explicitly unsupported until an atomic destination-lot/ATS flow exists.
4. **Audit provenance:** Approval/Revision creation is server-method-only; actor and timestamp are always overwritten from the authenticated session/server clock. Phase 1 revision approvals support `APPROVE` only—`OVERSELL_OVERRIDE` remains a Deal-level System Manager decision and cannot label a revision.
5. **Physical dispatch serialization:** every `record_dispatch` locks the stable Container row before reading lot inward or aggregate dispatched quantity and holds the lock through save/commit.
6. **RC Countered rate:** `decide(COUNTER)` stores rate on Approval.`decision_rate` only; Deal.`approved_rate` stays NULL; `accept_counter` copies decision_rate → approved_rate then Approved + D6.

**Security backlog (not fixed here — do not pad):**

- **FSEC-004 / FSEC-005** = Phase 2 entry gates (Evidence byte-hash; Evidence.`message_id` uniqueness before WhatsApp ingest).
- **FSEC-006** = before production (CI SAST / secret scan / dependency advisory).

Gate1 / D4 / D10 unchanged.
