import torch
import io
import asyncio
import threading
import numpy as np
import soundfile as sf
import librosa
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Tuple
from backend.core.logging import get_logger
from backend.core.utils.lazy import Lazy
from backend.config import TTS_SYNTHESIS_TIMEOUT, TTS_QUEUE_MAX_PENDING

# GPU optimizations
torch.backends.cudnn.benchmark = True
torch.backends.cuda.matmul.allow_tf32 = True
torch.backends.cudnn.allow_tf32 = True
# NOTE: torch.set_float32_matmul_precision('high') intentionally omitted - causes quality degradation

_logger = get_logger("media.qwen_tts")


class QueueFullError(Exception):
    """Raised when TTS synthesis queue is at capacity."""

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_VOICE_DIR = _PROJECT_ROOT / "data" / "voice"
_CHUNKS_DIR = _VOICE_DIR / "chunks"
_EMBEDDING_CACHE = _VOICE_DIR / "speaker_embedding.pt"
TEMPERATURE = 0.3
SPEAKER_EMBEDDING_SCALE = 1.5  # Amplify speaker embedding signal (1.0 = default)


def _create_model():
    """Load Qwen3-TTS model.

    Returns:
        Qwen3TTSModel instance
    """
    _logger.info("Loading Qwen3-TTS model...")
    from qwen_tts import Qwen3TTSModel
    model = Qwen3TTSModel.from_pretrained(
        "Qwen/Qwen3-TTS-12Hz-0.6B-Base",
        device_map="cuda:0",
        dtype=torch.bfloat16,
        attn_implementation="flash_attention_2",
    )
    _logger.info("Qwen3-TTS model loaded")
    return model


_lazy_model: Lazy = Lazy(_create_model)


def get_model():
    """Return the cached Qwen3-TTS model singleton (thread-safe).

    Returns:
        Qwen3TTSModel instance
    """
    return _lazy_model.get()


def _create_voice_prompt() -> tuple[dict, torch.Tensor]:
    """Extract and average speaker embeddings from reference chunks.

    Loads cached embedding from disk if available, otherwise computes
    from audio chunks and saves the result for future use.

    Returns:
        Tuple of (voice prompt dict, averaged speaker embedding tensor)
    """
    model = get_model()

    # Try loading cached embedding
    if _EMBEDDING_CACHE.exists():
        _logger.info("Loading cached speaker embedding", path=str(_EMBEDDING_CACHE))
        avg_embedding = torch.load(_EMBEDDING_CACHE, map_location="cuda:0", weights_only=True)
    else:
        # Compute from chunks
        chunk_paths = sorted(_CHUNKS_DIR.glob("chunk_*.wav"))
        if not chunk_paths:
            raise FileNotFoundError(f"No reference chunks in {_CHUNKS_DIR}")

        _logger.info("Extracting speaker embeddings from chunks...", count=len(chunk_paths))
        target_sr = model.model.speaker_encoder_sample_rate

        embeddings = []
        for i, chunk_path in enumerate(chunk_paths):
            wav, sr = sf.read(chunk_path, dtype="float32")
            if sr != target_sr:
                wav = librosa.resample(wav, orig_sr=sr, target_sr=target_sr)
                sr = target_sr

            emb = model.model.extract_speaker_embedding(wav, sr)
            embeddings.append(emb)
            if (i + 1) % 50 == 0:
                _logger.debug("Chunk embedding progress", done=i + 1)

        avg_embedding = torch.stack(embeddings).mean(dim=0)
        _logger.info("Speaker embedding averaged", chunks=len(embeddings))

        # Cache to disk
        _VOICE_DIR.mkdir(parents=True, exist_ok=True)
        torch.save(avg_embedding, _EMBEDDING_CACHE)
        _logger.info("Speaker embedding cached", path=str(_EMBEDDING_CACHE))

    scaled_embedding = avg_embedding * SPEAKER_EMBEDDING_SCALE
    _logger.info(
        "Speaker embedding scaled",
        scale=SPEAKER_EMBEDDING_SCALE,
        norm_before=float(avg_embedding.norm()),
        norm_after=float(scaled_embedding.norm()),
    )

    voice_prompt = {
        'ref_code': [None],
        'ref_spk_embedding': [scaled_embedding],
        'x_vector_only_mode': [True],
        'icl_mode': [False],
    }

    return voice_prompt, scaled_embedding


_lazy_voice_prompt: Lazy = Lazy(_create_voice_prompt)


def get_voice_prompt() -> tuple[dict, torch.Tensor]:
    """Return cached voice prompt and speaker embedding (thread-safe).

    Returns:
        Tuple of (voice prompt dict, averaged speaker embedding tensor)
    """
    return _lazy_voice_prompt.get()


class Qwen3TTS:
    def __init__(self) -> None:
        self.model = get_model()
        self._voice_prompt, self._avg_embedding = get_voice_prompt()
        self._executor = ThreadPoolExecutor(max_workers=1)
        self._pending = 0
        self._pending_lock = threading.Lock()

    async def synthesize(
        self, text: str, *, message_id: Optional[str] = None
    ) -> Tuple[bytes, int]:
        """Synthesize text to speech audio (single-shot, x_vector mode).

        Args:
            text: Text to synthesize
            message_id: Unused, kept for API compatibility

        Returns:
            Tuple of (WAV bytes, sample rate)

        Raises:
            QueueFullError: When pending requests exceed TTS_QUEUE_MAX_PENDING
            asyncio.TimeoutError: When synthesis exceeds TTS_SYNTHESIS_TIMEOUT
        """
        with self._pending_lock:
            if self._pending >= TTS_QUEUE_MAX_PENDING:
                _logger.warning("TTS queue full", pending=self._pending)
                raise QueueFullError(f"TTS queue full ({self._pending} pending)")
            self._pending += 1

        try:
            _logger.info("TTS request", chars=len(text), pending=self._pending)
            loop = asyncio.get_event_loop()
            return await asyncio.wait_for(
                loop.run_in_executor(self._executor, self._synthesize_sync, text),
                timeout=TTS_SYNTHESIS_TIMEOUT,
            )
        finally:
            with self._pending_lock:
                self._pending -= 1

    def _synthesize_sync(self, text: str) -> Tuple[bytes, int]:
        """Synchronous single-shot synthesis using x_vector_only mode.

        Args:
            text: Text to synthesize

        Returns:
            Tuple of (WAV bytes, sample rate)
        """
        from backend.media.tts_manager import get_tts_manager

        get_tts_manager().touch()

        wav_np, sr = self._synthesize_xvector(text)

        buffer = io.BytesIO()
        sf.write(buffer, wav_np, sr, format='WAV')
        buffer.seek(0)

        _logger.info("TTS done", duration_samples=len(wav_np))
        return buffer.read(), sr

    def _synthesize_xvector(self, text: str) -> Tuple[np.ndarray, int]:
        """Synthesize using x_vector_only mode (speaker embedding only).

        Args:
            text: Text to synthesize

        Returns:
            Tuple of (waveform numpy array, sample rate)
        """
        wavs, sr = self.model.generate_voice_clone(
            text=[text],
            language=["Korean"],
            voice_clone_prompt=self._voice_prompt,
            temperature=TEMPERATURE,
        )
        wav = wavs[0]
        return wav.cpu().numpy() if hasattr(wav, 'cpu') else wav, sr

