"""Lightweight emotion classification using Gemini Flash."""

import asyncio
from typing import Literal

from google.genai import types

from backend.core.logging import get_logger
from backend.core.utils.gemini_client import get_gemini_client, get_model_name, gemini_generate

_log = get_logger("services.emotion")

EmotionLabel = Literal["positive", "negative", "neutral", "mixed"]

_VALID_LABELS: set[str] = {"positive", "negative", "neutral", "mixed"}

_CLASSIFY_PROMPT = (
    "Classify the emotional tone of the following message into exactly ONE word: "
    "positive, negative, neutral, or mixed.\n"
    "Respond with ONLY that single word, nothing else.\n\n"
    "Message: {text}"
)

_CONFIG = types.GenerateContentConfig(
    temperature=0.0,
    max_output_tokens=4,
)


def classify_emotion_sync(text: str) -> EmotionLabel:
    """Classify emotion synchronously. Returns 'neutral' on any failure.

    Args:
        text: Message text to classify

    Returns:
        One of: positive, negative, neutral, mixed
    """
    if not text or len(text.strip()) < 2:
        return "neutral"

    try:
        client = get_gemini_client()
        prompt = _CLASSIFY_PROMPT.format(text=text[:500])
        response = client.models.generate_content(
            model=get_model_name(),
            contents=prompt,
            config=_CONFIG,
        )
        raw = response.text if response.text else ""
        label = raw.strip().lower()
        if label in _VALID_LABELS:
            _log.debug("emotion_classified", label=label, text_len=len(text))
            return label

        if label:
            _log.warning("emotion_unexpected_label", raw=label)
        else:
            _log.debug("emotion_empty_response", text_len=len(text))
        return "neutral"

    except Exception as e:
        _log.debug("emotion_classify_failed", error=str(e)[:100])
        return "neutral"


async def classify_emotion(text: str) -> EmotionLabel:
    """Classify emotion asynchronously. Returns 'neutral' on any failure.

    Args:
        text: Message text to classify

    Returns:
        One of: positive, negative, neutral, mixed
    """
    if not text or len(text.strip()) < 2:
        return "neutral"

    try:
        response = await gemini_generate(
            contents=_CLASSIFY_PROMPT.format(text=text[:500]),
            config=_CONFIG,
            timeout_seconds=20.0,
        )
        raw = response.text if response.text else ""
        label = raw.strip().lower()
        if label in _VALID_LABELS:
            _log.debug("emotion_classified", label=label, text_len=len(text))
            return label

        if label:
            _log.warning("emotion_unexpected_label", raw=label)
        else:
            _log.debug("emotion_empty_response", text_len=len(text))
        return "neutral"

    except Exception as e:
        _log.debug("emotion_classify_failed", error=str(e)[:100])
        return "neutral"
