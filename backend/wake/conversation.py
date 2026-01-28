import os
import pyaudio
import wave
import tempfile
import httpx
import asyncio
from typing import Optional
from backend.core.logging import get_logger

_log = get_logger("wake.conversation")

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

            _log.debug("tts synth start")
            audio_data = await self._synthesize(response_text)

            if not audio_data:
                _log.error("tts fail")
                return None

            _log.debug("aud playback start", bytes=len(audio_data))
            await self._play_audio(audio_data)

            await asyncio.sleep(1.5)
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

    async def _synthesize(self, text: str) -> Optional[bytes]:

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{API_BASE}/v1/audio/speech",
                json={
                    "input": text,
                    "voice": "axel",
                    "response_format": "mp3"
                },
                headers=_auth_headers()
            )

            if resp.status_code != 200:
                _log.error("tts req fail", status=resp.status_code)
                return None

            _log.debug("tts done", bytes=len(resp.content))
            return resp.content

    async def _play_audio(self, audio_data: bytes):

        import subprocess

        temp_path = tempfile.mktemp(suffix=".mp3")
        try:
            with open(temp_path, 'wb') as f:
                f.write(audio_data)

            _log.debug("aud play via paplay", path=temp_path)

            subprocess.run(['paplay', temp_path], check=False)
            _log.debug("aud playback done")
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
