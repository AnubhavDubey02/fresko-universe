# VERSIONS — pinned Frappe / ERPNext (Gate 2)

Pinned **2026-09-15** for reproducible CI / Docker bench. Do not float to `version-15` HEAD without updating this file **and** `.github/frappe-versions.json`, then verifying migrate + tests.

| Component | Tag | Commit SHA | Tip commit date |
|---|---|---|---|
| **Frappe** | `v15.120.1` | `9f8ae9cd25b6735be345da6cc12e9f5a96050c68` | 2026-09-08 |
| **ERPNext** | `v15.121.2` | `df8b7f9648c2ec4da12db8c4022edc8dd1018c6b` | 2026-09-09 |

Source of pins: `gh api repos/frappe/frappe/commits/version-15` and `…/erpnext/commits/version-15` (matched lightweight release tags above).

Machine-readable pin: [`.github/frappe-versions.json`](../.github/frappe-versions.json).

## Install (exact SHAs)

```bash
# After bench init on version-15:
cd apps/frappe && git fetch --tags && git checkout 9f8ae9cd25b6735be345da6cc12e9f5a96050c68
cd ../erpnext && git fetch --tags && git checkout df8b7f9648c2ec4da12db8c4022edc8dd1018c6b
```

Or use `scripts/ci_bench.sh` which reads `.github/frappe-versions.json`.

## CI

- Primary: `.github/workflows/ci.yml`
  - Job `smoke-unit`: offline Gate 1 / D4 / constants + pin assert (fast)
  - Job `frappe-bench`: runs `scripts/ci_bench.sh` (pinned SHAs → migrate → `run-tests --app fresko_universe`)
- Alternate: `.github/workflows/ci.yml` (inline bench steps; same pins)
- Local fallback: `docker-compose.bench.yml` + `scripts/ci_bench.sh`
- Failures on install / migrate / tests fail the PR (no fake green).

## Runner requirements

Full ERPNext v15 bench init + migrate is **heavy** for default GitHub-hosted runners:

| Resource | Guidance |
|---|---|
| Disk | ≥ 20 GB free (apps + site + node modules) |
| RAM | ≥ 7 GB recommended; OOM risk on stock `ubuntu-latest` during yarn/assets |
| Time | 45–90 minutes typical; workflow `timeout-minutes: 120` |
| Services | MariaDB 10.6, Redis |
| Optional | Use a larger / self-hosted runner if the hosted job OOMs or times out |

Smoke-unit job alone is sufficient for fast feedback; bench job is the Gate 2 merge gate.

## Coverage intent (wired into `bench run-tests --app fresko_universe`)

DocTypes/perms, Approval append-only, immutability, D4 ACL, D10, ATS, cancel dispatched, lot delete, revision+evidence, unresolved buyer, **Gate 1 RATE_POLICY_MISSING** — see `tests/test_smoke_unit.py`, `fresko_universe/tests/test_phase1_acceptance.py`, `fresko_deals/doctype/fresko_deal/test_fresko_deal.py`.
