"""Fresko authenticated, read-only, company-scoped operational reports.

Physical: posted Outward and reversal source rows from canonical physical_snapshot.
Commercial/Money: canonical read projections only. No financial re-estimation.
All reads fail closed and never post, approve, change or persist business data.
"""
from __future__ import annotations

import csv
import re
from datetime import datetime, time
from decimal import Decimal, InvalidOperation
from io import StringIO

import frappe

REPORTS = frozenset({'container_stock', 'sales', 'receivables'})
READ_ROLES = frozenset({'Fresko Accounts', 'Fresko Approver', 'System Manager'})
MAX_ROWS = 1200
MAX_EXPORT_BYTES = 500_000
COLUMNS = {
    'container_stock': (
        'row_type', 'company', 'container', 'container_no', 'lot', 'uom',
        'opening_qty', 'operating_inward_qty', 'posted_outward_qty', 'remaining_qty',
        'state', 'source_references', 'as_of',
    ),
    'sales': (
        'row_type', 'company', 'container', 'sale', 'line_key', 'customer',
        'status', 'lot', 'uom', 'approved_qty', 'allocated_qty',
        'final_amount', 'currency', 'state', 'source_references', 'as_of',
    ),
    'receivables': (
        'row_type', 'company', 'container', 'sale', 'customer', 'currency',
        'gross_amount', 'applied_collections', 'noncash_adjustments',
        'outstanding_amount', 'receipt_amount', 'bank_state', 'state', 'source_references', 'as_of',
    ),
}


def _deny():
    # Same text for missing and foreign targets; no record metadata leakage.
    frappe.throw('Report access unavailable', frappe.PermissionError)


def _bad():
    frappe.throw('Invalid report request', frappe.ValidationError)


def _principal():
    """Fresh session, role and *unique* company permission (same tenant policy as Group1B).

    Company or roles are NEVER taken from caller arguments or document text.
    """
    user = getattr(getattr(frappe, 'session', None), 'user', None)
    if not isinstance(user, str) or not user or user == 'Guest':
        _deny()
    enabled = frappe.db.sql('SELECT enabled FROM `tabUser` WHERE name=%s', (user,))
    if not enabled or not enabled[0][0]:
        _deny()
    roles = {r[0] for r in frappe.db.sql(
        "SELECT role FROM `tabHas Role` WHERE parent=%s AND parenttype='User'", (user,))}
    if any('supplier' in r.casefold() for r in roles) or not roles.intersection(READ_ROLES):
        _deny()
    grants = frappe.db.sql(
        "SELECT for_value, applicable_for FROM `tabUser Permission` "
        "WHERE user=%s AND allow='Company'", (user,), as_dict=True)
    values = {g.for_value for g in grants}
    if len(values) != 1 or any(g.applicable_for for g in grants):
        _deny()
    company = next(iter(values))
    if not company or not frappe.has_permission('Company', doc=company, ptype='read', user=user):
        _deny()
    return user, company


def _container(name, user, company):
    if type(name) is not str or not name.strip() or len(name) > 140:
        _bad()
    try:
        doc = frappe.get_doc('Fresko Container', name)
    except frappe.DoesNotExistError:
        frappe.clear_last_message()
        _deny()
    if doc.company != company or not frappe.has_permission('Fresko Container', doc=doc, ptype='read', user=user):
        _deny()
    return doc


def _cutoff(value):
    if value is None:
        return None
    if type(value) is not str or not value.strip():
        _bad()
    s = value.strip()
    try:
        if len(s) == 10:
            date = datetime.strptime(s, '%Y-%m-%d')
            return datetime.combine(date.date(), time(23, 59, 59))
        for form in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S'):
            try:
                return datetime.strptime(s, form)
            except ValueError:
                pass
    except ValueError:
        pass
    _bad()


def _number(value, field='quantity'):
    if value is None or isinstance(value, bool):
        raise ValueError(f'{field} missing')
    try:
        value = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f'{field} is invalid') from None
    if not value.is_finite():
        raise ValueError(f'{field} is invalid')
    return value


def _display(value):
    return format(value, 'f') if isinstance(value, Decimal) else value


