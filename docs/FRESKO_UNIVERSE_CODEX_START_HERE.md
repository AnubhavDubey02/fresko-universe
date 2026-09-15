FRESKO UNIVERSE

Codex Start Here — Master Build Brief

Architecture and product handoff

09 September 2026

Working definition: WhatsApp-first Produce Trade Operating SystemPrimary build philosophy: Free/open-source first; pay only where a compliant, reliable free route is not practical.

0. Instructions to Codex — read this before touching code

Treat this file as the current project memory and architecture brief for Fresko Universe. Do not restart product discovery from zero unless a decision below is explicitly reopened.

Before making a substantial architectural change:

Inspect the existing repository and current implementation.

Inspect the referenced Google Drive artifacts if access is available.

Preserve the principles in Section 3 unless the user explicitly changes them.

Prefer extending ERPNext/Frappe instead of recreating accounting, inventory, customers, permissions, or audit concepts that already exist.

Keep AI probabilistic work separate from deterministic financial truth.

Never silently mutate an approved financial record. Revisions must preserve old value, new value, actor, time, reason, and evidence.

Optimize for a simple phone experience for operational users and a richer desktop experience for reconciliation/admin.

Build free/open-source first. Paid APIs are escalation/fallback paths, not the default for every event.

Keep the AI provider replaceable behind an internal adapter/router.

Maintain a DECISIONS.md and OPEN_QUESTIONS.md in the repository as development progresses.

Recommended first repo files

/README.md                         # short project entry point/docs/FRESKO_UNIVERSE_CODEX_START_HERE.md/docs/ARCHITECTURE.md/docs/DATA_MODEL.md/docs/WORKFLOWS.md/docs/DECISIONS.md/docs/OPEN_QUESTIONS.md/docs/SOURCES.md

If this document is copied into the repo, preserve it as a project reference and update a dated changelog rather than overwriting the historical decisions without trace.

1. Executive summary

Fresko Universe is not merely a CRM or a QC app. The intended product is a Produce Trade Operating System that connects the full lifecycle of an imported produce shipment/container:

Shipment / Container      ↓Product / Lot / Grade / Count      ↓QC Evidence      ↓Buyer / Deal / Price Approval      ↓Delivery Order / Outward / Vehicle      ↓Collection / Payment Evidence      ↓Expenses / Accounting      ↓Reconciliation / Exceptions      ↓Container Settlement / Partner Transparency

The product should make the operational experience feel close to WhatsApp + camera + a few approval buttons, while the backend maintains a rigorous evidence-linked ledger.

The simplest description for users is:

WhatsApp is the inbox. The ledger is the truth.

2. Why this product exists — problems observed in a real container reconciliation

The third plum-container reconciliation exposed recurring operational failure modes that Fresko Universe should prevent by design:

The digital sales ledger, handwritten/manual ledger, cold-storage outward register, payment evidence and closing summaries did not always use the same timing or transaction granularity.

A transaction could be written as a short alias such as AZ, AZ/SSK, PG, MD, GVD, etc., making buyer identity difficult to resolve later.

Rate changes could appear in one source but not another.

“Hold gatepass” notes could conflict with later physical outward evidence.

Physical dispatch could exist without a clean manual/digital sale mapping.

The same commercial order could potentially appear in different documents at different dates, creating duplicate-count risk.

Payment messages/screenshots could be interpreted as paid even when bank clearing evidence was not yet final.

Closing the container required manual arithmetic and human reconstruction of what was sold, dispatched, paid and still outstanding.

QC evidence existed informally or not at all, making it difficult to show a supplier/partner what quality looked like at opening, cold storage and dispatch.

The product should convert these from end-of-month forensic exercises into real-time exceptions.

Concrete design lesson

A final container close should never require asking, “Are we at 3,104, 3,193 or 3,196 crates?” without the system immediately showing:

physical inward,

approved sold quantity,

physical outward,

pending outward,

cancelled quantity,

unsold quantity,

direct receipts,

recorded but unverified payments,

verified payments,

unresolved exceptions.

3. Non-negotiable product principles

3.1 WhatsApp is the inbox; ledger is the truth

WhatsApp messages, photos, voice notes and documents are evidence/input. They are not the accounting database.

3.2 AI extracts and proposes; deterministic systems decide financial truth

AI may parse:

buyer name/alias,

product,

lot,

count/size,

quantity,

rate,

vehicle,

payment amount/reference,

QC issue labels,

handwritten/document content.

AI must not independently decide:

stock balance,

approved selling-rate boundaries,

whether a duplicate is financially valid,

final receivable,

whether a bank payment is cleared,

whether an exception is closed.

Those are determined by code, workflow state and authorized human approval.

3.3 No silent edits

Approved/posted records are append/revision oriented. Every change must retain:

old_valuenew_valuechanged_bychanged_atreasonsupporting_evidenceapproval_reference (when required)

3.4 Evidence must remain linked to the commercial record

The system should let a reviewer drill from:

Container → Lot → Deal → Approval → QC → Outward → Payment → Settlement

3.5 Free/open-source first

Before adding a subscription or paid service, ask:

Is there a reliable open-source/self-hosted option?

Can Frappe already do this?

Can deterministic code do this without AI?

Can local OCR/document tooling handle it?

If an external API is genuinely better, can it be used only as an escalation path?

3.6 Provider independence

