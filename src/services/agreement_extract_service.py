"""AgentCore Platform v1.0 — Pass A (agreement term extraction) + Pass D
(dispute brief generation).

Both passes are LLM calls. Called from
src/nodes/main_node.py::MainNode.execute(). See docs/02_design.md
"Data Flow" MainNode Pass A / Pass D, and source proposal §4 Step 2
Pass A/D, §11 Risk #1.

Pass A output feeds Pass B's deterministic math (accrual_compliance_service)
— the LLM only performs semantic matching and structured extraction, never
the arithmetic itself.
"""

from __future__ import annotations

import json
from typing import Any

_CANONICAL_TYPES = (
    "volume_rebate",
    "coop_contribution",
    "listing_fee",
    "logistics_contribution",
)


def extract_terms(agreement_summary: str, claim_types: list[str], llm: Any = None) -> dict[str, Any]:
    """Pass A — semantic-match each claim line type to its agreement clause
    and extract structured formula parameters.

    Returns {type: {formula, threshold, period, cap, basis, basis_field,
    rate, extraction_confidence}}. Any type not found in the agreement, or
    with a low-confidence extraction, must be excluded so Pass B (accrual
    math) treats it as Needs-Info — never guess a formula.
    """
    if llm is not None:
        prompt = _build_extraction_prompt(agreement_summary, claim_types)
        try:
            response = llm.complete([{"role": "user", "content": prompt}])
            raw = response.get("content", "") if isinstance(response, dict) else str(response)
            parsed = json.loads(raw)
            return {t: terms for t, terms in parsed.items() if t in _CANONICAL_TYPES and isinstance(terms, dict)}
        except Exception:
            pass

    # Deterministic fallback when no LLM is configured (or it fails): no
    # terms can be extracted, so every line resolves to Needs-Info in Pass B
    # — never fabricate a formula without LLM-assisted extraction.
    return {}


def generate_dispute_briefs(
    line_decisions: list[dict[str, Any]],
    variance_table: list[dict[str, Any]],
    term_extracts: dict[str, Any],
    llm: Any = None,
) -> list[dict[str, Any]]:
    """Pass D — for each Dispute/Needs-Info line, draft a 2-3 sentence
    rationale citing variance amount and agreement clause, plus a
    recommended next action. Approve lines get a fixed short rationale
    (no LLM call needed).
    """
    variance_by_line = {v["line_id"]: v for v in variance_table}
    enriched = []

    for decision in line_decisions:
        line_id = decision["line_id"]
        variance_entry = variance_by_line.get(line_id, {})

        if decision["decision"] == "approve":
            enriched.append(
                {
                    **decision,
                    "rationale": "Claimed amount matches the expected accrual within tolerance.",
                    "recommended_action": "Approve for payment.",
                }
            )
            continue

        rationale, action = _draft_rationale(decision, variance_entry, term_extracts, llm)
        enriched.append({**decision, "rationale": rationale, "recommended_action": action})

    return enriched


def _draft_rationale(
    decision: dict[str, Any], variance_entry: dict[str, Any], term_extracts: dict[str, Any], llm: Any
) -> tuple[str, str]:
    line_type = variance_entry.get("type", "unknown")
    terms = term_extracts.get(line_type)

    if decision["decision"] == "needs_info":
        return (
            "Agreement clause not found or extraction confidence was low — " "manual review required.",
            "Route to buyer for manual agreement review.",
        )

    variance = variance_entry.get("variance", 0)
    deterministic_rationale = (
        f"Claimed amount exceeds the expected accrual by {variance:,.0f} JPY "
        f"based on the extracted {line_type} formula."
    )

    if llm is not None:
        prompt = _build_brief_prompt(decision, variance_entry, terms)
        try:
            response = llm.complete([{"role": "user", "content": prompt}])
            raw = response.get("content", "") if isinstance(response, dict) else str(response)
            answer = raw.strip()
            if _brief_is_factually_grounded(answer, variance, decision["line_id"]):
                return answer, "Send dispute notice citing agreement clause and variance."
        except Exception:
            pass

    # Deterministic fallback — used whenever no LLM is configured, the LLM
    # call fails, or the LLM's brief cannot be confirmed to reference the
    # actual computed variance (T1-04): a vendor-facing dispute notice must
    # never carry unconstrained free-text that could state a wrong amount.
    return deterministic_rationale, "Send dispute notice citing agreement clause and variance."


def _brief_is_factually_grounded(answer: str, variance: float, line_id: str) -> bool:
    """T1-04: minimal factual-grounding gate for the LLM-drafted dispute
    brief before it is sent to a vendor. The brief is free text (no
    structured schema to validate), so we cannot verify full correctness —
    but we can require it to actually cite the computed variance amount and
    the line it is about, catching the case where the LLM fabricates or
    omits the numbers entirely.
    """
    if not answer:
        return False
    variance_str = f"{abs(variance):,.0f}"
    return line_id in answer and variance_str in answer


def _build_extraction_prompt(agreement_summary: str, claim_types: list[str]) -> str:
    return (
        "You are a retail trade-promotion agreement analyst. Extract the "
        "rebate/contribution formula for each of the following claim types "
        f"from the agreement text below: {', '.join(claim_types)}.\n\n"
        "For each type found in the agreement, output JSON with keys: "
        "formula (str description), threshold (number), period (str), "
        "cap (number or null), basis (str description), basis_field "
        "(one of: net_sales, sell_out_units), rate (number, e.g. 0.03 for 3%), "
        "extraction_confidence (one of: high, medium, low — self-assess "
        "based on how explicit the agreement text is for this clause).\n\n"
        "Omit any type not found in the agreement. Respond with ONLY a JSON "
        "object mapping type -> extracted terms, no other text.\n\n"
        f"Agreement text:\n{agreement_summary}"
    )


def _build_brief_prompt(decision: dict[str, Any], variance_entry: dict[str, Any], terms: dict[str, Any] | None) -> str:
    return (
        "You are drafting a vendor rebate dispute brief for a retail "
        "category buyer. Write a 2-3 sentence rationale explaining why "
        f"claim line {decision['line_id']} ({variance_entry.get('type')}) is "
        "disputed, citing the variance amount and the agreement clause "
        "terms below. Be factual and concise — this will be sent to the "
        "vendor.\n\n"
        f"Claimed amount: {variance_entry.get('claimed_amount')}\n"
        f"Expected amount: {variance_entry.get('expected_amount')}\n"
        f"Variance: {variance_entry.get('variance')}\n"
        f"Agreement clause terms: {terms}\n"
    )
