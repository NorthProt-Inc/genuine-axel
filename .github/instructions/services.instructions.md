---
applyTo: "**"
---
# Service Operations

axnmihn systemd 서비스 운영 참고.

## 서비스 목록
| Service | Port | Description |
|---------|------|-------------|
| axnmihn-backend | 8000 | 메인 백엔드 |
| axnmihn-mcp | 8555 | MCP SSE 서버 |
| axnmihn-research | — | Research MCP |

## 주요 명령
```bash
# 상태 확인
systemctl --user status axnmihn-backend axnmihn-mcp --no-pager

# 재시작
systemctl --user restart axnmihn-backend

# 포트 확인
ss -tlnp | grep -E ":(8000|8555)"

# 헬스체크
curl -s http://localhost:8000/health | python3 -m json.tool

# 최근 로그
tail -n 50 logs/backend.log

# 프로세스 확인
pgrep -af "python.*(axnmihn|uvicorn|mcp)" | head -10
```
