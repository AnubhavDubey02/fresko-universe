from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import check_protected_doctype_writes as guard


class TestProtectedDoctypeWriteGuard(unittest.TestCase):
    def scan(self, source: str):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.py"
            path.write_text(source, encoding="utf-8")
            return guard.scan_file(path)

    def test_read_and_controlled_document_save_are_allowed(self):
        self.assertEqual(
            self.scan(
                "frappe.db.sql('SELECT name FROM `tabFresko Outward` FOR UPDATE')\n"
                "doc.save(ignore_permissions=True)\n"
            ),
            [],
        )

    def test_set_value_against_protected_doctype_fails(self):
        violations = self.scan(
            "frappe.db.set_value('Fresko Outward', 'OUT-1', 'status', 'Posted')\n"
        )
        self.assertEqual(len(violations), 1)

    def test_write_sql_against_protected_table_fails(self):
        violations = self.scan(
            "frappe.db.sql('UPDATE `tabFresko Field Assertion` SET status=%s', ('Active',))\n"
        )
        self.assertEqual(len(violations), 1)

    def test_dynamic_write_sql_fails_closed(self):
        violations = self.scan(
            "table = get_table()\nfrappe.db.sql(f'UPDATE {table} SET status=1')\n"
        )
        self.assertEqual(len(violations), 1)


if __name__ == "__main__":
    unittest.main()
