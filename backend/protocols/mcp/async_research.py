import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional, Literal
from backend.core.logging import get_logger
from backend.config import RESEARCH_INBOX_DIR, RESEARCH_LOG_PATH, PROJECT_ROOT

_log = get_logger("protocols.async_research")

INTERN_ANALYSIS_PROMPT = """리서치 인턴으로서 원본 데이터를 분석해 핵심만 추출해.

규칙:
- 미사여구, 과장, "흥미로운 기회" 같은 표현 금지
- 데이터가 부족하거나 추측이면 솔직하게 말해
- 한국어로 출력

출력 형식 (정확히 따라):

## 분석: [주제 5단어 이내]

### 한줄 요약
[추진할 가치 있음/없음/애매함 + 이유 1문장]

### 핵심 인사이트 3개

1. **[제목]**
   - 팩트: [데이터가 실제로 말하는 것]
   - 액션: [구체적 다음 단계]
   - 리스크: [잘못될 수 있는 것]

2. **[제목]**
   - 팩트: [데이터가 실제로 말하는 것]
   - 액션: [구체적 다음 단계]
   - 리스크: [잘못될 수 있는 것]

3. **[제목]**
   - 팩트: [데이터가 실제로 말하는 것]
   - 액션: [구체적 다음 단계]
   - 리스크: [잘못될 수 있는 것]

### 주의사항
[우려점, 데이터 공백, 회의적 이유 나열. 없으면 "없음"]

---
원본 데이터:
"""

_active_tasks: dict[str, asyncio.Task] = {}

def get_active_research_tasks() -> list[dict]:
    """Get list of active background research tasks.

    Returns:
        List of task info dicts with task_id, done, cancelled
    """
    return [
        {
            "task_id": tid,
            "done": task.done(),
            "cancelled": task.cancelled(),
        }
        for tid, task in list(_active_tasks.items())
    ]

async def _analyze_findings(
    query: str,
    raw_report: str,
    source: Literal["google", "deep_dive"]
) -> str:
    """Analyze raw research data with LLM intern analysis.

    Args:
        query: Original research query
        raw_report: Raw research output
        source: Research source type

    Returns:
        Formatted analysis markdown
    """
    try:
        from backend.core.utils.gemini_client import gemini_generate
        from google.genai import types
        from backend.config import DEFAULT_THINKING_LEVEL

        config = types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(
                include_thoughts=True,
                thinking_level=DEFAULT_THINKING_LEVEL,  # type: ignore[arg-type]
            ),
        )
        response = await gemini_generate(
            contents=f"{INTERN_ANALYSIS_PROMPT}\n\n{raw_report}",
            config=config,
            timeout_seconds=180.0,
        )

        analysis = response.text if hasattr(response, 'text') else str(response)
        _log.info("Intern analysis completed", query=query[:50], analysis_len=len(analysis or ""))
        return analysis or ""

    except Exception as e:
        _log.error("Intern analysis failed", error=str(e), query=query[:50])
        return f"## Analysis Failed\n\nError: {str(e)}\n\nRaw report saved for manual review."

async def _save_report(
    query: str,
    raw_report: str,
    analysis: str,
    source: str,
    execution_time: float
) -> Path:
    """Save research report to inbox directory.

    Args:
        query: Research query
        raw_report: Raw research output
        analysis: LLM analysis result
        source: Research source type
        execution_time: Total execution time in seconds

    Returns:
        Path to saved report file
    """
    RESEARCH_INBOX_DIR.mkdir(parents=True, exist_ok=True)

    date_str = datetime.now().strftime("%Y-%m-%d_%H%M%S")

    words = query.split()[:5]
    keywords = "_".join(
        "".join(c for c in w if c.isalnum() or '\uac00' <= c <= '\ud7a3')
        for w in words if len(w) > 2
    )[:40]
    filename = f"{date_str}_{keywords}.md"
    filepath = RESEARCH_INBOX_DIR / filename

    report_content = f"""---
query: {query}
source: {source}
timestamp: {datetime.now().isoformat()}
execution_time_seconds: {execution_time:.2f}
status: completed
---

{analysis}

---

## Raw Research Data

<details>
<summary>Click to expand raw research output ({len(raw_report):,} chars)</summary>

{raw_report}

</details>
"""

    await asyncio.to_thread(filepath.write_text, report_content, encoding="utf-8")
    _log.info("Report saved", path=str(filepath), chars=len(report_content))

    return filepath

