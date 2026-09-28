"""AgentCore Platform v1.0 — PostProcessNode domain logic: S-2/S-3
sanitization + Markdown reconciliation report rendering.

Called from src/nodes/post_process_node.py::PostProcessNode.execute(). See
docs/02_design.md "Security Design" and source proposal §4 Step 3,
§11 Risk #3/#4.
"""

from __future__ import annotations

import re
from typing import Any

# source proposal §11 Risk #4 — common back-margin / internal-pricing
# indicators that may have been inferred from agreement_summary and must
# never appear in the caller-facing report or dispute rationale.
_BACK_MARGIN_PATTERNS = [
    re.compile(r"margin\s*[:=]?\s*\d+(\.\d+)?%", re.IGNORECASE),
    re.compile(r"原価"),
    re.compile(r"仕切率"),
    re.compile(r"internal[_\s]?cost", re.IGNORECASE),
]

_REDACTED = "[redacted — internal pricing data]"

# source proposal §12 dependency #5 — draft disclaimer text (JP), pending
# legal review; kept here verbatim until legal sign-off updates it.
DISCLAIMER_JP = (
    "本エージェントが出力する支払期限計算および下請法第4条コンプライアンス"
    "フラグは情報提供を目的としたものであり、法的判断を構成するものでは"
    "ありません。最終的なコンプライアンス判断および下請法に基づくすべての"
    "義務はバイヤー/APチームおよびその法的顧問が負います。"
)
DISCLAIMER_EN = (
    "The payment-deadline calculations and 下請法 Article 4 compliance flags "
    "produced by this agent are informational only and do not constitute a "
    "legal determination. Final compliance determination and all "
    "下請法-related obligations remain with the buyer/AP team and their "
    "legal counsel."
)


def sanitize_text(text: str) -> str:
    """S-2/S-3: redact common back-margin/internal-pricing indicators."""
    sanitized = text
    for pattern in _BACK_MARGIN_PATTERNS:
        sanitized = pattern.sub(_REDACTED, sanitized)
    return sanitized


def sanitize_line_decisions(line_decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{**d, "rationale": sanitize_text(d.get("rationale", ""))} for d in line_decisions]


def render_markdown_report(
    vendor_id: str,
    payment_deadline: str,
    urgency_flag: bool,
    variance_table: list[dict[str, Any]],
    line_decisions: list[dict[str, Any]],
    compliance_flags: list[dict[str, Any]],
    summary: dict[str, Any],
) -> str:
    # T1-03: caller-facing surfaces must be consistent — the JSON response's
    # audit_ref carries only the hashed vendor_id (see
    # PostProcessNode._hash_vendor_id); the Markdown report must never
    # re-introduce the plaintext identifier the JSON side deliberately
    # withholds. Callers pass the already-hashed value in.
    lines = [
        "# Vendor Rebate Reconciliation Report",
        "",
        f"**Vendor Ref:** {vendor_id}",
        f"**Payment Deadline:** {payment_deadline}" + (" ⚠️ URGENT (< 14 days)" if urgency_flag else ""),
        "",
        "## Variance Table",
        "",
        "| Line ID | Type | Claimed | Expected | Variance | Decision |",
        "|---|---|---|---|---|---|",
    ]

    decision_by_line = {d["line_id"]: d["decision"] for d in line_decisions}
    for v in variance_table:
        decision = decision_by_line.get(v["line_id"], "needs_info")
        lines.append(
            f"| {v['line_id']} | {v['type']} | {v['claimed_amount']} | "
            f"{v.get('expected_amount', 'N/A')} | {v.get('variance', 'N/A')} | {decision} |"
        )

    if compliance_flags:
        lines += ["", "## 下請法 Compliance Flags", ""]
        for flag in compliance_flags:
            lines.append(f"- **{flag['type']}**: {flag['detail']}")

    disputed_or_ni = [d for d in line_decisions if d["decision"] != "approve"]
    if disputed_or_ni:
        lines += ["", "## Dispute Brief", ""]
        for d in disputed_or_ni:
            lines.append(f"**{d['line_id']}** ({d['decision']}): {d['rationale']}")
            lines.append(f"- Next action: {d['recommended_action']}")
            lines.append("")

    lines += [
        "## Summary",
        "",
        f"- Total Approved: {summary['total_approved']}",
        f"- Total Disputed: {summary['total_disputed']}",
        f"- Total Needs Info: {summary['total_needs_info']}",
        "",
        "---",
        "",
        f"*{DISCLAIMER_EN}*",
        "",
        f"*{DISCLAIMER_JP}*",
    ]

    return "\n".join(lines)


def compute_summary(variance_table: list[dict[str, Any]], line_decisions: list[dict[str, Any]]) -> dict[str, Any]:
    decision_by_line = {d["line_id"]: d for d in line_decisions}
    total_approved = 0.0
    total_disputed = 0.0
    total_needs_info = 0

    for v in variance_table:
        decision = decision_by_line.get(v["line_id"], {}).get("decision", "needs_info")
        if decision == "approve":
            total_approved += v["claimed_amount"]
        elif decision == "dispute":
            total_disputed += abs(v.get("variance") or 0)
        else:
            total_needs_info += 1

    return {
        "total_approved": total_approved,
        "total_disputed": total_disputed,
        "total_needs_info": total_needs_info,
    }
