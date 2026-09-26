"""Build publication-grade PDFs for the paper and the business plan.

Parses the markdown sources under docs/ and renders them with reportlab:

- paper (学术排版): 宋体正文 + 黑体标题、摘要块、三线表、表题居中、
  参考文献悬挂缩进、居中页码；
- business (商业排版): 封面页（标题/副题/声明框/版本信息）、微软雅黑、
  品牌色标题与浅色表格、页脚（文档名 + 页码）。

Usage:
    python scripts/build_documents.py            # regenerate both PDFs
    python scripts/build_documents.py --png DIR  # also render review PNGs

Requires: pip install reportlab pymupdf (not part of the test requirements).
The markdown files remain the single source of truth; edit them and rerun.
"""
from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate, Frame, HRFlowable, KeepTogether, PageBreak, PageTemplate,
    Paragraph, Preformatted, Spacer, Table, TableStyle,
)

ROOT = Path(__file__).resolve().parents[1]
PAPER_MD = ROOT / "docs" / "paper" / "payment-agent-security-rsi.md"
PAPER_PDF = ROOT / "docs" / "paper" / "payment-agent-security-rsi.pdf"
BUSINESS_MD = ROOT / "docs" / "business" / "redteam-business-plan.md"
BUSINESS_PDF = ROOT / "docs" / "business" / "redteam-business-plan.pdf"

INK = colors.HexColor("#1a1a1a")
ACCENT = colors.HexColor("#1f3864")
RULE = colors.HexColor("#404040")
SOFT = colors.HexColor("#d5dae2")
FILL = colors.HexColor("#eef1f6")
MUTED = colors.HexColor("#595959")

# Set by the active renderer so inline() can pick a CJK-capable font for
# code spans that contain Chinese (base-14 Courier has no CJK glyphs).
CJK_BODY_FONT = "Song"


def register_fonts() -> None:
    pdfmetrics.registerFont(TTFont("Song", "C:/Windows/Fonts/simsun.ttc", subfontIndex=0))
    pdfmetrics.registerFont(TTFont("Hei", "C:/Windows/Fonts/simhei.ttf"))
    pdfmetrics.registerFont(TTFont("Yahei", "C:/Windows/Fonts/msyh.ttc", subfontIndex=0))
    pdfmetrics.registerFont(TTFont("YaheiBold", "C:/Windows/Fonts/msyhbd.ttc", subfontIndex=0))
    pdfmetrics.registerFontFamily("Song", normal="Song", bold="Hei", italic="Song", boldItalic="Hei")
    pdfmetrics.registerFontFamily("Yahei", normal="Yahei", bold="YaheiBold",
                                  italic="Yahei", boldItalic="YaheiBold")


# --------------------------------------------------------------------- parser


@dataclass
class Block:
    kind: str            # h1|h2|h3|p|quote|code|table|li|hr
    text: str = ""
    meta: object = None  # list items: number; table: rows


