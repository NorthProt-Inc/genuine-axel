# Axnmihn Operations Guide

> **환경:** Pop!_OS (Ubuntu 24.04 LTS) + Systemd
> **마지막 업데이트:** 2026-02-11

---

## 목차

1. [서비스 구조](#서비스-구조)
2. [Claude Code 통합](#claude-code-통합)
3. [기초 생존 명령어](#기초-생존-명령어)
4. [파일 & 디렉토리 조작](#파일--디렉토리-조작)
5. [프로세스 & 서비스 관리](#프로세스--서비스-관리)
6. [Git 버전 관리](#git-버전-관리)
7. [Python 환경 관리](#python-환경-관리)
8. [시스템 모니터링 & 디버깅](#시스템-모니터링--디버깅)
9. [Axnmihn 시스템 전용 명령어](#axnmihn-시스템-전용-명령어)
10. [일상 운영 시나리오](#일상-운영-시나리오)
11. [트러블슈팅 의사결정 트리](#트러블슈팅-의사결정-트리)
12. [Cron 자동화](#cron-자동화)
13. [유용한 원라이너](#유용한-원라이너)
14. [백업 & 복구](#백업--복구)
15. [인프라 서비스 관리](#인프라-서비스-관리)
16. [응급 상황 대응](#응급-상황-대응)
17. [빠른 참조 카드](#빠른-참조-카드)

---

## 서비스 구조

### Systemd User Services
> **참고:** 모든 서비스는 **user service**로 `systemctl --user`로 관리 (sudo 불필요)

#### 핵심 서비스

| 서비스 | 포트 | 설명 | 리소스 제한 |
|--------|------|------|-------------|
| axnmihn-backend.service | 8000 | Main FastAPI Backend | 4G RAM, CPU 200% |
| axnmihn-mcp.service | 8555 | MCP Server (SSE) | 1G RAM, CPU 100% |
| axnmihn-research.service | 8766 | Research MCP Server (Deep Research) | 2G RAM, CPU 150% |
| axnmihn-tts.service | 8002 | TTS Microservice (Qwen3-TTS) | 4G RAM, CPU 200% |
| axnmihn-wakeword.service | - | Wakeword Detector | 512M RAM, CPU 50% |

#### MCP 확장 서비스

| 서비스 | 포트 | 설명 | 리소스 제한 |
|--------|------|------|-------------|
| context7-mcp.service | 3002 | Context7 MCP (Supergateway) | 1G RAM |
| markitdown-mcp.service | 3001 | Markitdown MCP (Supergateway) | 1G RAM |

#### 인프라 서비스

| 서비스 | 설명 |
|--------|------|
| axnmihn-postgres.service | PostgreSQL 17 + pgvector (5432) |
| axnmihn-redis.service | Redis 7.0 (6379) |

#### 보조 서비스 (Oneshot/Timer)

| 서비스 | 타이머 주기 | 설명 |
|--------|-------------|------|
| auto-cleanup.service | 매주 1회 | 주간 자동 정리 (pip 캐시, __pycache__, 오래된 로그) |
| axnmihn-mcp-reclaim.service | 10분마다 | MCP cgroup 페이지 캐시 회수 (300MB 초과 시) |
| context7-mcp-restart.service | 6시간마다 | Context7 프로세스 릭 정리용 재시작 |
| markitdown-mcp-restart.service | 4시간마다 | Markitdown 프로세스 릭 정리용 재시작 |
| claude-review.service | 3시간마다 | 자동 코드 리뷰 |

### 서비스 의존성

```
axnmihn-postgres (독립 실행)
axnmihn-redis (독립 실행)
    |
    +--- axnmihn-backend (postgres, redis 필요)
    |       |
    |       +--- axnmihn-wakeword (backend 필수)
    |       +--- axnmihn-research (backend 필수, mcp 선택)
    |
    +--- axnmihn-mcp (postgres 필요)
            +--- axnmihn-mcp-reclaim (mcp의 메모리 관리)

axnmihn-tts (독립 실행, localhost:8002)
```

### 포트 요약

| 포트 | 서비스 |
|------|--------|
| 3000 | Open WebUI (Frontend) |
| 3001 | Markitdown MCP |
| 3002 | Context7 MCP |
| 5432 | PostgreSQL (systemd) |
| 6379 | Redis (systemd) |
| 8000 | Axnmihn Backend |
| 8002 | TTS Microservice (localhost only) |
| 8123 | Home Assistant |
| 8555 | Main MCP Server |
| 8766 | Research MCP Server |

### 설정 파일 위치
```
/home/northprot/
├── .claude/                    # Claude Code 전역 설정
│   ├── settings.json
│   └── settings.local.json
├── .config/
│   ├── systemd/user/           # Systemd User Service 파일
│   └── logrotate/
│       └── axnmihn.conf        # 로그 로테이션 설정
├── projects/axnmihn/           # 프로젝트
│   ├── .claude/                # 프로젝트별 Claude 설정
│   │   └── settings.local.json
│   ├── .env                    # 환경변수 (API 키, 설정)
│   ├── docker-compose.yml      # Docker 배포용 (선택)
│   ├── backend/                # FastAPI 애플리케이션
│   │   ├── api/                # HTTP/WebSocket 라우터
│   │   │   └── websocket.py    # WebSocket 실시간 통신 (/ws)
│   │   ├── core/               # 핵심 로직
│   │   │   ├── errors.py       # 구조화된 에러 계층 (AxnmihnError)
│   │   │   ├── health/         # 컴포넌트 헬스체크
│   │   │   ├── intent/         # 인텐트 분류기 (6종)
│   │   │   └── telemetry/      # Prometheus 메트릭스
│   │   └── ...
│   ├── data/                   # 런타임 데이터
│   │   ├── working_memory.json     # M1: 워킹 메모리
│   │   ├── knowledge_graph.json    # M5.2: 지식 그래프
│   │   ├── dynamic_persona.json    # AI 페르소나
│   │   ├── sqlite/
│   │   │   └── sqlite_memory.db    # M3: 세션 아카이브
│   │   └── chroma_db/              # M4: 벡터 임베딩
│   ├── logs/                   # 애플리케이션 로그
│   └── storage/                # 리서치 아티팩트, 크론 결과
│       ├── research/
│       │   ├── inbox/          # 딥 리서치 결과
│       │   └── artifacts/      # 웹 페이지 스크랩
│       └── cron/
│           └── reports/        # 야간 작업 보고서
└── projects-env/               # Python venv (프로젝트 외부)
```

### Systemd 서비스 파일 위치
```
~/.config/systemd/user/
├── axnmihn-backend.service
├── axnmihn-mcp.service
├── axnmihn-mcp-reclaim.service        # + .timer
├── axnmihn-research.service
├── axnmihn-tts.service
├── axnmihn-wakeword.service
├── context7-mcp.service
├── context7-mcp-restart.service       # + .timer
├── markitdown-mcp.service
├── markitdown-mcp-restart.service     # + .timer
├── docker.service
├── auto-cleanup.service               # + .timer
└── claude-review.service              # + .timer
```

---

## Claude Code 통합

> Claude Code에서 시스템을 효율적으로 관리하기 위한 슬래시 명령어와 사용법

### 슬래시 명령어 빠른 참조

| 명령어 | 설명 | 예시 |
|--------|------|------|
| `/restart` | 백엔드 재시작 + 헬스체크 | `/restart` |
| `/logs` | 로그 확인 | `/logs error`, `/logs warn`, `/logs 50` |
| `/services` | 전체 서비스 상태 확인 | `/services` |
| `/analyze-error` | 최근 에러 분석 및 원인 추적 | `/analyze-error` |
| `/model-check` | LLM 모델 설정 전체 확인 | `/model-check` |
| `/code-health` | 미사용 코드/임포트/함수 검출 | `/code-health` |
| `/security` | 보안 취약점 스캔 | `/security` |
| `/purge-cache` | Python/Node.js 캐시 정리 | `/purge-cache` |
| `/project-init` | 프로젝트 컨텍스트 로딩 | `/project-init` |
| `/deps` | 의존성 상태 및 보안 감사 | `/deps` |
| `/diff-review` | 로컬 변경사항 리뷰 | `/diff-review` |
| `/perf` | 코드 성능 분석 | `/perf` |
| `/explain` | 코드 구조/함수 설명 | `/explain` |

### 명령어 상세 사용법

#### `/logs` - 로그 확인
```bash
/logs error      # 에러 로그만 확인
/logs warn       # 경고 로그 확인
/logs 100        # 최근 100줄 확인
/logs all        # 전체 로그 스트림
```

### 일반적인 작업 흐름

#### 1. 코드 수정 후 반영
```
1. 코드 수정
2. /restart          # 백엔드 재시작
3. /logs error       # 에러 확인
4. curl 테스트       # API 동작 확인
```

#### 2. 문제 발생 시 진단
```
1. /services         # 서비스 상태 확인
2. /analyze-error    # 에러 분석
3. /logs error       # 상세 로그 확인
4. 원인 파악 후 수정
5. /restart
```

#### 3. 성능 문제 조사
```
1. /services         # 메모리/CPU 확인
2. /logs warn        # 경고 메시지 확인
3. nvidia-smi        # GPU 상태 (터미널)
4. htop              # 프로세스 상태 (터미널)
```

---

## 기초 생존 명령어

### 현재 위치 & 이동
```bash
pwd                              # 지금 어디에 있는지
cd /home/northprot/projects/axnmihn  # 절대 경로로 이동
cd ..                            # 상위 폴더로
cd ~                             # 홈 디렉토리로
cd -                             # 이전 디렉토리로 돌아가기
```

### 파일/폴더 목록 보기
```bash
ls                     # 기본 목록
ls -la                 # 상세 목록 (숨김 파일 포함, 권한, 크기)
ls -lh                 # 사람이 읽기 쉬운 크기 (K, M, G)
ls -lt                 # 수정 시간순 정렬
```

### 파일 내용 보기
```bash
cat file.txt           # 전체 내용 출력
head -n 20 file.txt    # 처음 20줄
tail -n 20 file.txt    # 마지막 20줄
tail -f file.txt       # 실시간 파일 변화 모니터링 (로그 볼 때!)
less file.txt          # 페이지 단위로 보기 (q로 종료)
```

### 텍스트 검색
```bash
grep "검색어" file.txt              # 파일 내 검색
grep -r "검색어" .                  # 하위 폴더까지 재귀 검색
grep -rn "검색어" .                 # 재귀 검색 + 줄 번호
grep -i "검색어" file.txt           # 대소문자 무시
```

---

## 파일 & 디렉토리 조작

### 파일/폴더 생성
```bash
touch newfile.txt               # 빈 파일 생성
mkdir newfolder                 # 폴더 생성
mkdir -p a/b/c                  # 중첩 폴더 한 번에 생성
```

### 복사 & 이동
```bash
cp source.txt dest.txt          # 파일 복사
cp -r sourcedir/ destdir/       # 폴더 복사 (재귀)
mv old.txt new.txt              # 이름 변경 또는 이동
```

### 삭제 (주의!)
```bash
rm file.txt                     # 파일 삭제 (휴지통 없음!)
rm -r folder/                   # 폴더 삭제
rm -rf folder/                  # 강제 삭제 (물어보지 않음) - 위험!
```

> **CAUTION:** `rm -rf`는 되돌릴 수 없음! 특히 `rm -rf /` 또는 `rm -rf ~`는 시스템 파괴.
> 항상 삭제 전에 `ls`로 확인하고, 가능하면 `rm -ri`로 하나씩 확인.

### 파일 권한
```bash
chmod +x script.sh              # 실행 권한 추가
chmod 755 script.sh             # rwxr-xr-x (주인 모든 권한, 나머지 읽기+실행)
chmod 644 file.txt              # rw-r--r-- (주인 읽기쓰기, 나머지 읽기만)
```

---

## 프로세스 & 서비스 관리

### 프로세스 확인
```bash
ps aux                          # 모든 프로세스
ps aux | grep python            # Python 프로세스만
pgrep -a python                 # 파이썬 관련 프로세스 깔끔하게 나열
htop                            # 대화형 프로세스 모니터
```

### 프로세스 종료
```bash
kill PID                        # 정상 종료 요청
kill -9 PID                     # 강제 종료 (안 죽을 때)
pkill -f "uvicorn"              # 이름으로 종료
pkill -f [파일명.py]            # 부드러운 종료
pkill -9 -f [파일명.py]         # 강제 종료
killall python                  # 모든 python 프로세스 종료
```

### 포트 확인
```bash
lsof -i:8000                    # 8000 포트 사용 프로세스
ss -tlnp                        # 모든 열린 포트
ss -tlnp | grep -E "8000|8002|8555|8766|3000|3001|3002|5432|6379|8123"  # 주요 포트만
```

> **TIP:** 백엔드가 안 뜰 때 99%는 **포트 충돌**! 먼저 `lsof -i:포트번호`로 확인.

### Systemd 서비스 관리 (User Services)
> **중요:** User service는 `systemctl --user`로 관리 (sudo 사용 X)

```bash
# 상태 확인
systemctl --user status axnmihn-backend
systemctl --user status axnmihn-backend axnmihn-mcp axnmihn-research axnmihn-tts

# 시작/중지/재시작
systemctl --user start axnmihn-backend
systemctl --user stop axnmihn-backend
systemctl --user restart axnmihn-backend

# 핵심 서비스 동시 재시작
systemctl --user restart axnmihn-backend axnmihn-mcp axnmihn-research

# 전체 재시작 (MCP 확장 + TTS 포함)
systemctl --user restart axnmihn-backend axnmihn-mcp axnmihn-research axnmihn-tts context7-mcp markitdown-mcp

# 부팅 시 자동 시작
systemctl --user enable axnmihn-backend
systemctl --user disable axnmihn-backend

# 타이머 관리
systemctl --user list-timers                # 모든 타이머 확인
systemctl --user status axnmihn-mcp-reclaim.timer  # 특정 타이머 상태
```

### 로그 확인
```bash
# Systemd 저널 (user service는 --user 플래그 필요)
journalctl --user -u axnmihn-backend -f                    # 실시간 팔로우
journalctl --user -u axnmihn-backend -n 100                # 최근 100줄
journalctl --user -u axnmihn-backend --since "1 hour ago"  # 최근 1시간
journalctl --user -u axnmihn-mcp -f --since "10 min ago"

# 파일 로그 (추천 - 더 상세함)
tail -f ~/projects/axnmihn/logs/backend.log          # 실시간 로그
tail -f ~/projects/axnmihn/logs/backend_error.log    # 에러만
```

---

## Git 버전 관리

### 기본 워크플로우
```bash
git status                      # 변경사항 확인 (항상 먼저!)
git diff                        # 변경 내용 상세 보기
git diff --staged               # 스테이징된 변경사항
```

### 변경사항 저장
```bash
git add file.txt                # 특정 파일 스테이징
git add .                       # 모든 변경사항 스테이징
git commit -m "메시지"          # 커밋
git commit -am "메시지"         # add + commit 한 번에 (추적 중인 파일만)
```

### 히스토리 & 되돌리기
```bash
git log --oneline -10           # 최근 10개 커밋 한 줄씩
git log -p -1                   # 마지막 커밋 상세 diff

git checkout -- file.txt        # 파일 변경 취소 (커밋 전)
git reset HEAD~1                # 마지막 커밋 취소 (변경사항 유지)
git reset --hard HEAD~1         # 마지막 커밋 완전 삭제 (위험!)
```

### 브랜치
```bash
git branch                      # 브랜치 목록
git checkout -b feature-name    # 새 브랜치 생성 + 이동
git checkout main               # main 브랜치로 이동
git merge feature-name          # 브랜치 병합
```

### 원격 저장소
```bash
git pull                        # 원격에서 가져오기
git push                        # 원격으로 보내기
git remote -v                   # 원격 저장소 확인
```

### GitHub CLI
```bash
# 설치 & 인증
sudo apt install -y gh
gh auth login --web

# Git 설정
git config --global user.email "admin@northprot.com"
git config --global user.name "NorthProt"
git config --global init.defaultBranch main

# Repo 생성 & 푸시
gh repo create NorthProt-Inc/repo-name --public --source=. --remote=origin --push
```

---

## Python 환경 관리

### 시스템 Python & venv
```bash
# 시스템 Python (Ubuntu 24.x 기본)
/usr/bin/python3                # Python 3.12.3

# 프로젝트 venv (프로젝트 외부에 위치)
/home/northprot/projects-env/bin/python
/home/northprot/projects-env/bin/pip

# venv 활성화 (중요!)
source ~/projects-env/bin/activate
deactivate                      # 비활성화
```

### 패키지 관리
```bash
pip install package             # 패키지 설치
pip install -r backend/requirements.txt # 의존성 일괄 설치
pip freeze > backend/requirements.txt   # 현재 패키지 목록 저장
pip list                        # 설치된 패키지 목록
pip show package                # 패키지 정보
pip uninstall package           # 패키지 삭제

# 의존성 업데이트 원라이너
source ~/projects-env/bin/activate && cd /home/northprot/projects/axnmihn && pip install -r backend/requirements.txt --upgrade
```

### 코드 검증
```bash
python -m py_compile file.py    # 문법 검사 (실행 안 함)
python -c "import module"       # 모듈 import 테스트
python file.py                  # 실행
which python                    # 어떤 Python인지 확인
```

> **IMPORTANT:** 가상환경 활성화 안 하고 `pip install`하면 시스템 Python에 설치됨!
> 항상 `which python`으로 어떤 Python인지 확인.

---

## 시스템 모니터링 & 디버깅

### 디스크 사용량
```bash
df -h                           # 전체 디스크 사용량
df -h /home                     # /home 파티션만
du -sh *                        # 현재 폴더 내 크기
du -sh * | sort -h              # 크기순 정렬
du -sh ~/projects/axnmihn/data/*  # 데이터 디렉토리 크기 확인
ncdu                            # 대화형 디스크 분석
```

### 메모리 & CPU
```bash
free -h                         # 메모리 사용량
vmstat 1 5                      # CPU/메모리 상태 5초간 모니터링
htop                            # 대화형 프로세스 모니터

# 서비스 메모리 사용량 확인
systemctl --user status axnmihn-backend axnmihn-mcp axnmihn-research axnmihn-tts --no-pager | grep -E "●|Memory"
```

### GPU 관리
```bash
nvidia-smi                      # GPU 상태 확인
watch -n 1 nvidia-smi           # GPU 상태 실시간 모니터링
sudo nvidia-smi -pl 350         # Power Limit 350W로 올리기

# GPU 요약 (온도, 메모리, 사용률)
nvidia-smi --query-gpu=name,temperature.gpu,memory.used,memory.total,utilization.gpu --format=csv
```

### 네트워크
```bash
ping google.com                 # 인터넷 연결 확인
curl -I https://api.example.com # HTTP 헤더만 확인
curl https://api.example.com    # API 호출 테스트
ip a                            # 네트워크 인터페이스 목록
ss -tlnp                        # 열린 포트 목록

# Prometheus 메트릭스 확인 (요청 횟수, 응답 시간, 에러)
curl http://localhost:8000/metrics
```

### 시스템 전체 모니터링 (원라이너)
```bash
# CPU + RAM + GPU 한눈에
watch -n 1 'echo "=== CPU ===" && top -bn1 | head -5 && echo "" && echo "=== RAM ===" && free -h && echo "" && echo "=== GPU ===" && nvidia-smi --query-gpu=name,temperature.gpu,memory.used,memory.total,utilization.gpu --format=csv'
```

### 로그 로테이션
```bash
# 설정 파일: ~/.config/logrotate/axnmihn.conf
# - 매일 로테이션, 7일 보관, 압축
# - cron으로 매일 자정 실행

# 수동 실행
logrotate --state ~/.config/logrotate/state ~/.config/logrotate/axnmihn.conf

# 저널 로그 정리
journalctl --user --vacuum-size=500M
sudo journalctl --vacuum-size=500M
```

---

## Axnmihn 시스템 전용 명령어

### 핵심 디렉토리
```bash
/home/northprot/projects/axnmihn/              # 메인 코드
/home/northprot/projects/axnmihn/data/         # 데이터 (SQLite, ChromaDB, JSON)
/home/northprot/projects/axnmihn/logs/         # 로그
/home/northprot/projects/axnmihn/storage/      # 리서치 아티팩트, 크론 결과
/home/northprot/.claude/                       # Claude Code 설정
/home/northprot/backups/axnmihn/               # 백업
```

### 백엔드 재시작 & 로그
```bash
systemctl --user restart axnmihn-backend && sleep 5 && systemctl --user status axnmihn-backend --no-pager
# 재시작 + 로그 팔로우 (원라이너) - 추천!
systemctl --user restart axnmihn-backend && tail -f ~/projects/axnmihn/logs/backend.log

# 개별 명령 (user service - sudo 불필요)
systemctl --user restart axnmihn-backend
journalctl --user -u axnmihn-backend -f
systemctl --user status axnmihn-backend
```

### MCP 서버 관리
```bash
# User service로 관리 (sudo 불필요)
systemctl --user status axnmihn-mcp.service       # 상태 확인
systemctl --user restart axnmihn-mcp.service      # 재시작
journalctl --user -u axnmihn-mcp.service -f       # 로그 확인
systemctl --user stop axnmihn-mcp.service         # 중지

# Research MCP
systemctl --user restart axnmihn-research.service
journalctl --user -u axnmihn-research.service -f

# TTS Microservice
systemctl --user restart axnmihn-tts.service
tail -f ~/projects/axnmihn/logs/tts.log

# Context7 MCP
systemctl --user restart context7-mcp.service
journalctl --user -u context7-mcp.service -f

# Markitdown MCP
systemctl --user restart markitdown-mcp.service
journalctl --user -u markitdown-mcp.service -f
```

### Memory GC 수동 실행
```bash
cd /home/northprot/projects/axnmihn
source ~/projects-env/bin/activate
python scripts/memory_gc.py check           # 상태만 확인
python scripts/memory_gc.py cleanup         # 가비지 정리
python scripts/memory_gc.py full --dry-run  # 전체 GC 시뮬레이션
python scripts/memory_gc.py full            # 전체 GC 실제 실행
```

> **참고:** 앱 내에서 6시간마다 자동 consolidation이 실행됩니다. memory_gc.py는 추가적인 해시/시맨틱 중복 제거를 담당합니다.

### Persona 재생성
```bash
cd /home/northprot/projects/axnmihn
source ~/projects-env/bin/activate
python scripts/regenerate_persona.py
```

### 스크립트 목록

| 스크립트 | 설명 | 사용법 |
|----------|------|--------|
| memory_gc.py | 메모리 GC (해시 중복 제거, 임베딩 유사도, 대용량 제거) | `python scripts/memory_gc.py [check\|cleanup\|full] [--dry-run]` |
| optimize_memory.py | 4단계 메모리 최적화 (텍스트 정리, 역할명 정규화) | `python scripts/optimize_memory.py [--dry-run]` |
| cleanup_messages.py | LLM 기반 메시지 정리 (병렬, 체크포인트 지원) | `python scripts/cleanup_messages.py [--dry-run] [--limit N]` |
| db_maintenance.py | SQLite DB 최적화 (VACUUM, ANALYZE, integrity check) | `python scripts/db_maintenance.py [--dry-run] [--json]` |
| night_ops.py | 야간 자율 학습 (자동 리서치 + 보고서) | cron으로 실행 (0:50~5:50 PST) |
| regenerate_persona.py | 7일 기반 점진적 페르소나 업데이트 | `python scripts/regenerate_persona.py` |
| populate_knowledge_graph.py | 지식 그래프 초기 구축 (ChromaDB + SQLite 소스) | `python scripts/populate_knowledge_graph.py [--batch-size 10] [--clean]` |
| dedup_knowledge_graph.py | 지식 그래프 중복 노드/관계 제거 | `python scripts/dedup_knowledge_graph.py` |
| run_migrations.py | DB 스키마 마이그레이션 (status/list/apply) | `python scripts/run_migrations.py [status\|list\|apply]` |
| cron_memory_gc.sh | 메모리 GC cron 래퍼 (flock, 타임아웃 30분) | `./scripts/cron_memory_gc.sh` |

### axel-chat 사용법 (Rust CLI)

> Rust 기반 CLI. 소스: `~/projects/axel-chat`

```bash
# REPL 모드 (대화형)
axel-chat

# 단일 쿼리
axel-chat -e "안녕"

# 모델 목록 확인
axel-chat :models
```

**주요 기능:**
- 실시간 SSE 스트리밍
- 멀티라인 입력, 히스토리 검색 (Ctrl+R)
- Tab 자동완성
- 세션 관리, 롤 시스템, RAG
- Config: `~/.config/axel_chat/config.yaml`

### API 테스트

#### 기본 엔드포인트
```bash
# 헬스체크
curl http://localhost:8000/health

# 빠른 헬스체크
curl http://localhost:8000/health/quick

# Prometheus 메트릭스 (요청 횟수, 응답 시간, 에러 카운트)
curl http://localhost:8000/metrics

# 채팅 API (OpenAI 호환)
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{"model":"gemini","messages":[{"role":"user","content":"안녕"}]}'

# 스트리밍 응답
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{"model":"gemini","messages":[{"role":"user","content":"안녕"}],"stream":true}'
```

#### 메모리 API
```bash
# 메모리 검색 (시맨틱)
curl -H "Authorization: Bearer YOUR_API_KEY" \
  "http://localhost:8000/memory/search?query=프로젝트%20계획&limit=5"

# 메모리 통합 (decay + 페르소나 진화)
curl -X POST -H "Authorization: Bearer YOUR_API_KEY" \
  http://localhost:8000/memory/consolidate

# 메모리 통계
curl -H "Authorization: Bearer YOUR_API_KEY" \
  http://localhost:8000/memory/stats

# 최근 세션 조회
curl -H "Authorization: Bearer YOUR_API_KEY" \
  http://localhost:8000/memory/sessions

# 세션 종료
curl -X POST -H "Authorization: Bearer YOUR_API_KEY" \
  http://localhost:8000/session/end
```

#### 오디오 API
```bash
# TTS (Text-to-Speech)
curl -X POST http://localhost:8000/v1/audio/speech \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{"input":"안녕하세요","voice":"default"}' \
  --output speech.wav

# STT (Speech-to-Text)
curl -X POST http://localhost:8000/v1/audio/transcriptions \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -F "file=@recording.wav"
```

#### MCP 서버 테스트
```bash
# MCP 서버 상태 (SSE 연결)
curl http://localhost:8555/sse

# Research MCP 상태
curl http://localhost:8766/sse

# MCP 도구 목록 (tools/list)
curl -X POST http://localhost:8555/message \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

### 전체 상태 한눈에 보기
```bash
# 서비스 + 포트 한 번에
echo "=== Services ===" && \
systemctl --user status axnmihn-backend axnmihn-mcp axnmihn-research axnmihn-tts context7-mcp markitdown-mcp --no-pager | grep -E "●|Active" && \
echo "" && echo "=== Ports ===" && \
ss -tlnp | grep -E "8000|8002|8555|8766|3000|3001|3002|5432|6379|8123"
```

### 로그 파일 목록
```
logs/backend.log              # 백엔드 로그
logs/backend_error.log        # 백엔드 에러
logs/mcp.log                  # MCP 서버 로그
logs/mcp_error.log            # MCP 에러
logs/research.log             # 리서치 로그
logs/research_error.log       # 리서치 에러
logs/tts.log                  # TTS 로그
logs/tts_error.log            # TTS 에러
logs/wakeword.log             # 웨이크워드 로그
logs/wakeword_error.log       # 웨이크워드 에러
logs/context7_mcp.log         # Context7 MCP 로그
logs/context7_mcp_error.log   # Context7 MCP 에러
logs/markitdown_mcp.log       # Markitdown MCP 로그
logs/markitdown_mcp_error.log # Markitdown MCP 에러
logs/night_ops.log            # 야간 작업 로그
```

---

## 일상 운영 시나리오

### 아침에 확인할 것들

```bash
# 1. 서비스 상태 한눈에 (또는 /services)
systemctl --user status axnmihn-backend axnmihn-mcp axnmihn-research axnmihn-tts --no-pager | grep -E "●|Active|Memory"

# 2. 야간 작업 로그 확인
tail -50 ~/projects/axnmihn/logs/night_ops.log

# 3. 에러 발생 여부 (또는 /logs error)
grep -c "ERROR" ~/projects/axnmihn/logs/backend.log

# 4. 디스크 여유 공간
df -h /home | tail -1

# 5. GPU 상태 (머신러닝 사용 시)
nvidia-smi --query-gpu=memory.used,memory.total --format=csv
```

### 코드 배포 전 체크리스트

```bash
# 1. 현재 상태 확인
git status
git diff

# 2. 문법 검사
python -m py_compile backend/app.py

# 3. 테스트 실행
pytest tests/ -v

# 4. 서비스 재시작 (또는 /restart)
systemctl --user restart axnmihn-backend

# 5. 헬스체크
curl http://localhost:8000/health

# 6. 기본 기능 테스트
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{"model":"gemini","messages":[{"role":"user","content":"테스트"}]}'
```

### 성능 문제 발생 시

```bash
# 1. 어떤 서비스가 느린지 확인
systemctl --user status axnmihn-backend axnmihn-mcp axnmihn-research axnmihn-tts --no-pager | grep -E "Memory|CPU"

# 2. 시스템 전체 리소스
htop  # 또는 top

# 3. GPU 사용률
nvidia-smi

# 4. 디스크 I/O
iostat -x 1 5

# 5. 네트워크 연결 수
ss -s

# 6. 느린 쿼리/요청 로그
grep -i "slow\|timeout" ~/projects/axnmihn/logs/backend.log | tail -20
```

### 메모리 문제 해결

```bash
# 1. 메모리 상태 확인
free -h

# 2. 메모리 많이 쓰는 프로세스
ps aux --sort=-%mem | head -10

# 3. 서비스별 메모리 사용량
systemctl --user status axnmihn-backend axnmihn-mcp axnmihn-research axnmihn-tts context7-mcp markitdown-mcp --no-pager | grep Memory

# 4. 메모리 GC 실행
cd ~/projects/axnmihn && source ~/projects-env/bin/activate
python scripts/memory_gc.py check    # 상태 확인
python scripts/memory_gc.py cleanup  # 정리

# 5. Python 캐시 정리
find ~/projects/axnmihn -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null

# 6. 서비스 재시작 (메모리 해제)
systemctl --user restart axnmihn-backend axnmihn-mcp axnmihn-research
```

### 새 기능 추가 후

```bash
# 1. 의존성 설치
source ~/projects-env/bin/activate
pip install -r backend/requirements.txt

# 2. DB 마이그레이션 (필요시)
python scripts/run_migrations.py apply

# 3. 서비스 재시작
systemctl --user restart axnmihn-backend

# 4. 로그 모니터링
tail -f ~/projects/axnmihn/logs/backend.log

# 5. 기능 테스트 후 커밋
git add .
git commit -m "feat: 새 기능 추가"
```

---

## 트러블슈팅 의사결정 트리

### 서비스가 응답하지 않음

```
서비스 응답 없음
    |
    +-- 포트 열려있나? --- lsof -i:8000
    |       |
    |       +-- 열려있음 ---- 프로세스 hang --> systemctl --user restart
    |       +-- 안 열림 ----- 서비스 죽음 --> journalctl --user -u axnmihn-backend -n 50
    |
    +-- 로그에 에러? ----- tail -50 ~/projects/axnmihn/logs/backend_error.log
    |       |
    |       +-- OOM (Out of Memory) --> 메모리 정리 후 재시작
    |       +-- DB Lock --> SQLite 락 해제 또는 재시작
    |       +-- Import Error --> pip install 누락 패키지
    |
    +-- 리소스 부족? ---- htop, df -h, nvidia-smi
            |
            +-- CPU 100% --> 무한루프 의심, 프로세스 종료
            +-- RAM 부족 --> 메모리 GC, 서비스 재시작
            +-- 디스크 풀 --> 로그/캐시 정리
            +-- GPU 메모리 --> GPU 프로세스 정리
```

### API 에러 응답

```
API 에러
    |
    +-- 400 Bad Request --- 요청 형식 오류 --> 파라미터 확인
    +-- 401 Unauthorized -- 인증 실패 --> AXNMIHN_API_KEY 확인
    +-- 404 Not Found ----- 엔드포인트 없음 --> URL 확인
    +-- 500 Internal ------ 서버 에러 --> 로그 확인
    |       |
    |       +-- Traceback 확인 (아래에서 위로 읽기)
    |       +-- 최근 코드 변경 확인 (git diff)
    |       +-- 의존성 문제 확인 (pip list)
    |
    +-- 502/503/504 ------- 프록시/타임아웃 --> 백엔드 상태 확인
```

### MCP 연결 문제

```
MCP 연결 실패
    |
    +-- SSE 연결 안됨 ---- curl http://localhost:8555/sse
    |       |
    |       +-- Connection refused --> 서비스 시작 확인
    |       +-- 연결됨 but 응답 없음 --> 서비스 재시작
    |
    +-- 도구 호출 실패 --- 로그 확인
    |       |
    |       +-- Timeout --> 도구 실행 시간 초과
    |       +-- Invalid params --> 파라미터 형식 오류
    |       +-- Tool not found --> 도구 등록 확인 (MCP_DISABLED_TOOLS 확인)
    |
    +-- Claude Code 연결 -- .claude/settings.local.json 확인
            |
            +-- mcpServers 설정 확인
            +-- 포트/URL 일치 확인
```

### 메모리 관련 문제

```
메모리 문제
    |
    +-- 검색 결과 이상 --- ChromaDB 상태 확인
    |       |
    |       +-- 인덱스 손상 --> 재구축 필요 (data/chroma_db/ 확인)
    |       +-- 벡터 불일치 --> 임베딩 재생성
    |
    +-- 지식그래프 오류 -- data/knowledge_graph.json 확인
    |       |
    |       +-- JSON 파싱 실패 --> 백업에서 복원
    |       +-- 엔티티 중복 --> scripts/dedup_knowledge_graph.py 실행
    |
    +-- 대화 컨텍스트 ---- 최근 메시지 확인
            |
            +-- 컨텍스트 누락 --> 세션 ID 확인
            +-- 오래된 정보 --> 메모리 GC 실행 (scripts/memory_gc.py)
```

---

## Cron 자동화

### 현재 등록된 Cron 작업

| 스케줄 | 작업 | 설명 |
|--------|------|------|
| `0 4 * * *` | `cron_memory_gc.sh` | 메모리 GC - 매일 오전 4시 PST |
| `50 0-5 * * *` | `night_ops.py` | Night Shift - 0:50~5:50 PST (6회/일) |
| `0 0 * * *` | `logrotate` | 로그 로테이션 - 매일 자정 |

### Systemd Timer 작업

| 타이머 | 주기 | 설명 |
|--------|------|------|
| auto-cleanup.timer | 매주 1회 (랜덤 지연 1시간) | 주간 자동 정리 |
| axnmihn-mcp-reclaim.timer | 부팅 후 5분, 이후 10분마다 | MCP 메모리 캐시 회수 |
| context7-mcp-restart.timer | 6시간마다 | Context7 프로세스 릭 정리 |
| markitdown-mcp-restart.timer | 4시간마다 | Markitdown 프로세스 릭 정리 |
| claude-review.timer | 3시간마다 (랜덤 지연 5분) | 자동 코드 리뷰 |

### Cron 관리
```bash
crontab -l                      # 현재 cron 목록 확인
crontab -e                      # cron 편집 (nano 에디터)

# 타이머 확인
systemctl --user list-timers --all
```

---

## 유용한 원라이너

### 시스템 전체 상태
```bash
# 모든 서비스 상태 + 포트 + 디스크 한 번에
echo "=== Services ===" && systemctl --user status axnmihn-backend axnmihn-mcp axnmihn-research axnmihn-tts context7-mcp markitdown-mcp --no-pager | grep -E "●|Active|Memory" && echo "" && echo "=== Ports ===" && ss -tlnp | grep -E "8000|8002|8555|8766|3000|3001|3002|5432|6379|8123" && echo "" && echo "=== Disk ===" && df -h /home | tail -1
```

### 로그 검색
```bash
# 특정 에러 검색 (모든 로그에서)
grep -r "ERROR" ~/projects/axnmihn/logs/ --include="*.log" | tail -20

# 최근 1시간 에러만
find ~/projects/axnmihn/logs/ -name "*.log" -mmin -60 -exec grep -l "ERROR" {} \;

# 특정 request_id 추적
grep "request_id" ~/projects/axnmihn/logs/backend.log | tail -10
```

### 디스크 정리
```bash
# Python 캐시 정리
find ~/projects/axnmihn -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null

# pip 캐시 정리
pip cache purge

# 오래된 로그 수동 정리 (7일 이상)
find ~/projects/axnmihn/logs/ -name "*.log.*" -mtime +7 -delete

# 저널 로그 정리
journalctl --user --vacuum-size=500M
```

### 프로세스 디버깅
```bash
# 관련 모든 프로세스
pgrep -af "axnmihn|backend|mcp_server|research_server|tts_service"

# 메모리 많이 쓰는 프로세스 top 10
ps aux --sort=-%mem | head -11

# 파일 디스크립터 확인 (너무 많으면 문제)
ls /proc/$(pgrep -f "backend.app")/fd | wc -l
```

### 빠른 복구
```bash
# 백엔드 + MCP 전체 재시작 (한 줄)
systemctl --user restart axnmihn-backend axnmihn-mcp axnmihn-research && sleep 3 && systemctl --user status axnmihn-backend axnmihn-mcp axnmihn-research --no-pager | grep -E "●|Active"

# 좀비 Python 프로세스 정리 후 재시작
pkill -f uvicorn; pkill -f mcp_server; sleep 2; systemctl --user restart axnmihn-backend axnmihn-mcp axnmihn-research
```

---

## 백업 & 복구

### 핵심 데이터 위치

| 데이터 | 경로 | 설명 |
|--------|------|------|
| SQLite DB | `data/sqlite/sqlite_memory.db` | 세션, 메시지, 인터랙션 로그 |
| ChromaDB | `data/chroma_db/` | 벡터 임베딩 (장기 기억) |
| 지식그래프 | `data/knowledge_graph.json` | 엔티티, 관계 (JSON) |
| 워킹 메모리 | `data/working_memory.json` | 현재 대화 버퍼 |
| 페르소나 | `data/dynamic_persona.json` | AI 페르소나 설정 |
| 리서치 결과 | `storage/research/` | 딥 리서치 아티팩트 |
| 로그 | `logs/` | 서비스 로그 |
| 환경변수 | `.env` | API 키, 설정 |

### 수동 백업

```bash
# 백업 디렉토리 생성
BACKUP_DIR=~/backups/axnmihn/$(date +%Y%m%d)
mkdir -p $BACKUP_DIR

# 1. SQLite DB 백업 (안전한 방법)
sqlite3 ~/projects/axnmihn/data/sqlite/sqlite_memory.db ".backup '$BACKUP_DIR/sqlite_memory.db'"

# 2. 지식그래프 백업 (JSON 파일)
cp ~/projects/axnmihn/data/knowledge_graph.json $BACKUP_DIR/

# 3. ChromaDB 백업 (디렉토리 복사)
cp -r ~/projects/axnmihn/data/chroma_db/ $BACKUP_DIR/chroma_db/

# 4. 페르소나 & 워킹 메모리 백업
cp ~/projects/axnmihn/data/dynamic_persona.json $BACKUP_DIR/
cp ~/projects/axnmihn/data/working_memory.json $BACKUP_DIR/

# 5. 설정 파일 백업
cp ~/projects/axnmihn/.env $BACKUP_DIR/
cp -r ~/.claude/ $BACKUP_DIR/claude-config/

# 6. 리서치 아티팩트 백업 (선택)
cp -r ~/projects/axnmihn/storage/research/ $BACKUP_DIR/research/

# 7. 백업 확인
ls -lh $BACKUP_DIR/
```

### 원라이너 전체 백업

```bash
# 서비스 중지 --> 백업 --> 재시작
systemctl --user stop axnmihn-backend axnmihn-mcp && \
BACKUP_DIR=~/backups/axnmihn/$(date +%Y%m%d) && mkdir -p $BACKUP_DIR && \
sqlite3 ~/projects/axnmihn/data/sqlite/sqlite_memory.db ".backup '$BACKUP_DIR/sqlite_memory.db'" && \
cp ~/projects/axnmihn/data/knowledge_graph.json $BACKUP_DIR/ && \
cp -r ~/projects/axnmihn/data/chroma_db/ $BACKUP_DIR/chroma_db/ && \
cp ~/projects/axnmihn/data/dynamic_persona.json $BACKUP_DIR/ && \
cp ~/projects/axnmihn/.env $BACKUP_DIR/ && \
systemctl --user start axnmihn-backend axnmihn-mcp && \
echo "Backup completed: $BACKUP_DIR"
```

### 복구

```bash
# 1. 서비스 중지
systemctl --user stop axnmihn-backend axnmihn-mcp axnmihn-research

# 2. 기존 데이터 백업 (안전을 위해)
mv ~/projects/axnmihn/data/sqlite/sqlite_memory.db ~/projects/axnmihn/data/sqlite/sqlite_memory.db.old

# 3. 백업에서 복구
BACKUP_DIR=~/backups/axnmihn/20260210  # 원하는 백업 날짜
cp $BACKUP_DIR/sqlite_memory.db ~/projects/axnmihn/data/sqlite/
cp $BACKUP_DIR/knowledge_graph.json ~/projects/axnmihn/data/
rm -rf ~/projects/axnmihn/data/chroma_db/
cp -r $BACKUP_DIR/chroma_db/ ~/projects/axnmihn/data/
cp $BACKUP_DIR/dynamic_persona.json ~/projects/axnmihn/data/

# 4. 서비스 재시작
systemctl --user start axnmihn-backend axnmihn-mcp axnmihn-research

# 5. 확인
curl http://localhost:8000/health
```

### 정기 백업 설정 (cron 예시)

```bash
# crontab -e로 추가
# 매일 새벽 3시에 백업
0 3 * * * BACKUP_DIR=~/backups/axnmihn/$(date +\%Y\%m\%d) && mkdir -p $BACKUP_DIR && sqlite3 ~/projects/axnmihn/data/sqlite/sqlite_memory.db ".backup '$BACKUP_DIR/sqlite_memory.db'" 2>/dev/null

# 오래된 백업 정리 (30일 이상)
0 4 * * * find ~/backups/axnmihn/ -type d -mtime +30 -exec rm -rf {} + 2>/dev/null
```

### 긴급 복구: Git에서 코드 복구

```bash
# 최근 작동하던 상태로 코드 복구
git log --oneline -10           # 최근 커밋 확인
git checkout <commit-hash>      # 특정 커밋으로 이동

# 또는 최근 N개 커밋 전으로
git reset --hard HEAD~3         # 3개 커밋 전으로 (위험!)

# 서비스 재시작
systemctl --user restart axnmihn-backend axnmihn-mcp axnmihn-research
```

---

## 인프라 서비스 관리

PostgreSQL 17 + pgvector와 Redis는 user-level systemd 서비스로 운영한다.

### 데이터 디렉토리

```
~/services/
├── postgres/
│   ├── data/          # PostgreSQL 데이터
│   └── log/           # postgres.log, postgres_error.log
└── redis/
    ├── redis.conf     # Redis 설정
    ├── data/          # dump.rdb
    └── log/           # redis.log, redis_error.log
```

### 기본 운용

```bash
# 상태 확인
systemctl --user status axnmihn-postgres axnmihn-redis --no-pager

# 시작/중지/재시작
systemctl --user start axnmihn-postgres
systemctl --user stop axnmihn-redis
systemctl --user restart axnmihn-postgres

# 로그 확인
journalctl --user -u axnmihn-postgres --no-pager -n 50
tail -n 50 ~/services/postgres/log/postgres.log
tail -n 50 ~/services/redis/log/redis.log
```

### PostgreSQL 관리

```bash
# psql 접속
psql -h localhost -U axel axel

# DB 크기 확인
psql -h localhost -U axel axel -c "SELECT pg_size_pretty(pg_database_size('axel'));"

# 테이블 목록
psql -h localhost -U axel axel -c "\dt"

# pgvector 확장 확인
psql -h localhost -U axel axel -c "SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';"

# DB 백업
pg_dump -h localhost -U axel -Fc axel > backup_$(date +%Y%m%d).custom

# DB 복원
pg_restore -h localhost -U axel -d axel --no-owner backup_20260211.custom
```

### Redis 관리

```bash
# Redis 접속
redis-cli -p 6379

# 메모리 사용량
redis-cli -p 6379 info memory | grep used_memory_human

# 키 개수
redis-cli -p 6379 dbsize

# 전체 초기화 (주의)
redis-cli -p 6379 FLUSHALL
```

### 설정 파일

| 파일 | 위치 |
|------|------|
| PostgreSQL 설정 | `~/services/postgres/data/postgresql.conf` |
| PostgreSQL 인증 | `~/services/postgres/data/pg_hba.conf` |
| Redis 설정 | `~/services/redis/redis.conf` |
| PostgreSQL systemd | `~/.config/systemd/user/axnmihn-postgres.service` |
| Redis systemd | `~/.config/systemd/user/axnmihn-redis.service` |

### 트러블슈팅

```
인프라 서비스 문제
    |
    +-- PostgreSQL 안 뜸 --- journalctl --user -u axnmihn-postgres -n 50
    |       |
    |       +-- "could not bind" --> 포트 5432 충돌 (lsof -i:5432)
    |       +-- "data directory has wrong ownership" --> 퍼미션 확인
    |       +-- "shared memory" --> shared_buffers 설정 확인
    |
    +-- Redis 안 뜸 --- journalctl --user -u axnmihn-redis -n 50
    |       |
    |       +-- "Can't handle RDB format" --> dump.rdb 삭제 후 재시작
    |       +-- "Address already in use" --> 포트 6379 충돌
    |
    +-- 연결 거부 (앱에서)
            |
            +-- PostgreSQL: psql -h localhost -U axel axel -c "SELECT 1;"
            +-- Redis: redis-cli -p 6379 PING
            +-- 서비스 상태 확인: systemctl --user status axnmihn-postgres axnmihn-redis
```

---

## 응급 상황 대응

### 백엔드가 안 뜰 때
```bash
# 1. 로그 확인 (user service)
journalctl --user -u axnmihn-backend -n 100
tail -n 100 ~/projects/axnmihn/logs/backend_error.log

# 2. 포트 확인
lsof -i:8000

# 3. 좀비 프로세스 정리
pkill -f uvicorn
pkill -f "backend.app"

# 4. 재시작 (user service - sudo 불필요)
systemctl --user restart axnmihn-backend
```

### start-limit-hit (재시작 제한 초과)

> 짧은 시간 내 반복 실패 시 systemd가 추가 시작을 차단함
> 현재 설정: **1분 이내 5회 실패 시 차단** (`StartLimitIntervalSec=60`, `StartLimitBurst=5`)

```bash
# 1. 상태 확인 -- "start-limit-hit" 메시지가 보이는지 확인
systemctl --user status axnmihn-backend

# 2. 실패 카운터 초기화
systemctl --user reset-failed axnmihn-backend

# 3. 서비스 시작
systemctl --user start axnmihn-backend

# 4. 헬스체크
curl -sf http://localhost:8000/health
```

### 포트 충돌 (Address already in use)
```bash
lsof -i:8000              # 누가 쓰고 있는지 확인
kill -9 PID               # 해당 프로세스 종료
```

### 서비스 hang
```bash
systemctl --user stop axnmihn-backend
sleep 2
systemctl --user start axnmihn-backend
```

### 디스크 꽉 찼을 때
```bash
# 1. 큰 파일 찾기
du -sh /home/northprot/* | sort -h | tail -20

# 2. 로그 정리
journalctl --user --vacuum-size=500M
sudo journalctl --vacuum-size=500M

# 3. Python 캐시 정리
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null

# 4. pip 캐시 정리
pip cache purge

# 5. 오래된 리서치 아티팩트 정리
find ~/projects/axnmihn/storage/research/artifacts -mtime +30 -delete

# 6. 오래된 크론 리포트 정리
find ~/projects/axnmihn/storage/cron/reports -mtime +30 -delete
```

### 변경사항 되돌리기
```bash
git checkout -- file.txt       # 커밋 안 한 변경 취소
git checkout -- .              # 모든 변경 취소 (위험!)
git reset --hard HEAD          # 마지막 커밋으로 완전 복구 (더 위험!)
```

### 시스템 재부팅 (최후의 수단)
```bash
sudo reboot
```

---

## 빠른 참조 카드

### Claude Code 슬래시 명령어

| 상황 | 명령어 |
|------|--------|
| 서비스 재시작 | `/restart` |
| 에러 로그 | `/logs error` |
| 경고 로그 | `/logs warn` |
| 서비스 상태 | `/services` |
| 에러 분석 | `/analyze-error` |
| 모델 설정 확인 | `/model-check` |
| 캐시 정리 | `/purge-cache` |
| 코드 건강 검진 | `/code-health` |
| 보안 스캔 | `/security` |
| 의존성 확인 | `/deps` |

### 터미널 명령어

| 상황 | 명령어 |
|------|--------|
| 어디있지? | `pwd` |
| 뭐있지? | `ls -la` |
| 포트 누가 쓰지? | `lsof -i:8000` |
| 로그 보기 | `tail -f ~/projects/axnmihn/logs/backend.log` |
| 서비스 재시작 | `systemctl --user restart axnmihn-backend` |
| 전체 재시작 | `systemctl --user restart axnmihn-backend axnmihn-mcp axnmihn-research` |
| 전체 상태 | `systemctl --user status axnmihn-backend axnmihn-mcp axnmihn-research axnmihn-tts --no-pager` |
| 타이머 목록 | `systemctl --user list-timers` |
| Git 상태 | `git status` |
| venv 활성화 | `source ~/projects-env/bin/activate` |
| 프로세스 죽이기 | `kill -9 PID` |
| GPU 상태 | `nvidia-smi` |
| 디스크 확인 | `df -h /home` |
| cron 확인 | `crontab -l` |
| Docker 상태 | `docker compose ps` |
| 빠른 백업 | `sqlite3 ~/projects/axnmihn/data/sqlite/sqlite_memory.db ".backup ~/backups/quick.db"` |

---

## 절대 하지 말 것

| 명령어 | 위험도 | 이유 |
|--------|--------|------|
| `rm -rf /` | CRITICAL | 시스템 전체 삭제 |
| `rm -rf ~` | CRITICAL | 홈 디렉토리 삭제 |
| `chmod 777` | HIGH | 보안 취약점 (모든 권한 오픈) |
| `pip install` (venv 없이) | MEDIUM | 시스템 Python 오염 |
| `git push -f` | HIGH | 원격 히스토리 덮어씀 |
| `docker compose down -v` | HIGH | DB 볼륨 포함 삭제 |

---

## 수정 전 체크리스트

- [ ] `git status`로 현재 상태 확인
- [ ] 수정할 파일 백업 (큰 변경 시)
- [ ] 가상환경 활성화 확인 (`which python`)
- [ ] 서비스 중지 (`systemctl --user stop axnmihn-backend`)
- [ ] 수정 후 문법 검사 (`python -m py_compile`)
- [ ] 테스트 실행 (`pytest tests/ -v`)
- [ ] 서비스 재시작
- [ ] 헬스체크 (`curl http://localhost:8000/health`)

---

> **문제가 생기면:**
> 1. 에러 메시지를 **그대로** 읽어라
> 2. 로그를 확인해라
> 3. 구글에 에러 메시지 복붙
> 4. Python traceback은 **아래에서 위로** 읽음 (가장 아래 줄이 실제 에러)

*"차분하게, 하나씩, 확인하면서."*
