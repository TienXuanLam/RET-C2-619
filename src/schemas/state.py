"""AgentCore Platform v1.0"""

# ADR-005: State must be a flat TypedDict (see ADR-005 for the prohibited
# alternatives). LangGraph checkpoints use msgpack serialization, so only
# plain serializable fields are allowed. Do NOT add credentials or secrets.
#
# Dict/list domain fields are stored as Optional[str] (JSON-str) — producer
# calls json.dumps(), consumer calls json.loads(). See docs/02_design.md
# "State Definition" for the full field-by-field producer/consumer map.

from typing import Optional

from framework.schemas.agent_state import AgentState


class State(AgentState):
    """RetailVendorRebateTradePromoReconciliationAgent state.

    result and formatted_output are inherited from AgentState — not
    redeclared here.
    """

    # --- PreProcessNode output ---
    vendor_id: Optional[str]
    agreement_summary: Optional[str]
    normalized_claim: Optional[str]  # JSON-str: list[{line_id, type, claimed_amount, period, basis}]
    actual_performance: Optional[str]  # JSON-str: {net_sales, sell_out_units, ...}
    claim_receipt_date: Optional[str]  # ISO date string — caller-provided, needed by MainNode Pass C
    payment_deadline: Optional[str]  # ISO date string — claim_receipt_date + payment_due_days
    urgency_flag: Optional[bool]

    # --- MainNode output (Pass A-D) ---
    term_extracts: Optional[str]  # JSON-str: {type: {formula, threshold, period, cap, basis, extraction_confidence}}
    variance_table: Optional[str]  # JSON-str: list[{line_id, type, claimed_amount, expected_amount, variance}]
    line_decisions: Optional[str]  # JSON-str: list[{line_id, decision, variance_amount, rationale, recommended_action}]
    compliance_flags: Optional[str]  # JSON-str: list[{type, detail, informational}]
