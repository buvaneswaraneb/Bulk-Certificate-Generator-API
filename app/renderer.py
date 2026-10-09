from __future__ import annotations

from html import escape
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph


class CertificateRenderer:
    """Fixed certificate design; replace this adapter to use another rendering engine."""

    def render(self, destination: Path, *, recipient_name: str, course_name: str,
               issue_date: str, organization_name: str, event_name: str) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        width, height = landscape(A4)
        canvas = Canvas(str(destination), pagesize=(width, height))
        canvas.setFillColor(colors.HexColor("#FCFAF3"))
        canvas.rect(0, 0, width, height, stroke=0, fill=1)
        canvas.setStrokeColor(colors.HexColor("#9B7A36"))
        canvas.setLineWidth(3)
        canvas.rect(12 * mm, 12 * mm, width - 24 * mm, height - 24 * mm, stroke=1, fill=0)
        canvas.setLineWidth(.7)
        canvas.rect(17 * mm, 17 * mm, width - 34 * mm, height - 34 * mm, stroke=1, fill=0)
        canvas.setFillColor(colors.HexColor("#274C5E"))
        canvas.setFont("Helvetica-Bold", 26)
        canvas.drawCentredString(width / 2, height - 49 * mm, "CERTIFICATE OF COMPLETION")
        canvas.setFillColor(colors.HexColor("#555555"))
        canvas.setFont("Helvetica", 12)
        canvas.drawCentredString(width / 2, height - 66 * mm, "This certificate is proudly presented to")
        canvas.setFillColor(colors.HexColor("#9B7A36"))
        name_size = min(30, max(18, 500 / max(len(recipient_name), 1)))
        canvas.setFont("Helvetica-Bold", name_size)
        canvas.drawCentredString(width / 2, height - 90 * mm, recipient_name)
        canvas.setStrokeColor(colors.HexColor("#9B7A36"))
        canvas.line(width / 2 - 75 * mm, height - 95 * mm, width / 2 + 75 * mm, height - 95 * mm)
        style = ParagraphStyle("course", fontName="Helvetica", fontSize=13, leading=18,
                               alignment=1, textColor=colors.HexColor("#333333"))
        text = (f"for successfully completing <b>{escape(course_name)}</b><br/>"
                f"at {escape(event_name)}")
        paragraph = Paragraph(text, style)
        paragraph.wrapOn(canvas, 170 * mm, 35 * mm)
        paragraph.drawOn(canvas, width / 2 - 85 * mm, height - 125 * mm)
        canvas.setFillColor(colors.HexColor("#555555"))
        canvas.setFont("Helvetica", 10)
        canvas.drawString(35 * mm, 35 * mm, f"Issued by {organization_name}")
        canvas.drawRightString(width - 35 * mm, 35 * mm, f"Issued: {issue_date}")
        canvas.save()