def _row(**kw):
    return {k: _display(v) for k, v in kw.items()}


def _stock(doc, company, cutoff):
    from fresko_universe.fresko_core.physical import physical_snapshot
    from fresko_universe.fresko_core.services.quantity_assertion_service import quantity_reconciliation_projection
    # Canonical operating-inward assertion must agree with lot metadata.
    quantity = quantity_reconciliation_projection(doc.name)
    snapshot = physical_snapshot(doc.name)  # Existing canonical posted-physical reader.
    movements = snapshot['movements']
    lines = snapshot['line_provenance']
    if len(movements) + len(lines) > MAX_ROWS:
        _bad()  # Never silently truncate a financial/stock report.
    references = {}
    unknown = False
    for m in movements:
        if m.movement_type not in ('OUTWARD', 'REVERSAL'):
            unknown = True
        if cutoff is not None:
            if not m.posted_at or not m.movement_at:
                unknown = True
                continue
            try:
                if datetime.fromisoformat(str(m.posted_at)) > cutoff or datetime.fromisoformat(str(m.movement_at)) > cutoff:
                    continue
            except ValueError:
                unknown = True
                continue
        references[m.name] = m
    valid_names = {m.name for m in movements}
    seen = {name: 0 for name in references}
    if len(valid_names) != len(movements):
        unknown = True
    lot_rows = {}
    for lot in doc.lots:
        if not lot.lot_no or lot.lot_no in lot_rows or str(lot.uom) != str(doc.uom):
            unknown = True
            continue
        lot_rows[lot.lot_no] = {'inward': lot.inward_qty, 'net': Decimal(0), 'refs': []}
    unmapped = {'inward': None, 'net': Decimal(0), 'refs': []}
    for line in lines:
        if line.outward not in valid_names:
            unknown = True
            continue
        m = references.get(line.outward)
        if m is None:
            continue
        seen[line.outward] += 1
        try:
            q = _number(line.qty)
        except ValueError:
            unknown = True
            continue
        if q < 0 or line.uom != doc.uom:
            unknown = True
            continue
        dest = lot_rows.get(line.lot_no) if line.lot_no else unmapped
        if dest is None:
            unknown = True
            continue
        dest['net'] += (-q if m.movement_type == 'REVERSAL' else q)
        if m.source_evidence:
            dest['refs'].append(str(m.source_evidence))
        dest['refs'].append(str(m.name))
    if any(count == 0 for count in seen.values()):
        unknown = True
    current = cutoff is None
    try:
        if quantity.get('operating_quantity') is None or quantity.get('uom') != doc.uom:
            operating = None
            unknown = True
        else:
            operating = _number(quantity['operating_quantity'])
        all_lots = sum((_number(r['inward']) for r in lot_rows.values()), Decimal(0))
        if operating is None or operating < 0 or all_lots != operating:
            unknown = True
    except ValueError:
        unknown = True
        operating = None
    total_out = sum((r['net'] for r in lot_rows.values()), Decimal(0)) + unmapped['net']
    if total_out < 0 or (operating is not None and total_out > operating):
        unknown = True
    as_of = cutoff.isoformat(sep=' ') if cutoff else 'LIVE'
    rows = []
    for lot, info in sorted(lot_rows.items()):
        inward = _number(info['inward']) if current and not unknown else None
        remaining = inward - info['net'] if inward is not None else None
        rows.append(_row(row_type='LOT', company=company, container=doc.name, container_no=doc.container_no,
                         lot=lot, uom=doc.uom, opening_qty=None, operating_inward_qty=inward,
                         posted_outward_qty=info['net'] if not unknown else None, remaining_qty=remaining,
                         state=('PROVISIONAL_LEGACY' if quantity.get('operating_basis') == 'LEGACY_UNVERIFIED' else 'KNOWN') if remaining is not None and remaining >= 0 else 'UNKNOWN',
                         source_references='; '.join(sorted(set(info['refs']))), as_of=as_of))
    if unmapped['net'] or unmapped['refs']:
        rows.append(_row(row_type='UNMAPPED_OUTWARD',company=company, container=doc.name,
                         container_no=doc.container_no, lot=None, uom=doc.uom, opening_qty=None,
                         operating_inward_qty=None, posted_outward_qty=unmapped['net'] if not unknown else None,
                         remaining_qty=None, state='UNMAPPED', source_references='; '.join(sorted(set(unmapped['refs']))),as_of=as_of))
    total_in = operating if current and not unknown else None
    total_remaining = total_in - total_out if total_in is not None else None
    qty_reference = quantity.get('operating_assertion')
    rows.append(_row(row_type='TOTAL', company=company, container=doc.name,container_no=doc.container_no,
                     lot=None,uom=doc.uom,opening_qty=None,operating_inward_qty=total_in,
                     posted_outward_qty=total_out if not unknown else None,remaining_qty=total_remaining,
                     state=('PROVISIONAL_LEGACY' if quantity.get('operating_basis') == 'LEGACY_UNVERIFIED' else 'KNOWN') if total_remaining is not None else 'UNKNOWN',
                     source_references=qty_reference,as_of=as_of))
    warnings = ['Opening inventory UNKNOWN: no independently proven opening ledger snapshot.']
    if quantity.get('operating_basis') == 'LEGACY_UNVERIFIED':
        warnings.append('Operating inward uses LEGACY_UNVERIFIED Container compatibility fallback, not a separately verified source assertion.')
    if quantity.get('reconciliation_status') == 'OPEN_VARIANCE':
        warnings.append('Declared shipping versus operating inward has an OPEN_VARIANCE; values are not interchangeable.')
    if quantity.get('reconciliation_status') == 'UNRESOLVED':
        warnings.append('Quantity assertion reconciliation UNRESOLVED; operating inward and remaining are UNKNOWN.')
    if not current:
        warnings.append('Historical inward/remaining UNKNOWN: mutable Container inward is not an as-of assertion.')
    if unknown:
        warnings.append('Integrity issue in inward/lot/movement records: affected totals UNKNOWN.')
    if unmapped['net']:
        warnings.append('Unmapped physical Outward exists: lot assignment requires review.')
    return rows, warnings


