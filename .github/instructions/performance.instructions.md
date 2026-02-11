---
applyTo: "**/*.py"
---
# Performance Analysis Guidelines

Python 코드 성능 분석 시 참고.

## 체크 항목
1. **시간 복잡도**: O(n²) 이상 → 개선 가능성 검토
2. **N+1 쿼리**: 루프 안 개별 쿼리 → selectinload/joinedload 또는 IN 쿼리
3. **루프 내 불필요 연산**: 루프 밖으로 호이스팅
4. **문자열 연결**: `+=` 반복 → `"".join()` 사용
5. **불필요한 deepcopy**: 필요한 경우만 사용
6. **I/O 병목**: 동기 I/O → async 전환 검토

## 프로파일링
```bash
python -m cProfile -s cumtime script.py
time python script.py
```
