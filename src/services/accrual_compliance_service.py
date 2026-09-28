"""AgentCore Platform v1.0 — Pass B (accrual math) + Pass C (下請法 timeline check).

Pure deterministic domain logic — no LLM, no framework/agenticstar imports.
Called from src/nodes/main_node.py::MainNode.execute(). See
docs/02_design.md "Data Flow" MainNode Pass B / Pass C, and source proposal
§4 Step 2 Pass B/C, §11 Risk #1.

Accrual math is deterministic arithmetic applied to LLM-extracted formula
parameters (term_extracts, produced by Pass A) — the math itself is never
LLM-generated, which keeps the Approve/Dispute/Needs-Info decision path
hallucination-free (source proposal §7, §11 Risk #1).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

# source proposal §4 Step 2 Pass B — tolerance for variance classification
TOLERANCE_ABSOLUTE_JPY = 1000
TOLERANCE_RELATIVE = 0.005  # 0.5%

STATUTORY_MAX_PAYMENT_DAYS = 60

# Only these two basis fields exist in actual_performance (docs/02_design.md
# "State Definition") — an LLM-extracted basis_field outside this allowlist
# is a misextraction, never a value to silently default to 0.0 for (T1-01).
_ALLOWED_BASIS_FIELDS = ("net_sales", "sell_out_units")

# Pass A's prompt only ever asks for high/medium/low (agreement_extract_service
# ._build_extraction_prompt) — anything else means the LLM did not follow the
# schema and the extraction cannot be trusted at any confidence level.
_VALID_CONFIDENCE_LEVELS = ("high", "medium", "low")


def _terms_are_trustworthy(terms: dict[str, Any]) -> bool:
    """Strict extracted-term schema gate (T1-01): every numeric field must
    actually be numeric and non-negative, basis_field must be an allowlisted
    actual_performance key, and confidence must be explicitly "high" — never
    silently accept a malformed, incomplete, or merely "medium"-confidence
    extraction into authoritative deterministic arithmetic. Any failure here
    routes the line to Needs-Info in validate_accrual(), never
    Approve/Dispute.
    """
    if terms.get("extraction_confidence") != "high":
        return False
    if terms.get("basis_field") not in _ALLOWED_BASIS_FIELDS:
        return False

    rate = terms.get("rate")
    threshold = terms.get("threshold")
    cap = terms.get("cap")

    if not isinstance(rate, (int, float)) or isinstance(rate, bool) or rate < 0:
        return False
    if not isinstance(threshold, (int, float)) or isinstance(threshold, bool) or threshold < 0:
        return False
    if cap is not None and (not isinstance(cap, (int, float)) or isinstance(cap, bool) or cap < 0):
        return False

    return True


def validate_accrual(
    normalized_claim: list[dict[str, Any]],
    term_extracts: dict[str, Any],
    actual_performance: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Pass B — apply extracted formula to actual_performance; classify each line.

    Returns (variance_table, line_decisions) — line_decisions here carries
    only {line_id, decision, variance_amount}; rationale is merged in by
    Pass D later.
    """
    variance_table = []
    line_decisions = []

    for line in normalized_claim:
        line_id = line["line_id"]
        line_type = line["type"]
        claimed_amount = line["claimed_amount"]

        terms = term_extracts.get(line_type)
        if terms is None or not isinstance(terms, dict) or not _terms_are_trustworthy(terms):
            variance_table.append(
                {
                    "line_id": line_id,
                    "type": line_type,
                    "claimed_amount": claimed_amount,
                    "expected_amount": None,
                    "variance": None,
                }
            )
            line_decisions.append({"line_id": line_id, "decision": "needs_info", "variance_amount": None})
            continue

        expected_amount = _apply_formula(terms, actual_performance)
        variance = claimed_amount - expected_amount

        tolerance = max(TOLERANCE_ABSOLUTE_JPY, abs(expected_amount) * TOLERANCE_RELATIVE)
        decision = "approve" if abs(variance) <= tolerance else "dispute"

        variance_table.append(
            {
                "line_id": line_id,
                "type": line_type,
                "claimed_amount": claimed_amount,
                "expected_amount": expected_amount,
                "variance": variance,
            }
        )
        line_decisions.append({"line_id": line_id, "decision": decision, "variance_amount": variance})

    return variance_table, line_decisions


def _apply_formula(terms: dict[str, Any], actual_performance: dict[str, Any]) -> float:
    """Deterministic arithmetic: rate applied to the relevant actual-performance basis.

    Only called after _terms_are_trustworthy() has confirmed rate/threshold/
    cap are numeric and basis_field is allowlisted — no further defaulting
    needed here.
    """
    rate = terms["rate"]
    basis_field = terms["basis_field"]
    threshold = terms["threshold"]
    cap = terms.get("cap")

    basis_value = float(actual_performance.get(basis_field, 0.0))
    taxable_base = max(0.0, basis_value - threshold)
    expected = taxable_base * rate

    if cap is not None:
        expected = min(expected, cap)
    return round(float(expected), 2)


def check_timeline(payment_deadline: str, claim_receipt_date: str) -> list[dict[str, Any]]:
    """Pass C — 下請法 Article 4 statutory 60-day payment window check.

    Flags every claim (once, not per-line — the deadline is claim-level, not
    line-level) if the deadline exceeds the statutory maximum from receipt.
    Every flag carries informational=true (source proposal §11 Risk #3 —
    this is never a binding legal determination).
    """
    receipt = datetime.fromisoformat(claim_receipt_date).date()
    deadline = datetime.fromisoformat(payment_deadline).date()
    statutory_max = receipt + timedelta(days=STATUTORY_MAX_PAYMENT_DAYS)

    if deadline <= statutory_max:
        return []

    return [
        {
            "type": "下請法Article4",
            "detail": (
                f"Payment deadline {deadline.isoformat()} exceeds the 60-day "
                f"statutory limit from receipt {receipt.isoformat()}"
            ),
            "informational": True,
        }
    ]
