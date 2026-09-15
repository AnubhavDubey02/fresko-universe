# BASELINE_ASSESSMENT — Fresko Universe Phase 1

**Date:** 2026-09-15  
**Assessor role:** Fresko Security & Red Team  
**Tip:** Gate 2 app tip `3d9ac65a3aed0b64b9d02608b2fec392b40b8273` (`3d9ac65`) on `phase1-doctype-scaffold` (D6 fix; ACL re-verify `fdbd9bd`; prior Gate2 `d785b63`)  
**Method:** Static review of app code, DocType JSON, hooks, fixtures, Docker/CI, dependency docs, QA/Controls docs. No live exploit against deployed systems. No merge.

Fresko is **not** declared secure.

**Re-verify 2026-09-15 (tip `fdbd9bd`):** FSEC-001/002/003 **MITIGATED**. **D6 tip `3d9ac65` independent Security review:** BUYER_UNRESOLVED now opened on `accept_counter`; ACL gates/hooks unchanged; no new FSEC IDs. **Gate 2 CI (tip `3d9ac65`):** Smoke 58 + Bench 61 green (run 34957061073). FSEC-004+ remain OPEN. Verdict **SECURITY_OK_TO_HOLD**. Hold merge / no Phase 2. Do not declare secure.

## Scope coverage checklist

| # | Area | Outcome |
|---|---|---|
| 1 | Attack surface | Documented — whitelist set, DocTypes, Attach fields, compose, CI, fixtures |
| 2 | Authn/z | Roles present; method ACL incomplete; no permission_query |
| 3 | Secrets | No cloud keys in history; CI/compose defaults; gitignore gaps |
| 4 | Dependencies | Pins recorded; CVEs UNKNOWN; flit_core range pin |
| 5 | APIs | Whitelist validation uneven; no rate limit; error messages fairly specific |
| 6 | Business logic | Strong server controls for ATS/D4/D6/D10/Gate1/locks; FSEC-002 revision authz MITIGATED; RATE_FLOOR_BREACH drift remains FSEC-008 |
| 7 | AI/LLM | Not in code — future surface recorded |
| 8 | Data integrity | Append-only Approval; revision freeze; weak evidence hashing; track_changes uneven |
| 9 | Races / partial failure | FOR UPDATE on ATS paths; commit after whitelist; webhook N/A |
| 10 | CI | Functional tests only; security scanners missing; Gate 2 tip `3d9ac65` smoke+bench green (run 34957061073; 58/61) |
| 11 | Coverage vs mission/QA | Many QA design gaps closed in code; authz & ingest uniqueness residuals remain |

## RECORDED FACTS (summary)

1. Ten `@frappe.whitelist` entrypoints; commercial mutators gated via `permissions.py` at tip `fdbd9bd` (re-verify MITIGATED for FSEC-001/002).
2. Widespread `ignore_permissions=True` after business checks.
3. DocType JSON still grants Salesperson write=1 on Deal; **Python** `deal_has_permission` / query now owner-scope Salesperson (FSEC-003 MITIGATED with JSON residual).
4. Deal idempotency fields unique; Evidence.message_id not unique.
5. Evidence hash = SHA-256(path string).
6. `.github/workflows/ci.yml` has no SAST/secret/dep/permission jobs.
7. Compose exposes MariaDB/Redis with `root`/`root`.
8. AI/WhatsApp/OCR absent from code; policy requires proposals before adoption.
9. Controls doc revision role claim — **code now validates** Approver/SM + Approval↔Deal bind (FSEC-002 MITIGATED).

## TEST RESULTS

