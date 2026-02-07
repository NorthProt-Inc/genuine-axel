"""Tests for ContextService temporal filter and session archive support."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core.services.context_service import ContextService


@pytest.fixture
def mock_memory_manager():
    """Create a mock MemoryManager with session archive."""
    mm = MagicMock()
    mm.is_session_archive_available.return_value = True
    mm.is_working_available.return_value = False
    mm.is_graph_rag_available.return_value = False
    mm.session_archive = MagicMock()
    mm.memgpt = MagicMock()
    return mm


@pytest.fixture
def mock_long_term():
    """Create a mock LongTermMemory."""
    return MagicMock()


@pytest.fixture
def service(mock_memory_manager, mock_long_term):
    """Create a ContextService with mocked dependencies."""
    return ContextService(
        memory_manager=mock_memory_manager,
        long_term_memory=mock_long_term,
    )


# ── Cycle 3.1: _fetch_longterm_data with temporal filter ────────────────────


class TestFetchLongtermWithTemporalFilter:
    """Verify temporal filter is passed to memgpt.context_budget_select."""

    @pytest.mark.asyncio
    async def test_temporal_query_passes_filter_to_memgpt(
        self, service, mock_memory_manager
    ) -> None:
        mock_memgpt = mock_memory_manager.memgpt
        mock_memgpt.context_budget_select.return_value = ([], 0)

        with patch(
            "backend.memory.temporal.parse_temporal_query",
            return_value={"type": "exact", "date": "2025-01-15"},
        ):
            await service._fetch_longterm_data(
                "1월 15일에 뭐 했어?", service.config
            )

        mock_memgpt.context_budget_select.assert_called_once()
        call_kwargs = mock_memgpt.context_budget_select.call_args
        # temporal_filter should be passed (either as kwarg or positional)
        assert call_kwargs.kwargs.get("temporal_filter") == {
            "type": "exact",
            "date": "2025-01-15",
        }

    @pytest.mark.asyncio
    async def test_non_temporal_query_passes_none(
        self, service, mock_memory_manager
    ) -> None:
        mock_memgpt = mock_memory_manager.memgpt
        mock_memgpt.context_budget_select.return_value = ([], 0)

        with patch(
            "backend.memory.temporal.parse_temporal_query",
            return_value=None,
        ):
            await service._fetch_longterm_data("안녕", service.config)

        call_kwargs = mock_memgpt.context_budget_select.call_args
        assert call_kwargs.kwargs.get("temporal_filter") is None


# ── Cycle 3.2: _fetch_session_archive_data ──────────────────────────────────


class TestFetchSessionArchiveWithTemporalFilter:
    """Verify session archive fetching with temporal filter."""

    @pytest.mark.asyncio
    async def test_exact_date_uses_get_sessions_by_date(
        self, service, mock_memory_manager
    ) -> None:
        archive = mock_memory_manager.session_archive
        archive.get_sessions_by_date.return_value = "세션 내용"

        with patch(
            "backend.memory.temporal.parse_temporal_query",
            return_value={"type": "exact", "date": "2025-01-15"},
        ):
            result = await service._fetch_session_archive_data("1월 15일")

        archive.get_sessions_by_date.assert_called_once()
        args = archive.get_sessions_by_date.call_args[0]
        assert args[0] == "2025-01-15"  # from_date
        assert args[1] is None  # to_date
        assert result == "세션 내용"

    @pytest.mark.asyncio
    async def test_range_uses_get_sessions_by_date_with_range(
        self, service, mock_memory_manager
    ) -> None:
        archive = mock_memory_manager.session_archive
        archive.get_sessions_by_date.return_value = "범위 세션"

        with patch(
            "backend.memory.temporal.parse_temporal_query",
            return_value={
                "type": "range",
                "from": "2025-01-10",
                "to": "2025-01-15",
            },
        ):
            result = await service._fetch_session_archive_data("지난 5일")

        args = archive.get_sessions_by_date.call_args[0]
        assert args[0] == "2025-01-10"
        assert args[1] == "2025-01-15"
        assert args[2] == 10  # limit
        assert result == "범위 세션"

    @pytest.mark.asyncio
    async def test_non_temporal_uses_get_recent_summaries(
        self, service, mock_memory_manager
    ) -> None:
        archive = mock_memory_manager.session_archive
        archive.get_recent_summaries.return_value = "최근 요약"

        with patch(
            "backend.memory.temporal.parse_temporal_query",
            return_value=None,
        ):
            result = await service._fetch_session_archive_data("안녕")

        archive.get_recent_summaries.assert_called_once()
        assert result == "최근 요약"

    @pytest.mark.asyncio
    async def test_returns_none_when_unavailable(self, mock_long_term) -> None:
        mm = MagicMock()
        mm.is_session_archive_available.return_value = False
        svc = ContextService(memory_manager=mm, long_term_memory=mock_long_term)

        result = await svc._fetch_session_archive_data("test")
        assert result is None

    @pytest.mark.asyncio
    async def test_filters_empty_message(
        self, service, mock_memory_manager
    ) -> None:
        archive = mock_memory_manager.session_archive
        archive.get_recent_summaries.return_value = "최근 대화 기록이 없습니다"

        with patch(
            "backend.memory.temporal.parse_temporal_query",
            return_value=None,
        ):
            result = await service._fetch_session_archive_data("test")

        assert result is None


# ── Cycle 3.3: build() integrates session archive ───────────────────────────


class TestBuildIntegratesSessionArchive:
    """Verify build() calls _fetch_session_archive_data."""

    @pytest.mark.asyncio
    async def test_build_includes_session_archive_in_gather(
        self, service
    ) -> None:
        with patch.object(
            service, "_fetch_longterm_data", new_callable=AsyncMock, return_value=None
        ), patch.object(
            service, "_fetch_graphrag_data", new_callable=AsyncMock, return_value=None
        ), patch.object(
            service,
            "_fetch_session_archive_data",
            new_callable=AsyncMock,
            return_value="세션 기록",
        ) as mock_fetch, patch.object(
            service, "_build_code_context", new_callable=AsyncMock, return_value=("", "")
        ):
            result = await service.build("test", "axel", None)

        mock_fetch.assert_called_once_with("test")
        # Session archive content should appear in the output
        assert "세션 기록" in result.system_prompt
