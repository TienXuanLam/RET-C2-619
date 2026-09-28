# PB-03: 下請法 Article 4 compliance flags are always informational — never a
# binding legal ruling. See docs/02_design.md "Risk mitigations" Risk #3 and
# docs/03_test_spec.md PB-03.

import json

from framework.schemas.trust_level import TrustLevel
from src.nodes.main_node import MainNode
from src.nodes.post_process_node import PostProcessNode
from src.services import accrual_compliance_service, report_render_service


class FakeLLM:
    def complete(self, prompt, **kwargs) -> str:
        return "{}"


class TestPB03InformationalComplianceFlags:
    def test_check_timeline_flag_always_informational(self):
        flags = accrual_compliance_service.check_timeline(
            payment_deadline="2026-09-30", claim_receipt_date="2026-07-01"
        )
        assert len(flags) == 1
        assert flags[0]["informational"] is True

    def test_main_node_output_flags_always_informational(self):
        state = {
            "normalized_claim": json.dumps(
                [{"line_id": "L01", "type": "volume_rebate", "claimed_amount": 1000}]
            ),
            "actual_performance": json.dumps({"net_sales": 100}),
            "agreement_summary": "text",
            "claim_receipt_date": "2026-01-01",
            "payment_deadline": "2026-12-31",  # far beyond statutory window
            "correlation_id": "c",
            "session_id": "s",
            "thread_id": "t",
            "trace_id": "",
            "caller_trust_level": TrustLevel.VERIFIED_EXTERNAL.value,
            "caller_id": "",
            "hitl_allowed": True,
            "node_history": [],
            "error_log": [],
        }
        result = MainNode(llm=FakeLLM()).execute(state)
        flags = json.loads(result["compliance_flags"])
        assert all(f["informational"] is True for f in flags)

    def test_report_disclaimer_present_verbatim(self):
        output = report_render_service.render_markdown_report(
            vendor_id="V001",
            payment_deadline="2026-09-30",
            urgency_flag=False,
            variance_table=[],
            line_decisions=[],
            compliance_flags=[{"type": "下請法Article4", "detail": "x", "informational": True}],
            summary={"total_approved": 0, "total_disputed": 0, "total_needs_info": 0},
        )
        assert report_render_service.DISCLAIMER_EN in output
        assert report_render_service.DISCLAIMER_JP in output

    def test_post_process_node_never_omits_disclaimer(self):
        state = {
            "vendor_id": "V001",
            "payment_deadline": "2026-09-30",
            "urgency_flag": False,
            "variance_table": json.dumps([]),
            "line_decisions": json.dumps([]),
            "compliance_flags": json.dumps(
                [{"type": "下請法Article4", "detail": "breach", "informational": True}]
            ),
            "correlation_id": "c",
            "session_id": "s",
            "thread_id": "t",
            "trace_id": "",
            "caller_trust_level": TrustLevel.VERIFIED_EXTERNAL.value,
            "caller_id": "",
            "hitl_allowed": True,
            "node_history": [],
            "error_log": [],
        }
        result = PostProcessNode().execute(state)
        assert "informational only" in result["formatted_output"]
