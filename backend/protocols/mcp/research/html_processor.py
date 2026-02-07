"""HTML cleaning and markdown conversion for research pages."""

import re
from urllib.parse import urljoin

from backend.protocols.mcp.research.config import (
    AD_PATTERNS,
    EXCLUDED_TAGS,
    MAX_CONTENT_LENGTH,
)


def clean_html(html: str) -> str:
    """Remove noise elements from HTML for content extraction.

    Strips scripts, styles, ads, hidden elements, and comments.

    Args:
        html: Raw HTML string

    Returns:
        Cleaned HTML string
    """
    if not html:
        return ""

    from bs4 import BeautifulSoup, Comment

    soup = BeautifulSoup(html, "html.parser")

    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()

    for tag in EXCLUDED_TAGS:
        for element in soup.find_all(tag):
            element.decompose()

    for pattern in AD_PATTERNS:
        for element in soup.find_all(class_=re.compile(pattern, re.I)):
            element.decompose()
        for element in soup.find_all(id=re.compile(pattern, re.I)):
            element.decompose()

    for element in soup.find_all(style=re.compile(r"display:\s*none", re.I)):
        element.decompose()

    return str(soup)


def html_to_markdown(html: str, base_url: str = "") -> str:
    """Convert HTML to clean markdown with content limits.

    Args:
        html: Raw HTML string
        base_url: Base URL for resolving relative links

    Returns:
        Markdown string, truncated if exceeding MAX_CONTENT_LENGTH
    """
    if not html:
        return ""

    from markdownify import MarkdownConverter

    cleaned_html = clean_html(html)

    class _Converter(MarkdownConverter):
        def convert_a(self, el, text, **kwargs):
            href = el.get("href", "")
            if href and not href.startswith(("http://", "https://", "mailto:", "#")):
                href = urljoin(base_url, href)
            if not text.strip():
                return ""
            return f"[{text}]({href})" if href else text

        def convert_img(self, el, text, **kwargs):
            return ""

    markdown = _Converter(
        heading_style="ATX",
        bullets="-",
        strip=["script", "style", "noscript", "iframe"],
    ).convert(cleaned_html)

    markdown = re.sub(r"\n{3,}", "\n\n", markdown)
    markdown = re.sub(r" {2,}", " ", markdown)
    markdown = markdown.strip()

    if len(markdown) > MAX_CONTENT_LENGTH:
        markdown = markdown[:MAX_CONTENT_LENGTH] + "\n\n[Content truncated due to length...]"

    return markdown
