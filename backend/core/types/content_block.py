"""Multi-modal content block types.

Provides discriminated union types for text, image, and file content blocks,
ported from Axel's content-block system (RES-009).
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Union


class ContentBlockType(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    FILE = "file"


@dataclass(frozen=True)
class TextBlock:
    text: str
    type: ContentBlockType = field(default=ContentBlockType.TEXT, init=False)


@dataclass(frozen=True)
class ImageBlock:
    url: str | None = None
    base64_data: str | None = None
    media_type: str = "image/jpeg"
    alt_text: str = ""
    type: ContentBlockType = field(default=ContentBlockType.IMAGE, init=False)


@dataclass(frozen=True)
class FileBlock:
    filename: str
    data: bytes
    media_type: str = "application/octet-stream"
    type: ContentBlockType = field(default=ContentBlockType.FILE, init=False)


ContentBlock = Union[TextBlock, ImageBlock, FileBlock]
MessageContent = Union[str, list[ContentBlock]]


def extract_text(content: MessageContent) -> str:
    """Extract concatenated text from MessageContent."""
    if isinstance(content, str):
        return content
    return "".join(b.text for b in content if isinstance(b, TextBlock))


def extract_images(content: MessageContent) -> list[ImageBlock]:
    """Extract all ImageBlocks from MessageContent."""
    if isinstance(content, str):
        return []
    return [b for b in content if isinstance(b, ImageBlock)]


def is_text_only(content: MessageContent) -> bool:
    """Check if content contains only text."""
    if isinstance(content, str):
        return True
    return all(isinstance(b, TextBlock) for b in content)
