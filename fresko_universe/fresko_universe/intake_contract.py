"""Read-only intake values; deliberately no Frappe, HTTP, I/O or posting entrypoint.

Envelope.company is NOT proof of tenancy. Group 1B's authenticated adapter must
resolve Company and source identity, authorize/read back immutable Evidence, and
only then construct these values. Never deserialize HTTP payloads directly into
this contract or trust a caller's company_verified flag. Hashes classify replay;
only future database constraints/transactions can enforce durable uniqueness.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
import json
import re
from types import MappingProxyType


class IntakeError(ValueError):
    """Validation errors contain labels, never submitted values or identifiers."""


class Channel(str, Enum):
    WHATSAPP = "WHATSAPP"
    FILE = "FILE"
    MANUAL = "MANUAL"
    API = "API"


class ReviewState(str, Enum):
    NEEDS_SOURCE = "NEEDS_SOURCE"
    NEEDS_IDENTITY = "NEEDS_IDENTITY"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class FieldState(str, Enum):
    PROPOSED = "PROPOSED"
    UNKNOWN = "UNKNOWN"


class ReplayDisposition(str, Enum):
    DIFFERENT_SOURCE = "DIFFERENT_SOURCE"
    IDENTICAL = "IDENTICAL"
    CONFLICT = "CONFLICT"


_ALLOWED_FIELDS = frozenset({
    "container", "lot", "buyer_alias", "quantity", "uom", "rate", "currency",
    "movement_at", "gate_pass", "payment_reference", "amount", "bank_state",
    "document_type",
})
_NUMERIC_FIELDS = frozenset({"quantity", "rate", "amount"})
_DECIMAL = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", re.ASCII)
_SHA = re.compile(r"[a-f0-9]{64}", re.ASCII)
_LOCATORS = frozenset({
    "message", "worksheet_cell", "page_region", "manual_field", "api_field",
})


def _nonempty(value: object, label: str, maximum: int = 512) -> None:
    if type(value) is not str or not value.strip() or len(value) > maximum:
        raise IntakeError(f"{label}: nonempty bounded string required")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise IntakeError(f"{label}: invalid Unicode") from None
    if "\x00" in value:
        raise IntakeError(f"{label}: invalid control character")


def _strings(value: object, label: str, maximum: int) -> None:
    if type(value) is not tuple or len(value) > maximum:
        raise IntakeError(f"{label}: bounded tuple of strings required")
    for item in value:
        _nonempty(item, label, 128)


def _key(value: object) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"), allow_nan=False)
    return sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True, repr=False)
class Locator:
    """Opaque, exact locator; FILE reference must qualify sheet AND row/cell."""
    kind: str
    reference: str

    def __post_init__(self) -> None:
        if type(self.kind) is not str or self.kind not in _LOCATORS:
            raise IntakeError("Unsupported source locator")
        _nonempty(self.reference, "locator")

    def snapshot(self) -> dict:
        return {"kind": self.kind, "reference": self.reference}


@dataclass(frozen=True, slots=True, repr=False)
class Envelope:
    channel: Channel
    company: str
    source_account: str
    source_event_id: str
    evidence_ref: str
    evidence_sha256: str
    evidence_version: str
    locator: Locator
    source_provider: str | None = None
    source_conversation: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.channel, Channel):
            raise IntakeError("Invalid channel")
        for name in ("company", "source_account", "source_event_id",
                     "evidence_ref", "evidence_version"):
            _nonempty(getattr(self, name), name)
        for name in ("source_provider", "source_conversation"):
            value = getattr(self, name)
            if value is not None:
                _nonempty(value, name)
        if (type(self.evidence_sha256) is not str
                or not _SHA.fullmatch(self.evidence_sha256)):
            raise IntakeError("Invalid evidence SHA-256")
        if type(self.locator) is not Locator:
            raise IntakeError("Missing source locator")

    @property
    def delivery_key(self) -> str:
        # JSON framing prevents delimiter collisions. Preserve opaque IDs exactly.
        return _key(["fresko-intake-delivery-v1", self.company, self.channel.value,
                     self.source_provider, self.source_account,
                     self.source_conversation, self.source_event_id])

    @property
    def proposal_key(self) -> str:
        return _key(["fresko-intake-proposal-v1", self.delivery_key,
                     self.locator.kind, self.locator.reference])


@dataclass(frozen=True, slots=True, repr=False)
class Field:
    state: FieldState
    value: str | None
    locator: Locator
    parser_version: str | None = None
    uncertainty_flags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.state, FieldState) or type(self.locator) is not Locator:
            raise IntakeError("Invalid field state or locator")
        if self.state is FieldState.UNKNOWN:
            if self.value is not None:
                raise IntakeError("UNKNOWN must have null value")
        else:
            _nonempty(self.value, "proposed field", maximum=2048)
        if self.parser_version is not None:
            _nonempty(self.parser_version, "parser version", 128)
        _strings(self.uncertainty_flags, "uncertainty flags", 32)

    def snapshot(self) -> dict:
        return {"state": self.state.value, "value": self.value,
                "source_locator": self.locator.snapshot(),
                "parser_version": self.parser_version,
                "uncertainty_flags": list(self.uncertainty_flags)}


@dataclass(frozen=True, slots=True, repr=False)
class Proposal:
    envelope: Envelope
    fields: Mapping[str, Field]
    review_state: ReviewState
    warnings: tuple[str, ...] = ()
    can_post: bool = False

    def __post_init__(self) -> None:
        if type(self.envelope) is not Envelope:
            raise IntakeError("Missing envelope")
        if not isinstance(self.review_state, ReviewState):
            raise IntakeError("Invalid review state")
        if self.can_post is not False:
            raise IntakeError("Intake never authorizes posting")
        if not isinstance(self.fields, Mapping) or not self.fields:
            raise IntakeError("Missing fields")
        if len(self.fields) > len(_ALLOWED_FIELDS):
            raise IntakeError("Too many fields")
        _strings(self.warnings, "warnings", 50)
        copied = dict(self.fields)
        for name, field in copied.items():
            if type(name) is not str or name not in _ALLOWED_FIELDS or type(field) is not Field:
                raise IntakeError("Unsupported field")
            if name in _NUMERIC_FIELDS and field.state is FieldState.PROPOSED:
                # Lexical validation only: never float conversion, Decimal arithmetic,
                # quantization or implicit rounding. Exact submitted scale survives.
                if not _DECIMAL.fullmatch(field.value):
                    raise IntakeError("Exact unsigned decimal string required")
        object.__setattr__(self, "fields", MappingProxyType(copied))

    @property
    def proposal_key(self) -> str:
        return self.envelope.proposal_key

    def _content(self) -> dict:
        return {"delivery_key": self.envelope.delivery_key,
                "source_locator": self.envelope.locator.snapshot(),
                "evidence_ref": self.envelope.evidence_ref,
                "evidence_sha256": self.envelope.evidence_sha256,
                "evidence_version": self.envelope.evidence_version,
                "fields": {name: field.snapshot() for name, field in sorted(self.fields.items())}}

    @property
    def content_fingerprint(self) -> str:
        """Includes evidence/proposed content; excludes review progress and warnings."""
        return _key(["fresko-intake-content-v1", self._content()])

    @property
    def revision_key(self) -> str:
        return _key(["fresko-intake-revision-v1", self.proposal_key, self.content_fingerprint])

    def preview(self) -> dict:
        """Detached full review data, NOT a public response or a logging payload.

        Group 1B must authorize every Company/Evidence/source reference before
        exposing this data. Missing fields are absent, never inferred as zero.
        """
        return {**self._content(), "proposal_key": self.proposal_key,
                "content_fingerprint": self.content_fingerprint,
                "revision_key": self.revision_key, "channel": self.envelope.channel.value,
                "company": self.envelope.company,
                "source_provider": self.envelope.source_provider,
                "source_account": self.envelope.source_account,
                "source_conversation": self.envelope.source_conversation,
                "source_event_id": self.envelope.source_event_id,
                "review_state": self.review_state.value,
                "warnings": list(self.warnings), "can_post": False}

    def safe_summary(self) -> dict:
        """Counts/state only; deliberately omit identities, source data and hashes."""
        return {"channel": self.envelope.channel.value,
                "review_state": self.review_state.value,
                "proposed_fields": sum(f.state is FieldState.PROPOSED for f in self.fields.values()),
                "unknown_fields": sum(f.state is FieldState.UNKNOWN for f in self.fields.values()),
                "can_post": False}


def compare_replay(previous: Proposal, incoming: Proposal) -> ReplayDisposition:
    """Classification only: cannot reserve keys, suppress events or write revisions."""
    if type(previous) is not Proposal or type(incoming) is not Proposal:
        raise IntakeError("Replay comparison requires proposals")
    if previous.proposal_key != incoming.proposal_key:
        return ReplayDisposition.DIFFERENT_SOURCE
    if previous.content_fingerprint == incoming.content_fingerprint:
        return ReplayDisposition.IDENTICAL
    return ReplayDisposition.CONFLICT
