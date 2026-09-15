# Controls Review — Phase 1: Fresko Container + Fresko Deal

Reviewer: Fresko Controls  
Basis: `docs/FRESKO_UNIVERSE_CODEX_START_HERE.md` (09 Sep 2026)  
Scope: auditability, stock integrity, no silent mutation of approved financial records  
Status: **CONDITIONAL PASS** — Phase 1 may proceed only if the requirements below are implemented before Desk/API write paths go live.

---

## Verdict

Phase 1 design intent is sound (state machine, Approval DocType, revision trail, separate commercial vs physical notions). It is **not yet control-complete** until:

1. `Fresko Revision` (or equivalent) is a first-class DocType, not Version/changelog alone.
2. Post-approval field writes are blocked at server side (not UI-only).
3. `available_to_sell` is a computed invariant with reservation semantics decided by Anubhav (not inventable by parsers).
4. GST / SO timing / direct receipt / rate-floor ownership remain open and are not hard-coded.

**Reject any design that:** lets Desk edit `approved_rate` / `qty` after APPROVED|AUTO_APPROVED without a revision row; lets AI/parser set financial finality; conflates physical outward with commercial sale; or writes Deal status by free-form UI.

---

## 1. Required audit / revision strategy (Container + Deal)

### 1.1 Immutable sources

| Artifact | Rule |
|---|---|
| Original WhatsApp / file evidence | Never overwrite. Store `sha256`, `message_id`, `parser_version`, raw payload. |
| `Fresko Approval` row | Append-only. Decision, rates, approver, timestamp, reason are immutable after insert. |
| Submitted ERPNext accounting/stock docs (later phases) | Standard cancel+amend; never silent amend of submitted. |

### 1.2 `Fresko Revision` DocType (required in Phase 1)

Every material change to an approved/posted commercial field creates a **new** Revision child/parent row. Minimum fields:

- `parent_doctype`, `parent_name`
- `fieldname`
- `old_value`, `new_value`
- `changed_by`, `changed_at`
- `reason` (mandatory for material fields)
- `supporting_evidence` (Link/Dynamic Link to Fresko Evidence; mandatory when changing qty/rate after approval)
- `approval_reference` (Link to Fresko Approval when change requires re-approval)

**Material fields on Deal** (always revision + often re-approval): `qty`, `approved_rate`, `lot`/`batch`, `customer` (once confirmed), `currency`, `container`.

**Non-material / operational** (may update with reason only, still logged): unresolved alias notes, salesperson display notes, non-financial tags — still write Version; prefer Revision for consistency.

### 1.3 Write path rules

- No direct Desk overwrite of material fields once Deal is in `APPROVED`, `AUTO_APPROVED`, or later.
- Allowed mutation path: `request_revision` → (if rate/qty/lot) Approval workflow → apply via server method that writes Revision then updates Deal.
- Parsers/AI write only to Evidence + proposed extraction; they never call `db.set_value` on Deal financial fields.
- Idempotency: WhatsApp `message_id` / content hash must not create a second Deal or Approval.

### 1.4 Container

- `inward_qty`, `unit`, `landed_cost`, `currency`, `supplier_partner` become revision-controlled once status leaves draft / OPENING (exact gate: recommend after first inward confirmation).
- Closing / settlement quantities are **snapshot fields on Settlement**, not free edits on Container. Container close requires zero unresolved material Exceptions.

---

## 2. Field immutability by Deal state

| Field | PROPOSED / APPROVAL_REQUIRED | APPROVED / AUTO_APPROVED | OUTWARD_PENDING+ | DISPATCHED+ | CANCELLED |
|---|---|---|---|---|---|
| `proposed_rate` | Mutable (still log Version) | **Frozen** (historical proposal) | Frozen | Frozen | Frozen |
| `approved_rate` | N/A / set only by Approval | **Immutable** except via Revision+Approval | Same | Same | Frozen |
| `qty` | Mutable under stock check | **Immutable** except via Revision+Approval | Same; partial dispatch needs split/revision model | Same | Frozen |
| `lot` / batch / count_size | Mutable under stock check | **Immutable** except Revision+Approval | Same | Frozen | Frozen |
| `container` | Mutable | **Immutable** | Immutable | Immutable | Frozen |
| `customer` / confirmed party | Alias may resolve | Confirm once; change = Revision + evidence | Same | Same | Frozen |
| `status` | Only via validated transitions | Only via state machine | Same | Same | Terminal |
| `source_message_id`, `duplicate_fingerprint` | Set once | Immutable | Immutable | Immutable | Immutable |
| `approval_id` | Set on decision | Immutable | Immutable | Immutable | Immutable |

**Status transitions:** server-validated only. Desk must not offer a free Status dropdown that can jump to APPROVED / PAID / RECONCILED.

**COUNTERED:** writes a new Approval row with `decision_rate`; Deal retains `proposed_rate`; `approved_rate` updates only through that Approval — never by overwriting `proposed_rate`.

