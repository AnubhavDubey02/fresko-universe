"""Authenticated, non-posting intake drafts and append-only review events.

HTTP accepts proposed values, never an Envelope, company, roles or verified flag.
Identity/Evidence resolution is repeated on capture, read and review. No service
commits: Frappe owns the transaction, including retry after a lost HTTP response.
"""
from __future__ import annotations

import json
from hashlib import sha256

import frappe
from fresko_universe.intake_contract import (
    Channel, Envelope, Field, FieldState, IntakeError, Locator, Proposal, ReviewState,
)

DRAFT = 'Fresko Intake Draft'
REVISION = 'Fresko Intake Revision'
ALLOWED = frozenset({'Fresko Accounts', 'Fresko Approver', 'Fresko Salesperson'})


def _deny():
    frappe.throw('Intake access unavailable', frappe.PermissionError)


def _principal():
    user = getattr(frappe.session, 'user', None)
    if not user or user == 'Guest':
        _deny()
    enabled = frappe.db.sql('SELECT enabled FROM `tabUser` WHERE name=%s FOR UPDATE', (user,))
    if not enabled or not enabled[0][0]:
        _deny()
    # Fresh role rows prevent cached session roles authorizing a revoked grant.
    roles = {r[0] for r in frappe.db.sql(
        "SELECT role FROM `tabHas Role` WHERE parent=%s AND parenttype='User' FOR UPDATE", (user,))}
    if any('supplier' in role.casefold() for role in roles) or not roles & ALLOWED:
        _deny()
    grants = frappe.db.sql(
        "SELECT for_value, applicable_for FROM `tabUser Permission` WHERE user=%s AND allow='Company' FOR UPDATE",
        (user,), as_dict=True)
    companies = {g.for_value for g in grants}
    if len(companies) != 1 or not grants or any(g.applicable_for for g in grants):
        _deny()
    company = next(iter(companies))
    if not company or not frappe.has_permission('Company', doc=company, ptype='read', user=user):
        _deny()
    return user, company


def _get(doctype, name, *, for_update=True):
    if type(name) is not str or not name or len(name) > 140:
        _deny()
    try:
        return frappe.get_doc(doctype, name, for_update=for_update)
    except frappe.DoesNotExistError:
        frappe.clear_last_message()
        raise frappe.PermissionError('Intake access unavailable') from None


def _evidence_company(evidence, user, company):
    if not frappe.has_permission('Fresko Evidence', doc=evidence, ptype='read', user=user):
        _deny()
    parents = []
    for doctype, name in [('Fresko Deal', evidence.deal), ('Fresko Container', evidence.container)]:
        if name:
            parent = _get(doctype, name)
            if parent.company != company or not frappe.has_permission(doctype, doc=parent, ptype='read', user=user):
                _deny()
            parents.append(parent)
    if not parents:
        _deny()
    if evidence.deal and evidence.container and parents[0].container != evidence.container:
        _deny()


def _resolved_evidence(name, *, user, company):
    evidence = _get('Fresko Evidence', name)
    _evidence_company(evidence, user, company)
    # Reuse canonical File authorization and path containment. A stored SHA alone
    # is not byte proof for a file: hash the authorized current local bytes.
    from fresko_universe.fresko_core.services.evidence_service import (
        assert_file_read_permission, get_validated_local_file_path,
    )
    sources = []
    if evidence.file:
        sources.append((evidence.file, evidence.content_sha256))
    attachments = frappe.get_all('Fresko Evidence Attachment', filters={
        'evidence': evidence.name, 'is_current_version': 1}, fields=[
        'name', 'file_url', 'content_sha256', 'capture_status', 'readback_verified'])
    for att in attachments:
        if (att.capture_status != 'CAPTURED' or not att.readback_verified
                or not frappe.has_permission('Fresko Evidence Attachment', doc=att.name, ptype='read', user=user)):
            _deny()
        sources.append((att.file_url, att.content_sha256))
    for url, digest in sources:
        # Frappe attach_file may create several File rows for one authorized
        # attachment URL. Select the source binding, never an unrelated owner.
        files = frappe.get_all('File', filters={'file_url': url,
            'attached_to_doctype': ['in', ['Fresko Evidence', 'Fresko Evidence Attachment']],
            'attached_to_name': ['in', [evidence.name] + [a.name for a in attachments]]},
            fields=['name', 'is_private', 'attached_to_doctype', 'attached_to_name'])
        if not files or any(not f.is_private for f in files):
            _deny()
        try:
            for file in files:
                assert_file_read_permission(file.name, user=user)
            path = get_validated_local_file_path(url)
            actual = sha256()
            with open(path, 'rb') as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    actual.update(block)
            if not digest or actual.hexdigest() != digest:
                _deny()
        except (frappe.PermissionError, frappe.DoesNotExistError, OSError):
            frappe.clear_last_message()
            _deny()
    if not evidence.content_sha256:
        _deny()
    if not sources and not evidence.message_payload_sha256:
        # Manual notes have actual stored source text; no arbitrary caller hash.
        if not evidence.notes or sha256(evidence.notes.encode('utf-8')).hexdigest() != evidence.content_sha256:
            _deny()
    return evidence


