"""AgentCore Platform v1.0"""

# Node contract (node-contract.md): extend FunctionNode; implement
# execute(state) -> dict; return ONLY changed fields; use AgentStatus enum.
#
# Runs 4 sequential passes (A-D) inside this single node — see
# docs/02_design.md "Architecture Overview" for why this stays one node
# (source proposal §10-3: "no multi-node routing complexity"). Pass B/C
# are deterministic and authoritative; Pass A/D are LLM-assisted and never
# produce the Approve/Dispute/Needs-Info decision itself (source proposal
# §11 Risk #1).

import json
from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.services import accrual_compliance_service, agreement_extract_service


class MainNode(FunctionNode):
    """Passes A-D: agreement term extraction, accrual validation, 下請法
    timeline check, dispute brief generation."""

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def __init__(self, llm: Any = None) -> None:
        self._llm = llm

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        normalized_claim = json.loads(state.get("normalized_claim") or "[]")
        actual_performance = json.loads(state.get("actual_performance") or "{}")
        agreement_summary = state.get("agreement_summary", "")
        payment_deadline = state.get("payment_deadline", "")
        claim_receipt_date = state.get("claim_receipt_date", "")

        if not normalized_claim or not payment_deadline or not claim_receipt_date:
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": [
                    "MainNode: missing normalized_claim, payment_deadline, or "
                    "claim_receipt_date — PreProcessNode must run first"
                ],
            }

        claim_types = sorted({line["type"] for line in normalized_claim})

        # Pass A — LLM agreement term extraction (never produces the decision itself)
        term_extracts = agreement_extract_service.extract_terms(agreement_summary, claim_types, llm=self._llm)
        emit_trace_event(
            "terms_extracted",
            {"types_found": sorted(term_extracts.keys()), "types_requested": claim_types},
            state,
        )

        # Pass B — deterministic accrual math (authoritative decision path)
        variance_table, line_decisions = accrual_compliance_service.validate_accrual(
            normalized_claim, term_extracts, actual_performance
        )
        emit_trace_event(
            "accrual_validated",
            {"line_count": len(line_decisions)},
            state,
        )

        # Pass C — deterministic 下請法 Article 4 timeline check
        compliance_flags = accrual_compliance_service.check_timeline(payment_deadline, claim_receipt_date)
        emit_trace_event(
            "timeline_checked",
            {"flag_count": len(compliance_flags)},
            state,
        )

        # Pass D — LLM dispute brief generation
        line_decisions = agreement_extract_service.generate_dispute_briefs(
            line_decisions, variance_table, term_extracts, llm=self._llm
        )
        emit_trace_event(
            "dispute_brief_generated",
            {"disputed_or_needs_info": sum(1 for d in line_decisions if d["decision"] != "approve")},
            state,
        )

        return {
            "term_extracts": json.dumps(term_extracts),
            "variance_table": json.dumps(variance_table),
            "line_decisions": json.dumps(line_decisions),
            "compliance_flags": json.dumps(compliance_flags),
            "status": AgentStatus.SUCCESS.value,
        }
