"""Build the printable manual from its Markdown source and local screenshots."""
from pathlib import Path
import re
from html import escape
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Preformatted, KeepTogether

root = Path(__file__).resolve().parents[1]
source = root / "docs/WinWhisperPlus Benutzerhandbuch.md"
destination = source.with_suffix(".pdf")
version = (root / "VERSION").read_text(encoding="utf-8").strip()
pdfmetrics.registerFont(TTFont("Arial", "C:/Windows/Fonts/arial.ttf"))
pdfmetrics.registerFont(TTFont("ArialBold", "C:/Windows/Fonts/arialbd.ttf"))
styles = getSampleStyleSheet()
styles["BodyText"].allowWidows = 0
styles["BodyText"].allowOrphans = 0
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
code_intro = None


def flush():
    if paragraph:
        story.append(Paragraph(inline(" ".join(paragraph)), styles["BodyText"]))
        paragraph.clear()


for line in source.read_text(encoding="utf-8").splitlines():
    if line.startswith("```"):
        flush()
        if code is None:
            code_intro = story.pop() if story and isinstance(story[-1], Paragraph) and story[-1].style.name == "BodyText" else None
            code = []
        else:
            story.append(KeepTogether(([code_intro] if code_intro else []) + [Preformatted("\n".join(code), styles["Code"]), Spacer(1, 7)]))
            code_intro = None
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
        story.append(KeepTogether([picture, Spacer(1, 4), Paragraph(inline(image[1]), styles["CaptionBody"])]))
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
    canvas.drawString(50, 28, f"WinWhisperPlus {version} - Benutzerhandbuch")
    canvas.drawRightString(A4[0] - 50, 28, str(document.page))
    canvas.restoreState()


SimpleDocTemplate(str(destination), pagesize=A4, leftMargin=50, rightMargin=50,
                  topMargin=42, bottomMargin=45, title=f"WinWhisperPlus Benutzerhandbuch {version}",
                  author="WinWhisperPlus").build(story, onFirstPage=footer, onLaterPages=footer)
print(destination)
