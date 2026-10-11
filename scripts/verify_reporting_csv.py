"""Reconcile actual downloaded synthetic acceptance CSVs with Decimal arithmetic."""
import argparse
import csv
import hashlib
import json
from decimal import Decimal
from pathlib import Path


def verify(kind, path):
    rows = list(csv.DictReader(path.open(encoding="utf-8-sig", newline="")))
    assert rows, "Empty report export"
    number = lambda row, key: Decimal(row[key])
    if kind == "container_stock":
        total, = [row for row in rows if row["row_type"] == "TOTAL"]
        assert number(total, "operating_inward_qty") == Decimal("100")
        assert number(total, "posted_outward_qty") == Decimal("25")
        assert number(total, "remaining_qty") == Decimal("75")
        assert number(total, "operating_inward_qty") - number(total, "posted_outward_qty") == number(total, "remaining_qty")
        assert total["opening_qty"] == "UNKNOWN", "Missing opening evidence became a number"
    elif kind == "sales":
        line, = [row for row in rows if row["row_type"] == "SALE_LINE"]
        assert line["lot"] == "LOT-A"
        assert number(line, "approved_qty") == number(line, "allocated_qty") == Decimal("25")
        assert number(line, "final_amount") == number(line, "approved_qty") * Decimal("1000")
    elif kind == "receivables":
        total, = [row for row in rows if row["row_type"] == "CURRENCY_TOTAL" and row["currency"] == "INR"]
        assert number(total, "gross_amount") == Decimal("25000")
        assert number(total, "applied_collections") == Decimal("10000")
        assert number(total, "noncash_adjustments") == Decimal("0")
        assert number(total, "outstanding_amount") == Decimal("15000")
        assert number(total, "gross_amount") - number(total, "applied_collections") - number(total, "noncash_adjustments") == number(total, "outstanding_amount")
        pending, = [row for row in rows if row["row_type"] == "COMPANY_BANK_PENDING_UNATTRIBUTED" and row["currency"] == "INR"]
        assert number(pending, "receipt_amount") == Decimal("5000")
        assert pending["bank_state"] == "AUTHORIZATION_INPROCESS"
        assert pending["applied_collections"] == pending["outstanding_amount"] == "UNKNOWN"
    else:
        raise ValueError("Unsupported report")
    return {"report": kind, "file": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "rows": len(rows), "status": "PASS_DECIMAL", "scope": "Synthetic fixture arithmetic; no business posting or bank clearance proof"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", action="append", required=True, help="report=actual_download_path")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    results = [verify(kind, Path(path)) for kind, path in (value.split("=", 1) for value in args.csv)]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"status": "PASS", "checks": results}, indent=2))
    print(f"PASS: {len(results)} actual CSV downloads reconciled using Decimal")
