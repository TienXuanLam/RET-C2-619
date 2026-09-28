# RET-C2-619 — Unit Tests: MainNode (Pass A-D dispatcher)

import json

from framework.schemas.trust_level import TrustLevel
from src.nodes.main_node import MainNode


class FakeLLM:
    def __init__(self, extraction_response: str, brief_response: str = "LLM dispute rationale."):
        self._extraction_response = extraction_response
        self._brief_response = brief_response

    def complete(self, messages, **kwargs) -> dict:
        prompt = messages[0]["content"] if messages else ""
        if "Respond with ONLY a JSON object" in prompt:
            return {"content": self._extraction_response}
        return {"content": self._brief_response}


def _base_state(**overrides) -> dict:
    state = {
        "normalized_claim": json.dumps(
            [{"line_id": "L01", "type": "volume_rebate", "claimed_amount": 30000,
              "period": "Q2", "basis": ""}]
        ),
        "actual_performance": json.dumps({"net_sales": 1000000}),
        "agreement_summary": "3% rebate on net sales.",
        "claim_receipt_date": "2026-07-01",
        "payment_deadline": "2026-08-30",
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


_EXTRACTION_RESPONSE = json.dumps(
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


class TestMainNode:
    def test_success_path_with_llm(self):
        node = MainNode(llm=FakeLLM(_EXTRACTION_RESPONSE))
        result = node.execute(_base_state())
        assert result["status"] == "success"
        line_decisions = json.loads(result["line_decisions"])
        assert line_decisions[0]["decision"] == "approve"

    def test_no_llm_configured_falls_back_to_needs_info(self):
        node = MainNode(llm=None)
        result = node.execute(_base_state())
        line_decisions = json.loads(result["line_decisions"])
        assert line_decisions[0]["decision"] == "needs_info"
        assert result["status"] == "success"

    def test_compliance_flag_emitted_on_statutory_breach(self):
        node = MainNode(llm=FakeLLM(_EXTRACTION_RESPONSE))
        state = _base_state(payment_deadline="2026-09-15")
        result = node.execute(state)
        flags = json.loads(result["compliance_flags"])
        assert len(flags) == 1
        assert flags[0]["type"] == "下請法Article4"

    def test_no_compliance_flag_within_statutory_window(self):
        node = MainNode(llm=FakeLLM(_EXTRACTION_RESPONSE))
        result = node.execute(_base_state())
        flags = json.loads(result["compliance_flags"])
        assert flags == []


class TestMainNodeTrustGate:
    def test_trust_gate_blocks_anonymous(self):
        node = MainNode(llm=FakeLLM(_EXTRACTION_RESPONSE))
        state = _base_state()
        state["caller_trust_level"] = TrustLevel.ANONYMOUS.value
        result = node(state)
        assert result["status"] == "error"

    def test_trust_gate_allows_verified_external(self):
        node = MainNode(llm=FakeLLM(_EXTRACTION_RESPONSE))
        state = _base_state()
        state["caller_trust_level"] = TrustLevel.VERIFIED_EXTERNAL.value
        result = node(state)
        assert result["status"] == "success"
