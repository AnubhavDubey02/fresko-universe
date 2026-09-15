# SECURITY_FINDINGS — living log

**Baseline date:** 2026-09-15  
**Tip:** `18c5042` `phase1-doctype-scaffold`  
**All statuses below:** OPEN unless noted.

Severity gate: CRITICAL/HIGH require fix or documented human override before production.

---

## FSEC-001 — Whitelist commercial methods lack role/ownership checks

| Field | Value |
|---|---|
| **SEVERITY** | HIGH |
| **STATUS** | OPEN |
| **Prerequisites** | Any authenticated Desk/API user who can call `@frappe.whitelist` methods |
| **Component** | `fresko_universe/deals.py`, `container.py` |
| **Impact** | User with minimal DocType rights (or Accounts read-only on Deal) may still cancel deals, record dispatch, apply rate rules, open/apply revisions, or read ATS snapshots because methods save with `ignore_permissions=True` and do not call `get_roles` / ownership checks (except `accept_counter`). |
| **Evidence** | `deals.py:14-97` (`apply_rate_rules`), `:135-155` (`cancel_deal`), `:158-218` (`record_dispatch`), `:221-280` (`request_revision`), `:283-354` (`apply_revision`); `container.py:12-14`; contrast `approvals.py:38-40` which does check roles |
| **Repro (high-level)** | Authenticate as a low-privilege Fresko role; invoke the whitelist method names above with a victim `deal_name`; observe mutation without role denial. |
| **Fix** | Add explicit role/ownership gates per `PERMISSION_MATRIX.md`; avoid `ignore_permissions` except after checks; prefer `frappe.has_permission` + `check_permission`. |
| **Regression test** | For each method, `frappe.set_user` as Salesperson/Accounts/Approver/SM and assert allow/deny matrix. |

---

## FSEC-002 — `apply_revision` accepts any existing Approval name (no bind / decision check)

| Field | Value |
|---|---|
| **SEVERITY** | HIGH |
| **STATUS** | OPEN |
| **Prerequisites** | Ability to call `apply_revision`; existence of any `Fresko Approval` document in the site |
| **Component** | `deals.py:apply_revision` |
| **Impact** | Material commercial fields (rate/qty/lot/customer) can be applied if *any* Approval name is supplied. Code checks `frappe.db.exists("Fresko Approval", approval_ref)` only — does not verify Approval.deal == revision.parent_name, decision ∈ {APPROVE,…}, or that the caller is Approver. Controls docs claim role validation on this path (**DOC_ONLY**, contradicted). |
| **Evidence** | `deals.py:302-318`; `docs/controls.md` (~lines 106–107 claim whitelist validates state + role) |
| **Repro (high-level)** | Create Pending revision on Deal A; pass Approval document belonging to Deal B (or REJECT decision) into `apply_revision`; observe whether apply succeeds. |
| **Fix** | Load Approval; assert `approval.deal == deal.name`, decision allowed, optionally reason/evidence; require Fresko Approver/SM; reject stale Approvals. |
| **Regression test** | `test_apply_revision_rejects_mismatched_approval_deal`; `test_apply_revision_rejects_non_approver`. |

---

## FSEC-003 — No `has_permission` / `permission_query`; coarse Desk write

| Field | Value |
|---|---|
| **SEVERITY** | HIGH |
| **STATUS** | OPEN |
| **Prerequisites** | Authenticated user with Fresko role perms from DocType JSON |
| **Component** | hooks / DocType JSON / missing Python hooks |
| **Impact** | Salesperson has write on all Fresko Deals (not owner-scoped). Approver has write on Containers and Deals. No row-level query filter. Server validate blocks some field/status abuses, but list/report exposure and unexpected writes remain broad. |
| **Evidence** | `fresko_deal.json` permissions; repo search: zero `has_permission` / `permission_query` implementations under `fresko_universe` |
| **Repro (high-level)** | Log in as Salesperson A; open Deal owned by Salesperson B; confirm read/write via Desk. |
| **Fix** | Add `permission_query` conditions and `has_permission` for Deal/Evidence; tighten JSON perms (Accounts should not gain write via whitelist). |
| **Regression test** | Permission query tests with two sales users. |

