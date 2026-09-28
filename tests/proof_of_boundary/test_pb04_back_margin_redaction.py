# PB-04: back-margin / internal-pricing data inferred from agreement_summary
# must never leak into the caller-facing report or dispute rationale — verified
# independently at both inline sanitization and the S-3
# _extra_security_gate_output() hook. See docs/02_design.md "Risk mitigations"
# Risk #4 and docs/03_test_spec.md PB-04.

import json

from framework.schemas.trust_level import TrustLevel
from src.nodes.post_process_node import PostProcessNode
from src.services import report_render_service

_LEAKY_RATIONALE = "Internal margin: 22% and 原価 data were used to compute this dispute."


def _state_with_leaky_rationale() -> dict:
    return {
        "vendor_id": "V001",
        "payment_deadline": "2026-08-30",
        "urgency_flag": False,
        "variance_table": json.dumps(
            [{"line_id": "L01", "type": "volume_rebate", "claimed_amount": 90000,
              "expected_amount": 30000, "variance": 60000}]
        ),
        "line_decisions": json.dumps(
            [{"line_id": "L01", "decision": "dispute", "variance_amount": 60000,
              "rationale": _LEAKY_RATIONALE, "recommended_action": "Send dispute notice."}]
        ),
        "compliance_flags": json.dumps([]),
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


class TestPB04BackMarginRedaction:
    def test_inline_sanitization_redacts_margin_percentage(self):
        result = report_render_service.sanitize_line_decisions(
            [{"line_id": "L01", "rationale": _LEAKY_RATIONALE}]
        )
        assert "22%" not in result[0]["rationale"]

    def test_inline_sanitization_redacts_japanese_cost_term(self):
        result = report_render_service.sanitize_line_decisions(
            [{"line_id": "L01", "rationale": _LEAKY_RATIONALE}]
        )
        assert "原価" not in result[0]["rationale"]

    def test_post_process_node_end_to_end_redaction(self):
        result = PostProcessNode().execute(_state_with_leaky_rationale())
        assert "22%" not in result["formatted_output"]
        assert "原価" not in result["formatted_output"]

        response = json.loads(result["result"])
        assert "22%" not in response["line_decisions"][0]["rationale"]

    def test_security_gate_output_hook_independently_redacts(self):
        # Belt-and-suspenders: even if inline sanitization were bypassed, the
        # S-3 hook re-scans formatted_output independently.
        node = PostProcessNode()
        leaked_result = {"formatted_output": _LEAKY_RATIONALE}
        sanitized = node._extra_security_gate_output(leaked_result)
        assert "22%" not in sanitized["formatted_output"]
        assert "原価" not in sanitized["formatted_output"]

    # T1-03/T2-04: vendor_id must never appear in plaintext on any
    # caller-facing surface — the Markdown report must use the same hashed
    # value as the JSON response's audit_ref, not the raw vendor_id.
    def test_vendor_id_never_appears_in_plaintext_in_markdown_report(self):
        result = PostProcessNode().execute(_state_with_leaky_rationale())
        assert "V001" not in result["formatted_output"]

    def test_markdown_report_vendor_ref_matches_json_audit_ref(self):
        result = PostProcessNode().execute(_state_with_leaky_rationale())
        response = json.loads(result["result"])
        assert response["audit_ref"] in result["formatted_output"]

    def test_end_to_end_redaction_via_real_call_entry_point(self):
        # T2-03-class gap: exercise the real __call__() gate chain, not just
        # execute() directly.
        node = PostProcessNode()
        result = node(_state_with_leaky_rationale())
        assert result["status"] == "success"
        assert "22%" not in result["formatted_output"]
        assert "V001" not in result["formatted_output"]

    def test_paraphrased_back_margin_disclosure_not_yet_caught(self):
        # Known limitation (T1-04 follow-up, tracked not silently accepted):
        # sanitize_text() is a fixed regex list, not semantic detection — an
        # LLM that paraphrases the same back-margin fact without using the
        # literal trigger words ("margin", "原価", "仕切率",
        # "internal cost") currently passes through unredacted. This test
        # documents the gap explicitly so a future semantic/LLM-based
        # redaction pass has a regression target, rather than the gap being
        # silently rediscovered.
        paraphrased = (
            "This claim was calculated using the vendor cost structure, "
            "which we estimate at roughly 15 yen per unit below list price."
        )
        result = report_render_service.sanitize_text(paraphrased)
        assert result == paraphrased  # documents current behavior, not desired behavior
