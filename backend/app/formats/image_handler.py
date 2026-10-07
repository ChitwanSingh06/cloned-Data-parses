"""Standalone image support (PNG, JPG, TIFF, WEBP, BMP, GIF).

An uploaded image is wrapped losslessly into a one-page PDF so the existing pipeline handles it unchanged:
no text layer -> page is treated as scanned -> OCR, raster table detection and figure/chart detection run,
and the normal page viewer + bounding boxes work. Nothing is invented: text/tables come only from OCR/detection.
"""
import io
from pathlib import Path

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp", ".gif"}
_PAGE_DPI = 150          # assumed scan resolution when mapping pixels -> PDF points
_MAX_PIXELS = 60_000_000  # guards against decompression bombs / huge photos


def is_image_name(name: str) -> bool:
    return Path(name or "").suffix.lower() in IMAGE_EXTS


def image_to_pdf_bytes(data: bytes) -> bytes:
    """Return a one-page PDF containing the image. Raises ValueError for unreadable images."""
    import pymupdf
    from PIL import Image, ImageOps

    try:
        with Image.open(io.BytesIO(data)) as im:
            if im.width * im.height > _MAX_PIXELS:
                raise ValueError(f"Image is too large ({im.width}x{im.height}px)")
            im.seek(0)                      # first frame of multi-frame GIF/TIFF
            im = ImageOps.exif_transpose(im)  # honour camera rotation
            if im.mode in ("RGBA", "LA", "P"):
                rgba = im.convert("RGBA")
                bg = Image.new("RGB", rgba.size, "white")
                bg.paste(rgba, mask=rgba.split()[-1])
                im = bg
            elif im.mode != "RGB":
                im = im.convert("RGB")
            buf = io.BytesIO()
            im.save(buf, format="PNG")
            width_pt = im.width * 72 / _PAGE_DPI
            height_pt = im.height * 72 / _PAGE_DPI
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"Cannot read image: {exc}") from exc

    pdf = pymupdf.open()
    try:
        page = pdf.new_page(width=width_pt, height=height_pt)
        page.insert_image(page.rect, stream=buf.getvalue())
        return pdf.tobytes()
    finally:
        pdf.close()
