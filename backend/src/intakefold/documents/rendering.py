from collections.abc import Iterator
from io import BytesIO
from typing import cast

# pypdfium2 ships no type information, and this is the only module that uses it.
import pypdfium2  # pyright: ignore[reportMissingTypeStubs]
from PIL import Image

from intakefold.documents.checks import PDF

RENDER_DPI = 150
PDF_POINTS_PER_INCH = 72
# Bounds the pixels of any page, because a PDF states its own page size.
MAX_RENDER_SIDE = 2400


class RenderFailed(Exception):
    """The file passed the upload checks and still cannot be rendered."""


def render_pages(content: bytes, media_type: str, expected_pages: int) -> Iterator[bytes]:
    """Yields one PNG per page. Runs in the worker, so a parser crash cannot reach the API."""
    if media_type == PDF:
        return render_pdf(content, expected_pages)
    return iter([render_image(content)])


def render_image(content: bytes) -> bytes:
    with Image.open(BytesIO(content)) as image:
        return png(image)


def render_pdf(content: bytes, expected_pages: int) -> Iterator[bytes]:
    try:
        document = pypdfium2.PdfDocument(content)
    except pypdfium2.PdfiumError as error:
        raise RenderFailed from error
    try:
        # Two parsers disagreeing about a file is a sign it was built to confuse one of them.
        if len(document) != expected_pages:
            raise RenderFailed
        for index in range(len(document)):
            page = document[index]
            try:
                width, height = page.get_size()
                if width <= 0 or height <= 0:
                    raise RenderFailed
                scale = min(RENDER_DPI / PDF_POINTS_PER_INCH, MAX_RENDER_SIDE / max(width, height))
                # The library's inferred signature says int; its documentation says a scale factor.
                bitmap = page.render(scale=scale)  # pyright: ignore[reportArgumentType, reportUnknownMemberType, reportUnknownVariableType]
                yield png(cast(Image.Image, bitmap.to_pil()))  # pyright: ignore[reportUnknownMemberType]
            finally:
                page.close()
    except pypdfium2.PdfiumError as error:
        raise RenderFailed from error
    finally:
        document.close()


def png(image: Image.Image) -> bytes:
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()