Do not make the product dependent on a single AI vendor. Implement internal interfaces such as:

interface AIProvider {  extractStructured(input: ExtractionRequest): Promise<ExtractionResult>  reason(input: ReasoningRequest): Promise<ReasoningResult>}

The router can choose local tools, OpenAI, Gemini or another future model according to task, confidence, latency and cost.

4. Primary users and permission boundaries

Operational salesperson / agent

Needs: - submit deal quickly, - attach photos, - see approval status, - see only relevant stock/rate guidance, - submit dispatch/payment evidence, - minimal accounting complexity.

Owner / authorized approver

Needs: - approve/reject/counter below-floor deals, - see exceptions, - see current stock/sales/collections, - audit changes, - close a container.

Accounts / reconciliation user

Needs: - map payments, - verify settlement, - reconcile outward vs approved deals, - party ledger, - container P&L, - aged receivables, - evidence drill-down.

Cold-storage / logistics source

May contribute: - inward, - outward, - gatepass, - delivery-order status, - lot/vehicle evidence.

This source should be treated as authoritative for physical movement, not for sale rate unless explicitly configured.

Chinese supplier/partner

Needs read-only bilingual visibility: - container status, - quality timeline, - sales/realisation summary, - dispatch timeliness, - expenses, - settlement, - exceptions requiring explanation.

Should not receive unrestricted internal operational access.

5. Free-first architecture decision

5.1 Minimal V1 stack — preferred starting point

Start smaller than the originally discussed multi-service stack.

Meta WhatsApp Cloud API (official)            ↓Fresko webhook / ingestion service            ↓Frappe / ERPNext + custom Fresko app            ↓Frappe background jobs + webhooks            ↓Local document/OCR tools            ↓AI Router → external frontier model only when needed            ↓Frappe/PWA operational UI + partner portal

Why: Frappe already has REST APIs, background jobs, webhooks, authentication, roles, forms, reporting and ERPNext accounting/stock. Adding Chatwoot + Activepieces + Metabase on day one increases server footprint and operations before we have proven the need.

5.2 Optional components — add only when justified

Chatwoot Community EditionAdd if a shared multi-agent inbox/conversation UI becomes valuable. It is free/self-hostable, but its published production requirements are materially heavier than a minimal Fresko backend.

Activepieces Community EditionAdd when non-developers need visual workflow automation or many third-party connectors. Frappe background jobs/webhooks can handle many V1 automations directly.

Metabase Open SourceAdd if Frappe reports no longer meet analytics needs. Note AGPL implications before embedding or redistributing.

Next.js custom frontendAdd only if Frappe Desk/portal/PWA cannot achieve the desired operational UX. Avoid building a second full frontend before validating workflows.

6. System of record

Decision

ERPNext/Frappe is the primary system of record.

Do not use Supabase/PostgreSQL as a second competing business database for core financial truth in V1.

Use ERPNext standard entities wherever possible:

Company

Customer

Supplier

Item

Batch

Warehouse

Sales Order / Delivery Note / Sales Invoice where appropriate

Payment Entry

General Ledger / accounting dimensions

Stock transactions

Build Fresko-specific DocTypes only for concepts ERPNext does not model cleanly.

Important implementation rule

Do not automatically force every produce-specific object into a standard ERPNext document if that distorts the real workflow. Use custom operational records and link them to ERPNext accounting/stock documents at the right lifecycle stage.

7. Proposed Fresko custom domain model

The exact model should be validated against the ERPNext version installed, but the current conceptual model is:

Company ├─ Partner / Supplier └─ Shipment / Container      ├─ Product      ├─ Lot / Batch      ├─ Grade / Count / Size      ├─ QC Event(s)      ├─ Deal(s)      │    ├─ Buyer Alias Resolution      │    ├─ Price Approval      │    ├─ Evidence      │    └─ Dispatch link(s)      ├─ Expense(s)      ├─ Payment / Collection link(s)      ├─ Exception(s)      └─ Container Settlement

Candidate custom DocTypes

Fresko Container

Fields: - container_id - supplier_partner - country_of_origin - product - arrival_date - inward_qty - unit - landed_cost - currency - status - source_documents - closing_status

Fresko Deal

Fields: - deal_id - container - customer / unresolved_buyer_alias - product - lot/batch - count_size - qty - proposed_rate - approved_rate - currency - salesperson - status - source_message_id - created_at - approval_required - approval_id - duplicate_fingerprint

Fresko Approval

Fields: - approval_id - deal_id - rule_trigger - requested_rate - policy_floor - policy_ceiling - decision: APPROVE / REJECT / COUNTER - decision_rate - approver - timestamp - reason

Fresko QC Event

Fields: - qc_event_id - container - lot - deal (optional) - stage: OPENING / COLD_STORAGE / PRE_DISPATCH / DISPATCH / COMPLAINT - status: NO_ISSUE / CONCERN / COMPLAINT / NO_EVIDENCE - issue_types - notes - observed_by - observed_at

Fresko Evidence

Fields: - evidence_id - type: WHATSAPP_MESSAGE / IMAGE / PDF / XLSX / GATEPASS / PAYMENT / VOICE / OTHER - original_file/reference - source_actor - received_at - message_id - sha256/content_hash - parser_version - extraction_json - confidence - human_verified

Fresko Buyer Alias

