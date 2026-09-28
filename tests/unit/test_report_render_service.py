# RET-C2-619 — Unit Tests: report_render_service (PostProcessNode S-2/S-3 + Markdown)

from src.services import report_render_service


class TestSanitizeText:
    def test_margin_percentage_redacted(self):
        text = "Internal note: margin: 15% applies here."
        result = report_render_service.sanitize_text(text)
        assert "15%" not in result
        assert "[redacted" in result

    def test_japanese_cost_terms_redacted(self):
        assert "[redacted" in report_render_service.sanitize_text("原価は非公開です")
        assert "[redacted" in report_render_service.sanitize_text("仕切率は30%です")

    def test_clean_text_unchanged(self):
        text = "This claim line is approved for payment."
        assert report_render_service.sanitize_text(text) == text


class TestSanitizeLineDecisions:
    def test_rationale_sanitized(self):
        line_decisions = [
            {"line_id": "L01", "decision": "dispute", "rationale": "margin: 20% mismatch"}
        ]
        result = report_render_service.sanitize_line_decisions(line_decisions)
        assert "20%" not in result[0]["rationale"]


class TestComputeSummary:
    def test_summary_totals(self):
        variance_table = [
            {"line_id": "L01", "claimed_amount": 1000, "variance": 0},
            {"line_id": "L02", "claimed_amount": 2000, "variance": -500},
            {"line_id": "L03", "claimed_amount": 500, "variance": None},
        ]
        line_decisions = [
            {"line_id": "L01", "decision": "approve"},
            {"line_id": "L02", "decision": "dispute"},
            {"line_id": "L03", "decision": "needs_info"},
        ]
        summary = report_render_service.compute_summary(variance_table, line_decisions)
        assert summary["total_approved"] == 1000
        assert summary["total_disputed"] == 500
        assert summary["total_needs_info"] == 1


class TestRenderMarkdownReport:
    def test_disclaimer_present(self):
        output = report_render_service.render_markdown_report(
            vendor_id="V001",
            payment_deadline="2026-08-30",
            urgency_flag=False,
            variance_table=[],
            line_decisions=[],
            compliance_flags=[],
            summary={"total_approved": 0, "total_disputed": 0, "total_needs_info": 0},
        )
        assert report_render_service.DISCLAIMER_EN in output
        assert report_render_service.DISCLAIMER_JP in output

    def test_urgency_flag_shown(self):
        output = report_render_service.render_markdown_report(
            vendor_id="V001",
            payment_deadline="2026-07-15",
            urgency_flag=True,
            variance_table=[],
            line_decisions=[],
            compliance_flags=[],
            summary={"total_approved": 0, "total_disputed": 0, "total_needs_info": 0},
        )
        assert "URGENT" in output

    def test_compliance_flags_section_present_when_flagged(self):
        output = report_render_service.render_markdown_report(
            vendor_id="V001",
            payment_deadline="2026-09-15",
            urgency_flag=False,
            variance_table=[],
            line_decisions=[],
            compliance_flags=[{"type": "下請法Article4", "detail": "breach detail", "informational": True}],
            summary={"total_approved": 0, "total_disputed": 0, "total_needs_info": 0},
        )
        assert "下請法 Compliance Flags" in output
        assert "breach detail" in output
