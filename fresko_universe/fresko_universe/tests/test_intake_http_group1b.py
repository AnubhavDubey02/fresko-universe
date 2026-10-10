"""Genuine authenticated WSGI requests against pinned Frappe/MariaDB.

Cookies, login, CSRF, API routing, hooks, permissions and transactions are real.
Threads isolate Frappe local connections; no identity/permission functions mocked.
Synthetic fixtures only. This is HTTP contract proof, not a mobile UI/device test.
"""
from __future__ import annotations

import json
import secrets
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from urllib.parse import quote

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import get_test_client
from frappe.utils.file_manager import save_file
from frappe.utils.password import update_password
from fresko_universe.tests.test_commercial_sale import _ensure_user
from fresko_universe.tests.utils import ensure_masters, make_container
from fresko_universe import intake_native


class TestGroup1BAuthenticatedHTTP(FrappeTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        frappe.set_user('Administrator')
        cls.site = frappe.local.site
        cls.base = 'http://' + cls.site
        cls.masters = ensure_masters()
        cls.company = cls.masters['company']
        cls.company_b = 'Group1B Synthetic Company B'
        if not frappe.db.exists('Company', cls.company_b):
            frappe.get_doc({'doctype': 'Company', 'company_name': cls.company_b, 'abbr': 'G1BB',
                'default_currency': 'INR', 'country': 'India'}).insert(ignore_permissions=True)
        if not frappe.db.exists('Role', 'Fresko Supplier Viewer'):
            frappe.get_doc({'doctype': 'Role', 'role_name': 'Fresko Supplier Viewer', 'desk_access': 0}).insert(ignore_permissions=True)
        cls.users = {}
        for label, roles, company in [
            ('maker', ['Fresko Salesperson'], cls.company),
            ('accounts', ['Fresko Accounts'], cls.company),
            ('reviewer', ['Fresko Approver'], cls.company),
            ('other', ['Fresko Accounts'], cls.company_b),
            ('supplier', ['Fresko Supplier Viewer'], cls.company),
            ('mixed', ['Fresko Supplier Viewer', 'Fresko Accounts'], cls.company),
            ('revoked', ['Fresko Accounts'], cls.company),
            ('ambiguous', ['Fresko Accounts'], cls.company),
        ]:
            user = _ensure_user(f'group1b-http-{label}@example.invalid', roles)
            password = secrets.token_urlsafe(32)
            update_password(user, password, logout_all_sessions=True)
            if not frappe.db.exists('User Permission', {'user': user, 'allow': 'Company', 'for_value': company}):
                frappe.get_doc({'doctype': 'User Permission', 'user': user, 'allow': 'Company', 'for_value': company}).insert(ignore_permissions=True)
            cls.users[label] = (user, password)
        user = cls.users['ambiguous'][0]
        if not frappe.db.exists('User Permission', {'user': user, 'allow': 'Company', 'for_value': cls.company_b}):
            frappe.get_doc({'doctype': 'User Permission', 'user': user, 'allow': 'Company', 'for_value': cls.company_b}).insert(ignore_permissions=True)
        frappe.db.commit()

    def setUp(self):
        frappe.set_user('Administrator')
        self.token = frappe.generate_hash(length=12)
        self.container = make_container(self.masters, container_no='G1B-HTTP-' + self.token)
        notes = 'Synthetic intake HTTP source ' + self.token
        self.evidence = frappe.get_doc({'doctype': 'Fresko Evidence', 'evidence_type': 'Note',
            'container': self.container.name, 'notes': notes,
            'content_sha256': sha256(notes.encode()).hexdigest()}).insert(ignore_permissions=True)
        frappe.db.commit()

    def tearDown(self):
        frappe.set_user('Administrator')

    def _request(self, client, method, path, *, data=None, token=None):
        def request():
            headers = {'X-Frappe-Site-Name': self.site}
            if isinstance(data, str):
                headers['Content-Type'] = 'application/json'
            if token:
                headers['X-Frappe-CSRF-Token'] = token
            response = None
            try:
                response = client.open(path, base_url=self.base, method=method,
                    query_string=data if method == 'GET' and isinstance(data, dict) else None,
                    data=None if method == 'GET' and isinstance(data, dict) else data, headers=headers)
                return response.status_code, response.get_data()
            finally:
                try:
                    if response is not None:
                        response.close()
                finally:
                    # Rendering can raise before Frappe's ClosingIterator exists.
                    # Always close this worker's actual connection and its locks.
                    frappe.destroy()
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(request).result(timeout=90)

    def _login(self, label):
        client = get_test_client()
        user, password = self.users[label]
        status, _ = self._request(client, 'POST', '/api/method/login', data={'usr': user, 'pwd': password})
        self.assertEqual(status, 200, 'Synthetic principal login failed')
        # Read the real server-created session token without printing credentials.
        cookie = client.get_cookie('sid', domain=self.site)
        self.assertIsNotNone(cookie, 'Cookie names/domains only: ' + repr(list(client._cookies)))
        session = frappe.cache.hget('session', cookie.value)
        token = session.get('data', {}).get('csrf_token') if isinstance(session, dict) else session.data.get('csrf_token')
        return client, token

    def _capture(self, client, token, *, quantity='2', evidence=None, extra=None):
        data = {'evidence_name': evidence or self.evidence.name, 'channel': 'MANUAL',
            'locator': json.dumps({'kind': 'manual_field', 'reference': 'quantity'}),
            'fields': json.dumps({'quantity': {'state': 'PROPOSED', 'value': quantity,
                'locator': {'kind': 'manual_field', 'reference': 'quantity'}}})}
        data.update(extra or {})
        return self._request(client, 'POST', '/api/method/fresko_universe.intake_native.capture', data=data, token=token)

    def _truth(self):
        frappe.db.commit()
        return {dt: frappe.db.sql(f'SELECT * FROM `tab{dt}` ORDER BY name', as_dict=True) for dt in (
            'Fresko Container', 'Fresko Container Lot', 'Fresko Evidence', 'Fresko Outward',
            'Fresko Commercial Sale', 'Fresko Collection', 'Fresko Payment Allocation')}

    def test_authorized_capture_read_review_and_no_posting(self):
        client, token = self._login('maker')
        before = self._truth()
        status, body = self._capture(client, token)
        self.assertEqual(status, 200, body.decode()[:4000])
        result = json.loads(body)['message']
        draft = result['draft_key']
        status, body = self._request(client, 'GET', '/api/method/fresko_universe.intake_native.authorized_preview?draft_key=' + draft)
        self.assertEqual(status, 200)
        self.assertFalse(json.loads(body)['message']['can_post'])
        status, _ = self._request(client, 'POST', '/api/method/fresko_universe.intake_native.review',
            data={'draft_key': draft, 'expected_version': 1, 'action': 'ACKNOWLEDGE', 'reason': 'Synthetic review'}, token=token)
        self.assertEqual(status, 403)
        reviewer, review_token = self._login('reviewer')
        status, body = self._request(reviewer, 'POST', '/api/method/fresko_universe.intake_native.review',
            data={'draft_key': draft, 'expected_version': 1, 'action': 'ACKNOWLEDGE', 'reason': 'Synthetic review'}, token=review_token)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['message']['version'], 2)
        for version in ('', '1'):
            status, _ = self._request(reviewer, 'POST', '/api/method/fresko_universe.intake_native.review',
                data={'draft_key': draft, 'expected_version': version, 'action': 'REJECT', 'reason': 'Synthetic review'}, token=review_token)
            self.assertEqual(status, 417)
        self.assertEqual(self._truth(), before)

    def test_supplier_guest_ambiguous_and_forged_company_denied(self):
        before = self._truth()
        for label in ('supplier', 'mixed', 'ambiguous'):
            client, token = self._login(label)
            status, _ = self._capture(client, token)
            self.assertEqual(status, 403, label)
        status, _ = self._capture(get_test_client(), None)
        self.assertEqual(status, 403)
        client, token = self._login('accounts')
        status, _ = self._capture(client, token, extra={'company': self.company_b, 'company_verified': 'true'})
        self.assertEqual(status, 403)
        self.assertEqual(self._truth(), before)

    def test_cross_company_direct_list_v2_shared_records_and_missing_privacy(self):
        maker, token = self._login('maker')
        status, body = self._capture(maker, token)
        self.assertEqual(status, 200)
        draft = json.loads(body)['message']['draft_key']
        frappe.db.commit()
        revision = frappe.db.get_value(intake_native.REVISION, {'draft': draft}, 'name')
        # Adversarial administrative shares must not override tenant isolation.
        frappe.share.add(intake_native.DRAFT, draft, self.users['other'][0], read=1, flags={'ignore_share_permission': True})
        frappe.share.add(intake_native.REVISION, revision, self.users['other'][0], read=1, flags={'ignore_share_permission': True})
        frappe.db.commit()
        other, other_token = self._login('other')
        for dt, name in ((intake_native.DRAFT, draft), (intake_native.REVISION, revision)):
            for prefix in ('/api/resource/', '/api/v2/document/'):
                status, body = self._request(other, 'GET', prefix + quote(dt) + '/' + name)
                missing_status, missing = self._request(other, 'GET', prefix + quote(dt) + '/' + 'f' * 64)
                self.assertEqual((status, missing_status), (403, 403))
                self.assertNotIn(name.encode(), body)
            status, body = self._request(other, 'GET', '/api/resource/' + quote(dt))
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)['data'], [])
        for dt in (intake_native.DRAFT, intake_native.REVISION):
            status, body = self._request(other, 'GET', '/api/v2/doctype/' + quote(dt) + '/count')
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)['data'], 0)
        status, _ = self._capture(other, other_token)
        self.assertEqual(status, 403)

    def test_private_attachment_owner_share_and_anonymous_denial(self):
        contents = ('Synthetic private bytes ' + self.token).encode()
        ev = frappe.get_doc({'doctype': 'Fresko Evidence', 'evidence_type': 'Document',
            'container': self.container.name, 'content_sha256': sha256(contents).hexdigest()}).insert(ignore_permissions=True)
        file = save_file('g1b-' + self.token + '.txt', contents, 'Fresko Evidence', ev.name, is_private=1)
        ev.file = file.file_url
        ev.save(ignore_permissions=True)
        frappe.db.commit()
        rows = frappe.get_all('File', filters={'file_url': file.file_url}, fields=['name', 'is_private', 'attached_to_doctype', 'attached_to_name'])
        self.assertGreaterEqual(len(rows), 1, rows)
        self.assertTrue(all(row.is_private for row in rows), rows)
        self.assertTrue(all(row.attached_to_name == ev.name for row in rows), rows)
        client, token = self._login('accounts')
        status, body = self._capture(client, token, evidence=ev.name)
        self.assertEqual(status, 200, body.decode()[:4000])
        status, body = self._request(client, 'GET', file.file_url)
        self.assertEqual((status, body), (200, contents))
        from io import BytesIO
        from zipfile import ZipFile
        status, zipped = self._request(client, 'GET', '/api/method/frappe.core.api.file.zip_files?files=' + quote(json.dumps([file.name])))
        self.assertEqual(status, 200)
        with ZipFile(BytesIO(zipped)) as archive:
            self.assertEqual(archive.read(file.file_name), contents)
        status, _ = self._request(client, 'PUT', '/api/resource/File/' + file.name,
            data=json.dumps({'is_private': 0}), token=token)
        self.assertEqual(status, 403)
        status, preserved = self._request(client, 'GET', file.file_url)
        self.assertEqual((status, preserved), (200, contents))
        frappe.share.add('File', file.name, self.users['other'][0], read=1, flags={'ignore_share_permission': True})
        frappe.db.set_value('File', file.name, 'owner', self.users['other'][0])
        frappe.db.commit()
        other, other_token = self._login('other')
        for who in (other, get_test_client()):
            status, body = self._request(who, 'GET', file.file_url)
            self.assertEqual(status, 403)
            self.assertNotIn(contents, body)
        # A forged owned File alias of protected bytes must also fail.
        alias = frappe.get_doc({'doctype': 'File', 'file_name': 'alias-' + self.token + '.txt',
            'file_url': file.file_url, 'is_private': 1}).insert(ignore_permissions=True)
        frappe.db.set_value('File', alias.name, 'owner', self.users['other'][0])
        frappe.db.commit()
        for files in ([file.name], [alias.name]):
            status, body = self._request(other, 'GET', '/api/method/frappe.core.api.file.zip_files?files=' + quote(json.dumps(files)))
            self.assertEqual(status, 403)
            self.assertNotIn(contents, body)
        for method, arguments in (
            ('get_files_by_search_text', {'text': self.token}),
            ('get_files_in_folder', {'folder': file.folder}),
            ('get_attached_images', {'doctype': 'Fresko Evidence', 'names': json.dumps([ev.name])}),
        ):
            status, body = self._request(other, 'GET', '/api/method/frappe.core.api.file.' + method, data=arguments)
            self.assertEqual(status, 200)
            self.assertNotIn(file.name.encode(), body)
            self.assertNotIn(file.file_url.encode(), body)
            self.assertNotIn(alias.name.encode(), body)
        for method in ('download_file', 'frappe.handler.download_file',
                'frappe.core.doctype.file.file.download_file', 'frappe.utils.file_manager.download_file'):
            for prefix in ('/api/method/', '/api/v2/method/'):
                status, body = self._request(other, 'GET', prefix + method + '?file_url=' + quote(file.file_url))
                self.assertEqual(status, 403, method)
                self.assertNotIn(contents, body)
        for arguments in ({'dt': 'File', 'dn': file.name, 'method': 'optimize_file', 'docs': json.dumps({'doctype': 'User', 'name': self.users['other'][0]})},
                {'docs': json.dumps({'doctype': 'File', 'name': file.name}), 'method': 'optimize_file'}):
            status, body = self._request(other, 'POST', '/api/method/run_doc_method', data=arguments, token=other_token)
            self.assertEqual(status, 403)
            self.assertNotIn(contents, body)
        status, _ = self._request(other, 'POST', '/api/v2/method/run_doc_method',
            data={'document': json.dumps({'doctype': 'File', 'name': file.name}), 'method': 'optimize_file'}, token=other_token)
        self.assertEqual(status, 403)
        status, _ = self._request(other, 'GET', '/api/resource/File/' + file.name)
        self.assertEqual(status, 403)
        status, body = self._request(other, 'GET', '/api/resource/File?filters=' + quote(json.dumps({'name': file.name})))
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['data'], [])

    def test_revocation_in_existing_authenticated_session(self):
        client, token = self._login('revoked')
        status, body = self._capture(client, token)
        self.assertEqual(status, 200)
        draft = json.loads(body)['message']['draft_key']
        user = frappe.get_doc('User', self.users['revoked'][0])
        user.set('roles', [])
        user.save(ignore_permissions=True)
        frappe.db.commit()
        status, _ = self._request(client, 'GET', '/api/method/fresko_universe.intake_native.authorized_preview?draft_key=' + draft)
        self.assertEqual(status, 403)
        status, _ = self._capture(client, token)
        self.assertEqual(status, 403)
        user.append('roles', {'role': 'Fresko Accounts'})
        user.save(ignore_permissions=True)
        frappe.db.commit()

    def test_twelve_authenticated_replays_and_changed_content(self):
        clients = [self._login('accounts') for _ in range(12)]
        before = self._truth()
        with ThreadPoolExecutor(max_workers=12) as pool:
            responses = list(pool.map(lambda pair: self._capture(*pair), clients))
        self.assertTrue(all(status == 200 for status, _ in responses), [(status, body.decode()[:4000]) for status, body in responses if status != 200])
        results = [json.loads(body)['message'] for _, body in responses]
        self.assertEqual(sum(r['created'] for r in results), 1)
        draft = results[0]['draft_key']
        frappe.db.commit()
        self.assertEqual(frappe.db.count(intake_native.REVISION, {'draft': draft}), 1)
        client, token = clients[0]
        status, body = self._capture(client, token, quantity='3')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['message']['state'], 'CONFLICT')
        status, body = self._capture(client, token)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['message']['state'], 'CONFLICT')
        self.assertEqual(self._truth(), before)
        self.assertEqual(frappe.db.count(intake_native.REVISION, {'draft': draft}), 2)

    def test_salesperson_money_and_direct_history_mutation_denied(self):
        client, token = self._login('maker')
        before = self._truth()
        status, body = self._capture(client, token)
        self.assertEqual(status, 200)
        draft = json.loads(body)['message']['draft_key']
        frappe.db.commit()
        revision = frappe.db.get_value(intake_native.REVISION, {'draft': draft}, 'name')
        snapshot = frappe.get_doc(intake_native.REVISION, revision).as_dict()
        frappe.db.commit()
        status, _ = self._request(client, 'GET',
            '/api/method/fresko_universe.money.get_unallocated_collections?company=' + quote(self.company))
        self.assertEqual(status, 403)
        for dt, name in ((intake_native.DRAFT, draft), (intake_native.REVISION, revision)):
            for method in ('PUT', 'DELETE'):
                status, _ = self._request(client, method, '/api/resource/' + quote(dt) + '/' + name,
                    data=json.dumps({'review_state': 'REVIEWED', 'flags': {'intake_service': True}}), token=token)
                self.assertEqual(status, 403)
        frappe.db.commit()
        self.assertEqual(frappe.get_doc(intake_native.REVISION, revision).as_dict(), snapshot)
        self.assertEqual(self._truth(), before)

    def test_http_channels_unknown_and_source_scope(self):
        client, token = self._login('accounts')
        contents = ('Synthetic channel bytes ' + self.token).encode()
        ev = frappe.get_doc({'doctype': 'Fresko Evidence', 'evidence_type': 'Document',
            'container': self.container.name, 'content_sha256': sha256(contents).hexdigest()}).insert(ignore_permissions=True)
        file = save_file('channels-' + self.token + '.txt', contents, 'Fresko Evidence', ev.name, is_private=1)
        ev.file = file.file_url
        ev.save(ignore_permissions=True)
        # Synthetic scoped stored Evidence, not a live provider signature proof.
        scoped = frappe.get_doc({'doctype': 'Fresko Evidence', 'evidence_type': 'Note',
            'container': self.container.name, 'notes': 'Scoped synthetic source',
            'content_sha256': sha256(b'Scoped synthetic source').hexdigest(),
            'provider': 'GROUP1B_SYNTHETIC', 'provider_account_id': 'synthetic-account',
            'conversation_id': 'synthetic-conversation', 'provider_message_id': self.token}).insert(ignore_permissions=True)
        frappe.db.commit()
        names = []
        for channel, kind, reference, evidence in (
            ('MANUAL', 'manual_field', 'quantity', self.evidence.name),
            ('FILE', 'worksheet_cell', 'Sheet1!A2', ev.name),
            ('WHATSAPP', 'message', 'message:quantity', scoped.name),
            ('API', 'api_field', 'quantity', scoped.name),
        ):
            location = {'kind': kind, 'reference': reference}
            data = {'evidence_name': evidence, 'channel': channel,
                'locator': json.dumps(location), 'fields': json.dumps({
                    'quantity': {'state': 'UNKNOWN', 'value': None, 'locator': location}})}
            status, body = self._request(client, 'POST', '/api/method/fresko_universe.intake_native.capture', data=data, token=token)
            self.assertEqual(status, 200, body.decode()[:4000])
            draft = json.loads(body)['message']['draft_key']
            names.append(draft)
            status, body = self._request(client, 'GET', '/api/method/fresko_universe.intake_native.authorized_preview?draft_key=' + draft)
            self.assertEqual(status, 200)
            preview = json.loads(body)['message']['preview']
            self.assertEqual(preview['fields']['quantity']['state'], 'UNKNOWN')
            self.assertIsNone(preview['fields']['quantity']['value'])
        self.assertEqual(len(set(names)), 4)
        data['evidence_name'] = self.evidence.name
        status, _ = self._request(client, 'POST', '/api/method/fresko_universe.intake_native.capture', data=data, token=token)
        self.assertEqual(status, 403, 'API cannot downgrade to unscoped source identity')

    def test_conflict_revision_private_source_is_also_tenant_fenced(self):
        client, token = self._login('accounts')
        status, body = self._capture(client, token)
        self.assertEqual(status, 200)
        draft = json.loads(body)['message']['draft_key']
        contents = ('Synthetic conflict source ' + self.token).encode()
        ev = frappe.get_doc({'doctype': 'Fresko Evidence', 'evidence_type': 'Document',
            'container': self.container.name, 'content_sha256': sha256(contents).hexdigest()}).insert(ignore_permissions=True)
        file = save_file('conflict-' + self.token + '.txt', contents, 'Fresko Evidence', ev.name, is_private=1)
        ev.file = file.file_url
        ev.save(ignore_permissions=True)
        from fresko_universe.intake_contract import Channel, Envelope, Field, FieldState, Locator, Proposal, ReviewState
        location = Locator('manual_field', 'quantity')
        # Server-side correction supplies new evidence for the same original event.
        envelope = Envelope(Channel.MANUAL, self.company, self.evidence.name, self.evidence.name,
            ev.name, ev.content_sha256, ev.content_sha256, location)
        proposal = Proposal(envelope, {'quantity': Field(FieldState.PROPOSED, '3', location)}, ReviewState.NEEDS_REVIEW)
        frappe.set_user(self.users['accounts'][0])
        result = intake_native.capture_verified_proposal(proposal)
        self.assertEqual(result['draft_key'], draft)
        self.assertEqual(result['state'], 'CONFLICT')
        frappe.db.commit()
        frappe.set_user('Administrator')
        frappe.share.add('File', file.name, self.users['other'][0], read=1, flags={'ignore_share_permission': True})
        frappe.db.commit()
        other, _ = self._login('other')
        status, body = self._request(other, 'GET', '/api/method/frappe.core.api.file.get_files_by_search_text', data={'text': self.token})
        self.assertEqual(status, 200)
        self.assertNotIn(file.file_url.encode(), body)
        status, _ = self._request(other, 'GET', file.file_url)
        self.assertEqual(status, 403)
        status, body = self._request(client, 'GET', '/api/method/frappe.core.api.file.zip_files', data={'files': json.dumps([file.name])})
        self.assertEqual(status, 200)
