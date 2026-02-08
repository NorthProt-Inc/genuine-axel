# 04. 광범위한 예외 삼킴 (except: pass)

> 분석 날짜: 2026-02-04
> 분석 범위: 프로젝트 전반 (약 240+개소)

## 요약

프로젝트 전반에 걸쳐 **240개 이상**의 예외 처리 패턴이 발견되었으며, 그 중 대부분이 예외를 로깅만 하고 조용히 실패하거나, 아예 무시(`pass`)하는 방식입니다. 특히 **bare `except:`** 3개소와 **`except Exception: pass`** 형태의 완전한 예외 삼킴이 약 25개소 이상 존재합니다. 이로 인해 데이터 손실, 숨겨진 버그, 디버깅 불가능한 상태가 발생할 수 있습니다.

## 발견사항

### CRITICAL

- **Bare `except:` 사용 — 체크포인트 복구 무시**: (`scripts/populate_knowledge_graph.py:112`)
  - 영향: 체크포인트 파일 파싱 실패 시 조용히 무시. 손상된 체크포인트로 인해 이미 처리된 데이터가 재처리되거나, 반대로 처리되지 않은 데이터가 누락될 수 있음
  - 현재 코드:
    ```python
    try:
        with open(checkpoint_path) as f:
            checkpoint = json.load(f)
            start_batch = checkpoint.get("last_batch", 0)
    except:  # bare except - 모든 예외 무시
        pass
    ```
  - 개선안:
    ```python
    try:
        with open(checkpoint_path) as f:
            checkpoint = json.load(f)
            start_batch = checkpoint.get("last_batch", 0)
    except (json.JSONDecodeError, FileNotFoundError) as e:
        _log.warning("Checkpoint recovery failed, starting from beginning",
                     error=str(e), checkpoint_path=checkpoint_path)
    except Exception as e:
        _log.error("Unexpected checkpoint error", error=str(e))
        # 예상치 못한 에러는 상위로 전파 고려
    ```

- **Bare `except:` 사용 — 날짜 파싱 무시**: (`scripts/dedup_knowledge_graph.py:172,223`)
  - 영향: dead entity 판별 및 importance 재계산 시 잘못된 날짜 데이터를 가진 엔티티가 조용히 통과. 잘못된 데이터가 그래프에 남아 검색 품질 저하
  - 현재 코드 (172줄):
    ```python
    try:
        created = datetime.fromisoformat(created_str)
        if created < cutoff:
            dead.append(eid)
    except:
        pass  # 날짜 파싱 실패 = 해당 엔티티 무시
    ```
  - 개선안:
    ```python
    try:
        created = datetime.fromisoformat(created_str)
        if created < cutoff:
            dead.append(eid)
    except ValueError as e:
        # 파싱 불가능한 날짜를 가진 엔티티는 오래된 것으로 간주
        _log.warning("Invalid date format, treating as old entity",
                     entity_id=eid, created_str=created_str)
        dead.append(eid)
    ```

### HIGH

- **임베딩 업데이트 실패 무시**: (`backend/memory/permanent.py:639`)
  - 영향: `flush_access_updates()`에서 개별 메모리의 `last_accessed` 업데이트 실패를 무시. 메모리 decay 계산이 부정확해지고, 중요한 기억이 조기 삭제될 수 있음
  - 현재 코드:
    ```python
    for doc_id in ids_to_update:
        try:
            self.collection.update(
                ids=[doc_id],
                metadatas=[{"last_accessed": now}]
            )
            updated += 1
        except Exception:
            pass  # 업데이트 실패 완전 무시
    ```
  - 개선안:
    ```python
    failed_ids = []
    for doc_id in ids_to_update:
        try:
            self.collection.update(
                ids=[doc_id],
                metadatas=[{"last_accessed": now}]
            )
            updated += 1
        except Exception as e:
            failed_ids.append(doc_id)
            _log.debug("Access update failed", doc_id=doc_id[:8], error=str(e))

    if failed_ids:
        _log.warning("Some access updates failed",
                     failed_count=len(failed_ids),
                     total=len(ids_to_update))
        # 실패한 ID들을 다시 pending에 추가하여 재시도
        self._pending_access_updates.update(failed_ids)
    ```

