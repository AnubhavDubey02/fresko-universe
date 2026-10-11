"""Offline source contract checks only; native permissions/concurrency need Bench."""
import ast
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'fresko_universe'
SOURCE = PACKAGE / 'intake_native.py'


class NativeSourceContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SOURCE.read_text()
        cls.tree = ast.parse(cls.source)
        cls.functions = {n.name: n for n in cls.tree.body if isinstance(n, ast.FunctionDef)}
        cls.hooks = ast.parse((PACKAGE / 'hooks.py').read_text())

    def _text(self, function):
        return ast.get_source_segment(self.source, self.functions[function])

    def test_http_capture_has_no_authority_parameters(self):
        args = [a.arg for a in self.functions['capture'].args.args]
        self.assertEqual(args, ['evidence_name', 'channel', 'locator', 'fields'])
        self.assertEqual(self.functions['capture'].args.kwarg.arg, 'untrusted')
        self.assertIn('if untrusted or command not in', self._text('capture'))

    def test_capture_builds_server_envelope(self):
        text = self._text('capture')
        self.assertIn('_principal()', text)
        self.assertIn('capture_verified_proposal(proposal)', text)
        verified = self._text('capture_verified_proposal')
        self.assertIn('_resolved_evidence', verified)
        self.assertLess(verified.index('_resolved_evidence'), verified.index('_capture_locked'))
        self.assertIn('evidence.provider_message_id or evidence.name', text)
        self.assertIn('Envelope(channel, company', text)

    def test_current_roles_and_tenant_are_database_authority(self):
        text = self._text('_principal')
        self.assertIn('`tabHas Role`', text)
        self.assertIn('`tabUser Permission`', text)
        self.assertIn('FOR UPDATE', text)
        self.assertIn("'supplier' in role.casefold()", text)
        self.assertIn('len(companies) != 1', text)
        self.assertNotIn('get_roles(', text)

    def test_live_provider_channels_fail_closed(self):
        text = self._text('_assert_envelope')
        self.assertIn('(Channel.WHATSAPP, Channel.API)', text)
        self.assertIn('not all(scope)', text)

    def test_no_transaction_commit_or_posting_dependency(self):
        imports = [ast.unparse(n) for n in ast.walk(self.tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertFalse(any(any(x in n for x in ('commercial_service', 'money_service', 'outward')) for n in imports))
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Call):
                self.assertNotEqual(ast.unparse(node.func), 'frappe.db.commit')

    def test_serialization_retained_to_transaction_completion(self):
        text = self._text('_transaction_lock')
        for marker in ('GET_LOCK', 'RELEASE_LOCK', 'after_commit.add', 'after_rollback.add'):
            self.assertIn(marker, text)

    def test_partial_failure_is_savepoint_bounded(self):
        text = self._text('capture_verified_proposal')
        self.assertIn('savepoint', text)
        self.assertIn('except frappe.QueryDeadlockError', text)
        self.assertIn("rollback(save_point='intake_native_capture')", text)

    def test_blank_stale_tokens_do_not_skip_review_comparison(self):
        text = self._text('review')
        self.assertIn('expected_version is None', text)
        self.assertIn('str(expected_version) != str(row.version)', text)
        self.assertGreaterEqual(text.count("roles & {'Fresko Accounts', 'Fresko Approver'}"), 2)
        self.assertIn('actor == draft.capture_actor', text)

    def test_read_rechecks_all_revision_evidence(self):
        self.assertIn("filters={'draft': doc.name}, pluck='evidence'", self._text('_authorized_draft'))
        self.assertIn('_authorized_draft(key)', self._text('_capture_locked'))

    def test_private_download_v2_and_share_fences(self):
        text = self._text('guard_http_access')
        for marker in ('/private/files/', '/api/v2/document/', "form.filters = json.dumps", 'file_has_permission'):
            self.assertIn(marker, text)

    def test_only_new_hooks_added_existing_guards_preserved(self):
        values = {n.targets[0].id: ast.literal_eval(n.value) for n in self.hooks.body
                  if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)
                  and n.targets[0].id in ('auth_hooks', 'has_permission', 'permission_query_conditions')}
        self.assertIn('fresko_universe.permissions.deny_supplier_http_access', values['auth_hooks'])
        self.assertEqual(values['has_permission']['Fresko Evidence'], 'fresko_universe.permissions.evidence_has_permission')
        for dt in ('Fresko Intake Draft', 'Fresko Intake Revision'):
            self.assertIn(dt, values['has_permission'])
            self.assertIn(dt, values['permission_query_conditions'])

    def test_native_schema_unique_and_no_public_writes(self):
        for suffix, key in [('draft', 'proposal_key'), ('revision', 'revision_key')]:
            doc = json.loads((PACKAGE / f'fresko_core/doctype/fresko_intake_{suffix}/fresko_intake_{suffix}.json').read_text())
            fields = {f['fieldname']: f for f in doc['fields']}
            self.assertEqual(doc['engine'], 'InnoDB')
            self.assertTrue(fields[key]['unique'])
            if suffix == 'revision':
                self.assertTrue(fields['sequence_key']['unique'])
                self.assertEqual(fields['can_post']['default'], 0)
            for permission in doc['permissions']:
                self.assertFalse(any(permission.get(k) for k in ('write', 'create', 'delete', 'export', 'share')))


