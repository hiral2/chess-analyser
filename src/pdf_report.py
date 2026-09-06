"""Render a single analysis report as a PDF via ReportLab."""
from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    ListFlowable,
    ListItem,
)

RISK_COLORS = {
    "LOW": colors.HexColor("#22543d"),
    "MEDIUM": colors.HexColor("#744210"),
    "HIGH": colors.HexColor("#742a2a"),
}


def _styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="H2Custom", parent=styles["Heading2"], spaceBefore=16, spaceAfter=6))
    styles.add(ParagraphStyle(name="H3Custom", parent=styles["Heading3"], spaceBefore=10, spaceAfter=4))
    styles.add(ParagraphStyle(name="BodySmall", parent=styles["BodyText"], fontSize=9, leading=12))
    return styles


def build_pdf(report: dict, output_path: str, username: str) -> str:
    styles = _styles()
    doc = SimpleDocTemplate(output_path, pagesize=LETTER, topMargin=0.75 * inch, bottomMargin=0.75 * inch)
    story = []

    story.append(Paragraph(f"Chess Performance & Fair-Play Report", styles["Title"]))
    story.append(Paragraph(f"Player: {username} &nbsp;&nbsp;|&nbsp;&nbsp; Date: {report.get('date', '')}", styles["Normal"]))
    story.append(Spacer(1, 12))
    story.append(Paragraph(report.get("summary", ""), styles["BodyText"]))

    metrics = report.get("overall_metrics", {})
    story.append(Paragraph("Overall Metrics", styles["H2Custom"]))
    table_data = [
        ["Games", "Wins", "Losses", "Draws", "Tactical Accuracy"],
        [
            metrics.get("total_games", "-"),
            metrics.get("wins", "-"),
            metrics.get("losses", "-"),
            metrics.get("draws", "-"),
            metrics.get("tactical_accuracy_rating", "-"),
        ],
    ]
    t = Table(table_data, hAlign="LEFT")
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#edf2f7")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e0")),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(t)
    if metrics.get("primary_opening_weakness"):
        story.append(Spacer(1, 6))
        story.append(Paragraph(f"<b>Primary weakness:</b> {metrics['primary_opening_weakness']}", styles["BodyText"]))

    fp = report.get("fair_play_assessment", {})
    risk = fp.get("overall_risk_level", "LOW")
    story.append(Paragraph("Fair-Play Assessment", styles["H2Custom"]))
    risk_style = ParagraphStyle(name="Risk", parent=styles["BodyText"], textColor=RISK_COLORS.get(risk, colors.black))
    story.append(Paragraph(f"<b>Risk Level: {risk}</b>", risk_style))
    story.append(Paragraph(fp.get("summary_notes", ""), styles["BodyText"]))

    story.append(Paragraph("Games & Key Moments", styles["H2Custom"]))
    for game in report.get("games", []):
        header = f"{game.get('white', '?')} vs {game.get('black', '?')} — {game.get('result', '?')}"
        story.append(Paragraph(header, styles["H3Custom"]))
        story.append(Paragraph(f"<font size=8 color='#4a5568'>{game.get('game_id', '')}</font>", styles["Normal"]))

        opp = game.get("opponent_fair_play", {})
        if opp:
            story.append(
                Paragraph(
                    f"Opponent ({opp.get('opponent_username', '?')}): ACPL={opp.get('acpl', '-')}, "
                    f"Top-1 Match={opp.get('top_1_match_pct', '-')}%, Risk={opp.get('risk_level', '-')}",
                    styles["BodySmall"],
                )
            )
            if opp.get("notes"):
                story.append(Paragraph(opp["notes"], styles["BodySmall"]))

        moments = game.get("key_moments", [])
        if moments:
            items = []
            for m in moments:
                text = (
                    f"<b>Move {m.get('move_number', '?')} ({m.get('move_type', '')}):</b> "
                    f"played <font color='#e53e3e'>{m.get('blunder_move', '?')}</font>, "
                    f"best was <font color='#38a169'>{m.get('best_move', '?')}</font>. "
                    f"{m.get('explanation', '')}<br/>"
                    f"<font size=7 color='#718096'>FEN: {m.get('fen', '')}</font>"
                )
                items.append(ListItem(Paragraph(text, styles["BodySmall"])))
            story.append(ListFlowable(items, bulletType="bullet"))
        story.append(Spacer(1, 8))

    story.append(Paragraph("Coaching Plan", styles["H2Custom"]))
    plan_items = [ListItem(Paragraph(item, styles["BodyText"])) for item in report.get("coaching_plan", [])]
    if plan_items:
        story.append(ListFlowable(plan_items, bulletType="bullet"))

    doc.build(story)
    return output_path
