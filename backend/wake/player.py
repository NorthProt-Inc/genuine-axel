import subprocess
import os
from backend.core.logging import get_logger

_log = get_logger("wake.player")

RESOURCES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "resources")

class AudioPlayer:
    def __init__(self, device_index=None):
        self.sink_name = "alsa_output.pci-0000_0c_00.1.hdmi-stereo"

        self.sounds = {
            "ready": os.path.join(RESOURCES_DIR, "chime_ready.wav"),
            "listening": os.path.join(RESOURCES_DIR, "chime_listening.wav"),
            "error": os.path.join(RESOURCES_DIR, "chime_error.wav"),
            "complete": os.path.join(RESOURCES_DIR, "chime_complete.wav"),
            "beep": os.path.join(RESOURCES_DIR, "beep.wav"),
        }
        _log.debug("aud player init", sounds=len(self.sounds))

    def play(self, sound_name: str = "ready"):
        sound_path = self.sounds.get(sound_name, self.sounds["beep"])

        if not os.path.exists(sound_path):
            _log.warning("sound file missing", name=sound_name, path=sound_path)
            return

        try:
            _log.debug("play chime", name=sound_name)
            # PERF-041: Remove capture_output since output is unused
            subprocess.run(
                ["paplay", "--device", self.sink_name, sound_path],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        except Exception as e:
            _log.error("aud play err", name=sound_name, err=str(e))

    def close(self):
        _log.debug("aud player closed")

if __name__ == "__main__":
    import time

    player = AudioPlayer()

    print("Testing sounds...")
    for name in ["ready", "listening", "error", "complete"]:
        print(f"  Playing: {name}")
        player.play(name)
        time.sleep(0.8)

    print("Done!")