class BrowserFixtureCapacityContract(unittest.TestCase):
    def setUp(self):
        from types import SimpleNamespace
        class Config(dict):
            def __setattr__(self, name, value):
                self[name] = value
        self.conf = Config(allow_tests=True, fresko_browser_fixture_only=True,
                           fresko_disposable_browser_site=True)
        self.seen = []
        def insert(**kwargs):
            self.seen.append(self.conf['throttle_user_limit'])
            if self.fail:
                raise RuntimeError('synthetic insert failure')
            return 'created'
        def throw(message, exception):
            raise exception(message)
        self.fail = False
        frappe = SimpleNamespace(conf=self.conf, session=SimpleNamespace(user='Administrator'),
            PermissionError=PermissionError, throw=throw,
            db=SimpleNamespace(get_creation_count=lambda *args: 80),
            get_doc=lambda values: SimpleNamespace(insert=insert))
        source = (PACKAGE / 'tests/browser_fixture.py').read_text()
        function = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)
                        and n.name == '_insert_browser_user')
        scope = {'frappe': frappe}
        exec(compile(ast.Module(body=[function], type_ignores=[]), '<fixture>', 'exec'), scope)
        self.insert = scope['_insert_browser_user']
        self.values = {'doctype': 'User', 'email': 'synthetic@example.invalid'}

    def test_exhausted_capacity_restored_after_success(self):
        self.assertEqual(self.insert(self.values), 'created')
        self.assertEqual(self.seen, [81])
        self.assertNotIn('throttle_user_limit', self.conf)

    def test_existing_setting_restored_after_failure(self):
        self.conf['throttle_user_limit'] = 7
        self.fail = True
        with self.assertRaises(RuntimeError):
            self.insert(self.values)
        self.assertEqual(self.seen, [81])
        self.assertEqual(self.conf['throttle_user_limit'], 7)

    def test_ordinary_site_is_denied_without_configuration_change(self):
        self.conf['fresko_disposable_browser_site'] = False
        before = dict(self.conf)
        with self.assertRaises(PermissionError):
            self.insert(self.values)
        self.assertEqual(self.conf, before)
        self.assertFalse(self.seen)

    def test_real_user_is_denied_without_configuration_change(self):
        with self.assertRaises(PermissionError):
            self.insert({'doctype': 'User', 'email': 'real@example.com'})
        self.assertFalse(self.seen)
        self.assertNotIn('throttle_user_limit', self.conf)
