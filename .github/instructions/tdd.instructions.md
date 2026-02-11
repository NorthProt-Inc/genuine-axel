---
applyTo: "**/tests/**,**/backend/**"
---
# TDD Red-Green-Refactor (Python/pytest)

## Workflow

### RED — 실패하는 테스트 작성
1. 테스트 파일: `tests/<module-path>/test_<module>.py`
2. AAA 패턴: Happy path, Edge cases, Error cases
3. 실패 확인: `~/projects-env/bin/pytest tests/<path> -v`

### GREEN — 최소 구현
1. 모든 테스트 통과하는 최소 코드 작성
2. 통과 확인: `~/projects-env/bin/pytest tests/<path> -v`

### REFACTOR — 개선
1. 중복 제거, 네이밍 개선, 구조화
2. 테스트 재확인
3. `~/projects-env/bin/ruff check backend/<path>`

## 커버리지 목표
- backend/core/: 85%+
- backend/memory/: 80%+
- backend/api/: 75%+

## 규칙
- 한 번에 하나의 테스트만 작성 → 실패 확인 → 구현
- 타입 힌트 필수 (public 함수)
- async def 우선 (I/O-bound)
- 소스 파일 최대 400줄
