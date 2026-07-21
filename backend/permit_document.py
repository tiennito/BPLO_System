"""Single-source A4 renderer for the official Victoria Business Permit."""

from __future__ import annotations

from base64 import b64encode
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from html import escape
from io import BytesIO
from pathlib import Path
import re

try:
    from reportlab.graphics import renderPDF, renderSVG
    from reportlab.graphics.barcode.qr import QrCodeWidget
    from reportlab.graphics.shapes import Drawing
    from reportlab.lib.colors import HexColor, black
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfbase.pdfmetrics import stringWidth
    from reportlab.pdfgen import canvas
    REPORTLAB_AVAILABLE = True
except ModuleNotFoundError:
    renderPDF = renderSVG = QrCodeWidget = Drawing = HexColor = black = A4 = ImageReader = stringWidth = canvas = None
    REPORTLAB_AVAILABLE = False

try:
    import fitz
except ModuleNotFoundError:
    fitz = None

try:
    import qrcode
except ModuleNotFoundError:
    qrcode = None


PAGE_WIDTH, PAGE_HEIGHT = 595.2755905511812, 841.8897637795277
GREEN_HEX = "#006B45"
GREEN = HexColor(GREEN_HEX) if REPORTLAB_AVAILABLE else GREEN_HEX
ASSET_DIR = Path(__file__).resolve().parent.parent / "static" / "assets" / "permits"
MUNICIPALITY = "MUNICIPALITY OF VICTORIA"


def _required(data: dict, key: str) -> str:
    value = str(data.get(key) or "").strip()
    if not value:
        raise ValueError(f"Permit field '{key}' is required.")
    return value


def _date_text(value, *, include_time=False) -> str:
    if not value:
        return ""
    if isinstance(value, str):
        raw = value.replace("Z", "+00:00")
        try:
            value = datetime.fromisoformat(raw)
        except ValueError:
            try:
                value = date.fromisoformat(value[:10])
            except ValueError:
                return value
    if isinstance(value, datetime):
        pattern = "%B %d, %Y at %I:%M %p" if include_time else "%B %d, %Y"
        return value.strftime(pattern).replace(" 0", " ")
    if isinstance(value, date):
        return value.strftime("%B %d, %Y").replace(" 0", " ")
    return str(value)


def _money(value) -> str:
    try:
        return f"PHP {Decimal(str(value)):,.2f}"
    except (InvalidOperation, TypeError, ValueError):
        return str(value or "")


def normalize_permit_data(data: dict) -> dict:
    """Validate and format authoritative permit data for all render targets."""
    normalized = {
        "permit_number": _required(data, "permit_number"),
        "owner_name": _required(data, "owner_name").upper(),
        "business_name": _required(data, "business_name").upper(),
        "business_address": _required(data, "business_address"),
        "release_date": _date_text(_required(data, "release_date")),
        "expiration_date": _date_text(_required(data, "expiration_date")),
        "official_receipt_number": _required(data, "official_receipt_number"),
        "payment_date_time": _date_text(_required(data, "payment_date_time"), include_time=True),
        "payment_amount": _money(_required(data, "payment_amount")),
        "sp_number": _required(data, "sp_number"),
        "authorized_official_name": _required(data, "authorized_official_name").upper(),
        "authorized_official_position": _required(data, "authorized_official_position").upper(),
        "qr_verification_url": _required(data, "qr_verification_url"),
    }
    return normalized


def _fit_size(text: str, max_width: float, preferred: float, minimum: float, font="Helvetica-Bold") -> float:
    size = preferred
    while size > minimum and _text_width(text, font, size) > max_width:
        size -= 0.25
    return size


def _text_width(text: str, font: str, font_size: float) -> float:
    if REPORTLAB_AVAILABLE:
        return stringWidth(text, font, font_size)
    width_factor = 0.58 if "Bold" in font else 0.53
    return len(str(text or "")) * font_size * width_factor


def _wrapped_lines(text: str, max_width: float, font: str, font_size: float, max_lines: int) -> list[str]:
    words = re.split(r"\s+", text.strip())
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if not current or _text_width(candidate, font, font_size) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    if len(lines) <= max_lines:
        return lines
    lines = lines[:max_lines]
    while lines[-1] and _text_width(lines[-1] + "...", font, font_size) > max_width:
        lines[-1] = lines[-1][:-1]
    lines[-1] += "..."
    return lines


