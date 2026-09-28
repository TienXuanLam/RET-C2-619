# RET-C2-619 — Unit Tests: PostProcessNode

import json

from framework.schemas.trust_level import TrustLevel
from src.nodes.post_process_node import PostProcessNode


def _base_state(**overrides) -> dict:
    state = {
        "vendor_id": "V001",
        "payment_deadline": "2026-08-30",
        "urgency_flag": False,
        "variance_table": json.dumps(
            [{"line_id": "L01", "type": "volume_rebate", "claimed_amount": 30000,
              "expected_amount": 30000, "variance": 0}]
        ),
        "line_decisions": json.dumps(
            [{"line_id": "L01", "decision": "approve", "variance_amount": 0,
              "rationale": "Claimed amount matches the expected accrual within tolerance.",
              "recommended_action": "Approve for payment."}]
        ),
        "compliance_flags": json.dumps([]),
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
    state.update(overrides)
    return state


class TestPostProcessNode:
    def setup_method(self):
        self.node = PostProcessNode()

    def test_success_path(self):
        result = self.node.execute(_base_state())
        assert result["status"] == "success"
        response = json.loads(result["result"])
        assert response["summary"]["total_approved"] == 30000
        assert "Vendor Rebate Reconciliation Report" in result["formatted_output"]

    def test_vendor_id_hashed_not_raw_in_audit_ref(self):
        result = self.node.execute(_base_state())
        response = json.loads(result["result"])
        assert response["audit_ref"] != "V001"
        assert len(response["audit_ref"]) == 16

    def test_back_margin_redacted_in_output(self):
        state = _base_state(
            line_decisions=json.dumps(
                [{"line_id": "L01", "decision": "dispute", "variance_amount": 5000,
                  "rationale": "Internal margin: 15% was used to compute this.",
                  "recommended_action": "Send dispute notice."}]
            )
        )
        result = self.node.execute(state)
        assert "15%" not in result["formatted_output"]
        assert "[redacted" in result["formatted_output"]

    def test_disclaimer_present_in_report(self):
        result = self.node.execute(_base_state())
        assert "informational only" in result["formatted_output"]

    def test_extra_security_gate_output_sanitizes_formatted_output(self):
        # Belt-and-suspenders: even if inline sanitization were skipped,
        # the S-3 hook independently re-scans formatted_output.
        result_dict = {"formatted_output": "margin: 25% leaked here"}
        sanitized = self.node._extra_security_gate_output(result_dict)
        assert "25%" not in sanitized["formatted_output"]


class TestPostProcessNodeTrustGate:
    def test_trust_gate_blocks_anonymous(self):
        node = PostProcessNode()
        state = _base_state()
        state["caller_trust_level"] = TrustLevel.ANONYMOUS.value
        result = node(state)
        assert result["status"] == "error"

    def test_trust_gate_allows_verified_external(self):
        node = PostProcessNode()
        state = _base_state()
        state["caller_trust_level"] = TrustLevel.VERIFIED_EXTERNAL.value
        result = node(state)
        assert result["status"] == "success"