- **파일 읽기/디렉토리 리스팅 실패 무시**: (`backend/core/tools/system_observer.py:298,339`)
  - 영향: 코드 검색 및 로그 분석 시 일부 파일/디렉토리 접근 실패를 조용히 무시. 검색 결과가 불완전해지고 사용자에게 알리지 않음
  - 현재 코드 (339줄):
    ```python
    try:
        with open(full_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception:
        return None  # 모든 에러를 None으로 처리
    ```
  - 개선안:
    ```python
    try:
        with open(full_path, 'r', encoding='utf-8') as f:
            return f.read()
    except PermissionError:
        _log.warning("Permission denied reading file", path=str(full_path))
        return None
    except FileNotFoundError:
        return None  # 파일이 없는 것은 정상적인 경우일 수 있음
    except UnicodeDecodeError:
        _log.debug("Binary file skipped", path=str(full_path))
        return None
    except Exception as e:
        _log.error("Unexpected file read error", path=str(full_path), error=str(e))
        return None
    ```

- **브라우저 페이지 닫기 실패 무시**: (`backend/protocols/mcp/research_server.py:432,443`)
  - 영향: Playwright 페이지 닫기 실패 시 브라우저 리소스 누수. 장시간 운영 시 메모리 증가 및 성능 저하
  - 현재 코드:
    ```python
    finally:
        if page:
            try:
                await page.close()
            except Exception:
                pass  # 페이지 닫기 실패 무시
    ```
  - 개선안:
    ```python
    finally:
        if page:
            try:
                await page.close()
            except Exception as e:
                _log.warning("Failed to close browser page, potential resource leak",
                             url=url[:50], error=str(e))
                # 페이지 닫기 실패 시 전체 브라우저 컨텍스트 재시작 고려
                try:
                    await _restart_browser_context()
                except Exception:
                    pass
    ```

- **타임스탬프 파싱 실패 무시**: (`backend/protocols/mcp/memory_server.py:192,219,258`)
  - 영향: 메모리 컨텍스트에서 시간 정보가 "unknown"으로 표시되어 시간 기반 메모리 검색 품질 저하
  - 현재 코드:
    ```python
    def _parse_timestamp(timestamp_str: str):
        ...
        except Exception:
            return None  # 모든 파싱 에러 무시
    ```
  - 개선안:
    ```python
    def _parse_timestamp(timestamp_str: str):
        if not timestamp_str:
            return None

        # 여러 포맷 시도
        formats = [
            '%Y-%m-%dT%H:%M:%S%z',
            '%Y-%m-%dT%H:%M:%S.%f%z',
            '%Y-%m-%d %H:%M:%S',
            '%Y-%m-%d',
        ]

        for fmt in formats:
            try:
                parsed = datetime.strptime(timestamp_str, fmt)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed
            except ValueError:
                continue

        _log.debug("Unparseable timestamp", timestamp=timestamp_str[:30])
        return None
    ```

### MEDIUM

- **SQLite 연결 예외 re-raise 후 롤백만**: (`backend/memory/recent.py:44-46`)
  - 영향: 컨텍스트 매니저에서 예외 발생 시 롤백은 하지만 예외 타입/메시지가 보존되지 않아 디버깅 어려움
  - 현재 코드:
    ```python
    try:
        yield self._connection
    except Exception:
        self._connection.rollback()
        raise
    ```
  - 개선안: 이 패턴 자체는 괜찮으나, 롤백 실패 시의 처리가 없음
    ```python
    try:
        yield self._connection
    except Exception as e:
        try:
            self._connection.rollback()
        except Exception as rollback_error:
            _log.error("Rollback also failed", original_error=str(e),
                       rollback_error=str(rollback_error))
        raise
    ```

- **세션 요약 실패 시 조용한 실패**: (`backend/memory/recent.py:680-688`)
  - 영향: 만료된 세션 요약 처리 중 일부 세션 실패 시 전체 작업은 계속 진행되나, 실패한 세션이 다음 실행에서 재처리되지 않을 수 있음

- **scripts/memory_gc.py 전반** — 약 18개소
  - 영향: 메모리 GC 스크립트의 각 단계에서 실패 시 빈 딕셔너리 반환. 부분 실패가 전체 실패처럼 보이고, 어느 단계에서 문제가 발생했는지 추적 어려움

- **GenAI 래퍼 초기화 실패**: (`backend/memory/permanent.py:287-289`)
  - 영향: 임베딩 모델 초기화 실패 시 `self.genai_wrapper = None`으로 설정. 이후 모든 메모리 저장/검색이 실패하지만, 원인이 로그에만 남아 디버깅 어려움

- **그래프 연결 수 조회 실패**: (`backend/memory/permanent.py:144`)
  - 영향: `get_connection_count()`에서 GraphRAG import 또는 조회 실패 시 0 반환. decay 계산이 실제보다 빠르게 진행됨

