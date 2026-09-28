# RET-C2-619 — Unit Tests: PreProcessNode

import json

from framework.schemas.trust_level import TrustLevel
from src.nodes.pre_process_node import PreProcessNode

_VALID_PAYLOAD = {
    "vendor_id": "V001",
    "agreement_summary": "x" * 250,
    "claim_lines": [{"line_id": "L01", "type": "volume_rebate", "claimed_amount": 30000}],
    "actual_performance": {"net_sales": 1000000},
    "claim_receipt_date": "2026-07-01",
    "payment_due_days": 60,
}


def _base_state(user_input: str = "") -> dict:
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


class TestPreProcessNode:
    def setup_method(self):
        self.node = PreProcessNode()

    def test_valid_payload_success(self):
        state = _base_state(json.dumps(_VALID_PAYLOAD))
        result = self.node.execute(state)
        assert result["status"] == "success"
        assert result["vendor_id"] == "V001"
        assert json.loads(result["normalized_claim"])[0]["type"] == "volume_rebate"
        assert result["payment_deadline"] == "2026-08-30"

    def test_empty_input_returns_error(self):
        state = _base_state("")
        result = self.node.execute(state)
        assert result["status"] == "error"
        assert len(result["error_log"]) > 0

    def test_invalid_json_returns_error(self):
        state = _base_state("not json")
        result = self.node.execute(state)
        assert result["status"] == "error"
        assert "not valid JSON" in result["error_log"][0]

    def test_negative_claimed_amount_returns_error(self):
        payload = {**_VALID_PAYLOAD, "claim_lines": [{"line_id": "L01", "claimed_amount": -1}]}
        state = _base_state(json.dumps(payload))
        result = self.node.execute(state)
        assert result["status"] == "error"

    def test_claim_receipt_date_passed_through(self):
        state = _base_state(json.dumps(_VALID_PAYLOAD))
        result = self.node.execute(state)
        assert result["claim_receipt_date"] == "2026-07-01"

    def test_non_numeric_payment_due_days_rejected_cleanly(self):
        # T1-02/T2-01 regression: this used to reach
        # claim_normalize_service.compute_deadline()'s int(payment_due_days)
        # unguarded, producing a hard ValueError whose full Python traceback
        # leaked into error_log via BaseNode.__call__()'s generic exception
        # handler. validate_schema() must now catch it first, as a clean
        # domain error with no traceback text.
        payload = {**_VALID_PAYLOAD, "payment_due_days": "not-a-number"}
        state = _base_state(json.dumps(payload))
        result = self.node(state)  # via __call__(), the real entry point
        assert result["status"] == "error"
        assert "payment_due_days" in result["error_log"][0]
        assert "Traceback" not in result["error_log"][0]

    def test_negative_payment_due_days_rejected(self):
        payload = {**_VALID_PAYLOAD, "payment_due_days": -5}
        state = _base_state(json.dumps(payload))
        result = self.node(state)
        assert result["status"] == "error"


class TestPreProcessNodeSecurityGateInput:
    def test_short_raw_input_flagged(self):
        node = PreProcessNode()
        state = _base_state("short")
        result = node._extra_security_gate_input(state)
        assert result["_raw_input_suspiciously_short"] is True

    def test_normal_length_input_not_flagged(self):
        node = PreProcessNode()
        state = _base_state(json.dumps(_VALID_PAYLOAD))
        result = node._extra_security_gate_input(state)
        assert "_raw_input_suspiciously_short" not in result

    def test_hook_does_not_raise_on_empty_input(self):
        node = PreProcessNode()
        state = _base_state("")
        result = node._extra_security_gate_input(state)
        assert result is not None


class TestPreProcessNodeTrustGate:
    def test_trust_gate_blocks_anonymous(self):
        node = PreProcessNode()
        state = _base_state(json.dumps(_VALID_PAYLOAD))
        state["caller_trust_level"] = TrustLevel.ANONYMOUS.value
        result = node(state)  # via __call__, not execute()
        assert result["status"] == "error"

    def test_trust_gate_allows_verified_external(self):
        node = PreProcessNode()
        state = _base_state(json.dumps(_VALID_PAYLOAD))
        state["caller_trust_level"] = TrustLevel.VERIFIED_EXTERNAL.value
        result = node(state)
        assert result["status"] == "success"
