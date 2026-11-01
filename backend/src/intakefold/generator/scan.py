"""Makes a clean PDF look like a phone photo or scan."""

import random
from io import BytesIO
from typing import cast

# pypdfium2 ships no type information.
import pypdfium2  # pyright: ignore[reportMissingTypeStubs]
from PIL import Image, ImageEnhance, ImageFilter

from intakefold.generator.plan import DocumentPlan

SCAN_DPI = 110
PDF_POINTS_PER_INCH = 72
MAX_ROTATION_DEGREES = 2.5
NOISE_STRENGTH = 0.07
BLUR_RADIUS = 0.7
LOW_CONTRAST = 0.55
JPEG_QUALITY = 72


def rasterize(pdf: bytes) -> Image.Image:
    document = pypdfium2.PdfDocument(pdf)
    try:
        bitmap = document[0].render(scale=SCAN_DPI / PDF_POINTS_PER_INCH)  # pyright: ignore[reportArgumentType, reportUnknownMemberType, reportUnknownVariableType]
        image = cast(Image.Image, bitmap.to_pil())  # pyright: ignore[reportUnknownMemberType]
        return image.convert("RGB")
    finally:
        document.close()


def add_noise(image: Image.Image, rng: random.Random) -> Image.Image:
    # Pillow's effect_noise cannot be seeded, so the noise comes from the private generator.
    noise = Image.frombytes("L", image.size, rng.randbytes(image.width * image.height))
    return Image.blend(image, noise.convert("RGB"), NOISE_STRENGTH)


def scan(pdf: bytes, plan: DocumentPlan) -> bytes:
    rng = random.Random(plan.render_seed)  # noqa: S311 - reproducible test data, not security
    image = rasterize(pdf)
    if "rotation" in plan.degradations:
        angle = rng.uniform(-MAX_ROTATION_DEGREES, MAX_ROTATION_DEGREES)
        image = image.rotate(angle, Image.Resampling.BICUBIC, expand=True, fillcolor="white")
    if "low_contrast" in plan.degradations:
        image = ImageEnhance.Contrast(image).enhance(LOW_CONTRAST)
    if "blur" in plan.degradations:
        image = image.filter(ImageFilter.GaussianBlur(BLUR_RADIUS))
    if "noise" in plan.degradations:
        image = add_noise(image, rng)

    output = BytesIO()
    if plan.file_format == "jpeg":
        image.save(output, format="JPEG", quality=JPEG_QUALITY)
    else:
        image.save(output, format="PNG", optimize=True)
    return output.getvalue()
