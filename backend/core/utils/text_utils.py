"""Text sanitization utilities."""
import re


def sanitize_memory_text(text: str) -> str:
    """Sanitize text before storing in memory.

    Removes markdown syntax (**bold**, `code`), emojis, and special characters.
    Allows: English, Korean, numbers, and basic punctuation.

    Args:
        text: Raw text to sanitize

    Returns:
        Cleaned text string
    """
    if not text:
        return text

    # 마크다운 제거
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    text = re.sub(r'`([^`]+)`', r'\1', text)

    # 이모지 제거
    text = re.sub(r'[\U0001F000-\U0001FFFF]', '', text)
    text = re.sub(r'[\u2600-\u27BF]', '', text)

    # 허용: 영어, 한국어, 숫자, 기본 문장부호, 공백, 줄바꿈
    text = re.sub(r"[^a-zA-Z0-9가-힣\s.,!?:;\-()\"'\[\]\n/]", '', text)

    # 연속 공백 정리
    text = re.sub(r' +', ' ', text)

    return text.strip()
