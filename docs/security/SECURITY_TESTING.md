# SECURITY_TESTING — Fresko Universe

## Principles

- Scanners are **signals**, not proof.
- Prefer tests that encode Fresko business rules (D3 ATS, D4 counter ACL, D5 floors, D10 oversell, Gate 1 fail-closed, immutability).
- Red-team only in **controlled non-production** environments unless Anubhav explicitly authorizes otherwise.
- Human override: Security may block CI per agreed gate; must not autonomously destroy prod data, rotate prod secrets, disable prod, attack third parties, or mutate financial records.

## Current automated coverage (RECORDED FACTS — update with evidence)

| Signal | Location / CI | What it proves | Gaps |
|---|---|---|---|
| Offline smoke (Gate1/D4/constants) | `.github/workflows/ci.yml` smoke-unit | Static contracts / mocked paths | Not full authz matrix |
| Bench `run-tests --app fresko_universe` | Gate 2 job | DocType/server behavior on pinned v15 | Security suite not separate yet |
| Dependency pin file | `.github/frappe-versions.json` | Reproducible platform versions | No CVE scanner in CI yet |

## Planned security suites

Permission matrix tests; whitelist ACL tests; race/idempotency; malicious input; secret scan; dependency advisory report (non-auto-upgrade).
