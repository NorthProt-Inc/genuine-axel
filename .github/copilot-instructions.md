# axnmihn 프로젝트 Copilot 지시사항

## 프로젝트 개요
axnmihn — Python/FastAPI 기반 AI 백엔드 서비스. PostgreSQL + Redis 인프라 (systemd 네이티브).

## 아키텍처
- `backend/` — FastAPI 애플리케이션 (포트 8000)
- `backend/core/` — 핵심 로직 (MCP 서버 포트 8555)
- `backend/protocols/mcp/` — Research MCP 서버
- `data/` — 데이터 파일
- `storage/` — 영구 저장소
- `tests/` — pytest 테스트
- `scripts/` — 유틸리티 스크립트
- `docs/` — 문서

## 개발 환경
- Python 3.12, venv: `~/projects-env/bin/python3`
- PYTHONPATH: `/home/northprot/projects/axnmihn`
- 린트: `~/projects-env/bin/ruff check`
- 포맷: `python -m black`
- 테스트: `pytest` 또는 `~/projects-env/bin/pytest`

## systemd 서비스
- `axnmihn-backend.service` — 메인 백엔드 (:8000)
- `axnmihn-mcp.service` — MCP SSE 서버 (:8555)
- `axnmihn-research.service` — Research MCP 서버
- 상태 확인: `systemctl --user status axnmihn-backend`
- 재시작: `systemctl --user restart axnmihn-backend`
- 헬스체크: `curl -s http://localhost:8000/health`

## 코딩 규칙
- 파이썬 타입 힌트 필수 (public 함수)
- Protocol 기반 인터페이스, dataclass/pydantic 데이터
- async def 우선 (I/O-bound 작업)
- 소스 파일 최대 400줄
- backend/core/ 테스트 커버리지 85%+

## 로그 파일
- 백엔드 로그: `logs/backend.log`
- 로그 분석 시 최근 100줄부터 시작

## 커밋 규칙
- Conventional Commits 형식
- 변경 전 `ruff check --fix` 실행
- Python 파일 수정 시 `black` 자동 포맷