Fields: - raw_alias - normalized_alias - confirmed_customer - confidence - status - first_seen - last_seen

Fresko Buyer Candidate

Fields: - alias - candidate_name - public_source - internal_evidence - score - status: SUGGESTED / CONFIRMED / REJECTED

Fresko Exception

Fields: - exception_id - type - severity - container - deal/payment/dispatch reference - description - expected_value - observed_value - status - assigned_to - supporting_evidence - resolution_note

Fresko Container Settlement

Fields: - container - inward_qty - approved_sold_qty - physical_outward_qty - pending_outward_qty - cancelled_qty - unsold_qty - gross_sales - verified_collections - reported_unverified_collections - direct_receipts - expenses - receivable - partner_balance - unresolved_exception_count - closed_by - closed_at

8. Deal lifecycle and deterministic state machine

Primary deal lifecycle:

PROPOSED   ├──→ AUTO_APPROVED   └──→ APPROVAL_REQUIRED             ├──→ APPROVED             ├──→ COUNTERED             └──→ REJECTEDAPPROVED / AUTO_APPROVED   ↓OUTWARD_PENDING   ↓DISPATCHED   ↓PAYMENT_PENDING   ↓PAID   ↓RECONCILED

Additional terminal/interruption states:

CANCELLEDPARTIALLY_DISPATCHEDPARTIALLY_PAIDDISPUTED

State transitions must be validated in code. Do not allow arbitrary UI edits to set impossible states.

9. Price approval workflow

Example inbound message:

Rehan 50 crate 41869 600

AI/parser extraction:

{  "buyer_alias": "Rehan",  "qty": 50,  "unit": "crate",  "lot": "41869",  "proposed_rate": 600}

Deterministic rules then check:

Is the lot valid for this container?

Is sufficient available quantity present?

Is the rate inside the allowed band?

Is the buyer blocked or above exposure limit?

Is the same message/deal fingerprint already processed?

Are mandatory fields present?

If approved price range is ₹630–₹700 and proposed rate is ₹600:

APPROVAL REQUIREDBuyer: RehanQty: 50Lot: 41869Proposed: ₹600Floor: ₹630[Approve] [Counter] [Reject]

A human approval must write an immutable approval record. Do not merely overwrite proposed_rate.

10. Stock and dispatch controls

Required stock identities

For each container, continuously calculate:

physical_inwardapproved_soldphysical_outwardpending_outwardcancelledavailable_to_sellunsold

Potential formulas must be defined carefully to avoid double counting. For example, a deal is not automatically physical outward.

Key exception rules

Create an exception when:

physical outward exists with no approved Deal ID,

approved deal exceeds available stock,

duplicate gatepass/outward appears,

physical outward quantity exceeds approved quantity without explicit split/adjustment,

container close does not reconcile to inward quantity,

lot-level outward exceeds lot inward,

gatepass status conflicts with a later physical movement,

a transaction is edited after dispatch without revision/approval.

ERPNext batch use

ERPNext supports batch tracking and requires batch references on stock transactions for batched items. Use that capability where it maps cleanly to Fresko lot tracking; preserve the original commercial LOT No. as an explicit reference even if an ERPNext batch ID differs.

11. WhatsApp architecture

Goal

Make WhatsApp a low-friction operational entry point without making it the database.

Official route only

Use Meta WhatsApp Business Platform / Cloud API rather than unofficial WhatsApp Web automation for production.

Cost strategy

Meta’s current pricing page states that service messages inside the user-initiated 24-hour customer-service window are free, and utility messages sent in response to users are also not charged. Other business-initiated messages may be charged by market/category. Therefore:

favor user-initiated operational interactions,

use Fresko PWA push/in-app notifications for internal approvals when possible,

avoid unnecessary outbound templates,

log WhatsApp cost by message category once production traffic begins.

Ingestion examples

SALE Rehan 50 / 41869 / 650QC 41871 + photosPAYMENT Rehan 50000 + screenshotSTOCKDEAL 1052

Natural-language messages should also work; commands are only a low-ambiguity option.

Idempotency

Persist:

WhatsApp message ID,

sender,

timestamp,

attachment IDs,

content hash,

ingestion status.

Never create a second financial event when the same WhatsApp event is retried or forwarded internally.

Chatwoot decision

Chatwoot remains a strong optional shared-inbox layer and supports WhatsApp Cloud on self-hosted deployments. However, its published production recommendation is around 4 CPU / 8 GB RAM minimum, so do not make it a mandatory V1 dependency if the immediate requirement is only ingestion + a simple operational UI.

12. Document, photo and voice ingestion

Accepted evidence types should include:

WhatsApp text

photos / handwritten sheets

PDFs

Excel files

payment screenshots

stock / pending-DO reports

gatepasses

expense receipts

voice notes

Free/local-first processing pipeline

Input  ↓File type detection  ↓Docling / PaddleOCR / text parser / faster-whisper  ↓Structured candidate extraction  ↓Confidence + deterministic validation  ↓If uncertain → frontier AI API  ↓If financially consequential ambiguity remains → human verification  ↓Approved structured record

Never discard source evidence

Store the original attachment and parser/model version. If a parser improves later, the document can be reprocessed while retaining the historical extraction used at the time.

13. AI layer

Core decision

Do not “train a Fresko model” on day one.

Start with:

Base models/tools + live Fresko database + deterministic tools + evidence retrieval

