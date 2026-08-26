"""Renders a `CertificateTemplate` + completion data into a polished landscape
PDF certificate, using reportlab for vector drawing/text (crisp at any zoom,
tiny file size) and Pillow only for downloading/decoding uploaded logo/signature
images so they can be embedded.
"""

import io

import httpx
from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import landscape, A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from app.modules.certificate.entity import CertificateBorderStyleEnum

PAGE_SIZE = landscape(A4)
PAGE_WIDTH, PAGE_HEIGHT = PAGE_SIZE


def _fetch_image(url: str | None) -> ImageReader | None:
    if not url:
        return None
    try:
        response = httpx.get(url, timeout=10.0)
        response.raise_for_status()
        return ImageReader(io.BytesIO(response.content))
    except Exception:
        # A broken/unreachable image must never fail certificate generation -
        # the certificate is simply rendered without it.
        return None


def _wrap_text(pdf: canvas.Canvas, text: str, font_name: str, font_size: int, max_width: float) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if pdf.stringWidth(candidate, font_name, font_size) <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _draw_border(pdf: canvas.Canvas, primary: colors.Color, accent: colors.Color, style: CertificateBorderStyleEnum) -> None:
    margin = 24
    if style == CertificateBorderStyleEnum.NONE:
        return
    if style == CertificateBorderStyleEnum.MODERN:
        pdf.setStrokeColor(accent)
        pdf.setLineWidth(3)
        pdf.rect(margin, margin, PAGE_WIDTH - 2 * margin, PAGE_HEIGHT - 2 * margin)
        return
    # CLASSIC - an ornate double frame: a thick outer line in the primary color
    # and a slim inset accent line, with small corner flourishes.
    pdf.setStrokeColor(primary)
    pdf.setLineWidth(6)
    pdf.rect(margin, margin, PAGE_WIDTH - 2 * margin, PAGE_HEIGHT - 2 * margin)
    inset = margin + 12
    pdf.setStrokeColor(accent)
    pdf.setLineWidth(1.5)
    pdf.rect(inset, inset, PAGE_WIDTH - 2 * inset, PAGE_HEIGHT - 2 * inset)

    corner = 26
    pdf.setLineWidth(2)
    for cx, cy, dx, dy in (
        (inset, inset, 1, 1),
        (PAGE_WIDTH - inset, inset, -1, 1),
        (inset, PAGE_HEIGHT - inset, 1, -1),
        (PAGE_WIDTH - inset, PAGE_HEIGHT - inset, -1, -1),
    ):
        pdf.line(cx, cy, cx + dx * corner, cy)
        pdf.line(cx, cy, cx, cy + dy * corner)


def _draw_circular_image(
    pdf: canvas.Canvas,
    image: ImageReader,
    center_x: float,
    center_y: float,
    diameter: float,
    border_color: colors.Color,
) -> None:
    image_width, image_height = image.getSize()
    if not image_width or not image_height:
        return

    scale = max(diameter / image_width, diameter / image_height)
    draw_width = image_width * scale
    draw_height = image_height * scale
    draw_x = center_x - draw_width / 2
    draw_y = center_y - draw_height / 2
    radius = diameter / 2

    pdf.saveState()
    clip_path = pdf.beginPath()
    clip_path.circle(center_x, center_y, radius)
    pdf.clipPath(clip_path, stroke=0, fill=0)
    pdf.drawImage(image, draw_x, draw_y, width=draw_width, height=draw_height, mask="auto")
    pdf.restoreState()

    pdf.setStrokeColor(border_color)
    pdf.setLineWidth(2)
    pdf.circle(center_x, center_y, radius, stroke=1, fill=0)


