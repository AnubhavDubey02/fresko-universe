# fresko-universe

Produce-trade operations OS on **Frappe / ERPNext v15** (provisional pin).

This repository is a monorepo:

| Path | Contents |
|---|---|
| `fresko_universe/` | Installable Frappe app (`fresko_universe`) — Phase 0+1 Container + Deal |
| `docs/` | Blueprint, decisions, sources, deviations |

## Quick start

```bash
# Installable app root is fresko_universe/ (contains pyproject.toml + hooks)
bench get-app ./fresko_universe
bench --site <site> install-app fresko_universe
bench --site <site> migrate
bench --site <site> run-tests --app fresko_universe
```

### Without bench (smoke tests)

```bash
cd fresko_universe
python -m unittest tests.test_smoke_unit -v
```

See `fresko_universe/README.md` for whitelist APIs and roles.

## Locked decisions (Phase 1)

D1 no SO/DN/SLE on approve · D3 PROPOSED does not reduce ATS · D4 COUNTERED needs accept · D5 rate floor hierarchy · D6 unresolved buyer + BUYER_UNRESOLVED · D10 Owner/Admin oversell override only.

## Phase 2 note

WhatsApp Drive zip is listed in `docs/SOURCES.md` only — **not** unpacked or implemented here.
