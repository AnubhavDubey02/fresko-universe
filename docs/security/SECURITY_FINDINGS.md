# SECURITY_FINDINGS — living log

**Baseline date:** 2026-09-15  
**Re-verify tip (ACL):** `fdbd9bd59435ac5f5d7e27d8c486c2046457f4dd` on `phase1-doctype-scaffold`  
**App tip (this review):** `6ee6cb9f6b4287fb871cd8cb23c544f77c8fa691` (`6ee6cb9`) — ChatGPT blockers: commercial lock terminals, revision-bound Approval+consume, Countered `approved_rate` NULL  
**Prior app tip:** `3d9ac65` — D6 `accept_counter` BUYER_UNRESOLVED (still holds)  
**Gate 2 CI tip (evidence):** `6ee6cb9` — Smoke **75** + Bench **75** green (run [34960445631](https://github.com/AnubhavDubey02/fresko-universe/actions/runs/34960445631)); prior green `3d9ac65` 58/61 run 34957061073; `d785b63` 56/59 run 34954607466. Docs tip may be ahead (`40e9e56`).  
**Statuses:** FSEC-001/002/003 **MITIGATED** (re-verified on `6ee6cb9`; FSEC-002 strengthened); ChatGPT blockers 1–3 **independently verified PASS / MITIGATED** (see Closed notes); FSEC-004/005 **OPEN — Phase 2 entry**; FSEC-006 **OPEN — before production**; FSEC-007+ remain **OPEN**.  
Fresko is **not** declared secure. Hold merge / no Phase 2. Verdict: **SECURITY_OK_TO_HOLD**. Full re-attack: `/workspace/fresko-security-reattack-6ee6cb9.md`.

Severity gate: CRITICAL/HIGH require fix or documented human override before production.

---

## FSEC-001 — Whitelist commercial methods lack role/ownership checks

| Field | Value |
|---|---|
| **SEVERITY** | HIGH |
| **STATUS** | **MITIGATED** |
| **Prerequisites** | Any authenticated Desk/API user who can call `@frappe.whitelist` methods |
| **Component** | `fresko_universe/permissions.py`, `deals.py`, `container.py`, `fresko_container.py` |
| **Original impact** | Low-privilege callers could mutate deals / read ATS via whitelist + `ignore_permissions=True` without role/ownership gates (except `accept_counter` / `decide`). |
| **Evidence (pre-fix)** | Ungated `ignore_permissions` on commercial mutators at prior tip `055186d`. |
| **Fix (observed at tip)** | Central ACL in `permissions.py`; every listed mutator calls assert_* **before** `ignore_permissions`. |
| **Regression test** | Offline: `TestFSEC001WhitelistACL` in `fresko_universe/tests/test_smoke_unit.py`. Bench (site): `fresko_universe.tests.test_fsec_permissions` (`test_accounts_denied_cancel_and_apply_rate`, `test_salesperson_cancel_own_allowed_other_denied`, `test_salesperson_denied_record_dispatch`). |

### VERIFICATION (independent re-verify — tip `fdbd9bd`)

| Method | Gate (file:line) | Before `ignore_permissions`? |
|---|---|---|
| `apply_rate_rules` | `permissions.py:55` `assert_can_apply_rate_rules` via `deals.py:31` | Yes (`deals.py:84`) |
| `cancel_deal` | `permissions.py:68` via `deals.py:156` | Yes (`deals.py:166`) |
| `record_dispatch` | `permissions.py:81` via `deals.py:182` | Yes (`deals.py:236`) |
| `set_dispatched_qty` | shim → `record_dispatch` (`deals.py:386-388`) | Same gate |
| `request_revision` | `permissions.py:92` via `deals.py:257` | Yes (`deals.py:292`) |
| `apply_revision` | `permissions.py:105` via `deals.py:312` (+ FSEC-002 bind) | Yes (`deals.py:363`) |
| `container.snapshot` | `permissions.py:157` via `container.py:16` | N/A (read) |
| `container_snapshot` (doctype) | same assert at `fresko_container.py` whitelist | N/A (read) |
| `accept_counter` | ownership ACL `deals.py:125-133` (pre-existing D4) | Yes (`deals.py:145`) |
| `approvals.decide` | role gate `approvals.py:38-40` (pre-existing) | Yes |

Offline smoke for Accounts deny / stranger cancel / Salesperson dispatch deny / snapshot Guest deny: **18/18 FSEC smoke classes green** (FSEC-001 subset ok).

**TEST RESULTS (Gate 2 CI — tip `d785b63`):** GREEN — CI run [34954607466](https://github.com/AnubhavDubey02/fresko-universe/actions/runs/34954607466): Smoke **56** + Bench **59** including FSEC permission tests (`test_fsec_permissions`). Intermediate red on `f7db7c3` was FSEC `make_deal` fingerprint collisions; fixed by `d785b63` test hygiene only — Gate1/D4/D10 not weakened. Hold merge / no Phase 2. Status remains **MITIGATED** (not reopened; not declared secure).

**TEST RESULTS (Gate 2 CI — tip `3d9ac65`, independent Security review 2026-09-15):** GREEN — CI run [34957061073](https://github.com/AnubhavDubey02/fresko-universe/actions/runs/34957061073) `head_sha=3d9ac65…`, conclusion **success**: Smoke **58** + Bench **61**. App delta vs `d785b63`/`fdbd9bd`: **+1 line** `_maybe_open_buyer_unresolved(deal)` in `accept_counter` + D6 tests only — **no** `permissions.py` / `hooks.py` change. D4 ownership ACL still before `ignore_permissions`. FSEC-001 remains **MITIGATED**. Hold merge / no Phase 2.

**RE-ATTACK (tip `6ee6cb9`, independent Security 2026-09-15):** PASS — whitelist ACL gates unchanged in order (assert_* / D4 / role **before** `ignore_permissions`). Tip adds Approver Desk write Proposed-only (`permissions.py` deal_has_permission) and commercial lock terminals; does **not** weaken FSEC-001. Gate2 **75/75** green run 34960445631. FSEC-001 remains **MITIGATED**. Hold merge / no Phase 2.


### RESIDUAL (accepted under MITIGATED — not reopened)

- `ignore_permissions` remains on authorized paths by design (status/commercial flags).
- Approver may cancel/dispatch **any** Deal (matrix-aligned; not ownership-scoped).
- Helper `_open_exception` / `_resolve_buyer_exceptions` still `ignore_permissions` but only reachable after gated callers.

---

## FSEC-002 — `apply_revision` accepts any existing Approval name (no bind / decision check)

| Field | Value |
|---|---|
| **SEVERITY** | HIGH |
| **STATUS** | **MITIGATED** |
| **Prerequisites** | Ability to call `apply_revision`; existence of any `Fresko Approval` document in the site |
| **Component** | `deals.py:apply_revision`, `permissions.py` |
| **Original impact** | Material fields could apply with any existing Approval name (`exists()` only); no Deal bind, decision allowlist, or Approver role. |
| **Evidence (pre-fix)** | Prior `apply_revision` at `055186d` used `frappe.db.exists` only. |
| **Fix (observed at tip)** | Role + bind + decision + stale checks before save. |
| **Regression test** | Offline: `TestFSEC002ApplyRevisionBind`. Bench: `test_apply_revision_rejects_mismatched_approval_deal`, `test_apply_revision_rejects_non_approver`, `test_apply_revision_rejects_reject_decision`. |

### VERIFICATION (independent re-verify — tip `fdbd9bd`)

| Check | Location | Result |
|---|---|---|
| Caller Approver/SM | `assert_can_apply_revision` `permissions.py:105-112`; called `deals.py:312` | Present |
| Approval.deal == revision parent Deal | `assert_approval_bound_for_revision` `permissions.py:115-124`; `deals.py:337-338` | Present |
| Decision ∈ {APPROVE, OVERSELL_OVERRIDE} | `permissions.py:125-133` + `APPROVAL_APPLY_DECISIONS` | Present |
| Stale Approval reuse | `assert_approval_not_stale` `permissions.py:136-154` | Present |
| `exists()`-only | Removed as sole gate; still used as presence check then full load | OK |

`exists()`-only is **not** sufficient anymore. Offline mismatch / REJECT / non-approver tests: **ok**.

### VERIFICATION (independent re-attack — tip `6ee6cb9`)

| Check | Location | Result |
|---|---|---|
| Approval.`revision` + `consumed` fields | `fresko_approval.json` | Present |
| `create_revision_approval` | `approvals.py` + `assert_can_create_revision_approval` | Present |
| Exact revision bind (not Deal-only) | `assert_approval_bound_for_revision(..., revision=rev)` `permissions.py`; called `deals.py` material path | Present — Deal-only rejected |
| Consume / replay | `assert_approval_not_consumed` + `_mark_approval_consumed` | Present |
| Stale old_value + Applied reuse | `_assert_revision_old_value_matches_deal` + `assert_approval_not_stale` | Present |
| Bench/smoke | `test_apply_revision_*` (unbound/mismatch/consume/replay) | Green in Gate2 75/75 |

FSEC-002 remains **MITIGATED** and is **stronger** than Deal-only bind (ChatGPT blocker 2 closed in code). Hold merge / no Phase 2.

### RESIDUAL (accepted under MITIGATED)

- Any Fresko Approver may apply a bound APPROVE Approval (Approval.`approver` identity not required to match session user).
- Non-material revision fields still apply with Approver/SM role alone (no Approval doc) — by design.

---

## FSEC-003 — No `has_permission` / `permission_query`; coarse Desk write

| Field | Value |
|---|---|
| **SEVERITY** | HIGH |
| **STATUS** | **MITIGATED** |
| **Prerequisites** | Authenticated user with Fresko role perms from DocType JSON |
| **Component** | `hooks.py`, `permissions.py` (Deal + Evidence) |
| **Original impact** | Salesperson write-all Deals; no row-level query; no `has_permission` hooks. |
| **Evidence (pre-fix)** | Zero permission hooks under app; `fresko_deal.json` Salesperson write=1. |
| **Fix (observed at tip)** | Hooks wired; Salesperson owner/`salesperson_user` scoped; Desk write only while Proposed; Accounts read-only in `deal_has_permission`. |
| **Regression test** | Offline: `TestFSEC003DealPermissionHooks`. Bench: `test_permission_query_two_sales_users`. |

### VERIFICATION (independent re-verify — tip `fdbd9bd`)

| Control | Location | Result |
|---|---|---|
| `permission_query_conditions` Deal+Evidence | `hooks.py:34-37` | Wired |
| `has_permission` Deal+Evidence | `hooks.py:39-42` | Wired |
| Salesperson list filter owner\|salesperson_user | `deal_permission_query` `permissions.py:168-183` | Present |
| Salesperson write only own + Proposed | `deal_has_permission` `permissions.py:210-226` | Present |
| Accounts read-only via hook | `permissions.py:202-203` | Present |
| Salesperson write-all via hook | Denied (foreign write False in smoke) | Mitigated |

### RESIDUAL (keep noted — status remains MITIGATED, not reopened)

- **DocType JSON still coarse:** `fresko_deal.json` still grants Fresko Salesperson `write=1` globally; row/doc ACL depends on Python hooks loading correctly (defense-in-depth gap if hooks mis-registered).
- **Other DocTypes:** Container / Revision / Approval / Exception have **no** `permission_query` / `has_permission` hooks (Approver still RWC on Container via JSON alone).
- **Evidence without `deal`:** `evidence_has_permission` allows Salesperson create/read/write when deal is unset (`permissions.py:293-295`).
- **Prior residual (bench not run) UPDATED:** Gate 2 bench green on tip `d785b632803948d9b1b6c6a54423db143f50c0ca` (`d785b63`) includes FSEC permission tests (bench **59**). CI run 34954607466 success (Smoke 56 + Bench 59). See `docs/GATE2_CI_RESULT.md`. Intermediate red on `f7db7c3` was FSEC `make_deal` fingerprint collisions fixed by `d785b63` test hygiene — Gate1/D4/D10 not weakened. Hold merge / no Phase 2. FSEC-003 remains **MITIGATED** (not declared secure).
- **Tip `3d9ac65` re-check:** `hooks.py` still wires Deal+Evidence `permission_query_conditions` / `has_permission`; offline smoke `TestFSEC003*` green within 58. No hook regression from D6 fix. FSEC-003 remains **MITIGATED**.
- **Tip `6ee6cb9` re-attack:** hooks still wired; Approver Desk write now Proposed-only (aligned with Salesperson); Cancelled/Rejected/Disputed Desk write denied for non-SM. Offline `TestFSEC003*` green within 75. FSEC-003 remains **MITIGATED** (JSON coarse write residual unchanged).

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
| **Impact** | Secrets, vulnerable Actions/deps, and authz regressions can merge on green smoke/bench alone. Gate 2 tip `6ee6cb9` is green (Smoke 75 + Bench 75, run 34960445631; prior `3d9ac65` 58/61; `d785b63` 56/59) but CI still lacks SAST/secret/dep/permission jobs — security signal remains incomplete. |
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

- Gate 1 empty rate band fail-closed: **implemented** (`rate_rules.policy_resolved`, `apply_rate_rules` RATE_POLICY_MISSING). **Re-verified PASS** at `6ee6cb9`.
- D4 accept_counter ACL: **implemented** with tests (intact at `3d9ac65` and `6ee6cb9`; SM/Approver cannot accept on behalf).
- D6 Countered→Approved BUYER_UNRESOLVED: **fixed** at `3d9ac65` — still called from `accept_counter` at `6ee6cb9` after rate copy + Approved. Residual: multi-doc atomicity ASSUMPTION.
- D10 SM-only oversell: **implemented** with tests (unchanged by `6ee6cb9`).
- Desk `approved_rate` / `dispatched_qty` locks: **implemented**.
- **ChatGPT blocker 1 (commercial immutability / Cancelled·Rejected·Disputed):** **independently verified PASS / MITIGATED** at `6ee6cb9` — `COMMERCIAL_LOCK_STATUSES` + `_enforce_commercial_lock` + Approver/Sales Desk write Proposed-only. Free Desk mutation blocked; controlled revision path remains. Report: `fresko-security-reattack-6ee6cb9.md`.
- **ChatGPT blocker 2 (Approval.revision exact bind + consume/stale):** **independently verified PASS / MITIGATED** at `6ee6cb9` — strengthens FSEC-002. Deal-only Approvals rejected for material apply; consume blocks replay.
- **ChatGPT blocker 3 (Countered approved_rate NULL until accept_counter):** **independently verified PASS / MITIGATED** at `6ee6cb9` — COUNTER stores `decision_rate` on Approval only; `accept_counter` copies into `approved_rate`.
- No committed cloud API keys found in history scan (this baseline).
- **Not a merge certificate / not declared secure.** FSEC-004+ remain OPEN.
