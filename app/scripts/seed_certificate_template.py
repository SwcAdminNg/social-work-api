"""Seeds one beautiful, ready-to-use global certificate template (visible to
every instructor, and used as the fallback for any course that doesn't set its
own) and renders a sample PDF against dummy completion data so the whole
pipeline - design config -> logo upload -> PDF rendering - can be sanity
checked end to end without needing a real completed course.

Usage:
    python -m app.scripts.seed_certificate_template [--sample-out path/to/file.pdf]
"""

import argparse
import asyncio
import io
import math

from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import select

import app.models  # noqa: F401 - registers every entity on Base.metadata before use
from app.core.database import AsyncSessionLocal
from app.core.storage import get_r2_client
from app.modules.certificate.entity import CertificateBorderStyleEnum, CertificateTemplate
from app.modules.certificate.renderer import render_certificate_pdf

TEMPLATE_NAME = "Classic Achievement"

PRIMARY = "#0B3D2E"    # deep emerald
ACCENT = "#D4AF37"     # gold
BACKGROUND = "#FFFDF7"  # warm ivory
TEXT = "#1F2937"


def _build_emblem_logo_png(initials: str = "SW") -> bytes:
    """Procedurally draws a small circular emblem (gold ring + laurel-style
    ticks around a deep-emerald disc with the org's initials) so the seed has
    a real logo image to upload/embed, rather than shipping a static asset."""
    size = 512
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    center = size / 2
    gold = (212, 175, 55, 255)
    emerald = (11, 61, 46, 255)
    emerald_light = (20, 90, 68, 255)

    # Outer gold ring
    draw.ellipse((8, 8, size - 8, size - 8), fill=gold)
    # Inner emerald disc
    inset = 26
    draw.ellipse((inset, inset, size - inset, size - inset), fill=emerald)
    # Thin gold hairline just inside the disc
    hairline_inset = inset + 14
    draw.ellipse(
        (hairline_inset, hairline_inset, size - hairline_inset, size - hairline_inset),
        outline=gold, width=3,
    )

    # Laurel-style tick marks around the ring for a "seal" feel
    tick_radius_outer = size / 2 - 16
    tick_radius_inner = size / 2 - 30
    for i in range(48):
        angle = (2 * math.pi / 48) * i
        x1 = center + tick_radius_inner * math.cos(angle)
        y1 = center + tick_radius_inner * math.sin(angle)
        x2 = center + tick_radius_outer * math.cos(angle)
        y2 = center + tick_radius_outer * math.sin(angle)
        draw.line((x1, y1, x2, y2), fill=emerald_light, width=3)

    # Initials
    try:
        font = ImageFont.truetype("arialbd.ttf", 170)
    except OSError:
        font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), initials, font=font)
    text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(
        (center - text_w / 2 - bbox[0], center - text_h / 2 - bbox[1] - 6),
        initials, font=font, fill=gold,
    )

    # A small five-pointed star beneath the initials
    star_center = (center, center + 110)
    star_outer, star_inner = 26, 11
    points = []
    for i in range(10):
        angle = math.pi / 2 + i * math.pi / 5
        r = star_outer if i % 2 == 0 else star_inner
        points.append((star_center[0] + r * math.cos(angle), star_center[1] - r * math.sin(angle)))
    draw.polygon(points, fill=gold)

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


async def _get_or_create_global_template(session) -> CertificateTemplate:
    stmt = select(CertificateTemplate).where(
        CertificateTemplate.name == TEMPLATE_NAME, CertificateTemplate.owner_id.is_(None)
    )
    template = (await session.execute(stmt)).scalar_one_or_none()

    fields = dict(
        title_text="Certificate of Completion",
        subtitle_text="This certificate is proudly presented to",
        body_text=(
            "for successfully completing the course “{course_title}” on {completion_date}, "
            "having met all requirements with distinction and demonstrated a thorough "
            "understanding of the subject matter."
        ),
        organization_name="Social Workers Academy",
        footer_text="This certificate can be verified online using the code below.",
        signature_name="Dr. Amara Okafor",
        signature_title="Program Director, Social Workers Academy",
        primary_color=PRIMARY,
        accent_color=ACCENT,
        background_color=BACKGROUND,
        text_color=TEXT,
        font_family="Helvetica",
        border_style=CertificateBorderStyleEnum.CLASSIC,
        is_active=True,
    )

    if template is None:
        template = CertificateTemplate(name=TEMPLATE_NAME, owner_id=None, **fields)
        session.add(template)
    else:
        for key, value in fields.items():
            setattr(template, key, value)

    await session.flush()
    return template


async def seed(sample_out: str | None) -> None:
    async with AsyncSessionLocal() as session:
        template = await _get_or_create_global_template(session)

        r2 = get_r2_client()
        logo_bytes = _build_emblem_logo_png()
        logo_key = r2.build_certificate_template_image_key(template.id, "emblem-logo.png")
        r2.upload_bytes(logo_key, logo_bytes, "image/png")
        template.logo_url = r2.get_public_url(logo_key)

        await session.commit()
        print(f"Seeded global certificate template '{template.name}' (id={template.id})")
        print(f"Logo uploaded to: {template.logo_url}")

        if sample_out:
            pdf_bytes = render_certificate_pdf(
                template=template,
                recipient_name="Ada Chinwe Eze",
                course_title="Foundations of Community Social Work Practice",
                completion_date_str="August 23, 2026",
                instructor_name="Dr. Amara Okafor",
                certificate_number="SW-2026-DEMO01",
                verification_code="demo-verification-code",
                verify_url="https://example.com/certificates/verify/demo-verification-code",
            )
            with open(sample_out, "wb") as f:
                f.write(pdf_bytes)
            print(f"Sample certificate PDF written to: {sample_out}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sample-out", default=None, help="Also render a sample PDF (with dummy data) to this path"
    )
    args = parser.parse_args()
    asyncio.run(seed(args.sample_out))


if __name__ == "__main__":
    main()
