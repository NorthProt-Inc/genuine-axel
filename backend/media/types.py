"""Voice type system — STT/TTS Protocol abstractions and VoiceEvent union."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, runtime_checkable


@dataclass
class SpeechToTextConfig:
    """Configuration for speech-to-text providers."""

    model: str = "nova-3"
    language: str = "ko"
    sample_rate: int = 16000
    encoding: str = "linear16"


@dataclass
class TextToSpeechConfig:
    """Configuration for text-to-speech providers."""

    model: str = "tts-1"
    voice: str = "shimmer"
    speed: float = 1.0
    output_format: str = "mp3"


class VoiceEventType(str, Enum):
    """Discriminator for voice events."""

    TRANSCRIPTION = "transcription"
    SYNTHESIS_COMPLETE = "synthesis_complete"
    ERROR = "error"


@dataclass
class VoiceEvent:
    """Discriminated union for voice pipeline events."""

    type: VoiceEventType
    text: str | None = None
    audio_data: bytes | None = None
    error: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@runtime_checkable
class SpeechToTextProvider(Protocol):
    """Protocol for STT providers (Deepgram, Whisper, etc.)."""

    async def transcribe(self, audio: bytes, config: SpeechToTextConfig) -> str: ...


@runtime_checkable
class TextToSpeechProvider(Protocol):
    """Protocol for TTS providers (OpenAI, Qwen, etc.)."""

    async def synthesize(self, text: str, config: TextToSpeechConfig) -> bytes: ...
