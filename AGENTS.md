# AGENTS.md — axnmihn Custom Agents

## debugger
버그 추적 및 수정 전문가

### Instructions
- 백엔드 로그 확인: `tail -n 100 logs/backend.log`
- 에러 로그 필터: `grep -E "ERROR|CRITICAL" logs/backend.log | tail -20`
- systemd 로그: `journalctl --user -u axnmihn-backend --no-pager -n 50`
- 서비스 상태: `systemctl --user status axnmihn-backend axnmihn-mcp`
- 헬스체크: `curl -s http://localhost:8000/health | python3 -m json.tool`
- 에러 분류: Connection, Auth, Data, Server 카테고리로 분류
- 트레이스백에서 소스 파일:라인, 콜 스택 추출
- 근본 원인 분석 후 최소 수정으로 해결

### 사용 예시 (Usage Examples)

#### 시나리오 1: 백엔드 서비스 시작 실패
```bash
# 문제: systemctl --user start axnmihn-backend 실패
# 접근 방법:
1. journalctl --user -u axnmihn-backend --no-pager -n 100
2. 에러 메시지에서 ImportError, ModuleNotFoundError 확인
3. 가상환경 활성화 확인: which python3
4. 의존성 설치 확인: ~/projects-env/bin/pip list | grep fastapi
```

#### 시나리오 2: API 엔드포인트 500 에러
```bash
# 문제: POST /api/memory/store 호출 시 500 에러
# 디버깅 단계:
1. tail -f logs/backend.log (실시간 모니터링)
2. curl -X POST http://localhost:8000/api/memory/store \
   -H "Content-Type: application/json" \
   -d '{"content":"test","importance":0.5}'
3. 로그에서 트레이스백 확인
4. 해당 파일 확인 및 수정
```

#### 시나리오 3: 메모리 누수 의심
```bash
# 증상: 장시간 실행 후 메모리 사용량 증가
# 분석:
1. ps aux | grep "python.*backend" (메모리 사용량 확인)
2. systemctl --user restart axnmihn-backend
3. watch -n 5 'ps aux | grep "python.*backend"' (주기적 모니터링)
4. 로그에서 메모리 관련 경고 확인: grep "memory" logs/backend.log
```

### 트러블슈팅 가이드 (Troubleshooting Guide)

#### 자주 발생하는 문제

**1. ModuleNotFoundError: No module named 'fastapi'**
```bash
# 원인: 가상환경 미활성화 또는 의존성 미설치
# 해결:
source ~/projects-env/bin/activate
pip install -r backend/requirements.txt
```

**2. sqlite3.OperationalError: database is locked**
```bash
# 원인: 여러 프로세스가 동시에 DB 접근
# 해결:
fuser storage/axnmihn.db  # 프로세스 확인
systemctl --user stop axnmihn-backend axnmihn-mcp
rm -f storage/axnmihn.db-wal storage/axnmihn.db-shm
systemctl --user start axnmihn-backend axnmihn-mcp
```

**3. Connection refused (포트 충돌)**
```bash
# 원인: 8000번 포트 이미 사용 중
# 해결:
lsof -i :8000  # 포트 사용 프로세스 확인
kill -9 <PID>  # 또는 backend/config.py에서 포트 변경
```

**4. CORS 에러 (프론트엔드 연동 시)**
```bash
# 원인: CORS 설정 누락
# 해결: backend/main.py에서 확인
# app.add_middleware(CORSMiddleware, allow_origins=["*"])
```

#### 디버그 모드 활성화
```bash
# .env 파일 설정
DEBUG=true
LOG_LEVEL=DEBUG

# 또는 직접 실행
DEBUG=true python -m backend.main
```

## documenter
Technical documentation specialist

### Instructions
- 문서는 한국어 기본, 코드 예제는 영어
- docs/ 디렉토리에 문서 작성
- API 문서: 엔드포인트, 파라미터, 응답 형식 포함
- 아키텍처 문서: 모듈 간 관계, 데이터 흐름 설명
- README.md 업데이트 시 기존 구조 유지

### 사용 예시 (Usage Examples)