---

## FSEC-004 — Evidence content hash is path-string digest, not file bytes

| Field | Value |
|---|---|
| **SEVERITY** | MEDIUM |
| **STATUS** | OPEN |
| **Prerequisites** | Create Fresko Evidence with Attach `file` |
| **Component** | `fresko_evidence.py:16-21` |
| **Impact** | Integrity/non-repudiation claim is weak: identical path strings collide; replacing file bytes at same URL may keep same hash; does not detect content tampering. |
| **Evidence** | `fresko_evidence.py` `before_insert` hashes `(self.file or self.external_ref or "").encode()` |
| **Repro (high-level)** | Create two Evidence rows pointing at different binaries but same Attach path string pattern; compare `content_sha256`. |
| **Fix** | Hash file bytes from File doc / disk; store algorithm version; optional WORM storage later. |
| **Regression test** | `test_evidence_hash_matches_file_bytes`. |

---

## FSEC-005 — Evidence.`message_id` not unique (Deal-level only)

| Field | Value |
|---|---|
| **SEVERITY** | MEDIUM |
| **STATUS** | OPEN |
| **Prerequisites** | Phase 1 manual Evidence create today; critical once WhatsApp ingest lands |
| **Component** | `fresko_evidence.json` vs `fresko_deal.json` |
| **Impact** | Duplicate ingest evidence rows with same Meta message id possible; QA attack report residual for double-count if fingerprint optional. Deal `source_message_id` **is** unique=1. |
| **Evidence** | Deal field `source_message_id unique=1`; Evidence `message_id unique=None` (JSON parse baseline) |
| **Repro (high-level)** | Insert two Evidence docs with identical `message_id`. |
| **Fix** | Unique index on Evidence.message_id (nullable unique / partial as MariaDB allows) before webhook work. |
| **Regression test** | `test_evidence_message_id_unique`. |

---

## FSEC-006 — CI lacks SAST, secret scan, dependency advisory, permission tests

| Field | Value |
|---|---|
| **SEVERITY** | MEDIUM |
| **STATUS** | OPEN |
| **Prerequisites** | PR merge via `.github/workflows/ci.yml` |
| **Component** | `.github/workflows/ci.yml` |
| **Impact** | Secrets, vulnerable Actions/deps, and authz regressions can merge on green smoke/bench alone. Last recorded bench run failed (`docs/GATE2_CI_RESULT.md`) — security signal is incomplete. |
| **Evidence** | `ci.yml` jobs: `smoke-unit`, `frappe-bench` only — no CodeQL/semgrep/gitleaks/trivy/pip-audit/permission job |
| **Repro (high-level)** | Read workflow; confirm absence of scan steps. |
| **Fix** | Add gitleaks (or equivalent), pinned-action review, pip-audit/gh advisory job on lockfile/pins, and role-matrix unittest job. Do **not** auto-upgrade Frappe without Dependency Sovereignty proposal. |
| **Regression test** | CI must fail if secret scanner finds high-entropy credentials. |

---

## FSEC-007 — Local/CI compose publishes DB/Redis with default root credentials

| Field | Value |
|---|---|
| **SEVERITY** | MEDIUM |
| **STATUS** | OPEN |
| **Prerequisites** | `docker compose up` on a reachable host |
| **Component** | `docker-compose.yml`, `docker-compose.bench.yml`, `scripts/ci_bench.sh`, `ci.yml` |
| **Impact** | Accidental exposure of MariaDB (`root`/`root`) and open Redis on host ports 3306/6379. |
| **Evidence** | compose `ports: "3306:3306"`, `MYSQL_ROOT_PASSWORD: root`; `ci_bench.sh` defaults `DB_ROOT_PASSWORD=root`, `ADMIN_PASSWORD=admin` |
| **Repro (high-level)** | Start compose; connect from another host to published ports. |
| **Fix** | Bind to `127.0.0.1` only; use secrets; document never for prod; rotate any shared lab passwords. |
| **Regression test** | Compose config lint asserting `127.0.0.1:` binds. |

---

## FSEC-008 — Doc/code drift: RATE_FLOOR_BREACH exception not opened on out-of-band path