Operational facts such as stock, rate floor, collections and buyer balance must be queried from current data rather than memorized in model weights.

AI Router

Suggested internal tiers:

TIER 0 — No AIArithmetic, stock, accounting, state transitions, rate rules, duplicate checks.TIER 1 — Free/localOCR, simple extraction, classification, voice transcription.TIER 2 — Cost-efficient APIMessy extraction, ambiguous text/image parsing.TIER 3 — Frontier reasoningComplex cross-document reconciliation, difficult multimodal reasoning.TIER 4 — HumanHigh-value ambiguity, model disagreement, financial exception closure.

Model-provider policy

OpenAI can be the preferred frontier fallback if it wins Fresko-specific evaluations. Gemini or other providers may be used for tasks where they are demonstrably better/cheaper. The application must not expose vendor-specific model names in business logic.

Structured outputs

When using an external model for extraction, require schema-constrained structured output whenever available.

Example schema:

{  "event_type": "sale_proposal",  "buyer_alias": "string|null",  "qty": "number|null",  "unit": "crate|box|kg|null",  "rate": "number|null",  "lot": "string|null",  "vehicle": "string|null",  "confidence": {    "buyer_alias": 0.0,    "qty": 0.0,    "rate": 0.0,    "lot": 0.0  },  "needs_human_review": true}

Do not let model confidence equal truth

Confidence determines routing/review. It never creates accounting finality.

14. Future proprietary Fresko dataset

From day one, preserve:

original inputAI/local extractionhuman correctionfinal approved structured recordmodel/parser version

This creates a high-value domain dataset for:

produce-trade abbreviations,

party-name resolution,

handwritten ledger extraction,

lot/count/size understanding,

document matching,

QC issue classification,

exception detection.

Only after enough verified examples exist should we evaluate fine-tuning or self-hosting a domain model.

Economics rule

Do not self-host a large GPU model merely because it is “open source.” Compare:

GPU/server + electricity + maintenance + opsvs.actual API cost at Fresko traffic volume

Self-host only when quality, privacy, latency or economics justify it.

15. Fresko-specific AI benchmark

Before committing to an AI provider, create a benchmark set from real business data.

Suggested categories:

clean WhatsApp order extraction,

messy WhatsApp abbreviations,

handwritten quantities/rates,

overwritten handwriting,

lot/vehicle extraction,

payment screenshot extraction,

PDF outward-table extraction,

duplicate detection assistance,

buyer alias resolution,

cross-document transaction matching,

reconciliation explanations,

QC photo issue labeling.

Metrics:

field exact-match accuracynumeric accuracyfalse-positive ratehallucination ratehuman-review ratelatencycost / 1,000 eventsreconciliation success rate

For financial fields, a single digit error is a failure; do not use fuzzy scoring for quantity/rate/amount.

16. Buyer Identity Resolution engine

This emerged from real aliases such as:

AZAZ/SSKAZ/PGAZ/TbzAZ/MDAZ/EMAZ/GVDMoryaRoyal FruitRehan / RehaanAshapuraMahalakshmi

The system should not blindly rename aliases. It should produce candidates.

Example:

Ledger alias: AZ/SSKCandidate: SSK Fresh Fruit Pvt LtdConfidence: 82%Evidence:  - initials/name similarity  - fresh fruit / plum trade fit  - Navi Mumbai trade geography  - repeated internal transaction patterns[CONFIRM] [WRONG MATCH] [NEED MORE EVIDENCE]

Candidate scoring signals

Use, in decreasing order of evidentiary strength where available:

payment sender legal name,

GST/FSSAI/legal identifiers,

WhatsApp phone/contact,

delivery address,

bank beneficiary/remitter evidence,

repeated vehicle/location patterns,

gatepass/customer name,

historical confirmed mappings,

public business name/location/trade match,

text/initial similarity.

Public web results are candidate-generation evidence, not identity proof.

Once confirmed, maintain alias history:

AZ/SSK → confirmed Customer XSSK → same Customer Xother observed spelling → same Customer X

Never destroy the original alias that appeared in the source document.

17. QC module — photo-first, evidence-first

The Chinese partner specifically wants standalone quality feedback/evaluation for each container and considers quality as important as cost/price and delivery timeliness.

Realistic QC stages

1. Container Opening QC2. Cold Storage Entry / Random Sample QC3. Sale / Pre-dispatch / Dispatch QC4. Complaint / Rejection evidence if any

QC statuses

Do not invent pseudo-scientific numeric quality scores from ordinary photos.

Use defensible statuses:

🟢 NO ISSUE REPORTED🟡 QUALITY CONCERN🔴 COMPLAINT / REJECTION⚪ NO QC EVIDENCE

Issue categories:

soft fruit

damaged

rotten

colour

size

packaging

moisture/leakage (if relevant)

other

QC evidence object

Each QC photo set should link to:

containerlotcount/size if knowndeal if applicablebuyer if applicablestagetimestampuploaderoriginal imageshuman notesAI-suggested labels (optional)

Partner timeline

The partner should be able to see:

Origin/loading evidence→ India container opening→ cold-storage sample(s)→ dispatch sample(s)→ complaint/rejection evidence→ commercial outcome

18. Chinese partner portal

Provide English + Simplified Chinese views from the same underlying data.

Container summary