def _assert_envelope(proposal, evidence, tenant):
    if type(proposal) is not Proposal or proposal.envelope.company != tenant:
        _deny()
    env = proposal.envelope
    if (env.evidence_ref != evidence.name or env.evidence_sha256 != evidence.content_sha256
            or env.evidence_version != (evidence.message_payload_sha256 or evidence.content_sha256)):
        _deny()
    scope = (evidence.provider, evidence.provider_account_id,
             evidence.conversation_id, evidence.provider_message_id)
    if env.channel in (Channel.WHATSAPP, Channel.API) and not all(scope):
        _deny()
    for expected, actual in zip((env.source_provider, env.source_account,
                                env.source_conversation, env.source_event_id), scope):
        if actual and expected != actual:
            _deny()


def _authorized_draft(name):
    actor, company = _principal()
    doc = _get(DRAFT, name)
    if doc.company != company:
        _deny()
    _resolved_evidence(doc.evidence, user=actor, company=company)
    for evidence in set(frappe.get_all(REVISION, filters={'draft': doc.name}, pluck='evidence')):
        _resolved_evidence(evidence, user=actor, company=company)
    return doc, actor, company


def _readable_names(user=None):
    if not frappe.db.table_exists(DRAFT):
        return []
    try:
        actor, company = _principal()
        if user and user != actor:
            return []
        allowed = []
        for row in frappe.get_all(DRAFT, filters={'company': company}, fields=['name', 'evidence']):
            try:
                _authorized_draft(row.name)
                allowed.append(row.name)
            except frappe.PermissionError:
                frappe.clear_last_message()
        return allowed
    except frappe.PermissionError:
        frappe.clear_last_message()
        return []


def _in_names(column, names):
    return column + ' IN (' + ','.join(frappe.db.escape(n) for n in names) + ')' if names else '1=0'


def draft_permission_query(user=None):
    return _in_names('`tabFresko Intake Draft`.name', _readable_names(user))


def revision_permission_query(user=None):
    return _in_names('`tabFresko Intake Revision`.draft', _readable_names(user))


def draft_has_permission(doc, ptype=None, user=None):
    if ptype not in (None, 'read', 'select'):
        return False
    try:
        actor, company = _principal()
        if (user and user != actor) or getattr(doc, 'company', None) != company:
            return False
        _authorized_draft(doc.name)
        return True
    except frappe.PermissionError:
        frappe.clear_last_message()
        return False


def revision_has_permission(doc, ptype=None, user=None):
    if ptype not in (None, 'read', 'select') or not getattr(doc, 'draft', None):
        return False
    return draft_has_permission(_get(DRAFT, doc.draft), ptype, user)


