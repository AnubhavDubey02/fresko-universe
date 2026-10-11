"""Native Frappe/MariaDB intake replay, rollback and review regressions.

Threaded workers own real database connections; HTTP/session and private-file
probes live in test_intake_http_group1b. Synthetic fixtures only.
"""
from __future__ import annotations
from dataclasses import replace
from hashlib import sha256

import frappe
from frappe.tests.utils import FrappeTestCase
from fresko_universe.intake_contract import Channel, Envelope, Field, FieldState, Locator, Proposal, ReviewState
from fresko_universe import intake_native
from fresko_universe.tests.test_commercial_sale import _ensure_user
from fresko_universe.tests.utils import ensure_masters, make_container


class TestGroup1BNativeCapture(FrappeTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        frappe.set_user('Administrator')
        if not frappe.db.exists('Item', {'disabled': 0}):
            frappe.get_doc({'doctype': 'Item', 'item_code': 'GROUP1B-SYNTHETIC-ITEM',
                'item_name': 'Synthetic intake QA item', 'item_group': frappe.db.get_value('Item Group', {'is_group': 0}, 'name'),
                'stock_uom': 'Kg', 'is_stock_item': 0}).insert(ignore_permissions=True)
        if not frappe.db.exists('Supplier', {}):
            frappe.get_doc({'doctype': 'Supplier', 'supplier_name': 'GROUP1B-SYNTHETIC-SUPPLIER',
                'supplier_group': frappe.db.get_value('Supplier Group', {'is_group': 0}, 'name'),
                'supplier_type': 'Company'}).insert(ignore_permissions=True)
        cls.masters = ensure_masters()
        cls.actor = _ensure_user('group1b_accounts@example.invalid', ['Fresko Accounts'])
        if not frappe.db.exists('Role', 'Fresko Supplier Viewer'):
            frappe.get_doc({'doctype': 'Role', 'role_name': 'Fresko Supplier Viewer', 'desk_access': 0}).insert(ignore_permissions=True)
        cls.supplier = _ensure_user('group1b_supplier@example.invalid', ['Fresko Accounts', 'Fresko Supplier Viewer'])
        frappe.db.commit()

    def setUp(self):
        frappe.set_user('Administrator')
        self.token = frappe.generate_hash(length=10)
        self.container = make_container(self.masters, container_no=f'G1B-SYN-{self.token}', inward_qty=10)
        self.company = self.container.company
        evidence_hash = sha256(('synthetic|'+self.token).encode()).hexdigest()
        self.evidence = frappe.get_doc({'doctype':'Fresko Evidence', 'evidence_type':'Note',
            'container':self.container.name, 'content_sha256':evidence_hash,
            'notes':'synthetic|'+self.token}).insert(ignore_permissions=True)
        if not frappe.db.exists('User Permission', {'user':self.actor,'allow':'Company','for_value':self.company}):
            frappe.get_doc({'doctype':'User Permission','user':self.actor,'allow':'Company',
                            'for_value':self.company}).insert(ignore_permissions=True)
        if not frappe.db.exists('User Permission', {'user':self.supplier,'allow':'Company','for_value':self.company}):
            frappe.get_doc({'doctype':'User Permission','user':self.supplier,'allow':'Company',
                            'for_value':self.company}).insert(ignore_permissions=True)

    def tearDown(self):
        frappe.set_user('Administrator')

    def _proposal(self, *, quantity='2', event=None, company=None, evidence=None):
        ev=evidence or self.evidence
        env=Envelope(channel=Channel.MANUAL, company=company or self.company,
            source_account='test-manual', source_event_id=event or self.token,
            evidence_ref=ev.name, evidence_sha256=ev.content_sha256,
            evidence_version=ev.message_payload_sha256 or ev.content_sha256,
            locator=Locator('manual_field','qty'))
        return Proposal(envelope=env,fields={'quantity':Field(FieldState.PROPOSED,quantity,
                 Locator('manual_field','qty'))},review_state=ReviewState.NEEDS_REVIEW)

    def test_real_session_capture_and_idempotent_replay(self):
        p=self._proposal()
        frappe.set_user(self.actor)
        one=intake_native.capture_verified_proposal(p)
        two=intake_native.capture_verified_proposal(p)
        self.assertEqual(one['state'],'CREATED')
        self.assertEqual(two['state'],'IDENTICAL')
        self.assertFalse(one['can_post'])
        frappe.set_user('Administrator')
        self.assertEqual(frappe.db.count('Fresko Intake Revision',{'draft':p.proposal_key}),1)

    def test_changed_payload_conflict_is_immutable_and_sticky(self):
        original=self._proposal();changed=self._proposal(quantity='3')
        frappe.set_user(self.actor)
        self.assertEqual(intake_native.capture_verified_proposal(original)['state'],'CREATED')
        self.assertEqual(intake_native.capture_verified_proposal(changed)['state'],'CONFLICT')
        self.assertEqual(intake_native.capture_verified_proposal(original)['state'],'CONFLICT')
        frappe.set_user('Administrator')
        draft=frappe.get_doc('Fresko Intake Draft',original.proposal_key)
        self.assertEqual(draft.review_state,'CONFLICT')
        self.assertEqual(draft.content_fingerprint,original.content_fingerprint)
        self.assertEqual(frappe.db.count('Fresko Intake Revision',{'draft':draft.name}),2)

    def test_guest_supplier_and_cross_tenant_envelope_denied(self):
        p=self._proposal()
        for user in ('Guest',self.supplier):
            frappe.set_user(user)
            with self.assertRaises(frappe.PermissionError):
                intake_native.capture_verified_proposal(p)
        frappe.set_user(self.actor)
        with self.assertRaises(frappe.PermissionError):
            intake_native.capture_verified_proposal(self._proposal(company='OTHER-SYNTHETIC-COMPANY'))

    def test_distinct_source_events_not_auto_merged(self):
        p=self._proposal()
        later=self._proposal(event=self.token+'-other')
        frappe.set_user(self.actor)
        self.assertEqual(intake_native.capture_verified_proposal(p)['state'],'CREATED')
        self.assertEqual(intake_native.capture_verified_proposal(later)['state'],'POSSIBLE_DUPLICATE')
        self.assertNotEqual(p.proposal_key,later.proposal_key)

    def test_unlinked_evidence_denied_before_persistence(self):
        frappe.set_user('Administrator')
        ev=frappe.get_doc({'doctype':'Fresko Evidence', 'evidence_type':'Note',
                           'content_sha256':sha256(self.token.encode()).hexdigest()}).insert(ignore_permissions=True)
        p=self._proposal(evidence=ev)
        frappe.set_user(self.actor)
        with self.assertRaises(frappe.PermissionError):
            intake_native.capture_verified_proposal(p)
        frappe.set_user('Administrator')
        self.assertFalse(frappe.db.exists('Fresko Intake Draft',p.proposal_key))


    def test_hash_and_version_mismatch_leave_no_draft(self):
        p = self._proposal()
        frappe.set_user(self.actor)
        for envelope in (replace(p.envelope, evidence_sha256='a' * 64),
                         replace(p.envelope, evidence_version='forged')):
            with self.assertRaises(frappe.PermissionError):
                intake_native.capture_verified_proposal(replace(p, envelope=envelope))
        frappe.set_user('Administrator')
        self.assertFalse(frappe.db.exists(intake_native.DRAFT, p.proposal_key))

    def test_review_is_append_only_separate_and_requires_current_token(self):
        reviewer = _ensure_user('group1b_reviewer@example.invalid', ['Fresko Accounts'])
        if not frappe.db.exists('User Permission', {'user': reviewer, 'allow': 'Company', 'for_value': self.company}):
            frappe.get_doc({'doctype': 'User Permission', 'user': reviewer, 'allow': 'Company',
                            'for_value': self.company}).insert(ignore_permissions=True)
        p = self._proposal()
        frappe.set_user(self.actor)
        intake_native.capture_verified_proposal(p)
        with self.assertRaises(frappe.PermissionError):
            intake_native.review(p.proposal_key, 1, 'ACKNOWLEDGE', 'Synthetic check')
        frappe.set_user(reviewer)
        for token in (None, '', 0, '2'):
            with self.assertRaisesRegex(frappe.ValidationError, 'STALE_VERSION'):
                intake_native.review(p.proposal_key, token, 'ACKNOWLEDGE', 'Synthetic check')
        result = intake_native.review(p.proposal_key, 1, 'ACKNOWLEDGE', 'Synthetic check')
        self.assertEqual(result, {'state': 'REVIEWED', 'version': 2, 'can_post': False})
        with self.assertRaisesRegex(frappe.ValidationError, 'STALE_VERSION'):
            intake_native.review(p.proposal_key, 1, 'ACKNOWLEDGE', 'Synthetic check')
        preview = intake_native.authorized_preview(p.proposal_key)
        self.assertEqual([r.sequence for r in preview['history']], [1, 2])
        self.assertEqual(preview['preview']['fields']['quantity']['value'], '2')
        original = frappe.get_doc(intake_native.REVISION, p.revision_key)
        original.reason = 'Changed history'
        original.flags.intake_service = True
        with self.assertRaises(frappe.PermissionError):
            original.save(ignore_permissions=True)
        self.assertFalse(preview['can_post'])

    def test_capture_failure_rolls_back_and_retry_recovers(self):
        from unittest.mock import patch
        p = self._proposal()
        frappe.set_user(self.actor)
        with patch.object(intake_native, '_append_revision', side_effect=RuntimeError('synthetic fault')):
            with self.assertRaisesRegex(RuntimeError, 'synthetic fault'):
                intake_native.capture_verified_proposal(p)
        self.assertFalse(frappe.db.exists(intake_native.DRAFT, p.proposal_key))
        self.assertEqual(intake_native.capture_verified_proposal(p)['state'], 'CREATED')
        self.assertEqual(frappe.db.count(intake_native.REVISION, {'draft': p.proposal_key}), 1)

    def test_revoked_or_ambiguous_principal_cannot_read(self):
        p = self._proposal()
        frappe.set_user(self.actor)
        intake_native.capture_verified_proposal(p)
        frappe.set_user('Administrator')
        actor = frappe.get_doc('User', self.actor)
        actor.set('roles', [])
        actor.save(ignore_permissions=True)
        frappe.set_user(self.actor)
        with self.assertRaises(frappe.PermissionError):
            intake_native.authorized_preview(p.proposal_key)
        frappe.set_user('Administrator')
        actor.append('roles', {'role': 'Fresko Accounts'})
        actor.save(ignore_permissions=True)

    def _parallel(self, proposals):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        site = frappe.local.site
        sites_path = frappe.local.sites_path
        actor = self.actor
        frappe.db.commit()
        barrier = Barrier(len(proposals))
        def capture(proposal):
            frappe.init(site=site, sites_path=sites_path)
            frappe.connect()
            frappe.set_user(actor)
            try:
                barrier.wait(timeout=60)
                result = intake_native.capture_verified_proposal(proposal)
                frappe.db.commit()
                return result
            except Exception:
                frappe.db.rollback()
                raise
            finally:
                frappe.destroy()
        with ThreadPoolExecutor(max_workers=len(proposals)) as pool:
            results = list(pool.map(capture, proposals))
        frappe.db.commit()
        return results

    def test_twelve_native_mariadb_identical_replays(self):
        p = self._proposal()
        results = self._parallel([p] * 12)
        self.assertEqual(sum(r['created'] for r in results), 1)
        self.assertEqual(frappe.db.count(intake_native.DRAFT, {'name': p.proposal_key}), 1)
        self.assertEqual(frappe.db.count(intake_native.REVISION, {'draft': p.proposal_key}), 1)

    def test_native_competing_changed_revisions(self):
        p = self._proposal()
        frappe.set_user(self.actor)
        intake_native.capture_verified_proposal(p)
        results = self._parallel([self._proposal(quantity='3'), self._proposal(quantity='4')])
        self.assertTrue(all(r['state'] == 'CONFLICT' for r in results))
        draft = frappe.get_doc(intake_native.DRAFT, p.proposal_key)
        self.assertEqual(draft.review_state, 'CONFLICT')
        self.assertEqual(draft.version, 3)
        self.assertEqual(frappe.db.count(intake_native.REVISION, {'draft': draft.name}), 3)

    def test_identical_textual_source_ids_are_company_scoped(self):
        company_b = 'Group1B Synthetic Native Company B'
        if not frappe.db.exists('Company', company_b):
            frappe.get_doc({'doctype': 'Company', 'company_name': company_b, 'abbr': 'G1NB',
                'default_currency': 'INR', 'country': 'India'}).insert(ignore_permissions=True)
        masters_b = dict(self.masters, company=company_b)
        container_b = make_container(masters_b, container_no='G1B-B-' + self.token)
        notes = self.evidence.notes
        ev_b = frappe.get_doc({'doctype': 'Fresko Evidence', 'evidence_type': 'Note',
            'container': container_b.name, 'notes': notes, 'content_sha256': self.evidence.content_sha256}).insert(ignore_permissions=True)
        actor_b = _ensure_user('group1b-native-b@example.invalid', ['Fresko Accounts'])
        if not frappe.db.exists('User Permission', {'user': actor_b, 'allow': 'Company', 'for_value': company_b}):
            frappe.get_doc({'doctype': 'User Permission', 'user': actor_b, 'allow': 'Company', 'for_value': company_b}).insert(ignore_permissions=True)
        original = self._proposal(event='same-text-' + self.token)
        other = self._proposal(event='same-text-' + self.token, company=company_b, evidence=ev_b)
        frappe.set_user(self.actor)
        self.assertTrue(intake_native.capture_verified_proposal(original)['created'])
        frappe.set_user(actor_b)
        self.assertTrue(intake_native.capture_verified_proposal(other)['created'])
        self.assertNotEqual(original.proposal_key, other.proposal_key)
        with self.assertRaises(frappe.PermissionError):
            intake_native.authorized_preview(original.proposal_key)
        self.assertEqual(intake_native.authorized_preview(other.proposal_key)['preview']['fields']['quantity']['value'], '2')
