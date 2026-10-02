#!/usr/bin/env python3
import hashlib,json,re,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; FIXTURE=ROOT/'fresko_universe/fresko_universe/fixtures/real_data_shadow/manifest.json'
VOCAB={'SOURCE_OBSERVED','USER_CONFIRMED','DERIVED_ARITHMETIC','UNKNOWN','PENDING'}
def load(path=FIXTURE):
 with open(path,encoding='utf8') as f:return json.load(f)
def fail(s):raise ValueError(s)
def valid_hash(value):return isinstance(value,str) and re.fullmatch(r'[0-9A-Fa-f]{64}',value) is not None
def valid_range(value):return isinstance(value,str) and re.fullmatch(r"[^!\r\n]+![A-Z]{1,3}[1-9][0-9]*(?::[A-Z]{1,3}[1-9][0-9]*)?",value,re.I) is not None
def source_map(m):return {x['id']:x for x in m.get('sources',[]) if x.get('id')}
def validate_ref(ref,sources,*,require_verified=True):
 if not isinstance(ref,dict) or ref.get('source_id') not in sources:fail('missing or unknown source reference')
 source=sources[ref['source_id']]
 if require_verified and (source.get('verification_status')!='HASH_VERIFIED' or not valid_hash(source.get('sha256'))):fail('source reference is not hash verified')
 if source.get('kind')=='xlsx' and (not valid_range(ref.get('range')) or ref.get('range') not in source.get('ranges',[])):fail('source range is not declared')
 if source.get('kind')=='repository_decision' and ref.get('section') not in source.get('sections',[]):fail('decision section is not declared')
 return source
def validate(m):
 if m.get('schema_version')!=1:fail('schema_version must be 1')
 if set(m.get('provenance_vocab',[]))!=VOCAB:fail('provenance vocabulary mismatch')
 src=m.get('sources',[]); ids=[x.get('id') for x in src]
 if not ids or len(ids)!=len(set(ids)):fail('source ids must be unique')
 for x in src:
  if x.get('kind')=='xlsx':
   if x.get('verification_status')!='HASH_VERIFIED' or not valid_hash(x.get('sha256')) or not x.get('ranges') or any(not valid_range(r) for r in x.get('ranges',[])):fail('source pointers/hash required')
  elif x.get('kind')=='repository_decision':
   path=(ROOT/x.get('path','')).resolve()
   try:path.relative_to(ROOT)
   except ValueError:fail('repository decision path escapes root')
   if x.get('verification_status')!='HASH_VERIFIED' or not valid_hash(x.get('sha256')) or not path.is_file():fail('repository decision pointer/hash required')
   if hashlib.sha256(path.read_bytes()).hexdigest().lower()!=x['sha256'].lower():fail('repository decision hash drift')
   if not x.get('sections') or len(x['sections'])!=len(set(x['sections'])):fail('repository decision sections required')
  elif x.get('kind')=='photo':
   if x.get('verification_status')=='HASH_VERIFIED' and not valid_hash(x.get('sha256')):fail('verified photo requires SHA256')
   if x.get('verification_status')=='PENDING' and x.get('sha256') is not None:fail('pending photo must not claim a hash')
  else:fail('source kind is invalid')
 rs=m.get('replays',[]); rid=[x.get('id') for x in rs]
 if len(rid)!=len(set(rid)):fail('replay ids must be unique')
 p=next((x for x in rs if x.get('id')=='21-sep-plum'),None);g=next((x for x in rs if x.get('id')=='21-sep-grapes'),None);ca=next((x for x in rs if x.get('id')=='25-sep-ca'),None)
 if not p or not g or not ca:fail('required replay cut-offs missing')
 sources=source_map(m)
 for x in rs:validate_ref(x.get('source_ref'),sources)
 if sum(p['lots'].values())!=p['operating_inward'] or p['operating_inward']!=p['operating_outward']:fail('Plum lot/inward-outward mismatch')
 if p['priced']+p['unpriced']!=p['operating_outward'] or p['stock']!=0:fail('Plum aggregate mismatch')
 if g['operating_inward']!=g['operating_outward'] or sum(g['unpriced_breakdown'])!=g['unpriced'] or g['priced']+g['unpriced']!=g['operating_outward'] or g['stock']!=0:fail('Grapes operating aggregate mismatch')
 if g['declared_shipping']==g['operating_inward']:fail('declared shipping must remain separate')
 if ca['combined_sales']!=ca['plum']['sales']+ca['grapes']['sales']:fail('combined total drift')
 if ca['plum']['sales']!=ca['plum']['allocation']+ca['plum']['receivable'] or ca['grapes']['sales']!=ca['grapes']['allocation']+ca['grapes']['receivable']:fail('allocation drift')
 if ca['collections']!=ca['plum']['allocation']+ca['grapes']['allocation'] or ca['combined_sales']!=ca['collections']+ca['receivable']:fail('combined allocation drift')
 if sum(x['qty'] for x in ca['grapes']['rate_buckets'])!=180 or g['sales']+ca['grapes']['later_rate_total']!=ca['grapes']['sales']:fail('later Grapes rate total mismatch')
 if ca['grapes']['later_rate_total']!=sum(x['qty']*x['rate'] for x in ca['grapes']['rate_buckets']):fail('rate bucket arithmetic mismatch')
 if any('gp' in x for x in ca['grapes']['rate_buckets']):fail('rate buckets must not be force-mapped to GPs')
 b=m['business_examples']; one,three,ninety=b['inr101'],b['inr350000'],b['sohail_92_at_700']
 validate_ref(one.get('source_ref'),sources);validate_ref(one.get('decision_ref'),sources)
 validate_ref(three.get('source_ref'),sources);validate_ref(three.get('decision_ref'),sources)
 if one.get('provenance')!='USER_CONFIRMED' or one.get('classification')!='labour_outflow' or one.get('customer_collections')!=0:fail('INR101 entered collections')
 if three.get('received') is not True or three.get('bank_cleared') is True or three.get('allocated') is True:fail('INR350 received conflated with cleared/allocation')
 if ninety['derived_amount']!=ninety['quantity']*ninety['rate']:fail('92 arithmetic mismatch')
 photo=validate_ref(ninety.get('source_ref'),sources,require_verified=False)
 if photo.get('kind')!='photo':fail('92 source must be a photo')
 photo_verified=photo.get('verification_status')=='HASH_VERIFIED' and valid_hash(photo.get('sha256'))
 active=ninety.get('exact_photo_linked') and ninety.get('role_approved') and photo_verified
 if (active and ninety.get('activation_status')!='ACTIVE') or (not active and ninety.get('activation_status')!='VERIFICATION_PENDING'):fail('92 activation unsupported')
 validate_ref(b['pending_do'].get('source_ref'),sources)
 if b['pending_do'].get('stock_effect')!=0:fail('pending DO alters stock')
 return True
def main():
 try:validate(load());print('Validated real-data shadow replay fixture.');return 0
 except Exception as e:print(f'Fixture validation failed: {e}',file=sys.stderr);return 1
if __name__=='__main__':raise SystemExit(main())