| Field | Value |
|---|---|
| **SEVERITY** | LOW |
| **STATUS** | OPEN |
| **Prerequisites** | Deal with resolved band but `proposed_rate` outside band |
| **Component** | `deals.py:apply_rate_rules` else-branch |
| **Impact** | Status correctly becomes Approval Required, but comment claims “RATE_FLOOR_BREACH path” while no `Fresko Exception` of that type is created (unlike `RATE_POLICY_MISSING` / `STOCK_SHORTFALL`). Close-gate and ops dashboards may under-count material issues. |
| **Evidence** | `deals.py:64-68` sets status only; `EXCEPTION_TYPES` includes `RATE_FLOOR_BREACH` in `constants.py` |
| **Repro (high-level)** | `apply_rate_rules` on below-floor deal with defaults present; query Exceptions for type RATE_FLOOR_BREACH. |
| **Fix** | Open Exception consistently or update docs/close-gate lists deliberately. |
| **Regression test** | Assert exception row created (or explicitly document non-creation). |

---

## FSEC-009 — `.gitignore` gaps for key material / site config filenames

| Field | Value |
|---|---|
| **SEVERITY** | LOW |
| **STATUS** | OPEN |
| **Prerequisites** | Developer drops keys in repo tree |
| **Component** | root `.gitignore` |
| **Impact** | `*.pem`, `*.key`, `site_config.json`, credential filenames not ignored (`.env` and `sites/` are). Raises chance of accidental commit. |
| **Evidence** | `.gitignore` contents; history scan found no PEM/AWS keys today |
| **Fix** | Expand ignore patterns; add pre-commit secret scan. |
| **Regression test** | gitleaks on CI. |

---

## FSEC-010 — No API rate limiting / abuse throttling on commercial whitelist

| Field | Value |
|---|---|
| **SEVERITY** | MEDIUM |
| **STATUS** | OPEN |
| **Prerequisites** | Authenticated session |
| **Component** | whitelist surface |
| **Impact** | Automated spam of `apply_rate_rules` / `decide` / revisions; no Fresko throttle layer (relies on upstream only — UNKNOWN if configured). |
| **Evidence** | No `rate_limit`/`throttle` references under app Python |
| **Fix** | Frappe rate limiter / Redis counters on mutate methods; idempotency keys for decide. |
| **Regression test** | Burst calls return 429/limit error after N. |

---

## FSEC-011 — Phase 2 WhatsApp / OCR / LLM surface not implemented (future)

| Field | Value |
|---|---|
| **SEVERITY** | INFORMATIONAL |
| **STATUS** | OPEN (tracking) |
| **Prerequisites** | Future feature work |
| **Component** | docs only (`THIRD_PARTY.md`, QA WhatsApp attacks) |
| **Impact** | Large future attack surface: webhook auth, replay, prompt injection, PII to vendors. Must not ship without Fresko-owned interfaces + threat model update. |
| **Evidence** | No matching imports in app code; policy forbids adopting SDKs without proposal |
| **Fix** | Before implementation: webhook signature verification, Evidence uniqueness, LLM isolation, dependency proposal. |
| **Regression test** | TBD with feature. |

---

## FSEC-012 — Approval/Revision/Evidence `track_changes=0`

| Field | Value |
|---|---|
| **SEVERITY** | LOW |
| **STATUS** | OPEN |
| **Prerequisites** | None |
| **Component** | DocType JSON |
| **Impact** | Relies on custom append-only/immutable validators; Frappe Version trail absent for these DocTypes. Partially mitigated for Approval/Revision. |
| **Evidence** | JSON `track_changes` values from baseline parse |
| **Fix** | Enable track_changes where it does not fight append-only design, or export periodic audit snapshots. |
| **Regression test** | N/A / audit export test. |

---

## Closed / mitigated notes (not findings)

- Gate 1 empty rate band fail-closed: **implemented** (`rate_rules.policy_resolved`, `apply_rate_rules` RATE_POLICY_MISSING).
- D4 accept_counter ACL: **implemented** with tests.
- D10 SM-only oversell: **implemented** with tests.
- Desk `approved_rate` / `dispatched_qty` locks: **implemented**.
- No committed cloud API keys found in history scan (this baseline).
