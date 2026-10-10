"""Static read-report proposals; never execute queries or financial arithmetic.

``authenticated_company`` must come from a future authorized server adapter.
This pure function does not authenticate its caller or verify record membership.
The existing Ask Fresko dispatcher and underlying services remain responsible for
session roles, Supplier denial, Company scope and record/evidence permissions.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True, slots=True)
class ReportContract:
    name: str
    tool: str | None
    required: tuple[str, ...]
    optional: tuple[str, ...] = ()
    authority: str = "authenticated Frappe service"
    supported: bool = True
    limitation: str | None = None


_REPORTS = {
    # The commercial reconciliation tool describes physical Outward allocation,
    # not Inward minus Outward stock or a complete physical movement ledger.
    "container_stock": ReportContract(
        "container_stock", None, ("container",), ("as_of",), supported=False,
        limitation="Operating inward/current stock is not exposed by the read-tool catalog.",
    ),
    "lot_stock": ReportContract(
        "lot_stock", None, ("container", "lot"), supported=False,
        limitation="Lot-level stock aggregation is not exposed by the read-tool catalog.",
    ),
    "inward_outward": ReportContract(
        "inward_outward", None, ("container",), ("as_of",), supported=False,
        limitation="A complete inward/outward movement ledger is not exposed by the read-tool catalog.",
    ),
    "outward_reconciliation": ReportContract(
        "outward_reconciliation", "outward_reconciliation", ("outward_name",), ("as_of",),
    ),
    "sale_history": ReportContract("sale_history", "sale_as_of", ("sale_name", "as_of")),
    "buyer_receivables": ReportContract(
        "buyer_receivables", "customer_receivable", ("customer", "company"), ("as_of",),
    ),
    "unallocated_collections": ReportContract(
        "unallocated_collections", "unallocated_collections", ("company",), ("as_of",),
    ),
    "bank_pending": ReportContract("bank_pending", "bank_pending_collections", ("company",), ("as_of",)),
    "money_exceptions": ReportContract("money_exceptions", "open_money_exceptions", ("company",)),
    "source_lineage": ReportContract(
        "source_lineage", None, ("evidence_ref",), supported=False,
        limitation="Cross-document source-lineage aggregation is not implemented.",
    ),
    "document_lineage": ReportContract(
        "document_lineage", None, ("evidence_ref",), supported=False,
        limitation="Document lineage export is not implemented.",
    ),
}
REPORTS = MappingProxyType(_REPORTS)


def plan_report(name: str, args: Mapping[str, str], authenticated_company: str | None):
    """Return a proposal only, never authorization or data.

    Company parameters use server-owned context. Explicit competing Company is
    denied. Record-based tools still require native record/company authorization.
    Explicit blank arguments require clarification; a blank historical cutoff
    must not silently produce a live-read proposal.
    """
    if type(name) is not str or name not in REPORTS:
        return {"status": "UNSUPPORTED", "tool": None}
    contract = REPORTS[name]
    if type(authenticated_company) is not str or not authenticated_company.strip():
        return {"status": "DENIED", "tool": None}
    if not isinstance(args, Mapping) or any(type(k) is not str or type(v) is not str for k, v in args.items()):
        return {"status": "NEEDS_CLARIFICATION", "tool": None}
    if set(args) - set(contract.required + contract.optional):
        return {"status": "NEEDS_CLARIFICATION", "tool": None}
    if "company" in args and args["company"] != authenticated_company:
        return {"status": "DENIED", "tool": None}
    if any(not value.strip() for value in args.values()):
        return {"status": "NEEDS_CLARIFICATION", "tool": None}
    if not contract.supported:
        return {"status": "NOT_IMPLEMENTED", "tool": None, "authority": contract.authority, "limitation": contract.limitation}
    clean = dict(args)
    if "company" in contract.required:
        clean["company"] = authenticated_company
    missing = [key for key in contract.required if key not in clean]
    if missing:
        return {"status": "NEEDS_CLARIFICATION", "tool": None, "missing": missing}
    return {"status": "PROPOSAL_ONLY", "tool": contract.tool, "arguments": clean, "authority": contract.authority}
