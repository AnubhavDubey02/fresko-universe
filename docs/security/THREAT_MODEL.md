# THREAT_MODEL — Fresko Universe

**Status:** living · Fresko Security  

## Assets to protect

Customer/buyer & supplier data; WhatsApp messages & evidence; LOT/container data; inventory/ATS; orders/deals; pricing; payments; accounting; identities; tokens/credentials; audit/approval history; ERPNext/Frappe; AI integrations; GitHub repo; CI/CD.

## Adversaries (ASSUMPTIONS)

Malicious or mistaken internal users; compromised accounts; supply-chain / dependency attackers; external API abuse (future); prompt/document injection via AI pipelines (future).

## Priority abuse themes (Phase 1)

1. Approval / rate-floor / oversell bypass  
2. Counter acceptance ACL (D4) bypass via field reassignment  
3. ATS / concurrent double-commit  
4. Silent commercial field edits after lock  
5. Evidence/audit tampering  
6. Privilege via System Manager / role misconfiguration  

Detailed findings belong in `SECURITY_FINDINGS.md` with evidence.