def _source_urls():
    """Batch durable source bindings; never cache across transaction mutations."""
    if not frappe.db.table_exists(DRAFT) or not frappe.db.table_exists(REVISION):
        return {}
    evidence = set(frappe.get_all(DRAFT, pluck='evidence'))
    evidence.update(frappe.get_all(REVISION, pluck='evidence'))
    evidence.discard(None)
    if not evidence:
        return {}
    result = {}
    def add(url, source):
        if url and source:
            result.setdefault(url, set()).add(source)
    for row in frappe.get_all('Fresko Evidence', filters={'name': ['in', list(evidence)]}, fields=['name', 'file']):
        add(row.file, row.name)
    attachments = frappe.get_all('Fresko Evidence Attachment', filters={'evidence': ['in', list(evidence)]},
        fields=['name', 'evidence', 'file_url'])
    by_attachment = {row.name: row.evidence for row in attachments}
    for row in attachments:
        add(row.file_url, row.evidence)
    for row in frappe.get_all('File', filters={'attached_to_doctype': ['in',
            ['Fresko Evidence', 'Fresko Evidence Attachment']]},
            fields=['file_url', 'attached_to_doctype', 'attached_to_name']):
        source = row.attached_to_name if row.attached_to_doctype == 'Fresko Evidence' else by_attachment.get(row.attached_to_name)
        if source in evidence:
            add(row.file_url, source)
    return result


def _source_evidence_for_url(url):
    return _source_urls().get(url, set())


def file_has_permission(doc, ptype=None, user=None):
    """Additional denial for intake bytes; framework still owns positive grants.

    Alias rows and DocShare/owner cannot bypass the actual source provenance.
    Cross-company reuse of the same protected URL requires a future explicit
    sharing contract; it is conservatively denied when any source is unreadable.
    """
    sources = _source_evidence_for_url(doc.file_url)
    if not sources:
        return None
    try:
        actor, company = _principal()
        if user and actor != user:
            return False
        for evidence in sources:
            _evidence_company(_get('Fresko Evidence', evidence), actor, company)
        return None
    except frappe.PermissionError:
        frappe.clear_last_message()
        return False


def _hidden_files(user=None):
    sources = _source_urls()
    if not sources:
        return []
    permitted = {}
    try:
        actor, company = _principal()
        if user and user != actor:
            _deny()
        for source in set().union(*sources.values()):
            try:
                _evidence_company(_get('Fresko Evidence', source), actor, company)
                permitted[source] = True
            except frappe.PermissionError:
                frappe.clear_last_message()
                permitted[source] = False
    except frappe.PermissionError:
        frappe.clear_last_message()
    hidden_urls = {url for url, refs in sources.items() if any(not permitted.get(ref) for ref in refs)}
    return frappe.get_all('File', filters={'file_url': ['in', list(hidden_urls)]}, pluck='name') if hidden_urls else []


def file_permission_query(user=None):
    return 'NOT (' + _in_names('`tabFile`.name', _hidden_files(user)) + ')' if frappe.db.table_exists(DRAFT) else ''


def _file_filters(filters=None):
    # Explicit user filters remain outside Frappe's DocShare OR fallback.
    return list(filters or []) + [['name', 'not in', _hidden_files()]]


@frappe.whitelist()
def get_files_in_folder(folder, start=0, page_length=20):
    """Pinned File folder contract, with intake tenant filters before pagination."""
    start, page_length = int(start), int(page_length)
    if start < 0 or not 1 <= page_length <= 100:
        frappe.throw('Invalid file page', frappe.ValidationError)
    files = frappe.get_list('File', filters=_file_filters([['folder', '=', folder]]),
        fields=['name', 'file_name', 'file_url', 'is_folder', 'modified'],
        start=start, page_length=page_length + 1)
    attachment_folder = frappe.db.get_value('File', 'Home/Attachments',
        ['name', 'file_name', 'file_url', 'is_folder', 'modified'], as_dict=True)
    if folder == 'Home' and attachment_folder and attachment_folder not in files:
        files.insert(0, attachment_folder)
    return {'files': files[:page_length], 'has_more': len(files) > page_length}


@frappe.whitelist()
def get_files_by_search_text(text):
    if not text:
        return []
    pattern = '%' + str(text).lower() + '%'
    return frappe.get_list('File', fields=['name', 'file_name', 'file_url', 'is_folder', 'modified'],
        filters=_file_filters([['is_folder', '=', 0]]),
        or_filters={'file_name': ['like', pattern], 'file_url': pattern, 'name': ['like', pattern]},
        order_by='modified desc', limit=20)


@frappe.whitelist()
def get_attached_images(doctype, names):
    names = json.loads(names) if isinstance(names, str) else names
    if type(names) is not list or not all(type(name) is str for name in names):
        frappe.throw('Invalid attachment query', frappe.ValidationError)
    rows = frappe.get_list('File', filters=_file_filters([
        ['attached_to_doctype', '=', doctype], ['attached_to_name', 'in', names], ['is_folder', '=', 0]]),
        fields=['file_url', 'attached_to_name as docname'])
    result = {}
    for row in rows:
        result.setdefault(row.docname, []).append(row.file_url)
    return result


