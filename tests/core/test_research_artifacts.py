"""Tests for backend.core.research_artifacts.

Uses tmp_path for all file operations to avoid touching real filesystem.
"""

import re
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.core.research_artifacts import (
    ARTIFACT_THRESHOLD,
    MAX_SUMMARY_CHARS,
    MAX_SUMMARY_LINES,
    _sanitize_filename,
    create_artifact_reference,
    generate_summary,
    list_artifacts,
    process_content_for_artifact,
    read_artifact,
    save_artifact,
    should_save_as_artifact,
)


# ---------------------------------------------------------------------------
# should_save_as_artifact
# ---------------------------------------------------------------------------


class TestShouldSaveAsArtifact:
    def test_empty_content_returns_false(self):
        assert should_save_as_artifact("") is False

    def test_none_content_returns_false(self):
        assert should_save_as_artifact(None) is False

    def test_short_content_returns_false(self):
        assert should_save_as_artifact("x" * ARTIFACT_THRESHOLD) is False

    def test_long_content_returns_true(self):
        assert should_save_as_artifact("x" * (ARTIFACT_THRESHOLD + 1)) is True

    def test_exactly_at_threshold_returns_false(self):
        assert should_save_as_artifact("x" * ARTIFACT_THRESHOLD) is False

    def test_one_over_threshold(self):
        assert should_save_as_artifact("x" * (ARTIFACT_THRESHOLD + 1)) is True

    def test_threshold_is_2000(self):
        assert ARTIFACT_THRESHOLD == 2000


# ---------------------------------------------------------------------------
# generate_summary
# ---------------------------------------------------------------------------


class TestGenerateSummary:
    def test_empty_content(self):
        assert generate_summary("") == "No content"

    def test_none_content(self):
        assert generate_summary(None) == "No content"

    def test_heading_extracted_as_title(self):
        content = "# My Document\n\nThis is a longer paragraph that should appear in the summary and is over fifty characters."
        summary = generate_summary(content)
        assert "Title: My Document" in summary

    def test_first_line_as_title_when_no_heading(self):
        content = "Introduction paragraph\n\nSome long text that should appear as a bullet point in the summary and needs to be over fifty characters."
        summary = generate_summary(content)
        assert "Title:" in summary
        assert "Introduction" in summary

    def test_paragraphs_as_bullet_points(self):
        content = (
            "# Title\n\n"
            "This is the first paragraph that is long enough to be extracted as a bullet point.\n\n"
            "This is the second paragraph that is also long enough to be extracted as a bullet point."
        )
        summary = generate_summary(content)
        assert summary.count("- ") >= 1

    def test_skips_short_paragraphs(self):
        content = "# Title\n\nShort.\n\nThis is a much longer paragraph that should be long enough to be included in the output."
        summary = generate_summary(content)
        # "Short." is under 50 chars and should be skipped
        lines_without_title = [l for l in summary.split("\n") if l.startswith("- ")]
        for line in lines_without_title:
            assert "Short." not in line

    def test_skips_headings_in_body(self):
        content = "# Title\n\n## Subtitle\n\nThis paragraph is long enough to be included in the summary as a bullet point for testing."
        summary = generate_summary(content)
        assert "Subtitle" not in summary

    def test_skips_bold_only_paragraphs(self):
        content = "# Title\n\n**Bold Only**\n\nThis paragraph is long enough to be included in the summary as a bullet point for testing."
        summary = generate_summary(content)
        assert "Bold Only" not in summary

    def test_skips_link_paragraphs(self):
        content = "# Title\n\n[Link text](url)\n\nThis paragraph is long enough to be included in the summary as a bullet point for testing."
        summary = generate_summary(content)
        assert "[Link text]" not in summary

    def test_skips_image_paragraphs(self):
        content = "# Title\n\n![Alt text](img.png)\n\nThis paragraph is long enough to be included in the summary as a bullet point for testing."
        summary = generate_summary(content)
        assert "![Alt text]" not in summary

    def test_max_lines_respected(self):
        paragraphs = [
            f"Paragraph number {i} with enough text to be over fifty characters for inclusion."
            for i in range(20)
        ]
        content = "# Title\n\n" + "\n\n".join(paragraphs)
        summary = generate_summary(content, max_lines=3)
        # Title line + at most 2 bullet points
        lines = [l for l in summary.split("\n") if l.strip()]
        assert len(lines) <= 3

    def test_summary_truncated_at_max_chars(self):
        paragraphs = [
            f"This is paragraph {i} which contains enough words to be over fifty characters easily."
            for i in range(100)
        ]
        content = "# A Document\n\n" + "\n\n".join(paragraphs)
        summary = generate_summary(content, max_lines=50)
        assert len(summary) <= MAX_SUMMARY_CHARS

    def test_long_first_sentence_truncated(self):
        long_sentence = "A" * 150 + ". More text."
        content = "# Title\n\n" + long_sentence
        summary = generate_summary(content)
        if "- " in summary:
            bullet = summary.split("- ", 1)[1].split("\n")[0]
            assert len(bullet) <= 101

    def test_fallback_when_no_content(self):
        content = "\n\n\n"
        summary = generate_summary(content)
        assert summary == "Content summary unavailable"

    def test_blank_lines_before_heading_skipped(self):
        content = "\n\n\n# My Title\n\nLong paragraph with sufficient length to be included in the generated summary output."
        summary = generate_summary(content)
        assert "Title: My Title" in summary


