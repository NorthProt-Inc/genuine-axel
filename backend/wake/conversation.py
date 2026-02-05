import os
import re
import pyaudio
import wave
import tempfile
import httpx
import asyncio
import subprocess
from typing import Optional, List
from backend.core.logging import get_logger

_log = get_logger("wake.conversation")


def split_sentences(text: str) -> List[str]:
    """Split text into sentences by punctuation.

    Args:
        text: Input text to split

    Returns:
        List of sentence strings
    """
    sentences = re.split(r'(?<=[.!?。！？])\s*', text)
    sentences = [s.strip() for s in sentences if s.strip()]
    return sentences if sentences else [text]

API_BASE = os.environ.get("AXNMIHN_API", "http://localhost:8000")
API_KEY = os.environ.get("AXNMIHN_API_KEY") or os.environ.get("API_KEY")

def _auth_headers() -> dict:
    if API_KEY:
        return {"Authorization": f"Bearer {API_KEY}"}
    return {}

RATE = 16000
CHANNELS = 1
FORMAT = pyaudio.paInt16
CHUNK = 1024
MAX_RECORD_SECONDS = 20
SILENCE_THRESHOLD = 500
SILENCE_DURATION = 3.0

class ConversationHandler:
    def __init__(self, device_index: int = 11):
        self.device_index = device_index
        self.p = pyaudio.PyAudio()

    async def handle_wakeword(self) -> Optional[str]:

        try:

            _log.debug("conv flow start, pause 0.5s")
            await asyncio.sleep(0.5)

            _log.info("recording user speech")
            audio_path = self._record_until_silence()

            if not audio_path:
                _log.warning("no speech det")
                return None

            _log.debug("stt start")
            user_text = await self._transcribe(audio_path)

            if not user_text:
                _log.warning("stt empty")
                return None

            _log.info("user input", text=user_text[:80])

            _log.debug("chat req start")
            response_text = await self._chat(user_text)

            if not response_text:
                _log.warning("chat no res")
                return None

            _log.info("axel res", text=response_text[:80])

            _log.debug("tts streaming start")
            await self._synthesize_and_play_streaming(response_text)

            await asyncio.sleep(1.0)
            _log.info("conv done, ready for next")

            return response_text

        except Exception as e:
            _log.exception("conv flow err", err=str(e))
            return None
        finally:

            if 'audio_path' in locals() and audio_path and os.path.exists(audio_path):
                os.remove(audio_path)

    def _record_until_silence(self) -> Optional[str]:

        stream = self.p.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=RATE,
            input=True,
            input_device_index=self.device_index,
            frames_per_buffer=CHUNK
        )

        frames = []
        silent_chunks = 0
        has_speech = False

        _log.debug("rec strm open, listening", dev=self.device_index)

        for _ in range(int(RATE / CHUNK * MAX_RECORD_SECONDS)):
            data = stream.read(CHUNK)
            frames.append(data)

            amplitude = max(abs(int.from_bytes(data[i:i+2], 'little', signed=True))
                          for i in range(0, len(data), 2))

            if amplitude > SILENCE_THRESHOLD:
                has_speech = True
                silent_chunks = 0
            else:
                silent_chunks += 1

            if has_speech and silent_chunks > int(SILENCE_DURATION * RATE / CHUNK):
                _log.debug("silence det, stop rec")
                break

        stream.stop_stream()
        stream.close()

        if not has_speech:
            _log.debug("no speech in rec")
            return None

        temp_path = tempfile.mktemp(suffix=".wav")
        with wave.open(temp_path, 'wb') as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(self.p.get_sample_size(FORMAT))
            wf.setframerate(RATE)
            wf.writeframes(b''.join(frames))

        _log.debug("rec saved", frames=len(frames), path=temp_path)
        return temp_path

    async def _transcribe(self, audio_path: str) -> Optional[str]:

        async with httpx.AsyncClient(timeout=30.0) as client:
            with open(audio_path, 'rb') as f:
                files = {'file': ('audio.wav', f, 'audio/wav')}
                resp = await client.post(
                    f"{API_BASE}/v1/audio/transcriptions",
                    files=files,
                    data={'model': 'nova-3'},
                    headers=_auth_headers()
                )

            if resp.status_code != 200:
                _log.error("stt req fail", status=resp.status_code)
                return None

            text = resp.json().get('text', '')
            _log.debug("stt done", chars=len(text))
            return text

    async def _chat(self, user_text: str) -> Optional[str]:

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{API_BASE}/v1/chat/completions",
                json={
                    "model": "auto",
                    "messages": [{"role": "user", "content": user_text}],
                    "stream": False
                },
                headers=_auth_headers()
            )

            if resp.status_code != 200:
                _log.error("chat req fail", status=resp.status_code)
                return None

            data = resp.json()
            content = data.get('choices', [{}])[0].get('message', {}).get('content', '')
            _log.debug("chat res recv", chars=len(content))
            return content

    async def _synthesize_sentence(self, text: str) -> Optional[bytes]:
        """Synthesize a single sentence to audio via TTS API.

        Args:
            text: Sentence text to synthesize

        Returns:
            Audio bytes or None on failure
        """
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{API_BASE}/v1/audio/speech",
                json={
                    "input": text,
                    "voice": "axel",
                    "response_format": "wav"
                },
                headers=_auth_headers()
            )

            if resp.status_code != 200:
                _log.error("tts req fail", status=resp.status_code, text=text[:30])
                return None

            return resp.content

    async def _synthesize_and_play_streaming(self, text: str):
        """Synthesize and play audio with sentence-level streaming.

        Args:
            text: Full text to speak
        """
        sentences = split_sentences(text)
        _log.info("tts streaming", sentences=len(sentences))

        audio_queue = asyncio.Queue()
        tts_done = asyncio.Event()

        async def tts_worker():
            """백그라운드 TTS 처리"""
            for i, sentence in enumerate(sentences):
                _log.debug("tts sentence", idx=i, text=sentence[:30])
                audio = await self._synthesize_sentence(sentence)
                if audio:
                    await audio_queue.put(audio)
            tts_done.set()

        async def play_worker():
            """오디오 재생 (큐에서 가져와서 재생)"""
            while True:
                try:
                    audio = await asyncio.wait_for(audio_queue.get(), timeout=1.0)
                    await self._play_audio_async(audio)
                except asyncio.TimeoutError:
                    if tts_done.is_set() and audio_queue.empty():
                        break

        # TTS와 재생을 동시 실행
        await asyncio.gather(tts_worker(), play_worker())
        _log.debug("tts streaming done")

    async def _play_audio_async(self, audio_data: bytes):
        """Play audio asynchronously using paplay.

        Args:
            audio_data: WAV audio bytes to play
        """
        temp_path = tempfile.mktemp(suffix=".wav")
        try:
            with open(temp_path, 'wb') as f:
                f.write(audio_data)

            _log.debug("aud play", bytes=len(audio_data))
            proc = await asyncio.create_subprocess_exec(
                'paplay', temp_path,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL
            )
            await proc.wait()
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def close(self):
        self.p.terminate()

if __name__ == "__main__":
    handler = ConversationHandler(device_index=11)
    try:
        result = asyncio.run(handler.handle_wakeword())
        print(f"Result: {result}")
    finally:
        handler.close()
