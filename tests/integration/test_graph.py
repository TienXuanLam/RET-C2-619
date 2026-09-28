# RET-C2-619 — Integration: full compiled-graph invocation.
# T2-05: PB-01/PB-02/PB-04's node-level tests never exercised the full
# compiled pipeline end-to-end (PreProcessNode -> MainNode -> PostProcessNode
# via agent.invoke()). This file closes that gap: valid claims must flow
# through to a rendered report, and invalid/malformed claims must never
# reach MainNode or PostProcessNode. See docs/02_design.md "Data Flow" and
# docs/03_test_spec.md.

import json

from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel

from src.graph.graph import RetailVendorRebateTradePromoReconciliationAgent


def _compiled_agent():
    agent = RetailVendorRebateTradePromoReconciliationAgent()
    agent.compile()
    return agent


def _ctx():
    return InvocationContext(session_id="test", caller_trust_level=TrustLevel.VERIFIED_EXTERNAL)


def _valid_payload(**overrides) -> dict:
    payload = {
        "vendor_id": "V001",
        "agreement_summary": "x" * 250,
        "claim_lines": [{"line_id": "L01", "type": "volume_rebate", "claimed_amount": 30000}],
        "actual_performance": {"net_sales": 1000000},
        "claim_receipt_date": "2026-07-01",
        "payment_due_days": 60,
    }
    payload.update(overrides)
    return payload


class TestFullPipelineValidClaim:
    def test_valid_claim_no_llm_resolves_needs_info_and_renders_report(self):
        # No LLM configured -> extract_terms() returns {} -> every line is
        # Needs-Info (never a fabricated Approve/Dispute) -> report still
        # renders successfully.
        agent = _compiled_agent()
        result = agent.invoke(json.dumps(_valid_payload()), ctx=_ctx())
        assert result["status"] == "success"
        assert "Vendor Rebate Reconciliation Report" in result["output"]
        assert "needs_info" in result["output"]

    def test_valid_claim_output_never_contains_plaintext_vendor_id(self):
        agent = _compiled_agent()
        result = agent.invoke(json.dumps(_valid_payload(vendor_id="ACME-CORP")), ctx=_ctx())
        assert "ACME-CORP" not in result["output"]

    def test_disclaimer_always_present_in_full_pipeline_output(self):
        agent = _compiled_agent()
        result = agent.invoke(json.dumps(_valid_payload()), ctx=_ctx())
        assert "Disclaimer" in result["output"] or "informational only" in result["output"]


class TestFullPipelineRejectsInvalidInputBeforeMainNode:
    def test_negative_claimed_amount_never_reaches_main_node(self):
        agent = _compiled_agent()
        payload = _valid_payload(
            claim_lines=[{"line_id": "L01", "claimed_amount": -999999}]
        )
        result = agent.invoke(json.dumps(payload), ctx=_ctx())
        assert result["status"] == "error"
        # MainNode would have produced a rendered Markdown report on success;
        # its absence confirms the pipeline never reached Pass A-D.
        assert "Vendor Rebate Reconciliation Report" not in (result.get("output") or "")

    def test_malformed_payment_due_days_never_reaches_main_node(self):
        # T1-02/T2-05 regression: the crash used to occur inside
        # PreProcessNode.execute() itself (compute_deadline()), so this also
        # proves the fix holds through the full compiled graph, not just the
        # node in isolation.
        agent = _compiled_agent()
        payload = _valid_payload(payment_due_days="not-a-number")
        result = agent.invoke(json.dumps(payload), ctx=_ctx())
        assert result["status"] == "error"
        assert "Traceback" not in json.dumps(result)

    def test_oversized_claim_batch_never_reaches_main_node(self):
        agent = _compiled_agent()
        payload = _valid_payload(
            claim_lines=[{"line_id": f"L{i}", "claimed_amount": 1} for i in range(31)]
        )
        result = agent.invoke(json.dumps(payload), ctx=_ctx())
        assert result["status"] == "error"

    def test_anonymous_caller_rejected_by_trust_gate(self):
        agent = _compiled_agent()
        result = agent.invoke(
            json.dumps(_valid_payload()),
            ctx=InvocationContext(session_id="test", caller_trust_level=TrustLevel.ANONYMOUS),
        )
        assert result["status"] == "error"


class TestFullPipelineTermValidation:
    def test_untrustworthy_llm_extraction_still_resolves_needs_info_end_to_end(self):
        # Even with an LLM configured, a low/medium-confidence or malformed
        # extraction must never produce Approve/Dispute anywhere in the full
        # pipeline output — not just at the accrual_compliance_service unit
        # level (T1-01/T2-02).
        class _MediumConfidenceLLM:
            def complete(self, messages: list, **kwargs) -> dict:
                prompt = messages[0]["content"] if messages else ""
                if "Extract the rebate" in prompt:
                    return {
                        "content": json.dumps(
                            {
                                "volume_rebate": {
                                    "formula": "3% on net sales",
                                    "threshold": 0,
                                    "period": "Q2",
                                    "cap": None,
                                    "basis": "net sales",
                                    "basis_field": "net_sales",
                                    "rate": 0.03,
                                    "extraction_confidence": "medium",
                                }
                            }
                        )
                    }
                return {"content": "Manual review recommended."}

        agent = RetailVendorRebateTradePromoReconciliationAgent(config={"llm": _MediumConfidenceLLM()})
        agent.compile()
        result = agent.invoke(json.dumps(_valid_payload()), ctx=_ctx())
        assert result["status"] == "success"
        assert "| L01 | volume_rebate |" in result["output"]
        assert "needs_info" in result["output"]