# ---------------------------------------------------------------------------
# _sanitize_filename
# ---------------------------------------------------------------------------


class TestSanitizeFilename:
    def test_basic_url(self):
        filename = _sanitize_filename("https://example.com/page")
        assert filename.endswith(".md")
        assert "example-com" in filename

    def test_contains_hash(self):
        filename = _sanitize_filename("https://example.com/page")
        parts = filename.split("_")
        assert len(parts) >= 3

    def test_contains_timestamp(self):
        filename = _sanitize_filename("https://example.com")
        assert re.search(r"\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}", filename)

    def test_special_chars_sanitized(self):
        filename = _sanitize_filename("https://example.com/path?q=1&b=2")
        assert re.match(r"^[\w\-.]+$", filename)

    def test_different_urls_different_filenames(self):
        f1 = _sanitize_filename("https://example.com/page1")
        f2 = _sanitize_filename("https://example.com/page2")
        assert f1 != f2

    def test_url_with_port(self):
        filename = _sanitize_filename("https://localhost:8080/api")
        assert "localhost-8080" in filename


# ---------------------------------------------------------------------------
# save_artifact
# ---------------------------------------------------------------------------


class TestSaveArtifact:
    def test_saves_file_and_returns_summary(self, tmp_path):
        with patch("backend.core.research_artifacts.ARTIFACTS_DIR", tmp_path):
            url = "https://example.com/article"
            content = "# Test Article\n\nThis is a longer paragraph that should appear in the summary and is over fifty characters."

            filepath, summary = save_artifact(url, content)

            assert filepath.exists()
            assert "Title: Test Article" in summary

            saved = filepath.read_text(encoding="utf-8")
            assert "source: https://example.com/article" in saved
            assert content in saved

    def test_creates_directory_if_missing(self, tmp_path):
        new_dir = tmp_path / "nested" / "artifacts"
        with patch("backend.core.research_artifacts.ARTIFACTS_DIR", new_dir):
            save_artifact("https://example.com", "content " * 300)

            assert new_dir.exists()

    def test_frontmatter_contains_metadata(self, tmp_path):
        with patch("backend.core.research_artifacts.ARTIFACTS_DIR", tmp_path):
            content = "Test content"
            filepath, _ = save_artifact("https://example.com/page", content)

            saved = filepath.read_text(encoding="utf-8")
            assert saved.startswith("---")
            assert "source:" in saved
            assert "saved_at:" in saved
            assert "content_length:" in saved

    def test_content_length_in_frontmatter(self, tmp_path):
        with patch("backend.core.research_artifacts.ARTIFACTS_DIR", tmp_path):
            content = "x" * 500
            filepath, _ = save_artifact("https://example.com", content)

            saved = filepath.read_text(encoding="utf-8")
            assert "content_length: 500" in saved

    def test_file_is_markdown(self, tmp_path):
        with patch("backend.core.research_artifacts.ARTIFACTS_DIR", tmp_path):
            filepath, _ = save_artifact("https://example.com", "content")
            assert filepath.suffix == ".md"


