"""Tests for backend.core.utils.pdf.

All fitz (PyMuPDF) interactions are mocked via patching the module attribute.
"""

import base64
from unittest.mock import MagicMock, patch

import pytest


def _make_mock_doc(num_pages: int, png_bytes: bytes = b"PNGDATA"):
    """Create a mock fitz Document with the given number of pages."""
    doc = MagicMock()
    doc.__len__ = MagicMock(return_value=num_pages)

    pages = []
    for _ in range(num_pages):
        pix = MagicMock()
        pix.tobytes.return_value = png_bytes
        page = MagicMock()
        page.get_pixmap.return_value = pix
        pages.append(page)

    doc.__getitem__ = MagicMock(side_effect=lambda idx: pages[idx])
    return doc


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestConvertPdfToImages:
    @patch("backend.core.utils.pdf.fitz")
    def test_single_page(self, mock_fitz):
        png_data = b"FAKE_PNG_BYTES"
        doc = _make_mock_doc(1, png_data)
        mock_fitz.open.return_value = doc
        mock_fitz.Matrix.return_value = MagicMock()

        from backend.core.utils.pdf import convert_pdf_to_images

        result = convert_pdf_to_images(b"pdf-content")

        assert len(result) == 1
        assert result[0]["mime_type"] == "image/png"
        assert result[0]["page"] == 1
        assert base64.b64decode(result[0]["data"]) == png_data
        doc.close.assert_called_once()

    @patch("backend.core.utils.pdf.fitz")
    def test_multiple_pages(self, mock_fitz):
        doc = _make_mock_doc(3, b"PNG")
        mock_fitz.open.return_value = doc
        mock_fitz.Matrix.return_value = MagicMock()

        from backend.core.utils.pdf import convert_pdf_to_images

        result = convert_pdf_to_images(b"pdf", max_pages=10)

        assert len(result) == 3
        assert [img["page"] for img in result] == [1, 2, 3]

    @patch("backend.core.utils.pdf.fitz")
    def test_max_pages_limits_output(self, mock_fitz):
        doc = _make_mock_doc(15, b"P")
        mock_fitz.open.return_value = doc
        mock_fitz.Matrix.return_value = MagicMock()

        from backend.core.utils.pdf import convert_pdf_to_images

        result = convert_pdf_to_images(b"pdf", max_pages=5)

        assert len(result) == 5
        assert result[-1]["page"] == 5

    @patch("backend.core.utils.pdf.fitz")
    def test_custom_dpi(self, mock_fitz):
        doc = _make_mock_doc(1, b"X")
        mock_fitz.open.return_value = doc
        mock_fitz.Matrix.return_value = MagicMock()

        from backend.core.utils.pdf import convert_pdf_to_images

        convert_pdf_to_images(b"pdf", dpi=300)

        zoom = 300 / 72
        mock_fitz.Matrix.assert_called_with(zoom, zoom)

    @patch("backend.core.utils.pdf.fitz")
    def test_empty_pdf_zero_pages(self, mock_fitz):
        doc = _make_mock_doc(0)
        mock_fitz.open.return_value = doc
        mock_fitz.Matrix.return_value = MagicMock()

        from backend.core.utils.pdf import convert_pdf_to_images

        result = convert_pdf_to_images(b"pdf")

        assert result == []
        doc.close.assert_called_once()

    @patch("backend.core.utils.pdf.fitz")
    def test_fitz_open_raises_returns_empty(self, mock_fitz):
        mock_fitz.open.side_effect = RuntimeError("corrupt PDF")

        from backend.core.utils.pdf import convert_pdf_to_images

        result = convert_pdf_to_images(b"bad-pdf")

        assert result == []

    @patch("backend.core.utils.pdf.fitz")
    def test_page_pixmap_raises_returns_empty(self, mock_fitz):
        doc = MagicMock()
        doc.__len__ = MagicMock(return_value=1)
        page = MagicMock()
        page.get_pixmap.side_effect = RuntimeError("render failure")
        doc.__getitem__ = MagicMock(return_value=page)
        mock_fitz.open.return_value = doc
        mock_fitz.Matrix.return_value = MagicMock()

        from backend.core.utils.pdf import convert_pdf_to_images

        result = convert_pdf_to_images(b"pdf")

        assert result == []

    @patch("backend.core.utils.pdf.fitz")
    def test_b64_data_is_valid(self, mock_fitz):
        original = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        doc = _make_mock_doc(1, original)
        mock_fitz.open.return_value = doc
        mock_fitz.Matrix.return_value = MagicMock()

        from backend.core.utils.pdf import convert_pdf_to_images

        result = convert_pdf_to_images(b"pdf")

        decoded = base64.b64decode(result[0]["data"])
        assert decoded == original

    @patch("backend.core.utils.pdf.fitz")
    def test_fitz_open_called_with_correct_args(self, mock_fitz):
        doc = _make_mock_doc(1, b"X")
        mock_fitz.open.return_value = doc
        mock_fitz.Matrix.return_value = MagicMock()

        from backend.core.utils.pdf import convert_pdf_to_images

        content = b"my-pdf-bytes"
        convert_pdf_to_images(content)

        mock_fitz.open.assert_called_once_with(stream=content, filetype="pdf")

    @patch("backend.core.utils.pdf.fitz")
    def test_default_max_pages_is_ten(self, mock_fitz):
        doc = _make_mock_doc(12, b"P")
        mock_fitz.open.return_value = doc
        mock_fitz.Matrix.return_value = MagicMock()

        from backend.core.utils.pdf import convert_pdf_to_images

        result = convert_pdf_to_images(b"pdf")

        assert len(result) == 10

    @patch("backend.core.utils.pdf.fitz")
    def test_default_dpi_is_150(self, mock_fitz):
        doc = _make_mock_doc(1, b"X")
        mock_fitz.open.return_value = doc
        mock_fitz.Matrix.return_value = MagicMock()

        from backend.core.utils.pdf import convert_pdf_to_images

        convert_pdf_to_images(b"pdf")

        zoom = 150 / 72
        mock_fitz.Matrix.assert_called_with(zoom, zoom)

    @patch("backend.core.utils.pdf.fitz")
    def test_truncation_warning_when_exceeding_max(self, mock_fitz):
        """When total_pages > max_pages, a warning is logged (no crash)."""
        doc = _make_mock_doc(20, b"X")
        mock_fitz.open.return_value = doc
        mock_fitz.Matrix.return_value = MagicMock()

        from backend.core.utils.pdf import convert_pdf_to_images

        result = convert_pdf_to_images(b"pdf", max_pages=3)

        assert len(result) == 3

    @patch("backend.core.utils.pdf.fitz")
    def test_each_image_has_required_keys(self, mock_fitz):
        doc = _make_mock_doc(2, b"PX")
        mock_fitz.open.return_value = doc
        mock_fitz.Matrix.return_value = MagicMock()

        from backend.core.utils.pdf import convert_pdf_to_images

        result = convert_pdf_to_images(b"pdf")

        for img in result:
            assert "mime_type" in img
            assert "data" in img
            assert "page" in img