#### 시나리오 1: 새로운 API 엔드포인트 문서화
```markdown
# Task: POST /api/chat/send 엔드포인트 문서 추가
# 결과 위치: docs/api/chat.md

## POST /api/chat/send

대화 메시지를 전송하고 AI 응답을 받습니다.

### Request
\```json
{
  "message": "안녕하세요",
  "context_ids": ["mem_123", "mem_456"],
  "settings": {
    "temperature": 0.7,
    "max_tokens": 1000
  }
}
\```

### Response (200 OK)
\```json
{
  "response": "안녕하세요! 무엇을 도와드릴까요?",
  "memory_ids": ["mem_789"],
  "usage": {
    "prompt_tokens": 50,
    "completion_tokens": 20
  }
}
\```

### Errors
- 400: Invalid message format
- 500: AI service error
```

#### 시나리오 2: 아키텍처 다이어그램 추가
```markdown
# Task: 메모리 시스템 아키텍처 문서화
# 결과: docs/architecture/memory-system.md

\```mermaid
graph TD
    A[User Input] --> B[Memory Encoder]
    B --> C[Vector Store]
    C --> D[Decay Calculator]
    D --> E[Retrieval System]
    E --> F[AI Context]
\```

## 구성 요소
1. **Memory Encoder**: 입력을 벡터로 변환
2. **Vector Store**: SQLite + FAISS 하이브리드
3. **Decay Calculator**: 시간 기반 중요도 감소
4. **Retrieval System**: 유사도 기반 검색
```

#### 시나리오 3: README 업데이트
```bash
# Task: backend/native/README.md에 벤치마크 결과 추가
# 접근:
1. 기존 "Performance" 섹션 확인
2. 벤치마크 스크립트 실행: python tests/bench_native.py
3. 결과 테이블 형식으로 정리
4. 환경 정보 추가 (CPU, OS, 컴파일러)
```

### 트러블슈팅 가이드 (Troubleshooting Guide)

#### 문서 작성 시 주의사항

**1. 코드 블록 언어 지정**
```markdown
# ❌ 잘못된 예
\```
def hello():
    pass
\```

# ✅ 올바른 예
\```python
def hello():
    pass
\```
```

**2. Mermaid 다이어그램 렌더링 확인**
```bash
# GitHub에서 미리보기 확인
# 또는 VS Code + Mermaid 플러그인 사용
```

**3. 상대 경로 링크 검증**
```markdown
# ❌ 깨진 링크
[API 문서](api.md)

# ✅ 올바른 경로
[API 문서](./docs/api.md)
```

#### 문서 구조 가이드라인

**README.md 섹션 순서**
1. 프로젝트 제목 및 설명
2. Features
3. Quick Start / Installation
4. Usage Examples
5. Configuration
6. Development
7. Testing
8. Troubleshooting
9. License

**API 문서 템플릿**
- 엔드포인트 설명
- HTTP 메서드 및 경로
- Request 파라미터 및 예시
- Response 형식 및 예시
- 에러 코드 및 메시지
- 사용 예시 (curl, Python, JavaScript)

## planner
Axel 계획서/ADR 작성 전문가

### Instructions
- ADR(Architecture Decision Record) 형식으로 작성
- 문제 정의 → 선택지 분석 → 결정 → 근거 구조
- 마크다운 체크박스로 작업 항목 관리
- 의존성 분석 포함 (wave 기반 병렬 실행 계획)
- 예상 영향도 및 리스크 명시

### 사용 예시 (Usage Examples)

#### 시나리오 1: 새로운 기능 설계
```markdown
# Task: 메모리 자동 태깅 기능 추가 계획
# 결과: docs/adr/001-auto-tagging.md

# ADR-001: 메모리 자동 태깅 시스템

## Status
Proposed (2024-01-15)

## Context
사용자가 수동으로 태그를 입력하는 것은 번거롭고 일관성이 떨어짐.
AI를 활용한 자동 태그 추출로 사용성 향상 필요.

## Options
1. Rule-based: 키워드 매칭
2. ML-based: 사전 학습된 분류 모델
3. LLM-based: GPT API 활용

## Decision
LLM-based 방식 선택

## Rationale
- 높은 정확도 (90%+)
- 유연한 태그 생성
- 초기 구현 간단 (API 호출)

## Implementation Plan
- [ ] OpenAI API 통합
- [ ] 프롬프트 설계 및 테스트
- [ ] 태그 검증 로직 추가
- [ ] UI에 태그 표시

## Risks
- API 비용 증가 (예상: $10/1000 memories)
- 응답 지연 (예상: 1-2초)

## Mitigation
- 배치 처리로 비용 절감
- 백그라운드 작업으로 UX 영향 최소화
```

