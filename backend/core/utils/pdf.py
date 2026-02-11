import base64
import fitz
from backend.core.logging import get_logger

_log = get_logger("utils.pdf")

def convert_pdf_to_images(
    content: bytes,
    max_pages: int = 10,
    dpi: int = 150
) -> list[dict]:

    images = []

    try:
        doc = fitz.open(stream=content, filetype="pdf")
        total_pages = len(doc)
        pages_to_convert = min(total_pages, max_pages)

        _log.info(
            "Converting PDF to images",
            total_pages=total_pages,
            converting=pages_to_convert,
            dpi=dpi
        )

        zoom = dpi / 72
        matrix = fitz.Matrix(zoom, zoom)

        for page_num in range(pages_to_convert):
            page = doc[page_num]
            pix = page.get_pixmap(matrix=matrix)

            png_bytes = pix.tobytes("png")
            b64_data = base64.b64encode(png_bytes).decode("utf-8")

            images.append({
                "mime_type": "image/png",
                "data": b64_data,
                "page": page_num + 1
            })

            _log.debug(
                "PDF page converted",
                page=page_num + 1,
                size_kb=len(png_bytes) // 1024
            )

        doc.close()

        if total_pages > max_pages:
            _log.warning(
                "PDF truncated",
                total_pages=total_pages,
                converted=pages_to_convert
            )

        # PERF-040: Estimate size without decoding (base64: 4 chars = 3 bytes)
        _log.info(
            "PDF conversion complete",
            pages=len(images),
            total_size_kb=sum(len(str(img["data"])) * 3 // 4 for img in images) // 1024
        )

        return images

    except Exception as e:
        _log.error("PDF to image conversion failed", error=str(e))
        return []