def _sales(doc, company, cutoff):
    from fresko_universe import commercial
    view = commercial.get_container_reconciliation(doc.name, cutoff.isoformat(sep=' ') if cutoff else None)
    if view.get('view_scope') != 'INTERNAL' or view.get('container') != doc.name:
        _deny()
    as_of = view['as_of']
    rows, warnings = [], []
    for sale in view['sales']:
        if sale.get('company') != company or sale.get('container') != doc.name:
            _deny()
        status = sale.get('status')
        for line in sale.get('lines') or []:
            qty = None
            if status == 'APPROVED' and line.get('qty_state') == 'KNOWN':
                qty = _display(_number(line['qty']))
            rate_final = status == 'APPROVED' and line.get('price_state') == 'FINAL' and bool(sale.get('currency'))
            amount = _display(_number(line['amount'], 'sale amount')) if rate_final and line.get('amount') is not None else None
            rows.append(_row(row_type='SALE_LINE', company=company, container=doc.name, sale=sale['name'],
                             line_key=line.get('line_key'), customer=sale.get('customer'), status=status,
                             lot=line.get('lot_no') if line.get('lot_state') == 'KNOWN' else None,
                             uom=line.get('uom'),approved_qty=qty,
                             allocated_qty=_display(_number(line['allocated_qty'])) if qty is not None and line.get('allocated_qty') is not None else None,
                             final_amount=amount,currency=sale.get('currency'),
                             state='FINAL' if amount is not None and qty is not None and sale.get('customer') else 'PENDING / UNKNOWN',
                             source_references=sale.get('source_evidence'),as_of=as_of))
    if len(rows) > MAX_ROWS:
        _bad()
    if view.get('unknown_quantity_count') or view.get('unresolved_buyer_count') or view.get('pending_sale_count'):
        warnings.append('Some sales, quantities, rates or buyer mappings remain PENDING/UNKNOWN.')
    warnings.append('Only APPROVED sale lines with FINAL rates count as final commercial values; physical Outward is separate.')
    return rows, warnings


