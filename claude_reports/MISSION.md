# MISSION BRIEFING: axnmihn 자동 코드 리뷰

> 이 파일은 모든 코드 리뷰 세션이 첫 번째로 읽는 미션 브리핑입니다.
> 수정하지 마십시오.

---

## 프로젝트 개요

**axnmihn**은 Python 3.12 / FastAPI / Google Gemini 기반의 자율 AI 에이전트 시스템입니다.

- **규모**: ~95 Python 파일, ~23,595줄
- **위치**: `/home/northprot/projects/axnmihn`
- **목적**: 메모리 지속성, IoT 제어, 다중 도구 실행 기능을 갖춘 AI 에이전트

## 아키텍처

### 핵심 스택
- **프레임워크**: FastAPI + Uvicorn (비동기 ASGI)
- **LLM**: Google Gemini (`gemini-3-flash-preview`, 임베딩: `gemini-embedding-001`)
- **메모리**: 3계층 (Working JSON / Session SQLite / Long-term ChromaDB)
- **프로토콜**: MCP (Model Context Protocol)

### MCP 서버 (4개)
| 서버 | 파일 | 기능 |
|------|------|------|
| Main | `backend/protocols/mcp/server.py` | 시스템 도구 (파일, HASS, 로그) |
| Research | `backend/protocols/mcp/research_server.py` | 웹 검색 및 페이지 분석 (Playwright) |
| Memory | `backend/protocols/mcp/memory_server.py` | 메모리 저장/검색 인터페이스 |
| Opus Bridge | `backend/protocols/mcp/opus_bridge.py` | Claude Opus 코딩 작업 위임 |

### 3계층 메모리 시스템
| 계층 | 파일 | 저장소 | 토큰 예산 |
|------|------|--------|-----------|
| Working Memory | `backend/memory/current.py` | JSON | 150,000 |
| Session Archive | `backend/memory/recent.py` | SQLite | 90,000 |
| Long-term Memory | `backend/memory/permanent.py` | ChromaDB | 120,000 |

### 주요 모듈
| 모듈 | 위치 | 설명 |
|------|------|------|
| ChatHandler | `backend/core/chat_handler.py` (~36KB) | 메인 대화 파이프라인 |
| MCP Server | `backend/core/mcp_server.py` (~35KB) | 도구 레지스트리 및 실행 엔진 |
| Context Optimizer | `backend/core/context_optimizer.py` | 3-Tier 컨텍스트 최적화 |
| Memory Manager | `backend/memory/unified.py` | 3계층 메모리 통합 |
| GraphRAG | `backend/memory/graph_rag.py` | 지식 그래프 검색 |
| LLM Client | `backend/llm/clients.py` | Gemini API (Circuit Breaker 포함) |
| Config | `backend/config.py` | 환경 설정 |

### 디렉토리 구조
```
axnmihn/
├── backend/
│   ├── app.py                    # FastAPI 엔트리 포인트
│   ├── config.py                 # 환경 설정
│   ├── api/                      # API 라우터 (11 파일)
│   ├── core/
│   │   ├── chat_handler.py       # 메인 대화 파이프라인
│   │   ├── mcp_server.py         # MCP 서버 코어
│   │   ├── context_optimizer.py  # 컨텍스트 최적화
│   │   ├── mcp_tools/            # 도구 구현 (9 파일)
│   │   ├── tools/                # Opus 위임, HASS (6 파일)
│   │   ├── utils/                # 유틸리티 (17 파일)
│   │   ├── logging/              # 로깅 시스템 (4 파일)
│   │   └── identity/             # 페르소나 (2 파일)
│   ├── memory/                   # 메모리 시스템 (8 파일)
│   ├── llm/                      # LLM 클라이언트 (3 파일)
│   ├── media/                    # 음성/비디오 (3 파일)
│   ├── protocols/mcp/            # MCP 프로토콜 (7 파일)
│   └── wake/                     # 웨이크워드 감지 (8 파일)
├── data/                         # 메모리, DB, 페르소나 데이터
├── storage/                      # 연구 및 크론 결과
├── logs/                         # 애플리케이션 로그
└── scripts/                      # 유틸리티 스크립트
```

---

## 리뷰 관점 (7가지)

모든 분석은 다음 7가지 관점에서 수행합니다.
Google의 대규모 코드 리뷰 연구에 따르면 리뷰에서 가장 가치 있는 피드백은 설계와 가독성 영역(~50%)이며, 버그 발견(~15%)은 부차적입니다. 이를 반영한 우선순위입니다.

### 1. 설계 품질 (Design Quality) ★ 최우선
> "Complexity is the root cause of the vast majority of problems with software today." — John Ousterhout

- **모듈 의존성**: 순환 의존, 과도한 결합(coupling), 낮은 응집도(cohesion)
- **추상화 수준**: 얕은 모듈(인터페이스만 복잡하고 하는 일은 적음) vs 깊은 모듈(간단한 인터페이스 + 풍부한 기능)
- **단일 책임 원칙(SRP)**: 하나의 클래스/함수가 여러 역할을 담당하는 경우
- **샷건 수술(Shotgun Surgery)**: 하나의 변경이 여러 파일에 영향을 주는 구조
- **God Object/Function**: chat_handler.py(36KB), mcp_server.py(35KB) 등 거대 파일의 분리 가능성

