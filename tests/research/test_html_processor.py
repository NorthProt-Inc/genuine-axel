"""Tests for HTML processing functions."""



class TestCleanHtml:
    """Tests for clean_html function."""

    def test_removes_script_tags(self):
        from backend.protocols.mcp.research.html_processor import clean_html

        html = "<div><p>Hello</p><script>alert('xss')</script></div>"
        result = clean_html(html)
        assert "<script>" not in result
        assert "alert" not in result
        assert "Hello" in result

    def test_removes_style_tags(self):
        from backend.protocols.mcp.research.html_processor import clean_html

        html = "<div><p>Content</p><style>.foo{color:red}</style></div>"
        result = clean_html(html)
        assert "<style>" not in result
        assert "color:red" not in result
        assert "Content" in result

    def test_removes_ad_pattern_class(self):
        from backend.protocols.mcp.research.html_processor import clean_html

        html = '<div><p>Good content</p><div class="advertisement-box">Ad text</div></div>'
        result = clean_html(html)
        assert "Ad text" not in result
        assert "Good content" in result

    def test_removes_ad_pattern_id(self):
        from backend.protocols.mcp.research.html_processor import clean_html

        html = '<div><p>Main</p><div id="cookie-consent">Accept cookies</div></div>'
        result = clean_html(html)
        assert "Accept cookies" not in result
        assert "Main" in result

    def test_removes_display_none(self):
        from backend.protocols.mcp.research.html_processor import clean_html

        html = '<div><p>Visible</p><span style="display: none">Hidden</span></div>'
        result = clean_html(html)
        assert "Hidden" not in result
        assert "Visible" in result

    def test_removes_html_comments(self):
        from backend.protocols.mcp.research.html_processor import clean_html

        html = "<div><!-- comment --><p>Content</p></div>"
        result = clean_html(html)
        assert "comment" not in result
        assert "Content" in result

    def test_empty_input(self):
        from backend.protocols.mcp.research.html_processor import clean_html

        assert clean_html("") == ""

    def test_broken_html(self):
        from backend.protocols.mcp.research.html_processor import clean_html

        html = "<div><p>Unclosed <b>bold"
        result = clean_html(html)
        assert "Unclosed" in result
        assert "bold" in result


class TestHtmlToMarkdown:
    """Tests for html_to_markdown function."""

    def test_converts_basic_html(self):
        from backend.protocols.mcp.research.html_processor import html_to_markdown

        html = "<h1>Title</h1><p>Paragraph text</p>"
        result = html_to_markdown(html)
        assert "Title" in result
        assert "Paragraph text" in result

    def test_absolutizes_relative_urls(self):
        from backend.protocols.mcp.research.html_processor import html_to_markdown

        html = '<a href="/about">About</a>'
        result = html_to_markdown(html, base_url="https://example.com")
        assert "https://example.com/about" in result

    def test_removes_images(self):
        from backend.protocols.mcp.research.html_processor import html_to_markdown

        html = '<p>Text</p><img src="photo.jpg" alt="Photo"/>'
        result = html_to_markdown(html)
        assert "photo.jpg" not in result
        assert "Text" in result

    def test_truncates_long_content(self):
        from backend.protocols.mcp.research.html_processor import html_to_markdown
        from backend.protocols.mcp.research.config import MAX_CONTENT_LENGTH

        html = "<p>" + "A" * (MAX_CONTENT_LENGTH + 1000) + "</p>"
        result = html_to_markdown(html)
        assert len(result) <= MAX_CONTENT_LENGTH + 100  # truncation suffix
        assert "[Content truncated" in result

    def test_empty_input(self):
        from backend.protocols.mcp.research.html_processor import html_to_markdown

        result = html_to_markdown("")
        assert result == ""

    def test_collapses_whitespace(self):
        from backend.protocols.mcp.research.html_processor import html_to_markdown

        html = "<p>Text</p>\n\n\n\n\n<p>More</p>"
        result = html_to_markdown(html)
        assert "\n\n\n" not in result