Original QtyApproved Sold QtyPhysical Dispatched QtyPending OutwardRemaining / UnsoldGross SalesVerified CollectionsReceivableExpensesNet RealisationQuality StatusDelivery TimelinessReconciliation Status

Drill-down

Container  → Lot    → Deal      → Approval        → QC Photos          → Gatepass / Outward            → Payment

Traffic-light transparency

GREEN  = verified / reconciledYELLOW = evidence pending / review requiredRED    = exception / mismatch / dispute

Container Settlement Certificate

At close, generate a signed/approved settlement snapshot containing:

inward quantity,

sale quantity,

dispatch quantity,

closing stock,

rate/value summary,

collections,

direct receipts,

expenses,

receivable/payable,

unresolved exceptions,

QC summary,

closure timestamp/approver.

A container with unresolved material exceptions should not appear “fully reconciled.”

19. Payments and collections

Payment states

REPORTEDEVIDENCE_RECEIVEDVERIFICATION_PENDINGVERIFIED / CLEAREDMATCHED_TO_RECEIVABLERECONCILEDREJECTED / REVERSED

A WhatsApp screenshot or message saying a payment was made must not directly set VERIFIED.

Evidence examples

bank statement line,

bank API/connector confirmation,

UTR/reference matched to bank credit,

cash deposit evidence + authorized cash confirmation.

Direct receipt

Support situations where a buyer pays the owner/company directly rather than through the intermediary being settled. The sale remains in gross sales, while the amount may be excluded from the intermediary’s amount-to-settle. This needs an explicit, auditable field rather than an informal spreadsheet adjustment.

20. Accounting and container economics

ERPNext should handle the accounting engine where possible.

Per container, Fresko needs a management view of:

opening/inward stocklanded costsalesclosing stockcost of goods / gross margintransportcommissioncold storagehandling/labourother direct expensesnet container resultverified collectionsreceivablespayablespartner balance

Outputs:

Container P&L

Party Ledger

Stock Register

Expense Ledger

Bank/Cash Book

Receivable Ageing

Exception Register

Partner Settlement

Tax/GST rule

Do not hard-code legal/tax conclusions during product prototyping. Tax treatment, ledger mapping and statutory configuration must be reviewed/configured with a qualified CA/accountant for the actual entity and transaction model.

21. Exception engine

High-value exception types:

OUTWARD_WITHOUT_DEALDEAL_WITHOUT_OUTWARDRATE_BELOW_FLOORRATE_CHANGED_AFTER_APPROVALQTY_EXCEEDS_AVAILABLE_STOCKLOT_OVERDRAWNDUPLICATE_MESSAGEDUPLICATE_GATEPASSPAYMENT_REPORTED_NOT_VERIFIEDPAYMENT_UNMATCHEDBUYER_UNRESOLVEDQC_EVIDENCE_MISSINGCOMPLAINT_WITHOUT_QC_HISTORYCONTAINER_QTY_NOT_RECONCILEDSETTLEMENT_VALUE_MISMATCHMANUAL_OVERRIDE

Each exception should have:

severityownercreated_atevidenceexpected vs observedstatusresolutionresolved_byresolved_at

The dashboard should prioritize exceptions requiring action, not drown users in raw ERP records.

22. Audit and evidence integrity

Required controls

immutable original source message/file reference,

content hash for attachments,

idempotency key for external events,

created_by / modified_by,

revision history,

explicit approval trail,

reason required for material correction,

role-based permissions,

audit export per container.

Evidence authority by source

Suggested default:

Agent/salesperson → proposed deal / buyer conversationOwner/approver → commercial approvalCold storage → physical inward/outward/gatepass/DOBank/accounts → cleared paymentTransporter → freight/vehicle evidenceQC observer → observed quality evidence

This does not mean a source can never be wrong. It determines which conflict should be escalated and what evidence is required to override it.

23. UX principles

Mobile operational UI

Home screen should emphasize:

New Deal

Pending Approvals

Add QC Photos

Record Dispatch Evidence

Record Payment Evidence

Exceptions

Stock Snapshot

Avoid exposing a giant ERP navigation tree to a salesperson.

Owner approval card

PRICE APPROVAL REQUIREDRehan50 crates | Lot 41869Agent rate: ₹600Allowed floor: ₹630Available stock: 82[APPROVE ₹600] [COUNTER] [REJECT]

Desktop reconciliation

Provide side-by-side evidence views:

Deal | Outward | Payment | QC | Exceptions

Users should be able to reconcile by transaction and by container.

24. Suggested service/module boundaries

Do not create microservices prematurely. A modular monolith inside the Frappe custom app is acceptable for V1.

Suggested logical modules:

fresko_corefresko_dealsfresko_approvalsfresko_inventoryfresko_qcfresko_evidencefresko_whatsappfresko_aifresko_paymentsfresko_reconciliationfresko_partner_portalfresko_identity

External adapters:

Meta WhatsApp AdapterOpenAI AdapterGemini Adapter (optional)Local OCR AdapterDocling AdapterBank/statement importer

25. AI/tool contracts — suggested pattern

Extraction result

export type FieldEvidence = {  value: string | number | null;  confidence: number;  sourceSpan?: string;  evidenceId: string;};export type SaleExtraction = {  buyerAlias: FieldEvidence;  qty: FieldEvidence;  rate: FieldEvidence;  lot: FieldEvidence;  vehicle: FieldEvidence;  countSize: FieldEvidence;  needsHumanReview: boolean;  parserVersion: string;};

