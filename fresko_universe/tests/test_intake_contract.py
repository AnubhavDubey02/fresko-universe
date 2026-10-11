import unittest


from fresko_universe.intake_contract import (
    Channel, Envelope, Field, FieldState, IntakeError, Locator, Proposal, ReviewState,
)




class IntakeContractTest(unittest.TestCase):
    def env(self, channel=Channel.WHATSAPP, **changes):
        kwargs = dict(
            channel=channel, company="A", source_account="account-1",
            source_event_id="event-1", evidence_ref="EV-1",
            evidence_sha256="a" * 64, evidence_version="v1",
            locator=Locator("message", "line:1"),
        )
        kwargs.update(changes)
        return Envelope(**kwargs)


    def proposal(self, **changes):
        kwargs = dict(
            envelope=self.env(),
            fields={"quantity": Field(FieldState.PROPOSED, "50.00", Locator("message", "qty"))},
            review_state=ReviewState.NEEDS_REVIEW,
        )
        kwargs.update(changes)
        return Proposal(**kwargs)


    def test_all_channels_are_read_only(self):
        for channel in Channel:
            self.assertFalse(self.proposal(envelope=self.env(channel)).preview()["can_post"])


    def test_replay_key_stable(self):
        self.assertEqual(self.env().delivery_key, self.env().delivery_key)


    def test_cross_company_keys_differ(self):
        self.assertNotEqual(self.env().delivery_key, self.env(company="B").delivery_key)


    def test_accounts_separate(self):
        self.assertNotEqual(self.env().delivery_key, self.env(source_account="other").delivery_key)


    def test_rows_share_delivery_but_not_proposal(self):
        a = self.env(Channel.FILE, locator=Locator("worksheet_cell", "Sheet1!A1"))
        b = self.env(Channel.FILE, locator=Locator("worksheet_cell", "Sheet1!A2"))
        self.assertEqual(a.delivery_key, b.delivery_key)
        self.assertNotEqual(a.proposal_key, b.proposal_key)


    def test_unknown_is_null(self):
        self.assertIsNone(Field(FieldState.UNKNOWN, None, Locator("message", "buyer")).value)
        with self.assertRaises(IntakeError):
            Field(FieldState.UNKNOWN, "guessed buyer", Locator("message", "buyer"))


    def test_forged_posting_rejected(self):
        with self.assertRaises(IntakeError):
            self.proposal(can_post=True)


    def test_unsupported_field_rejected(self):
        with self.assertRaises(IntakeError):
            self.proposal(fields={"approve": Field(FieldState.PROPOSED, "true", Locator("message", "x"))})


    def test_bad_numeric_values_rejected(self):
        for value in ("-1", "1e6", "NaN", "Infinity", "1,000", "1.2.3"):
            with self.subTest(value=value), self.assertRaises(IntakeError):
                self.proposal(fields={"amount": Field(FieldState.PROPOSED, value, Locator("message", "x"))})


    def test_large_exact_decimal_allowed(self):
        self.proposal(fields={"amount": Field(FieldState.PROPOSED, "12345678901234567890.123456",
                                             Locator("worksheet_cell", "Sheet!D7"))})


    def test_bad_evidence_hash_rejected(self):
        with self.assertRaises(IntakeError):
            self.env(evidence_sha256="not-a-sha")


    def test_empty_source_event_rejected(self):
        with self.assertRaises(IntakeError):
            self.env(source_event_id="")


    def test_field_provenance_preserved(self):
        self.assertEqual(self.proposal().preview()["fields"]["quantity"]["source_locator"]["reference"], "qty")


    def test_evidence_version_preserved(self):
        self.assertEqual(self.proposal().preview()["evidence_version"], "v1")







