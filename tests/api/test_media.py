"""Tests for backend.api.media -- File upload / transcription endpoints."""

import io
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from backend.api.media import _sanitize_filename, ALLOWED_UPLOAD_EXTENSIONS


# ---------------------------------------------------------------------------
# _sanitize_filename
# ---------------------------------------------------------------------------


class TestSanitizeFilename:

    def test_normal_filename(self):
        assert _sanitize_filename("report.pdf") == "report.pdf"

    def test_empty_string(self):
        assert _sanitize_filename("") == "upload.bin"

    def test_none_like(self):
        assert _sanitize_filename(None) == "upload.bin"

    def test_special_characters_replaced(self):
        result = _sanitize_filename("hello world (1).txt")
        assert " " not in result
        assert "(" not in result

    def test_path_traversal_stripped(self):
        result = _sanitize_filename("../../../etc/passwd")
        # Path(...).name strips directory components
        assert "/" not in result
        assert ".." not in result

    def test_long_filename_truncated(self):
        long_name = "a" * 300 + ".txt"
        result = _sanitize_filename(long_name)
        assert len(result) <= 200

    def test_leading_dots_stripped(self):
        result = _sanitize_filename("...hidden.txt")
        # Leading dots/underscores are stripped by .strip("._")
        assert not result.startswith(".")

    def test_windows_path(self):
        result = _sanitize_filename("C:\\Users\\test\\file.txt")
        # On Linux, Path.name treats the full string as the filename.
        # The important thing is that the result is safe (no slashes).
        assert "/" not in result
        assert result.endswith(".txt")


# ---------------------------------------------------------------------------
# ALLOWED_UPLOAD_EXTENSIONS
# ---------------------------------------------------------------------------


class TestAllowedExtensions:

    def test_pdf_allowed(self):
        assert ".pdf" in ALLOWED_UPLOAD_EXTENSIONS

    def test_common_image_types(self):
        for ext in [".png", ".jpg", ".jpeg", ".gif", ".webp"]:
            assert ext in ALLOWED_UPLOAD_EXTENSIONS

    def test_common_text_types(self):
        for ext in [".py", ".js", ".json", ".txt", ".md"]:
            assert ext in ALLOWED_UPLOAD_EXTENSIONS


# ---------------------------------------------------------------------------
# POST /transcribe
# ---------------------------------------------------------------------------


class TestTranscribeEndpoint:

    @patch("backend.media.transcribe_audio", new_callable=AsyncMock)
    def test_success(self, mock_transcribe, no_auth_client):
        mock_transcribe.return_value = "transcribed text"

        audio_data = io.BytesIO(b"\x00" * 100)
        resp = no_auth_client.post(
            "/transcribe",
            files={"audio": ("test.webm", audio_data, "audio/webm")},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["text"] == "transcribed text"

    @patch("backend.media.transcribe_audio", new_callable=AsyncMock)
    def test_failure(self, mock_transcribe, no_auth_client):
        mock_transcribe.return_value = None

        audio_data = io.BytesIO(b"\x00" * 100)
        resp = no_auth_client.post(
            "/transcribe",
            files={"audio": ("test.webm", audio_data, "audio/webm")},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is False

    @patch("backend.media.transcribe_audio", new_callable=AsyncMock)
    def test_with_language(self, mock_transcribe, no_auth_client):
        """language form field is now ignored (kept for backward compat)."""
        mock_transcribe.return_value = "Korean text"

        audio_data = io.BytesIO(b"\x00" * 100)
        resp = no_auth_client.post(
            "/transcribe",
            files={"audio": ("test.webm", audio_data, "audio/webm")},
            data={"language": "ko"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True


# ---------------------------------------------------------------------------
# POST /upload
# ---------------------------------------------------------------------------


class TestUploadEndpoint:

    def test_upload_text_file(self, no_auth_client):
        content = b"print('hello')"
        file_data = io.BytesIO(content)
        resp = no_auth_client.post(
            "/upload",
            files={"file": ("script.py", file_data, "text/x-python")},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["size"] == len(content)
        assert "content" in body  # text files get content decoded
        assert "print" in body["content"]

    def test_upload_image_file(self, no_auth_client):
        # Minimal PNG header
        content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
        file_data = io.BytesIO(content)
        resp = no_auth_client.post(
            "/upload",
            files={"file": ("photo.png", file_data, "image/png")},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body  # images get base64 encoded
        assert body["data_type"] == "image/png"

    def test_upload_pdf_file(self, no_auth_client):
        content = b"%PDF-1.4 fake pdf content"
        file_data = io.BytesIO(content)
        resp = no_auth_client.post(
            "/upload",
            files={"file": ("doc.pdf", file_data, "application/pdf")},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body

    def test_unsupported_extension(self, no_auth_client):
        file_data = io.BytesIO(b"binary stuff")
        resp = no_auth_client.post(
            "/upload",
            files={"file": ("malware.exe", file_data, "application/octet-stream")},
        )
        assert resp.status_code == 400
        body = resp.json()
        assert "unsupported" in body["detail"].lower()

    def test_upload_json_file(self, no_auth_client):
        content = b'{"key": "value"}'
        file_data = io.BytesIO(content)
        resp = no_auth_client.post(
            "/upload",
            files={"file": ("data.json", file_data, "application/json")},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "content" in body
        assert '"key"' in body["content"]

    def test_upload_jpeg(self, no_auth_client):
        content = b"\xff\xd8\xff\xe0" + b"\x00" * 50
        file_data = io.BytesIO(content)
        resp = no_auth_client.post(
            "/upload",
            files={"file": ("photo.jpeg", file_data, "image/jpeg")},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body