Rule result

export type RuleDecision = {  decision: "AUTO_APPROVE" | "APPROVAL_REQUIRED" | "REJECT";  reasons: string[];  ruleVersion: string;};

Do not mix the AI confidence object and the business rule decision into one opaque “AI score.”

26. API boundary

Frappe exposes REST/RPC APIs for DocTypes. Use that rather than bypassing Frappe’s permission/document layer with direct database writes from external services.

Examples of intended routes/concepts (actual names to be implemented):

POST /api/resource/Fresko DealPOST /api/method/fresko.whatsapp.ingestPOST /api/method/fresko.deals.submit_for_approvalPOST /api/method/fresko.approvals.decidePOST /api/method/fresko.qc.attach_evidencePOST /api/method/fresko.reconciliation.run_containerGET  /api/method/fresko.container.snapshotGET  /api/method/fresko.partner.container_view

Write actions should validate authorization and state transitions server-side.

27. Reconciliation model

For every container, compute distinct ledgers rather than conflating them:

COMMERCIAL LEDGER      approved deals / cancellations / approved revisionsPHYSICAL LEDGER        inward / outward / warehouse movementsCOLLECTION LEDGER      reported / verified / matched paymentsEXPENSE LEDGER         direct expensesQC LEDGER              evidence/status events

The reconciliation engine compares these ledgers and creates exceptions.

Example invariants

At final close, subject to configured business rules:

INWARD = PHYSICAL_OUTWARD + PHYSICAL_REMAININGAPPROVED_SOLD = DISPATCHED_SOLD + SOLD_PENDING_OUTWARD + CANCELLED_ADJUSTMENTS(if relevant)GROSS_SALES - DIRECT_RECEIPTS_EXCLUDED_FROM_AGENT_SETTLEMENT  = AGENT_SETTLEMENT_BASISAGENT_SETTLEMENT_BASIS - VERIFIED_SETTLEMENT_PAYMENTS  = BALANCE_PAYABLE

Do not encode these exact formulas blindly; confirm the legal/commercial meaning of each adjustment. The important design requirement is that every difference must be explainable by a named category rather than a manual plug.

28. Real-world reference artifacts in Google Drive

Codex has access to Google Drive according to the user. These files are useful as test fixtures / domain examples. Do not modify originals unless explicitly asked.

Key current files

Fresko Third Container - Final Ledger - 3196 Crates - 09 Sep 2026.xlsx

Our-side final ledger basis.

Treats all 3,196 crates as sold.

Includes a 92-crate balance line at ₹700 as user-instructed commercial closing treatment.

This is a business decision basis, not evidence that all 92 are individually mapped to lot/vehicle records.

Fresko Third Container - Collection Set - 07 Sep 2026.xlsx

Evidence-oriented collection working set built from manual sale records plus later outward-only quantities where a user-instructed rate was applied.

Fresko Third Container - Internal Digital Control Set - 07 Sep 2026.xlsx

Internal digital-ledger control view; useful for demonstrating why order-book timing and dispatch timing must remain distinct.

Important warning for training/tests

Do not treat every number in a reconciled spreadsheet as a ground-truth label automatically. Some rows represent explicit user instructions, provisional mappings or commercial closing assumptions. Test datasets must mark:

VERIFIED_SOURCEUSER_CONFIRMEDINFERREDPROVISIONALUNRESOLVED

This provenance concept should exist in Fresko Universe itself.

29. Buyer-resolution prototype candidates already identified

These are candidate leads, not confirmed identity mappings:

AZ/SSK → SSK Fresh Fruit Pvt Ltd is a high-interest candidate because public information shows a fresh-fruit importer/wholesaler dealing in stone fruit including plums and operating in Navi Mumbai/Turbhe.

AZ/PG → PG Exports is an initial candidate based on initials, fresh-produce trade and Vashi geography.

Other aliases such as Morya, Royal Fruit, Rehan, Ashapura, MD, Mahalakshmi remain lower-confidence until internal evidence resolves them.

The product feature should store candidates and let an authorized user confirm/reject them.

30. V1 build plan

Phase 0 — repo and environment

Deliverables: - Frappe/ERPNext dev environment reproducible via Docker/bench. - Custom app skeleton: fresko_universe. - .env.example; no secrets committed. - CI for lint/tests. - docs folder containing this brief.

Phase 1 — core data and deterministic deal workflow

Deliverables: - Container, Deal, Approval, Evidence, Exception, QC Event DocTypes. - Role definitions. - Deal state machine. - rate-floor rule. - stock availability rule. - revision/audit mechanism. - basic mobile-friendly forms.

Acceptance scenario: salesperson submits 50 crates below floor → owner gets approval → counter/approval is stored → approved deal cannot be silently edited.

Phase 2 — WhatsApp ingestion

Deliverables: - Meta webhook endpoint. - message/event idempotency. - text + attachment ingestion. - basic deterministic parser for common order syntax. - map message → proposed Deal.

Acceptance scenario: sending Rehan 50 crate 41869 650 produces one proposed deal even if webhook is delivered more than once.

Phase 3 — outward and reconciliation

Deliverables: - import/record cold-storage outward. - link outward to Deal ID. - exception for outward without approved deal. - container stock snapshot. - reconciliation screen.

Phase 4 — payment evidence