def _qr_drawing(value: str, size: float):
    if not REPORTLAB_AVAILABLE:
        raise RuntimeError("ReportLab is not available.")
    widget = QrCodeWidget(value, barLevel="M")
    x1, y1, x2, y2 = widget.getBounds()
    width, height = x2 - x1, y2 - y1
    drawing = Drawing(size, size, transform=[size / width, 0, 0, size / height, 0, 0])
    drawing.add(widget)
    return drawing


def _asset_data_uri(path: Path) -> str:
    return f"data:image/png;base64,{b64encode(path.read_bytes()).decode('ascii')}"


def _qr_data_uri(value: str) -> str:
    if REPORTLAB_AVAILABLE:
        raw = renderSVG.drawToString(_qr_drawing(value, 110))
        if isinstance(raw, str):
            raw = raw.encode("utf-8")
        return f"data:image/svg+xml;base64,{b64encode(raw).decode('ascii')}"
    png = _qr_png_bytes(value)
    if png:
        return f"data:image/png;base64,{b64encode(png).decode('ascii')}"
    fallback = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="110" height="110">'
        '<rect width="110" height="110" fill="white" stroke="black"/>'
        f'<text x="55" y="52" text-anchor="middle" font-size="7">{escape(value[:32])}</text>'
        f'<text x="55" y="64" text-anchor="middle" font-size="7">{escape(value[32:64])}</text>'
        "</svg>"
    ).encode("utf-8")
    return f"data:image/svg+xml;base64,{b64encode(fallback).decode('ascii')}"


def _qr_png_bytes(value: str) -> bytes:
    if qrcode is None:
        return b""
    image = qrcode.make(value)
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _svg_text(x, y, text, size, *, weight=400, anchor="start", fill="#111111", italic=False, opacity=1):
    style = f"font-size:{size}px;font-weight:{weight};font-style:{'italic' if italic else 'normal'}"
    return (
        f'<text x="{x}" y="{y}" text-anchor="{anchor}" fill="{fill}" opacity="{opacity}" '
        f'style="{style}">{escape(str(text))}</text>'
    )


def _svg_wrapped_center(text: str, y: float, max_width: float, size: float, max_lines=2, bold=True) -> str:
    lines = _wrapped_lines(text, max_width, "Helvetica-Bold" if bold else "Helvetica", size, max_lines)
    start = y - ((len(lines) - 1) * size * 0.58)
    return "".join(
        _svg_text(PAGE_WIDTH / 2, start + index * size * 1.08, line, size, weight=700 if bold else 400, anchor="middle")
        for index, line in enumerate(lines)
    )


