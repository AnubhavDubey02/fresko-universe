import copy,unittest
import validate_real_data_shadow_fixture as v
class T(unittest.TestCase):
 def setUp(self):self.m=v.load()
 def bad(self,f,msg):
  m=copy.deepcopy(self.m);f(m)
  with self.assertRaisesRegex(ValueError,msg):v.validate(m)
 def test_valid(self):self.assertTrue(v.validate(self.m))
 def test_combined_total_drift(self):self.bad(lambda m:m['replays'][2].__setitem__('combined_sales',1),'combined total')
 def test_101(self):self.bad(lambda m:m['business_examples']['inr101'].__setitem__('customer_collections',101),'INR101')
 def test_350(self):self.bad(lambda m:m['business_examples']['inr350000'].__setitem__('bank_cleared',True),'INR350')
 def test_92(self):self.bad(lambda m:m['business_examples']['pending_92_at_700'].__setitem__('activation_status','ACTIVE'),'92 activation')
 def test_92_photo_only(self):
  def mutate(m):
   m['business_examples']['pending_92_at_700']['exact_photo_linked']=True
   m['business_examples']['pending_92_at_700']['activation_status']='ACTIVE'
  self.bad(mutate,'92 activation')
 def test_92_approval_only(self):
  def mutate(m):
   m['business_examples']['pending_92_at_700']['role_approved']=True
   m['business_examples']['pending_92_at_700']['activation_status']='ACTIVE'
  self.bad(mutate,'92 activation')
 def test_wrong_source_hash(self):self.bad(lambda m:m['sources'][1].__setitem__('sha256','0'*63),'source pointers/hash')
 def test_malformed_source_range(self):self.bad(lambda m:m['sources'][1]['ranges'].__setitem__(0,'Current Position 21-Sep'), 'source pointers/hash')
 def test_unknown_source_reference(self):self.bad(lambda m:m['replays'][0]['source_ref'].__setitem__('source_id','missing'),'missing or unknown')
 def test_business_example_requires_source(self):self.bad(lambda m:m['business_examples']['inr101'].pop('source_ref'),'missing or unknown')
 def test_decision_hash_drift(self):self.bad(lambda m:m['sources'][3].__setitem__('sha256','0'*64),'repository decision hash drift')
 def test_allocation_drift(self):self.bad(lambda m:m['replays'][2]['plum'].__setitem__('allocation',1),'allocation drift')
 def test_rate_gp(self):self.bad(lambda m:m['replays'][2]['grapes']['rate_buckets'][0].__setitem__('gp','GP205537'),'force-mapped')
 def test_declared(self):self.bad(lambda m:m['replays'][1].__setitem__('declared_shipping',3056),'declared shipping')
 def test_pending(self):self.bad(lambda m:m['business_examples']['pending_do'].__setitem__('stock_effect',-10),'pending DO')
 def test_pending_requires_source(self):self.bad(lambda m:m['business_examples']['pending_do'].pop('source_ref'),'missing or unknown')
if __name__=='__main__':unittest.main()