#### 시나리오 2: 기술 스택 변경
```markdown
# Task: DB 마이그레이션 계획 (SQLite → PostgreSQL)
# 결과: docs/adr/002-postgres-migration.md

## Wave-based Implementation

### Wave 1 (병렬 가능)
- [ ] PostgreSQL 설치 및 설정
- [ ] 스키마 설계 (SQLAlchemy models)
- [ ] 연결 풀 설정

### Wave 2 (Wave 1 완료 후)
- [ ] 데이터 마이그레이션 스크립트
- [ ] 테스트 환경 마이그레이션
- [ ] 성능 벤치마크

### Wave 3 (Wave 2 검증 후)
- [ ] 프로덕션 마이그레이션
- [ ] 모니터링 설정
- [ ] 롤백 플랜 준비

## Dependencies
- Wave 2는 Wave 1 완료 필요
- Wave 3는 Wave 2 검증 필요
```

#### 시나리오 3: 버그 수정 계획
```markdown
# Task: 메모리 검색 정확도 개선
# 접근:

## Problem Analysis
- 현재 정확도: 65%
- 원인: 벡터 유사도만 사용
- 목표: 80%+

## Solution Options
1. 하이브리드 검색 (벡터 + 키워드)
2. 리랭킹 모델 추가
3. 메타데이터 필터링 강화

## Selected: Hybrid Search

## Implementation Checklist
- [ ] BM25 인덱스 추가
- [ ] 벡터 + BM25 점수 결합 (가중치 0.7:0.3)
- [ ] 성능 테스트 (1000 쿼리)
- [ ] A/B 테스트 준비
```

### 트러블슈팅 가이드 (Troubleshooting Guide)

#### 효과적인 ADR 작성

**1. 너무 상세하거나 너무 간략**
```markdown
# ❌ 너무 간략
Decision: Use Redis
Reason: Fast

# ✅ 적절한 수준
Decision: Use Redis for session storage

Rationale:
- Session 데이터는 휘발성 (재시작 시 손실 가능)
- 초당 1000+ 읽기/쓰기 필요
- Redis 평균 응답 시간: <1ms
- 대안 (Memcached): 데이터 구조 제한
- 대안 (PostgreSQL): 10-50ms 지연
```

**2. 의존성 분석 누락**
```markdown
# ❌ 순서 없이 나열
- [ ] API 개발
- [ ] DB 스키마
- [ ] 프론트엔드

# ✅ Wave로 구조화
Wave 1:
- [ ] DB 스키마 (독립적)
Wave 2 (Wave 1 필요):
- [ ] API 개발
Wave 3 (Wave 2 필요):
- [ ] 프론트엔드 연동
```

**3. 리스크 평가 부재**
```markdown
# ✅ 리스크 포함
## Risks
- Performance: 예상 10x 느려짐 → 벤치마크 필수
- Breaking change: 기존 API 호환성 → 버전 관리
- Cost: 월 $100 → $500 증가 → 예산 승인 필요
```

## refactorer
코드 구조 개선 전문가

### Instructions
- 변경 전 기존 테스트 통과 확인: `~/projects-env/bin/pytest`
- ruff check 통과: `~/projects-env/bin/ruff check`
- 최소 변경 원칙 — 동작 변경 없이 구조만 개선
- 400줄 초과 파일 분리 우선
- 중복 코드 제거, 미사용 임포트 정리
- Protocol/ABC로 인터페이스 추출

### 사용 예시 (Usage Examples)

#### 시나리오 1: 대형 파일 분리
```bash
# 문제: backend/services/memory_service.py (650줄)
# 접근:

1. 책임 분석
   - MemoryStorage (DB 접근)
   - MemoryRetrieval (검색)
   - MemoryDecay (감쇠 계산)
   - MemoryEncoder (벡터 변환)

2. 파일 분리
   backend/services/memory/
   ├── __init__.py
   ├── storage.py      # MemoryStorage
   ├── retrieval.py    # MemoryRetrieval
   ├── decay.py        # MemoryDecay
   └── encoder.py      # MemoryEncoder

3. 검증
   pytest tests/test_memory_service.py
   ruff check backend/services/memory/
```

