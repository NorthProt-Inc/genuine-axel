import os
from pathlib import Path
from typing import Optional, Tuple

AXEL_ROOT = Path(__file__).parent.parent.parent.parent.resolve()

OPUS_ALLOWED_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".yaml", ".yml",
    ".md", ".txt", ".html", ".css", ".scss", ".sql", ".sh", ".bash",
    ".env.example", ".toml", ".cfg", ".ini",
}
OPUS_MAX_FILE_SIZE = 500 * 1024        # 500KB
OPUS_MAX_FILES = 20
OPUS_MAX_TOTAL_CONTEXT = 1024 * 1024   # 1MB


def validate_opus_file_path(file_path: str) -> Tuple[bool, Optional[Path], Optional[str]]:
    """Validate file path for Opus delegation.

    Returns:
        (valid, resolved_path, error_message)
    """
    try:
        if not os.path.isabs(file_path):
            resolved = (AXEL_ROOT / file_path).resolve()
        else:
            resolved = Path(file_path).resolve()

        try:
            resolved.relative_to(AXEL_ROOT)
        except ValueError:
            return False, None, f"Path '{file_path}' is outside project root"

        if not resolved.exists():
            return False, None, f"File not found: {file_path}"

        if not resolved.is_file():
            return False, None, f"Not a file: {file_path}"

        if resolved.suffix.lower() not in OPUS_ALLOWED_EXTENSIONS:
            return False, None, f"File extension not allowed: {resolved.suffix}"

        if resolved.stat().st_size > OPUS_MAX_FILE_SIZE:
            return False, None, f"File too large (>{OPUS_MAX_FILE_SIZE // 1024}KB): {file_path}"

        return True, resolved, None

    except Exception as e:
        return False, None, f"Path validation error: {str(e)}"


def read_opus_file_content(file_path: Path) -> str:
    try:
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            return f.read()
    except Exception as e:
        return f"[Error reading file: {str(e)}]"