def protect_intake_source(doc, method=None):
    """Keep durable intake provenance reachable; corrections use new evidence."""
    if not frappe.db.table_exists(DRAFT) or doc.is_new():
        return
    previous = frappe.get_doc(doc.doctype, doc.name)
    if doc.doctype == 'File':
        protected = bool(_source_evidence_for_url(previous.file_url))
        fields = ('file_url', 'is_private', 'attached_to_doctype', 'attached_to_name',
                  'file_name', 'content_hash', 'file_size')
    else:
        evidence = previous.name if doc.doctype == 'Fresko Evidence' else previous.evidence
        protected = (frappe.db.exists(DRAFT, {'evidence': evidence})
            or frappe.db.exists(REVISION, {'evidence': evidence}))
        fields = ('notes', 'file', 'content_sha256', 'message_payload_sha256', 'container', 'deal',
            'provider', 'provider_account_id', 'conversation_id', 'provider_message_id') if doc.doctype == 'Fresko Evidence' else (
            'evidence', 'file_url', 'content_sha256', 'capture_status', 'readback_verified')
    if protected and (method == 'on_trash' or any(doc.get(f) != previous.get(f) for f in fields)):
        _deny()


def _transaction_lock(key):
    """MariaDB advisory lock retained until the owning transaction completes.

    This serializes first insert without missing-row gap locks. Connection close
    releases locks on crash. Review still uses the actual draft row lock.
    """
    held = getattr(frappe.local, 'intake_transaction_locks', None)
    if held is None:
        held = frappe.local.intake_transaction_locks = set()
    name = sha256(('fresko-intake-lock-v1:' + key).encode()).hexdigest()
    if name in held:
        return
    if frappe.db.sql('SELECT GET_LOCK(%s, 30)', (name,))[0][0] != 1:
        frappe.throw('INTAKE_RETRY_REQUIRED', frappe.ValidationError)
    held.add(name)
    def release():
        if name in held:
            frappe.db.sql('SELECT RELEASE_LOCK(%s)', (name,))
            held.remove(name)
    frappe.db.after_commit.add(release)
    frappe.db.after_rollback.add(release)


def _lock_draft(key):
    rows = frappe.db.sql('SELECT name, content_fingerprint, review_state, version, current_revision '
                         'FROM `tabFresko Intake Draft` WHERE name=%s FOR UPDATE', (key,), as_dict=True)
    return rows[0] if rows else None


def _append_revision(draft, *, revision_key, evidence, evidence_version, fingerprint,
                     state, payload, actor, action, reason=None):
    sequence = int(draft.version) + 1 if draft.current_revision else 1
    revision = frappe.get_doc({'doctype': REVISION, 'revision_key': revision_key,
        'draft': draft.name, 'evidence': evidence, 'evidence_version': evidence_version,
        'content_fingerprint': fingerprint, 'review_state': state,
        'payload_json': json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False),
        'capture_actor': actor, 'can_post': 0, 'sequence': sequence,
        'sequence_key': f'{draft.name}:{sequence}', 'previous_revision': draft.current_revision,
        'action': action, 'reason': reason})
    revision.flags.intake_service = True
    # References originate from authorized Evidence and a locked current draft.
    # Frappe's consistent-read Link check can see an older transaction snapshot
    # after waiting behind another committed revision; validate the prior link
    # with a current locking read instead, without skipping actor authorization.
    if draft.current_revision:
        assert frappe.db.sql('SELECT name FROM `tabFresko Intake Revision` WHERE name=%s FOR UPDATE',
                             (draft.current_revision,)), 'Missing intake predecessor'
    revision.flags.ignore_links = True
    revision.insert(ignore_permissions=True)
    frappe.db.set_value('Fresko Intake Draft', draft.name, {
        'current_revision': revision.name, 'version': sequence, 'review_state': state})
    return revision


