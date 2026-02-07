"""Pytest fixtures for Opus shared module tests."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, "/home/northprot/projects/axnmihn")


# ── File validation mocks ────────────────────────────────────────────────────


@pytest.fixture
def mock_axel_root(tmp_path: Path) -> Path:
    """Temporary project root for path resolution."""
    return tmp_path


@pytest.fixture
def mock_validate_file_path(monkeypatch: pytest.MonkeyPatch):
    """Patches _validate_file_path used by build_context_block."""
    mock = MagicMock()
    monkeypatch.setattr(
        "backend.core.utils.opus_shared._validate_file_path",
        mock,
    )
    return mock


@pytest.fixture
def mock_read_file_content(monkeypatch: pytest.MonkeyPatch):
    """Patches _read_file_content used by build_context_block."""
    mock = MagicMock(return_value="file content here")
    monkeypatch.setattr(
        "backend.core.utils.opus_shared._read_file_content",
        mock,
    )
    return mock


# ── Subprocess mocks ─────────────────────────────────────────────────────────


@pytest.fixture
def mock_process():
    """Mock asyncio subprocess process."""
    process = AsyncMock()
    process.communicate = AsyncMock(return_value=(b"output", b""))
    process.returncode = 0
    process.kill = MagicMock()
    process.wait = AsyncMock()
    return process


@pytest.fixture
def mock_create_subprocess(monkeypatch: pytest.MonkeyPatch, mock_process):
    """Patches asyncio.create_subprocess_exec for run_claude_cli tests."""
    mock_create = AsyncMock(return_value=mock_process)
    monkeypatch.setattr("asyncio.create_subprocess_exec", mock_create)
    return mock_create
