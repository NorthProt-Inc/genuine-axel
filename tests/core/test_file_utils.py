"""Tests for backend.core.utils.file_utils."""

import asyncio
import os
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from backend.core.utils.file_utils import (
    TMP_FILE_PREFIX,
    TMP_MAX_AGE_SECONDS,
    fsync_directory,
    cleanup_orphaned_tmp_files,
    get_async_file_lock,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestConstants:
    """Validate module constants."""

    def test_tmp_file_prefix(self):
        assert TMP_FILE_PREFIX == ".axnmihn_tmp_"

    def test_tmp_max_age(self):
        assert TMP_MAX_AGE_SECONDS == 3600


# ---------------------------------------------------------------------------
# fsync_directory
# ---------------------------------------------------------------------------


class TestFsyncDirectory:
    """Tests for the fsync_directory function."""

    def test_fsync_existing_directory(self, tmp_path):
        """Should not raise on an existing directory."""
        fsync_directory(tmp_path)

    def test_fsync_nonexistent_directory(self, tmp_path):
        """Should not raise even on bad path (catches OSError)."""
        bad_path = tmp_path / "does_not_exist"
        fsync_directory(bad_path)  # should log warning, not raise

    @patch("backend.core.utils.file_utils.os.name", "nt")
    def test_fsync_skipped_on_windows(self, tmp_path):
        """fsync is a no-op on Windows."""
        # Should return immediately without error
        fsync_directory(tmp_path)


# ---------------------------------------------------------------------------
# cleanup_orphaned_tmp_files
# ---------------------------------------------------------------------------


class TestCleanupOrphanedTmpFiles:
    """Tests for the cleanup_orphaned_tmp_files function."""

    def test_nonexistent_directory_returns_zero(self, tmp_path):
        result = cleanup_orphaned_tmp_files(tmp_path / "nope")
        assert result == 0

    def test_no_tmp_files_returns_zero(self, tmp_path):
        # Create a non-tmp file
        (tmp_path / "regular_file.txt").write_text("hello")
        result = cleanup_orphaned_tmp_files(tmp_path)
        assert result == 0
        assert (tmp_path / "regular_file.txt").exists()

    def test_young_tmp_file_not_deleted(self, tmp_path):
        """Tmp files younger than TMP_MAX_AGE_SECONDS are kept."""
        tmp_file = tmp_path / f"{TMP_FILE_PREFIX}young"
        tmp_file.write_text("data")
        result = cleanup_orphaned_tmp_files(tmp_path)
        assert result == 0
        assert tmp_file.exists()

    def test_old_tmp_file_deleted(self, tmp_path):
        """Tmp files older than TMP_MAX_AGE_SECONDS are deleted."""
        tmp_file = tmp_path / f"{TMP_FILE_PREFIX}old"
        tmp_file.write_text("data")
        # Set mtime to far in the past
        old_time = time.time() - TMP_MAX_AGE_SECONDS - 100
        os.utime(tmp_file, (old_time, old_time))
        result = cleanup_orphaned_tmp_files(tmp_path)
        assert result == 1
        assert not tmp_file.exists()

    def test_multiple_old_files_deleted(self, tmp_path):
        old_time = time.time() - TMP_MAX_AGE_SECONDS - 100
        for i in range(3):
            f = tmp_path / f"{TMP_FILE_PREFIX}old_{i}"
            f.write_text("data")
            os.utime(f, (old_time, old_time))
        # Also one young file
        young = tmp_path / f"{TMP_FILE_PREFIX}young"
        young.write_text("data")
        result = cleanup_orphaned_tmp_files(tmp_path)
        assert result == 3
        assert young.exists()

    def test_non_tmp_files_never_deleted(self, tmp_path):
        """Files that don't match the prefix are never deleted."""
        regular = tmp_path / "important_data.json"
        regular.write_text('{"key": "value"}')
        old_time = time.time() - TMP_MAX_AGE_SECONDS - 100
        os.utime(regular, (old_time, old_time))
        result = cleanup_orphaned_tmp_files(tmp_path)
        assert result == 0
        assert regular.exists()

    def test_file_vanished_during_scan(self, tmp_path):
        """Handle race condition where file is deleted between iterdir and stat."""
        tmp_file = tmp_path / f"{TMP_FILE_PREFIX}vanished"
        tmp_file.write_text("data")
        old_time = time.time() - TMP_MAX_AGE_SECONDS - 100
        os.utime(tmp_file, (old_time, old_time))

        # Delete before cleanup can process it — simulates race
        original_stat = Path.stat

        def flaky_stat(self_, *args, **kwargs):
            if self_.name == f"{TMP_FILE_PREFIX}vanished":
                raise FileNotFoundError("Gone")
            return original_stat(self_, *args, **kwargs)

        with patch.object(Path, "stat", flaky_stat):
            result = cleanup_orphaned_tmp_files(tmp_path)
        assert result == 0  # FileNotFoundError was caught


# ---------------------------------------------------------------------------
# get_async_file_lock
# ---------------------------------------------------------------------------


class TestGetAsyncFileLock:
    """Tests for the async file locking mechanism."""

    async def test_returns_asyncio_lock(self, tmp_path):
        lock = await get_async_file_lock(tmp_path / "test.json")
        assert isinstance(lock, asyncio.Lock)

    async def test_same_path_same_lock(self, tmp_path):
        path = tmp_path / "shared.json"
        lock1 = await get_async_file_lock(path)
        lock2 = await get_async_file_lock(path)
        assert lock1 is lock2

    async def test_different_path_different_lock(self, tmp_path):
        lock1 = await get_async_file_lock(tmp_path / "a.json")
        lock2 = await get_async_file_lock(tmp_path / "b.json")
        assert lock1 is not lock2

    async def test_lock_is_usable(self, tmp_path):
        lock = await get_async_file_lock(tmp_path / "test.json")
        async with lock:
            pass  # Should acquire and release without error


# ---------------------------------------------------------------------------
# Constant TMP_FILE_PREFIX interaction
# ---------------------------------------------------------------------------


class TestTmpFilePrefixMatching:
    """Ensure prefix matching logic works correctly."""

    def test_exact_prefix_matches(self, tmp_path):
        f = tmp_path / f"{TMP_FILE_PREFIX}data"
        f.write_text("test")
        assert f.name.startswith(TMP_FILE_PREFIX)

    def test_similar_but_wrong_prefix(self, tmp_path):
        f = tmp_path / ".axnmihn_tmp"  # missing trailing underscore
        f.write_text("test")
        assert not f.name.startswith(TMP_FILE_PREFIX)

    def test_prefix_as_substring_not_prefix(self, tmp_path):
        f = tmp_path / f"other_{TMP_FILE_PREFIX}data"
        f.write_text("test")
        assert not f.name.startswith(TMP_FILE_PREFIX)
