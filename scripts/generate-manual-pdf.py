"""Render the German Markdown user manual as the distributed PDF manual."""

from __future__ import annotations

import html
import re
import sys
from pathlib import Path

from PIL import Image as PilImage
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "WinWhisperPlus Benutzerhandbuch.md"
TARGET = ROOT / "docs" / "WinWhisperPlus Benutzerhandbuch.pdf"
IMAGE_PATTERN = re.compile(r"!\[[^]]*]\(([^)]+)\)")
INLINE_PATTERN = re.compile(r"(`[^`]+`|\*\*[^*]+\*\*)")


def _inline_markup(text: str) -> str:
    """Translate the small Markdown subset used by the manual to ReportLab markup."""
    parts: list[str] = []
    for part in INLINE_PATTERN.split(text):
        if part.startswith("`") and part.endswith("`"):
            parts.append(f'<font name="Courier">{html.escape(part[1:-1])}</font>')
        elif part.startswith("**") and part.endswith("**"):
            parts.append(f"<b>{html.escape(part[2:-2])}</b>")
        else:
            parts.append(html.escape(part))
    return "".join(parts)


def _footer(canvas, document) -> None:
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#d0d0d0"))
    canvas.line(document.leftMargin, 1.35 * cm, A4[0] - document.rightMargin, 1.35 * cm)
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#666666"))
    canvas.drawString(document.leftMargin, 0.85 * cm, "WinWhisperPlus Benutzerhandbuch")
    canvas.drawRightString(A4[0] - document.rightMargin, 0.85 * cm, f"Seite {document.page}")
    canvas.restoreState()


def _manual_styles() -> dict[str, ParagraphStyle]:
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="ManualTitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=24,
        spaceAfter=14,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#1d3557"),
    ))
    styles.add(ParagraphStyle(
        name="ManualHeading1",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=15,
        leading=19,
        spaceBefore=12,
        spaceAfter=7,
        textColor=colors.HexColor("#1d3557"),
    ))
    styles.add(ParagraphStyle(
        name="ManualHeading2",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=15,
        spaceBefore=9,
        spaceAfter=5,
        textColor=colors.HexColor("#264653"),
    ))
    styles.add(ParagraphStyle(
        name="ManualBody",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=9.5,
        leading=13,
        spaceAfter=6,
    ))
    styles.add(ParagraphStyle(
        name="ManualBullet",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=9.5,
        leading=13,
        leftIndent=13,
        firstLineIndent=-10,
        spaceAfter=3,
    ))
    return styles


def _image_flowable(path: Path, max_width: float, max_height: float) -> Image:
    with PilImage.open(path) as source:
        width, height = source.size
    scale = min(max_width / width, max_height / height, 1.0)
    return Image(str(path), width=width * scale, height=height * scale)


def build_pdf(source: Path = SOURCE, target: Path = TARGET) -> None:
    styles = _manual_styles()
    story = []
    document = SimpleDocTemplate(
        str(target),
        pagesize=A4,
        leftMargin=2.0 * cm,
        rightMargin=2.0 * cm,
        topMargin=1.8 * cm,
        bottomMargin=2.0 * cm,
        title="WinWhisperPlus Benutzerhandbuch",
        author="orgAnice Lizenz-Verwaltung UG (haftungsbeschränkt)",
    )

    for raw_line in source.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        image_match = IMAGE_PATTERN.fullmatch(line)
        if image_match:
            image_path = source.parent / image_match.group(1)
            story.append(_image_flowable(image_path, document.width, 10.8 * cm))
            story.append(Spacer(1, 0.22 * cm))
        elif line.startswith("# "):
            story.append(Paragraph(_inline_markup(line[2:]), styles["ManualTitle"]))
        elif line.startswith("## "):
            story.append(Paragraph(_inline_markup(line[3:]), styles["ManualHeading1"]))
        elif line.startswith("### "):
            story.append(Paragraph(_inline_markup(line[4:]), styles["ManualHeading2"]))
        elif line.startswith("- "):
            story.append(Paragraph(f"• {_inline_markup(line[2:])}", styles["ManualBullet"]))
        elif line.startswith("```text") or line == "```":
            continue
        else:
            story.append(Paragraph(_inline_markup(line), styles["ManualBody"]))

    target.parent.mkdir(parents=True, exist_ok=True)
    document.build(story, onFirstPage=_footer, onLaterPages=_footer)


if __name__ == "__main__":
    build_pdf(*(Path(argument) for argument in sys.argv[1:]))