def _capture_locked(proposal, evidence, actor, company):
    key, fingerprint = proposal.proposal_key, proposal.content_fingerprint
    row = _lock_draft(key)
    if row:
        _authorized_draft(key)
        if row.content_fingerprint == fingerprint:
            return {'state': 'CONFLICT' if row.review_state == 'CONFLICT' else 'IDENTICAL',
                    'draft_key': key, 'version': row.version, 'created': False, 'can_post': False}
        if not frappe.db.exists(REVISION, proposal.revision_key):
            _append_revision(row, revision_key=proposal.revision_key, evidence=evidence.name,
                evidence_version=proposal.envelope.evidence_version, fingerprint=fingerprint,
                state='CONFLICT', payload=proposal.preview(), actor=actor, action='CONFLICT')
        return {'state': 'CONFLICT', 'draft_key': key, 'version': frappe.db.get_value(DRAFT, key, 'version'),
                'created': False, 'can_post': False}
    duplicate = bool(frappe.db.exists(DRAFT, {'company': company, 'source_sha256': evidence.content_sha256}))
    draft = frappe.get_doc({'doctype': DRAFT, 'proposal_key': key, 'company': company,
        'evidence': evidence.name, 'source_sha256': evidence.content_sha256,
        'source_version': proposal.envelope.evidence_version, 'content_fingerprint': fingerprint,
        'review_state': proposal.review_state.value, 'possible_duplicate': int(duplicate),
        'capture_actor': actor, 'version': 1})
    draft.flags.intake_service = True
    draft.insert(ignore_permissions=True)
    _append_revision(draft, revision_key=proposal.revision_key, evidence=evidence.name,
        evidence_version=proposal.envelope.evidence_version, fingerprint=fingerprint,
        state=proposal.review_state.value, payload=proposal.preview(), actor=actor, action='CAPTURE')
    return {'state': 'POSSIBLE_DUPLICATE' if duplicate else 'CREATED', 'draft_key': key,
            'version': 1, 'created': True, 'can_post': False}


def capture_verified_proposal(proposal):
    """Internal API; savepoint contains partial failures, caller owns commit."""
    if type(proposal) is not Proposal:
        _deny()
    actor, company = _principal()
    _transaction_lock(proposal.proposal_key)
    evidence = _resolved_evidence(proposal.envelope.evidence_ref, user=actor, company=company)
    _assert_envelope(proposal, evidence, company)
    frappe.db.savepoint('intake_native_capture')
    try:
        return _capture_locked(proposal, evidence, actor, company)
    except frappe.DuplicateEntryError:
        frappe.db.rollback(save_point='intake_native_capture')
        try:
            return _capture_locked(proposal, evidence, actor, company)
        except Exception:
            frappe.db.rollback(save_point='intake_native_capture')
            raise
    except frappe.QueryDeadlockError:
        # MariaDB already rolled back the entire transaction/savepoints.
        raise
    except Exception:
        frappe.db.rollback(save_point='intake_native_capture')
        raise


def _require_post():
    if getattr(frappe.local, 'request', None) and frappe.request.method != 'POST':
        _deny()


