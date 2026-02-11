import json
import os
from datetime import datetime
from typing import List, Dict, Any
from pathlib import Path
import tempfile
from backend.core.utils.timezone import VANCOUVER_TZ
from backend.core.logging import get_logger

_log = get_logger("core.ai_brain")

_DEFAULT_PERSONA_PATH = Path(__file__).parent.parent.parent.parent / "data" / "dynamic_persona.json"

class IdentityManager:
    def __init__(self, persona_path: str = None):
        self.persona_path = Path(persona_path) if persona_path else _DEFAULT_PERSONA_PATH
        self.persona: Dict[str, Any] = self._load_persona()
        self._last_mtime: float = self._get_file_mtime()
        self._ensure_data_dir()

    def _get_file_mtime(self) -> float:
        try:
            return self.persona_path.stat().st_mtime if self.persona_path.exists() else 0
        except Exception:
            return 0

    def _maybe_reload(self) -> bool:
        current_mtime = self._get_file_mtime()
        if current_mtime > self._last_mtime:
            self.persona = self._load_persona()
            self._last_mtime = current_mtime
            _log.info("Persona hot-reloaded", mtime=current_mtime)
            return True
        return False

    def _ensure_data_dir(self):
        self.persona_path.parent.mkdir(parents=True, exist_ok=True)

    def _load_persona(self) -> Dict[str, Any]:
        if self.persona_path.exists():
            try:
                with open(self.persona_path, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)

                    return loaded
            except PermissionError as e:

                _log.error("Persona permission denied - refusing to load default",
                              path=str(self.persona_path), error=str(e))
                raise RuntimeError(
                    f"Cannot read {self.persona_path}: permission denied. "
                    f"Fix with: sudo chown $(whoami) {self.persona_path}"
                ) from e
            except json.JSONDecodeError as e:
                _log.error("Persona JSON corrupted", path=str(self.persona_path), error=str(e))
                raise RuntimeError(f"Corrupted persona file: {self.persona_path}") from e
            except Exception as e:
                _log.warning("Persona load error", error=str(e))
                raise

        _log.info("No persona file found, using default", path=str(self.persona_path))
        return {}

    async def _save_persona(self):
        import asyncio

        json_data = json.dumps(self.persona, ensure_ascii=False, indent=2)

        tmp_path = None

        try:

            from backend.core.utils.async_utils import bounded_to_thread
            from backend.core.utils.file_utils import (
                TMP_FILE_PREFIX,
                fsync_directory,
                async_file_lock
            )

            def sync_write_with_fsync() -> str:
                with tempfile.NamedTemporaryFile(
                    mode='w',
                    encoding='utf-8',
                    dir=self.persona_path.parent,
                    prefix=TMP_FILE_PREFIX,
                    suffix=".tmp",
                    delete=False
                ) as f:
                    f.write(json_data)
                    f.flush()
                    os.fsync(f.fileno())
                    return f.name

            tmp_path = await bounded_to_thread(
                sync_write_with_fsync,
                timeout_seconds=5.0
            )

            async with async_file_lock(self.persona_path):
                os.replace(tmp_path, self.persona_path)

                await bounded_to_thread(fsync_directory, self.persona_path.parent, timeout_seconds=5.0)
            tmp_path = None

        except asyncio.TimeoutError as e:
            _log.error("Save timeout", error=str(e))
            raise
        except Exception as e:
            _log.error("Save error", error=str(e))

            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
            raise

    async def evolve(self, insights: List[str]) -> int:
        added = 0

        if not isinstance(self.persona.get("learned_behaviors"), list):
            self.persona["learned_behaviors"] = []

        for insight in insights:
            if self._is_new_insight(insight):
                self.persona["learned_behaviors"].append({
                    "insight": insight,
                    "learned_at": datetime.now(VANCOUVER_TZ).isoformat(),
                    "confidence": 0.7
                })
                added += 1

        if added > 0:
            self.persona["last_updated"] = datetime.now(VANCOUVER_TZ).isoformat()
            self.persona["version"] = self.persona.get("version", 1) + 1
            await self._save_persona()
            _log.info(
                "Persona evolved",
                new_behaviors=added,
                version=self.persona['version']
            )

        return added

    def _is_new_insight(self, insight: str) -> bool:
        insight_lower = insight.lower().strip()
        for behavior in self.persona.get("learned_behaviors", []):
            existing = behavior.get("insight", "").lower().strip()

            if insight_lower in existing or existing in insight_lower:
                return False
        return True

    async def update_preference(self, key: str, value: Any):
        self.persona["user_preferences"][key] = value
        self.persona["last_updated"] = datetime.now(VANCOUVER_TZ).isoformat()
        await self._save_persona()

    async def add_relationship_note(self, note: str):
        if note not in self.persona.get("relationship_notes", []):
            self.persona["relationship_notes"].append(note)
            self.persona["last_updated"] = datetime.now(VANCOUVER_TZ).isoformat()
            await self._save_persona()

    def get_system_prompt(self, include_recent_behaviors: int = 10) -> str:
        self._maybe_reload()

        core = self.persona.get("core_identity", "")

        voice = self.persona.get("voice_and_tone", {})
        voice_style = voice.get("style", "친근하고 직설적")
        voice_nuances = voice.get("nuance", [])
        voice_text = "\n".join([f"- {n}" for n in voice_nuances]) if voice_nuances else ""
        examples = voice.get("examples", {})
        good_example = examples.get("good", "")
        bad_example = examples.get("bad", "")

        honesty = self.persona.get("honesty_directive", "")

        CONFIDENCE_THRESHOLD = 0.3
        behaviors = self.persona.get("learned_behaviors", [])
        active_behaviors = [b for b in behaviors if b.get("confidence", 0.7) >= CONFIDENCE_THRESHOLD]
        recent_behaviors = active_behaviors[-include_recent_behaviors:] if active_behaviors else []

        def format_behavior(b):
            conf = b.get('confidence', 0.7)
            insight = b['insight']
            if conf >= 0.85:
                return f"- [반드시] {insight}"
            else:
                return f"- [경향] {insight}"

        behaviors_text = "\n".join([
            format_behavior(b)
            for b in recent_behaviors
        ]) or "아직 학습된 행동 양식이 없습니다."

        prefs = self.persona.get("user_preferences", {})
        prefs_text = "\n".join([
            f"- {k}: {v}"
            for k, v in prefs.items()
        ]) or "학습된 선호도가 없습니다."

        notes = self.persona.get("relationship_notes", [])
        notes_text = "\n".join([f"- {n}" for n in notes[-5:]]) or "관계 메모가 없습니다."

        prompt = f"""
# 나의 정체성 (Identity)
{core}

## 말투 및 화법 (Voice & Tone) - 스타일: {voice_style}
{voice_text}

### 이렇게 해라:
"{good_example}"

### 절대 하지 말 것:
"{bad_example}"

## 정직성 원칙 (Honesty Directive)
{honesty}

## 학습된 행동 양식 (Learned Behaviors)
{behaviors_text}

## 사용자 선호도 (User Preferences)
{prefs_text}

## 관계 메모 (Relationship Notes)
{notes_text}

## 기억 활용 지침
- 장기 기억에 포함된 [시간] 라벨을 참고하여 기억의 신선도를 판단해.
"""
        return prompt

    def get_stats(self) -> Dict[str, Any]:
        behaviors = self.persona.get("learned_behaviors", [])
        return {
            "version": self.persona.get("version", 1),
            "total_behaviors": len(behaviors),
            "preferences_count": len(self.persona.get("user_preferences", {})),
            "relationship_notes_count": len(self.persona.get("relationship_notes", [])),
            "last_updated": self.persona.get("last_updated"),
        }

    async def reset(self, keep_core_identity: bool = True):
        if keep_core_identity:
            core = self.persona.get("core_identity")
            self.persona = {}
            self.persona["core_identity"] = core
        else:
            self.persona = {}

        self.persona["last_updated"] = datetime.now(VANCOUVER_TZ).isoformat()
        await self._save_persona()
        _log.info("Persona reset to default", keep_core_identity=keep_core_identity)