def render_permit_svg(data: dict) -> str:
    """Render the browser/print preview using the same geometry as the PDF."""
    value = normalize_permit_data(data)
    victoria = _asset_data_uri(ASSET_DIR / "victoria-seal.png")
    bplo = _asset_data_uri(ASSET_DIR / "bplo-seal.png")
    qr = _qr_data_uri(value["qr_verification_url"])
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="210mm" height="297mm" viewBox="0 0 {PAGE_WIDTH:.3f} {PAGE_HEIGHT:.3f}" role="img" aria-label="Official Business Permit">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<rect x="34" y="20" width="527" height="801" fill="none" stroke="#006B45" stroke-width="2.4"/>',
        f'<image href="{victoria}" x="54" y="38" width="72" height="72" preserveAspectRatio="xMidYMid meet"/>',
        f'<image href="{bplo}" x="469" y="35" width="76" height="76" preserveAspectRatio="xMidYMid meet"/>',
        f'<image href="{victoria}" x="74" y="202" width="447" height="447" opacity="0.075" preserveAspectRatio="xMidYMid meet"/>',
        _svg_text(PAGE_WIDTH / 2, 50, "REPUBLIC OF THE PHILIPPINES", 9, anchor="middle"),
        _svg_text(PAGE_WIDTH / 2, 64, "PROVINCE OF LAGUNA", 10, weight=700, anchor="middle"),
        _svg_text(PAGE_WIDTH / 2, 81, "MUNICIPALITY OF VICTORIA", 13, weight=700, anchor="middle", fill="#006B45"),
        _svg_text(PAGE_WIDTH / 2, 96, "BUSINESS PERMITS AND LICENSING OFFICE", 8.5, weight=700, anchor="middle"),
        _svg_text(PAGE_WIDTH / 2, 139, "PAHINTULOT SA PANGANGALAKAL", 20, weight=700, anchor="middle", fill="#006B45"),
        _svg_text(PAGE_WIDTH / 2, 161, "BUSINESS PERMIT", 8.5, weight=700, anchor="middle"),
        _svg_text(PAGE_WIDTH / 2, 181, f"PERMIT NO. {value['permit_number']}", 13, weight=700, anchor="middle"),
        _svg_text(PAGE_WIDTH / 2, 241, "IPINAGKAKALOOB KAY", 8.5, weight=700, anchor="middle", fill="#006B45"),
        _svg_wrapped_center(value["owner_name"], 318, 465, _fit_size(value["owner_name"], 465, 18, 11), 2),
        '<line x1="66" y1="341" x2="529" y2="341" stroke="#006B45" stroke-width="1"/>',
        _svg_text(PAGE_WIDTH / 2, 356, "ang pahintulot na mangalakal sa nasasakupan ng bayang ito, sa pook na", 8.5, anchor="middle", italic=True),
        _svg_wrapped_center(value["business_address"], 412, 450, 11.5, 3, bold=False),
        '<line x1="66" y1="442" x2="529" y2="442" stroke="#006B45" stroke-width="1"/>',
        _svg_text(69, 458, "alinsunod sa mga umiiral na batas, ordinansa, alituntunin at patakaran ng Pamahalaang", 8, anchor="start"),
        _svg_text(69, 470, "Bayan ng Victoria, Laguna, para sa negosyong nakapangalan bilang:", 8, anchor="start"),
        _svg_wrapped_center(value["business_name"], 541, 458, _fit_size(value["business_name"], 458, 18, 11), 2),
        '<line x1="66" y1="566" x2="529" y2="566" stroke="#006B45" stroke-width="1"/>',
        _svg_text(PAGE_WIDTH / 2, 590, "ANG PAHINTULOT NA ITO AY MAY BISA MULA", 8.5, weight=700, anchor="middle"),
        _svg_text(PAGE_WIDTH / 2, 608, value["release_date"].upper(), 12, weight=700, anchor="middle", fill="#006B45"),
        _svg_text(PAGE_WIDTH / 2, 625, "HANGGANG", 8.5, weight=700, anchor="middle"),
        _svg_text(PAGE_WIDTH / 2, 644, value["expiration_date"].upper(), 12, weight=700, anchor="middle", fill="#006B45"),
        _svg_text(PAGE_WIDTH / 2, 687, value["authorized_official_name"], _fit_size(value["authorized_official_name"], 270, 14, 10), weight=700, anchor="middle"),
        '<line x1="190" y1="692" x2="405" y2="692" stroke="#111111" stroke-width="0.8"/>',
        _svg_text(PAGE_WIDTH / 2, 707, value["authorized_official_position"], 8.5, weight=700, anchor="middle"),
        _svg_text(64, 742, f"O.R. NO.: {value['official_receipt_number']}", 7.8, weight=700),
        _svg_text(64, 756, f"DATE/TIME PAID: {value['payment_date_time']}", 7.2),
        _svg_text(64, 770, f"AMOUNT PAID: {value['payment_amount']}", 7.8, weight=700),
        _svg_text(64, 784, f"S.P. NO.: {value['sp_number']}", 7.8, weight=700),
        _svg_text(280, 742, "PAALALA:", 7.6, weight=700, fill="#006B45"),
        _svg_text(280, 755, "Ang pahintulot na ito ay dapat ipaskil sa hayag na lugar", 6.6),
        _svg_text(280, 766, "sa loob ng establisimyento at ipakita kapag hinihingi", 6.6),
        _svg_text(280, 777, "ng mga awtorisadong kinatawan ng Pamahalaang Bayan.", 6.6),
        f'<image href="{qr}" x="479" y="733" width="61" height="61"/>',
        _svg_text(509.5, 805, "SCAN TO VERIFY", 5.8, weight=700, anchor="middle", fill="#006B45"),
        "</svg>",
    ]
    return "".join(parts)


def _pdf_center_lines(pdf, text, top_y, max_width, font, size, max_lines=2, leading=None):
    lines = _wrapped_lines(text, max_width, font, size, max_lines)
    leading = leading or size * 1.1
    start = top_y + ((len(lines) - 1) * leading / 2)
    pdf.setFont(font, size)
    for index, line in enumerate(lines):
        pdf.drawCentredString(PAGE_WIDTH / 2, start - index * leading, line)