Deliverables: - payment report/evidence workflow. - reported vs verified states. - payment matching. - party/container balance.

Phase 5 — QC

Deliverables: - opening/cold-storage/dispatch photo evidence. - issue/status workflow. - QC timeline. - partner-facing summary.

Phase 6 — AI router

Deliverables: - local parser/OCR adapter. - OpenAI adapter. - provider-neutral schema. - confidence-based escalation. - human correction capture. - benchmark harness.

Phase 7 — buyer identity resolution

Deliverables: - alias master. - candidate matching. - evidence scoring. - confirm/reject workflow.

Phase 8 — partner portal and container settlement

Deliverables: - bilingual read-only portal. - container timeline. - financial/QC/dispatch summary. - closing certificate.

31. V1 deliberately out of scope

Unless required for a real workflow, do not start with:

training a custom foundation model,

GPU server infrastructure,

Kubernetes,

microservices,

a separate data warehouse,

a custom accounting engine,

an elaborate native iOS/Android app,

Chatwoot + Activepieces + Metabase simultaneously,

blockchain/immutable ledger technology,

automatic AI-generated “quality score” presented as objective fact,

fully autonomous financial exception closure.

32. Security and privacy checklist

Before production:

HTTPS only.

secrets in environment/secret manager, never repo.

webhook signature validation where provider supports it.

least-privilege API users.

role-based DocType permissions.

audit logs retained.

attachment access controlled.

encrypted backups.

restore procedure tested.

user offboarding procedure.

production/test data separation.

API usage/billing limits.

redaction/minimization for data sent to external AI providers.

For external AI, send the minimum information necessary for the task. Do not send entire accounting histories when a single cropped document/event is sufficient.

33. Architecture diagram

flowchart TD    WA[WhatsApp / Photos / Voice / Files] --> ING[Official Meta Cloud API + Ingestion]    UI[Phone / PWA / Desktop] --> FRAPPE[Frappe + ERPNext]    ING --> EVID[Evidence Store / Fresko Evidence]    EVID --> PARSE[Local Parse: Docling / PaddleOCR / Whisper]    PARSE --> VALIDATE[Schema + Deterministic Validation]    VALIDATE -->|high confidence| RULES[Business Rules Engine]    VALIDATE -->|uncertain| AIR[AI Router]    AIR --> OAI[Frontier AI API]    AIR --> ALT[Other Provider Optional]    OAI --> REVIEW[Human Review if material ambiguity]    ALT --> REVIEW    REVIEW --> RULES    RULES --> DEAL[Deal / Approval / QC / Dispatch / Payment]    DEAL --> FRAPPE    FRAPPE --> RECON[Reconciliation + Exception Engine]    RECON --> OWNER[Owner / Accounts Dashboard]    RECON --> PARTNER[English + Chinese Partner Portal]

34. Decision log as of 09-Sep-2026

Decision

Current position

Product category

Produce Trade Operating System

System of record

ERPNext/Frappe

Operational channel

WhatsApp-first, but WhatsApp not ledger

WhatsApp integration

Official Meta Cloud API

App UX

PWA/mobile first; desktop reconciliation

Custom frontend

Optional; use Frappe first

Chatwoot

Optional shared inbox, not mandatory V1

Activepieces

Optional workflow glue, not mandatory V1

Metabase

Optional analytics layer

AI

Provider-neutral router; external frontier models only when needed

Training

Do not train first; collect verified training/eval data from day one

Financial truth

Deterministic rules + authorized human workflow

QC

Photo-first evidence/status; no fake precision

Partner transparency

Bilingual container/QC/financial portal

Buyer names

Alias-resolution engine with candidates and confirmation

Cost philosophy

Free/open-source first, paid fallback

Database

Frappe-supported DB architecture; no competing Supabase SoR

Audit

No silent edits; preserve revision/evidence chain

35. Open questions Codex should not silently decide

These require user/business/CA input before hard-coding:

Exact legal entities/company structure and partner accounting model.

GST/tax configuration and invoice timing.

Whether every approved deal should immediately create a Sales Order or only after dispatch confirmation.

Exact meaning and authority of “direct receipt” across different buyers/agents.

Rate-floor ownership and whether floors are container/lot/count/buyer-specific.

Credit/exposure rules per buyer.

Exact stock reservation semantics for an approved but not dispatched deal.

How cold-storage integrations will arrive in production: WhatsApp files, Excel, email, API, or portal entry.

WhatsApp number/account to use for production and consent/template policy.

Chinese partner’s desired financial granularity and access permissions.

Final public buyer identity mappings.

Retention period for WhatsApp messages/images and QC evidence.

36. Public sources and implementation references

All links below were checked/researched for this build brief around 09-Sep-2026. Codex should prefer primary/official documentation and re-check version-specific behavior during implementation.

S1 — ERPNext repository / license / capabilities

https://github.com/frappe/erpnext

Why it matters: ERPNext is GPL-3.0, open source, and includes accounting, stock, order/customer/supplier workflows. Its repository also documents self-hosted setup.

S2 — Frappe Framework repository / license / architecture

https://github.com/frappe/frappe

Why it matters: Frappe is MIT-licensed, uses Python + MariaDB in its documented stack, provides built-in role permissions, admin forms, reporting and REST APIs.

S3 — Frappe REST API

https://docs.frappe.io/framework/user/en/guides/integration/rest_api

