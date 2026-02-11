"""Tests for DB Backup (Wave 3.4)."""

import pytest

from backend.core.ops.backup import (
    BackupConfig,
    RetentionPolicy,
    build_pg_dump_command,
    apply_retention_policy,
)


class TestBackupConfig:

    def test_default_config(self):
        config = BackupConfig(database_url="postgresql://user:pass@localhost/db")
        assert config.database_url == "postgresql://user:pass@localhost/db"
        assert config.output_dir == "/tmp/backups"
        assert config.format == "custom"

    def test_custom_output_dir(self):
        config = BackupConfig(
            database_url="postgresql://localhost/db",
            output_dir="/var/backups",
        )
        assert config.output_dir == "/var/backups"


class TestRetentionPolicy:

    def test_default_policy(self):
        policy = RetentionPolicy()
        assert policy.daily == 7
        assert policy.weekly == 4
        assert policy.monthly == 3


class TestBuildPgDumpCommand:

    def test_basic_command(self):
        config = BackupConfig(database_url="postgresql://user:pass@host:5432/mydb")
        cmd = build_pg_dump_command(config, "backup_2024.dump")
        assert "pg_dump" in cmd[0]
        assert "backup_2024.dump" in cmd[-1]

    def test_custom_format(self):
        config = BackupConfig(
            database_url="postgresql://localhost/db",
            format="custom",
        )
        cmd = build_pg_dump_command(config, "test.dump")
        assert "-Fc" in cmd

    def test_plain_format(self):
        config = BackupConfig(
            database_url="postgresql://localhost/db",
            format="plain",
        )
        cmd = build_pg_dump_command(config, "test.sql")
        assert "-Fp" in cmd


class TestApplyRetentionPolicy:

    def test_empty_backups(self):
        result = apply_retention_policy([], RetentionPolicy())
        assert result["to_delete"] == []

    def test_keeps_recent(self):
        from datetime import datetime, timedelta
        now = datetime.now()
        backups = [
            {"path": f"backup_{i}.dump", "created": now - timedelta(days=i)}
            for i in range(10)
        ]
        policy = RetentionPolicy(daily=7, weekly=0, monthly=0)
        result = apply_retention_policy(backups, policy)
        assert len(result["to_keep"]) <= 7

    def test_respects_daily_limit(self):
        from datetime import datetime, timedelta
        now = datetime.now()
        backups = [
            {"path": f"backup_{i}.dump", "created": now - timedelta(days=i)}
            for i in range(20)
        ]
        policy = RetentionPolicy(daily=3, weekly=0, monthly=0)
        result = apply_retention_policy(backups, policy)
        assert len(result["to_keep"]) <= 3
        assert len(result["to_delete"]) >= 17
