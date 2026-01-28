from .detector import WakewordDetector
from .player import AudioPlayer
from .conversation import ConversationHandler
import sys
import asyncio
from backend.core.logging import get_logger

_log = get_logger("wake.runner")

def main():
    try:
        _log.info("=== Axel Voice Asst starting ===")

        detector = WakewordDetector(sensitivity=0.2, gain=3.0, device_index=11)
        player = AudioPlayer(device_index=11)
        handler = ConversationHandler(device_index=11)

        _log.info("components init done", dev=11, sensitivity=0.2, gain=3.0)

        for detected in detector.listen():
            if detected:
                _log.info(">> WAKEWORD TRIGGERED <<")

                player.play("listening")

                try:
                    result = asyncio.run(handler.handle_wakeword())
                    if result:
                        _log.info("conv done ok")
                        player.play("complete")
                    else:
                        _log.warning("conv no res")
                        player.play("error")
                except Exception as e:
                    _log.exception("conv fail", err=str(e))
                    player.play("error")

                detector.reset()

                _log.debug("ready for next wakeword")

    except KeyboardInterrupt:
        _log.info("shutdown requested (Ctrl+C)")
        if 'detector' in locals():
            detector.stop()
        if 'handler' in locals():
            handler.close()
        sys.exit(0)
    except Exception as e:
        _log.critical("fatal err", err=str(e))
        sys.exit(1)

if __name__ == "__main__":
    main()