class IntakeAdversarialTest(unittest.TestCase):
    env = IntakeContractTest.env
    proposal = IntakeContractTest.proposal

    def test_input_mapping_and_preview_are_detached(self):
        fields = {"quantity": Field(FieldState.PROPOSED, "1.00", Locator("message", "qty"), "p1", ("CHECK",))}
        p = self.proposal(fields=fields, warnings=("CHECK",))
        before = p.content_fingerprint
        fields.clear()
        with self.assertRaises(TypeError):
            p.fields["quantity"] = None
        snapshot = p.preview()
        snapshot["source_locator"]["reference"] = "forged"
        snapshot["fields"]["quantity"]["value"] = "999"
        snapshot["fields"]["quantity"]["source_locator"]["reference"] = "forged"
        snapshot["fields"]["quantity"]["uncertainty_flags"].clear()
        snapshot["warnings"].clear()
        self.assertEqual(before, p.content_fingerprint)
        self.assertEqual(p.fields["quantity"].value, "1.00")
        self.assertEqual(p.warnings, ("CHECK",))

    def test_frozen_nested_objects_have_no_mutable_dict(self):
        from dataclasses import FrozenInstanceError
        p = self.proposal()
        for value in (p, p.envelope, p.envelope.locator, p.fields["quantity"]):
            self.assertFalse(hasattr(value, "__dict__"))
        with self.assertRaises(FrozenInstanceError):
            p.envelope.locator.reference = "forged"

    def test_nonstring_values_rejected(self):
        from decimal import Decimal
        for value in (1.2, Decimal("1.20"), True, 0, [], {}, b"1.2"):
            with self.subTest(kind=type(value).__name__), self.assertRaises(IntakeError):
                Field(FieldState.PROPOSED, value, Locator("message", "x"))

    def test_numeric_grammar_is_ascii_and_exact(self):
        for value in ("+1", "01", ".5", "1.", "1\n", " 1", "1 ", "1e-2", "0x10", "1_000", "١", "1.٢"):
            with self.subTest(value=value), self.assertRaises(IntakeError):
                self.proposal(fields={"amount": Field(FieldState.PROPOSED, value, Locator("message", "x"))})

    def test_decimal_context_cannot_round_values(self):
        from decimal import localcontext
        raw = "9" * 1000 + ".000000000000000001"
        with localcontext() as ctx:
            ctx.prec = 2
            p = self.proposal(fields={"amount": Field(FieldState.PROPOSED, raw, Locator("message", "x"))})
            self.assertEqual(p.preview()["fields"]["amount"]["value"], raw)
        for value in ("0", "0.0000", "1.2300"):
            p = self.proposal(fields={"rate": Field(FieldState.PROPOSED, value, Locator("message", "x"))})
            self.assertEqual(p.preview()["fields"]["rate"]["value"], value)

    def test_unknown_and_absent_never_turn_into_zero(self):
        p = self.proposal(fields={"rate": Field(FieldState.UNKNOWN, None, Locator("message", "rate"))})
        self.assertNotIn("amount", p.preview()["fields"])
        self.assertIsNone(p.preview()["fields"]["rate"]["value"])
        self.assertEqual(p.safe_summary()["unknown_fields"], 1)

    def test_identical_replay_and_changed_content(self):
        from dataclasses import replace
        from fresko_universe.intake_contract import compare_replay, ReplayDisposition
        a = self.proposal()
        b = self.proposal()
        self.assertEqual(compare_replay(a, b), ReplayDisposition.IDENTICAL)
        self.assertEqual(a.revision_key, b.revision_key)
        b = replace(b, fields={"quantity": Field(FieldState.PROPOSED, "51", Locator("message", "qty"))})
        self.assertEqual(a.proposal_key, b.proposal_key)
        self.assertNotEqual(a.revision_key, b.revision_key)
        self.assertEqual(compare_replay(a, b), ReplayDisposition.CONFLICT)
        self.assertEqual(a.fields["quantity"].value, "50.00")

    def test_same_source_changed_evidence_is_conflict(self):
        from fresko_universe.intake_contract import compare_replay, ReplayDisposition
        a = self.proposal()
        for changes in ({"evidence_sha256": "b" * 64}, {"evidence_version": "v2"}, {"evidence_ref": "EV-2"}):
            self.assertEqual(compare_replay(a, self.proposal(envelope=self.env(**changes))),
                             ReplayDisposition.CONFLICT)

    def test_every_identity_dimension_is_scoped(self):
        from fresko_universe.intake_contract import compare_replay, ReplayDisposition
        a = self.proposal()
        for changes in ({"company": "B"}, {"channel": Channel.API}, {"source_account": "B"},
                        {"source_event_id": "B"}, {"source_provider": "provider"},
                        {"source_conversation": "conversation"}):
            b = self.proposal(envelope=self.env(**changes))
            self.assertEqual(compare_replay(a, b), ReplayDisposition.DIFFERENT_SOURCE)
            self.assertNotEqual(a.envelope.delivery_key, b.envelope.delivery_key)

    def test_same_hash_other_event_is_not_suppressed(self):
        from fresko_universe.intake_contract import compare_replay, ReplayDisposition
        a, b = self.proposal(), self.proposal(envelope=self.env(source_event_id="other"))
        self.assertEqual(a.envelope.evidence_sha256, b.envelope.evidence_sha256)
        self.assertEqual(compare_replay(a, b), ReplayDisposition.DIFFERENT_SOURCE)

    def test_delimiter_and_optional_scope_collisions(self):
        self.assertNotEqual(self.env(company="a|b", source_account="c").delivery_key,
                            self.env(company="a", source_account="b|c").delivery_key)
        self.assertNotEqual(self.env(source_provider=None).delivery_key,
                            self.env(source_provider="null").delivery_key)

    def test_worksheet_rows_sheets_and_pages_are_distinct(self):
        refs = [Locator("worksheet_cell", "Sheet1!A1"), Locator("worksheet_cell", "Sheet2!A1"),
                Locator("worksheet_cell", "Sheet1!A2"), Locator("page_region", "page1:row1"),
                Locator("page_region", "page2:row1")]
        p = [self.proposal(envelope=self.env(Channel.FILE, locator=l)) for l in refs]
        self.assertEqual(len({x.envelope.delivery_key for x in p}), 1)
        self.assertEqual(len({x.proposal_key for x in p}), 5)

    def test_field_order_does_not_change_fingerprint(self):
        a = Field(FieldState.PROPOSED, "2.00", Locator("message", "x"))
        b = Field(FieldState.PROPOSED, "1", Locator("message", "y"))
        self.assertEqual(self.proposal(fields={"amount": a, "quantity": b}).content_fingerprint,
                         self.proposal(fields={"quantity": b, "amount": a}).content_fingerprint)

    def test_review_progress_not_a_source_conflict(self):
        from dataclasses import replace
        from fresko_universe.intake_contract import compare_replay, ReplayDisposition
        a = self.proposal(review_state=ReviewState.NEEDS_SOURCE)
        b = replace(a, review_state=ReviewState.NEEDS_REVIEW, warnings=("CHECK",))
        self.assertEqual(compare_replay(a, b), ReplayDisposition.IDENTICAL)
        self.assertFalse(b.can_post)

    def test_parser_uncertainty_and_field_locator_changes_require_revision(self):
        from dataclasses import replace
        from fresko_universe.intake_contract import compare_replay, ReplayDisposition
        a = self.proposal()
        f = a.fields["quantity"]
        for changed in (replace(f, parser_version="p2"), replace(f, uncertainty_flags=("CHECK",)),
                        replace(f, locator=Locator("message", "other"))):
            b = replace(a, fields={"quantity": changed})
            self.assertEqual(compare_replay(a, b), ReplayDisposition.CONFLICT)
            self.assertEqual(b.preview()["fields"]["quantity"], changed.snapshot())

    def test_company_data_never_claims_authenticated_authority(self):
        from dataclasses import replace
        with self.assertRaises(TypeError):
            replace(self.env(), company_verified=True)
        self.assertNotIn("company_verified", self.proposal().preview())
        self.assertEqual(self.env(company="unverified synthetic tenant").company,
                         "unverified synthetic tenant")

    def test_raw_party_text_preserved(self):
        raw = "  A & B / WhatsApp\nparty  "
        p = self.proposal(fields={"buyer_alias": Field(FieldState.PROPOSED, raw, Locator("message", "span:3-29"))})
        self.assertEqual(p.preview()["fields"]["buyer_alias"]["value"], raw)
        self.assertEqual(p.preview()["source_account"], "account-1")
        self.assertEqual(p.preview()["source_event_id"], "event-1")

    def test_sensitive_values_absent_from_repr_summary_and_errors(self):
        import json
        marker = "SYNTHETIC-PRIVATE-PARTY"
        p = self.proposal(envelope=self.env(company=marker), fields={
            "buyer_alias": Field(FieldState.PROPOSED, marker, Locator("message", marker))})
        for value in (p, p.envelope, p.fields["buyer_alias"], p.fields["buyer_alias"].locator):
            self.assertNotIn(marker, repr(value))
        self.assertNotIn(marker, json.dumps(p.safe_summary()))
        with self.assertRaises(IntakeError) as caught:
            self.proposal(fields={marker: p.fields["buyer_alias"]})
        self.assertNotIn(marker, str(caught.exception))

    def test_invalid_types_and_bounds_fail_closed(self):
        for kind in (None, [], {}, "unsupported"):
            with self.assertRaises(IntakeError):
                Locator(kind, "x")
        for value in ("", "  ", "x" * 513, "bad\x00id", "bad\ud800id"):
            with self.assertRaises(IntakeError):
                self.env(source_event_id=value)
        for fields in ({1: self.proposal().fields["quantity"]}, {"amount": "1"}, {"quantity": None}, {}):
            with self.assertRaises(IntakeError):
                self.proposal(fields=fields)
        with self.assertRaises(IntakeError):
            self.env(channel="WHATSAPP")
        with self.assertRaises(IntakeError):
            Field("PROPOSED", "1", Locator("message", "x"))
        with self.assertRaises(IntakeError):
            Field(FieldState.PROPOSED, "x" * 2049, Locator("message", "x"))
        with self.assertRaises(IntakeError):
            self.env(locator={"kind": "message", "reference": "x"})

    def test_collections_are_bounded_and_immutable(self):
        for warnings in (["CHECK"], (None,), ("",), ("x" * 129,), ("CHECK",) * 51):
            with self.assertRaises(IntakeError):
                self.proposal(warnings=warnings)
        with self.assertRaises(IntakeError):
            Field(FieldState.UNKNOWN, None, Locator("message", "x"), uncertainty_flags=["CHECK"])

    def test_posting_and_approval_states_cannot_be_invented(self):
        for value in (True, None, 0, 1, "false"):
            with self.assertRaises(IntakeError):
                self.proposal(can_post=value)
        for state in ("APPROVED", "VERIFIED", "POSTED"):
            with self.assertRaises(IntakeError):
                self.proposal(review_state=state)

    def test_no_io_or_domain_posting_dependencies(self):
        import ast
        from pathlib import Path
        import fresko_universe.intake_contract as contract
        allowed = {"__future__", "collections", "dataclasses", "enum", "hashlib", "json", "re", "types"}
        for node in ast.walk(ast.parse(Path(contract.__file__).read_text())):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                imports = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module]
                self.assertTrue(all(name.split(".")[0] in allowed for name in imports))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotIn(node.func.id, {"open", "eval", "exec", "__import__"})

    def test_invalid_replay_inputs_rejected(self):
        from fresko_universe.intake_contract import compare_replay
        with self.assertRaises(IntakeError):
            compare_replay(self.proposal(), {})


if __name__ == "__main__":
    unittest.main()
