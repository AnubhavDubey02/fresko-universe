import unittest
from fresko_universe.report_contracts import REPORTS,plan_report
class ReportsTest(unittest.TestCase):
 def test_all_eleven_subjects(self):
  self.assertEqual(len(REPORTS),11)
 def test_unknown_not_supported(self):
  self.assertEqual(plan_report('profit_forecast',{},'TENANT-A')['status'],'UNSUPPORTED')
 def test_no_tenant_denies(self):
  self.assertEqual(plan_report('bank_pending',{},None)['status'],'DENIED')
 def test_company_derived(self):
  self.assertEqual(plan_report('bank_pending',{},'TENANT-A')['arguments'],{'company':'TENANT-A'})
 def test_cross_tenant_denied(self):
  self.assertEqual(plan_report('bank_pending',{'company':'TENANT-B'},'TENANT-A')['status'],'DENIED')
 def test_record_required(self):
  self.assertEqual(plan_report('sale_history',{'sale_name':'SALE-Z1'},'TENANT-A')['missing'],['as_of'])
 def test_unsupported_lot_doesnt_guess(self):
  self.assertEqual(plan_report('lot_stock',{'container':'C','lot':'L'},'TENANT-A')['status'],'NOT_IMPLEMENTED')
 def test_lineage_is_not_raw_data_export(self):
  self.assertEqual(plan_report('document_lineage',{'evidence_ref':'EV-1'},'TENANT-A')['status'],'NOT_IMPLEMENTED')
 def test_no_implicit_amounts(self):
  result=plan_report('buyer_receivables',{'customer':'C'},'TENANT-A')
  self.assertEqual(result['arguments'],{'customer':'C','company':'TENANT-A'})
  self.assertNotIn('amount',repr(result))
 def test_no_arbitrary_flags(self):
  self.assertEqual(plan_report('container_stock',{'container':'MSCU1234566','approve':'yes'},'TENANT-A')['status'],'NEEDS_CLARIFICATION')

class AdversarialReportsTest(unittest.TestCase):
 def test_physical_stock_and_movements_are_explicitly_unsupported(self):
  for name in ('container_stock','inward_outward','lot_stock','source_lineage','document_lineage'):
   with self.subTest(name=name):
    self.assertFalse(REPORTS[name].supported)
    self.assertIsNone(REPORTS[name].tool)
    result=plan_report(name,{},'SYN-A')
    self.assertEqual(result['status'],'NOT_IMPLEMENTED')
    self.assertTrue(result['limitation'])

 def test_supported_descriptors_match_actual_allowlisted_signatures(self):
  import ast
  from pathlib import Path
  tree=ast.parse((Path(__file__).resolve().parents[1]/'fresko_universe'/'ask_fresko.py').read_text())
  catalog={}
  for node in tree.body:
   if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id in {'_COMMERCIAL','_MONEY'} for t in node.targets):
    for key,value in zip(node.value.keys,node.value.values):
     catalog[ast.literal_eval(key)]=(ast.literal_eval(value.elts[1]),ast.literal_eval(value.elts[2]))
  self.assertEqual(len(catalog),10)
  for report in REPORTS.values():
   if report.supported:
    with self.subTest(name=report.name):
     self.assertIn(report.tool,catalog)
     self.assertEqual((report.required,report.optional),catalog[report.tool])

 def test_every_supported_descriptor_produces_only_exact_arguments(self):
  for report in REPORTS.values():
   if report.supported:
    args={key:'SYN-VALUE' for key in report.required if key!='company'}
    if 'as_of' in report.required+report.optional:args['as_of']='2026-10-02 12:00:00'
    result=plan_report(report.name,args,'SYN-A')
    self.assertEqual(result['status'],'PROPOSAL_ONLY')
    self.assertEqual(result['tool'],report.tool)
    self.assertEqual(set(result),{'status','tool','arguments','authority'})
    self.assertTrue(set(result['arguments'])<=set(report.required+report.optional))

 def test_missing_and_nonstring_company_are_denied(self):
  for company in (None,'',' ',False,1,['SYN-A']):
   self.assertEqual(plan_report('bank_pending',{},company)['status'],'DENIED')

 def test_unhashable_unknown_report_does_not_crash(self):
  for name in ([],{},False,None,1):
   self.assertEqual(plan_report(name,{},'SYN-A')['status'],'UNSUPPORTED')

 def test_blank_cutoff_never_silently_becomes_live(self):
  for cutoff in ('',' '):
   result=plan_report('outward_reconciliation',{'outward_name':'SYN-O','as_of':cutoff},'SYN-A')
   self.assertEqual(result['status'],'NEEDS_CLARIFICATION')
   self.assertIsNone(result['tool'])

 def test_absent_optional_cutoff_remains_live_proposal(self):
  self.assertEqual(plan_report('outward_reconciliation',{'outward_name':'SYN-O'},'SYN-A')['arguments'],{'outward_name':'SYN-O'})

 def test_blank_record_requires_clarification(self):
  for value in ('',' '):
   self.assertEqual(plan_report('outward_reconciliation',{'outward_name':value},'SYN-A')['status'],'NEEDS_CLARIFICATION')

 def test_wrong_argument_types_and_unsupported_flags_are_rejected(self):
  for args in (None,[],{'company':True},{'as_of':None},{'ignore_permissions':'yes'},{1:'x'}):
   self.assertEqual(plan_report('bank_pending',args,'SYN-A')['status'],'NEEDS_CLARIFICATION')

 def test_no_role_or_verified_claim_is_consumed(self):
  for args in ({'roles':'Fresko Approver'},{'company_verified':'true'},{'authorized':'true'}):
   self.assertEqual(plan_report('bank_pending',args,'SYN-A')['status'],'NEEDS_CLARIFICATION')

 def test_opaque_identifiers_are_preserved_and_arguments_detached(self):
  args={'outward_name':' SYN-O '}
  result=plan_report('outward_reconciliation',args,'SYN-A')
  self.assertEqual(result['arguments']['outward_name'],' SYN-O ')
  args['outward_name']='CHANGED'
  self.assertEqual(result['arguments']['outward_name'],' SYN-O ')
  result['arguments']['outward_name']='OTHER'
  self.assertEqual(args['outward_name'],'CHANGED')

 def test_reports_and_descriptors_cannot_be_changed_through_public_contract(self):
  from dataclasses import FrozenInstanceError
  with self.assertRaises(TypeError):REPORTS['new']=None
  with self.assertRaises(FrozenInstanceError):REPORTS['bank_pending'].supported=False

 def test_source_has_no_frappe_query_dispatch_or_arithmetic(self):
  import ast
  from pathlib import Path
  tree=ast.parse((Path(__file__).resolve().parents[1]/'fresko_universe'/'report_contracts.py').read_text())
  for node in ast.walk(tree):
   if isinstance(node,ast.Import):self.assertTrue(all(item.name!='frappe' for item in node.names))
   if isinstance(node,ast.ImportFrom):self.assertNotEqual(node.module,'frappe')
   if isinstance(node,ast.Call) and isinstance(node.func,ast.Name):
    self.assertNotIn(node.func.id,{'open','eval','exec','float','Decimal','run_tool'})

if __name__=='__main__':unittest.main()
