import torch
import io
import re
import asyncio
import numpy as np
import soundfile as sf
import librosa
from concurrent.futures import ThreadPoolExecutor
from typing import Tuple, AsyncGenerator
from backend.core.logging import get_logger

# GPU optimizations
torch.backends.cudnn.benchmark = True
torch.backends.cuda.matmul.allow_tf32 = True
torch.backends.cudnn.allow_tf32 = True
# NOTE: torch.set_float32_matmul_precision('high') intentionally omitted - causes quality degradation

_logger = get_logger("media.qwen_tts")
_model = None
_voice_prompt = None

REF_CHUNKS = [f"/tmp/soldier76_chunks/chunk_{i}.wav" for i in range(57)]  # 28분 전체 (마지막 짧은 청크 제외)
TEMPERATURE = 0.1


def split_sentences(text: str) -> list[str]:
    """Split text into sentences for Korean/English.

    Args:
        text: Input text to split

    Returns:
        List of sentence strings
    """
    pattern = r'(?<=[.!?。？！])["\']?\s+'
    sentences = re.split(pattern, text.strip())
    return [s for s in sentences if s.strip()]


def get_model():
    """Load and cache Qwen3-TTS model singleton.

    Returns:
        Qwen3TTSModel instance
    """
    global _model
    if _model is None:
        _logger.info("Loading Qwen3-TTS model...")
        from qwen_tts import Qwen3TTSModel
        _model = Qwen3TTSModel.from_pretrained(
            "Qwen/Qwen3-TTS-12Hz-1.7B-Base",
            device_map="cuda:0",
            dtype=torch.bfloat16,
            attn_implementation="flash_attention_2",
        )
        _logger.info("Qwen3-TTS model loaded")
    return _model


def get_voice_prompt():
    """Extract and average speaker embeddings from reference chunks.

    Returns:
        Voice prompt dict with averaged speaker embedding
    """
    global _voice_prompt
    if _voice_prompt is not None:
        return _voice_prompt

    model = get_model()
    _logger.info("Extracting speaker embeddings from chunks...", count=len(REF_CHUNKS))

    embeddings = []
    for i, chunk_path in enumerate(REF_CHUNKS):
        wav, sr = sf.read(chunk_path)
        if sr != model.model.speaker_encoder_sample_rate:
            wav = librosa.resample(wav.astype(np.float32),
                                   orig_sr=sr,
                                   target_sr=model.model.speaker_encoder_sample_rate)
            sr = model.model.speaker_encoder_sample_rate

        emb = model.model.extract_speaker_embedding(wav, sr)
        embeddings.append(emb)
        _logger.debug("Chunk embedding", idx=i)

    avg_embedding = torch.stack(embeddings).mean(dim=0)
    _logger.info("Speaker embedding averaged", chunks=len(embeddings))

    _voice_prompt = {
        'ref_code': [None],
        'ref_spk_embedding': [avg_embedding],
        'x_vector_only_mode': [True],
        'icl_mode': [False],
    }

    return _voice_prompt


class Qwen3TTS:
    def __init__(self):
        self.model = get_model()
        self._voice_prompt = get_voice_prompt()
        self._executor = ThreadPoolExecutor(max_workers=1)

    async def synthesize(self, text: str) -> Tuple[bytes, int]:
        """Synthesize text to speech audio.

        Args:
            text: Text to synthesize

        Returns:
            Tuple of (WAV bytes, sample rate)
        """
        _logger.info("TTS request", chars=len(text))
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self._executor, self._synthesize_sync, text)

    def _synthesize_sync(self, text: str) -> Tuple[bytes, int]:
        wavs, sr = self.model.generate_voice_clone(
            text=[text],
            language=["Korean"],
            voice_clone_prompt=self._voice_prompt,
            temperature=TEMPERATURE,
        )

        wav = wavs[0]
        wav_np = wav.cpu().numpy() if hasattr(wav, 'cpu') else wav

        buffer = io.BytesIO()
        sf.write(buffer, wav_np, sr, format='WAV')
        buffer.seek(0)

        _logger.info("TTS done", duration_samples=len(wav_np))
        return buffer.read(), sr

    async def synthesize_stream(self, text: str) -> AsyncGenerator[Tuple[bytes, int], None]:
        """Stream TTS synthesis sentence by sentence.

        Args:
            text: Full text to synthesize

        Yields:
            Tuple of (WAV bytes, sample rate) for each sentence
        """
        sentences = split_sentences(text)
        if not sentences:
            sentences = [text]

        _logger.info("Streaming TTS", sentences=len(sentences))
        loop = asyncio.get_event_loop()

        for i, sentence in enumerate(sentences):
            _logger.debug("Processing sentence", idx=i)

            def process_one(s):
                wavs, sr = self.model.generate_voice_clone(
                    text=[s],
                    language=["Korean"],
                    voice_clone_prompt=self._voice_prompt,
                    temperature=TEMPERATURE,
                )
                wav = wavs[0]
                wav_np = wav.cpu().numpy() if hasattr(wav, 'cpu') else wav
                buffer = io.BytesIO()
                sf.write(buffer, wav_np, sr, format='WAV')
                buffer.seek(0)
                return buffer.read(), sr

            audio_bytes, sr = await loop.run_in_executor(self._executor, process_one, sentence)
            yield audio_bytes, sr
