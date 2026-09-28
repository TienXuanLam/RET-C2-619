"""AgentCore Platform v1.0"""

# Node contract (node-contract.md): extend FunctionNode; implement
# execute(state) -> dict; return ONLY changed fields; use AgentStatus enum.
#
# S-1 schema validation + claim line normalization + statutory deadline
# computation (source proposal §4 Step 1, docs/02_design.md "Data Flow"
# PreProcessNode section).

import json
from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.services import claim_normalize_service

# source proposal §11 Risk #5 — protects against LLM context-window overflow
MAX_CLAIM_LINES = 30
MAX_AGREEMENT_SUMMARY_TOKENS = 8000
MIN_AGREEMENT_SUMMARY_CHARS = 200  # source proposal §11 Risk #2 — warn only


class PreProcessNode(FunctionNode):
    """Validate claim payload, normalize claim lines, compute statutory deadline."""

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def _extra_security_gate_input(self, state: dict[str, Any]) -> dict[str, Any]:
        # S-2 (docs/02_design.md "Security Design"): no additional PII scan
        # needed beyond the framework default — vendor financial data only,
        # no APPI personal data (source proposal §10-5). Runs BEFORE JSON
        # parsing (user_input is still the raw payload string here), so this
        # can only do a raw-length sanity check; the field-level
        # agreement_summary length warning (source proposal Risk #2) happens
        # in execute() where the parsed payload is available.
        raw_input = state.get("user_input", "")
        if raw_input and len(raw_input) < MIN_AGREEMENT_SUMMARY_CHARS:
            state = dict(state)
            state["_raw_input_suspiciously_short"] = True
        return state

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        raw_input = state.get("user_input", "")

        try:
            payload = json.loads(raw_input) if raw_input else {}
        except json.JSONDecodeError:
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["PreProcessNode: user_input is not valid JSON"],
            }

        error_log = claim_normalize_service.validate_schema(payload, MAX_CLAIM_LINES)
        if error_log:
            return {"status": AgentStatus.ERROR.value, "error_log": error_log}

        agreement_summary = payload.get("agreement_summary", "")
        if len(agreement_summary) < MIN_AGREEMENT_SUMMARY_CHARS:
            error_log = [
                f"PreProcessNode: agreement_summary is suspiciously short "
                f"({len(agreement_summary)} chars) relative to claim line count — "
                "extraction accuracy may be degraded"
            ]
        else:
            error_log = []

        agreement_summary = claim_normalize_service.cap_agreement_summary(
            agreement_summary, MAX_AGREEMENT_SUMMARY_TOKENS
        )

        normalized_claim = claim_normalize_service.normalize_claim_lines(payload.get("claim_lines", []))
        payment_deadline, urgency_flag = claim_normalize_service.compute_deadline(
            payload.get("claim_receipt_date", ""),
            payload.get("payment_due_days", 60),
        )

        emit_trace_event(
            "input_validated",
            {"line_count": len(normalized_claim), "urgency_flag": urgency_flag},
            state,
        )

        return {
            "vendor_id": payload.get("vendor_id", ""),
            "agreement_summary": agreement_summary,
            "normalized_claim": json.dumps(normalized_claim),
            "actual_performance": json.dumps(payload.get("actual_performance", {})),
            "claim_receipt_date": payload.get("claim_receipt_date", ""),
            "payment_deadline": payment_deadline,
            "urgency_flag": urgency_flag,
            "error_log": error_log,
            "status": AgentStatus.SUCCESS.value,
        }
