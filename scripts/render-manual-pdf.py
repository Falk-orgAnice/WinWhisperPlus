"""Build the printable manual from its Markdown source and local screenshots."""
from pathlib import Path
import re
from html import escape
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Preformatted

root = Path(__file__).resolve().parents[1]
source = root / "docs/WinWhisperPlus Benutzerhandbuch.md"
destination = source.with_suffix(".pdf")
pdfmetrics.registerFont(TTFont("Arial", "C:/Windows/Fonts/arial.ttf"))
pdfmetrics.registerFont(TTFont("ArialBold", "C:/Windows/Fonts/arialbd.ttf"))
styles = getSampleStyleSheet()
for style in styles.byName.values():
    style.fontName = "Arial"
for name in ("Title", "Heading1", "Heading2", "Heading3"):
    styles[name].fontName = "ArialBold"
    styles[name].textColor = colors.HexColor("#173754")
    styles[name].keepWithNext = True
styles["BodyText"].fontSize = 10
styles["BodyText"].leading = 14
styles["BodyText"].spaceAfter = 7
styles.add(ParagraphStyle("BulletBody", parent=styles["BodyText"], leftIndent=13, firstLineIndent=-10))
styles.add(ParagraphStyle("CaptionBody", parent=styles["BodyText"], fontSize=8, textColor=colors.HexColor("#526577")))


def inline(text):
    text = escape(text).replace("\u2011", "-").replace("\u2013", "-").replace("\u2014", "-")
    text = re.sub(r"`([^`]+)`", r'<font color="#173754">\1</font>', text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    return re.sub(r"\[([^]]+)\]\(([^)]+)\)", r'<link href="\2" color="#17558a">\1</link>', text)


story, paragraph, code = [], [], None


def flush():
    if paragraph:
        story.append(Paragraph(inline(" ".join(paragraph)), styles["BodyText"]))
        paragraph.clear()


for line in source.read_text(encoding="utf-8").splitlines():
    if line.startswith("```"):
        flush()
        if code is None:
            code = []
        else:
            story.append(Preformatted("\n".join(code), styles["Code"]))
            story.append(Spacer(1, 7))
            code = None
        continue
    if code is not None:
        code.append(line)
        continue
    if not line.strip():
        flush()
        continue
    heading = re.match(r"^(#{1,3}) (.*)", line)
    image = re.match(r"!\[([^]]*)\]\(([^)]+)\)", line)
    if heading:
        flush()
        level = len(heading[1])
        story.append(Paragraph(inline(heading[2]), styles["Title" if level == 1 else f"Heading{level - 1}"]))
    elif image:
        flush()
        picture = Image(str(source.parent / image[2]))
        scale = min(1, 470 / picture.imageWidth, 370 / picture.imageHeight)
        picture.drawWidth = picture.imageWidth * scale
        picture.drawHeight = picture.imageHeight * scale
        story += [picture, Spacer(1, 4), Paragraph(inline(image[1]), styles["CaptionBody"])]
    elif line.startswith("- "):
        flush()
        story.append(Paragraph("- " + inline(line[2:]), styles["BulletBody"]))
    else:
        paragraph.append(line)
flush()


def footer(canvas, document):
    canvas.saveState()
    canvas.setFont("Arial", 8)
    canvas.setFillColor(colors.HexColor("#526577"))
    canvas.drawString(50, 28, "WinWhisperPlus 1.2.0 - Benutzerhandbuch")
    canvas.drawRightString(A4[0] - 50, 28, str(document.page))
    canvas.restoreState()


SimpleDocTemplate(str(destination), pagesize=A4, leftMargin=50, rightMargin=50,
                  topMargin=42, bottomMargin=45, title="WinWhisperPlus Benutzerhandbuch 1.2.0",
                  author="WinWhisperPlus").build(story, onFirstPage=footer, onLaterPages=footer)
print(destination)
