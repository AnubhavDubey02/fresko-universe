"""Additive Evidence ownership proof: historical NULL is never inferred."""
from __future__ import annotations
import json
from pathlib import Path
import frappe

STATE = 'unassigned_evidence_upgrade_seed.json'
FIRST = 'unassigned_evidence_upgrade_first.json'


def _snapshot():
    return json.loads(json.dumps(frappe.db.sql(
        'SELECT * FROM `tabFresko Evidence` ORDER BY name', as_dict=True), default=str))


def _write(name, value):
    Path(frappe.get_site_path('private', name)).write_text(json.dumps(value, sort_keys=True))


def _read(name):
    return json.loads(Path(frappe.get_site_path('private', name)).read_text())


def seed_phase1():
    rows = _snapshot()
    assert rows, 'Earlier registry Evidence sentinel required'
    assert all('evidence_company' not in row for row in rows), 'Ownership field already present at baseline'
    _write(STATE, rows)


def seed_current_baseline():
    seed_phase1()


def verify_first_migrate():
    previous = _read(STATE)
    rows = _snapshot()
    current = {row['name']: row for row in rows}
    assert set(current) == {row['name'] for row in previous}, 'Evidence identities changed'
    for row in previous:
        assert {k: current[row['name']][k] for k in row} == row, 'Historical source changed'
        assert not current[row['name']]['evidence_company'], 'Historical ownership was inferred'
    assert frappe.get_meta('Fresko Evidence').get_field('evidence_company').read_only
    _write(FIRST, rows)


def verify_second_migrate():
    assert _snapshot() == _read(FIRST), 'Repeated migration changed Evidence'
