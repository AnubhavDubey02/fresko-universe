"""Isolated offline tests of *actual reporting_engine.py* with synthetic Frappe/service facades.
Not signed-in native Frappe permission proof. No private operational data.
"""
import csv
import importlib.util
import io
import json
import pathlib
import sys
import types
import unittest
from decimal import Decimal
from unittest.mock import patch

SRC = pathlib.Path(__file__).resolve().parents[1] / 'fresko_universe' / 'reporting_engine.py'


def item(**kw):
    return types.SimpleNamespace(**kw)


class FakeDB:
    def __init__(self, scene):
        self.scene = scene
        self.sql_count = 0
    def sql(self, sql, params=(), as_dict=False):
        self.sql_count += 1
        if 'tabUser`' in sql:
            return [(self.scene.enabled,)]
        if 'tabHas Role`' in sql:
            return [(role,) for role in self.scene.roles]
        if 'tabUser Permission`' in sql:
            return [item(for_value=val, applicable_for=scope) for val, scope in self.scene.grants]
        raise AssertionError('No other database query authorized by reporting_engine')


class Scene:
    def __init__(self):
        self.user='synthetic.accounts@example.invalid'
        self.enabled=1
        self.roles={'Fresko Accounts'}
        self.grants=[('SYN-COMPANY-A', None)]
        self.company_allowed=True
        self.container_allowed=True
        self.calls=[]
        self.container=item(name='SYN-CONT-1',company='SYN-COMPANY-A',container_no='SYNX1234567',
                            inward_qty=120, uom='Crate', lots=[item(lot_no='LOT-A',uom='Crate',inward_qty=80),
                                item(lot_no='LOT-B',uom='Crate',inward_qty=40)])
        self.movements=[item(name='SYN-OUT-1',movement_type='OUTWARD',posted_at='2026-09-20 11:00:00',
                             movement_at='2026-09-20 10:00:00',source_evidence='SYN-EVID-1'),
                        item(name='SYN-OUT-R1',movement_type='REVERSAL',posted_at='2026-09-22 11:00:00',
                             movement_at='2026-09-22 10:00:00',source_evidence='SYN-EVID-2')]
        self.lines=[item(outward='SYN-OUT-1',lot_no='LOT-A',uom='Crate',qty='30.000'),
                    item(outward='SYN-OUT-1',lot_no=None,uom='Crate',qty='10'),
                    item(outward='SYN-OUT-R1',lot_no='LOT-A',uom='Crate',qty='5')]
        self.commercial_view={
            'view_scope':'INTERNAL','container':'SYN-CONT-1','as_of':'2026-09-25 23:59:59',
            'unknown_quantity_count':0,'unresolved_buyer_count':1,'pending_sale_count':1,
            'sales':[{'name':'SYN-SALE-1','company':'SYN-COMPANY-A','container':'SYN-CONT-1',
                 'status':'APPROVED','customer':'SYN-CUST-1','currency':'INR','source_evidence':'SYN-EVID-3',
                 'lines':[{'line_key':'L1','qty_state':'KNOWN','qty':'40','allocated_qty':'25',
                           'price_state':'FINAL','amount':'32000.00','lot_no':'LOT-A','lot_state':'KNOWN','uom':'Crate'}]},
                {'name':'SYN-SALE-2','company':'SYN-COMPANY-A','container':'SYN-CONT-1',
                 'status':'PROPOSED','customer':None,'currency':'INR','source_evidence':'SYN-EVID-4',
                 'lines':[{'line_key':'L2','qty_state':'UNKNOWN','qty':None,'allocated_qty':'0',
                           'price_state':'PROPOSED','amount':'10000.00','lot_no':None,'lot_state':'UNKNOWN','uom':'Crate'}]}]}
        self.money_view={
            'company':'SYN-COMPANY-A','container':'SYN-CONT-1','as_of':'2026-09-25 23:59:59',
            'unresolved_pricing_sales_count':1,
            'outstanding_receivable_by_currency': {'INR':None},
            'gross_sales_by_currency':{'INR':None},
            'cash_applied_by_currency':{'INR':'12000.00'},
            'adjustments_by_currency':{'INR':'2000.00'},
            'sales':[{'sale':'SYN-SALE-1','customer':'SYN-CUST-1','currency':'INR',
                      'company':'SYN-COMPANY-A','container':'SYN-CONT-1','gross_commercial_amount':'32000.00',
                      'cash_applied_amount':'12000.00','adjustment_applied_amount':'2000.00',
                      'outstanding_receivable':'18000.00','is_qualifying_debt':True,
                      'payment_allocations':[{'collection':'SYN-COLL-CLEARED','amount':'12000.00'}]},
                     {'sale':'SYN-SALE-2','customer':None,'currency':'INR',
                      'company':'SYN-COMPANY-A','container':'SYN-CONT-1','gross_commercial_amount':None,
                      'cash_applied_amount':'0.00','adjustment_applied_amount':'0.00',
                      'outstanding_receivable':None,'is_qualifying_debt':False,'payment_allocations':[]}]}
        self.bank_pending={'company':'SYN-COMPANY-A','as_of':'2026-09-25 23:59:59',
           'pending_count':1,'collections':[{'name':'SYN-COLL-PENDING','company':'SYN-COMPANY-A',
           'currency':'INR','amount':'9000.00','amount_state':'KNOWN','bank_state':'AUTHORIZATION_INPROCESS',
           'is_bank_cleared':False,'is_bank_pending':True}]}
        self.positions={
            'SYN-COLL-CLEARED':{'exists':True,'company':'SYN-COMPANY-A', 'is_bank_cleared':True, 'is_bank_pending':False,'is_cash_received':False},
            'SYN-COLL-PENDING':{'exists':True,'company':'SYN-COMPANY-A', 'is_bank_cleared':False, 'is_bank_pending':True,'is_cash_received':False},
        }
        self.quantity={'container':'SYN-CONT-1','uom':'Crate','operating_quantity':'120',
                       'operating_basis':'OPERATING_INWARD','operating_assertion':'SYN-INWARD-ASSERTION',
                       'reconciliation_status':'MATCH'}
        self.fr=None
        self.db=FakeDB(self)

    def modules(self):
        me=self
        f=types.ModuleType('frappe')
        f.PermissionError=type('PermissionError',(Exception,),{})
        f.ValidationError=type('ValidationError',(Exception,),{})
        f.DoesNotExistError=type('DoesNotExistError',(Exception,),{})
        f.session=item(user=me.user)
        f.db=me.db
        f.whitelist=lambda *a,**kw: (lambda fn:fn) if a==() else a[0]
        f.throw=lambda msg,exc=None: (_ for _ in ()).throw((exc or ValueError)(msg))
        f.clear_last_message=lambda:None
        def get_doc(doctype,name):
            me.calls.append(('get_doc',doctype,name))
            if doctype=='Fresko Container' and name=='SYN-CONT-1':return me.container
            raise f.DoesNotExistError('No such document')
        f.get_doc=get_doc
        f.has_permission=lambda doctype,doc,ptype=None,user=None:me.company_allowed if doctype=='Company' else me.container_allowed
        f.get_list=lambda doctype,**kw:[item(name='SYN-CONT-1',container_no='SYNX1234567')]
        root=types.ModuleType('fresko_universe');root.__path__=[]
        core=types.ModuleType('fresko_universe.fresko_core');core.__path__=[]
        physical=types.ModuleType('fresko_universe.fresko_core.physical')
        def snapshot(name):
            me.calls.append(('physical_snapshot',name))
            return {'movements':me.movements,'line_provenance':me.lines}
        physical.physical_snapshot=snapshot
        services=types.ModuleType('fresko_universe.fresko_core.services');services.__path__=[]
        qty=types.ModuleType('fresko_universe.fresko_core.services.quantity_assertion_service')
        def quantity_projection(name):
            me.calls.append(('quantity_projection',name));return me.quantity
        qty.quantity_reconciliation_projection=quantity_projection
        commercial=types.ModuleType('fresko_universe.commercial')
        def sales(name,as_of=None):
            me.calls.append(('commercial',name,as_of));return me.commercial_view
        commercial.get_container_reconciliation=sales
        money=types.ModuleType('fresko_universe.money')
        def get_cont(name,as_of=None):
            me.calls.append(('money',name,as_of));return me.money_view
        def pos(name,as_of=None):
            me.calls.append(('position',name,as_of));return me.positions[name]
        money.get_container_receivable=get_cont
        def pending(company, as_of=None):
            me.calls.append(('bank_pending',company,as_of));return me.bank_pending
        money.get_bank_pending_collections=pending
        money.get_collection_position=pos
        return {'frappe':f,'fresko_universe':root,'fresko_universe.fresko_core':core,
                'fresko_universe.fresko_core.physical':physical,
                'fresko_universe.fresko_core.services':services,
                'fresko_universe.fresko_core.services.quantity_assertion_service':qty,
                'fresko_universe.commercial':commercial,'fresko_universe.money':money}