def parse_markdown(text: str) -> list[Block]:
    blocks: list[Block] = []
    lines = text.replace("\r\n", "\n").split("\n")
    index, paragraph = 0, []

    def flush_paragraph():
        if paragraph:
            blocks.append(Block("p", " ".join(paragraph).strip()))
            paragraph.clear()

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if stripped.startswith("<div") or stripped.startswith("</div"):
            index += 1
            continue
        if not stripped:
            flush_paragraph()
            index += 1
            continue
        if stripped.startswith("```"):
            flush_paragraph()
            index += 1
            code = []
            while index < len(lines) and not lines[index].strip().startswith("```"):
                code.append(lines[index])
                index += 1
            blocks.append(Block("code", "\n".join(code).strip("\n")))
            index += 1
            continue
        if stripped.startswith("|"):
            flush_paragraph()
            rows = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                row = [cell.strip() for cell in lines[index].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{3,}:?", cell) for cell in row):
                    rows.append(row)
                index += 1
            blocks.append(Block("table", meta=rows))
            continue
        if stripped.startswith("###"):
            flush_paragraph()
            blocks.append(Block("h3", stripped.lstrip("#").strip()))
            index += 1
            continue
        if stripped.startswith("##"):
            flush_paragraph()
            blocks.append(Block("h2", stripped.lstrip("#").strip()))
            index += 1
            continue
        if stripped.startswith("#"):
            flush_paragraph()
            blocks.append(Block("h1", stripped.lstrip("#").strip()))
            index += 1
            continue
        elif stripped.startswith(">"):
            flush_paragraph()
            quote = []
            while index < len(lines) and lines[index].strip().startswith(">"):
                quote.append(lines[index].strip().lstrip(">").strip())
                index += 1
            blocks.append(Block("quote", " ".join(q for q in quote if q)))
            continue
        if re.fullmatch(r"-{3,}", stripped):
            flush_paragraph()
            blocks.append(Block("hr"))
            index += 1
            continue
        match = re.match(r"^(\d+)\.\s+(.*)", stripped)
        if match:
            flush_paragraph()
            blocks.append(Block("li", match.group(2), meta=int(match.group(1))))
            index += 1
            continue
        if stripped.startswith("- "):
            flush_paragraph()
            blocks.append(Block("li", stripped[2:].strip(), meta=None))
            index += 1
            continue
        paragraph.append(stripped)
        index += 1
    flush_paragraph()
    return blocks


def inline(text: str) -> str:
    """Markdown inline markup -> reportlab intra-paragraph XML."""
    t = escape(text)
    codes: list[str] = []

    def keep_code(match: re.Match) -> str:
        codes.append(match.group(1))
        return f"\x00{len(codes) - 1}\x01"

    t = re.sub(r"`([^`]+)`", keep_code, t)
    t = re.sub(
        r"\[([^\]]+)\]\((https?://[^)]+)\)",
        lambda m: f'<link href="{m.group(2)}" color="#1a56a0"><u>{m.group(1)}</u></link>',
        t,
    )
    t = re.sub(
        r"(?<![\w\"'>=/])(https?://[^\s<>）)，；」』\]]+)",
        lambda m: f'<link href="{m.group(1)}" color="#1a56a0"><u>{m.group(1)}</u></link>',
        t,
    )
    t = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<i>\1</i>", t)
    t = re.sub(
        r"\x00(\d+)\x01",
        lambda m: (
            f'<font face="{CJK_BODY_FONT}">{escape(codes[int(m.group(1))])}</font>'
            if any(ord(ch) > 0x2E80 for ch in codes[int(m.group(1))])
            else f'<font face="Courier" size="8.3">{escape(codes[int(m.group(1))])}</font>'
        ),
        t,
    )
    return t


def plain_length(text: str) -> float:
    text = re.sub(r"`([^`]+)`|\*\*([^*]+)\*\*|\[([^\]]+)\]\([^)]+\)", lambda m: m.group(1) or m.group(2) or m.group(3), text)
    return sum(2.0 if ord(ch) > 0x2E80 else 1.0 for ch in text)


# ------------------------------------------------------------------- renderer


def col_widths(rows: list[list[str]], total: float) -> list[float]:
    columns = len(rows[0])
    weights = []
    for column in range(columns):
        longest = max((plain_length(row[column]) if column < len(row) else 0.0)
                      for row in rows)
        weights.append(max(longest, 6.0))
    bounded = [min(weight, 90.0) for weight in weights]
    scale = total / sum(bounded)
    widths = [max(w * scale, total * 0.06) for w in bounded]
    over = sum(widths) - total
    widest = widths.index(max(widths))
    widths[widest] -= over
    return widths


def caption_of(text: str) -> str | None:
    if re.match(r"^表\s*\d+", text):
        return text
    return None


def make_table(rows: list[list[str]], profile: str, available: float) -> Table:
    widths = col_widths(rows, available)
    body_style = ParagraphStyle(
        "cell", fontName="Song" if profile == "paper" else "Yahei",
        fontSize=9.3, leading=13.5, wordWrap="CJK",
        alignment=TA_LEFT,
    )
    head_style = ParagraphStyle(
        "cellh", parent=body_style, fontName="Hei" if profile == "paper" else "YaheiBold",
        alignment=TA_CENTER,
    )
    data = []
    for r, row in enumerate(rows):
        style = head_style if r == 0 else body_style
        data.append([Paragraph(inline(cell), style) for cell in row])
    table = Table(data, colWidths=widths, repeatRows=1, hAlign="CENTER")
    if profile == "paper":
        table.setStyle(TableStyle([
            ("LINEABOVE", (0, 0), (-1, 0), 1.1, RULE),
            ("LINEBELOW", (0, 0), (-1, 0), 0.6, RULE),
            ("LINEBELOW", (0, -1), (-1, -1), 1.1, RULE),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
    else:
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), FILL),
            ("LINEBELOW", (0, 0), (-1, -2), 0.4, SOFT),
            ("LINEBELOW", (0, -1), (-1, -1), 0.8, ACCENT),
            ("LINEABOVE", (0, 0), (-1, 0), 0.8, ACCENT),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
    return table


class DocumentBuilder:
    def __init__(self, profile: str, title_footer: str) -> None:
        self.profile = profile
        self.title_footer = title_footer
        if profile == "paper":
            self.body = ParagraphStyle(
                "paper-body", fontName="Song", fontSize=10.5, leading=17.5,
                firstLineIndent=21, alignment=TA_JUSTIFY, wordWrap="CJK",
                spaceAfter=3, textColor=INK,
            )
            self.plain = ParagraphStyle("paper-plain", parent=self.body, firstLineIndent=0)
            self.h2 = ParagraphStyle("paper-h2", fontName="Hei", fontSize=13, leading=18,
                                     spaceBefore=16, spaceAfter=8, keepWithNext=1, textColor=INK)
            self.h3 = ParagraphStyle("paper-h3", fontName="Hei", fontSize=11, leading=16,
                                     spaceBefore=10, spaceAfter=5, keepWithNext=1, textColor=INK)
            self.small = 9.3
        else:
            self.body = ParagraphStyle(
                "biz-body", fontName="Yahei", fontSize=10.3, leading=17,
                alignment=TA_JUSTIFY, wordWrap="CJK", spaceAfter=7, textColor=INK,
            )
            self.plain = self.body
            self.h2 = ParagraphStyle("biz-h2", fontName="YaheiBold", fontSize=13, leading=18,
                                     spaceBefore=16, spaceAfter=8, keepWithNext=1, textColor=ACCENT)
            self.h3 = ParagraphStyle("biz-h3", fontName="YaheiBold", fontSize=11, leading=16,
                                     spaceBefore=10, spaceAfter=5, keepWithNext=1, textColor=INK)
            self.small = 9.3

    # -- flowable factories -------------------------------------------------

    def paragraph(self, text: str, *, indent: bool = True, size: float | None = None,
                  leading: float | None = None, align=None, color=None,
                  left: float = 0, right: float = 0, space_after: float | None = None,
                  keep: int = 0) -> Paragraph:
        style = ParagraphStyle(
            f"p{abs(hash(text)) % 99999}", parent=self.body,
            firstLineIndent=(self.body.firstLineIndent if indent else 0),
            fontSize=size or self.body.fontSize,
            leading=leading or (size + 7 if size else self.body.leading),
            alignment=align if align is not None else self.body.alignment,
            textColor=color or self.body.textColor,
            leftIndent=left, rightIndent=right, keepWithNext=keep,
            spaceAfter=self.body.spaceAfter if space_after is None else space_after,
        )
        return Paragraph(inline(text), style)

    def heading(self, level: int, text: str) -> Paragraph:
        style = self.h2 if level == 2 else self.h3
        return Paragraph(inline(text), style)

    def caption(self, text: str) -> Paragraph:
        style = ParagraphStyle(
            "caption", fontName="Hei" if self.profile == "paper" else "YaheiBold",
            fontSize=9.3, leading=13, alignment=TA_CENTER, keepWithNext=1,
            spaceBefore=8, spaceAfter=4, textColor=INK,
        )
        return Paragraph(inline(text), style)

    def code_block(self, text: str, available: float) -> Table:
        style = ParagraphStyle(
            "code", fontName="Song" if self.profile == "paper" else "Yahei",
            fontSize=8.6, leading=13, wordWrap="CJK", textColor=INK,
        )
        rendered = "<br/>".join(inline(line) for line in text.split("\n"))
        body = Table([[Paragraph(rendered, style)]], colWidths=[available])
        body.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f6f7f9")),
            ("BOX", (0, 0), (-1, -1), 0.4, SOFT),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ]))
        return body

    def quote_block(self, text: str, available: float, *, big: bool = False) -> Table:
        style = ParagraphStyle(
            "quote", parent=self.plain, fontSize=9.4 if not big else 10,
            leading=15 if not big else 16.5, textColor=MUTED,
            alignment=TA_LEFT, wordWrap="CJK",
        )
        body = Table([[Paragraph(inline(text), style)]], colWidths=[available])
        body.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f7f8fa")),
            ("LINEBEFORE", (0, 0), (0, -1), 2.2, ACCENT if self.profile != "paper" else RULE),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ("LEFTPADDING", (0, 0), (-1, -1), 12),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ]))
        return body

    def list_item(self, number: int | None, text: str, available: float) -> Paragraph:
        marker = f"{number}." if number is not None else "•"
        style = ParagraphStyle(
            f"li{abs(hash(text)) % 99999}", parent=self.plain,
            leftIndent=22, firstLineIndent=-14,
            spaceAfter=max(self.body.spaceAfter - 1, 2),
        )
        return Paragraph(f"{marker}&nbsp;&nbsp;{inline(text)}", style)

    def reference_item(self, text: str) -> Paragraph:
        style = ParagraphStyle(
            f"ref{abs(hash(text)) % 99999}", parent=self.plain,
            fontSize=9.2, leading=14.5, leftIndent=18, firstLineIndent=-18,
            spaceAfter=4, alignment=TA_LEFT,
        )
        return Paragraph(inline(text), style)


