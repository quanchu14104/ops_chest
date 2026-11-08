"""Xuat don dat hang PDF (reportlab). Can font TTF co dau tieng Viet (DejaVu/Arial)."""
from __future__ import annotations

import io
import logging
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.config import settings

log = logging.getLogger(__name__)

_CANDIDATES = [
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
    ("/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
]
_font: tuple[str, str] | None = None


def _fonts() -> tuple[str, str]:
    global _font
    if _font:
        return _font
    cands = list(_CANDIDATES)
    if settings.pdf_font_path:
        cands.insert(0, (settings.pdf_font_path, settings.pdf_font_path))
    for reg, bold in cands:
        if Path(reg).exists():
            pdfmetrics.registerFont(TTFont("VN", reg))
            pdfmetrics.registerFont(TTFont("VN-Bold", bold if Path(bold).exists() else reg))
            _font = ("VN", "VN-Bold")
            return _font
    log.warning("Không tìm thấy font tiếng Việt, PDF sẽ lỗi dấu. Đặt PDF_FONT_PATH trong .env.")
    _font = ("Helvetica", "Helvetica-Bold")
    return _font


def _money(v) -> str:
    return f"{int(v):,}".replace(",", ".")


def purchase_order_pdf(code: str, supplier: dict, order_date: str, expected_date: str, lines: list[dict],
                       total: int, approved_by: str, note: str | None = None) -> bytes:
    reg, bold = _fonts()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm,
                            bottomMargin=16 * mm, title=f"Đơn đặt hàng {code}")
    h = ParagraphStyle("h", fontName=bold, fontSize=16, leading=20)
    n = ParagraphStyle("n", fontName=reg, fontSize=10, leading=14)
    story = [
        Paragraph(settings.store_name, ParagraphStyle("s", fontName=bold, fontSize=11, leading=14)),
        Paragraph(f"{settings.store_address} · ĐT {settings.store_phone}", n),
        Spacer(1, 8 * mm),
        Paragraph(f"ĐƠN ĐẶT HÀNG {code}", h),
        Spacer(1, 3 * mm),
        Paragraph(f"Nhà cung cấp: <b>{supplier['name']}</b> ({supplier.get('code', '')}) · {supplier.get('email', '')}", n),
        Paragraph(f"Ngày đặt: {order_date} · Ngày giao đề nghị: <b>{expected_date}</b>", n),
        Spacer(1, 5 * mm),
    ]
    data = [["#", "Mã hàng", "Tên hàng", "SL", "Đơn giá", "Thành tiền"]]
    for i, l in enumerate(lines, 1):
        data.append([str(i), l["sku"], Paragraph(l["name"], n), str(l["qty"]), _money(l["unit_cost"]),
                     _money(l["qty"] * l["unit_cost"])])
    data.append(["", "", "", "", "Tổng cộng", _money(total)])
    t = Table(data, colWidths=[8 * mm, 20 * mm, 72 * mm, 14 * mm, 24 * mm, 28 * mm], repeatRows=1)
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), reg),
        ("FONTNAME", (0, 0), (-1, 0), bold),
        ("FONTNAME", (0, -1), (-1, -1), bold),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef1f4")),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.HexColor("#1f2328")),
        ("LINEABOVE", (0, -1), (-1, -1), 0.6, colors.HexColor("#1f2328")),
        ("ALIGN", (3, 1), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#f8f9fa")]),
    ]))
    story += [t, Spacer(1, 6 * mm)]
    if note:
        story.append(Paragraph(f"Ghi chú: {note}", n))
    story += [
        Spacer(1, 10 * mm),
        Paragraph(f"Người duyệt: <b>{approved_by}</b> (Store Manager)", n),
        Paragraph("Đơn do hệ thống Ops Chest đề xuất và đã được Store Manager duyệt trước khi gửi.",
                  ParagraphStyle("f", fontName=reg, fontSize=8, textColor=colors.HexColor("#656d76"))),
    ]
    doc.build(story)
    return buf.getvalue()