def _receivables(doc, company, cutoff):
    from fresko_universe import money
    as_of = cutoff.isoformat(sep=' ') if cutoff else None
    view = money.get_container_receivable(doc.name, as_of)
    as_of = view.get('as_of')  # Freeze the same canonical cutoff for every subsidiary Money read.
    if type(as_of) is not str or not as_of.strip():
        _bad()
    if view.get('company') != company or view.get('container') != doc.name:
        _deny()
    rows, warnings = [], []
    collections = {}
    inconsistent_bank = set()
    for sale in view.get('sales') or []:
        if sale.get('company') != company or sale.get('container') != doc.name:
            _deny()
        bank_states = set()
        for app in sale.get('payment_allocations') or []:
            key = app.get('collection')
            if not key:
                _bad()
            if key not in collections:
                pos = money.get_collection_position(key, as_of)
                if not pos.get('exists') or pos.get('company') != company:
                    _deny()
                collections[key] = pos
            pos = collections[key]
            if pos.get('is_bank_pending'):
                bank_states.add('BANK_PENDING')
                inconsistent_bank.add(str(sale.get('sale')))
            elif pos.get('is_bank_cleared'):
                bank_states.add('BANK_CLEARED')
            elif pos.get('is_cash_received'):
                bank_states.add('CASH_RECEIVED')
            else:
                bank_states.add('UNKNOWN')
        # Canonical money service supplies all sums; no independent truth engine.
        inconsistent = str(sale.get('sale')) in inconsistent_bank
        rows.append(_row(row_type='SALE_RECEIVABLE',company=company,container=doc.name,sale=sale.get('sale'),
                         customer=sale.get('customer'),currency=sale.get('currency'),
                         gross_amount=sale.get('gross_commercial_amount'),
                         applied_collections=None if inconsistent else sale.get('cash_applied_amount'),
                         noncash_adjustments=sale.get('adjustment_applied_amount'),
                         outstanding_amount=None if inconsistent else sale.get('outstanding_receivable'),
                         receipt_amount=None, bank_state='; '.join(sorted(bank_states)) if bank_states else 'NO_APPLIED_RECEIPT',
                         state='REVIEW_BANK_PENDING_ALLOCATION' if inconsistent else ('QUALIFYING' if sale.get('is_qualifying_debt') and sale.get('outstanding_receivable') is not None else 'PENDING / UNKNOWN'),
                         source_references='; '.join(sorted({str(a['collection']) for a in sale.get('payment_allocations') or []})),
                         as_of=view.get('as_of')))
    if len(rows) > MAX_ROWS:
        _bad()
    # Company-wide bank-pending records are displayed separately, NEVER allocated
    # to the selected container or included in its outstanding reconciliation.
    pending = money.get_bank_pending_collections(company, as_of)
    if pending.get('company') != company:
        _deny()
    for coll in pending.get('collections') or []:
        if coll.get('company') != company or coll.get('is_bank_cleared') or not coll.get('is_bank_pending'):
            _deny()
        known = coll.get('amount_state') == 'KNOWN'
        rows.append(_row(row_type='COMPANY_BANK_PENDING_UNATTRIBUTED', company=company,
                         container=doc.name, sale=None, customer=None, currency=coll.get('currency'),
                         gross_amount=None, applied_collections=None, noncash_adjustments=None,
                         outstanding_amount=None, receipt_amount=coll.get('amount') if known else None,
                         bank_state=coll.get('bank_state') or 'UNKNOWN', state='BANK_PENDING_NOT_CLEARED',
                         source_references=coll.get('name'), as_of=as_of))
    if pending.get('collections'):
        warnings.append('Company-wide bank-pending receipts shown separately; no container or sale attribution is inferred.')
    for curr, outstanding in (view.get('outstanding_receivable_by_currency') or {}).items():
        rows.append(_row(row_type='CURRENCY_TOTAL',company=company,container=doc.name,sale=None,
                         customer=None,currency=curr,gross_amount=(view.get('gross_sales_by_currency') or {}).get(curr),
                         applied_collections=(view.get('cash_applied_by_currency') or {}).get(curr),
                         noncash_adjustments=(view.get('adjustments_by_currency') or {}).get(curr),
                         outstanding_amount=None if inconsistent_bank else outstanding, receipt_amount=None, bank_state='NOT_APPLICABLE',
                         state='KNOWN' if outstanding is not None and not inconsistent_bank else 'PENDING / UNKNOWN',source_references=None,
                         as_of=view.get('as_of')))
    if inconsistent_bank:
        warnings.append('Bank-pending collection linked to an applied receipt: mark applied/outstanding UNKNOWN and investigate the canonical ledger.')
    if len(rows) > MAX_ROWS:
        _bad()
    if view.get('unresolved_pricing_sales_count'):
        warnings.append('Unresolved pricing: gross/outstanding totals UNKNOWN, not zero.')
    warnings.append('Bank pending is never bank cleared; container-unapplied receipts are separate from sale allocation.')
    warnings.append('No supplier costs, FX rates or profit calculations are included.')
    return rows, warnings