async def _append_to_research_log(
    query: str,
    source: str,
    report_path: Optional[Path],
    execution_time: float,
    success: bool
) -> None:
    """Append entry to research log file.

    Args:
        query: Research query
        source: Research source type
        report_path: Path to saved report
        execution_time: Execution time in seconds
        success: Whether research succeeded
    """
    try:
        # Initialize log file if it doesn't exist
        if not RESEARCH_LOG_PATH.exists():
            RESEARCH_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(
                RESEARCH_LOG_PATH.write_text,
                "# Research Log\n\n| Timestamp | Status | Source | Query | Report | Time |\n|-----------|--------|--------|-------|--------|------|\n",
                encoding="utf-8"
            )

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        status = "✅" if success else "❌"

        if report_path and report_path.is_absolute() and str(PROJECT_ROOT) in str(report_path):
            try:
                relative_path = str(report_path.relative_to(PROJECT_ROOT))
            except ValueError:
                relative_path = "N/A"
        else:
            relative_path = "FAILED" if not success else "N/A"

        entry = f"| {timestamp} | {status} | {source} | {query[:40]}... | `{relative_path}` | {execution_time:.1f}s |\n"

        # Append entry asynchronously
        def _append():
            with RESEARCH_LOG_PATH.open("a", encoding="utf-8") as f:
                f.write(entry)

        await asyncio.to_thread(_append)

        _log.debug("Research log updated", query=query[:30])

    except Exception as e:
        _log.warning("Failed to update research log", error=str(e))

async def _run_research_pipeline(
    query: str,
    source: Literal["google"],
    depth: Optional[int] = None,
    task_id: str = ""
) -> None:
    """Execute full research pipeline: fetch, analyze, save.

    Args:
        query: Research query
        source: Research source type
        depth: Research depth (1-5)
        task_id: Unique task identifier
    """
    import time
    start_time = time.time()

    _log.info(
        "Background research started",
        task_id=task_id,
        query=query[:50],
        source=source,
        depth=depth
    )

    try:

        from backend.protocols.mcp.google_research import google_deep_research
        raw_report = await google_deep_research(query, depth or 3)

        execution_time = time.time() - start_time

        if raw_report.startswith("Error:") or raw_report.startswith("## Research Failed"):
            _log.warning(
                "Research returned error",
                task_id=task_id,
                error=raw_report[:200]
            )
            await _append_to_research_log(query, source, None, execution_time, False)
            return

        _log.info(
            "Research phase complete",
            task_id=task_id,
            raw_len=len(raw_report),
            dur_ms=int(execution_time * 1000)
        )

        analysis = await _analyze_findings(query, raw_report, source)

        report_path = await _save_report(
            query=query,
            raw_report=raw_report,
            analysis=analysis,
            source=source,
            execution_time=execution_time
        )

        await _append_to_research_log(query, source, report_path, execution_time, True)

        total_time = time.time() - start_time
        _log.info(
            "Pipeline complete",
            task_id=task_id,
            query=query[:50],
            report_path=str(report_path),
            dur_ms=int(total_time * 1000)
        )

    except Exception as e:
        execution_time = time.time() - start_time
        _log.error(
            "Pipeline failed",
            task_id=task_id,
            error=str(e),
            query=query[:50],
            dur_ms=int(execution_time * 1000)
        )
        await _append_to_research_log(query, source, None, execution_time, False)

    finally:
        _active_tasks.pop(task_id, None)

def dispatch_async_research(
    query: str,
    source: Literal["google"] = "google",
    depth: Optional[int] = None
) -> str:
    """Dispatch research task to background.

    Args:
        query: Research query
        source: Research source type
        depth: Research depth (1-5)

    Returns:
        Status message with task ID and output locations
    """
    task_id = f"{source}_{datetime.now().strftime('%H%M%S')}"

    task = asyncio.create_task(
        _run_research_pipeline(query, source, depth, task_id)
    )

    _active_tasks[task_id] = task

    def _on_complete(t: asyncio.Task):
        try:
            exc = t.exception()
            if exc:
                _log.error("Background task exception", task_id=task_id, error=str(exc))
        except asyncio.CancelledError:
            _log.info("Background task cancelled", task_id=task_id)

    task.add_done_callback(_on_complete)

    _log.info(
        "Research dispatched to background",
        task_id=task_id,
        query=query[:50],
        source=source
    )

    return f"""Research task `{task_id}` started.

Query: {query[:100]}{'...' if len(query) > 100 else ''}
Results: storage/research/inbox/
Log: storage/research/log.md"""

async def run_research_sync(
    query: str,
    source: Literal["google"] = "google",
    depth: Optional[int] = None
) -> str:
    """Execute research synchronously and return result.

    Args:
        query: Research query
        source: Research source type
        depth: Research depth (1-5)

    Returns:
        Analysis with report path and execution time
    """
    import time
    start_time = time.time()

    from backend.protocols.mcp.google_research import google_deep_research
    raw_report = await google_deep_research(query, depth or 3)

    if raw_report.startswith("Error:") or raw_report.startswith("## Research Failed"):
        return raw_report

    analysis = await _analyze_findings(query, raw_report, source)

    execution_time = time.time() - start_time

    report_path = await _save_report(query, raw_report, analysis, source, execution_time)
    await _append_to_research_log(query, source, report_path, execution_time, True)

    return f"""{analysis}

---
📂 **Full report saved:** `{report_path.relative_to(PROJECT_ROOT)}`
⏱️ **Execution time:** {execution_time:.1f}s
"""