def build_paper(md_text: str, path: Path) -> None:
    builder = DocumentBuilder("paper", "payment-agent-security-rsi")
    blocks = parse_markdown(md_text)
    page_w, _page_h = A4
    margin_lr, margin_tb = 2.7 * cm, 2.5 * cm
    available = page_w - 2 * margin_lr
    story: list = []

    # -- title block: H1, author lines, source note
    index = 0
    while index < len(blocks):
        block = blocks[index]
        if block.kind == "h1":
            story.append(Spacer(1, 10))
            story.append(Paragraph(inline(block.text), ParagraphStyle(
                "title", fontName="Hei", fontSize=16.5, leading=25,
                alignment=TA_CENTER, textColor=INK, spaceAfter=10)))
        elif block.kind == "p":
            centered = ParagraphStyle(
                "author", fontName="Song", fontSize=11.5, leading=18,
                alignment=TA_CENTER, textColor=INK, spaceAfter=2)
            for line in block.text.split("\n"):
                story.append(Paragraph(inline(line), centered))
        elif block.kind == "quote":
            story.append(Spacer(1, 4))
            story.append(Paragraph(inline(block.text), ParagraphStyle(
                "note", fontName="Song", fontSize=9.3, leading=14,
                alignment=TA_CENTER, textColor=MUTED, spaceAfter=6)))
            story.append(HRFlowable(width="100%", thickness=0.5, color=SOFT,
                                    spaceBefore=6, spaceAfter=10))
            index += 1
            break
        index += 1

    # -- body blocks
    in_abstract = False
    abstract_paras: list[Paragraph] = []
    first_section_seen = False
    while index < len(blocks):
        block = blocks[index]
        kind, text = block.kind, block.text
        if kind == "h2":
            if text == "摘要":
                in_abstract = True
                story.append(Paragraph("摘　要", ParagraphStyle(
                    "abslabel", fontName="Hei", fontSize=11.5, leading=16,
                    alignment=TA_CENTER, spaceBefore=4, spaceAfter=6, textColor=INK)))
            else:
                in_abstract = False
                first_section_seen = True
                story.append(builder.heading(2, text))
        elif in_abstract and kind == "p":
            if not caption_of(text):
                story.append(builder.paragraph(
                    text, indent=False, size=9.6, leading=15.5,
                    left=26, right=26, space_after=4))
        elif kind == "p":
            caption = caption_of(text)
            if caption:
                story.append(builder.caption(caption))
            elif re.match(r"^\[\d+\]", text):
                story.append(builder.reference_item(text))
            elif text.startswith("•") or text.startswith("-"):
                story.append(builder.paragraph(text, indent=False))
            else:
                story.append(builder.paragraph(text))
        elif kind == "h3":
            story.append(builder.heading(3, text))
        elif kind == "table":
            rows = block.meta
            story.append(make_table(rows, "paper", available))
            story.append(Spacer(1, 6))
        elif kind == "code":
            story.append(builder.code_block(text, available))
            story.append(Spacer(1, 6))
        elif kind == "quote":
            story.append(builder.quote_block(text, available))
            story.append(Spacer(1, 4))
        elif kind == "li":
            story.append(builder.list_item(block.meta, text, available))
        index += 1

    def footer(canvas, doc) -> None:
        canvas.saveState()
        canvas.setFont("Song", 9)
        canvas.setFillColor(MUTED)
        canvas.drawCentredString(page_w / 2, 1.4 * cm, f"– {doc.page} –")
        canvas.restoreState()

    doc = BaseDocTemplate(
        str(path), pagesize=A4, title="面向支付智能体的对抗评测与经验驱动修复",
        author="黄一民",
        leftMargin=margin_lr, rightMargin=margin_lr,
        topMargin=margin_tb, bottomMargin=margin_tb,
    )
    frame = Frame(margin_lr, margin_tb, available, A4[1] - 2 * margin_tb, id="main")
    doc.addPageTemplates([PageTemplate(id="page", frames=[frame], onPage=footer)])
    doc.build(story)


