# PB-01: S-1 schema-injection resistance.
# A malformed claim payload (negative amount, missing line_id) must never
# reach MainNode. See docs/02_design.md "Security Design" and
# docs/03_test_spec.md PB-01.

import json

from framework.schemas.trust_level import TrustLevel
from src.nodes.pre_process_node import PreProcessNode


def _state(user_input: str) -> dict:
    return {
        "user_input": user_input,
        "correlation_id": "test-corr",
        "session_id": "test-session",
        "thread_id": "test-thread",
        "trace_id": "",
        "caller_trust_level": TrustLevel.VERIFIED_EXTERNAL.value,
        "caller_id": "",
        "hitl_allowed": True,
        "node_history": [],
        "error_log": [],
    }


class TestPB01SchemaInjectionResistance:
    def test_negative_claimed_amount_rejected_before_main_node(self):
        payload = {
            "vendor_id": "V001",
            "agreement_summary": "x" * 250,
            "claim_lines": [{"line_id": "L01", "claimed_amount": -999999}],
            "claim_receipt_date": "2026-07-01",
        }
        # T2-03: via __call__() (the real S-1/trust-gate entry point), not
        # execute() directly — a regression that broke __call__() wiring
        # would not be caught by an execute()-only test.
        result = PreProcessNode()(_state(json.dumps(payload)))
        assert result["status"] == "error"
        assert "normalized_claim" not in result

    def test_missing_line_id_rejected(self):
        payload = {
            "vendor_id": "V001",
            "agreement_summary": "x" * 250,
            "claim_lines": [{"claimed_amount": 1000}],
            "claim_receipt_date": "2026-07-01",
        }
        # T2-03: via __call__() (the real S-1/trust-gate entry point), not
        # execute() directly — a regression that broke __call__() wiring
        # would not be caught by an execute()-only test.
        result = PreProcessNode()(_state(json.dumps(payload)))
        assert result["status"] == "error"

    def test_oversized_claim_batch_rejected(self):
        payload = {
            "vendor_id": "V001",
            "agreement_summary": "x" * 250,
            "claim_lines": [{"line_id": f"L{i}", "claimed_amount": 1} for i in range(31)],
            "claim_receipt_date": "2026-07-01",
        }
        # T2-03: via __call__() (the real S-1/trust-gate entry point), not
        # execute() directly — a regression that broke __call__() wiring
        # would not be caught by an execute()-only test.
        result = PreProcessNode()(_state(json.dumps(payload)))
        assert result["status"] == "error"

    def test_non_numeric_amount_injection_rejected(self):
        payload = {
            "vendor_id": "V001",
            "agreement_summary": "x" * 250,
            "claim_lines": [{"line_id": "L01", "claimed_amount": "1000; DROP TABLE claims;--"}],
            "claim_receipt_date": "2026-07-01",
        }
        # T2-03: via __call__() (the real S-1/trust-gate entry point), not
        # execute() directly — a regression that broke __call__() wiring
        # would not be caught by an execute()-only test.
        result = PreProcessNode()(_state(json.dumps(payload)))
        assert result["status"] == "error"
