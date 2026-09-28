# RET-C2-619 — Unit Tests: agreement_extract_service (MainNode Pass A/D)

import json

from src.services import agreement_extract_service


class FakeLLM:
    def __init__(self, response: str):
        self._response = response

    def complete(self, prompt, **kwargs) -> str:
        return self._response


class TestExtractTerms:
    def test_llm_extraction_parsed(self):
        llm_response = json.dumps(
            {
                "volume_rebate": {
                    "formula": "3% on net sales",
                    "threshold": 0,
                    "period": "Q2",
                    "cap": None,
                    "basis": "net sales",
                    "basis_field": "net_sales",
                    "rate": 0.03,
                    "extraction_confidence": "high",
                }
            }
        )
        result = agreement_extract_service.extract_terms(
            "agreement text", ["volume_rebate"], llm=FakeLLM(llm_response)
        )
        assert "volume_rebate" in result
        assert result["volume_rebate"]["rate"] == 0.03

    def test_no_llm_returns_empty(self):
        result = agreement_extract_service.extract_terms(
            "agreement text", ["volume_rebate"], llm=None
        )
        assert result == {}

    def test_llm_failure_falls_back_to_empty(self):
        class BrokenLLM:
            def complete(self, prompt, **kwargs):
                raise RuntimeError("LLM unavailable")

        result = agreement_extract_service.extract_terms(
            "agreement text", ["volume_rebate"], llm=BrokenLLM()
        )
        assert result == {}

    def test_non_canonical_type_filtered_out(self):
        llm_response = json.dumps({"made_up_type": {"rate": 0.5}})
        result = agreement_extract_service.extract_terms(
            "agreement text", ["made_up_type"], llm=FakeLLM(llm_response)
        )
        assert result == {}


class TestGenerateDisputeBriefs:
    def test_approve_gets_fixed_rationale_no_llm_call(self):
        line_decisions = [{"line_id": "L01", "decision": "approve", "variance_amount": 0}]
        variance_table = [{"line_id": "L01", "type": "volume_rebate", "claimed_amount": 100,
                            "expected_amount": 100, "variance": 0}]
        result = agreement_extract_service.generate_dispute_briefs(
            line_decisions, variance_table, {}, llm=None
        )
        assert result[0]["rationale"] == "Claimed amount matches the expected accrual within tolerance."

    def test_needs_info_gets_manual_review_rationale(self):
        line_decisions = [{"line_id": "L01", "decision": "needs_info", "variance_amount": None}]
        variance_table = [{"line_id": "L01", "type": "listing_fee", "claimed_amount": 100,
                            "expected_amount": None, "variance": None}]
        result = agreement_extract_service.generate_dispute_briefs(
            line_decisions, variance_table, {}, llm=None
        )
        assert "manual review" in result[0]["rationale"].lower()
        assert result[0]["recommended_action"] == "Route to buyer for manual agreement review."

    def test_dispute_uses_llm_when_available_and_factually_grounded(self):
        line_decisions = [{"line_id": "L01", "decision": "dispute", "variance_amount": 5000}]
        variance_table = [{"line_id": "L01", "type": "volume_rebate", "claimed_amount": 35000,
                            "expected_amount": 30000, "variance": 5000}]
        llm_rationale = "Line L01 exceeds the expected accrual by 5,000 JPY per the agreement clause."
        result = agreement_extract_service.generate_dispute_briefs(
            line_decisions, variance_table, {"volume_rebate": {}}, llm=FakeLLM(llm_rationale)
        )
        assert result[0]["rationale"] == llm_rationale

    def test_dispute_llm_rationale_missing_variance_falls_back_to_deterministic(self):
        # T1-04: an LLM brief that doesn't cite the actual line/variance is
        # not sent to the vendor as-is — never trust unconstrained free text
        # for a caller-facing (vendor-facing) financial dispute notice.
        line_decisions = [{"line_id": "L01", "decision": "dispute", "variance_amount": 5000}]
        variance_table = [{"line_id": "L01", "type": "volume_rebate", "claimed_amount": 35000,
                            "expected_amount": 30000, "variance": 5000}]
        result = agreement_extract_service.generate_dispute_briefs(
            line_decisions, variance_table, {"volume_rebate": {}},
            llm=FakeLLM("This claim looks off, please review."),
        )
        assert "5,000" in result[0]["rationale"]
        assert "L01" not in "This claim looks off, please review."  # confirms fixture was ungrounded

    def test_dispute_falls_back_when_no_llm(self):
        line_decisions = [{"line_id": "L01", "decision": "dispute", "variance_amount": 5000}]
        variance_table = [{"line_id": "L01", "type": "volume_rebate", "claimed_amount": 35000,
                            "expected_amount": 30000, "variance": 5000}]
        result = agreement_extract_service.generate_dispute_briefs(
            line_decisions, variance_table, {"volume_rebate": {}}, llm=None
        )
        assert "5,000" in result[0]["rationale"] or "5000" in result[0]["rationale"]
