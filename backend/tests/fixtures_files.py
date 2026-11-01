"""Small real files, built in code so nothing binary is committed."""

from io import BytesIO

from PIL import Image
from pypdf import PdfWriter


def pdf_bytes(pages: int = 1, seed: int = 0) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(300 + seed, 400)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def png_bytes(
    size: tuple[int, int] = (60, 40), mode: str = "RGB", color: int | str = "white"
) -> bytes:
    output = BytesIO()
    Image.new(mode, size, color).save(output, format="PNG")
    return output.getvalue()


def jpeg_bytes(size: tuple[int, int] = (60, 40), color: str = "white") -> bytes:
    output = BytesIO()
    Image.new("RGB", size, color).save(output, format="JPEG")
    return output.getvalue()
