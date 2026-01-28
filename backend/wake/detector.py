import os
import numpy as np
import pyaudio
import openwakeword
from openwakeword.model import Model
from collections import deque
from backend.core.logging import get_logger

_log = get_logger("wake.detector")

CHUNK_SIZE = 1280
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000
WAKE_MODEL_PATH = os.path.join(os.path.dirname(__file__), "models/hey_agssel.onnx")

class WakewordDetector:
    def __init__(self, sensitivity: float = 0.5, gain: float = 1.0, device_index: int = None):
        self.sensitivity = sensitivity
        self.gain = gain
        self.device_index = device_index
        self.p = pyaudio.PyAudio()
        self.stream = None

        if not os.path.exists(WAKE_MODEL_PATH):
            _log.error("mdl not found", path=WAKE_MODEL_PATH)
            raise FileNotFoundError(f"Wakeword model not found at {WAKE_MODEL_PATH}")

        _log.info("loading wakeword mdl", path=WAKE_MODEL_PATH)
        self.owwModel = Model(wakeword_model_paths=[WAKE_MODEL_PATH])
        _log.info("wakeword mdl loaded", sensitivity=sensitivity, gain=gain)

    def start(self):

        self.stream = self.p.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=RATE,
            input=True,
            input_device_index=self.device_index,
            frames_per_buffer=CHUNK_SIZE
        )
        _log.info("mic strm start", dev=self.device_index or "default")

    def stop(self):

        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
        self.p.terminate()
        _log.info("det strm stopped")

    def reset(self):

        import numpy as np
        silence = np.zeros(self.owwModel.model_inputs[0].shape[-1], dtype=np.int16)
        for _ in range(5):
            self.owwModel.predict(silence)
        _log.debug("det buf reset")

    def listen(self):

        if not self.stream:
            self.start()

        _log.info("listening for wakeword")

        while True:
            try:

                audio_data = np.frombuffer(self.stream.read(CHUNK_SIZE), dtype=np.int16)

                if self.gain != 1.0:

                    audio_float = audio_data.astype(np.float32) * self.gain
                    audio_data = np.clip(audio_float, -32768, 32767).astype(np.int16)

                prediction = self.owwModel.predict(audio_data)

                for model_name, score in prediction.items():
                    if score > self.sensitivity:
                        _log.info("wakeword det!", mdl=model_name, score=f"{score:.4f}")
                        yield True

            except KeyboardInterrupt:
                _log.info("det interrupted by user")
                break
            except Exception as e:
                _log.exception("det loop err", err=str(e))
                break
