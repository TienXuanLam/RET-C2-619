# RET-C2-619 — Unit Tests: claim_normalize_service (PreProcessNode domain logic)

from src.services import claim_normalize_service


class TestValidateSchema:
    def test_valid_payload_passes(self):
        payload = {
            "claim_lines": [{"line_id": "L01", "claimed_amount": 1000}],
            "agreement_summary": "x" * 250,
            "claim_receipt_date": "2026-07-01",
        }
        assert claim_normalize_service.validate_schema(payload, max_claim_lines=30) == []

    def test_missing_claim_lines_rejected(self):
        errors = claim_normalize_service.validate_schema({}, max_claim_lines=30)
        assert len(errors) == 1
        assert "claim_lines" in errors[0]

    def test_negative_claimed_amount_rejected(self):
        payload = {
            "claim_lines": [{"line_id": "L01", "claimed_amount": -100}],
            "agreement_summary": "x" * 250,
            "claim_receipt_date": "2026-07-01",
        }
        errors = claim_normalize_service.validate_schema(payload, max_claim_lines=30)
        assert any("claimed_amount" in e for e in errors)

    def test_missing_line_id_rejected(self):
        payload = {
            "claim_lines": [{"claimed_amount": 100}],
            "agreement_summary": "x" * 250,
            "claim_receipt_date": "2026-07-01",
        }
        errors = claim_normalize_service.validate_schema(payload, max_claim_lines=30)
        assert any("line_id" in e for e in errors)

    def test_empty_agreement_summary_rejected(self):
        payload = {
            "claim_lines": [{"line_id": "L01", "claimed_amount": 100}],
            "agreement_summary": "",
            "claim_receipt_date": "2026-07-01",
        }
        errors = claim_normalize_service.validate_schema(payload, max_claim_lines=30)
        assert any("agreement_summary" in e for e in errors)

    def test_unparseable_date_rejected(self):
        payload = {
            "claim_lines": [{"line_id": "L01", "claimed_amount": 100}],
            "agreement_summary": "x" * 250,
            "claim_receipt_date": "not-a-date",
        }
        errors = claim_normalize_service.validate_schema(payload, max_claim_lines=30)
        assert any("claim_receipt_date" in e for e in errors)

    def test_claim_lines_over_cap_rejected(self):
        payload = {
            "claim_lines": [{"line_id": f"L{i}", "claimed_amount": 1} for i in range(31)],
            "agreement_summary": "x" * 250,
            "claim_receipt_date": "2026-07-01",
        }
        errors = claim_normalize_service.validate_schema(payload, max_claim_lines=30)
        assert any("exceeds the maximum" in e for e in errors)

    def _base_payload(self, **overrides):
        payload = {
            "claim_lines": [{"line_id": "L01", "claimed_amount": 1000}],
            "agreement_summary": "x" * 250,
            "claim_receipt_date": "2026-07-01",
        }
        payload.update(overrides)
        return payload

    # T1-02/T2-01: payment_due_days flows unguarded into
    # compute_deadline()'s int(payment_due_days) if not validated here.
    def test_payment_due_days_non_numeric_string_rejected(self):
        errors = claim_normalize_service.validate_schema(
            self._base_payload(payment_due_days="not-a-number"), max_claim_lines=30
        )
        assert any("payment_due_days" in e for e in errors)

    def test_payment_due_days_float_rejected(self):
        errors = claim_normalize_service.validate_schema(
            self._base_payload(payment_due_days=60.5), max_claim_lines=30
        )
        assert any("payment_due_days" in e for e in errors)

    def test_payment_due_days_bool_rejected(self):
        errors = claim_normalize_service.validate_schema(
            self._base_payload(payment_due_days=True), max_claim_lines=30
        )
        assert any("payment_due_days" in e for e in errors)

    def test_payment_due_days_negative_rejected(self):
        errors = claim_normalize_service.validate_schema(
            self._base_payload(payment_due_days=-1), max_claim_lines=30
        )
        assert any("payment_due_days" in e for e in errors)

    def test_payment_due_days_zero_accepted(self):
        errors = claim_normalize_service.validate_schema(
            self._base_payload(payment_due_days=0), max_claim_lines=30
        )
        assert errors == []

    def test_payment_due_days_sixty_accepted(self):
        errors = claim_normalize_service.validate_schema(
            self._base_payload(payment_due_days=60), max_claim_lines=30
        )
        assert errors == []

    def test_payment_due_days_upper_bound_accepted(self):
        errors = claim_normalize_service.validate_schema(
            self._base_payload(payment_due_days=365), max_claim_lines=30
        )
        assert errors == []

    def test_payment_due_days_over_upper_bound_rejected(self):
        errors = claim_normalize_service.validate_schema(
            self._base_payload(payment_due_days=366), max_claim_lines=30
        )
        assert any("payment_due_days" in e for e in errors)

    def test_payment_due_days_absent_defaults_ok(self):
        # payment_due_days is optional at the schema-validation layer — the
        # node layer (PreProcessNode) supplies the default of 60 before
        # calling compute_deadline().
        errors = claim_normalize_service.validate_schema(self._base_payload(), max_claim_lines=30)
        assert errors == []


class TestNormalizeClaimLines:
    def test_canonical_type_preserved(self):
        result = claim_normalize_service.normalize_claim_lines(
            [{"line_id": "L01", "type": "volume_rebate", "claimed_amount": 100}]
        )
        assert result[0]["type"] == "volume_rebate"

    def test_unknown_type_mapped_to_other(self):
        result = claim_normalize_service.normalize_claim_lines(
            [{"line_id": "L01", "type": "unknown_bespoke_type", "claimed_amount": 100}]
        )
        assert result[0]["type"] == "other"

    def test_missing_type_defaults_to_other(self):
        result = claim_normalize_service.normalize_claim_lines(
            [{"line_id": "L01", "claimed_amount": 100}]
        )
        assert result[0]["type"] == "other"


class TestComputeDeadline:
    def test_deadline_is_receipt_plus_due_days(self):
        deadline, _ = claim_normalize_service.compute_deadline("2026-01-01", 60)
        assert deadline == "2026-03-02"

    def test_urgency_flag_true_when_deadline_near(self):
        from datetime import date, timedelta

        near_receipt = (date.today() - timedelta(days=55)).isoformat()
        _, urgency = claim_normalize_service.compute_deadline(near_receipt, 60)
        assert urgency is True

    def test_urgency_flag_false_when_deadline_far(self):
        from datetime import date

        _, urgency = claim_normalize_service.compute_deadline(date.today().isoformat(), 60)
        assert urgency is False


class TestCapAgreementSummary:
    def test_short_summary_unchanged(self):
        text = "short agreement text"
        assert claim_normalize_service.cap_agreement_summary(text, max_tokens=8000) == text

    def test_long_summary_truncated(self):
        text = "x" * 100000
        capped = claim_normalize_service.cap_agreement_summary(text, max_tokens=8000)
        assert len(capped) == 8000 * 4