# ---------------------------------------------------------------------------
# create_artifact_reference
# ---------------------------------------------------------------------------


class TestCreateArtifactReference:
    def test_contains_url(self):
        ref = create_artifact_reference(
            "https://example.com",
            Path("/artifacts/test.md"),
            "Test summary",
        )
        assert "https://example.com" in ref

    def test_contains_filepath(self):
        ref = create_artifact_reference(
            "https://example.com",
            Path("/artifacts/test.md"),
            "Test summary",
        )
        assert "/artifacts/test.md" in ref

    def test_contains_summary(self):
        ref = create_artifact_reference(
            "https://example.com",
            Path("/artifacts/test.md"),
            "My summary line",
        )
        assert "My summary line" in ref

    def test_contains_artifact_saved_header(self):
        ref = create_artifact_reference(
            "https://example.com",
            Path("/artifacts/test.md"),
            "summary",
        )
        assert "[ARTIFACT SAVED]" in ref

    def test_contains_read_artifact_hint(self):
        ref = create_artifact_reference(
            "https://example.com",
            Path("/artifacts/test.md"),
            "summary",
        )
        assert "read_artifact" in ref


# ---------------------------------------------------------------------------
# read_artifact
# ---------------------------------------------------------------------------


class TestReadArtifact:
    def test_reads_content_stripping_frontmatter(self, tmp_path):
        f = tmp_path / "artifact.md"
        f.write_text("---\nsource: url\n---\nActual content here", encoding="utf-8")

        result = read_artifact(str(f))
        assert result == "Actual content here"

    def test_reads_without_frontmatter(self, tmp_path):
        f = tmp_path / "plain.md"
        f.write_text("No frontmatter here", encoding="utf-8")

        result = read_artifact(str(f))
        assert result == "No frontmatter here"

    def test_nonexistent_file_returns_none(self, tmp_path):
        result = read_artifact(str(tmp_path / "missing.md"))
        assert result is None

    def test_relative_path_resolved_via_project_root(self, tmp_path):
        f = tmp_path / "rel.md"
        f.write_text("---\nsource: x\n---\nRelative content", encoding="utf-8")

        with patch("backend.core.research_artifacts.PROJECT_ROOT", tmp_path):
            result = read_artifact("rel.md")
            assert result == "Relative content"

    def test_absolute_path_reads_directly(self, tmp_path):
        f = tmp_path / "abs.md"
        f.write_text("---\nk: v\n---\nDirect read", encoding="utf-8")

        result = read_artifact(str(f))
        assert result == "Direct read"

    def test_frontmatter_with_multiple_dashes(self, tmp_path):
        f = tmp_path / "multi.md"
        f.write_text(
            "---\nsource: url\nsaved_at: 2024-01-01\n---\nBody text",
            encoding="utf-8",
        )

        result = read_artifact(str(f))
        assert result == "Body text"

    def test_read_error_returns_none(self, tmp_path):
        f = tmp_path / "noperm.md"
        f.write_text("content")
        f.chmod(0o000)

        result = read_artifact(str(f))
        assert result is None

        f.chmod(0o644)

    def test_empty_frontmatter(self, tmp_path):
        f = tmp_path / "empty_fm.md"
        f.write_text("---\n---\nContent after empty frontmatter", encoding="utf-8")

        result = read_artifact(str(f))
        assert result == "Content after empty frontmatter"


# ---------------------------------------------------------------------------
# process_content_for_artifact
# ---------------------------------------------------------------------------