class RealSourceReportingTest(unittest.TestCase):
    def setUp(self):
        self.scene=Scene()
        self.patch=patch.dict(sys.modules,self.scene.modules());self.patch.start()
        self.addCleanup(self.patch.stop)
        spec=importlib.util.spec_from_file_location('fresko_reporting_engine_under_test',SRC)
        self.m=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.m)
        self.f=sys.modules['frappe']
    def report(self,name='container_stock',as_of=None):return self.m.execute_report(name,'SYN-CONT-1',as_of)
    def totals(self):return self.report()['rows'][-1]
    def test_live_stock_exact_numbers(self):
        total=self.totals()
        self.assertEqual([Decimal(total[x]) for x in ('operating_inward_qty','posted_outward_qty','remaining_qty')],[Decimal('120'),Decimal('35'),Decimal('85')])
        self.assertIsNone(total['opening_qty'])
    def test_lot_reversal_and_unmapped(self):
        rows=self.report()['rows'];self.assertEqual(len(rows),4)
        self.assertEqual(Decimal(rows[0]['remaining_qty']),Decimal('55'));self.assertEqual(Decimal(rows[1]['remaining_qty']),Decimal('40'))
        self.assertEqual(rows[2]['posted_outward_qty'],'10');self.assertEqual(rows[2]['state'],'UNMAPPED')
    def test_original_evidence_reference(self):self.assertIn('SYN-EVID-1',self.report()['rows'][0]['source_references'])
    def test_historical_cutoff_preserves_unknown_inward(self):
        rows=self.report(as_of='2026-09-21')['rows']
        self.assertIsNone(rows[-1]['operating_inward_qty']);self.assertIsNone(rows[-1]['remaining_qty'])
        self.assertEqual(Decimal(rows[-1]['posted_outward_qty']),Decimal('40'))
    def test_asof_before_posting_outward_zero(self):self.assertEqual(self.report(as_of='2026-09-19')['rows'][-1]['posted_outward_qty'],'0')
    def test_oversell_flags_unknown(self):
        self.scene.lines[0].qty='180'
        rows=self.report()['rows'];self.assertIsNone(rows[-1]['remaining_qty']);self.assertEqual(rows[-1]['state'],'UNKNOWN')
    def test_invalid_record_qty_fails_closed(self):
        self.scene.lines[0].qty='NaN';self.assertIsNone(self.report()['rows'][-1]['posted_outward_qty'])
    def test_container_lot_inward_conflict_fails_closed(self):
        self.scene.container.lots[1].inward_qty='39'
        self.assertIsNone(self.report()['rows'][-1]['operating_inward_qty'])
    def test_negative_stock_reversal_fails_closed(self):
        self.scene.lines[2].qty='9999';self.assertIsNone(self.report()['rows'][-1]['remaining_qty'])
    def test_sales_approved_only(self):
        rows=self.report('sales')['rows'];self.assertEqual(len(rows),2)
        self.assertEqual(rows[0]['approved_qty'],'40');self.assertEqual(rows[0]['final_amount'],'32000.00')
        self.assertIsNone(rows[1]['approved_qty']);self.assertIsNone(rows[1]['final_amount'])
    def test_sales_canonical_api_and_as_of(self):
        self.report('sales','2026-09-25');self.assertIn(('commercial','SYN-CONT-1','2026-09-25 23:59:59'),self.scene.calls)
    def test_sales_never_projects_invisible_company(self):
        self.scene.commercial_view['sales'][0]['company']='SYN-COMPANY-B'
        with self.assertRaises(self.f.PermissionError):self.report('sales')
    def test_sales_missing_internal_scope_denied(self):
        self.scene.commercial_view['view_scope']='ASSIGNED'
        with self.assertRaises(self.f.PermissionError):self.report('sales')
    def test_receivable_canonical_values_and_unknown(self):
        rows=self.report('receivables')['rows']
        self.assertEqual(rows[0]['gross_amount'],'32000.00');self.assertEqual(rows[0]['outstanding_amount'],'18000.00')
        self.assertEqual(rows[0]['noncash_adjustments'],'2000.00')
        self.assertEqual(rows[-1]['state'],'PENDING / UNKNOWN');self.assertIsNone(rows[-1]['outstanding_amount'])
    def test_bank_pending_reported_without_attribution(self):
        rows=self.report('receivables')['rows']
        pending=next(r for r in rows if r['row_type']=='COMPANY_BANK_PENDING_UNATTRIBUTED')
        self.assertEqual(pending['receipt_amount'],'9000.00')
        self.assertEqual(pending['bank_state'],'AUTHORIZATION_INPROCESS')
        self.assertIsNone(pending['outstanding_amount'])
        self.assertIn(('bank_pending','SYN-COMPANY-A','2026-09-25 23:59:59'),self.scene.calls)
    def test_bank_pending_company_mismatch_denied(self):
        self.scene.bank_pending['company']='SYN-COMPANY-B'
        with self.assertRaises(self.f.PermissionError):self.report('receivables')
    def test_bank_cleared_distinct_pending(self):self.assertEqual(self.report('receivables')['rows'][0]['bank_state'],'BANK_CLEARED')
    def test_pending_bank_never_cleared(self):
        self.scene.money_view['sales'][0]['payment_allocations'][0]['collection']='SYN-COLL-PENDING'
        self.assertEqual(self.report('receivables')['rows'][0]['bank_state'],'BANK_PENDING')
        self.assertIsNone(self.report('receivables')['rows'][0]['applied_collections'])
        self.assertIsNone(self.report('receivables')['rows'][-1]['outstanding_amount'])
    def test_bank_different_tenant_denied(self):
        self.scene.positions['SYN-COLL-CLEARED']['company']='SYN-COMPANY-B'
        with self.assertRaises(self.f.PermissionError):self.report('receivables')
    def test_receivables_not_fake_profit(self):self.assertNotIn('profit', json.dumps(self.report('receivables')['rows']).lower())
    def test_unknown_currency_total_never_zero(self):self.assertIsNone(self.report('receivables')['rows'][-1]['gross_amount'])
    def test_missing_container_denied(self):
        with self.assertRaises(self.f.PermissionError):self.m.execute_report('container_stock','SYN-CONT-OTHER')
    def test_foreign_container_denied(self):
        self.scene.container.company='SYN-COMPANY-B'
        with self.assertRaises(self.f.PermissionError):self.report()
    def test_guest_denied(self):
        self.f.session.user='Guest'
        with self.assertRaises(self.f.PermissionError):self.report()
    def test_supplier_with_accounts_denied(self):
        self.scene.roles={'Fresko Accounts','Fresko Supplier Viewer'}
        with self.assertRaises(self.f.PermissionError):self.report()
    def test_salesperson_denied(self):
        self.scene.roles={'Fresko Salesperson'}
        with self.assertRaises(self.f.PermissionError):self.report()
    def test_disabled_user_denied(self):
        self.scene.enabled=0
        with self.assertRaises(self.f.PermissionError):self.report()
    def test_no_company_permission_denied(self):
        self.scene.grants=[]
        with self.assertRaises(self.f.PermissionError):self.report()
    def test_multi_company_permission_denied(self):
        self.scene.grants=[('SYN-COMPANY-A',None),('SYN-COMPANY-B',None)]
        with self.assertRaises(self.f.PermissionError):self.report()
    def test_applicable_for_company_denied(self):
        self.scene.grants=[('SYN-COMPANY-A','Fresko Container')]
        with self.assertRaises(self.f.PermissionError):self.report()
    def test_company_doc_permission_denied(self):
        self.scene.company_allowed=False
        with self.assertRaises(self.f.PermissionError):self.report()
    def test_container_doc_permission_denied(self):
        self.scene.container_allowed=False
        with self.assertRaises(self.f.PermissionError):self.report()
    def test_invalid_report_rejected(self):
        with self.assertRaises(self.f.ValidationError):self.report('profit')
    def test_malformed_date_rejected(self):
        for as_of in ('', '2026-02-30','tomorrow','2026/09/20','2026-09-20T25:00:00',123):
            with self.subTest(as_of=as_of),self.assertRaises(self.f.ValidationError):self.report(as_of=as_of)
    def test_no_mutation_services_called(self):
        for name in ('container_stock','sales','receivables'):self.report(name)
        self.assertTrue(all(item[0] in {'get_doc','physical_snapshot','quantity_projection','commercial','money','position','bank_pending'} for item in self.scene.calls))
    def test_export_recomputes_canonical_read(self):
        file=self.m.export_report_csv('container_stock','SYN-CONT-1')
        self.assertEqual(file['mime_type'],'text/csv;charset=utf-8')
        rows=list(csv.DictReader(io.StringIO(file['content'].lstrip('\ufeff'))))
        total=rows[-1]
        self.assertEqual(Decimal(total['operating_inward_qty'])-Decimal(total['posted_outward_qty']),Decimal(total['remaining_qty']))
        self.assertEqual(total['opening_qty'],'UNKNOWN')
        self.assertEqual(self.scene.calls.count(('physical_snapshot','SYN-CONT-1')),1)
    def test_csv_injection_guard(self):
        for txt in ('=1+1', '+SUM(A1)', '-1+2', '@cmd', '\t=cmd'):
            self.assertTrue(self.m._csv_value(txt).startswith("'"))
    def test_csv_escape_safe_negative_decimal(self):
        # Numeric values should remain usable for independent CSV verification.
        self.assertEqual(self.m._csv_value('-8.25'),'-8.25')
    def test_csv_sales_recalculation(self):
        out=self.m.export_report_csv('sales','SYN-CONT-1')
        rows=list(csv.DictReader(io.StringIO(out['content'].lstrip('\ufeff'))))
        final=sum((Decimal(r['final_amount']) for r in rows if r['state']=='FINAL'),Decimal(0))
        self.assertEqual(final,Decimal('32000.00'))
    def test_csv_receivable_recalculation(self):
        out=self.m.export_report_csv('receivables','SYN-CONT-1')
        rows=list(csv.DictReader(io.StringIO(out['content'].lstrip('\ufeff'))))
        r=rows[0];self.assertEqual(Decimal(r['gross_amount'])-Decimal(r['applied_collections'])-Decimal(r['noncash_adjustments']),Decimal(r['outstanding_amount']))
        self.assertEqual(rows[-1]['gross_amount'],'UNKNOWN')
    def test_literal_source_csv_escape(self):
        self.scene.commercial_view['sales'][0]['source_evidence']='=HYPERLINK("http://evil")'
        out=self.m.export_report_csv('sales','SYN-CONT-1')['content']
        self.assertIn("'=HYPERLINK",out)
    def test_incomplete_outward_missing_lines_unknown(self):
        self.scene.lines=[]
        self.assertIsNone(self.report()['rows'][-1]['remaining_qty'])
    def test_orphan_line_marks_unknown(self):
        self.scene.lines.append(item(outward='SYN-OUT-OTHER',lot_no='LOT-A',uom='Crate',qty='10'))
        self.assertIsNone(self.report()['rows'][-1]['posted_outward_qty'])
    def test_no_operating_assertion_is_unknown(self):
        self.scene.quantity={'reconciliation_status':'UNRESOLVED'}
        total=self.report()['rows'][-1]
        self.assertIsNone(total['remaining_qty'])
        self.assertIsNone(total['operating_inward_qty'])
    def test_mismatched_operating_assertion_is_unknown(self):
        self.scene.quantity['operating_quantity']='100'
        self.assertIsNone(self.report()['rows'][-1]['remaining_qty'])
    def test_variance_warning_not_secretly_merged(self):
        self.scene.quantity['reconciliation_status']='OPEN_VARIANCE'
        self.assertTrue(any('OPEN_VARIANCE' in w for w in self.report()['warnings']))
    def test_accessible_context_scoped(self):
        context=self.m.get_report_context();self.assertEqual(context['company'],'SYN-COMPANY-A')
        self.assertEqual(context['containers'],[{'name':'SYN-CONT-1','container_no':'SYNX1234567'}])
    def test_max_rows_fail_closed(self):
        self.scene.movements=[self.scene.movements[0]]*1201
        with self.assertRaises(self.f.ValidationError):self.report()

if __name__=='__main__':unittest.main()