def render_certificate_pdf(
    template,
    recipient_name: str,
    course_title: str,
    completion_date_str: str,
    instructor_name: str,
    certificate_number: str,
    verification_code: str,
    verify_url: str,
    student_profile_picture_url: str | None = None,
) -> bytes:
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=PAGE_SIZE)

    primary = HexColor(template.primary_color)
    accent = HexColor(template.accent_color)
    background = HexColor(template.background_color)
    text_color = HexColor(template.text_color)
    font = template.font_family if template.font_family in (
        "Helvetica", "Helvetica-Bold", "Times-Roman", "Times-Bold", "Courier", "Courier-Bold",
    ) else "Helvetica"
    font_bold = font if font.endswith("Bold") else f"{font}-Bold" if f"{font}-Bold" in (
        "Helvetica-Bold", "Times-Bold", "Courier-Bold",
    ) else "Helvetica-Bold"

    pdf.setFillColor(background)
    pdf.rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT, fill=1, stroke=0)

    _draw_border(pdf, primary, accent, template.border_style)

    student_image = _fetch_image(student_profile_picture_url)
    if student_image is not None:
        _draw_circular_image(
            pdf,
            student_image,
            center_x=PAGE_WIDTH - 86,
            center_y=PAGE_HEIGHT - 86,
            diameter=72,
            border_color=accent,
        )

    center_x = PAGE_WIDTH / 2
    cursor_y = PAGE_HEIGHT - 90

    logo_image = _fetch_image(template.logo_url)
    if logo_image is not None:
        logo_size = 64
        pdf.drawImage(
            logo_image, center_x - logo_size / 2, cursor_y - logo_size + 10,
            width=logo_size, height=logo_size, preserveAspectRatio=True, mask="auto",
        )
        cursor_y -= logo_size + 18

    pdf.setFillColor(primary)
    pdf.setFont(font_bold, 13)
    pdf.drawCentredString(center_x, cursor_y, template.organization_name.upper())
    cursor_y -= 40

    pdf.setFillColor(accent)
    pdf.setFont(font_bold, 34)
    pdf.drawCentredString(center_x, cursor_y, template.title_text)
    cursor_y -= 14
    pdf.setStrokeColor(accent)
    pdf.setLineWidth(1.5)
    pdf.line(center_x - 130, cursor_y, center_x + 130, cursor_y)
    cursor_y -= 36

    if template.subtitle_text:
        pdf.setFillColor(text_color)
        pdf.setFont(font, 13)
        pdf.drawCentredString(center_x, cursor_y, template.subtitle_text)
        cursor_y -= 46

    pdf.setFillColor(primary)
    pdf.setFont(font_bold, 40)
    pdf.drawCentredString(center_x, cursor_y, recipient_name)
    cursor_y -= 10
    pdf.setStrokeColor(primary)
    pdf.setLineWidth(1)
    pdf.line(center_x - 200, cursor_y, center_x + 200, cursor_y)
    cursor_y -= 34

    body = template.body_text.format(
        course_title=course_title,
        completion_date=completion_date_str,
        student_name=recipient_name,
        instructor_name=instructor_name,
        organization_name=template.organization_name,
    )
    pdf.setFillColor(text_color)
    pdf.setFont(font, 13)
    for line in _wrap_text(pdf, body, font, 13, PAGE_WIDTH - 260):
        pdf.drawCentredString(center_x, cursor_y, line)
        cursor_y -= 19

    # -- footer: signature (left) + issue metadata (right) --------------------
    footer_y = 110
    sig_x = 150
    signature_image = _fetch_image(template.signature_image_url)
    if signature_image is not None:
        pdf.drawImage(
            signature_image, sig_x - 60, footer_y + 6, width=120, height=40,
            preserveAspectRatio=True, mask="auto", anchor="s",
        )
    pdf.setStrokeColor(text_color)
    pdf.setLineWidth(0.75)
    pdf.line(sig_x - 80, footer_y, sig_x + 80, footer_y)
    if template.signature_name:
        pdf.setFillColor(text_color)
        pdf.setFont(font_bold, 11)
        pdf.drawCentredString(sig_x, footer_y - 16, template.signature_name)
    if template.signature_title:
        pdf.setFont(font, 9)
        pdf.drawCentredString(sig_x, footer_y - 28, template.signature_title)

    meta_x = PAGE_WIDTH - 150
    pdf.setFillColor(text_color)
    pdf.setFont(font, 9)
    pdf.drawCentredString(meta_x, footer_y - 4, f"Issued {completion_date_str}")
    pdf.drawCentredString(meta_x, footer_y - 16, f"Certificate No. {certificate_number}")
    pdf.setFont(font, 7)
    pdf.setFillColor(colors.grey)
    pdf.drawCentredString(meta_x, footer_y - 28, f"Verify at {verify_url}")
    pdf.drawCentredString(meta_x, footer_y - 38, verification_code)

    if template.footer_text:
        pdf.setFillColor(text_color)
        pdf.setFont(font, 9)
        pdf.drawCentredString(center_x, 46, template.footer_text)

    pdf.showPage()
    pdf.save()
    return buffer.getvalue()