@frappe.whitelist()
def get_report_context():
    user, company = _principal()
    rows = frappe.get_list('Fresko Container', filters={'company': company},
                           fields=['name', 'container_no'], limit_page_length=100, order_by='name asc')
    allowed = []
    for row in rows:
        try:
            doc = _container(row.name, user, company)
        except (frappe.PermissionError, frappe.DoesNotExistError):
            continue
        allowed.append({'name': doc.name, 'container_no': doc.container_no})
    return {'company': company, 'containers': allowed, 'supported_reports': sorted(REPORTS),
            'limit_notice': 'First 100 accessible containers; choose exact ID for others.'}


@frappe.whitelist()
def execute_report(report: str, container: str, as_of: str | None = None):
    if type(report) is not str or report not in REPORTS:
        _bad()
    cutoff = _cutoff(as_of)
    user, company = _principal()
    doc = _container(container, user, company)
    if report == 'container_stock':
        rows, warnings = _stock(doc, company, cutoff)
    elif report == 'sales':
        rows, warnings = _sales(doc, company, cutoff)
    else:
        rows, warnings = _receivables(doc, company, cutoff)
    return {'report': report, 'company': company, 'container': doc.name,
            'container_no': doc.container_no, 'as_of': cutoff.isoformat(sep=' ') if cutoff else 'LIVE',
            'columns': list(COLUMNS[report]), 'rows': rows, 'warnings': warnings,
            'read_only': True, 'status': 'COMPLETE_WITH_LIMITATIONS' if warnings else 'COMPLETE',
            'source_authority': {'container_stock': 'Fresko Physical posted Outward + Container',
                                 'sales': 'Fresko Commercial reconciliation',
                                 'receivables': 'Fresko Money receivable/collection position'}[report]}


def _csv_value(value):
    if value is None:
        return 'UNKNOWN'
    text = str(value)
    # RFC4180 CSV quoting does not prevent Excel/Sheets formula interpretation.
    if re.fullmatch(r'-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?', text):
        return text
    if text.lstrip().startswith(('=', '+', '-', '@', '\t', '\r', '\n')):
        return "'" + text
    return text


@frappe.whitelist()
def export_report_csv(report: str, container: str, as_of: str | None = None):
    """Authorized export recomputes server-side; caller never supplies report rows."""
    result = execute_report(report, container, as_of)
    output = StringIO(newline='')
    writer = csv.writer(output, lineterminator='\r\n')
    writer.writerow(result['columns'])
    for row in result['rows']:
        writer.writerow([_csv_value(row.get(col)) for col in result['columns']])
    data = output.getvalue()
    if len(data.encode('utf-8-sig')) > MAX_EXPORT_BYTES:
        _bad()
    filename_id = re.sub(r'[^A-Za-z0-9_.-]', '_', container)
    return {'filename': f"fresko_{report}_{filename_id}.csv",
            'mime_type': 'text/csv;charset=utf-8', 'content': '\ufeff' + data,
            'as_of': result['as_of'], 'rows': len(result['rows']), 'read_only': True}
