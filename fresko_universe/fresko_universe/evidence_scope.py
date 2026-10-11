"""Durable tenant binding for new, unassigned operator Evidence.

Historical NULL ownership stays unknown. Provider ingress keeps its existing
contract; it cannot manufacture ownership from a worker's current permissions.
"""
from __future__ import annotations

import frappe


def _principal(user=None):
    from fresko_universe.intake_native import _principal as principal, _deny
    actor, company = principal()
    if user and user != actor:
        _deny()
    return actor, company


def bind_new(doc):
    from fresko_universe.intake_native import _deny
    # Binding is never a caller assertion, even when it matches their grant.
    if doc.get('evidence_company') or doc.get('company'):
        _deny()
    if doc.deal or doc.container or getattr(doc.flags, 'in_service', False):
        return
    if frappe.session.user == 'Administrator':
        # Administrative imports/test sentinels have no proven tenant. Do not
        # infer it from owner or default Company; intake will deny these rows.
        return
    actor, company = _principal()
    roles = {r[0] for r in frappe.db.sql(
        "SELECT role FROM `tabHas Role` WHERE parent=%s AND parenttype='User' FOR UPDATE", (actor,))}
    if not roles & {'Fresko Salesperson', 'Fresko Approver'}:
        _deny()
    for field in ('message_payload_sha256', 'scoped_message_key', 'provider',
                  'provider_account_id', 'conversation_id', 'provider_message_id',
                  'source_sender_id', 'source_sent_at', 'received_at', 'human_verified',
                  'linked_doctype', 'linked_name'):
        if doc.get(field):
            _deny()
    if (doc.get('manifest_status') not in (None, '', 'UNKNOWN')
            or doc.get('overall_verification_status') not in (None, '', 'PENDING')
            or doc.get('verified_attachment_count')):
        _deny()
    if doc.file:
        _new_file(doc, actor)
    doc.evidence_company = company
    if doc.notes and not doc.file and not doc.message_payload_sha256:
        from hashlib import sha256
        digest = sha256(doc.notes.encode('utf-8')).hexdigest()
        if doc.content_sha256 and doc.content_sha256 != digest:
            _deny()
        doc.content_sha256 = digest


def validate_existing(doc):
    from fresko_universe.intake_native import _deny, _get
    if doc.is_new():
        return
    binding = getattr(doc, 'evidence_company', None)
    stored = doc.get_db_value('evidence_company')
    if not isinstance(binding, str) and not isinstance(stored, str):
        return
    previous = doc.get_doc_before_save() or _get('Fresko Evidence', doc.name)
    # Includes NULL -> Company: historical ownership needs a separately
    # reviewed migration with source evidence, never current owner permissions.
    if doc.get('evidence_company') != previous.get('evidence_company'):
        _deny()
    if not previous.get('evidence_company'):
        return
    actor, company = _principal()
    if company != previous.evidence_company or bound_has_permission(previous, 'write', actor) is not True:
        _deny()
    for field in ('notes', 'file', 'content_sha256', 'message_id', 'external_ref',
                  'provider', 'provider_account_id', 'conversation_id',
                  'provider_message_id', 'source_sender_id', 'source_sent_at',
                  'received_at', 'message_payload_sha256', 'linked_doctype', 'linked_name'):
        if doc.get(field) != previous.get(field):
            _deny()
    changed = any(doc.get(f) != previous.get(f) for f in ('deal', 'container'))
    if changed:
        # Only the explicit, server-authorized link operation may establish
        # parents. Existing parents cannot be removed or replaced.
        if not getattr(doc.flags, 'link_unassigned_evidence', False):
            _deny()
        for field in ('deal', 'container'):
            if previous.get(field) and doc.get(field) != previous.get(field):
                _deny()
        for doctype, name in [('Fresko Deal', doc.deal), ('Fresko Container', doc.container)]:
            if name:
                parent = _get(doctype, name)
                if parent.company != company or not frappe.has_permission(
                        doctype, doc=parent, ptype='write', user=actor):
                    _deny()
        if doc.deal and doc.container and _get('Fresko Deal', doc.deal).container != doc.container:
            _deny()