def render_permit_pdf(data: dict) -> bytes:
    """Create the permanent one-page A4 PDF from authoritative permit data."""
    if not REPORTLAB_AVAILABLE:
        return _render_permit_pdf_fitz(data)

    value = normalize_permit_data(data)
    output = BytesIO()
    pdf = canvas.Canvas(output, pagesize=A4, pageCompression=1)
    pdf.setTitle(f"Business Permit {value['permit_number']}")
    pdf.setAuthor("Municipality of Victoria Business Permits and Licensing Office")

    pdf.setStrokeColor(GREEN)
    pdf.setLineWidth(2.4)
    pdf.rect(34, PAGE_HEIGHT - 821, 527, 801, stroke=1, fill=0)
    victoria_path = ASSET_DIR / "victoria-seal.png"
    bplo_path = ASSET_DIR / "bplo-seal.png"
    pdf.drawImage(ImageReader(str(victoria_path)), 54, PAGE_HEIGHT - 110, 72, 72, preserveAspectRatio=True, mask="auto")
    pdf.drawImage(ImageReader(str(bplo_path)), 469, PAGE_HEIGHT - 111, 76, 76, preserveAspectRatio=True, mask="auto")
    pdf.saveState()
    pdf.setFillAlpha(0.075)
    pdf.drawImage(ImageReader(str(victoria_path)), 74, PAGE_HEIGHT - 649, 447, 447, preserveAspectRatio=True, mask="auto")
    pdf.restoreState()

    def centered(text, top, size, font="Helvetica", color=black):
        pdf.setFillColor(color)
        pdf.setFont(font, size)
        pdf.drawCentredString(PAGE_WIDTH / 2, PAGE_HEIGHT - top, text)

    def left(text, x, top, size, font="Helvetica", color=black):
        pdf.setFillColor(color)
        pdf.setFont(font, size)
        pdf.drawString(x, PAGE_HEIGHT - top, text)

    centered("REPUBLIC OF THE PHILIPPINES", 50, 9)
    centered("PROVINCE OF LAGUNA", 64, 10, "Helvetica-Bold")
    centered("MUNICIPALITY OF VICTORIA", 81, 13, "Helvetica-Bold", GREEN)
    centered("BUSINESS PERMITS AND LICENSING OFFICE", 96, 8.5, "Helvetica-Bold")
    centered("PAHINTULOT SA PANGANGALAKAL", 139, 20, "Helvetica-Bold", GREEN)
    centered("BUSINESS PERMIT", 161, 8.5, "Helvetica-Bold")
    centered(f"PERMIT NO. {value['permit_number']}", 181, 13, "Helvetica-Bold")
    centered("IPINAGKAKALOOB KAY", 241, 8.5, "Helvetica-Bold", GREEN)
    owner_size = _fit_size(value["owner_name"], 465, 18, 11)
    _pdf_center_lines(pdf, value["owner_name"], PAGE_HEIGHT - 318, 465, "Helvetica-Bold", owner_size, 2)
    pdf.setStrokeColor(GREEN); pdf.setLineWidth(1); pdf.line(66, PAGE_HEIGHT - 341, 529, PAGE_HEIGHT - 341)
    centered("ang pahintulot na mangalakal sa nasasakupan ng bayang ito, sa pook na", 356, 8.5, "Helvetica-Oblique")
    _pdf_center_lines(pdf, value["business_address"], PAGE_HEIGHT - 412, 450, "Helvetica", 11.5, 3, 12.5)
    pdf.line(66, PAGE_HEIGHT - 442, 529, PAGE_HEIGHT - 442)
    left("alinsunod sa mga umiiral na batas, ordinansa, alituntunin at patakaran ng Pamahalaang", 69, 458, 8)
    left("Bayan ng Victoria, Laguna, para sa negosyong nakapangalan bilang:", 69, 470, 8)
    business_size = _fit_size(value["business_name"], 458, 18, 11)
    _pdf_center_lines(pdf, value["business_name"], PAGE_HEIGHT - 541, 458, "Helvetica-Bold", business_size, 2)
    pdf.line(66, PAGE_HEIGHT - 566, 529, PAGE_HEIGHT - 566)
    centered("ANG PAHINTULOT NA ITO AY MAY BISA MULA", 590, 8.5, "Helvetica-Bold")
    centered(value["release_date"].upper(), 608, 12, "Helvetica-Bold", GREEN)
    centered("HANGGANG", 625, 8.5, "Helvetica-Bold")
    centered(value["expiration_date"].upper(), 644, 12, "Helvetica-Bold", GREEN)
    official_size = _fit_size(value["authorized_official_name"], 270, 14, 10)
    centered(value["authorized_official_name"], 687, official_size, "Helvetica-Bold")
    pdf.setStrokeColor(black); pdf.setLineWidth(0.8); pdf.line(190, PAGE_HEIGHT - 692, 405, PAGE_HEIGHT - 692)
    centered(value["authorized_official_position"], 707, 8.5, "Helvetica-Bold")
    left(f"O.R. NO.: {value['official_receipt_number']}", 64, 742, 7.8, "Helvetica-Bold")
    left(f"DATE/TIME PAID: {value['payment_date_time']}", 64, 756, 7.2)
    left(f"AMOUNT PAID: {value['payment_amount']}", 64, 770, 7.8, "Helvetica-Bold")
    left(f"S.P. NO.: {value['sp_number']}", 64, 784, 7.8, "Helvetica-Bold")
    left("PAALALA:", 280, 742, 7.6, "Helvetica-Bold", GREEN)
    left("Ang pahintulot na ito ay dapat ipaskil sa hayag na lugar", 280, 755, 6.6)
    left("sa loob ng establisimyento at ipakita kapag hinihingi", 280, 766, 6.6)
    left("ng mga awtorisadong kinatawan ng Pamahalaang Bayan.", 280, 777, 6.6)
    renderPDF.draw(_qr_drawing(value["qr_verification_url"], 61), pdf, 479, PAGE_HEIGHT - 794)
    left("SCAN TO VERIFY", 487, 805, 5.8, "Helvetica-Bold", GREEN)

    pdf.showPage()
    pdf.save()
    return output.getvalue()


