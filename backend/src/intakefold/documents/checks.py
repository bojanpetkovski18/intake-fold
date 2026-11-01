"""Decides what an uploaded file is. Its name and declared type are never consulted."""

from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageOps
from pypdf import PdfReader

from intakefold.settings import Settings

PDF = "application/pdf"
PNG = "image/png"
JPEG = "image/jpeg"

PDF_MAGIC = b"%PDF-"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
JPEG_MAGIC = b"\xff\xd8\xff"

JPEG_QUALITY = 90

# Pillow's own check would warn or raise while opening. check_image applies the smaller
# configured cap right after opening, which reads only the header, before any pixel is decoded.
Image.MAX_IMAGE_PIXELS = None


class UploadRefused(Exception):
    """`code` is for clients and `detail` for people. Neither quotes the file."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class CheckedFile:
    media_type: str
    page_count: int
    content: bytes  # What is stored: the PDF as uploaded, or the re-encoded image.


def check_upload(data: bytes, settings: Settings) -> CheckedFile:
    if not data:
        raise UploadRefused("empty_file", "The file is empty.")
    if data.startswith(PDF_MAGIC):
        return check_pdf(data, settings)
    if data.startswith(PNG_MAGIC):
        return check_image(data, "PNG", PNG, settings)
    if data.startswith(JPEG_MAGIC):
        return check_image(data, "JPEG", JPEG, settings)
    raise UploadRefused("unsupported_type", "Only PDF, PNG and JPEG files are accepted.")


def check_pdf(data: bytes, settings: Settings) -> CheckedFile:
    if len(data) > settings.max_pdf_bytes:
        raise too_large(settings.max_pdf_bytes)
    try:
        reader = PdfReader(BytesIO(data))
        if reader.is_encrypted:
            raise UploadRefused("encrypted_pdf", "Encrypted PDFs are not accepted.")
        page_count = len(reader.pages)
        if page_count > settings.max_pdf_pages:
            raise UploadRefused(
                "too_many_pages", f"The limit is {settings.max_pdf_pages} pages per PDF."
            )
        for page in reader.pages:
            page.get_contents()
    except UploadRefused:
        raise
    except Exception:  # A decoder fed hostile input can raise almost anything.
        raise undecodable() from None
    if page_count == 0:
        raise undecodable()
    return CheckedFile(PDF, page_count, data)


def check_image(data: bytes, image_format: str, media_type: str, settings: Settings) -> CheckedFile:
    if len(data) > settings.max_image_bytes:
        raise too_large(settings.max_image_bytes)
    try:
        with Image.open(BytesIO(data), formats=[image_format]) as image:
            width, height = image.size
            if max(width, height) > settings.max_image_side:
                raise UploadRefused(
                    "image_too_large", f"The limit is {settings.max_image_side} px per side."
                )
            if width * height > settings.max_image_pixels:
                raise UploadRefused(
                    "image_too_large", f"The limit is {settings.max_image_pixels} pixels."
                )
            if getattr(image, "n_frames", 1) > 1:
                raise UploadRefused("unsupported_type", "Animated images are not accepted.")
            # Re-encoding decodes every pixel, which is the proof that the image is real.
            content = reencode(image, image_format)
    except UploadRefused:
        raise
    except Exception:  # A decoder fed hostile input can raise almost anything.
        raise undecodable() from None
    if len(content) > settings.max_image_bytes:
        raise too_large(settings.max_image_bytes)
    return CheckedFile(media_type, 1, content)


def reencode(image: Image.Image, image_format: str) -> bytes:
    """Pixels only: anything hidden in metadata or after the image data is left behind."""
    upright = ImageOps.exif_transpose(image)  # Metadata is dropped, so apply it first.
    has_alpha = "A" in upright.mode or "transparency" in upright.info
    clean = upright.convert("RGBA" if has_alpha and image_format == "PNG" else "RGB")
    clean.info = {}
    output = BytesIO()
    if image_format == "JPEG":
        clean.save(output, format="JPEG", quality=JPEG_QUALITY)
    else:
        clean.save(output, format="PNG", optimize=True)
    return output.getvalue()


def too_large(limit: int) -> UploadRefused:
    return UploadRefused("too_large", f"The limit is {limit // (1024 * 1024)} MiB for this type.")


def undecodable() -> UploadRefused:
    return UploadRefused("undecodable", "The file is damaged or is not what it appears to be.")
