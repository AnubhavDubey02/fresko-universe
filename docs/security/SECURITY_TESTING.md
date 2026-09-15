# SECURITY_TESTING — current coverage vs needed regressions

**Tip:** `18c5042`.

## RECORDED FACTS — What exists today

### Offline smoke (`fresko_universe/tests/test_smoke_unit.py`)

Runs in CI job `smoke-unit` without bench. Covers:

- Fingerprint shape, D5 rate hierarchy, Gate 1 empty-band semantics
- ATS `commercial_qty_for_ats` (Proposed excluded, cancel keeps dispatched)
- Constants: D10 roles, commercial lock includes Approval Required, salesperson in locked fields
- Static source checks: DocType names, evidence hash field name, approval/revision under core, flag names (`allow_revision_apply`, `allow_dispatch_write`)
- D4 ACL **unit** tests with mocked session user (`test_owner_can_accept`, SM/Approver cannot)
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
| Unit/acceptance business-logic tests | Partial (smoke green; bench last recorded **failed**) |
| SAST (CodeQL/semgrep/bandit) | **Missing** |
| Secret scan (gitleaks/trufflehog) | **Missing** |
| Dependency advisory (pip-audit/OSV) | **Missing** |
| Permission / role matrix tests as CI gate | **Missing** as dedicated job |
| Container image scan | **Missing** (compose only) |

### Controlled red-team posture this baseline

Static analysis + test reading only. **No** live attacks against deployed systems.

## TEST RESULTS

- Local execution of full bench suite: **not re-run** in this Security baseline (environment is ledger-writing box, not a green Gate 2 runner).
- Documented Gate 2 (`docs/GATE2_CI_RESULT.md` @ `6a4db0e`): 52 tests, 11 failed, 8 errors — later commits claim product fixes; tip `18c5042` outcome **UNKNOWN**.

## ASSUMPTIONS

- When bench is green, acceptance tests remain the primary regression net for ATS/D4/D10/Gate1.
- Frappe core CSRF/session tests are out of scope for Fresko app CI.

## UNKNOWN

- Flaky concurrency test reliability under MariaDB isolation levels.
- Whether `ignore_permissions` paths are ever exercised by non-SM in CI (likely always Administrator).

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
