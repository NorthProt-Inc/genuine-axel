import os
import sys
from pathlib import Path
from datetime import datetime
import time
import re

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

import httpx

from backend.config import CRON_REPORTS_DIR, CRON_LOG_PATH, HOST, PORT

API_URL = os.getenv("AXEL_API_URL", f"http://{HOST}:{PORT}")
API_KEY = os.getenv("AXNMIHN_API_KEY") or os.getenv("API_KEY")
REPORTS_DIR = CRON_REPORTS_DIR
SUMMARY_LOG = CRON_LOG_PATH

REQUEST_TIMEOUT = 300.0
MAX_RETRIES = 3
RETRY_DELAY = 60

NIGHT_QUERIES = [
    "2026 아무거나"
]

# 시간대 기반 쿼리 선택
hour = datetime.now().hour
query = NIGHT_QUERIES[hour % len(NIGHT_QUERIES)]

NIGHT_SHIFT_PROMPT = f"""다음 주제를 조사: {query}

오푸스가 프롬프트 거지같이 써놔서 루트 어드민 이종민이 직접 편집한다. 걍 맘대로 휘집고 놀아ㅋㅋ.
아 참고로 이거 night_ops.py 후속작임. 구글 딥리서치는 이제 비싸니까 네가 하는걸로 하자고. 알다시피 크론잡이고 난 자는 중이다.

[AXEL_SUMMARY_START] 와 [AXEL_SUMMARY_END] 태그 사이에 요약."""

def log(message: str) -> None:

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}", flush=True)

def ensure_reports_dir() -> None:

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

def get_headers() -> dict:

    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"
    return headers

def call_axel_api(prompt: str) -> str | None:

    endpoint = f"{API_URL}/v1/chat/completions"
    payload = {
        "model": "axel-pro",
        "messages": [{"role": "user", "content": prompt}],
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            log(f"Attempt {attempt}/{MAX_RETRIES}: Calling Axel at {endpoint}")

            with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
                response = client.post(endpoint, headers=get_headers(), json=payload)
                response.raise_for_status()

            data = response.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")

            if content:
                log(f"Received response ({len(content)} chars)")
                return content
            else:
                log("Warning: Empty response content")

        except httpx.TimeoutException:
            log(f"Timeout after {REQUEST_TIMEOUT}s")
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            text = e.response.text[:500] if e.response.text else "No body"
            log(f"HTTP {status}: {text}")

            if status == 429:
                log("Rate limited. Waiting 120s before retry...")
                time.sleep(120)
        except Exception as e:
            log(f"Error: {type(e).__name__}: {e}")

        if attempt < MAX_RETRIES:
            log(f"Retrying in {RETRY_DELAY}s...")
            time.sleep(RETRY_DELAY)

    log("All attempts failed")
    return None

def extract_summary(content: str) -> str:

    summary_match = re.search(
        r'\[AXEL_SUMMARY_START\](.*?)\[AXEL_SUMMARY_END\]',
        content,
        re.DOTALL
    )
    if summary_match:
        return summary_match.group(1).strip()

    return content

def save_summary(axel_summary: str, timestamp: datetime) -> Path:

    time_str = timestamp.strftime('%Y%m%d_%H00')
    filename = f"report_{time_str}_summary.md"
    filepath = REPORTS_DIR / filename

    content = f"""# Night Shift Report - Axel Summary
**Generated:** {timestamp.strftime('%Y-%m-%d %H:%M:%S')} (Vancouver Time)
**Author:** Axel (Co-founder AI)

---

{axel_summary}
"""
    filepath.write_text(content, encoding="utf-8")
    log(f"Saved summary: {filepath}")

    return filepath

def extract_brief_summary(content: str) -> str:

    lines = content.strip().split('\n')
    for line in lines:
        line = line.strip()
        if line and not line.startswith('#') and len(line) > 20:
            return line[:200] + ('...' if len(line) > 200 else '')
    return content[:200] + ('...' if len(content) > 200 else '')

def update_summary_log(axel_summary: str, timestamp: datetime) -> None:

    brief = extract_brief_summary(axel_summary)

    entry = f"""
## {timestamp.strftime('%Y-%m-%d %H:%M')}
{brief}

---
"""

    if not SUMMARY_LOG.exists():
        SUMMARY_LOG.write_text("# Night Shift Summary Log\n\n", encoding="utf-8")

    with open(SUMMARY_LOG, "a", encoding="utf-8") as f:
        f.write(entry)

    log(f"Updated summary log: {SUMMARY_LOG}")

def main() -> int:

    log("=" * 60)
    log("NIGHT SHIFT DAEMON ACTIVATED")
    log("Engine: Axel Backend + Free Deep Research (DuckDuckGo)")
    log("=" * 60)

    ensure_reports_dir()
    timestamp = datetime.now()

    log("Sending Night Shift Protocol prompt to Axel...")
    response = call_axel_api(NIGHT_SHIFT_PROMPT)

    if not response:
        log("FAILED: No response from Axel")
        return 1

    axel_summary = extract_summary(response)
    log(f"Extracted summary: {len(axel_summary)} chars")

    save_summary(axel_summary, timestamp)

    update_summary_log(axel_summary, timestamp)

    log("Night Shift cycle complete")
    log("=" * 60)
    return 0

if __name__ == "__main__":
    sys.exit(main())
