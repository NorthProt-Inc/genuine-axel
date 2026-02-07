"""Shared TTS utilities used by both in-process and service modes.

Contains text cleaning and audio format conversion functions that are
independent of the TTS model itself.
"""

import asyncio
import os
import re
import subprocess
import tempfile

from backend.config import TTS_FFMPEG_TIMEOUT


def clean_text_for_tts(text: str) -> str:
    """Strip markdown and special characters from text for TTS input.

    Args:
        text: Raw text possibly containing markdown formatting

    Returns:
        Cleaned plain text suitable for TTS synthesis
    """
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    text = re.sub(r"#{1,6}\s*", "", text)
    text = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", text)
    text = re.sub(r"```[\s\S]*?```", "", text)
    text = re.sub(r"[^\w\s가-힣ㄱ-ㅎㅏ-ㅣ,.!?;:'\"()~\-]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _convert_wav_to_mp3_sync(wav_bytes: bytes) -> bytes:
    """Convert WAV audio to MP3 using ffmpeg (sync, runs in thread).

    Args:
        wav_bytes: Raw WAV audio data

    Returns:
        MP3 encoded audio bytes
    """
    wav_tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    wav_path = wav_tmp.name
    mp3_path = wav_path.replace(".wav", ".mp3")

    try:
        wav_tmp.write(wav_bytes)
        wav_tmp.close()

        subprocess.run(
            [
                "ffmpeg", "-y", "-i", wav_path,
                "-codec:a", "libmp3lame", "-qscale:a", "2",
                mp3_path,
            ],
            check=True,
            capture_output=True,
            timeout=TTS_FFMPEG_TIMEOUT,
        )

        with open(mp3_path, "rb") as f:
            return f.read()
    finally:
        if os.path.exists(wav_path):
            os.unlink(wav_path)
        if os.path.exists(mp3_path):
            os.unlink(mp3_path)


async def convert_wav_to_mp3(wav_bytes: bytes) -> bytes:
    """Convert WAV audio to MP3 using ffmpeg (async wrapper).

    Args:
        wav_bytes: Raw WAV audio data

    Returns:
        MP3 encoded audio bytes
    """
    return await asyncio.to_thread(_convert_wav_to_mp3_sync, wav_bytes)
