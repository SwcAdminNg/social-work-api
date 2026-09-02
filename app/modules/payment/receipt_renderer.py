"""Renders a course payment `Transaction` into a plain, Stripe-style portrait
A4 PDF receipt, using reportlab for vector drawing/text (crisp at any zoom,
tiny file size) — same rendering approach as the certificate renderer.
"""

import io
from pathlib import Path

import httpx
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from app.core.config import settings

PAGE_WIDTH, PAGE_HEIGHT = A4

TEXT = HexColor("#1A1A1A")
MUTED = HexColor("#6B7280")
FAINT = HexColor("#9CA3AF")
BORDER = HexColor("#E5E7EB")
GREEN = HexColor("#15803D")
WATERMARK = HexColor("#0B3D2E")


def _naira_glyph_width(pdf: canvas.Canvas, font: str, size: float) -> float:
    """The base-14 PDF fonts have no glyph for U+20A6 (₦) - it renders as a
    .notdef box. Draw it as a bold vector glyph instead: an 'N' with two
    horizontal strike bars, the standard way to render Naira where the font
    doesn't support it. Width matches the 'N' glyph it's built from."""
    return pdf.stringWidth("N", font, size)


def _draw_naira_glyph(pdf: canvas.Canvas, x: float, y: float, font: str, size: float) -> float:
    pdf.setFont(font, size)
    pdf.drawString(x, y, "N")
    width = pdf.stringWidth("N", font, size)

    cap_height = size * 0.66
    pdf.setLineWidth(max(0.7, size * 0.05))
    for fraction in (0.32, 0.56):
        bar_y = y + cap_height * fraction
        pdf.line(x - width * 0.08, bar_y, x + width * 1.08, bar_y)

    return width


def _draw_amount_left(pdf: canvas.Canvas, x: float, y: float, amount: float, font: str, size: float, color) -> float:
    pdf.setFillColor(color)
    pdf.setStrokeColor(color)
    naira_w = _draw_naira_glyph(pdf, x, y, font, size)
    gap = size * 0.08
    amount_str = f"{amount:,.2f}"
    pdf.setFont(font, size)
    pdf.drawString(x + naira_w + gap, y, amount_str)
    return naira_w + gap + pdf.stringWidth(amount_str, font, size)


def _draw_amount_right(pdf: canvas.Canvas, x_right: float, y: float, amount: float, font: str, size: float, color) -> float:
    amount_str = f"{amount:,.2f}"
    naira_w = _naira_glyph_width(pdf, font, size)
    gap = size * 0.08
    amount_w = pdf.stringWidth(amount_str, font, size)
    total_w = naira_w + gap + amount_w

    x_start = x_right - total_w
    pdf.setFillColor(color)
    pdf.setStrokeColor(color)
    _draw_naira_glyph(pdf, x_start, y, font, size)
    pdf.setFont(font, size)
    pdf.drawString(x_start + naira_w + gap, y, amount_str)
    return total_w


