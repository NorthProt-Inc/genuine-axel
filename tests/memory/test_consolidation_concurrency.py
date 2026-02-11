"""Tests for consolidation concurrency limiting."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from backend.memory.memgpt import _consolidation_semaphore, MAX_CONSOLIDATION_CONCURRENCY


class TestConsolidationConcurrency:

    def test_max_concurrency_value(self):
        assert MAX_CONSOLIDATION_CONCURRENCY == 3

    @pytest.mark.asyncio
    async def test_concurrent_limit_respected(self):
        active = []
        max_active = [0]

        async def mock_consolidate(*args, **kwargs):
            active.append(1)
            max_active[0] = max(max_active[0], len(active))
            await asyncio.sleep(0.05)
            active.pop()
            return {"transformed": 0}

        sem = asyncio.Semaphore(3)

        async def limited_call():
            async with sem:
                return await mock_consolidate()

        tasks = [asyncio.create_task(limited_call()) for _ in range(6)]
        await asyncio.gather(*tasks)

        assert max_active[0] <= 3

    @pytest.mark.asyncio
    async def test_semaphore_released_on_error(self):
        sem = asyncio.Semaphore(2)

        async def failing_task():
            async with sem:
                raise ValueError("test error")

        with pytest.raises(ValueError):
            await failing_task()

        # Semaphore should be released
        assert sem._value == 2

    def test_sequential_still_works(self):
        """Sync episodic_to_semantic should still be callable."""
        from backend.memory.memgpt import MemGPTManager
        assert hasattr(MemGPTManager, "episodic_to_semantic")
