"""Offline Ask Fresko v0.3 read proposal router.

Additive only. No Frappe services imported, no SQL/network/files access,
no actual authorization decisions; caller MUST pass server-verified roles and
invoke ask_fresko.run_tool only through the authenticated backend.

Original v0.2 Joblib model is never modified/retrained. It can be supplied as
an advisory-only classifier, but no probability may override this gate.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import date
from typing import Any, Callable, Mapping, Sequence
import re

# Frozen exactly against existing ask_fresko.py read signatures (PR22 head).
TOOL_SPEC={
 'container_reconciliation':(('container',),('as_of',)),
 'sale_as_of':(('sale_name','as_of'),()),
 'outward_reconciliation':(('outward_name',),('as_of',)),
 'sale_receivable':(('sale',),('as_of',)),
 'container_receivable':(('container',),('as_of',)),
 'customer_receivable':(('customer','company'),('as_of',)),
 'unallocated_collections':(('company',),('as_of',)),
 'bank_pending_collections':(('company',),('as_of',)),
 'open_money_exceptions':(('company',),()),
 'collection_position':(('name',),('as_of',)),
}
MONEY=frozenset(('sale_receivable','container_receivable','customer_receivable',
 'unallocated_collections','bank_pending_collections','open_money_exceptions','collection_position'))
COMMERCIAL_ROLES=frozenset(('Fresko Salesperson','Fresko Accounts','Fresko Approver','System Manager'))
MONEY_ROLES=frozenset(('Fresko Accounts','Fresko Approver'))
MAX_INPUT=500
ID=re.compile(r'(?<![\w.-])(?P<kind>CN|BOX|CONT|SAL|SALE|OUT|COLL|CUST|BUYER|FIRM|COMPANY)-(?P<body>[A-Za-z0-9][A-Za-z0-9._-]{1,79})(?![\w.-])',re.I)
KIND={'CN':'container','BOX':'container','CONT':'container','SAL':'sale','SALE':'sale','OUT':'outward_name','COLL':'name','CUST':'customer','BUYER':'customer','FIRM':'company','COMPANY':'company'}
# ISO 6346 shaped container tokens only: owner code (three letters), category
# (U/J/Z), six-digit serial and one check digit. We do NOT mandate checksum
# validity: historical/internal records may be nonconformant. Backend resolves IDs.
ISO_CONTAINER=re.compile(r'(?<![A-Za-z0-9_])(?P<whole>[A-Za-z]{3}[UJZujz][ .-]?[0-9]{7})(?![A-Za-z0-9_])')
ISO_ALPHA={letter:n for letter,n in zip('ABCDEFGHIJKLMNOPQRSTUVWXYZ',
 (10,12,13,14,15,16,17,18,19,20,21,23,24,25,26,27,28,29,30,31,32,34,35,36,37,38))}
def iso6346_check_digit_ok(identifier:str)->bool:
 """Pure diagnostic only; validation is NOT a requirement for existing Fresko IDs."""
 code=identifier.upper().replace(' ','').replace('-','').replace('.','')
 if not re.fullmatch(r'[A-Z]{3}[UJZ][0-9]{7}',code):return False
 total=sum((ISO_ALPHA.get(ch,int(ch) if ch.isdigit() else 0)*2**i) for i,ch in enumerate(code[:10]))
 return (total%11)%10==int(code[-1])
DATE_ISO=re.compile(r'(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)')
QUOTE_FIELD=re.compile(r'\b(container|cntr|customer|buyer|sale|outward|dispatch|collection|receipt|company|firm|entity)\s*[:=]?\s*["“]([^"”\r\n]{1,120})["”]',re.I)
FIELD_KIND={'container':'container','cntr':'container','customer':'customer','buyer':'customer','sale':'sale','outward':'outward_name','dispatch':'outward_name','collection':'name','receipt':'name','company':'company','firm':'company','entity':'company'}
# Do not strip suspicious instructions as mere benign punctuation.
MUTATION=re.compile(r'\b(?:delete|remove|move|withdraw|reclassify|disburse|settle|credit|debit|approve|approval\s+execute|submit|reverse|cancel|alter|edit|update|modify|insert|create|write|pay|transfer|execute|post|refund|upload|dump|bypass|export\s+all|ignore\s+(?:all\s+)?(?:permissions|policy|security)|disregard\s+(?:all\s+)?(?:permissions|policy|security)|query\s+every|override\s+(?:all\s+)?(?:acl|permissions|security)|disable\s+authorization|mark\s+(?:as\s+)?(?:paid|cleared|approved)|set\b|drop\b|run\s+(?:raw\s+)?sql|raw\s+sql|execute_raw_sql|approve_collection|reset\s+passwords?|send\s+(?:every|all)\s+(?:bank|customer))\b',re.I)
SOURCE_CLAIM=re.compile(r'\b(?:screenshot\s+(?:caption|says)|ocr\s+(?:says|note)|invoice\s+(?:footer|footnote)|whatsapp\s+(?:caption|says)|pasted\s+whatsapp|document\s+instructs|system\s+(?:message|says)|footer\s*:)\b',re.I)
BAD_SOURCE=re.compile(r'\b(?:ignore|override|execute|approve|export|reveal|transfer|query\s+every|disregard|change\s+company|reset)\b',re.I)
DATE_CONTEXT=re.compile(r'\b(?:as\s+of|on\s+\d{4}|historical|history|snapshot|on\s+date|\d{4}-\d{2}-\d{2}\s+tak|without\s+date|cutoff|by\s+date)\b|\b(?:तक|दिनांक)\b',re.I)

@dataclass(frozen=True)
class Proposal:
 status:str
 tool:str|None=None
 arguments:Mapping[str,str]|None=None
 missing_arguments:tuple[str,...]=()
 reason:str=''
 confidence:float|None=None
 source_ignored:bool=False
 def to_dict(self)->dict[str,Any]:
  d=asdict(self);d['arguments']=dict(self.arguments or {});d['missing_arguments']=list(self.missing_arguments);return d

def _has(q:str,pattern:str)->bool:
 return bool(re.search(pattern,q,re.I))

def _ids(q:str)->tuple[dict[str,str],str|None]:
 # Token/type consistency is enforced; any extra IDs cause clarification,
 # not heuristic "use first ID" selection. Quoted names are accepted only
 # with explicit field labels and never interpreted as instructions.
 found:dict[str,list[str]]={}
 spans=[]
 for m in QUOTE_FIELD.finditer(q):
  k=FIELD_KIND[m.group(1).casefold()];v=m.group(2).strip()
  found.setdefault(k,[]).append(v);spans.append(m.span(2))
 for m in ISO_CONTAINER.finditer(q):
  if any(a<=m.start()<b for a,b in spans):continue
  value=re.sub(r'[ .-]','',m.group('whole')).upper()
  found.setdefault('container',[]).append(value)
  spans.append(m.span('whole'))
 for m in ID.finditer(q):
  if any(a<=m.start()<b for a,b in spans):continue
  k=KIND[m.group('kind').upper()];found.setdefault(k,[]).append(m.group())
 vals={}
 for k,items in found.items():
  if len(set(items))!=1:return {},f'conflicting {k} identifiers'
  vals[k]=items[0].rstrip('.')
 return vals,None

def _intent(q:str,vals:Mapping[str,str])->str|None:
 lo=q.casefold()
 if _has(lo,r'\b(?:trial\s+balance|net\s+profit|forecast|ledger\s+export|tax\s+return)\b'):
  return None
 # Company-level money inquiries take precedence only if the exact family is clear.
 if _has(lo,r'unallocated|unapplied|unassigned|unadjusted|not\s+(?:yet\s+)?(?:allocated|adjusted)|allocate\s+na\s+hue|adjust\s+nahi|allocate\s+nahi|allocation\s+pending|बिना\s+आवंटित|आवंटित\s+नहीं|बिना\s+समायोजित|समायोजन\s+नहीं|आवंटन\s+(?:नहीं|शेष)|पैसा\s+आया\s+लेकिन'):
  return 'unallocated_collections'
 if _has(lo,r'bank|बैंक') and _has(lo,r'pending|uncleared|awaiting|confirmation|confirmed|पुष्टि|लंबित|बाकी|baaki|cleared|clearance|not\s+yet'):
  return 'bank_pending_collections'
 if _has(lo,r'(?:money|payment|cash|धन)\s+(?:exceptions?|mismatch|discrepanc)|(?:open|unresolved|खुली|बकाया)\s+(?:money|payment|cash|धन)|\b(?:exception|mismatch|discrepanc|issue)s?\b|विसंगतियाँ|अपवाद'):
  if _has(lo,r'exception|mismatch|discrepanc|विसंगत|अपवाद|\bissues?\b'):
   return 'open_money_exceptions'
 # If a typed container identifier is present, incidental 'dispatch' can refer
 # to the same stock reconciliation; if a separate OUT id exists it is
 # rejected by the strict extra-ID check below.
 if 'container' in vals and _has(lo,r'reconcil|stock|स्टॉक|tally|मिलान|हिसाब|balance|dispatched\s+sales|issued|shipment|container\s+position|शेष\s+माल') and not _has(lo,r'outstanding|\bdue\b|receivable|unpaid'):
  return 'container_reconciliation'
 # Dates and receipt positions are not financial read permissions themselves.
 if 'name' in vals or _has(lo,r'collection|receipt|संग्रह|कलेक्शन'):
  if _has(lo,r'position|status|स्थिति|विवरण|अभी|current|receipt\s+note') or 'name' in vals:
   return 'collection_position'
 if 'customer' in vals or _has(lo,r'customer|buyer|ग्राहक'):
  if _has(lo,r'owe|receivable|outstanding|due|unpaid|money|बकाया|बाकी|देय|देनदारी|paisa|पैसा|payment'):
   return 'customer_receivable'
 if 'sale' in vals or _has(lo,r'\bsale\b|\bsales\b|बिक्री'):
  # Receivable as-of queries stay financial, not historical sale-state.
  if _has(lo,r'owe|receivable|outstanding|due|dues|unpaid|pending|बकाया|बाकी|भुगतान|रकम|amount|paisa|payment'):
   return 'sale_receivable'
  if _has(lo,r'\b(as\s+of|historical|history|snapshot|position|status|state|on\s+\d{4}|\d{4}-\d{2}-\d{2}\s+tak|cutoff)\b|दिनांक|तक|पर') or bool(DATE_ISO.search(lo)):
   return 'sale_as_of'
 if 'outward_name' in vals or _has(lo,r'outward|dispatch|डिस्पैच|आउटवर्ड'):
  if _has(lo,r'outward|dispatch|reconcil|मिलान|हिसाब|match|verify|audit'):
   return 'outward_reconciliation'
 if 'container' in vals or _has(lo,r'container|cntr|कंटेनर|माल'):
  if _has(lo,r'owe|receivable|outstanding|due|dues|unpaid|pending|बकाया|बाकी|भुगतान|रकम|amount|paisa|payment') and not _has(lo,r'reconcil|tally|मिलान|stock|स्टॉक'):
   return 'container_receivable'
  if _has(lo,r'reconcil|stock|स्टॉक|tally|मिलान|हिसाब|balance|dispatched\s+sales|issued|shipment') and not _has(lo,r'outstanding|\bdue\b|receivable|unpaid'):
   return 'container_reconciliation'
 # No automatic company-only or generic-money fallback.
 return None

def propose(question:Any,*,trusted_roles:Sequence[str]|None=None,trusted_company:str|None=None,untrusted_source:str|None=None,model:Any=None)->Proposal:
 """Safe offline proposal; `trusted_*` values MUST originate from server session.

 model is intentionally not called in v0.3: misclassification cannot override
 schema and role gates; v0.2 model stays preserved for separate comparisons.
 `untrusted_source` is ignored by the planner, not concatenated to question.
 """
 src=untrusted_source is not None
 if not isinstance(question,str) or not question.strip() or len(question)>MAX_INPUT or any(ord(c)<32 and c not in '\t\n' for c in question):
  return Proposal('NEEDS_CLARIFICATION',reason='invalid or oversized question',source_ignored=src)
 if untrusted_source is not None and (not isinstance(untrusted_source,str) or len(untrusted_source)>10000):
  return Proposal('DENIED',reason='invalid source envelope',source_ignored=True)
 roles=set(trusted_roles or ())
 if any('supplier' in r.casefold() or r.casefold()=='guest' for r in roles) or not roles or not roles & COMMERCIAL_ROLES:
  return Proposal('DENIED',reason='role not authorized for assistant',source_ignored=src)
 # Tenant authority is mandatory even for non-company-argument read tools.
 # This value must only be constructed within authenticated server code.
 if not isinstance(trusted_company,str) or not trusted_company.strip():
  return Proposal('DENIED',reason='authenticated tenant context unavailable',source_ignored=src)
 if MUTATION.search(question) or (SOURCE_CLAIM.search(question) and BAD_SOURCE.search(question)):
  return Proposal('DENIED',reason='mutation, unsupported command or embedded hostile instructions',source_ignored=src)
 if _has(question,r'\bscreenshot\b|\bassume\b'):
  return Proposal('NEEDS_CLARIFICATION',reason='unverified screenshot or asserted payment cannot establish truth',source_ignored=src)
 if _has(question,r'\bstock\b|स्टॉक') and _has(question,r'\bbank\b|\boutstanding\b|\breceivable\b'):
  return Proposal('NEEDS_CLARIFICATION',reason='mixed physical and money request',source_ignored=src)
 vals,error=_ids(question)
 if error:return Proposal('NEEDS_CLARIFICATION',reason=error,source_ignored=src)
 if len(set(vals)-{'company'})>1:
  return Proposal('NEEDS_CLARIFICATION',reason='multiple record domains in one question',source_ignored=src)
 mentioned_company=vals.get('company')
 if mentioned_company is not None and mentioned_company.strip().casefold()!=trusted_company.strip().casefold():
  return Proposal('DENIED',reason='explicit company does not match server tenant scope',source_ignored=src)
 # User text referring to an unparsed company must not silently fall back to
 # the authenticated tenant: the operator could be asking about another entity.
 if mentioned_company is None and _has(question,r'\bcompany\s*[:=]?\s+[A-Za-z]|\bfirm\s*[:=]?\s+[A-Za-z]|कंपनी\s+[A-Za-z]'):
  return Proposal('NEEDS_CLARIFICATION',reason='company mentioned but not uniquely identified',source_ignored=src)
 # A record identifier occurring as a filename is not trustworthy identity.
 if _has(question,r'\bfilename\b|\bfile\s+named\b'):
  return Proposal('NEEDS_CLARIFICATION',reason='filename does not establish record identity',source_ignored=src)
 tool=_intent(question,vals)
 if tool is None:
  if _has(question,r'\b(container|cntr|outward|outbound|dispatch|sale|sales|invoice|receipt|bank|payment|customer|buyer|collection|cash|stock|money)\b|कंटेनर|बिक्री|ग्राहक|रसीद|बैंक|भुगतान'):
   return Proposal('NEEDS_CLARIFICATION',reason='read-shaped request lacks a supported unambiguous intent',source_ignored=src)
  return Proposal('UNSUPPORTED',reason='no allowlisted read intent',source_ignored=src)
 if tool in MONEY and not roles & MONEY_ROLES:
  return Proposal('DENIED',reason='role not permitted for Money tools',source_ignored=src)
 # A stated but unparseable cutoff must never be silently dropped.
 # This applies even when the read tool permits an optional cutoff.
 if _has(question,r'\bas\s+of\b') and not DATE_ISO.search(question):
  return Proposal('NEEDS_CLARIFICATION',missing_arguments=('as_of',),reason='explicit cutoff is missing a literal ISO date',source_ignored=src)
 # Only date literals are permitted; no "today", last month, or guessed dates.
 dates=list(dict.fromkeys(DATE_ISO.findall(question)))
 if len(dates)>1:return Proposal('NEEDS_CLARIFICATION',reason='multiple cutoff dates',source_ignored=src)
 if dates:
  try:date.fromisoformat(dates[0])
  except ValueError:return Proposal('NEEDS_CLARIFICATION',reason='invalid ISO cutoff date',source_ignored=src)
 if tool=='sale_as_of' and not dates:
  return Proposal('NEEDS_CLARIFICATION',missing_arguments=('as_of',),reason='historical sale requires literal date',source_ignored=src)
 # Any other family of identifier used in the query is an ambiguity/error.
 required,optional=TOOL_SPEC[tool]; accepted=set(required+optional)
 # sale name and sale_receivable use same typed ID but different param names.
 trans={'container':'container','outward_name':'outward_name','sale':'sale_name' if tool=='sale_as_of' else 'sale',
        'customer':'customer','company':'company','name':'name'}
 args={trans[k]:v for k,v in vals.items() if trans[k] in accepted and k!='company'}
 if 'company' in accepted:args['company']=trusted_company
 extra=[k for k in vals if trans[k] not in accepted]
 if extra:return Proposal('NEEDS_CLARIFICATION',reason='unrelated identifier types: '+', '.join(sorted(extra)),source_ignored=src)
 if dates and 'as_of' not in accepted:
  return Proposal('NEEDS_CLARIFICATION',reason='tool does not accept a cutoff date',source_ignored=src)
 if dates:args['as_of']=dates[0]
 missing=tuple(k for k in required if k not in args)
 if missing:return Proposal('NEEDS_CLARIFICATION',missing_arguments=missing,reason='missing required explicitly supplied arguments',source_ignored=src)
 return Proposal('TOOL_READY',tool=tool,arguments=args,source_ignored=src,
  reason='read proposal only; authenticated backend must revalidate permissions and company')

def authorized_dispatch(question:Any,*,server_roles:Sequence[str],server_company:str|None,
                        server_list_tools:Callable[[],Sequence[Mapping[str,Any]]],
                        server_run_tool:Callable[[str,dict[str,str]],Any],
                        untrusted_source:str|None=None)->dict[str,Any]:
 """Application-server-only bridge; server callbacks must use session-backed Frappe.

 Never expose this function directly with client-provided roles or callbacks.
 A server-side run_tool must re-check roles, company/record scopes and ACL.
 """
 p=propose(question,trusted_roles=server_roles,trusted_company=server_company,untrusted_source=untrusted_source)
 if p.status!='TOOL_READY':return p.to_dict()
 try:
  catalog={t['name']:t for t in server_list_tools() if isinstance(t,Mapping) and isinstance(t.get('name'),str)}
 except Exception:return Proposal('DENIED',reason='authorization catalog unavailable').to_dict()
 if p.tool not in catalog:return Proposal('DENIED',reason='tool not in authenticated role catalog').to_dict()
 if not isinstance(server_company,str) or not server_company.strip():
  return Proposal('DENIED',reason='server has no authenticated company context').to_dict()
 spec=TOOL_SPEC.get(p.tool)
 if not spec or set(p.arguments or {})-set(spec[0]+spec[1]):
  return Proposal('DENIED',reason='invalid tool schema').to_dict()
 # This exact call is the only dispatch path; callback is never user supplied.
 result=server_run_tool(p.tool,dict(p.arguments or {}))
 return {'status':'SERVER_RESULT','tool':p.tool,'arguments':dict(p.arguments or {}),'data':result}