def bound_has_permission(doc, ptype=None, user=None):
    """None delegates legacy rows to the existing permission implementation."""
    if isinstance(doc, str):
        doc = frappe.get_doc('Fresko Evidence', doc)
    binding = getattr(doc, 'evidence_company', None) if doc else None
    if not isinstance(binding, str) or not binding:
        return None
    try:
        actor, company = _principal(user)
        if doc.evidence_company != company:
            return False
        from fresko_universe.intake_native import _get
        for doctype, name in [('Fresko Deal', doc.deal), ('Fresko Container', doc.container)]:
            if name:
                parent = _get(doctype, name)
                if parent.company != company or not frappe.has_permission(
                        doctype, doc=parent, ptype='read', user=actor):
                    return False
        if ptype in (None, 'read', 'select', 'print', 'report', 'export'):
            return True
        roles = {r[0] for r in frappe.db.sql(
            "SELECT role FROM `tabHas Role` WHERE parent=%s AND parenttype='User' FOR UPDATE", (actor,))}
        return ptype == 'write' and 'Fresko Approver' in roles
    except frappe.PermissionError:
        frappe.clear_last_message()
        return False


def query_condition():
    """Additional bound-row denial; never a positive grant for legacy rows."""
    try:
        _, company = _principal()
        return "(IFNULL(evidence_company, '') = '' OR evidence_company = " + frappe.db.escape(company) + ')'
    except frappe.PermissionError:
        frappe.clear_last_message()
        return "IFNULL(evidence_company, '') = ''"


@frappe.whitelist()
def link_unassigned_evidence(evidence_name, container=None, deal=None, **untrusted):
    from fresko_universe.intake_native import _deny, _get, _resolved_evidence, _require_post
    _require_post()
    command = untrusted.pop('cmd', None)
    if (untrusted or command not in (None, 'fresko_universe.evidence_scope.link_unassigned_evidence')
            or not (container or deal)):
        _deny()
    actor, company = _principal()
    evidence = _resolved_evidence(evidence_name, user=actor, company=company)
    if not evidence.get('evidence_company') or bound_has_permission(evidence, 'write', actor) is not True:
        _deny()
    if deal:
        parent = _get('Fresko Deal', deal)
        container = container or parent.container
    for field, value in [('container', container), ('deal', deal)]:
        if value:
            if evidence.get(field) and evidence.get(field) != value:
                _deny()
            evidence.set(field, value)
    evidence.flags.link_unassigned_evidence = True
    evidence.save()
    return {'evidence': evidence.name, 'company': evidence.evidence_company,
            'container': evidence.container, 'deal': evidence.deal}


def _new_file(doc, actor):
    from fresko_universe.intake_native import _deny
    from fresko_universe.fresko_core.services.evidence_service import (
        assert_file_read_permission, get_validated_local_file_path)
    rows = frappe.get_all('File', filters={'file_url': doc.file},
        fields=['name', 'owner', 'is_private', 'attached_to_doctype', 'attached_to_name'])
    if not rows or any(not row.is_private or row.owner != actor or row.attached_to_name
                       or row.attached_to_doctype for row in rows):
        _deny()
    for row in rows:
        assert_file_read_permission(row.name, user=actor)
    from hashlib import sha256
    digest = sha256()
    try:
        with open(get_validated_local_file_path(doc.file), 'rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
    except OSError:
        _deny()
    actual = digest.hexdigest()
    if doc.content_sha256 and doc.content_sha256 != actual:
        _deny()
    doc.content_sha256 = actual
    return rows


def attach_new_file(doc):
    if not doc.get('evidence_company') or not doc.file:
        return
    actor, company = _principal()
    if company != doc.evidence_company:
        from fresko_universe.intake_native import _deny
        _deny()
    for row in _new_file(doc, actor):
        file = frappe.get_doc('File', row.name, for_update=True)
        if file.owner != actor or not file.is_private or file.attached_to_name or file.attached_to_doctype:
            from fresko_universe.intake_native import _deny
            _deny()
        file.flags.bind_unassigned_evidence = doc.name
        file.attached_to_doctype = doc.doctype
        file.attached_to_name = doc.name
        file.save()
