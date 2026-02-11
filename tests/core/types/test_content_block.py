"""Tests for Content Block types (Wave 1.4).

Tests multi-modal content block types: TextBlock, ImageBlock, FileBlock
and MessageContent union type.
"""

import pytest

from backend.core.types.content_block import (
    ContentBlockType,
    TextBlock,
    ImageBlock,
    FileBlock,
    ContentBlock,
    MessageContent,
    extract_text,
    extract_images,
    is_text_only,
)


class TestContentBlockType:

    def test_has_three_types(self):
        assert len(ContentBlockType) == 3

    def test_values(self):
        assert ContentBlockType.TEXT.value == "text"
        assert ContentBlockType.IMAGE.value == "image"
        assert ContentBlockType.FILE.value == "file"


class TestTextBlock:

    def test_creation(self):
        block = TextBlock(text="hello world")
        assert block.type == ContentBlockType.TEXT
        assert block.text == "hello world"

    def test_empty_text(self):
        block = TextBlock(text="")
        assert block.text == ""


class TestImageBlock:

    def test_creation_with_url(self):
        block = ImageBlock(url="https://example.com/img.png")
        assert block.type == ContentBlockType.IMAGE
        assert block.url == "https://example.com/img.png"
        assert block.base64_data is None

    def test_creation_with_base64(self):
        block = ImageBlock(base64_data="aGVsbG8=", media_type="image/png")
        assert block.base64_data == "aGVsbG8="
        assert block.media_type == "image/png"

    def test_media_type_default(self):
        block = ImageBlock(url="https://example.com/img.jpg")
        assert block.media_type == "image/jpeg"

    def test_alt_text(self):
        block = ImageBlock(url="https://example.com/img.png", alt_text="A cat")
        assert block.alt_text == "A cat"


class TestFileBlock:

    def test_creation(self):
        block = FileBlock(filename="doc.pdf", data=b"binary-content")
        assert block.type == ContentBlockType.FILE
        assert block.filename == "doc.pdf"
        assert block.data == b"binary-content"

    def test_media_type(self):
        block = FileBlock(
            filename="doc.pdf",
            data=b"content",
            media_type="application/pdf",
        )
        assert block.media_type == "application/pdf"

    def test_media_type_default(self):
        block = FileBlock(filename="test.txt", data=b"hello")
        assert block.media_type == "application/octet-stream"


class TestExtractText:

    def test_from_string(self):
        content: MessageContent = "hello"
        assert extract_text(content) == "hello"

    def test_from_text_blocks(self):
        content: MessageContent = [
            TextBlock(text="hello "),
            TextBlock(text="world"),
        ]
        assert extract_text(content) == "hello world"

    def test_from_mixed_blocks(self):
        content: MessageContent = [
            TextBlock(text="see image: "),
            ImageBlock(url="https://example.com/img.png"),
            TextBlock(text=" above"),
        ]
        assert extract_text(content) == "see image:  above"

    def test_empty_list(self):
        content: MessageContent = []
        assert extract_text(content) == ""


class TestExtractImages:

    def test_no_images(self):
        content: MessageContent = "just text"
        assert extract_images(content) == []

    def test_from_blocks(self):
        img = ImageBlock(url="https://example.com/img.png")
        content: MessageContent = [TextBlock(text="look"), img]
        result = extract_images(content)
        assert len(result) == 1
        assert result[0].url == "https://example.com/img.png"


class TestIsTextOnly:

    def test_string_is_text_only(self):
        assert is_text_only("hello") is True

    def test_text_blocks_only(self):
        content: MessageContent = [TextBlock(text="a"), TextBlock(text="b")]
        assert is_text_only(content) is True

    def test_mixed_not_text_only(self):
        content: MessageContent = [
            TextBlock(text="a"),
            ImageBlock(url="https://example.com/img.png"),
        ]
        assert is_text_only(content) is False

    def test_empty_list_is_text_only(self):
        assert is_text_only([]) is True
