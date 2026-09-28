"""AgentCore Platform v1.0"""

# Node contract: extend FunctionNode; implement
# execute(state) -> dict; return ONLY changed fields; use AgentStatus enum.
#
# Real S-3 gate slot. S-2/S-3 sanitization + Markdown report rendering +
# line_decisions[] JSON assembly + S-4 audit log. See docs/02_design.md
# "Data Flow" PostProcessNode section, source proposal §4 Step 3.

import hashlib
import json
from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.services import report_render_service


class PostProcessNode(FunctionNode):
    """S-2/S-3 sanitization + report assembly + S-4 audit log."""

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def _extra_security_gate_output(self, result: dict[str, Any]) -> dict[str, Any]:
        # S-3: back-margin/internal-pricing redaction is already applied
        # inside execute() via report_render_service.sanitize_text(); this
        # hook confirms the gate ran (ADR-017), belt-and-suspenders re-scan
        # of the final formatted_output.
        formatted_output = result.get("formatted_output")
        if isinstance(formatted_output, str):
            result["formatted_output"] = report_render_service.sanitize_text(formatted_output)
        return result

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        vendor_id = state.get("vendor_id", "")
        payment_deadline = state.get("payment_deadline", "")
        urgency_flag = bool(state.get("urgency_flag", False))
        variance_table = json.loads(state.get("variance_table") or "[]")
        line_decisions = json.loads(state.get("line_decisions") or "[]")
        compliance_flags = json.loads(state.get("compliance_flags") or "[]")

        # S-2/S-3: redact back-margin/internal-pricing data that may have
        # been inferred from agreement_summary (source proposal Risk #4)
        line_decisions = report_render_service.sanitize_line_decisions(line_decisions)

        summary = report_render_service.compute_summary(variance_table, line_decisions)

        vendor_id_hash = _hash_vendor_id(vendor_id)

        response = {
            "line_decisions": line_decisions,
            "compliance_flags": compliance_flags,
            "summary": summary,
            "audit_ref": vendor_id_hash,
        }

        formatted_output = report_render_service.render_markdown_report(
            vendor_id=vendor_id_hash,
            payment_deadline=payment_deadline,
            urgency_flag=urgency_flag,
            variance_table=variance_table,
            line_decisions=line_decisions,
            compliance_flags=compliance_flags,
            summary=summary,
        )

        emit_trace_event(
            "report_assembled",
            {
                "vendor_id_hash": vendor_id_hash,
                "line_count": len(line_decisions),
                "decision_counts": {
                    "approve": sum(1 for d in line_decisions if d["decision"] == "approve"),
                    "dispute": sum(1 for d in line_decisions if d["decision"] == "dispute"),
                    "needs_info": sum(1 for d in line_decisions if d["decision"] == "needs_info"),
                },
                "compliance_flag_count": len(compliance_flags),
            },
            state,
        )

        return {
            "result": json.dumps(response),
            "formatted_output": formatted_output,
            "line_decisions": json.dumps(line_decisions),
            "status": AgentStatus.SUCCESS.value,
        }


def _hash_vendor_id(vendor_id: str) -> str:
    if not vendor_id:
        return ""
    return hashlib.sha256(vendor_id.encode("utf-8")).hexdigest()[:16]