### LOW

- **로그 파일 stat 실패 무시**: (`backend/core/tools/system_observer.py:298`)
  - 영향: 로그 파일 목록에서 일부 파일이 누락될 수 있으나, 기능에 큰 영향 없음

- **chat_handler.py 전반** — 약 12개소
  - 대부분 적절한 로깅과 함께 예외를 처리하고 있으나, 일부는 너무 넓은 범위의 `except Exception`을 사용

- **MCP 서버 import 예외**: (`backend/core/mcp_server.py:6`)
  - 영향: 모듈 로드 시점의 import 실패를 무시. 다운스트림에서 더 혼란스러운 에러 발생 가능

## 예외 처리 패턴별 분포

| 패턴 | 개수 | 위험도 |
|------|------|--------|
| `except:` (bare except) | 3 | CRITICAL |
| `except Exception: pass` | ~25 | HIGH |
| `except Exception: return None/{}` | ~60 | MEDIUM |
| `except Exception as e: log + return` | ~150 | LOW |

## 파일별 예외 처리 개수 (상위 10개)

| 파일 | 개수 | 비고 |
|------|------|------|
| `scripts/memory_gc.py` | 18 | 메모리 정리 스크립트 |
| `backend/memory/permanent.py` | 17 | 장기 메모리 저장소 |
| `backend/memory/recent.py` | 16 | 세션 아카이브 |
| `backend/core/chat_handler.py` | 12 | 메인 대화 파이프라인 |
| `backend/protocols/mcp/memory_server.py` | 12 | MCP 메모리 인터페이스 |
| `backend/core/mcp_tools/memory_tools.py` | 11 | 메모리 도구 |
| `backend/protocols/mcp/research_server.py` | 10 | 웹 연구 서버 |
| `backend/memory/unified.py` | 9 | 메모리 매니저 |
| `backend/core/mcp_tools/system_tools.py` | 9 | 시스템 도구 |
| `backend/core/utils/gemini_wrapper.py` | 6 | LLM 래퍼 |

## 개선 제안

### 1. 예외 처리 정책 수립

```python
# backend/core/utils/exceptions.py

class AxelError(Exception):
    """Base exception for all Axel errors"""
    pass

class MemoryError(AxelError):
    """Memory system errors"""
    pass

class ToolError(AxelError):
    """MCP tool execution errors"""
    pass

class ExternalServiceError(AxelError):
    """External API/service errors"""
    pass
```

### 2. 예외 분류 및 처리 가이드라인

| 예외 유형 | 처리 방식 | 예시 |
|----------|----------|------|
| 복구 가능 | 로깅 + 기본값 반환 | 네트워크 타임아웃 → 재시도 |
| 복구 불가능 | 로깅 + 상위 전파 | 인증 실패 → 에러 응답 |
| 데이터 손실 위험 | 로깅 + 경고 + 안전한 실패 | 메모리 저장 실패 → 재시도 큐 |
| 리소스 누수 위험 | 로깅 + 정리 시도 + 경고 | 브라우저 닫기 실패 → 컨텍스트 재시작 |

### 3. 재시도 로직 통합

```python
# backend/core/utils/retry.py에 이미 존재하지만 미사용

from backend.core.utils.retry import retry_with_backoff

@retry_with_backoff(max_retries=3, exceptions=(TimeoutError, ConnectionError))
async def external_api_call():
    ...
```

### 4. 점진적 개선 계획

1. **즉시 수정** (CRITICAL): bare `except:` 3개소 → 구체적 예외 타입으로 변경
2. **1주 내** (HIGH): 데이터 손실 위험이 있는 메모리 관련 예외 처리 개선
3. **2주 내** (MEDIUM): 리소스 누수 위험이 있는 브라우저/연결 관련 예외 처리 개선
4. **지속적**: 새 코드 작성 시 예외 처리 가이드라인 준수

## 수정 난이도

| 항목 | 난이도 | 이유 |
|------|--------|------|
| Bare except → 구체적 예외 | 쉬움 | 단순 문자열 교체 + 예외 타입 지정 |
| 메모리 시스템 예외 처리 | 중간 | 실패 시 재시도 로직 추가 필요 |
| 브라우저 리소스 누수 | 중간 | Playwright 생명주기 이해 필요 |
| 예외 정책 통합 | 어려움 | 프로젝트 전반에 걸친 변경 |
| 테스트 추가 | 어려움 | 예외 경로 테스트를 위한 모킹 필요 |