---

## 3. Stock integrity — `available_to_sell`

### 3.1 Keep ledgers separate (non-negotiable)

| Ledger | What counts |
|---|---|
| Physical | `physical_inward`, `physical_outward`, warehouse/gatepass movements |
| Commercial | approved deals, cancellations, approved qty revisions |
| Collection | out of Phase 1 write path; do not invent paid from screenshots |

**Never** treat an approved Deal as physical outward.

### 3.2 Working definitions (Phase 1 — commercial reservation)

Until Anubhav confirms reservation semantics (open question §35), implement **conservative reservation** and label it as provisional in OPEN_QUESTIONS:

```
available_to_sell =
  physical_inward
  - SUM(qty of Deals in APPROVED | AUTO_APPROVED | OUTWARD_PENDING | PARTIALLY_DISPATCHED
        | DISPATCHED | PAYMENT_PENDING | PAID | RECONCILED
        /* exclude CANCELLED; for PARTIALLY_* use remaining undisp. commercial qty */)
```

Clarifications required in code comments + OPEN_QUESTIONS:

- Whether `PROPOSED` / `APPROVAL_REQUIRED` soft-reserves stock (recommend: **soft hold with expiry**, not hard reserve, until approved — Anubhav decides).
- Lot-level: same formula scoped to lot inward; lot overdraw → Exception `LOT_OVERDRAWN` / `QTY_EXCEEDS_AVAILABLE_STOCK`.
- Cancel restores availability only via status transition to CANCELLED (logged), not silent qty zeroing.

### 3.3 Hard rules (enforce in validate)

1. Cannot AUTO_APPROVE / APPROVE if `qty > available_to_sell` (lot + container).
2. Cannot increase approved qty without Revision + re-check availability + Approval if rate band also affected.
3. Exception types mandatory in Phase 1 scaffolding: `QTY_EXCEEDS_AVAILABLE_STOCK`, `RATE_BELOW_FLOOR`, `RATE_CHANGED_AFTER_APPROVAL`, `DUPLICATE_MESSAGE`, `MANUAL_OVERRIDE`.
4. Container close (later) must explain every unit: inward vs approved sold vs outward vs pending vs cancelled vs unsold — no plug figures.

### 3.4 Physical vs commercial

Phase 1 may stub outward links, but **must not** decrement physical stock from Deal approval. Physical movements wait for Phase 3 outward records. UI copy must not say “sold out of warehouse” for commercial approval alone.

---

## 4. Controls risks + decisions refused to hard-code

### 4.1 Block / flag for Anubhav + CA (do not encode as product law)

| Topic | Why Controls refuses to hard-code |
|---|---|
| **GST / tax / invoice timing** | Entity structure and tax treatment need CA; prototyping must not invent statutory truth. |
| **Sales Order timing** | Whether every approved Deal creates SO immediately vs after dispatch — commercial/legal; leave as config after Anubhav decision. |
| **Direct receipt** | Who owns cash, how it affects agent settlement — needs explicit auditable field later; no informal spreadsheet semantics in code. |
| **Rate-floor ownership** | Container vs lot vs count vs buyer-specific floors — Anubhav owns policy; system stores policy version on Approval (`policy_floor`, `rule_version`). |
| **Credit / exposure limits** | Business policy; stub structure only. |
| **Exact close formulas** (§27) | Confirm commercial meaning of adjustments before encoding settlement arithmetic. |
| **Legal entity / partner accounting model** | CA + Anubhav. |

### 4.2 Design risks to reject in Frappe implementation reviews

1. **Desk edit bypass** — `ignore_permissions`, client-only read-only, or allowing System Manager habits to become the ops path.
2. **Approval as a checkbox** — must be a separate immutable Approval DocType.
3. **AI confidence → auto financial post** — confidence routes review only.
4. **Conflating outward with sale** — stock snapshot must show both series.
5. **Silent rate fix** — changing rate after APPROVED without Revision + Approval → Exception `RATE_CHANGED_AFTER_APPROVAL` and block submit.
6. **Duplicate deals from webhook retries** — missing idempotency keys.
7. **Buyer alias auto-rename destroying source alias** — forbidden.

### 4.3 Phase 1 acceptance (controls lens)

Pass only if demo shows: below-floor deal → Approval stored → attempt to edit `approved_rate`/`qty` in Desk fails → revision path creates old/new/actor/time/reason/evidence/approval_ref → stock check blocks oversell.

---

## Sign-off

| Item | Decision |
|---|---|
| Phase 1 Container + Deal controls posture | **Conditional pass** |
| Blocking before build | Revision DocType + server-side immutability + ATS formula + state machine |
| Escalations | GST, SO timing, direct receipt, rate-floor ownership → Anubhav/CA |

Next review: Fresko Frappe DocType/permission PR for Container, Deal, Approval, Revision, Evidence, Exception.