@frappe.whitelist()
def capture(evidence_name, channel, locator, fields, **untrusted):
    """Proposed field JSON only; all authority/source-envelope fields are server-owned."""
    _require_post()
    # Frappe v15 injects the RPC command into form_dict and forwards it to **kwargs.
    # Accept only that exact transport marker; tenant/role/envelope extras fail closed.
    command = untrusted.pop('cmd', None)
    if untrusted or command not in (None, 'fresko_universe.intake_native.capture'):
        _deny()
    actor, company = _principal()
    # Preliminary source metadata determines the serialization key. It grants
    # nothing: capture_verified_proposal re-reads/authorizes all source bytes
    # under the transaction lock before any persistence. No source row locks
    # are acquired here ahead of that key lock.
    evidence = _get('Fresko Evidence', evidence_name, for_update=False)
    try:
        channel = Channel(channel)
        location = json.loads(locator) if isinstance(locator, str) else locator
        values = json.loads(fields) if isinstance(fields, str) else fields
        if type(location) is not dict or set(location) != {'kind', 'reference'} or type(values) is not dict:
            raise IntakeError('Invalid shape')
        origin = Locator(**location)
        kind = {Channel.MANUAL: 'manual_field', Channel.FILE: 'worksheet_cell',
                Channel.WHATSAPP: 'message', Channel.API: 'api_field'}[channel]
        if origin.kind != kind or (channel is Channel.FILE and ('!' not in origin.reference or not evidence.file)):
            raise IntakeError('Invalid channel location')
        parsed = {}
        for name, value in values.items():
            if type(value) is not dict or set(value) - {'state', 'value', 'locator', 'parser_version', 'uncertainty_flags'}:
                raise IntakeError('Invalid field shape')
            field_origin = Locator(**value['locator'])
            if field_origin.kind != kind or type(value.get('uncertainty_flags', [])) not in (list, tuple):
                raise IntakeError('Invalid field provenance')
            parsed[name] = Field(FieldState(value['state']), value.get('value'), field_origin,
                value.get('parser_version'), tuple(value.get('uncertainty_flags', ())))
        provider = evidence.provider or None
        account = evidence.provider_account_id or evidence.name
        conversation = evidence.conversation_id or None
        event = evidence.provider_message_id or evidence.name
        env = Envelope(channel, company, account, event, evidence.name,
            evidence.content_sha256, evidence.message_payload_sha256 or evidence.content_sha256,
            origin, provider, conversation)
        proposal = Proposal(env, parsed, ReviewState.NEEDS_REVIEW)
    except (IntakeError, ValueError, TypeError, KeyError):
        frappe.throw('Invalid intake proposal', frappe.ValidationError)
    return capture_verified_proposal(proposal)


@frappe.whitelist()
def authorized_preview(draft_key):
    draft, _, _ = _authorized_draft(draft_key)
    revisions = frappe.get_all(REVISION, filters={'draft': draft.name},
        fields=['name', 'sequence', 'action', 'review_state', 'capture_actor', 'reason', 'previous_revision'],
        order_by='sequence asc')
    if not revisions or len(revisions) != int(draft.version):
        _deny()
    first = _get(REVISION, revisions[0].name)
    return {'status': draft.review_state, 'version': draft.version,
            'preview': json.loads(first.payload_json), 'history': revisions, 'can_post': False}


@frappe.whitelist()
def review(draft_key, expected_version, action, reason):
    """Review acknowledgement/evidence request/rejection; never approve or post truth."""
    _require_post()
    _principal()
    if type(draft_key) is not str or len(draft_key) != 64:
        _deny()
    _transaction_lock(draft_key)
    draft, actor, company = _authorized_draft(draft_key)
    roles = {r[0] for r in frappe.db.sql(
        "SELECT role FROM `tabHas Role` WHERE parent=%s AND parenttype='User' FOR UPDATE", (actor,))}
    if not roles & {'Fresko Accounts', 'Fresko Approver'} or actor == draft.capture_actor:
        _deny()
    if action not in ('ACKNOWLEDGE', 'REQUEST_EVIDENCE', 'REJECT') or type(reason) is not str or not reason.strip() or len(reason) > 1024:
        frappe.throw('Invalid intake review', frappe.ValidationError)
    row = _lock_draft(draft.name)
    if (expected_version is None or str(expected_version) != str(row.version)):
        frappe.throw('STALE_VERSION', frappe.ValidationError)
    # Recheck ACL after obtaining the record lock; no cached role/user authority.
    _authorized_draft(draft.name)
    roles = {r[0] for r in frappe.db.sql(
        "SELECT role FROM `tabHas Role` WHERE parent=%s AND parenttype='User' FOR UPDATE", (actor,))}
    if not roles & {'Fresko Accounts', 'Fresko Approver'} or actor == draft.capture_actor:
        _deny()
    state = row.review_state
    if state != 'CONFLICT':
        state = {'ACKNOWLEDGE': 'REVIEWED', 'REQUEST_EVIDENCE': 'NEEDS_SOURCE', 'REJECT': 'REJECTED'}[action]
    revision_key = sha256(json.dumps(['intake-review-v1', draft.name, row.version, actor, action, reason],
                                    separators=(',', ':')).encode()).hexdigest()
    _append_revision(row, revision_key=revision_key, evidence=draft.evidence,
        evidence_version=draft.source_version, fingerprint=draft.content_fingerprint,
        state=state, payload={'action': action, 'reason': reason, 'can_post': False}, actor=actor, action=action, reason=reason)
    return {'state': state, 'version': int(row.version) + 1, 'can_post': False}


