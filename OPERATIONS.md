# Axnmihn Operations Guide / 운영 가이드

<details open>
<summary><strong>한국어 버전</strong></summary>

> **환경:** Pop!_OS (Ubuntu 24.04 LTS) + Systemd  
> **최종 업데이트:** 2026-02-11  
> **프로젝트:** axnmihn - AI Backend Service

---

## 목차

1. [서비스 구조](#서비스-구조)
2. [기본 명령어](#기본-명령어)
3. [서비스 관리](#서비스-관리)
4. [모니터링 & 디버깅](#모니터링--디버깅)
5. [일상 운영 시나리오](#일상-운영-시나리오)
6. [트러블슈팅](#트러블슈팅)
7. [자동화 작업](#자동화-작업)
8. [백업 & 복구](#백업--복구)
9. [응급 상황 대응](#응급-상황-대응)
10. [빠른 참조](#빠른-참조)

---

## 서비스 구조

### Systemd User Services

모든 서비스는 **user service**로 `systemctl --user`로 관리합니다 (sudo 불필요).

#### 핵심 서비스

| 서비스 | 포트 | 설명 | 리소스 제한 |
|--------|------|------|-------------|
| `axnmihn-backend.service` | 8000 | Main FastAPI Backend | 4G RAM, CPU 200% |
| `axnmihn-mcp.service` | 8555 | MCP Server (SSE) | 1G RAM, CPU 100% |
| `axnmihn-research.service` | 8766 | Research MCP Server | 2G RAM, CPU 150% |
| `axnmihn-tts.service` | 8002 | TTS Microservice (Qwen3-TTS) | 4G RAM, CPU 200% |
| `axnmihn-wakeword.service` | - | Wakeword Detector | 512M RAM, CPU 50% |

#### MCP 확장 서비스

| 서비스 | 포트 | 설명 |
|--------|------|------|
| `context7-mcp.service` | 3002 | Context7 MCP (Supergateway) |
| `markitdown-mcp.service` | 3001 | Markitdown MCP (Supergateway) |

#### 보조 서비스 (Oneshot/Timer)

| 서비스 | 주기 | 설명 |
|--------|------|------|
| `auto-cleanup.timer` | 매주 | pip 캐시, __pycache__, 오래된 로그 정리 |
| `axnmihn-mcp-reclaim.timer` | 10분 | MCP cgroup 페이지 캐시 회수 |
| `context7-mcp-restart.timer` | 6시간 | Context7 메모리 릭 정리 |
| `markitdown-mcp-restart.timer` | 4시간 | Markitdown 메모리 릭 정리 |
| `claude-review.timer` | 3시간 | 자동 코드 리뷰 |

### 포트 매핑

> ℹ️ Discord/Telegram 봇은 `axnmihn-backend` 프로세스 내에서 실행됩니다 (별도 포트 불필요).

| 포트 | 서비스 | 접근 |
|------|--------|------|
| 3000 | Open WebUI | Public |
| 3001 | Markitdown MCP | Localhost |
| 3002 | Context7 MCP | Localhost |
| 5432 | PostgreSQL (systemd) | Localhost |
| 6379 | Redis (systemd) | Localhost |
| 8000 | Axnmihn Backend | Public |
| 8002 | TTS | Localhost |
| 8123 | Home Assistant | LAN |
| 8555 | Main MCP | Localhost |
| 8766 | Research MCP | Localhost |

### 디렉토리 구조

```
/home/northprot/projects/axnmihn/
├── backend/               # FastAPI 애플리케이션
│   ├── app.py            # 진입점
│   ├── config.py         # 설정
│   ├── api/              # HTTP/WebSocket 라우터
│   ├── core/             # 핵심 로직
│   │   ├── errors.py     # 구조화된 에러 계층 (AxnmihnError)
│   │   ├── health/       # 컴포넌트 헬스체크
│   │   ├── intent/       # 인텐트 분류기
│   │   ├── telemetry/    # Prometheus 메트릭스
│   │   └── ...
│   ├── llm/              # LLM 프로바이더
│   ├── memory/           # 6계층 메모리 시스템
│   ├── native/           # C++17 확장 모듈
│   ├── channels/         # 채널 어댑터 (Discord, Telegram)
│   └── protocols/mcp/    # MCP 프로토콜 핸들러
├── tests/                # pytest 테스트
├── scripts/              # 자동화 스크립트
├── data/                 # 런타임 데이터
│   ├── working_memory.json       # M1: 워킹 메모리
│   ├── knowledge_graph.json      # M5.2: 지식 그래프
│   ├── dynamic_persona.json      # AI 페르소나
│   ├── sqlite/
│   │   └── sqlite_memory.db     # M3: 세션 아카이브
│   └── chroma_db/               # M4: 벡터 임베딩
├── logs/                 # 애플리케이션 로그
│   └── backend.log       # 메인 로그 파일
├── storage/              # 리서치 결과, 크론 리포트
│   ├── research/
│   │   ├── inbox/        # 딥 리서치 결과
│   │   └── artifacts/    # 웹 스크랩
│   └── cron/
│       └── reports/      # 야간 작업 보고서
├── .env                  # 환경 변수 (API 키)
├── docker-compose.yml    # Docker 배포용 (선택)
└── Dockerfile            # 멀티스테이지 빌드
```

### Systemd 서비스 파일 위치

```bash
~/.config/systemd/user/
├── axnmihn-backend.service
├── axnmihn-mcp.service
├── axnmihn-mcp-reclaim.service / .timer
├── axnmihn-postgres.service
├── axnmihn-redis.service
├── axnmihn-research.service
├── axnmihn-tts.service
├── axnmihn-wakeword.service
├── context7-mcp.service
├── context7-mcp-restart.service / .timer
├── markitdown-mcp.service
├── markitdown-mcp-restart.service / .timer
├── claude-review.service / .timer
└── auto-cleanup.service / .timer
```

---

## 기본 명령어

### 서비스 상태 확인

```bash
# 전체 서비스 상태
systemctl --user status axnmihn-backend axnmihn-mcp --no-pager

# 단일 서비스 상태
systemctl --user status axnmihn-backend

# 실행 중인 서비스만 확인
systemctl --user list-units "axnmihn-*" --state=running
```

### 서비스 제어

```bash
# 시작
systemctl --user start axnmihn-backend

# 중지
systemctl --user stop axnmihn-backend

# 재시작
systemctl --user restart axnmihn-backend

# 부팅 시 자동 시작 활성화
systemctl --user enable axnmihn-backend

# 부팅 시 자동 시작 비활성화
systemctl --user disable axnmihn-backend
```

### 로그 확인

```bash
# 최근 로그 (journald)
journalctl --user -u axnmihn-backend --no-pager -n 50

# 실시간 로그 (tail -f)
journalctl --user -u axnmihn-backend -f

# 애플리케이션 로그
tail -n 100 logs/backend.log

# 에러 로그만 필터링
grep -E "ERROR|CRITICAL" logs/backend.log | tail -50

# 특정 시간대 로그
journalctl --user -u axnmihn-backend --since "2026-02-11 08:00" --until "2026-02-11 09:00"
```

### 헬스체크

```bash
# 빠른 헬스체크
curl -s http://localhost:8000/health/quick

# 전체 헬스체크 (메모리, LLM, 모듈 포함)
curl -s http://localhost:8000/health | python3 -m json.tool

# MCP 서버 헬스체크
curl -s http://localhost:8555/health
```

### 포트 확인

```bash
# 핵심 포트 확인
ss -tlnp | grep -E ":(8000|8555|8766)"

# 특정 포트 사용 프로세스 확인
lsof -i :8000

# 전체 axnmihn 프로세스
pgrep -af "python.*(axnmihn|uvicorn|mcp)" | head -20
```

---

## 서비스 관리

### 전체 재시작

```bash
# 백엔드 서비스 재시작
systemctl --user restart axnmihn-backend

# 전체 재시작 (의존 서비스 포함)
systemctl --user restart axnmihn-backend axnmihn-mcp axnmihn-research

# 재시작 후 상태 확인
systemctl --user status axnmihn-backend --no-pager && \
curl -s http://localhost:8000/health/quick
```

### 설정 변경 후 적용

```bash
# .env 파일 수정 후
systemctl --user restart axnmihn-backend

# systemd 서비스 파일 수정 후
systemctl --user daemon-reload
systemctl --user restart axnmihn-backend
```

### 타이머 관리

```bash
# 활성화된 타이머 목록
systemctl --user list-timers

# 특정 타이머 상태
systemctl --user status axnmihn-mcp-reclaim.timer

# 타이머 시작/중지
systemctl --user start axnmihn-mcp-reclaim.timer
systemctl --user stop axnmihn-mcp-reclaim.timer

# 타이머 즉시 실행 (테스트용)
systemctl --user start axnmihn-mcp-reclaim.service
```

---

## 모니터링 & 디버깅

### 리소스 사용량

```bash
# CPU/메모리 사용량 (실시간)
top -u northprot

# 특정 프로세스 리소스
ps aux | grep "uvicorn.*axnmihn"

# systemd cgroup 리소스
systemctl --user status axnmihn-backend | grep -E "Memory|CPU"

# 디스크 사용량
du -sh data/ logs/ storage/
```

### 에러 분석

```bash
# 최근 에러 로그
grep -E "ERROR|CRITICAL|Traceback" logs/backend.log | tail -100

# 에러 빈도 분석
grep "ERROR" logs/backend.log | cut -d' ' -f4 | sort | uniq -c | sort -rn

# 특정 에러 패턴 검색
grep -A 10 "ConnectionError" logs/backend.log | tail -50
```

### 메모리 시스템 진단

```bash
# 메모리 통계
curl -s http://localhost:8000/memory/stats | python3 -m json.tool

# SQLite 데이터베이스 크기
ls -lh data/sqlite/sqlite_memory.db

# ChromaDB 디렉토리 크기
du -sh data/chroma_db/

# 워킹 메모리 확인
cat data/working_memory.json | python3 -m json.tool | head -50
```

### 네트워크 진단

```bash
# API 응답 시간 측정
time curl -s http://localhost:8000/health/quick

# 연결 수 확인
ss -tn | grep ":8000" | wc -l

# 요청 로그 실시간 모니터링
tail -f logs/backend.log | grep "POST\|GET"

# Prometheus 메트릭스 (요청 횟수, 응답 시간, 에러 카운트)
curl -s http://localhost:8000/metrics
```

---

## 일상 운영 시나리오

### 시나리오 1: 코드 수정 후 반영

```bash
# 1. 코드 수정 (backend/ 디렉토리)
vim backend/core/chat_handler.py

# 2. 린트 & 포맷 (선택)
~/projects-env/bin/ruff check --fix backend/
python -m black backend/

# 3. 백엔드 재시작
systemctl --user restart axnmihn-backend

# 4. 로그 모니터링
journalctl --user -u axnmihn-backend -f -n 50
# (Ctrl+C로 중단)

# 5. 헬스체크
curl -s http://localhost:8000/health/quick

# 6. 에러 확인
grep "ERROR" logs/backend.log | tail -20
```

### 시나리오 2: 메모리 통합 실행

```bash
# 메모리 통합 트리거 (decay + persona evolution)
curl -X POST http://localhost:8000/memory/consolidate \
  -H "Authorization: Bearer ${AXNMIHN_API_KEY}"

# 통합 상태 확인
tail -f logs/backend.log | grep "consolidat"
```

> **참고:** 앱 내에서 6시간마다 자동 consolidation이 실행됩니다. 수동 실행은 즉시 통합이 필요한 경우에만 사용하세요.

### 시나리오 3: 디스크 공간 부족

```bash
# 1. 디스크 사용량 확인
df -h ~

# 2. 큰 디렉토리 찾기
du -sh ~/projects/axnmihn/* | sort -rh | head -10

# 3. 오래된 로그 정리
find logs/ -name "*.log.*" -mtime +30 -delete

# 4. SQLite VACUUM
sqlite3 data/sqlite/sqlite_memory.db "VACUUM;"

# 5. Docker 정리 (선택)
docker system prune -a --volumes
```

### 시나리오 4: 성능 저하 진단

```bash
# 1. 프로세스 리소스 확인
systemctl --user status axnmihn-backend --no-pager

# 2. CPU 사용률 확인
top -b -n 1 -u northprot | grep python

# 3. 메모리 사용량
ps aux | grep uvicorn | awk '{print $6}'

# 4. 응답 시간 측정
for i in {1..10}; do
  time curl -s http://localhost:8000/health/quick > /dev/null
done

# 5. 로그에서 느린 요청 찾기
grep "took.*ms" logs/backend.log | awk '{print $NF}' | sort -rn | head -20
```

### 시나리오 5: 새 API 키 업데이트

```bash
# 1. .env 파일 백업
cp .env .env.backup

# 2. API 키 수정
vim .env
# GEMINI_API_KEY=새로운키
# ANTHROPIC_API_KEY=새로운키

# 3. 백엔드 재시작
systemctl --user restart axnmihn-backend

# 4. LLM 프로바이더 확인
curl -s http://localhost:8000/llm/providers | python3 -m json.tool

# 5. 테스트 요청
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer ${AXNMIHN_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"테스트"}],"stream":false}'
```

---

## 트러블슈팅

### 문제: 서비스가 시작되지 않음

```bash
# 1. 상세 로그 확인
journalctl --user -u axnmihn-backend -n 100 --no-pager

# 2. 설정 파일 검증
python3 -c "from backend.config import config; print(config.model_dump())"

# 3. 포트 충돌 확인
ss -tlnp | grep :8000

# 4. 환경 변수 확인
grep -v "^#" .env | grep "API_KEY"

# 5. 수동 실행으로 에러 확인
cd ~/projects/axnmihn
~/projects-env/bin/python -m uvicorn backend.app:app --host 0.0.0.0 --port 8000
```

**해결 방법:**
- 포트 충돌: 기존 프로세스 종료 (`kill <PID>`)
- API 키 누락: `.env` 파일에 키 추가
- 의존성 문제: `pip install -r backend/requirements.txt`

---

### 문제: 메모리 부족 (OOM)

```bash
# 1. 메모리 사용량 확인
free -h
systemctl --user status axnmihn-backend | grep Memory

# 2. ChromaDB 크기 확인
du -sh data/chroma_db/

# 3. 메모리 정리 스크립트 실행
~/projects-env/bin/python scripts/memory_gc.py

# 4. SQLite VACUUM
sqlite3 data/sqlite/sqlite_memory.db "VACUUM; ANALYZE;"

# 5. 서비스 재시작
systemctl --user restart axnmihn-backend
```

**해결 방법:**
- ChromaDB가 너무 큼: 오래된 메모리 삭제 (`memory_gc.py`)
- SQLite 비대: VACUUM 실행
- 메모리 릭: 서비스 재시작 후 모니터링

---

### 문제: LLM 요청 실패

```bash
# 1. 프로바이더 상태 확인
curl -s http://localhost:8000/llm/providers | python3 -m json.tool

# 2. API 키 확인
grep "API_KEY" .env

# 3. 네트워크 연결 테스트
curl -s https://generativelanguage.googleapis.com/v1beta/models

# 4. 로그에서 에러 확인
grep -E "Gemini|Anthropic|LLM" logs/backend.log | tail -50

# 5. Circuit breaker 상태 확인
grep "circuit.*open" logs/backend.log
```

**해결 방법:**
- API 키 만료: 새 키 발급 후 `.env` 업데이트
- Rate limit: 잠시 대기 후 재시도
- Circuit breaker open: 일정 시간 후 자동 복구

---

### 문제: PostgreSQL 연결 실패 (선택)

```bash
# 1. PostgreSQL 서비스 상태 확인
systemctl --user status axnmihn-postgres

# 2. PostgreSQL 로그 확인
journalctl --user -u axnmihn-postgres --no-pager -n 50

# 3. 연결 테스트
psql postgresql://axnmihn:password@localhost:5432/axnmihn -c "SELECT 1;"

# 4. DATABASE_URL 확인
grep "DATABASE_URL" .env

# 5. 서비스 재시작
systemctl --user restart axnmihn-postgres
```

**해결 방법:**
- 서비스 중지됨: `systemctl --user start axnmihn-postgres`
- 비밀번호 불일치: `.env`와 PostgreSQL 설정 일치 확인
- 포트 충돌: 5432 포트 사용 프로세스 종료

---

### 문제: 디스크 I/O 병목

```bash
# 1. I/O 사용량 확인
iostat -x 1 5

# 2. 큰 파일 찾기
find ~/projects/axnmihn -type f -size +100M -exec ls -lh {} \;

# 3. SQLite WAL 크기 확인
ls -lh data/sqlite/sqlite_memory.db-wal

# 4. WAL 체크포인트 강제 실행
sqlite3 data/sqlite/sqlite_memory.db "PRAGMA wal_checkpoint(TRUNCATE);"

# 5. 로그 로테이션 확인
journalctl --disk-usage
```

**해결 방법:**
- SQLite WAL 비대: 체크포인트 실행
- 로그 파일 비대: 로그 로테이션 설정
- ChromaDB 비대: 오래된 데이터 정리

---

## 자동화 작업

### 메모리 가비지 컬렉션

```bash
# 수동 실행
~/projects-env/bin/python scripts/memory_gc.py

# Cron 등록 (매일 새벽 4시 실행 — 권장)
(crontab -l 2>/dev/null; echo "0 4 * * * cd ~/projects/axnmihn && ~/projects-env/bin/python scripts/memory_gc.py >> logs/memory_gc.log 2>&1") | crontab -

# 등록 확인
crontab -l | grep memory_gc
```

> **참고:** 앱 내에서도 6시간마다 자동 consolidation이 실행됩니다.
> cron은 추가적인 해시 중복 제거 및 시맨틱 중복 제거를 담당합니다.

**작업 내용:**
- 중복 메모리 제거 (유사도 0.90 이상)
- 중요도 낮은 메모리 삭제 (< 0.03)
- 오래된 세션 아카이브 정리 (30일 이상)

---

### 데이터베이스 유지보수

```bash
# SQLite VACUUM & ANALYZE
~/projects-env/bin/python scripts/db_maintenance.py

# 무결성 검사
sqlite3 data/sqlite/sqlite_memory.db "PRAGMA integrity_check;"

# Cron 설정 (주간 실행)
crontab -e
# 0 3 * * 0 cd ~/projects/axnmihn && ~/projects-env/bin/python scripts/db_maintenance.py >> logs/db_maintenance.log 2>&1
```

---

### 페르소나 재생성

```bash
# 7일 증분 업데이트
~/projects-env/bin/python scripts/regenerate_persona.py

# 전체 재생성
~/projects-env/bin/python scripts/regenerate_persona.py --full
```

---

### 야간 리서치 작업

```bash
# Night Ops 스크립트
~/projects-env/bin/python scripts/night_ops.py

# 결과 확인
ls -lh storage/cron/reports/
```

---

## 백업 & 복구

### 데이터 백업

```bash
#!/bin/bash
# backup.sh

BACKUP_DIR=~/backups/axnmihn/$(date +%Y%m%d_%H%M%S)
mkdir -p "$BACKUP_DIR"

# 데이터 백업
cp -r ~/projects/axnmihn/data "$BACKUP_DIR/"
cp -r ~/projects/axnmihn/storage "$BACKUP_DIR/"
cp ~/projects/axnmihn/.env "$BACKUP_DIR/"

# SQLite WAL 체크포인트 후 백업
sqlite3 ~/projects/axnmihn/data/sqlite/sqlite_memory.db "PRAGMA wal_checkpoint(TRUNCATE);"

# 압축
tar czf "$BACKUP_DIR.tar.gz" -C "$BACKUP_DIR/.." "$(basename "$BACKUP_DIR")"
rm -rf "$BACKUP_DIR"

echo "백업 완료: $BACKUP_DIR.tar.gz"
```

---

### 복구

```bash
# 백업 압축 해제
tar xzf ~/backups/axnmihn/20260211_080000.tar.gz -C /tmp/

# 서비스 중지
systemctl --user stop axnmihn-backend axnmihn-mcp

# 데이터 복원
rsync -av /tmp/20260211_080000/data/ ~/projects/axnmihn/data/
rsync -av /tmp/20260211_080000/storage/ ~/projects/axnmihn/storage/

# 서비스 재시작
systemctl --user start axnmihn-backend axnmihn-mcp

# 정리
rm -rf /tmp/20260211_080000
```

---

## 응급 상황 대응

### 긴급: 전체 서비스 다운

```bash
# 1. 모든 서비스 상태 확인
systemctl --user status axnmihn-* --no-pager

# 2. 전체 재시작
systemctl --user restart axnmihn-backend axnmihn-mcp axnmihn-research

# 3. 헬스체크
curl -s http://localhost:8000/health/quick

# 4. 로그 모니터링
journalctl --user -u axnmihn-backend -f -n 100
```

---

### 긴급: 메모리 누수

```bash
# 1. 메모리 사용량 확인
free -h
ps aux | grep uvicorn | awk '{print $6}'

# 2. 서비스 재시작
systemctl --user restart axnmihn-backend

# 3. 메모리 정리
~/projects-env/bin/python scripts/memory_gc.py

# 4. 모니터링
watch -n 5 'ps aux | grep uvicorn | awk "{print \$6}"'
```

---

### 긴급: API 응답 없음

```bash
# 1. 프로세스 확인
pgrep -af uvicorn

# 2. 포트 확인
ss -tlnp | grep :8000

# 3. 강제 재시작
systemctl --user restart axnmihn-backend

# 4. 수동 시작 (디버깅)
~/projects-env/bin/python -m uvicorn backend.app:app --host 0.0.0.0 --port 8000
```

---

## 빠른 참조

### 주요 명령어 요약

| 작업 | 명령어 |
|------|--------|
| 서비스 상태 | `systemctl --user status axnmihn-backend` |
| 서비스 재시작 | `systemctl --user restart axnmihn-backend` |
| 로그 확인 | `journalctl --user -u axnmihn-backend -n 50` |
| 헬스체크 | `curl -s http://localhost:8000/health/quick` |
| 에러 로그 | `grep ERROR logs/backend.log \| tail -50` |
| 메모리 통계 | `curl -s http://localhost:8000/memory/stats` |
| 포트 확인 | `ss -tlnp \| grep :8000` |
| 프로세스 확인 | `pgrep -af axnmihn` |

---

### 환경 변수 참조

| 변수 | 설명 | 위치 |
|------|------|------|
| `AXNMIHN_API_KEY` | API 인증 키 | `.env` |
| `GEMINI_API_KEY` | Gemini LLM | `.env` |
| `ANTHROPIC_API_KEY` | Claude LLM | `.env` |
| `DATABASE_URL` | PostgreSQL 연결 (선택) | `.env` |
| `PYTHONPATH` | `/home/northprot/projects/axnmihn` | systemd |

---

### 유용한 스크립트

| 스크립트 | 설명 |
|----------|------|
| `scripts/memory_gc.py` | 메모리 가비지 컬렉션 (중복제거, decay, 대형 항목 제거) |
| `scripts/db_maintenance.py` | SQLite VACUUM, ANALYZE, 무결성 검사 |
| `scripts/regenerate_persona.py` | 페르소나 재생성 (7일 증분/전체) |
| `scripts/night_ops.py` | 야간 자동화 리서치 작업 |
| `scripts/optimize_memory.py` | 4단계 메모리 최적화 (텍스트 정리, 역할 정규화) |
| `scripts/cleanup_messages.py` | LLM 기반 메시지 정리 (병렬, 체크포인트) |
| `scripts/dedup_knowledge_graph.py` | 지식 그래프 중복 제거 |
| `scripts/populate_knowledge_graph.py` | 지식 그래프 초기 구축 |
| `scripts/run_migrations.py` | 데이터베이스 스키마 마이그레이션 |
| `scripts/cron_memory_gc.sh` | cron용 메모리 GC 래퍼 스크립트 |

---

</details>

---

<details>
<summary><strong>English Version</strong></summary>

> **Environment:** Pop!_OS (Ubuntu 24.04 LTS) + Systemd  
> **Last Update:** 2026-02-11  
> **Project:** axnmihn - AI Backend Service

---

## Table of Contents

1. [Service Architecture](#service-architecture)
2. [Basic Commands](#basic-commands)
3. [Service Management](#service-management)
4. [Monitoring & Debugging](#monitoring--debugging)
5. [Daily Operations](#daily-operations)
6. [Troubleshooting](#troubleshooting-en)
7. [Automation](#automation)
8. [Backup & Recovery](#backup--recovery-en)
9. [Emergency Response](#emergency-response)
10. [Quick Reference](#quick-reference-en)

---

## Service Architecture

### Systemd User Services

All services managed via `systemctl --user` (no sudo required).

#### Core Services

| Service | Port | Description | Resource Limits |
|---------|------|-------------|-----------------|
| `axnmihn-backend.service` | 8000 | Main FastAPI Backend | 4G RAM, CPU 200% |
| `axnmihn-mcp.service` | 8555 | MCP Server (SSE) | 1G RAM, CPU 100% |
| `axnmihn-research.service` | 8766 | Research MCP Server | 2G RAM, CPU 150% |
| `axnmihn-tts.service` | 8002 | TTS Microservice (Qwen3-TTS) | 4G RAM, CPU 200% |
| `axnmihn-wakeword.service` | - | Wakeword Detector | 512M RAM, CPU 50% |

#### MCP Extension Services

| Service | Port | Description |
|---------|------|-------------|
| `context7-mcp.service` | 3002 | Context7 MCP (Supergateway) |
| `markitdown-mcp.service` | 3001 | Markitdown MCP (Supergateway) |

#### Auxiliary Services (Oneshot/Timer)

| Service | Interval | Description |
|---------|----------|-------------|
| `auto-cleanup.timer` | Weekly | Clean pip cache, __pycache__, old logs |
| `axnmihn-mcp-reclaim.timer` | 10min | MCP cgroup page cache reclaim |
| `context7-mcp-restart.timer` | 6h | Context7 memory leak cleanup |
| `markitdown-mcp-restart.timer` | 4h | Markitdown memory leak cleanup |
| `claude-review.timer` | 3h | Automated code review |

### Port Mapping

| Port | Service | Access |
|------|---------|--------|
| 3000 | Open WebUI | Public |
| 3001 | Markitdown MCP | Localhost |
| 3002 | Context7 MCP | Localhost |
| 5432 | PostgreSQL (systemd) | Localhost |
| 6379 | Redis (systemd) | Localhost |
| 8000 | Axnmihn Backend | Public |
| 8002 | TTS | Localhost |
| 8123 | Home Assistant | LAN |
| 8555 | Main MCP | Localhost |
| 8766 | Research MCP | Localhost |

### Directory Structure

```
/home/northprot/projects/axnmihn/
├── backend/               # FastAPI application
│   ├── app.py            # Entry point
│   ├── config.py         # Configuration
│   ├── api/              # HTTP routers
│   ├── core/             # Core logic
│   ├── llm/              # LLM providers
│   ├── memory/           # 6-layer memory system
│   ├── native/           # C++17 extension module
│   └── protocols/mcp/    # MCP protocol handlers
├── tests/                # pytest tests
├── scripts/              # Automation scripts
├── data/                 # Runtime data
│   ├── working_memory.json       # M1: Working memory
│   ├── knowledge_graph.json      # M5.2: Knowledge graph
│   ├── dynamic_persona.json      # AI persona
│   ├── sqlite/
│   │   └── sqlite_memory.db     # M3: Session archive
│   └── chroma_db/               # M4: Vector embeddings
├── logs/                 # Application logs
│   └── backend.log       # Main log file
├── storage/              # Research results, cron reports
│   ├── research/
│   │   ├── inbox/        # Deep research results
│   │   └── artifacts/    # Web scraping
│   └── cron/
│       └── reports/      # Night shift reports
├── .env                  # Environment variables (API keys)
├── docker-compose.yml    # Docker deployment (optional)
└── Dockerfile            # Multi-stage build
```

---

## Basic Commands

### Check Service Status

```bash
# All services
systemctl --user status axnmihn-backend axnmihn-mcp --no-pager

# Single service
systemctl --user status axnmihn-backend

# Running services only
systemctl --user list-units "axnmihn-*" --state=running
```

### Service Control

```bash
# Start
systemctl --user start axnmihn-backend

# Stop
systemctl --user stop axnmihn-backend

# Restart
systemctl --user restart axnmihn-backend

# Enable auto-start
systemctl --user enable axnmihn-backend

# Disable auto-start
systemctl --user disable axnmihn-backend
```

### View Logs

```bash
# Recent logs (journald)
journalctl --user -u axnmihn-backend --no-pager -n 50

# Real-time logs (tail -f)
journalctl --user -u axnmihn-backend -f

# Application log
tail -n 100 logs/backend.log

# Error logs only
grep -E "ERROR|CRITICAL" logs/backend.log | tail -50

# Time range
journalctl --user -u axnmihn-backend --since "2026-02-11 08:00" --until "2026-02-11 09:00"
```

### Health Check

```bash
# Quick health check
curl -s http://localhost:8000/health/quick

# Full health check (memory, LLM, modules)
curl -s http://localhost:8000/health | python3 -m json.tool

# MCP server health
curl -s http://localhost:8555/health
```

### Port Check

```bash
# Core ports
ss -tlnp | grep -E ":(8000|8555|8766)"

# Specific port process
lsof -i :8000

# All axnmihn processes
pgrep -af "python.*(axnmihn|uvicorn|mcp)" | head -20
```

---

## Service Management

### Full Restart

```bash
# Restart backend
systemctl --user restart axnmihn-backend

# Restart all (with dependencies)
systemctl --user restart axnmihn-backend axnmihn-mcp axnmihn-research

# Restart and check status
systemctl --user status axnmihn-backend --no-pager && \
curl -s http://localhost:8000/health/quick
```

### Apply Configuration Changes

```bash
# After .env modification
systemctl --user restart axnmihn-backend

# After systemd service file modification
systemctl --user daemon-reload
systemctl --user restart axnmihn-backend
```

### Timer Management

```bash
# List active timers
systemctl --user list-timers

# Specific timer status
systemctl --user status axnmihn-mcp-reclaim.timer

# Start/stop timer
systemctl --user start axnmihn-mcp-reclaim.timer
systemctl --user stop axnmihn-mcp-reclaim.timer

# Trigger timer immediately (test)
systemctl --user start axnmihn-mcp-reclaim.service
```

---

## Monitoring & Debugging

### Resource Usage

```bash
# CPU/Memory (real-time)
top -u northprot

# Specific process resources
ps aux | grep "uvicorn.*axnmihn"

# Systemd cgroup resources
systemctl --user status axnmihn-backend | grep -E "Memory|CPU"

# Disk usage
du -sh data/ logs/ storage/
```

### Error Analysis

```bash
# Recent errors
grep -E "ERROR|CRITICAL|Traceback" logs/backend.log | tail -100

# Error frequency
grep "ERROR" logs/backend.log | cut -d' ' -f4 | sort | uniq -c | sort -rn

# Specific error pattern
grep -A 10 "ConnectionError" logs/backend.log | tail -50
```

### Memory System Diagnostics

```bash
# Memory statistics
curl -s http://localhost:8000/memory/stats | python3 -m json.tool

# SQLite database size
ls -lh data/sqlite/sqlite_memory.db

# ChromaDB directory size
du -sh data/chroma_db/

# Working memory
cat data/working_memory.json | python3 -m json.tool | head -50
```

### Network Diagnostics

```bash
# API response time
time curl -s http://localhost:8000/health/quick

# Connection count
ss -tn | grep ":8000" | wc -l

# Real-time request log
tail -f logs/backend.log | grep "POST\|GET"
```

---

## Daily Operations

### Scenario 1: Code Changes Deployment

```bash
# 1. Modify code (backend/ directory)
vim backend/core/chat_handler.py

# 2. Lint & format (optional)
~/projects-env/bin/ruff check --fix backend/
python -m black backend/

# 3. Restart backend
systemctl --user restart axnmihn-backend

# 4. Monitor logs
journalctl --user -u axnmihn-backend -f -n 50
# (Ctrl+C to stop)

# 5. Health check
curl -s http://localhost:8000/health/quick

# 6. Check errors
grep "ERROR" logs/backend.log | tail -20
```

### Scenario 2: Memory Consolidation

```bash
# Trigger memory consolidation (decay + persona evolution)
curl -X POST http://localhost:8000/memory/consolidate \
  -H "Authorization: Bearer ${AXNMIHN_API_KEY}"

# Check consolidation status
tail -f logs/backend.log | grep "consolidat"
```

> **Note:** The app runs automatic consolidation every 6 hours. Manual execution is only needed for immediate consolidation.

### Scenario 3: Disk Space Low

```bash
# 1. Check disk usage
df -h ~

# 2. Find large directories
du -sh ~/projects/axnmihn/* | sort -rh | head -10

# 3. Clean old logs
find logs/ -name "*.log.*" -mtime +30 -delete

# 4. SQLite VACUUM
sqlite3 data/sqlite/sqlite_memory.db "VACUUM;"

# 5. Docker cleanup (optional)
docker system prune -a --volumes
```

### Scenario 4: Performance Degradation

```bash
# 1. Process resources
systemctl --user status axnmihn-backend --no-pager

# 2. CPU usage
top -b -n 1 -u northprot | grep python

# 3. Memory usage
ps aux | grep uvicorn | awk '{print $6}'

# 4. Response time measurement
for i in {1..10}; do
  time curl -s http://localhost:8000/health/quick > /dev/null
done

# 5. Find slow requests in logs
grep "took.*ms" logs/backend.log | awk '{print $NF}' | sort -rn | head -20
```

### Scenario 5: Update API Keys

```bash
# 1. Backup .env
cp .env .env.backup

# 2. Modify API keys
vim .env
# GEMINI_API_KEY=new_key
# ANTHROPIC_API_KEY=new_key

# 3. Restart backend
systemctl --user restart axnmihn-backend

# 4. Check LLM providers
curl -s http://localhost:8000/llm/providers | python3 -m json.tool

# 5. Test request
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer ${AXNMIHN_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"test"}],"stream":false}'
```

---

## Troubleshooting (EN)

### Issue: Service Won't Start

```bash
# 1. Detailed logs
journalctl --user -u axnmihn-backend -n 100 --no-pager

# 2. Validate config
python3 -c "from backend.config import config; print(config.model_dump())"

# 3. Port conflicts
ss -tlnp | grep :8000

# 4. Environment variables
grep -v "^#" .env | grep "API_KEY"

# 5. Manual execution for errors
cd ~/projects/axnmihn
~/projects-env/bin/python -m uvicorn backend.app:app --host 0.0.0.0 --port 8000
```

**Solutions:**
- Port conflict: Kill existing process (`kill <PID>`)
- Missing API key: Add to `.env`
- Dependencies: `pip install -r backend/requirements.txt`

---

### Issue: Out of Memory (OOM)

```bash
# 1. Memory usage
free -h
systemctl --user status axnmihn-backend | grep Memory

# 2. ChromaDB size
du -sh data/chroma_db/

# 3. Memory cleanup script
~/projects-env/bin/python scripts/memory_gc.py

# 4. SQLite VACUUM
sqlite3 data/sqlite/sqlite_memory.db "VACUUM; ANALYZE;"

# 5. Restart service
systemctl --user restart axnmihn-backend
```

**Solutions:**
- ChromaDB too large: Delete old memories (`memory_gc.py`)
- SQLite bloat: Run VACUUM
- Memory leak: Restart and monitor

---

### Issue: LLM Request Failures

```bash
# 1. Provider status
curl -s http://localhost:8000/llm/providers | python3 -m json.tool

# 2. API keys
grep "API_KEY" .env

# 3. Network test
curl -s https://generativelanguage.googleapis.com/v1beta/models

# 4. Error logs
grep -E "Gemini|Anthropic|LLM" logs/backend.log | tail -50

# 5. Circuit breaker status
grep "circuit.*open" logs/backend.log
```

**Solutions:**
- API key expired: Issue new key, update `.env`
- Rate limit: Wait and retry
- Circuit breaker open: Auto-recovery after cooldown

---

### Issue: PostgreSQL Connection Failure (Optional)

```bash
# 1. PostgreSQL service status
systemctl --user status axnmihn-postgres

# 2. PostgreSQL logs
journalctl --user -u axnmihn-postgres --no-pager -n 50

# 3. Connection test
psql postgresql://axnmihn:password@localhost:5432/axnmihn -c "SELECT 1;"

# 4. DATABASE_URL
grep "DATABASE_URL" .env

# 5. Restart service
systemctl --user restart axnmihn-postgres
```

**Solutions:**
- Service stopped: `systemctl --user start axnmihn-postgres`
- Password mismatch: Verify `.env` and PostgreSQL configuration
- Port conflict: Kill process on 5432

---

### Issue: Disk I/O Bottleneck

```bash
# 1. I/O usage
iostat -x 1 5

# 2. Find large files
find ~/projects/axnmihn -type f -size +100M -exec ls -lh {} \;

# 3. SQLite WAL size
ls -lh data/sqlite/sqlite_memory.db-wal

# 4. Force WAL checkpoint
sqlite3 data/sqlite/sqlite_memory.db "PRAGMA wal_checkpoint(TRUNCATE);"

# 5. Log rotation
journalctl --disk-usage
```

**Solutions:**
- SQLite WAL bloat: Run checkpoint
- Log bloat: Configure log rotation
- ChromaDB bloat: Clean old data

---

## Automation

### Memory Garbage Collection

```bash
# Manual execution
~/projects-env/bin/python scripts/memory_gc.py

# Register cron (daily at 4 AM — recommended)
(crontab -l 2>/dev/null; echo "0 4 * * * cd ~/projects/axnmihn && ~/projects-env/bin/python scripts/memory_gc.py >> logs/memory_gc.log 2>&1") | crontab -

# Verify registration
crontab -l | grep memory_gc
```

> **Note:** The app also runs automatic consolidation every 6 hours.
> Cron handles additional hash and semantic deduplication.

**Tasks:**
- Remove duplicate memories (similarity >= 0.90)
- Delete low-importance memories (< 0.03)
- Clean old session archives (30+ days)

---

### Database Maintenance

```bash
# SQLite VACUUM & ANALYZE
~/projects-env/bin/python scripts/db_maintenance.py

# Integrity check
sqlite3 data/sqlite/sqlite_memory.db "PRAGMA integrity_check;"

# Cron setup (weekly)
crontab -e
# 0 3 * * 0 cd ~/projects/axnmihn && ~/projects-env/bin/python scripts/db_maintenance.py >> logs/db_maintenance.log 2>&1
```

---

### Persona Regeneration

```bash
# 7-day incremental update
~/projects-env/bin/python scripts/regenerate_persona.py

# Full regeneration
~/projects-env/bin/python scripts/regenerate_persona.py --full
```

---

### Night Operations

```bash
# Night ops script
~/projects-env/bin/python scripts/night_ops.py

# Check results
ls -lh storage/cron/reports/
```

---

## Backup & Recovery (EN)

### Data Backup

```bash
#!/bin/bash
# backup.sh

BACKUP_DIR=~/backups/axnmihn/$(date +%Y%m%d_%H%M%S)
mkdir -p "$BACKUP_DIR"

# Backup data
cp -r ~/projects/axnmihn/data "$BACKUP_DIR/"
cp -r ~/projects/axnmihn/storage "$BACKUP_DIR/"
cp ~/projects/axnmihn/.env "$BACKUP_DIR/"

# SQLite WAL checkpoint before backup
sqlite3 ~/projects/axnmihn/data/sqlite/sqlite_memory.db "PRAGMA wal_checkpoint(TRUNCATE);"

# Compress
tar czf "$BACKUP_DIR.tar.gz" -C "$BACKUP_DIR/.." "$(basename "$BACKUP_DIR")"
rm -rf "$BACKUP_DIR"

echo "Backup complete: $BACKUP_DIR.tar.gz"
```

---

### Recovery

```bash
# Extract backup
tar xzf ~/backups/axnmihn/20260211_080000.tar.gz -C /tmp/

# Stop services
systemctl --user stop axnmihn-backend axnmihn-mcp

# Restore data
rsync -av /tmp/20260211_080000/data/ ~/projects/axnmihn/data/
rsync -av /tmp/20260211_080000/storage/ ~/projects/axnmihn/storage/

# Restart services
systemctl --user start axnmihn-backend axnmihn-mcp

# Cleanup
rm -rf /tmp/20260211_080000
```

---

## Emergency Response

### Critical: All Services Down

```bash
# 1. Check all services
systemctl --user status axnmihn-* --no-pager

# 2. Restart all
systemctl --user restart axnmihn-backend axnmihn-mcp axnmihn-research

# 3. Health check
curl -s http://localhost:8000/health/quick

# 4. Monitor logs
journalctl --user -u axnmihn-backend -f -n 100
```

---

### Critical: Memory Leak

```bash
# 1. Memory usage
free -h
ps aux | grep uvicorn | awk '{print $6}'

# 2. Restart service
systemctl --user restart axnmihn-backend

# 3. Memory cleanup
~/projects-env/bin/python scripts/memory_gc.py

# 4. Monitor
watch -n 5 'ps aux | grep uvicorn | awk "{print \$6}"'
```

---

### Critical: API Unresponsive

```bash
# 1. Check process
pgrep -af uvicorn

# 2. Check port
ss -tlnp | grep :8000

# 3. Force restart
systemctl --user restart axnmihn-backend

# 4. Manual start (debug)
~/projects-env/bin/python -m uvicorn backend.app:app --host 0.0.0.0 --port 8000
```

---

## Quick Reference (EN)

### Command Summary

| Task | Command |
|------|---------|
| Service status | `systemctl --user status axnmihn-backend` |
| Restart service | `systemctl --user restart axnmihn-backend` |
| View logs | `journalctl --user -u axnmihn-backend -n 50` |
| Health check | `curl -s http://localhost:8000/health/quick` |
| Error logs | `grep ERROR logs/backend.log \| tail -50` |
| Memory stats | `curl -s http://localhost:8000/memory/stats` |
| Port check | `ss -tlnp \| grep :8000` |
| Process check | `pgrep -af axnmihn` |

---

### Environment Variables

| Variable | Description | Location |
|----------|-------------|----------|
| `AXNMIHN_API_KEY` | API authentication | `.env` |
| `GEMINI_API_KEY` | Gemini LLM | `.env` |
| `ANTHROPIC_API_KEY` | Claude LLM | `.env` |
| `DISCORD_BOT_TOKEN` | Discord bot token | `.env` |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token | `.env` |
| `DATABASE_URL` | PostgreSQL (optional) | `.env` |
| `PYTHONPATH` | `/home/northprot/projects/axnmihn` | systemd |

---

### Useful Scripts

| Script | Description |
|--------|-------------|
| `scripts/memory_gc.py` | Memory garbage collection (dedup, decay, oversized removal) |
| `scripts/db_maintenance.py` | SQLite VACUUM, ANALYZE, integrity check |
| `scripts/regenerate_persona.py` | Persona regeneration (7-day incremental/full) |
| `scripts/night_ops.py` | Automated night shift research |
| `scripts/optimize_memory.py` | 4-phase memory optimization (text cleaning, role normalization) |
| `scripts/cleanup_messages.py` | LLM-powered message cleanup (parallel, checkpointed) |
| `scripts/dedup_knowledge_graph.py` | Knowledge graph deduplication |
| `scripts/populate_knowledge_graph.py` | Knowledge graph initial population |
| `scripts/run_migrations.py` | Database schema migrations |
| `scripts/cron_memory_gc.sh` | Cron wrapper for memory GC |

---

</details>
