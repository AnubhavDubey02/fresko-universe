"""Adversarial checks for certainty and source labelling in the offline corpus."""

import copy
import unittest

import validate_phase2_readiness_fixtures as validator


class ReadinessContractTests(unittest.TestCase):
    def setUp(self):
        self.corpus = validator.load_json(validator.FIXTURE_DIR / "cases.json")
        self.cases = {case["id"]: copy.deepcopy(case) for case in self.corpus["cases"]}

    def test_reviewed_corpus_passes(self):
        for case in self.cases.values():
            validator.validate_case(case, self.corpus["confidence_vocabulary"])
        validator.validate_semantics(self.cases)

    def test_condensed_summary_cannot_claim_raw_text(self):
        case = self.cases["ambiguous-amendment-add-10"]
        case["source"]["raw_text"] = case["source"]["source_summary"]
        with self.assertRaisesRegex(ValueError, "must not be labelled raw_text"):
            validator.validate_case(case, self.corpus["confidence_vocabulary"])

    def test_redelivery_cannot_confirm_buyer(self):
        self.cases["provider-redelivery-same-message"]["expected"]["identity_match_confidence"] = "CONFIRMED"
        with self.assertRaisesRegex(ValueError, "does not establish buyer identity"):
            validator.validate_semantics(self.cases)

    def test_authorization_cannot_establish_settlement(self):
        self.cases["bank-authorization-not-cleared-receipt"]["expected"]["settlement_status"] = "CLEARED"
        with self.assertRaisesRegex(ValueError, "does not establish settlement outcome"):
            validator.validate_semantics(self.cases)

    def test_archive_presence_cannot_confirm_capture(self):
        self.cases["same-timestamp-attachment-records"]["expected"]["capture_status"] = "CAPTURED"
        with self.assertRaisesRegex(ValueError, "does not prove successful application capture"):
            validator.validate_semantics(self.cases)

    def test_amendment_cannot_invent_parent(self):
        self.cases["ambiguous-amendment-add-10"]["expected"]["parent_order"] = "nearby-order"
        with self.assertRaisesRegex(ValueError, "parent_order UNKNOWN"):
            validator.validate_semantics(self.cases)


if __name__ == "__main__":
    unittest.main()