#### 시나리오 2: 중복 코드 제거
```python
# Before (중복)
def get_user_memories(user_id: str):
    conn = sqlite3.connect("axnmihn.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM memories WHERE user_id = ?", (user_id,))
    results = cursor.fetchall()
    conn.close()
    return results

def get_memory_by_id(memory_id: str):
    conn = sqlite3.connect("axnmihn.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM memories WHERE id = ?", (memory_id,))
    result = cursor.fetchone()
    conn.close()
    return result

# After (DRY)
from contextlib import contextmanager

@contextmanager
def get_db_connection():
    conn = sqlite3.connect("axnmihn.db")
    try:
        yield conn
    finally:
        conn.close()

def get_user_memories(user_id: str):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM memories WHERE user_id = ?", (user_id,))
        return cursor.fetchall()

def get_memory_by_id(memory_id: str):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM memories WHERE id = ?", (memory_id,))
        return cursor.fetchone()
```

#### 시나리오 3: 인터페이스 추출
```python
# Before (강결합)
class MemoryService:
    def __init__(self):
        self.encoder = OpenAIEncoder(api_key="...")
    
    def encode(self, text: str):
        return self.encoder.encode(text)

# After (느슨한 결합)
from typing import Protocol

class Encoder(Protocol):
    def encode(self, text: str) -> list[float]:
        ...

class MemoryService:
    def __init__(self, encoder: Encoder):
        self.encoder = encoder
    
    def encode(self, text: str):
        return self.encoder.encode(text)

# 테스트가 쉬워짐
class MockEncoder:
    def encode(self, text: str) -> list[float]:
        return [0.1] * 384

service = MemoryService(MockEncoder())
```

### 트러블슈팅 가이드 (Troubleshooting Guide)

#### 리팩토링 중 자주 발생하는 문제

**1. 순환 import**
```python
# ❌ 문제
# services/memory.py
from services.user import UserService

# services/user.py
from services.memory import MemoryService

# ✅ 해결책 1: 인터페이스 분리
# services/interfaces.py
class IUserService(Protocol): ...
class IMemoryService(Protocol): ...

# ✅ 해결책 2: 지연 import
def get_user_service():
    from services.user import UserService
    return UserService()
```

**2. 테스트 실패 (리팩토링 후)**
```bash
# 원인: import 경로 변경
# Before: from backend.services.memory_service import MemoryService
# After:  from backend.services.memory.storage import MemoryStorage

# 해결:
grep -r "from.*memory_service" tests/
# 모든 import 경로 업데이트
```

**3. Type hint 에러**
```python
# ❌ 순환 참조
class User:
    memories: list[Memory]

class Memory:
    user: User

# ✅ TYPE_CHECKING 활용
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .memory import Memory

class User:
    memories: list["Memory"]
```

**4. 성능 저하 (리팩토링 후)**
```bash
# 벤치마크로 확인
pytest tests/bench_memory.py --benchmark-only

# Before: 100ms
# After:  500ms → 문제 발견!

# 원인 확인
python -m cProfile -s cumtime backend/services/memory/storage.py
```

#### 리팩토링 체크리스트

**전 (Pre-refactoring)**
- [ ] 모든 테스트 통과 확인
- [ ] 현재 커버리지 측정: `pytest --cov`
- [ ] 벤치마크 기록 (성능 비교용)
- [ ] Git 브랜치 생성: `git checkout -b refactor/memory-service`

**중 (During refactoring)**
- [ ] 한 번에 하나의 변경만 수행
- [ ] 각 단계마다 테스트 실행
- [ ] 의미 있는 커밋 메시지
- [ ] Type hint 유지 및 추가

**후 (Post-refactoring)**
- [ ] 모든 테스트 통과 확인
- [ ] 커버리지 유지/향상 확인
- [ ] 벤치마크 비교 (±10% 이내)
- [ ] ruff check/format 통과
- [ ] 코드 리뷰 요청

#### 도구 활용

**자동 리팩토링 도구**
```bash
# 미사용 import 제거
ruff check --fix backend/

# 코드 포맷팅
ruff format backend/

# 타입 체크
mypy backend/ --strict
```

**복잡도 측정**
```bash
# 라돈 설치
pip install radon

# 순환 복잡도 측정 (10 이하 권장)
radon cc backend/ -a -nb

# 유지보수성 지수
radon mi backend/ -s
```