class TestProcessContentForArtifact:
    def test_short_content_returned_as_is(self):
        content = "Short content"
        result = process_content_for_artifact("https://example.com", content)
        assert result == content

    @patch("backend.core.research_artifacts.save_artifact")
    def test_long_content_saved_as_artifact(self, mock_save):
        mock_save.return_value = (Path("/tmp/artifact.md"), "summary text")

        content = "x" * (ARTIFACT_THRESHOLD + 1)
        result = process_content_for_artifact("https://example.com", content)

        assert "[ARTIFACT SAVED]" in result
        mock_save.assert_called_once()

    @patch("backend.core.research_artifacts.save_artifact")
    def test_save_failure_returns_truncated(self, mock_save):
        mock_save.side_effect = IOError("disk full")

        content = "y" * (ARTIFACT_THRESHOLD + 500)
        result = process_content_for_artifact("https://example.com", content)

        assert f"truncated at {ARTIFACT_THRESHOLD}" in result.lower()
        assert len(result) < len(content)

    def test_exactly_at_threshold_not_saved(self):
        content = "z" * ARTIFACT_THRESHOLD
        result = process_content_for_artifact("https://example.com", content)
        assert result == content

    def test_empty_content_returned_as_is(self):
        result = process_content_for_artifact("https://example.com", "")
        assert result == ""


# ---------------------------------------------------------------------------
# list_artifacts
# ---------------------------------------------------------------------------


class TestListArtifacts:
    def test_empty_directory(self, tmp_path):
        with patch("backend.core.research_artifacts.ARTIFACTS_DIR", tmp_path):
            result = list_artifacts()
            assert result == []

    def test_nonexistent_directory(self, tmp_path):
        missing = tmp_path / "does_not_exist"
        with patch("backend.core.research_artifacts.ARTIFACTS_DIR", missing):
            result = list_artifacts()
            assert result == []

    def test_lists_artifacts_with_metadata(self, tmp_path):
        f1 = tmp_path / "2024-01-01_example_abc.md"
        f1.write_text(
            "---\nsource: https://example.com\nsaved_at: 2024-01-01T00:00:00\n---\nContent",
            encoding="utf-8",
        )

        with patch("backend.core.research_artifacts.ARTIFACTS_DIR", tmp_path):
            result = list_artifacts()

        assert len(result) == 1
        assert result[0]["url"] == "https://example.com"
        assert result[0]["saved_at"] == "2024-01-01T00:00:00"
        assert result[0]["size"] > 0

    def test_limit_parameter(self, tmp_path):
        for i in range(5):
            f = tmp_path / f"file_{i}.md"
            f.write_text(f"---\nsource: url{i}\nsaved_at: ts{i}\n---\nBody", encoding="utf-8")

        with patch("backend.core.research_artifacts.ARTIFACTS_DIR", tmp_path):
            result = list_artifacts(limit=3)
            assert len(result) == 3

    def test_corrupt_file_skipped(self, tmp_path):
        good = tmp_path / "good.md"
        good.write_text("---\nsource: url\nsaved_at: ts\n---\nContent", encoding="utf-8")

        bad = tmp_path / "bad.md"
        bad.write_text("---\nsource: url\nsaved_at: ts\n---\nContent", encoding="utf-8")
        bad.chmod(0o000)

        with patch("backend.core.research_artifacts.ARTIFACTS_DIR", tmp_path):
            result = list_artifacts()

        assert len(result) >= 1
        assert any(r["url"] == "url" for r in result)

        bad.chmod(0o644)

    def test_file_without_frontmatter(self, tmp_path):
        f = tmp_path / "nofm.md"
        f.write_text("Just plain content without frontmatter", encoding="utf-8")

        with patch("backend.core.research_artifacts.ARTIFACTS_DIR", tmp_path):
            result = list_artifacts()

        assert len(result) == 1
        assert result[0]["url"] == ""
        assert result[0]["saved_at"] == ""

    def test_default_limit_is_20(self, tmp_path):
        for i in range(25):
            f = tmp_path / f"f{i:02d}.md"
            f.write_text(f"---\nsource: u\nsaved_at: t\n---\n", encoding="utf-8")

        with patch("backend.core.research_artifacts.ARTIFACTS_DIR", tmp_path):
            result = list_artifacts()
            assert len(result) == 20

    def test_sorted_reverse_order(self, tmp_path):
        """Artifacts are sorted newest first (reverse filename order)."""
        for name in ["aaa.md", "bbb.md", "zzz.md"]:
            f = tmp_path / name
            f.write_text("---\nsource: u\nsaved_at: t\n---\n", encoding="utf-8")

        with patch("backend.core.research_artifacts.ARTIFACTS_DIR", tmp_path):
            result = list_artifacts()

        paths = [r["path"] for r in result]
        assert "zzz.md" in paths[0]
