import os
import pathlib
import json
from decimal import Decimal

bench_sites = pathlib.Path("/home/dshri/.local/state/fresko-control/group-1b/runtime/frappe-bench/sites")
os.chdir(bench_sites)

import frappe
from frappe.utils import now_datetime
from fresko_universe import outward, quantity_assertion, commercial, money
from fresko_universe.tests.test_commercial_sale import _ensure_user
from fresko_universe.fresko_core.services.quantity_assertion_service import quantity_reconciliation_projection
import fresko_universe.reporting_engine as reporting_engine

def seed():
    frappe.init(site="group1b-qa.localhost")
    frappe.connect()
    if not all(frappe.conf.get(key) for key in (
        "allow_tests", "fresko_disposable_browser_site", "fresko_browser_fixture_only"
    )):
        raise RuntimeError("Reporting fixtures require an explicitly disposable test site")
    frappe.set_user("Administrator")

    container_name = "CON-2026-00479"
    doc = frappe.get_doc("Fresko Container", container_name)
    company = doc.company
    assert company == "Wind Power LLC"
    uom = doc.uom
    assert uom == "Kg"
    lot_no = doc.lots[0].lot_no
    assert lot_no == "LOT-A"

    # Dedicated clean actors without Company User Permission
    sales_maker = _ensure_user("seed_sales_maker@example.invalid", ["Fresko Salesperson"])
    comm_accounts = _ensure_user("seed_comm_accounts@example.invalid", ["Fresko Accounts"])
    comm_approver = _ensure_user("seed_comm_approver@example.invalid", ["Fresko Approver"])

    money_maker = _ensure_user("seed_money_maker@example.invalid", ["Fresko Accounts"])
    money_checker = _ensure_user("seed_money_checker@example.invalid", ["Fresko Accounts"])
    money_approver = _ensure_user("seed_money_approver@example.invalid", ["Fresko Approver"])

    # 1. Evidence
    evidence = frappe.get_doc({
        "doctype": "Fresko Evidence",
        "container": container_name,
        "evidence_type": "Note",
        "notes": "Authoritative synthetic reporting acceptance evidence"
    }).insert(ignore_permissions=True)
    frappe.db.commit()

    # 2. Quantity Assertions
    proj = quantity_reconciliation_projection(container_name)
    if not proj.get("declared_assertion"):
        frappe.set_user(sales_maker)
        decl = quantity_assertion.create(
            container=container_name, basis="DECLARED_SHIPPING", raw_value="100.0",
            quantity="100.0", uom=uom, raw_uom=uom, evidence=evidence.name,
            effective_at="2026-10-01 10:00:00", provenance="SOURCE_EXTRACTED",
            reason="Authoritative declared shipping", source_fact_id="fact-decl-acceptance-1"
        )
        quantity_assertion.submit(decl["name"])
        frappe.set_user(comm_approver)
        quantity_assertion.review(decl["name"], "ACTIVATE")
        frappe.db.commit()

    proj = quantity_reconciliation_projection(container_name)
    if not proj.get("operating_assertion"):
        frappe.set_user(sales_maker)
        op = quantity_assertion.create(
            container=container_name, basis="OPERATING_INWARD", raw_value="100.0",
            quantity="100.0", uom=uom, raw_uom=uom, evidence=evidence.name,
            effective_at="2026-10-01 10:00:00", provenance="SOURCE_EXTRACTED",
            reason="Authoritative operating inward", source_fact_id="fact-op-acceptance-1"
        )
        quantity_assertion.submit(op["name"])
        frappe.set_user(comm_approver)
        quantity_assertion.review(op["name"], "ACTIVATE")
        frappe.db.commit()

    # 3. Physical Outward (posted)
    outward_exists = frappe.db.get_value("Fresko Outward", {"container": container_name, "status": "Posted"}, "name")
    if not outward_exists:
        frappe.set_user(sales_maker)
        outw = outward.create(
            container=container_name, movement_at="2026-10-02 10:00:00",
            source_evidence=evidence.name, source_event_id="reporting:outward:acceptance-1",
            lines=[{
                "source_line_ref": "1", "raw_lot_text": lot_no, "lot_no": lot_no,
                "qty": "25.0", "uom": uom, "raw_qty_text": "25.0", "raw_uom_text": uom
            }]
        )
        outward.submit_for_review(outw["name"])
        frappe.set_user(comm_approver)
        outward.post(outw["name"])
        frappe.db.commit()
        outward_name = outw["name"]
    else:
        outward_name = outward_exists

    # 4. Customer & Party Alias Mapping
    customer_name = "Acceptance Customer LLC"
    frappe.set_user("Administrator")
    if not frappe.db.exists("Customer", customer_name):
        frappe.get_doc({
            "doctype": "Customer",
            "customer_name": customer_name,
            "customer_type": "Company",
            "customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
            "territory": frappe.db.get_value("Territory", {"is_group": 0}, "name")
        }).insert(ignore_permissions=True)
        frappe.db.commit()

    raw_alias = "Raw Acceptance Buyer"
    alias_row = frappe.db.get_value("Fresko Party Alias Mapping", {"company": company, "raw_alias": raw_alias}, "name")
    if not alias_row:
        frappe.set_user(sales_maker)
        mapping = commercial.propose_alias_mapping(
            company=company, raw_alias=raw_alias, proposed_customer=customer_name,
            evidence=evidence.name, source_event_id="reporting:alias:acceptance-1"
        )
        frappe.set_user(comm_accounts)
        commercial.verify_alias_mapping(mapping["name"])
        frappe.set_user(comm_approver)
        commercial.approve_alias_mapping(mapping["name"])
        frappe.db.commit()

    # 5. Commercial Sale
    sale_exists = frappe.db.get_value("Fresko Commercial Sale", {"container": container_name, "status": "APPROVED"}, "name")
    if not sale_exists:
        frappe.set_user(sales_maker)
        sale_res = commercial.create_sale(
            company=company, container=container_name,
            sale_at="2026-10-02 11:00:00", source_evidence=evidence.name,
            source_event_id="reporting:sale:acceptance-1",
            raw_party_alias=raw_alias, party_state="KNOWN",
            currency="INR", lines=[{
                "line_key": "source-line-1", "source_line_ref": "1",
                "item": doc.item, "container_lot": doc.lots[0].name,
                "raw_lot_text": lot_no, "lot_state": "KNOWN",
                "qty": "25.0", "qty_state": "KNOWN", "uom": uom,
                "rate": "1000.00", "price_state": "PROPOSED",
                "rate_basis": "RATE_ASSERTION", "evidence": evidence.name
            }]
        )
        commercial.submit_sale(sale_res["name"])
        frappe.set_user(comm_accounts)
        commercial.verify_sale(sale_res["name"])
        frappe.set_user(comm_approver)
        commercial.approve_sale(sale_res["name"])
        sale_name = sale_res["name"]
        frappe.db.commit()

    else:
        sale_name = sale_exists

    if not frappe.db.exists("Fresko Sale Outward Allocation", {"sale": sale_name, "state": "APPROVED"}):
        # Allocate sale to outward
        sale_doc = frappe.get_doc("Fresko Commercial Sale", sale_name)
        outw_doc = frappe.get_doc("Fresko Outward", outward_name)
        frappe.set_user(sales_maker)
        so_alloc = commercial.propose_sale_outward_allocation(
            sale_name=sale_name,
            sale_line_key=sale_doc.lines[0].line_key,
            outward=outward_name,
            outward_line_key=outw_doc.lines[0].line_key,
            qty="25.0",
            uom=uom,
            evidence=evidence.name,
            source_event_id="reporting:so_alloc:acceptance-1"
        )
        frappe.set_user(comm_accounts)
        commercial.verify_sale_outward_allocation(so_alloc["name"])
        frappe.set_user(comm_approver)
        commercial.approve_sale_outward_allocation(so_alloc["name"])
        frappe.db.commit()
    # 6. Bank Account & Collections
    bank_acc_name = frappe.db.get_value("Bank Account", {"company": company, "is_company_account": 1}, "name")
    assert bank_acc_name, "Expected an existing company bank account"

    # Cleared collection of 10000.00
    coll_cleared_name = frappe.db.get_value("Fresko Collection", {"company": company, "source_event_id": "reporting:coll:cleared-1"}, "name")
    if not coll_cleared_name:
        frappe.set_user(money_maker)
        coll_cleared = money.create_collection(
            company=company, source_namespace="synthetic-reporting-v1",
            source_event_id="reporting:coll:cleared-1", direction="INFLOW",
            amount="10000.00", currency="INR", payment_channel="BANK",
            bank_state="BANK_CLEARED", source_classification="BANK_CREDIT_CONFIRMATION",
            bank_account=bank_acc_name, bank_reference="REF-BANK-CLEARED-1", rail="RTGS",
            effective_at="2026-10-02 12:00:00", payer_raw="Raw Acceptance Payer",
            source_evidence=evidence.name
        )
        money.submit_collection(coll_cleared["name"])
        frappe.set_user(money_checker)
        money.verify_collection(coll_cleared["name"])
        frappe.set_user(money_approver)
        money.approve_collection(coll_cleared["name"])
        coll_cleared_name = coll_cleared["name"]
        frappe.db.commit()

        # Allocate 10000.00 to sale
        frappe.set_user(money_maker)
        alloc = money.propose_payment_allocation(
            collection=coll_cleared_name, allocation_type="SALE",
            amount="10000.00", currency="INR", evidence=evidence.name,
            source_event_id="reporting:alloc:cleared-1",
            sale=sale_name, container=container_name
        )
        money.submit_payment_allocation(alloc["name"])
        frappe.set_user(money_checker)
        money.verify_payment_allocation(alloc["name"])
        frappe.set_user(money_approver)
        money.approve_payment_allocation(alloc["name"])
        frappe.db.commit()

    # Pending bank collection of 5000.00
    coll_pending_name = frappe.db.get_value("Fresko Collection", {"company": company, "source_event_id": "reporting:coll:pending-1"}, "name")
    if not coll_pending_name:
        frappe.set_user(money_maker)
        coll_pending = money.create_collection(
            company=company, source_namespace="synthetic-reporting-v1",
            source_event_id="reporting:coll:pending-1", direction="INFLOW",
            amount="5000.00", currency="INR", payment_channel="BANK",
            bank_state="AUTHORIZATION_INPROCESS", source_classification="RTGS_NEFT",
            rail="RTGS", bank_reference="REF-BANK-PENDING-1",
            effective_at="2026-10-02 13:00:00", payer_raw="Raw Acceptance Payer Pending",
            source_evidence=evidence.name
        )
        money.submit_collection(coll_pending["name"])
        frappe.set_user(money_checker)
        money.verify_collection(coll_pending["name"])
        frappe.set_user(money_approver)
        money.approve_collection(coll_pending["name"])
        coll_pending_name = coll_pending["name"]
        frappe.db.commit()

    # Now verify all 3 reports via reporting_engine using QA accounts user
    frappe.set_user("group1b-http-accounts@example.invalid")
    stock_res = reporting_engine.execute_report("container_stock", container_name)
    sales_res = reporting_engine.execute_report("sales", container_name)
    rec_res = reporting_engine.execute_report("receivables", container_name)

    print("=== Stock Rows ===")
    for r in stock_res["rows"]:
        print(r)

    print("=== Sales Rows ===")
    for r in sales_res["rows"]:
        print(r)

    print("=== Receivables Rows ===")
    for r in rec_res["rows"]:
        print(r)

    frappe.destroy()
    return True

if __name__ == "__main__":
    seed()
