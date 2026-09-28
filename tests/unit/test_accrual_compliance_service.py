# RET-C2-619 — Unit Tests: accrual_compliance_service (MainNode Pass B/C)
# Most security/correctness-critical module — see docs/02_design.md Risks #1, #3.
# Accrual math must be deterministic arithmetic, never LLM-generated.

from src.services import accrual_compliance_service

_TERMS_VOLUME_REBATE = {
    "rate": 0.03,
    "basis_field": "net_sales",
    "threshold": 0,
    "cap": None,
    "extraction_confidence": "high",
}


class TestValidateAccrual:
    def test_approve_within_tolerance(self):
        # expected = 0.03 * 1_000_000 = 30_000; claimed matches exactly
        claim = [{"line_id": "L01", "type": "volume_rebate", "claimed_amount": 30000}]
        term_extracts = {"volume_rebate": _TERMS_VOLUME_REBATE}
        actual_performance = {"net_sales": 1000000}

        variance_table, line_decisions = accrual_compliance_service.validate_accrual(
            claim, term_extracts, actual_performance
        )
        assert line_decisions[0]["decision"] == "approve"
        assert variance_table[0]["expected_amount"] == 30000

    def test_dispute_over_tolerance(self):
        # expected = 30_000; claimed = 90_000 -> far over tolerance
        claim = [{"line_id": "L01", "type": "volume_rebate", "claimed_amount": 90000}]
        term_extracts = {"volume_rebate": _TERMS_VOLUME_REBATE}
        actual_performance = {"net_sales": 1000000}

        _, line_decisions = accrual_compliance_service.validate_accrual(
            claim, term_extracts, actual_performance
        )
        assert line_decisions[0]["decision"] == "dispute"
        assert line_decisions[0]["variance_amount"] == 60000

    def test_needs_info_when_clause_not_found(self):
        claim = [{"line_id": "L01", "type": "listing_fee", "claimed_amount": 5000}]
        term_extracts = {}  # no listing_fee terms extracted
        actual_performance = {"net_sales": 1000000}

        _, line_decisions = accrual_compliance_service.validate_accrual(
            claim, term_extracts, actual_performance
        )
        assert line_decisions[0]["decision"] == "needs_info"
        assert line_decisions[0]["variance_amount"] is None

    def test_needs_info_when_low_confidence(self):
        # Risk #1: a low-confidence extraction must never drive Approve/Dispute
        claim = [{"line_id": "L01", "type": "volume_rebate", "claimed_amount": 30000}]
        low_confidence_terms = {**_TERMS_VOLUME_REBATE, "extraction_confidence": "low"}
        term_extracts = {"volume_rebate": low_confidence_terms}
        actual_performance = {"net_sales": 1000000}

        _, line_decisions = accrual_compliance_service.validate_accrual(
            claim, term_extracts, actual_performance
        )
        assert line_decisions[0]["decision"] == "needs_info"

    def test_cap_applied(self):
        capped_terms = {**_TERMS_VOLUME_REBATE, "cap": 10000}
        claim = [{"line_id": "L01", "type": "volume_rebate", "claimed_amount": 10000}]
        term_extracts = {"volume_rebate": capped_terms}
        actual_performance = {"net_sales": 1000000}  # uncapped would be 30_000

        variance_table, _ = accrual_compliance_service.validate_accrual(
            claim, term_extracts, actual_performance
        )
        assert variance_table[0]["expected_amount"] == 10000

    def test_math_is_deterministic_no_llm_dependency(self):
        # PB-02: repeated calls with identical input must produce identical output —
        # validate_accrual() takes no llm argument anywhere in its signature.
        claim = [{"line_id": "L01", "type": "volume_rebate", "claimed_amount": 30000}]
        term_extracts = {"volume_rebate": _TERMS_VOLUME_REBATE}
        actual_performance = {"net_sales": 1000000}

        result_1 = accrual_compliance_service.validate_accrual(claim, term_extracts, actual_performance)
        result_2 = accrual_compliance_service.validate_accrual(claim, term_extracts, actual_performance)
        assert result_1 == result_2


class TestCheckTimeline:
    def test_within_statutory_window_no_flag(self):
        flags = accrual_compliance_service.check_timeline(
            payment_deadline="2026-08-30", claim_receipt_date="2026-07-01"
        )
        assert flags == []

    def test_statutory_breach_flagged(self):
        flags = accrual_compliance_service.check_timeline(
            payment_deadline="2026-09-15", claim_receipt_date="2026-07-01"
        )
        assert len(flags) == 1
        assert flags[0]["type"] == "下請法Article4"
        assert flags[0]["informational"] is True

    def test_flag_is_always_informational(self):
        flags = accrual_compliance_service.check_timeline(
            payment_deadline="2026-12-31", claim_receipt_date="2026-01-01"
        )
        assert all(f["informational"] is True for f in flags)
