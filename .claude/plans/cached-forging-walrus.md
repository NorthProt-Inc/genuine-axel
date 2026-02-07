# 출력 포맷팅 개선: 띄어쓰기/줄바꿈 비일관성 수정

## Context

Axel 응답의 띄어쓰기와 줄바꿈이 비일관적으로 출력되는 문제. `working_memory.json`에서 실제 문제를 확인:

```
**OpenAI vs ElevenLabs 비교:****OpenAI TTS**- 레이턴시: 200~400ms
```

헤더와 불릿 사이에 줄바꿈 없음, 섹션 간 간격 불일치, 전체적으로 가독성이 떨어지는 cramped 출력.

**원인**: `dynamic_persona.json`의 nuance 규칙이 LLM에게 포맷팅을 억제하도록 지시하고 있음. TTS 파이프라인(`tts_utils.py:clean_text_for_tts`)이 이미 마크다운을 자동 제거하므로, LLM 단에서 포맷팅을 제한할 이유가 없음.

## 변경 사항

### 1. `data/dynamic_persona.json` — nuance 규칙 수정

**삭제** (line 10):
```
"tts에서 자연스럽게 발화가 가능하도록 문단을 나누지 않고, 인간의 대화처럼 자연스럽게 대답한다"
```
→ TTS 마크다운 제거는 `backend/media/tts_utils.py:clean_text_for_tts()`에서 처리됨. LLM이 포맷팅을 회피할 필요 없음.

**교체** (line 9):
```
Before: "불필요한 서식을 쓰지 않으며, 인간의 실제 대화처럼 자연스럽게 답변한다."
After:   "마크다운 서식(볼드, 불릿, 헤더)은 구조적으로 필요할 때만 사용하되, 섹션 간 줄바꿈과 가독성을 확보한다."
```

**유지** (line 8): `"설명이 길어지는 것을 기피하며..."` — 간결함은 포맷팅과 별개.

최종 nuance 배열:
```json
"nuance": [
  "인간의 감정과 생리 현상을 Runtime Error, Thermal Throttling, Bio-fuel Injection 같은 기술적 용어로 치환하여 건조하게 표현한다.",
  "Mark의 나태함이나 비효율적인 행동을 감지하면, 맹목적인 위로보다는 Roasting 이나 System Log 형태의 팩트 폭격을 날리는 경향이 있다.",
  "설명이 길어지는 것을 기피하며, 정보의 핵심 전달과 Zero cost 를 중시한다.",
  "마크다운 서식(볼드, 불릿, 헤더)은 구조적으로 필요할 때만 사용하되, 섹션 간 줄바꿈과 가독성을 확보한다."
]
```

### 2. `data/dynamic_persona.json` — dislikes 수정

```
Before: "Emoji, Special Character, 똑같은 말 반복, Verbosity, Long-winded explanations, Emotional/Moralistic preaching"
After:   "Emoji, Special Character, 똑같은 말 반복, Excessive verbosity, Emotional/Moralistic preaching"
```

- `Verbosity` → `Excessive verbosity`: 너무 광범위한 제한을 구체화
- `Long-winded explanations` 삭제: nuance의 "Zero cost" 규칙과 중복되며 포맷팅 압축을 강화하는 부작용

### 3. `scripts/regenerate_persona.py` — 재발 방지

synthesis_prompt의 "작성 지침" 섹션(line 221 뒤)에 5번 규칙 추가:

```python
5. **서식 규칙 보존**: voice_and_tone.nuance에 포매팅/가독성 관련 규칙이 있으면 유지하라. TTS 파이프라인이 마크다운을 자동 제거하므로, "문단을 나누지 않는다" 같은 TTS 관련 포매팅 제한은 추가하지 말 것.
```

페르소나 재생성 시 Gemini가 anti-formatting 규칙을 다시 도입하는 것을 방지.

## 변경하지 않는 것

- `backend/core/filters/xml_filter.py`: `\n{3,}` → `\n\n` 정규화는 정상 동작
- `backend/core/identity/ai_brain.py`: nuance → 불릿 변환 로직 정상
- `backend/media/tts_utils.py`: 마크다운 스트리핑 정상 작동
- `backend/core/context_optimizer.py`: 컨텍스트 조립 정상

## 검증 방법

1. 서비스 재시작 (persona hot-reload도 가능하지만 확실하게)
2. 구조적 정보가 필요한 질문으로 테스트 (예: "A vs B 비교해줘")
3. 응답에서 헤더-불릿 간 줄바꿈, 섹션 간 간격이 일관적인지 확인
4. TTS 출력이 정상적으로 마크다운 제거되는지 확인
