---
applyTo: "**/logs/**,**/backend/**"
---
# Error Log Analysis

에러, 트레이스백, 반복 실패 조사 시 참고.

## 로그 수집
```bash
# 최근 에러 로그
grep -E "ERROR|CRITICAL|Traceback" logs/backend.log | tail -100

# 전체 최근 로그
tail -n 500 logs/backend.log
```

## 에러 분류
| Category | Patterns |
|----------|----------|
| Connection | ConnectionError, TimeoutError |
| Auth | AuthenticationError, 401, 403 |
| Data | ValidationError, JSONDecodeError |
| Server | 500, InternalServerError |

## 분석 절차
1. 트레이스백에서 소스 파일:라인, 콜 스택 추출
2. 에러 발생 소스 코드 읽기
3. 근본 원인 파악 후 최소 수정 제안
