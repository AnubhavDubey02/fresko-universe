# Canonical documents and historical evidence

**Status:** Phase 1 closeout index

**Reviewed:** 2026-10-02

**Scope:** Historical Phase 1 authority, dated PR #7 stabilization status, the
focused Phase 2A physical-Outward contract/implementation checkpoint, the
2026-10-02 locked operational/access decisions, and the 2026-10-03 real-data
shadow-replay/quantity-boundary checkpoint. This index authorizes no merge.

Use this index before relying on an older design memo. Historical documents remain
in the repository as dated evidence; a later canonical decision overrides a
conflicting proposal without rewriting the historical record.

## Current authority

| Subject | Canonical document | Rule |
|---|---|---|
| Real-data shadow-replay gate | `docs/REAL_DATA_SHADOW_REPLAY_CONTRACT.md` plus `fresko_universe/fresko_universe/fixtures/real_data_shadow/manifest.json` | Sanitized source-hash/range-bound acceptance truth for the reviewed Plum/Grapes/CA cut-offs. It is a deterministic fixture gate, not runtime, bank, accounting, or CA proof. |
| Money runtime, receipt review and noncash receivables | `docs/MONEY_RECONCILIATION_RUNTIME.md` | Collections preserve received assertions separately from bank clearance; approved cash declarations need no bank deposit. Explicit reviewed applications alone discharge Sale debt. |
| Native operations workspace and read tools | `docs/OPERATIONS_WORKSPACE.md` and `fresko_universe/fresko_universe/ask_fresko.py` | Native Frappe Pages; deterministic allowlisted read tools preserve service permissions. Live LLM/OCR/WhatsApp remain deferred. |
| Commercial Sale runtime and alias architecture | `docs/COMMERCIAL_SALE_RUNTIME.md` | Authoritative documentation for the implemented Commercial Sale ledger, multi-lot lines, approved party aliases, many-to-many physical Outward allocations, and segregation-of-duties role controls. |
| Next commercial-event and alias slice | `docs/COMMERCIAL_EVENT_ALIAS_CONTRACT.md` | Implementation contract for multi-lot Commercial Sale, unallocated price buckets, Sale-to-Outward allocation, and role-approved reusable aliases. It records no runtime implementation. |
| Current operational classifications and access boundaries | `docs/CANONICAL_BUSINESS_DECISIONS_2026-10-02.md` | Records the INR 101 boundary and evidence-pending INR 350,000/92-at-INR-700 states; accepts role-based alias approval and supplier isolation in principle while exact transitions/visible fields remain proposed. |
| Latest stabilization and temporal acceptance status | `docs/CANONICAL_STATUS_ADDENDUM_2026-10-01.md` | Current exact-head checkpoint and dated corrections to time-bounded business examples; preserves older documents as historical evidence. |
| Container-to-CA business contract | `docs/CONTAINER_CYCLE_TO_CA_CONTRACT.md` | Governs truth layers, cut-offs, lifecycle boundaries, Phase 2A physical movement, future ledgers, settlement, and CA-ready output without implying those future ledgers are implemented. |
| Staging package, browser and recovery boundary | `docs/STAGING_DEPLOYMENT_BROWSER_BASELINE.md` | Implementation 02; immutable app-root exports, native browser proof and isolated recovery. Cloud deployment and paid-site creation require actual connected access and explicit cost approval. |
| Current pilot safety closure and provider entry | `docs/PILOT_SAFETY_CLOSE_POLICY.md` | Implementation 01 materiality matrix, contextual Money attribution, current-read close gate, Attachment aggregation correction and fail-closed future-provider service contract; no live ingestion. |
| Current coding-agent implementation handoff | `docs/AGENT_HANDOFF.md` | Dated branch/SHA/test status. The 2026-10-02 section records the first Phase 2A slice and its explicit deferrals; live GitHub checks still control exact-head claims. |
| Locked product and architecture decisions | `docs/DECISIONS.md` | Highest authority for D1, D3-D6, D10, merge gates, dependency sovereignty, and security role. |
| Phase 1 Container/Deal design | `docs/PHASE1_BLUEPRINT_FINAL.md` | Supersedes specialist drafts where they conflict. |
| Remaining uncertainty | `docs/OPEN_QUESTIONS.md` | `UNKNOWN` and `PENDING` items remain open until evidence or an authorized decision closes them. |
| Dependency selection | `docs/DEPENDENCY_POLICY.md`, `docs/THIRD_PARTY.md`, `docs/VERSIONS.md` | Free-first/free-forever rules, approved inventory, and immutable platform pins. |
| Schema-changing pull requests | `docs/SCHEMA_MIGRATION_PROOFS.md` plus `scripts/schema_migration_proofs.json` | Every persisted-schema change registers a seeded Phase 1-to-current proof run by the reusable harness; non-schema changes add none. |
| CI verification | `docs/GATE2_CI_RESULT.md` | Exact-SHA run URLs, counts, failures, and skips. A green ancestor is not proof for a later SHA. |
| Security posture | `docs/security/SECURITY_FINDINGS.md`, `docs/security/SECURITY_TESTING.md` | Finding status and test evidence; FSEC-004/FSEC-005 remain Phase 2 entry gates. |
| Operational source provenance | `docs/SOURCES.md` | Drive identifiers, immutable local hashes, and permitted phase use. |
| WhatsApp readiness contract | `docs/phase2_readiness/WHATSAPP_FIXTURE_CONTRACT.md` | Test-only evidence semantics; does not authorize live ingestion or implement Phase 2. |
| Readiness source review | `docs/phase2_readiness/CLOSEOUT_REVIEW.md` | Source comparisons, corrected certainty claims, remaining operational evidence, and limits of fixture validation. |

## Historical or supporting evidence

The following are retained as dated inputs or reviews. They are not independent
authority when they conflict with the current documents above.

- `briefs/*.md` and their mirrored `docs/{architecture,controls,frappe_doctypes,qa_adversarial}.md`
- `docs/DOCTYPE_CONTAINER_DEAL_v1.md`
- `docs/PHASE1_CONTAINER_DEAL_ARCHITECTURE.md`
- `docs/CONTROLS_PHASE1_CONTAINER_DEAL.md` and review reports
- `docs/QA_CONTAINER_DEAL_ATTACK_REPORT.md` and QA review reports
- `docs/PHASE1_MERGE_EVIDENCE_PACK.md`
- older dated sections inside `docs/GATE2_CI_RESULT.md` and `docs/security/`

Two important resolved conflicts are:

1. Phase 1 approval creates no Sales Order, Delivery Note, Stock Entry, or Stock
   Ledger Entry. It creates a soft commercial reservation only.
2. A counter rate lives on `Fresko Approval.decision_rate`; Deal.`approved_rate`
   remains null until the originator or assigned salesperson accepts the counter.

## Change discipline

- Preserve historical dates and conclusions; add a dated correction or
  superseded notice instead of silently rewriting past evidence.
- Cite an immutable commit SHA for CI evidence and verify that exact SHA.
- Never turn missing evidence into zero, success, matched, received, or verified.
- Do not merge, retarget, or close predecessor PRs without explicit repository-owner authorization. Keep Phase 2A work on its focused branch/PR.
