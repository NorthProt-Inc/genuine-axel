"""Database backup utilities.

Provides pg_dump command generation and retention policy management.
"""

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse


@dataclass
class BackupConfig:
    """Configuration for database backup."""

    database_url: str
    output_dir: str = "/tmp/backups"
    format: str = "custom"


@dataclass
class RetentionPolicy:
    """Backup retention policy (count per period)."""

    daily: int = 7
    weekly: int = 4
    monthly: int = 3


def build_pg_dump_command(config: BackupConfig, filename: str) -> list[str]:
    """Build pg_dump command from config."""
    parsed = urlparse(config.database_url)

    fmt_flag = "-Fc" if config.format == "custom" else "-Fp"

    cmd = ["pg_dump"]

    if parsed.hostname:
        cmd.extend(["-h", parsed.hostname])
    if parsed.port:
        cmd.extend(["-p", str(parsed.port)])
    if parsed.username:
        cmd.extend(["-U", parsed.username])

    cmd.append(fmt_flag)

    db_name = parsed.path.lstrip("/") if parsed.path else ""
    if db_name:
        cmd.extend(["-d", db_name])

    output_path = f"{config.output_dir}/{filename}"
    cmd.extend(["-f", output_path])

    return cmd


def apply_retention_policy(
    backups: list[dict[str, Any]],
    policy: RetentionPolicy,
) -> dict[str, list]:
    """Apply retention policy to a list of backups.

    Args:
        backups: List of dicts with 'path' and 'created' (datetime) keys.
        policy: Retention policy to apply.

    Returns:
        Dict with 'to_keep' and 'to_delete' lists.
    """
    if not backups:
        return {"to_keep": [], "to_delete": []}

    sorted_backups = sorted(backups, key=lambda b: b["created"], reverse=True)

    to_keep = sorted_backups[: policy.daily]
    to_delete = sorted_backups[policy.daily:]

    return {"to_keep": to_keep, "to_delete": to_delete}
