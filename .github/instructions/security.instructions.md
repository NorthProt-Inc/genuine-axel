---
applyTo: "**/*.py"
---
# Security Scan Guidelines

Python 코드 보안 점검 시 참고.

## 체크리스트
1. **하드코딩된 시크릿**: password, api_key, secret, token 패턴
2. **SQL Injection**: f-string 쿼리 조합 → 파라미터 바인딩 사용
3. **Command Injection**: `os.system()`, `subprocess(shell=True)` 금지
4. **위험 함수**: `eval()`, `exec()`, `pickle.loads()` (신뢰되지 않는 입력)
5. **YAML**: `yaml.load()` → `yaml.safe_load()` 필수
6. **CORS**: `origins = ["*"]` 확인
7. **Debug 모드**: `DEBUG = True` 프로덕션 비활성화

## 검사 명령
```bash
# 하드코딩된 시크릿
grep -rn --include="*.py" -E "(password|api_key|secret|token)\s*=\s*['\"][^'\"]+['\"]" .
# 위험 함수
grep -rn --include="*.py" -E "\b(eval|exec|os\.system)\b" .
# shell=True
grep -rn --include="*.py" "shell\s*=\s*True" .
```
