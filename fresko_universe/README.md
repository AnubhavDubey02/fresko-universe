# fresko_universe

Frappe/ERPNext v15 custom app implementing Fresko Universe Phase 0+1:
**Fresko Container**, **Fresko Deal**, and companion DocTypes
(Approval, Revision, Evidence, Exception).

## Install (bench)

```bash
# From your bench directory
bench get-app /path/to/fresko-universe-repo/fresko_universe
# or from GitHub (after merge):
# bench get-app https://github.com/AnubhavDubey02/fresko-universe --branch phase1-doctype-scaffold
# then move/use the fresko_universe subfolder as the app root, OR:
cd apps && ln -s ../fresko-universe/fresko_universe fresko_universe  # if monorepo layout

bench --site <site> install-app fresko_universe
bench --site <site> migrate
```

**Monorepo note:** This repository contains docs + the installable app under
`fresko_universe/`. Point `bench get-app` at the `fresko_universe/` subdirectory
(the folder that contains `hooks.py` / `pyproject.toml`), or clone and:

```bash
bench get-app ./fresko_universe   # path to app package root
```

## Roles created on install

- `Fresko Salesperson`
- `Fresko Approver`
- `Fresko Accounts`

## Naming series

- Containers: `CON-.YYYY.-.`
- Deals: `DEAL-.YYYY.-.`

## Whitelist APIs

| Method | Purpose |
|---|---|
| `fresko_universe.deals.apply_rate_rules` | Band/stock → Auto Approved or Approval Required |
| `fresko_universe.approvals.decide` | Approver APPROVE / COUNTER / REJECT / OVERSELL_OVERRIDE |
| `fresko_universe.deals.request_revision` | Post-approval commercial change request |
| `fresko_universe.deals.accept_counter` | D4: originator accepts counter → Approved |
| `fresko_universe.container.snapshot` | ATS / inward / approved_sold |

## Versions (Gate 2)

Pinned Frappe/ERPNext v15 SHAs: see repo `docs/VERSIONS.md` and `.github/frappe-versions.json`.
CI: `.github/workflows/ci.yml` (smoke-unit + full bench).

## Tests

### With full bench (preferred)

```bash
bench --site <site> run-tests --app fresko_universe
```

### Without Frappe installed (smoke / unit mocks)

```bash
cd fresko_universe
python -m pytest tests/test_smoke_unit.py -v
# or
python -m unittest tests.test_smoke_unit -v
```

See `docs/PHASE1_BLUEPRINT_FINAL.md` §I for acceptance coverage list.

## Out of scope (Phase 1)

WhatsApp, AI/OCR, payments, QC, partner portal, Sales Order / Delivery Note / Stock Entry posting.


## Sample fixtures

`fresko_universe/fixtures/drive/SAMPLE_*.xlsx` — lot / buyer / rate samples for tests.
Drive originals referenced in `docs/SOURCES.md`. WhatsApp zip is Phase 2 only.
