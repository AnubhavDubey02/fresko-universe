# Schema-migration proof rule

**Status:** Current rule for schema-changing pull requests

**Reviewed:** 2026-10-03

## Rule

A pull request that changes a persisted schema must add a seeded upgrade proof.
Examples include adding, removing, or retyping a DocType field, changing a child
table, or adding a `patches.txt` entry that rewrites stored rows. The proof is
a `scripts/prove_*.py` module registered in `scripts/schema_migration_proofs.json`.
A pull request that does not change a persisted schema does not add a proof.

Each proof module defines three module-level functions:

| Stage | Runs against | Must prove |
|---|---|---|
| `seed_phase1()` | the exact Phase 1 baseline (`FRESKO_PHASE1_SHA`) after install | Seeds only synthetic rows and records their pre-upgrade state under the site's private files. |
| `verify_first_migrate()` | the current candidate after the first `bench migrate` | Legacy rows are preserved or deterministically transformed. Unknown legacy values remain `UNKNOWN`/`PENDING`, and no business fact is invented. |
| `verify_second_migrate()` | the current candidate after a second `bench migrate` | The second migration is a no-op relative to the first-migrate snapshot. |

A proof uses synthetic, non-resolving identifiers only. It must not infer or
confirm customer identity, rate, GP, lot or payment allocation, bank clearance,
quantity, evidence, or timestamps.

## How it runs

`scripts/run_schema_migration_harness.py` loads the registry and runs each
stage for every registered proof in declared order, in one Frappe connection.
`scripts/ci_bench.sh` calls it once per stage on a disposable upgrade site.

A stage is fail-fast, not atomic across proofs. Proofs own their commits, so a
failure stops later proofs but does not undo an earlier proof's committed seed
or snapshot. The upgrade site must be recreated after any failure. Proofs
should keep their state-file names unique.

## Offline gate

The Smoke job runs `python3 scripts/run_schema_migration_harness.py --validate-only`
and its unit tests. The offline gate fails when:

- the registry is malformed, or has a duplicate id or path;
- a registered path escapes the repository;
- a proof is missing any of the three stage functions;
- a `scripts/prove_*.py` module exists but is not registered.

The offline gate proves registration and shape only. Migration safety is shown
only by the pinned Bench run at the exact pull-request head, and only for the
assertions each proof makes.

## Automatic schema-change detection

`scripts/schema_snapshot.json` records the persisted shape of every Fresko
DocType: column-defining field properties and DocType storage properties.
Labels, descriptions, permissions, and layout fields are excluded. The snapshot
also records the line-ending-normalized hash of every source that runs DDL or a
data migration during install or migrate (`install.py`, `patches.txt`, and patch
modules), plus the registered proof ids.

`scripts/check_schema_snapshot.py --check` runs in the Smoke job. It fails when:

- the committed snapshot no longer matches the repository; or
- on a pull request, the schema differs from the base branch's snapshot but no
  new proof id was registered. A hand-edited snapshot therefore cannot hide a
  schema change.

When you intend a schema change, add and register the proof first, then run
`python3 scripts/check_schema_snapshot.py --update`. The update refuses an
unproven schema change. Any edit to `install.py` or a patch module counts as a
schema-source change, because those files run DDL or data migration.

The detector checks declared schema only. It cannot judge whether a proof's
assertions are adequate; review and pinned Bench still decide that.

## 2026-10-03 Commercial Sale Ledger proof registration

The Commercial Sale backend slice adds `Fresko Commercial Sale`, `Fresko Commercial Sale Line`, `Fresko Party Alias Mapping`, and `Fresko Sale Outward Allocation`, with an additional `commercial_scope_key` index on `Fresko Exception`.
- Registered as the fifth proof `commercial_sale_ledger` (`scripts/prove_commercial_sale_upgrade.py`) in `scripts/schema_migration_proofs.json`.
- Implements `seed_phase1()`, `verify_first_migrate()`, and `verify_second_migrate()`.
- Verifies that selected legacy Deal, Container, Lot, Exception, and Outward field values remain unchanged (`_legacy_snapshot()`, with deterministic driver-value serialization).
- Proves zero commercial fabrication: counts on newly introduced commercial DocTypes start strictly at 0 rows.
- Includes `seed_current_main()` for proving upgrades directly from current `main` at `579a8465f363105eb6e78c15cb173156e2c0df93`.