- **Gate 2 CI green** on tip `3d9ac65a3aed0b64b9d02608b2fec392b40b8273` (`3d9ac65`): Smoke **58** + Bench **61** including FSEC permission + D6 tests. CI run [34957061073](https://github.com/AnubhavDubey02/fresko-universe/actions/runs/34957061073) success. See `docs/GATE2_CI_RESULT.md`.
- Prior tip `d785b63`: Smoke **56** + Bench **59**, run 34954607466.
- Local Security re-check: offline smoke **58 OK**. Permission-negative `TestFSEC001*` / `002*` / `003*` still present. Tip status no longer UNKNOWN for `3d9ac65`. Hold merge / no Phase 2.

## ASSUMPTIONS

- Phase 1 remains Desk-user authenticated only.
- Production will not reuse compose defaults.

## UNKNOWN

- CVE list for Frappe `9f8ae9cd…` / ERPNext `df8b7f96…` transitive tree.
- (Cleared: Gate 2 bench+smoke status on tip `3d9ac65` / prior `d785b63` is green — see TEST RESULTS.)
- Site-level File upload hardening.
- Multi-role effective permissions.

---

## Prioritized backlog

### MUST FIX NOW (before treating Phase 1 as internally trustworthy)

| Item | Evidence | Finding | Re-verify `fdbd9bd` |
|---|---|---|---|
| Add role/ownership gates to `cancel_deal`, `record_dispatch`, `set_dispatched_qty`, `apply_rate_rules`, `request_revision`, `apply_revision`, snapshots | `permissions.py` + whitelist call sites | FSEC-001 | **MITIGATED** — gates present; offline smoke OK |
| Bind Approval→Deal (+ decision) inside `apply_revision`; require Approver/SM | `assert_approval_bound_for_revision` + `assert_can_apply_revision` | FSEC-002 | **MITIGATED** — not exists()-only |
| Prove Accounts cannot mutate Deals via whitelist despite read-only DocType perm | `TestFSEC001*` + `deal_has_permission` Accounts read-only | FSEC-001/003 | **MITIGATED**; Gate 2 bench green on `d785b63` includes FSEC permission tests (59) |
| Re-run Gate 2 bench on tip; do not claim green from older SHA | `GATE2_CI_RESULT.md` vs tip | CI hygiene | **Done for tip `3d9ac65`** — run 34957061073 Smoke 58 + Bench 61 green (prior `d785b63` 56/59); hold merge / no Phase 2 |

### BEFORE PRODUCTION

| Item | Evidence | Finding |
|---|---|---|
| ~~Implement `has_permission` / `permission_query` for Deal (and ideally Evidence)~~ **MITIGATED** at `fdbd9bd`; residual: tighten Deal JSON / add Container hooks | `hooks.py` + `permissions.py` | FSEC-003 |
| Unique Evidence.message_id before WhatsApp | `fresko_evidence.json` | FSEC-005 |
| Hash Evidence file bytes | `fresko_evidence.py` | FSEC-004 |
| CI: secret scan + SAST + advisory job (report-only first; no auto-upgrade) | `ci.yml` | FSEC-006 |
| Bind compose DB/Redis to localhost; rotate defaults | compose files | FSEC-007 |
| API rate limits on mutate whitelist | no throttle code | FSEC-010 |
| Align RATE_FLOOR_BREACH exception behavior with docs/close-gate | `deals.py:64-68` | FSEC-008 |
| Expand `.gitignore` for keys/site_config | `.gitignore` | FSEC-009 |
| Exact-pin `flit_core` before packaging releases | `pyproject.toml`, `THIRD_PARTY.md` | dep policy |

### LATER HARDENING

| Item | Notes |
|---|---|
| Dual-control / break-glass workflow for D10 oversell | SM alone is powerful |
| Enable or replace `track_changes` on Approval/Evidence | FSEC-012 |
| Settlement snapshot immutability (QA residual) | Phase beyond current Deal stub |
| WhatsApp webhook auth, replay, PII; OCR/LLM isolation | FSEC-011; Dependency Sovereignty proposals required |
| Formal penetration test on staging | After authz fixes land |
| Immutable evidence object store (WORM) | Beyond Attach |

## Dependency Sovereignty reminder

Do **not** auto-upgrade Frappe/ERPNext or add SDKs because a scanner flagged a CVE. Follow `docs/DEPENDENCY_POLICY.md`: proposal → pin/SHA → `THIRD_PARTY.md` → Anubhav approval. Report breaking-change risk explicitly when recommending a pin move.

## Coverage gaps vs QA / Controls mission

| QA / Controls expectation | Code status |
|---|---|
| Duplicate message/fingerprint | Largely implemented on Deal |
| Concurrent ATS | Implemented with FOR UPDATE + tests (Gate 2 tip `d785b63` bench green) |
| Lot membership | Implemented |
| approved_rate Desk lock | Implemented |
| Unresolved buyer blocks Reconciled | Implemented |
| Container close w/ open exceptions | Implemented for listed types |
| Revision path validates **role** | **MITIGATED** at `fdbd9bd` (Approver/SM + Approval bind) — FSEC-002 |
| WhatsApp ingest / payment verified | Not implemented |
| Settlement certificate immutability | Not in Phase 1 scope code |