Why it matters: Frappe exposes CRUD/RPC APIs for DocTypes; external services should integrate through this layer rather than bypass permissions with direct DB writes.

S4 — Frappe background jobs

https://docs.frappe.io/framework/user/en/api/background_jobs

Why it matters: V1 can run asynchronous parsing/reconciliation tasks without immediately adding a separate workflow platform.

S5 — Frappe webhooks

https://docs.frappe.io/framework/v14/user/en/guides/integration/webhooks

Why it matters: Frappe can emit HTTP callbacks on document events. Re-check the current-version documentation path when implementing.

S6 — ERPNext batch tracking

https://docs.frappe.io/erpnext/batch

Why it matters: Supports batch/lot-like inventory tracking and batch references in stock transactions.

S7 — ERPNext serial and batch model

https://docs.frappe.io/erpnext/serial-and-batch

Why it matters: Current ERPNext documentation describes batch/serial traceability and version-specific behavior.

S8 — ERPNext stock reconciliation

https://docs.frappe.io/erpnext/stock-reconciliation

Why it matters: Physical stock vs system stock reconciliation is a first-class ERP concept we should reuse where possible.

S9 — ERPNext accounting entries

https://docs.frappe.io/erpnext/accounting-entries

Why it matters: Submitted business documents create the general-ledger effect; avoid building a parallel accounting engine.

S10 — WhatsApp Business Platform pricing (official)

https://business.whatsapp.com/products/platform-pricing

Why it matters: Current pricing is per delivered message by category/market. The page states that service messages inside the user-initiated 24-hour customer-service window are not charged, and utility messages in response to users are also not charged. Re-check pricing before production rollout.

S11 — Meta WhatsApp Cloud API developer docs

https://developers.facebook.com/docs/whatsapp/cloud-api/

Why it matters: Official production integration route. Use Meta Cloud API rather than unofficial WhatsApp Web automation.

S12 — Chatwoot self-hosted deployment

https://www.chatwoot.com/deploy

Why it matters: Chatwoot can be self-hosted and is useful as an optional shared inbox. Published production guidance currently lists roughly 4 CPU cores, 8 GB RAM minimum, PostgreSQL and Redis, which is why it is optional rather than mandatory V1.

S13 — Chatwoot self-hosted Community Edition pricing

https://www.chatwoot.com/pricing/self-hosted-plans

Why it matters: Community Edition is listed at $0/agent/month, while premium features are separate.

S14 — Chatwoot WhatsApp Cloud setup

https://www.chatwoot.com/hc/user-guide/articles/1756799850-how-to-setup-a-whats_app-channel-manual-flow

Why it matters: Documents connecting Chatwoot directly to Meta’s WhatsApp Cloud API without a third-party WhatsApp hosting provider.

S15 — Activepieces licensing

https://www.activepieces.com/docs/about/license https://github.com/activepieces/activepieces

Why it matters: Core/Community Edition is MIT, while enterprise directories/features use a commercial license. Treat as optional automation glue.

S16 — PaddleOCR

https://github.com/PaddlePaddle/PaddleOCR

Why it matters: Apache-2.0 OCR/document toolkit; useful for local/free-first image/PDF extraction.

S17 — Docling

https://github.com/docling-project/docling

Why it matters: MIT-licensed local document processing supporting PDF, DOCX, XLSX, PPTX, images and other formats, with structured document output.

S18 — faster-whisper

https://github.com/SYSTRAN/faster-whisper

Why it matters: MIT-licensed local speech-to-text implementation suitable for optional WhatsApp voice-note transcription.

S19 — OpenAI API quickstart / multimodal input

https://platform.openai.com/docs/quickstart/make-your-first-api-request

Why it matters: OpenAI API can analyze images/files and is a candidate frontier fallback for difficult extraction/reasoning.

S20 — OpenAI Responses structured outputs reference

https://platform.openai.com/docs/api-reference/responses-streaming/response/refusal

Why it matters: Responses API supports JSON-schema structured output; use schema-constrained extraction when available.

S21 — OpenAI model selection / current frontier models

https://platform.openai.com/docs/models/gpt-4-turbo-and-gpt-4

Why it matters: Current docs recommend GPT-5.6 Sol for complex reasoning/coding and lower-cost models for high-volume workloads. Re-check model IDs/pricing at implementation time.

S22 — OpenAI API pricing

https://openai.com/api/

Why it matters: External AI is pay-as-you-go; cost should be measured per Fresko task and used as an escalation path rather than sent every event by default.

S23 — Gemini API pricing (optional provider)

https://ai.google.dev/gemini-api/docs/pricing

Why it matters: Useful as a secondary provider/benchmark candidate; free and paid tiers vary by model and data-use terms. Do not architect Fresko around one provider.

S24 — Metabase licensing

https://www.metabase.com/license/

Why it matters: Open Source Edition is AGPL; evaluate licensing before embedding/distributing inside a commercial Fresko product.

37. Final instruction to future coding agents

When asked to “continue Fresko Universe,” do not begin by generating another generic SaaS architecture.

First determine the next unimplemented phase from Section 30, inspect the current repository and referenced evidence, then implement the smallest coherent vertical slice that respects:

WhatsApp is the inbox.The ledger is the truth.AI proposes.Rules + evidence + authorized people decide.No silent edits.Free-first, paid only when justified.
