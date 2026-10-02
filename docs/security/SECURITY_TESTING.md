# SECURITY_TESTING — current coverage vs needed regressions

**Tip:** Gate 2 app tip `3d9ac65a3aed0b64b9d02608b2fec392b40b8273` (`3d9ac65`) on `phase1-doctype-scaffold` (D6 accept_counter BUYER_UNRESOLVED; ACL tip `fdbd9bd` / prior Gate2 `d785b63`).

## RECORDED FACTS — What exists today

### Offline smoke (`fresko_universe/tests/test_smoke_unit.py`)

Runs in CI job `smoke-unit` without bench. Covers:

- Fingerprint shape, D5 rate hierarchy, Gate 1 empty-band semantics
- ATS `commercial_qty_for_ats` (Proposed excluded, cancel keeps dispatched)
- Constants: D10 roles, commercial lock includes Approval Required, salesperson in locked fields
- Static source checks: DocType names, evidence hash field name, approval/revision under core, flag names (`allow_revision_apply`, `allow_dispatch_write`)
- D4 ACL **unit** tests with mocked session user (`test_owner_can_accept`, SM/Approver cannot)
- D6 accept_counter BUYER_UNRESOLVED smoke (`TestD6AcceptCounterBuyerUnresolved` empty vs set customer)
- D10 Approver cannot oversell (mocked `get_roles`)

### Bench suites (require site)

| File | Security-relevant tests (names) |
|---|---|
| `fresko_universe/tests/test_phase1_acceptance.py` | duplicate message/fingerprint, lot membership, floor→Approval Required, Gate1 policy missing, desk edit approved_rate rejected, revision+approval, unresolved buyer blocks Reconciled, illegal status transition, ATS cancel/approved, concurrent over-approve, close blocked w/ exception, D4 counter+accept, decide rejects from Proposed |
| `fresko_deals/.../test_fresko_deal.py` | Similar + qty frozen in Approval Required, oversell override exception, lot inward floor, dispatch desk reject, SM cannot accept_counter unless owner, Gate1 variants |
| `tests/test_constants_and_fingerprint.py` | Transition map, ATS status sets, D10 constant, rate hierarchy |

### CI security tooling

| Signal | Present? |
|---|---|
| Unit/acceptance business-logic tests | Partial (Gate 2 tip `3d9ac65`: smoke **58** + bench **61** green; still no dedicated security scanner jobs) |
| SAST (CodeQL/semgrep/bandit) | **Missing** |
| Secret scan (gitleaks/trufflehog) | **Missing** |
| Dependency advisory (pip-audit/OSV) | **Missing** |
| Permission / role matrix tests as CI gate | **Missing** as dedicated job |
| Container image scan | **Missing** (compose only) |

### Controlled red-team posture this baseline

Static analysis + test reading only. **No** live attacks against deployed systems.

## TEST RESULTS

- **Gate 2 CI green** on tip `3d9ac65a3aed0b64b9d02608b2fec392b40b8273` (`3d9ac65`): Smoke **58** + Bench **61** (includes FSEC permission tests + D6 accept_counter coverage). CI run [34957061073](https://github.com/AnubhavDubey02/fresko-universe/actions/runs/34957061073) success (`head_sha` match confirmed). See `docs/GATE2_CI_RESULT.md`.
- Prior Gate 2 green on `d785b63`: Smoke **56** + Bench **59**, run 34954607466 — still valid for that SHA.
- Local offline re-check (Security review): `python3 -m unittest tests.test_smoke_unit` → **Ran 58 tests … OK**.
- Intermediate red on `f7db7c3` was FSEC `make_deal` fingerprint collisions; fixed by `d785b63` test hygiene — Gate1/D4/D10 not weakened by `3d9ac65`.
- Tip status for `3d9ac65` Gate 2 is **no longer UNKNOWN**. Hold merge / no Phase 2. CI green ≠ secure.

## ASSUMPTIONS

- When bench is green, acceptance tests remain the primary regression net for ATS/D4/D10/Gate1.
- Frappe core CSRF/session tests are out of scope for Fresko app CI.

## UNKNOWN

- Flaky concurrency test reliability under MariaDB isolation levels.
- Whether `ignore_permissions` paths are ever exercised by non-SM in CI (likely always Administrator).
- (Cleared for tip `3d9ac65` / prior `d785b63`: Gate 2 smoke+bench outcome is green — see TEST RESULTS.)

## Needed security regression tests (backlog)

| Priority | Test idea | Maps to finding |
|---|---|---|
| P0 | Role matrix: each whitelist method × {Salesperson, Approver, Accounts, SM, stranger} | FSEC-001 |
| P0 | `apply_revision` rejects Approval for different deal / REJECT decision / non-Approver | FSEC-002 |
| P0 | Salesperson A cannot write Salesperson B’s Deal (after has_permission) | FSEC-003 |
| P1 | Evidence `message_id` uniqueness | FSEC-005 |
| P1 | Evidence hash equals SHA-256 of file bytes | FSEC-004 |
| P1 | RATE_FLOOR_BREACH exception (or documented absence) | FSEC-008 |
| P1 | Burst whitelist calls limited | FSEC-010 |
| P2 | gitleaks clean on PR | FSEC-006/009 |
| P2 | Concurrent approve under load (repeat ATS test) | threat A2 |

## How to run (developers)

```bash
# Offline
cd fresko_universe && python3 -m unittest tests.test_smoke_unit -v

# Bench (pinned) — see scripts/ci_bench.sh / docs/VERSIONS.md
bench --site <site> run-tests --app fresko_universe
```

CI green ≠ secure. Prefer failing closed on missing security jobs over silent absence.