def guard_http_access():
    """Uniform denial before standard get/resource fetch can reveal existence."""
    request = frappe.request
    form = frappe.local.form_dict
    doctype = form.get('dt') or form.get('doctype')
    name = form.get('dn') if form.get('dt') else form.get('name') or form.get('docname')
    serialized = form.get('document') or form.get('docs')
    if serialized and not form.get('dt'):
        try:
            document = json.loads(serialized) if isinstance(serialized, str) else serialized
            if type(document) is dict:
                doctype, name = document.get('doctype'), document.get('name')
        except (ValueError, TypeError):
            _deny()
    if request.path.startswith(('/api/resource/', '/api/v1/resource/', '/api/v2/document/', '/api/v2/doctype/')):
        from urllib.parse import unquote
        parts = unquote(request.path).split('/')
        offset = 4 if parts[2] in ('v1', 'v2') else 3
        if len(parts) > offset:
            doctype = parts[offset]
            name = parts[offset + 1] if len(parts) > offset + 1 else None
            if parts[2] == 'v2' and parts[3] == 'doctype':
                name = None
    if doctype in (DRAFT, REVISION) and not name:
        _principal()
        # User filters remain outside Frappe's DocShare OR fallback.
        filters = form.get('filters') or []
        filters = json.loads(filters) if isinstance(filters, str) else filters
        if type(filters) is dict:
            filters = [[k, '=', v] for k, v in filters.items()]
        if type(filters) is not list:
            _deny()
        column = 'name' if doctype == DRAFT else 'draft'
        form.filters = json.dumps(filters + [[column, 'in', _readable_names()]])
    if doctype in (DRAFT, REVISION) and name:
        if doctype == REVISION:
            name = _get(REVISION, name).draft
        _authorized_draft(name)

    # Framework DocShare fallback may override has_permission=False. This fence
    # runs before private downloads and direct File fetches, even for owners/shared
    # recipients, preserving tenant denial independently of positive framework ACL.
    file_names = []
    command = form.get('cmd') or request.path.rsplit('/', 1)[-1]
    if command == 'frappe.core.api.file.zip_files':
        files = form.get('files') or []
        files = json.loads(files) if isinstance(files, str) else files
        if type(files) is not list or not all(type(name) is str for name in files):
            _deny()
        file_names.extend(files)
    if command == 'frappe.utils.file_manager.add_attachments':
        attachments = form.get('attachments') or []
        attachments = json.loads(attachments) if isinstance(attachments, str) else attachments
        if type(attachments) is not list or not all(type(name) is str for name in attachments):
            _deny()
        file_names.extend(attachments)
    if request.path.startswith('/private/files/'):
        from urllib.parse import unquote
        file_names = frappe.get_all('File', filters={'file_url': unquote(request.path)}, pluck='name')
    elif doctype == 'File' and name:
        file_names = [name]
    elif request.path.startswith(('/api/method/', '/api/v1/method/', '/api/v2/method/')) or form.get('cmd'):
        cmd = form.get('cmd') or request.path.rsplit('/', 1)[-1]
        if cmd in ('download_file', 'frappe.handler.download_file',
                'frappe.core.doctype.file.file.download_file',
                'frappe.utils.file_manager.download_file', 'frappe.core.api.file.download_file'):
            if form.get('file_name'):
                file_names = [form.file_name]
            elif form.get('file_url'):
                file_names = frappe.get_all('File', filters={'file_url': form.file_url}, pluck='name')
    for file_name in file_names:
        file = _get('File', file_name)
        if file_has_permission(file, ptype='read', user=frappe.session.user) is False:
            _deny()
        if command in ('run_doc_method', 'frappe.handler.run_doc_method') and _source_evidence_for_url(file.file_url):
            _deny()

    if doctype == 'File' and not name and frappe.db.table_exists(DRAFT):
        # File list has the same DocShare OR fallback: restrict it outside ACL SQL.
        hidden = _hidden_files()
        if hidden:
            filters = form.get('filters') or []
            filters = json.loads(filters) if isinstance(filters, str) else filters
            if type(filters) is dict:
                filters = [[k, '=', v] for k, v in filters.items()]
            if type(filters) is not list:
                _deny()
            form.filters = json.dumps(filters + [['name', 'not in', hidden]])
