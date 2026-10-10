"""Seeded upgrade proof: preserve legacy truth, fabricate no intake records."""
from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import frappe

DOCTYPES = ('Fresko Intake Draft', 'Fresko Intake Revision')
STATE = 'intake_upgrade_seed.json'
FIRST = 'intake_upgrade_first.json'
LEGACY = ('Fresko Container', 'Fresko Container Lot', 'Fresko Deal', 'Fresko Evidence',
          'Fresko Outward', 'Fresko Commercial Sale', 'Fresko Sale Outward Allocation',
          'Fresko Collection', 'Fresko Payment Allocation')


def _snapshot():
    result = {}
    for doctype in LEGACY:
        if frappe.db.table_exists(doctype, cached=False):
            rows = frappe.db.sql(f'SELECT * FROM `tab{doctype}` ORDER BY name', as_dict=True)
            result[doctype] = json.loads(json.dumps(rows, sort_keys=True, default=str))
    return result


def _write(name, value):
    path = Path(frappe.get_site_path('private', name)); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + '\n')


def _read(name):
    return json.loads(Path(frappe.get_site_path('private', name)).read_text())


def _seed():
    from fresko_universe.tests.utils import ensure_masters, make_container
    frappe.set_user('Administrator')
    for doctype in DOCTYPES:
        assert not frappe.db.table_exists(doctype), f'Unexpected baseline table: {doctype}'
    container = make_container(ensure_masters(), container_no='INTAKE-UPGRADE-SYNTHETIC', inward_qty=7)
    frappe.get_doc({'doctype': 'Fresko Evidence', 'evidence_type': 'Note',
        'container': container.name, 'notes': 'Synthetic upgrade sentinel, unresolved',
        'content_sha256': sha256(b'intake synthetic migration sentinel').hexdigest()}).insert(ignore_permissions=True)
    frappe.db.commit()
    legacy = _snapshot()
    assert legacy.get('Fresko Container') and legacy.get('Fresko Evidence'), 'Current baseline sentinels required'
    _write(STATE, legacy)


def seed_phase1():
    """Phase1 precedes ERPNext masters; reuse registry-seeded legacy sentinels."""
    frappe.set_user('Administrator')
    for doctype in DOCTYPES:
        assert not frappe.db.table_exists(doctype), f'Unexpected baseline table: {doctype}'
    legacy = _snapshot()
    # Phase1 registry deliberately has populated Deal/Evidence, no ERPNext
    # Company/Container masters. Exact PR22 additionally proves Container rows.
    assert legacy.get('Fresko Deal') and legacy.get('Fresko Evidence'), 'Registry legacy sentinels required'
    _write(STATE, legacy)


def seed_current_baseline():
    """Additional exact PR22-to-candidate proof using the same assertions."""
    _seed()


def _assert_schema_empty():
    for doctype in DOCTYPES:
        assert frappe.db.exists('DocType', doctype)
        assert frappe.db.count(doctype) == 0, f'Migration fabricated {doctype}'
        indexes = frappe.db.sql(f'SHOW INDEX FROM `tab{doctype}`', as_dict=True)
        field = 'proposal_key' if doctype.endswith('Draft') else 'revision_key'
        assert any(row.Column_name == field and not row.Non_unique for row in indexes)
    for field in ('sequence_key',):
        indexes = frappe.db.sql('SHOW INDEX FROM `tabFresko Intake Revision`', as_dict=True)
        assert any(row.Column_name == field and not row.Non_unique for row in indexes)


def verify_first_migrate():
    _assert_schema_empty()
    current = _snapshot()
    # Later baseline-to-current proofs may add columns to legacy tables: compare
    # precisely the columns/rows present at seed, without inventing old values.
    seeded = _read(STATE)
    for doctype, original in seeded.items():
        actual = {r['name']: r for r in current[doctype]}
        assert set(actual) == {r['name'] for r in original}, f'Migration changed row identities: {doctype}'
        for row in original:
            assert {k: actual[row['name']][k] for k in row} == row, doctype
    for doctype in current.keys() - seeded.keys():
        assert not current[doctype], f'Migration fabricated legacy truth: {doctype}'
    _write(FIRST, current)


def verify_second_migrate():
    _assert_schema_empty()
    assert _snapshot() == _read(FIRST), 'Repeated migrate changed legacy truth'
