# Plan: gemini_wrapper.py 제거

## Context

`gemini_wrapper.py`의 `generate_content_sync`에 deadlock 버그가 있음:
- `with ThreadPoolExecutor` → timeout 후 `__exit__`에서 `shutdown(wait=True)` → 스레드가 아직 Gemini API 대기 중 → **무한 블록**
- 이로 인해 emotion detection timeout 시 전체 채팅 파이프라인 정지

google-genai SDK가 이미 native async (`client.aio`), native timeout (`HttpOptions`), native streaming을 지원하므로 wrapper 자체가 불필요.

## 접근 방식

`gemini_wrapper.py`를 삭제하고, 새로운 `gemini_client.py` (순수 SDK client singleton + async 헬퍼)로 대체. 모든 caller를 native async SDK 호출로 전환.

## 변경 파일 목록

### 1. 새 파일: `backend/core/utils/gemini_client.py`
- `get_gemini_client()` → `genai.Client` singleton (Lazy 패턴, `HttpOptions(timeout=180000)`)
- `get_model_name()` → `DEFAULT_GEMINI_MODEL` 반환
- `gemini_generate(contents, *, model, config, timeout_seconds)` → async, `asyncio.wait_for` + `client.aio.models.generate_content()`로 per-call timeout
- `gemini_embed(contents, *, model, task_type)` → async embedding 헬퍼

### 2. Simple callers (`.text`만 사용)
- **`backend/core/services/emotion_service.py`**: `classify_emotion` → `await gemini_generate(...)`. `classify_emotion_sync` → `client.models.generate_content()` 직접 호출. `ThreadPoolExecutor` 제거.
- **`backend/memory/permanent/importance.py`**: async 버전 → `await gemini_generate()`. sync 버전 → `client.models.generate_content()` 직접 호출. `asyncio.to_thread` 제거.
- **`backend/protocols/mcp/async_research.py`**: `await gemini_generate(...)` with thinking config.
- **`backend/protocols/mcp/google_research.py`**: `get_gemini_client()` → `client.interactions.create()` 직접.

### 3. Model 의존 callers (`self.model` 패턴)
`model: GenerativeModelWrapper` → `client: genai.Client` + `model_name: str`로 전환:
- **`backend/memory/unified.py`** (MemoryManager): `__init__(client, model_name)`, `_summarize_session` → `await client.aio.models.generate_content()`
- **`backend/memory/graph_rag.py`** (GraphRAG): `extract_and_store`, `_extract_query_entities` → `await asyncio.wait_for(client.aio.models.generate_content(...), timeout)`
- **`backend/memory/memgpt.py`** (MemGPTManager): `_extract_semantic_knowledge` → `client.models.generate_content()` (sync context 유지)

### 4. Embedding callers
- **`backend/memory/permanent/embedding_service.py`**: `genai_wrapper` → `client`, `embed_content_sync()` → `client.models.embed_content()` 직접.
- **`backend/memory/permanent/facade.py`**: `GenerativeModelWrapper(client_or_model=...)` → `get_gemini_client()`.

### 5. Complex caller (streaming + thinking + function calls)
- **`backend/llm/clients.py`** (GeminiClient):
  - `GenerativeModelWrapper` → `get_gemini_client()` 사용
  - `_build_config` 로직을 이 파일의 private 함수로 이동
  - `generate_stream`: `client.aio.models.generate_content_stream()` native async streaming. `asyncio.to_thread` + Queue 패턴 제거. SDK chunk에서 직접 `.text`, `.thought`, `.function_call` 파싱.
  - `generate`: `await client.aio.models.generate_content()` 직접.
  - `GenerateContentResponseWrapper` 불필요 → 삭제 (inline 파싱)

### 6. App startup & state
- **`backend/app.py`**: `GenerativeModelWrapper(...)` → `get_gemini_client()`. `MemoryManager(client=client, model_name=...)`.
- **`backend/api/deps.py`**: `gemini_model` → `gemini_client` 필드명 변경.

### 7. Scripts
- **`scripts/memory_gc.py`**, **`scripts/populate_knowledge_graph.py`**, **`scripts/regenerate_persona.py`**: `GenerativeModelWrapper` → `get_gemini_client()` + 직접 SDK 호출.

### 8. Tests
- **`tests/core/test_gemini_singleton.py`**: `get_gemini_wrapper` → `get_gemini_client` 테스트로 변경.
- **`tests/llm/test_stream_retry.py`**: patch 경로 및 mock 대상 업데이트.
- **`tests/memory/conftest.py`**: `mock_genai_wrapper` → `mock_genai_client`.

### 9. Cleanup
- **`backend/core/utils/__init__.py`**: `GenerativeModelWrapper` re-export 제거, `get_gemini_client` export.
- **`backend/core/utils/gemini_wrapper.py`**: 삭제.

## 실행 순서

1. `gemini_client.py` 생성
2. `__init__.py` 업데이트
3. Simple callers 전환 (emotion, importance, async_research, google_research)
4. Embedding callers 전환 (embedding_service, facade)
5. Model 의존 callers 전환 (unified.py, graph_rag.py, memgpt.py)
6. GeminiClient 재작성 (llm/clients.py) — 가장 복잡
7. App startup & deps 업데이트
8. Scripts 업데이트
9. Tests 업데이트
10. `gemini_wrapper.py` 삭제
11. `grep -r gemini_wrapper` 으로 잔여 참조 확인

## 검증
- `pytest tests/` 전체 실행
- `grep -r "gemini_wrapper\|GenerativeModelWrapper\|get_gemini_wrapper\|generate_content_sync\|embed_content_sync"` 잔여 참조 zero 확인
- 백엔드 시작 후 채팅 요청 테스트 (emotion timeout이 더 이상 전체를 블록하지 않는지 확인)