def build_business(md_text: str, path: Path) -> None:
    global CJK_BODY_FONT
    CJK_BODY_FONT = "Yahei"
    builder = DocumentBuilder("business", "REDTEAM 商业计划书")
    blocks = parse_markdown(md_text)
    page_w, page_h = A4
    margin_lr, margin_tb = 2.4 * cm, 2.3 * cm
    available = page_w - 2 * margin_lr

    # ---- cover
    cover: list = []
    title_text = next(b.text for b in blocks if b.kind == "h1")
    subtitle = next(b.text for b in blocks if b.kind == "h2")
    disclaimer = next(b.text for b in blocks if b.kind == "quote")
    display_title = re.sub(r"^REDTEAM\s*", "", title_text) or title_text
    cover.append(Spacer(1, 3.2 * cm))
    cover.append(HRFlowable(width="30%", thickness=2.2, color=ACCENT, hAlign="LEFT"))
    cover.append(Spacer(1, 0.8 * cm))
    cover.append(Paragraph("REDTEAM", ParagraphStyle(
        "brand", fontName="YaheiBold", fontSize=26, leading=34, textColor=ACCENT)))
    cover.append(Spacer(1, 0.5 * cm))
    cover.append(Paragraph(inline(display_title), ParagraphStyle(
        "covtitle", fontName="YaheiBold", fontSize=20, leading=30, textColor=INK)))
    cover.append(Spacer(1, 0.4 * cm))
    cover.append(Paragraph(inline(subtitle), ParagraphStyle(
        "covsub", fontName="Yahei", fontSize=13, leading=20, textColor=MUTED)))
    cover.append(Spacer(1, 1.6 * cm))
    cover.append(builder.quote_block(disclaimer, available * 0.94, big=True))
    cover.append(Spacer(1, 2.2 * cm))
    meta_style = ParagraphStyle("meta", fontName="Yahei", fontSize=10.5, leading=19, textColor=INK)
    for line in ("文档类型：商业计划书（讨论稿 · 拟议方案）",
                 "版本：v1.0",
                 "日期：2026 年 9 月 27 日",
                 "研究原型：github.com/Fishman-free/REDTEAM"):
        cover.append(Paragraph(inline(line), meta_style))
    cover.append(Spacer(1, 2.0 * cm))
    cover.append(HRFlowable(width="100%", thickness=0.6, color=SOFT))

    # ---- body
    story: list = cover + [PageBreak()]
    for block in blocks:
        kind, text = block.kind, block.text
        if kind in {"h1", "h2"} and text in {title_text, subtitle}:
            continue
        if kind == "quote" and text == disclaimer:
            continue
        if kind == "h1":
            continue
        if kind == "h2":
            story.append(builder.heading(2, text))
        elif kind == "h3":
            story.append(builder.heading(3, text))
        elif kind == "p":
            if caption_of(text):
                story.append(builder.caption(text))
            else:
                story.append(builder.paragraph(text))
        elif kind == "table":
            story.append(make_table(block.meta, "business", available))
            story.append(Spacer(1, 8))
        elif kind == "code":
            story.append(builder.code_block(text, available))
            story.append(Spacer(1, 8))
        elif kind == "quote":
            story.append(builder.quote_block(text, available))
            story.append(Spacer(1, 6))
        elif kind == "li":
            story.append(builder.list_item(block.meta, text, available))

    def footer(canvas, doc) -> None:
        if doc.page == 1:
            return
        canvas.saveState()
        canvas.setStrokeColor(SOFT)
        canvas.setLineWidth(0.5)
        canvas.line(margin_lr, 1.65 * cm, page_w - margin_lr, 1.65 * cm)
        canvas.setFont("Yahei", 8)
        canvas.setFillColor(MUTED)
        canvas.drawString(margin_lr, 1.15 * cm, "REDTEAM 商业计划书 · 拟议方案讨论稿")
        canvas.drawRightString(page_w - margin_lr, 1.15 * cm, f"第 {doc.page} 页")
        canvas.restoreState()

    doc = BaseDocTemplate(
        str(path), pagesize=A4, title="REDTEAM 商业计划书", author="REDTEAM",
        leftMargin=margin_lr, rightMargin=margin_lr,
        topMargin=margin_tb, bottomMargin=margin_tb,
    )
    frame = Frame(margin_lr, margin_tb, available, page_h - 2 * margin_tb, id="main")
    doc.addPageTemplates([PageTemplate(id="page", frames=[frame], onPage=footer)])
    doc.build(story)


def render_png(pdf_paths: list[Path], out_dir: Path, dpi: int = 100) -> list[Path]:
    import pymupdf

    out_dir.mkdir(parents=True, exist_ok=True)
    rendered = []
    for pdf_path in pdf_paths:
        document = pymupdf.open(pdf_path)
        stem = pdf_path.stem[:24]
        for number, page in enumerate(document, start=1):
            target = out_dir / f"{stem}-p{number:02d}.png"
            page.get_pixmap(dpi=dpi).save(target)
            rendered.append(target)
    return rendered


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--png", type=Path, default=None, help="render review PNGs to DIR")
    args = parser.parse_args()
    register_fonts()
    build_paper(PAPER_MD.read_text(encoding="utf-8"), PAPER_PDF)
    build_business(BUSINESS_MD.read_text(encoding="utf-8"), BUSINESS_PDF)
    print(f"built {PAPER_PDF.name}, {BUSINESS_PDF.name}")
    if args.png:
        rendered = render_png([PAPER_PDF, BUSINESS_PDF], args.png)
        print(f"rendered {len(rendered)} review pages to {args.png}")


if __name__ == "__main__":
    main()
