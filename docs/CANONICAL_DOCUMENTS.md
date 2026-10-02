# Canonical documents and historical evidence

**Status:** Phase 1 closeout index

**Reviewed:** 2026-09-18

**Scope:** PR #2 / `phase1-doctype-scaffold`; Phase 2 implementation remains on hold.

Use this index before relying on an older design memo. Historical documents remain
in the repository as dated evidence; a later canonical decision overrides a
conflicting proposal without rewriting the historical record.

## Current authority

| Subject | Canonical document | Rule |
|---|---|---|
| Locked product and architecture decisions | `docs/DECISIONS.md` | Highest authority for D1, D3-D6, D10, merge gates, dependency sovereignty, and security role. |
| Phase 1 Container/Deal design | `docs/PHASE1_BLUEPRINT_FINAL.md` | Supersedes specialist drafts where they conflict. |
| Remaining uncertainty | `docs/OPEN_QUESTIONS.md` | `UNKNOWN` and `PENDING` items remain open until evidence or an authorized decision closes them. |
| Dependency selection | `docs/DEPENDENCY_POLICY.md`, `docs/THIRD_PARTY.md`, `docs/VERSIONS.md` | Free-first/free-forever rules, approved inventory, and immutable platform pins. |
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
- Do not merge PR #2 or begin Phase 2 without explicit authorization.