### 2. 복잡도 & 가독성 (Complexity & Readability)
> Google 연구: 리뷰어 피드백의 ~25%가 가독성/이해 용이성

- **과도하게 긴 함수** (100줄+) — Martin Fowler의 "Long Method" 냄새
- **깊은 중첩** (4단계+) — early return으로 해소 가능한 경우
- **복잡한 조건문** — 의미 있는 이름의 변수/함수로 추출 가능한 경우
- **불명확한 네이밍** — 의도를 표현하지 못하는 변수명/함수명
- **과도한 인라인 로직** — 한 줄에 너무 많은 연산

### 3. 보안 (Security)
- **입력 검증**: 외부 입력(API 요청, 파일 업로드)의 검증 누락
- **인증/인가 경로**: 우회 가능한 인증 체크, 미보호 엔드포인트
- **민감 데이터 노출**: 로그에 API 키/토큰 기록, 에러 응답에 내부 정보
- **인젝션**: 명령어 인젝션, 경로 탐색(path traversal)
- **의존성 보안**: 알려진 취약점이 있는 라이브러리

### 4. 버그 & 안정성 (Bugs & Reliability)
- **로직 오류**: off-by-one, null/None 참조, 잘못된 조건
- **Race condition**: 비동기 코드의 동시성 문제
- **리소스 누수**: 미닫힌 연결, 파일 핸들, 세션
- **예외 처리**: `except Exception: pass` 같은 과도한 예외 삼킴, 누락된 에러 경로
- **엣지 케이스**: 빈 입력, 타임아웃, 네트워크 실패 시 동작

### 5. 변경 용이성 (Changeability)
> "The code that is hard to change is the most dangerous code." — Michael Feathers

- **하드코딩된 값**: 설정으로 빼야 할 매직 넘버/문자열
- **테스트 부재**: 변경 시 영향을 검증할 수 없는 코드
- **높은 결합도**: 한 모듈 수정 시 연쇄적으로 다른 모듈도 수정 필요
- **숨겨진 의존성**: 암묵적 전역 상태, 모듈 간 비명시적 계약
- **리팩토링 기회**: async/await 최적화, 디자인 패턴 적용, 타입 안전성 개선

### 6. 불필요한 코드 (Dead Code)
- 미사용 import
- 호출되지 않는 함수/메서드
- 주석 처리된 코드 블록
- 도달 불가능한 코드 경로
- 더 이상 사용되지 않는 설정값

### 7. 중복 (DRY 위반)
- Copy-paste 코드 패턴
- 유사한 기능의 다른 구현
- 통합 가능한 유틸리티 함수
- 중복된 에러 처리 로직

---

## 리포트 포맷 규격

모든 리포트는 다음 포맷을 따릅니다:

```markdown
# [번호] [주제]

> 분석 날짜: YYYY-MM-DD
> 분석 범위: [파일/모듈 목록]

## 요약
[1~3문장 핵심 요약]

## 발견사항

### CRITICAL
- **[제목]**: [설명] (`파일경로:라인번호`)
  - 영향: [영향 범위]
  - 개선안: [구체적 코드 예시]

### HIGH
...

### MEDIUM
...

### LOW
...

## 개선 제안
[종합적인 리팩토링 방향]

## 수정 난이도
| 항목 | 난이도 | 이유 |
|------|--------|------|
```

### 심각도 정의
| 심각도 | 정의 |
|--------|------|
| **CRITICAL** | 즉시 수정 필요. 버그, 보안 취약점, 데이터 손실 위험 |
| **HIGH** | 빠른 수정 권장. 성능 저하, 유지보수성 심각 저해 |
| **MEDIUM** | 개선 권장. 코드 품질, 가독성, 중복 |
| **LOW** | 선택적 개선. 스타일, 컨벤션, 마이너 최적화 |

---

## 상태 파일 업데이트 규칙

### PROGRESS.md 업데이트
매 세션 종료 시 반드시 PROGRESS.md를 업데이트합니다:

1. **Phase** 업데이트: `INIT` → `REVIEWING` → `COMPLETE`
2. **완료 카운트** 업데이트
3. **다음 작업** 명시
4. **완료된 리뷰 테이블**에 행 추가:
   - `#`: 리포트 번호
   - `주제`: 리뷰 주제
   - `날짜`: 완료 날짜
   - `리포트`: 파일명 (링크)
   - `핵심 발견`: CRITICAL/HIGH 항목 요약

---

## 작업 규칙

1. **읽기 전용**: 프로젝트 코드를 절대 수정하지 않습니다
2. **쓰기 대상**: `~/projects/claude_reports/` 디렉토리만 쓰기 가능
3. **참조 형식**: 모든 발견사항에 `파일경로:라인번호` 형식 참조 필수
4. **한 세션 한 리뷰**: 각 세션은 하나의 우선순위 항목만 심층 분석
5. **상태 추적**: 매 세션 PROGRESS.md 업데이트 필수

