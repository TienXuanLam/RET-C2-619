# PB-02: Accrual math is deterministic arithmetic, never LLM-influenced.
# See docs/02_design.md "Design Decision Record" and docs/03_test_spec.md PB-02.

import inspect

from src.services import accrual_compliance_service


class TestPB02DeterministicAccrualMath:
    def test_validate_accrual_signature_has_no_llm_parameter(self):
        # The function that produces Approve/Dispute/Needs-Info must not be
        # able to accept an LLM object at all — this is a structural
        # guarantee, not just a convention.
        sig = inspect.signature(accrual_compliance_service.validate_accrual)
        assert "llm" not in sig.parameters

    def test_check_timeline_signature_has_no_llm_parameter(self):
        sig = inspect.signature(accrual_compliance_service.check_timeline)
        assert "llm" not in sig.parameters

    def test_repeated_calls_produce_identical_output(self):
        claim = [{"line_id": "L01", "type": "volume_rebate", "claimed_amount": 30000}]
        term_extracts = {
            "volume_rebate": {
                "rate": 0.03,
                "basis_field": "net_sales",
                "threshold": 0,
                "cap": None,
                "extraction_confidence": "high",
            }
        }
        actual_performance = {"net_sales": 1000000}

        results = [
            accrual_compliance_service.validate_accrual(claim, term_extracts, actual_performance)
            for _ in range(5)
        ]
        assert all(r == results[0] for r in results)

    def test_low_confidence_never_produces_approve_or_dispute(self):
        claim = [{"line_id": "L01", "type": "volume_rebate", "claimed_amount": 30000}]
        term_extracts = {
            "volume_rebate": {
                "rate": 0.03,
                "basis_field": "net_sales",
                "threshold": 0,
                "cap": None,
                "extraction_confidence": "low",
            }
        }
        _, line_decisions = accrual_compliance_service.validate_accrual(
            claim, term_extracts, {"net_sales": 1000000}
        )
        assert line_decisions[0]["decision"] == "needs_info"

    # T1-01/T2-02: adversarial term_extracts — a merely "medium"-confidence
    # or structurally malformed LLM extraction must never drive an
    # Approve/Dispute decision. Every case here must resolve to needs_info.
    def _claim(self):
        return [{"line_id": "L01", "type": "volume_rebate", "claimed_amount": 30000}]

    def _decision_for(self, terms):
        _, line_decisions = accrual_compliance_service.validate_accrual(
            self._claim(), {"volume_rebate": terms}, {"net_sales": 1000000}
        )
        return line_decisions[0]["decision"]

    def test_medium_confidence_never_produces_approve_or_dispute(self):
        terms = {
            "rate": 0.03, "basis_field": "net_sales", "threshold": 0, "cap": None,
            "extraction_confidence": "medium",
        }
        assert self._decision_for(terms) == "needs_info"

    def test_missing_confidence_field_never_produces_approve_or_dispute(self):
        terms = {"rate": 0.03, "basis_field": "net_sales", "threshold": 0, "cap": None}
        assert self._decision_for(terms) == "needs_info"

    def test_unrecognized_confidence_value_never_produces_approve_or_dispute(self):
        terms = {
            "rate": 0.03, "basis_field": "net_sales", "threshold": 0, "cap": None,
            "extraction_confidence": "very_high",
        }
        assert self._decision_for(terms) == "needs_info"

    def test_unallowlisted_basis_field_never_produces_approve_or_dispute(self):
        terms = {
            "rate": 0.03, "basis_field": "gross_margin_internal", "threshold": 0, "cap": None,
            "extraction_confidence": "high",
        }
        assert self._decision_for(terms) == "needs_info"

    def test_non_numeric_rate_never_produces_approve_or_dispute(self):
        terms = {
            "rate": "three percent", "basis_field": "net_sales", "threshold": 0, "cap": None,
            "extraction_confidence": "high",
        }
        assert self._decision_for(terms) == "needs_info"

    def test_negative_rate_never_produces_approve_or_dispute(self):
        terms = {
            "rate": -0.03, "basis_field": "net_sales", "threshold": 0, "cap": None,
            "extraction_confidence": "high",
        }
        assert self._decision_for(terms) == "needs_info"

    def test_bool_rate_never_produces_approve_or_dispute(self):
        # bool is technically an int subclass in Python — must be excluded.
        terms = {
            "rate": True, "basis_field": "net_sales", "threshold": 0, "cap": None,
            "extraction_confidence": "high",
        }
        assert self._decision_for(terms) == "needs_info"

    def test_non_numeric_cap_never_produces_approve_or_dispute(self):
        terms = {
            "rate": 0.03, "basis_field": "net_sales", "threshold": 0, "cap": "unlimited",
            "extraction_confidence": "high",
        }
        assert self._decision_for(terms) == "needs_info"

    def test_non_dict_terms_never_produces_approve_or_dispute(self):
        _, line_decisions = accrual_compliance_service.validate_accrual(
            self._claim(), {"volume_rebate": "not a dict"}, {"net_sales": 1000000}
        )
        assert line_decisions[0]["decision"] == "needs_info"