def _fitz_color(hex_value: str) -> tuple[float, float, float]:
    hex_value = hex_value.strip().lstrip("#")
    return tuple(int(hex_value[index:index + 2], 16) / 255 for index in (0, 2, 4))


def _transparent_png(path: Path, opacity: int) -> bytes:
    try:
        from PIL import Image
    except ModuleNotFoundError:
        return b""
    image = Image.open(path).convert("RGBA")
    alpha = image.getchannel("A").point(lambda value: int(value * opacity / 255))
    image.putalpha(alpha)
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _render_permit_pdf_fitz(data: dict) -> bytes:
    if fitz is None:
        raise RuntimeError("Install either reportlab or pymupdf to render official permit PDFs.")

    value = normalize_permit_data(data)
    doc = fitz.open()
    page = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    green = _fitz_color(GREEN_HEX)
    black_color = (0, 0, 0)
    victoria_path = ASSET_DIR / "victoria-seal.png"
    bplo_path = ASSET_DIR / "bplo-seal.png"

    page.draw_rect(fitz.Rect(34, 20, 561, 821), color=green, width=2.4)
    page.insert_image(fitz.Rect(54, 38, 126, 110), filename=str(victoria_path), keep_proportion=True)
    page.insert_image(fitz.Rect(469, 35, 545, 111), filename=str(bplo_path), keep_proportion=True)
    watermark = _transparent_png(victoria_path, 20)
    if watermark:
        page.insert_image(fitz.Rect(74, 202, 521, 649), stream=watermark, keep_proportion=True)

    def font_name(bold=False, italic=False):
        if bold:
            return "hebo"
        if italic:
            return "heit"
        return "helv"

    def text_box(x0, y0, x1, y1, text, size, *, bold=False, italic=False, color=black_color, align=fitz.TEXT_ALIGN_LEFT):
        page.insert_textbox(
            fitz.Rect(x0, y0, x1, y1),
            str(text),
            fontsize=size,
            fontname=font_name(bold=bold, italic=italic),
            color=color,
            align=align,
        )

    def centered(text, baseline_y, size, *, bold=False, italic=False, color=black_color):
        text_box(34, baseline_y - size, PAGE_WIDTH - 34, baseline_y + size * 0.55, text, size, bold=bold, italic=italic, color=color, align=fitz.TEXT_ALIGN_CENTER)

    def left(text, x, baseline_y, size, *, bold=False, color=black_color):
        text_box(x, baseline_y - size, PAGE_WIDTH - 34, baseline_y + size * 0.65, text, size, bold=bold, color=color)

    def centered_lines(text, center_y, max_width, size, *, bold=False, italic=False, max_lines=2, color=black_color):
        lines = _wrapped_lines(text, max_width, "Helvetica-Bold" if bold else "Helvetica", size, max_lines)
        leading = size * 1.12
        start = center_y - ((len(lines) - 1) * leading / 2)
        for index, line in enumerate(lines):
            centered(line, start + index * leading, size, bold=bold, italic=italic, color=color)

    centered("REPUBLIC OF THE PHILIPPINES", 50, 9)
    centered("PROVINCE OF LAGUNA", 64, 10, bold=True)
    centered("MUNICIPALITY OF VICTORIA", 81, 13, bold=True, color=green)
    centered("BUSINESS PERMITS AND LICENSING OFFICE", 96, 8.5, bold=True)
    centered("PAHINTULOT SA PANGANGALAKAL", 139, 20, bold=True, color=green)
    centered("BUSINESS PERMIT", 161, 8.5, bold=True)
    centered(f"PERMIT NO. {value['permit_number']}", 181, 13, bold=True)
    centered("IPINAGKAKALOOB KAY", 241, 8.5, bold=True, color=green)
    centered_lines(value["owner_name"], 318, 465, _fit_size(value["owner_name"], 465, 18, 11), bold=True)
    page.draw_line(fitz.Point(66, 341), fitz.Point(529, 341), color=green, width=1)
    centered("ang pahintulot na mangalakal sa nasasakupan ng bayang ito, sa pook na", 356, 8.5, italic=True)
    centered_lines(value["business_address"], 412, 450, 11.5, max_lines=3)
    page.draw_line(fitz.Point(66, 442), fitz.Point(529, 442), color=green, width=1)
    left("alinsunod sa mga umiiral na batas, ordinansa, alituntunin at patakaran ng Pamahalaang", 69, 458, 8)
    left("Bayan ng Victoria, Laguna, para sa negosyong nakapangalan bilang:", 69, 470, 8)
    centered_lines(value["business_name"], 541, 458, _fit_size(value["business_name"], 458, 18, 11), bold=True)
    page.draw_line(fitz.Point(66, 566), fitz.Point(529, 566), color=green, width=1)
    centered("ANG PAHINTULOT NA ITO AY MAY BISA MULA", 590, 8.5, bold=True)
    centered(value["release_date"].upper(), 608, 12, bold=True, color=green)
    centered("HANGGANG", 625, 8.5, bold=True)
    centered(value["expiration_date"].upper(), 644, 12, bold=True, color=green)
    centered(value["authorized_official_name"], 687, _fit_size(value["authorized_official_name"], 270, 14, 10), bold=True)
    page.draw_line(fitz.Point(190, 692), fitz.Point(405, 692), color=black_color, width=0.8)
    centered(value["authorized_official_position"], 707, 8.5, bold=True)
    left(f"O.R. NO.: {value['official_receipt_number']}", 64, 742, 7.8, bold=True)
    left(f"DATE/TIME PAID: {value['payment_date_time']}", 64, 756, 7.2)
    left(f"AMOUNT PAID: {value['payment_amount']}", 64, 770, 7.8, bold=True)
    left(f"S.P. NO.: {value['sp_number']}", 64, 784, 7.8, bold=True)
    left("PAALALA:", 280, 742, 7.6, bold=True, color=green)
    left("Ang pahintulot na ito ay dapat ipaskil sa hayag na lugar", 280, 755, 6.6)
    left("sa loob ng establisimyento at ipakita kapag hinihingi", 280, 766, 6.6)
    left("ng mga awtorisadong kinatawan ng Pamahalaang Bayan.", 280, 777, 6.6)
    qr_png = _qr_png_bytes(value["qr_verification_url"])
    if qr_png:
        page.insert_image(fitz.Rect(479, 733, 540, 794), stream=qr_png, keep_proportion=True)
    else:
        page.draw_rect(fitz.Rect(479, 733, 540, 794), color=black_color, width=0.8)
        text_box(481, 755, 538, 775, "QR module missing", 5.5, align=fitz.TEXT_ALIGN_CENTER)
    text_box(479, 800, 540, 812, "SCAN TO VERIFY", 5.8, bold=True, color=green, align=fitz.TEXT_ALIGN_CENTER)

    doc.set_metadata({"title": f"Business Permit {value['permit_number']}", "author": "Municipality of Victoria Business Permits and Licensing Office"})
    pdf_bytes = doc.tobytes(garbage=4, deflate=True)
    doc.close()
    return pdf_bytes


def permit_storage_path(permit_number: str, version_number: int) -> str:
    year_match = re.search(r"(?:^|-)\d{4}(?:-|$)", permit_number)
    year = year_match.group(0).strip("-") if year_match else str(datetime.now().year)
    safe_number = re.sub(r"[^A-Za-z0-9._-]", "-", permit_number)
    return f"{year}/{safe_number}/permit-v{int(version_number or 1)}.pdf"
