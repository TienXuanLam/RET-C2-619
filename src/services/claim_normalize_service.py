"""AgentCore Platform v1.0"""

# Pure domain logic for PreProcessNode: S-1 schema validation, claim line
# type normalization, statutory payment-deadline computation. No
# framework/agenticstar imports — this module receives and returns plain
# dict/list, called by PreProcessNode.execute().

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

CANONICAL_TYPES = {
    "volume_rebate",
    "coop_contribution",
    "listing_fee",
    "logistics_contribution",
}
DEFAULT_TYPE = "other"

# 下請法 (Subcontract Act) Article 4 statutory maximum payment window (days)
STATUTORY_MAX_PAYMENT_DAYS = 60
URGENT_WINDOW_DAYS = 14


def validate_schema(payload: dict[str, Any], max_claim_lines: int) -> list[str]:
    """Return a list of validation error strings; empty list means valid."""
    errors: list[str] = []

    claim_lines = payload.get("claim_lines")
    if not claim_lines or not isinstance(claim_lines, list):
        errors.append("PreProcessNode: claim_lines is missing or not a list")
        return errors

    if len(claim_lines) > max_claim_lines:
        errors.append(
            f"PreProcessNode: claim_lines count ({len(claim_lines)}) exceeds "
            f"the maximum of {max_claim_lines} — split into multiple batches"
        )
        return errors

    for i, line in enumerate(claim_lines):
        if not isinstance(line, dict):
            errors.append(f"PreProcessNode: claim_lines[{i}] is not an object")
            continue
        if not line.get("line_id"):
            errors.append(f"PreProcessNode: claim_lines[{i}] missing required field 'line_id'")
        amount = line.get("claimed_amount")
        if not isinstance(amount, (int, float)) or amount < 0:
            errors.append(f"PreProcessNode: claim_lines[{i}] 'claimed_amount' must be a non-negative number")

    agreement_summary = payload.get("agreement_summary")
    if not agreement_summary or not str(agreement_summary).strip():
        errors.append("PreProcessNode: agreement_summary is empty or missing")

    receipt_date = payload.get("claim_receipt_date", "")
    try:
        datetime.fromisoformat(receipt_date)
    except (ValueError, TypeError):
        errors.append(f"PreProcessNode: claim_receipt_date '{receipt_date}' is not a parseable ISO date")

    # T1-02: payment_due_days flows unguarded into compute_deadline()'s
    # int(payment_due_days) — validate here so a malformed value is a clean
    # domain error, not an uncaught ValueError leaking a stack trace into
    # error_log.
    if "payment_due_days" in payload:
        payment_due_days = payload.get("payment_due_days")
        if isinstance(payment_due_days, bool) or not isinstance(payment_due_days, int):
            errors.append(f"PreProcessNode: payment_due_days '{payment_due_days}' must be an integer")
        elif payment_due_days < 0 or payment_due_days > 365:
            errors.append(f"PreProcessNode: payment_due_days ({payment_due_days}) must be between 0 and 365")

    return errors


def cap_agreement_summary(agreement_summary: str, max_tokens: int) -> str:
    """Truncate agreement_summary to an approximate token cap.

    Approximation: 1 token ~= 4 chars (source proposal §10-4 token estimate).
    """
    max_chars = max_tokens * 4
    if len(agreement_summary) <= max_chars:
        return agreement_summary
    return agreement_summary[:max_chars]


def normalize_claim_lines(claim_lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map each claim line's 'type' to the canonical set; unknown -> 'other'."""
    normalized = []
    for line in claim_lines:
        line_type = line.get("type", DEFAULT_TYPE)
        canonical_type = line_type if line_type in CANONICAL_TYPES else DEFAULT_TYPE
        normalized.append(
            {
                "line_id": line["line_id"],
                "type": canonical_type,
                "claimed_amount": line["claimed_amount"],
                "period": line.get("period", ""),
                "basis": line.get("basis", ""),
            }
        )
    return normalized


def compute_deadline(claim_receipt_date: str, payment_due_days: int) -> tuple[str, bool]:
    """Compute payment_deadline = claim_receipt_date + payment_due_days.

    Returns (payment_deadline ISO string, urgency_flag). Urgency is true when
    the deadline is less than URGENT_WINDOW_DAYS away from today.
    """
    receipt = datetime.fromisoformat(claim_receipt_date).date()
    deadline = receipt + timedelta(days=int(payment_due_days))
    urgency_flag = deadline < date.today() + timedelta(days=URGENT_WINDOW_DAYS)
    return deadline.isoformat(), urgency_flag
