"""Offline preservation assertions; native schema/DDL proof remains separate."""
import copy
import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


class IntakeUpgradeProofTests(unittest.TestCase):
    def setUp(self):
        source = Path(__file__).with_name('prove_intake_upgrade.py')
        spec = importlib.util.spec_from_file_location('intake_upgrade_test', source)
        self.proof = importlib.util.module_from_spec(spec)
        self.frappe = SimpleNamespace(set_user=Mock(), db=SimpleNamespace(table_exists=Mock(return_value=False)))
        with patch.dict(sys.modules, {'frappe': self.frappe}):
            spec.loader.exec_module(self.proof)
        self.legacy = {'Fresko Container': [],
            'Fresko Deal': [{'name': 'SYNTHETIC-DEAL', 'qty': None, 'buyer_alias': '  raw  '}],
            'Fresko Evidence': [{'name': 'SYNTHETIC-EVIDENCE', 'content_sha256': None}]}

    def test_phase1_reuses_populated_deal_and_evidence_without_company_masters(self):
        with patch.object(self.proof, '_snapshot', return_value=self.legacy), patch.object(self.proof, '_write') as write:
            self.proof.seed_phase1()
        write.assert_called_once_with(self.proof.STATE, self.legacy)

    def test_phase1_rejects_vacuous_or_missing_source_sentinels(self):
        for doctype in ('Fresko Deal', 'Fresko Evidence'):
            legacy = copy.deepcopy(self.legacy); legacy[doctype] = []
            with self.subTest(doctype=doctype), patch.object(self.proof, '_snapshot', return_value=legacy), patch.object(self.proof, '_write') as write:
                with self.assertRaises(AssertionError): self.proof.seed_phase1()
                write.assert_not_called()

    def verify(self, current):
        with patch.object(self.proof, '_assert_schema_empty'), patch.object(self.proof, '_snapshot', return_value=current), patch.object(self.proof, '_read', return_value=self.legacy), patch.object(self.proof, '_write') as write:
            self.proof.verify_first_migrate()
        write.assert_called_once_with(self.proof.FIRST, current)

    def test_new_columns_and_empty_new_tables_preserve_existing_truth(self):
        current = copy.deepcopy(self.legacy)
        current['Fresko Deal'][0]['new_column'] = None
        current['Fresko Outward'] = []
        self.verify(current)

    def test_unknown_quantity_cannot_be_manufactured_as_zero(self):
        current = copy.deepcopy(self.legacy); current['Fresko Deal'][0]['qty'] = 0
        with self.assertRaises(AssertionError): self.verify(current)

    def test_existing_rows_cannot_be_deleted(self):
        current = copy.deepcopy(self.legacy); current['Fresko Evidence'] = []
        with self.assertRaises(AssertionError): self.verify(current)

    def test_existing_tables_cannot_gain_fabricated_rows(self):
        current = copy.deepcopy(self.legacy); current['Fresko Container'].append({'name': 'FABRICATED'})
        with self.assertRaises(AssertionError): self.verify(current)

    def test_new_business_tables_cannot_gain_fabricated_rows(self):
        current = copy.deepcopy(self.legacy); current['Fresko Outward'] = [{'name': 'FABRICATED'}]
        with self.assertRaises(AssertionError): self.verify(current)


if __name__ == '__main__': unittest.main()