def _fetch_logo() -> ImageReader | None:
    local_path = Path(settings.company_logo_path) if settings.company_logo_path else None
    if local_path and local_path.is_file():
        try:
            return ImageReader(str(local_path))
        except Exception:
            pass

    if not settings.company_logo_url:
        return None
    try:
        response = httpx.get(settings.company_logo_url, timeout=10.0, headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
        return ImageReader(io.BytesIO(response.content))
    except Exception:
        # A broken/unreachable logo must never fail receipt generation.
        return None


def render_payment_receipt_pdf(
    recipient_name: str,
    recipient_email: str,
    items: list[dict],
    subtotal_amount: float,
    discount_amount: float,
    total_amount: float,
    reference: str,
    payment_date_str: str,
    payment_method: str,
    coupon_code: str | None = None,
) -> bytes:
    """`items` is a list of `{"title": str, "unit_price": float}` - one row per
    course (1 for a single-course purchase, N for a cart checkout)."""
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)

    margin = 56
    content_width = PAGE_WIDTH - 2 * margin

    # -- faint diagonal watermark, drawn first so everything sits above it --
    pdf.saveState()
    pdf.translate(PAGE_WIDTH / 2, PAGE_HEIGHT / 2)
    pdf.rotate(38)
    pdf.setFillColor(WATERMARK)
    pdf.setFillAlpha(0.045)
    pdf.setFont("Helvetica-Bold", 150)
    pdf.drawCentredString(0, 0, "PAID")
    pdf.restoreState()

    cursor_y = PAGE_HEIGHT - 66

    # -- logo (large and bold, the header's dominant element) ------------------
    logo = _fetch_logo()
    if logo is not None:
        logo_w_px, logo_h_px = logo.getSize()
        logo_h = 70
        logo_w = logo_h * (logo_w_px / logo_h_px) if logo_h_px else 0
        pdf.drawImage(logo, margin, cursor_y - logo_h, width=logo_w, height=logo_h, mask="auto", preserveAspectRatio=True)
    else:
        pdf.setFillColor(TEXT)
        pdf.setFont("Helvetica-Bold", 22)
        pdf.drawString(margin, cursor_y - 20, settings.company_name)

    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 9)
    pdf.drawRightString(PAGE_WIDTH - margin, cursor_y - 6, payment_date_str)

    cursor_y -= 96

    # -- "Receipt from ..." heading -------------------------------------------
    pdf.setFillColor(TEXT)
    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawString(margin, cursor_y, f"Receipt from {settings.company_name}")

    cursor_y -= 20
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 9.5)
    pdf.drawString(margin, cursor_y, f"Receipt #{reference}")

    cursor_y -= 34

    # -- amount paid ------------------------------------------------------
    amount_w = _draw_amount_left(pdf, margin, cursor_y, total_amount, "Helvetica-Bold", 22, TEXT)
    pdf.setFillColor(GREEN)
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(margin + amount_w + 10, cursor_y + 6, "PAID")

    cursor_y -= 14
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 9.5)
    pdf.drawString(margin, cursor_y, f"Paid on {payment_date_str} using {payment_method}")

    cursor_y -= 30
    pdf.setStrokeColor(BORDER)
    pdf.setLineWidth(1)
    pdf.line(margin, cursor_y, PAGE_WIDTH - margin, cursor_y)

    # -- billed to ----------------------------------------------------------
    cursor_y -= 26
    pdf.setFillColor(FAINT)
    pdf.setFont("Helvetica-Bold", 8)
    pdf.drawString(margin, cursor_y, "BILLED TO")
    cursor_y -= 14
    pdf.setFillColor(TEXT)
    pdf.setFont("Helvetica", 10)
    pdf.drawString(margin, cursor_y, recipient_name)
    cursor_y -= 13
    pdf.setFillColor(MUTED)
    pdf.drawString(margin, cursor_y, recipient_email)

    cursor_y -= 34

    # -- line-item table --------------------------------------------------
    desc_x = margin
    qty_x = margin + content_width * 0.62
    amount_x = PAGE_WIDTH - margin

    pdf.setFillColor(FAINT)
    pdf.setFont("Helvetica-Bold", 8)
    pdf.drawString(desc_x, cursor_y, "DESCRIPTION")
    pdf.drawCentredString(qty_x, cursor_y, "QTY")
    pdf.drawRightString(amount_x, cursor_y, "AMOUNT")

    cursor_y -= 8
    pdf.setStrokeColor(BORDER)
    pdf.setLineWidth(1)
    pdf.line(margin, cursor_y, PAGE_WIDTH - margin, cursor_y)

    for item in items:
        cursor_y -= 22
        pdf.setFillColor(TEXT)
        pdf.setFont("Helvetica", 10.5)
        pdf.drawString(desc_x, cursor_y, item["title"])
        pdf.setFont("Helvetica", 10)
        pdf.drawCentredString(qty_x, cursor_y, "1")
        _draw_amount_right(pdf, amount_x, cursor_y, item["unit_price"], "Helvetica", 10, TEXT)
        pdf.setFillColor(MUTED)
        pdf.setFont("Helvetica", 8.5)
        pdf.drawString(desc_x, cursor_y - 13, "Course enrollment")
        cursor_y -= 13

    cursor_y -= 21
    pdf.setStrokeColor(BORDER)
    pdf.line(margin, cursor_y, PAGE_WIDTH - margin, cursor_y)

    cursor_y -= 22
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 10)
    pdf.drawString(desc_x, cursor_y, "Subtotal")
    _draw_amount_right(pdf, amount_x, cursor_y, subtotal_amount, "Helvetica", 10, MUTED)

    if discount_amount > 0:
        cursor_y -= 20
        pdf.setFillColor(GREEN)
        pdf.setFont("Helvetica", 10)
        label = f"Coupon ({coupon_code})" if coupon_code else "Discount"
        pdf.drawString(desc_x, cursor_y, label)

        dash_w = pdf.stringWidth("-", "Helvetica", 10)
        amount_w = _draw_amount_right(pdf, amount_x, cursor_y, discount_amount, "Helvetica", 10, GREEN)
        pdf.setFillColor(GREEN)
        pdf.setFont("Helvetica", 10)
        pdf.drawString(amount_x - amount_w - dash_w, cursor_y, "-")

    cursor_y -= 20
    pdf.setFillColor(TEXT)
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(desc_x, cursor_y, "Amount paid")
    _draw_amount_right(pdf, amount_x, cursor_y, total_amount, "Helvetica-Bold", 11, TEXT)

    cursor_y -= 12
    pdf.setStrokeColor(BORDER)
    pdf.line(margin, cursor_y, PAGE_WIDTH - margin, cursor_y)

    # -- footer -------------------------------------------------------------
    footer_y = 90
    pdf.setStrokeColor(BORDER)
    pdf.line(margin, footer_y + 24, PAGE_WIDTH - margin, footer_y + 24)

    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 8.5)
    pdf.drawString(margin, footer_y, f"If you have any questions, contact us at {settings.company_support_email}.")
    pdf.setFillColor(FAINT)
    pdf.setFont("Helvetica", 8)
    pdf.drawString(margin, footer_y - 14, settings.company_name)
    pdf.drawString(margin, footer_y - 26, settings.company_address)
    pdf.drawString(margin, footer_y - 38, settings.company_phone)

    pdf.showPage()
    pdf.save()
    return buffer.getvalue()
