"""Tests for Voice type system (Wave 4.4)."""

import pytest

from backend.media.types import (
    SpeechToTextConfig,
    TextToSpeechConfig,
    VoiceEventType,
    VoiceEvent,
    SpeechToTextProvider,
    TextToSpeechProvider,
)


class TestSpeechToTextConfig:

    def test_default_model(self):
        config = SpeechToTextConfig()
        assert config.model == "nova-3"

    def test_custom_model(self):
        config = SpeechToTextConfig(model="whisper-1")
        assert config.model == "whisper-1"

    def test_language_default(self):
        config = SpeechToTextConfig()
        assert config.language == "ko"


class TestTextToSpeechConfig:

    def test_default_model(self):
        config = TextToSpeechConfig()
        assert config.model == "tts-1"

    def test_voice(self):
        config = TextToSpeechConfig(voice="alloy")
        assert config.voice == "alloy"


class TestVoiceEvent:

    def test_transcription_event(self):
        event = VoiceEvent(
            type=VoiceEventType.TRANSCRIPTION,
            text="Hello world",
        )
        assert event.type == VoiceEventType.TRANSCRIPTION
        assert event.text == "Hello world"

    def test_synthesis_complete(self):
        event = VoiceEvent(
            type=VoiceEventType.SYNTHESIS_COMPLETE,
            audio_data=b"audio-bytes",
        )
        assert event.audio_data == b"audio-bytes"

    def test_error_event(self):
        event = VoiceEvent(
            type=VoiceEventType.ERROR,
            error="something went wrong",
        )
        assert event.error == "something went wrong"


class TestVoiceProtocols:

    def test_stt_protocol(self):
        class MySTT:
            async def transcribe(self, audio: bytes, config: SpeechToTextConfig) -> str:
                return "hello"

        stt = MySTT()
        assert isinstance(stt, SpeechToTextProvider)

    def test_tts_protocol(self):
        class MyTTS:
            async def synthesize(self, text: str, config: TextToSpeechConfig) -> bytes:
                return b"audio"

        tts = MyTTS()
        assert isinstance(tts, TextToSpeechProvider)
