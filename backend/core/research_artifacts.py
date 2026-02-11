import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urlparse
from backend.core.logging import get_logger
from backend.config import RESEARCH_ARTIFACTS_DIR, PROJECT_ROOT

_log = get_logger("core.research")

ARTIFACT_THRESHOLD = 2000
ARTIFACTS_DIR = RESEARCH_ARTIFACTS_DIR
MAX_SUMMARY_LINES = 5
MAX_SUMMARY_CHARS = 500

def should_save_as_artifact(content: str) -> bool:
    if not content:
        return False
    return len(content) > ARTIFACT_THRESHOLD

def generate_summary(content: str, max_lines: int = MAX_SUMMARY_LINES) -> str:
    if not content:
        return "No content"

    lines = []

    title = ""
    for line in content.split('\n'):
        line = line.strip()
        if not line:
            continue

        if line.startswith('#'):
            title = line.lstrip('#').strip()
            break

        if not title:
            title = line[:100]
            break

    if title:
        lines.append(f"Title: {title}")

    paragraphs = re.split(r'\n\n+', content)
    point_count = 0

    for para in paragraphs:
        para = para.strip()
        if not para or len(para) < 50:
            continue
        if para.startswith('#'):
            continue
        if para.startswith('**') and para.endswith('**'):
            continue
        if para.startswith('[') or para.startswith('!['):
            continue

        first_sentence = para.split('.')[0]
        if len(first_sentence) > 100:
            first_sentence = first_sentence[:97] + "..."
        else:
            first_sentence += "."

        lines.append(f"- {first_sentence}")
        point_count += 1

        if point_count >= max_lines - 1:
            break

    summary = '\n'.join(lines)

    if len(summary) > MAX_SUMMARY_CHARS:
        summary = summary[:MAX_SUMMARY_CHARS - 3] + "..."

    return summary if summary else "Content summary unavailable"

def _sanitize_filename(url: str) -> str:
    parsed = urlparse(url)
    domain = parsed.netloc.replace('.', '-').replace(':', '-')

    url_hash = hashlib.md5(url.encode()).hexdigest()[:8]

    timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")

    filename = f"{timestamp}_{domain}_{url_hash}.md"

    filename = re.sub(r'[^\w\-.]', '_', filename)

    return filename

def save_artifact(url: str, content: str) -> Tuple[Path, str]:
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

    filename = _sanitize_filename(url)
    filepath = ARTIFACTS_DIR / filename

    summary = generate_summary(content)

    artifact_content = f"""---
source: {url}
saved_at: {datetime.now().isoformat()}
content_length: {len(content)}
---

{content}
"""

    try:
        filepath.write_text(artifact_content, encoding='utf-8')
        _log.info("Artifact saved", path=str(filepath), chars=len(content), url=url[:50])
    except Exception as e:
        _log.error("Failed to save artifact", error=str(e), url=url[:50])
        raise

    return filepath, summary

def create_artifact_reference(url: str, filepath: Path, summary: str) -> str:
    relative_path = str(filepath)

    return f"""[ARTIFACT SAVED]
- Source: {url}
- Path: {relative_path}
- Summary:
{summary}

Use `read_artifact` tool with path="{relative_path}" if detailed content needed."""

def read_artifact(filepath: str) -> Optional[str]:
    try:
        path = Path(filepath)

        if not path.is_absolute():

            if not path.exists():

                path = PROJECT_ROOT / filepath

        if not path.exists():
            _log.warning("Artifact not found", path=str(filepath))
            return None

        content = path.read_text(encoding='utf-8')

        if content.startswith('---'):
            parts = content.split('---', 2)
            if len(parts) >= 3:
                content = parts[2].strip()

        _log.info("Artifact read", path=str(filepath), chars=len(content))
        return content

    except Exception as e:
        _log.error("Failed to read artifact", path=str(filepath), error=str(e))
        return None

def process_content_for_artifact(url: str, content: str) -> str:
    if not should_save_as_artifact(content):
        return content

    try:
        filepath, summary = save_artifact(url, content)
        return create_artifact_reference(url, filepath, summary)
    except Exception as e:
        _log.error("Artifact processing failed, returning truncated content", error=str(e))

        return content[:ARTIFACT_THRESHOLD] + f"\n\n[Content truncated at {ARTIFACT_THRESHOLD} chars due to artifact save failure]"

def list_artifacts(limit: int = 20) -> list[dict]:
    """List artifacts, reading only metadata header instead of full file."""
    if not ARTIFACTS_DIR.exists():
        return []

    artifacts = []

    for file_path in sorted(ARTIFACTS_DIR.glob("*.md"), reverse=True)[:limit]:
        try:
            # Read only first ~500 chars for metadata instead of entire file
            with open(file_path, 'r', encoding='utf-8') as f:
                header = f.read(500)

            url = ""
            saved_at = ""

            if header.startswith('---'):
                parts = header.split('---', 2)
                if len(parts) >= 2:
                    metadata = parts[1]
                    for line in metadata.split('\n'):
                        if line.startswith('source:'):
                            url = line.replace('source:', '').strip()
                        elif line.startswith('saved_at:'):
                            saved_at = line.replace('saved_at:', '').strip()

            artifacts.append({
                'path': str(file_path),
                'url': url,
                'saved_at': saved_at,
                'size': file_path.stat().st_size
            })
        except Exception:
            continue

    return artifacts
