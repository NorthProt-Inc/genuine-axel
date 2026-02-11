"""Tests for backend.core.utils.http_pool."""

import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

import httpx
import pytest

# We need to clear the module-level _clients dict between tests
import backend.core.utils.http_pool as http_pool_mod
from backend.core.utils.http_pool import (
    POOL_LIMITS,
    close_all,
    get_client,
)


@pytest.fixture(autouse=True)
async def _clean_pool():
    """Ensure pool is empty before and after each test."""
    http_pool_mod._clients.clear()
    yield
    # close any lingering clients
    for client in list(http_pool_mod._clients.values()):
        try:
            await client.aclose()
        except Exception:
            pass
    http_pool_mod._clients.clear()


# ---------------------------------------------------------------------------
# POOL_LIMITS constants
# ---------------------------------------------------------------------------


class TestPoolLimits:
    def test_max_connections(self):
        assert POOL_LIMITS.max_connections == 100

    def test_max_keepalive_connections(self):
        assert POOL_LIMITS.max_keepalive_connections == 20


# ---------------------------------------------------------------------------
# get_client
# ---------------------------------------------------------------------------


class TestGetClient:
    async def test_creates_new_client(self):
        client = await get_client(service="test_svc", base_url="https://test.example.com")

        assert isinstance(client, httpx.AsyncClient)
        assert "test_svc" in http_pool_mod._clients

    async def test_reuses_existing_client(self):
        client1 = await get_client(service="reuse_svc", base_url="https://example.com")
        client2 = await get_client(service="reuse_svc", base_url="https://example.com")

        assert client1 is client2

    async def test_different_services_get_different_clients(self):
        c1 = await get_client(service="svc_a", base_url="https://a.example.com")
        c2 = await get_client(service="svc_b", base_url="https://b.example.com")

        assert c1 is not c2

    async def test_custom_base_url(self):
        client = await get_client(service="custom_url", base_url="https://example.com")

        assert client.base_url == httpx.URL("https://example.com")

    async def test_custom_headers(self):
        client = await get_client(
            service="custom_hdr",
            base_url="https://example.com",
            headers={"Authorization": "Bearer token123"},
        )

        assert client.headers["authorization"] == "Bearer token123"

    async def test_custom_timeout(self):
        client = await get_client(service="custom_to", base_url="https://example.com", timeout=99.0)

        assert client.timeout.read == 99.0
        assert client.timeout.connect == 5.0

    async def test_default_timeout_from_service_timeouts(self):
        """When no explicit timeout, uses SERVICE_TIMEOUTS lookup."""
        from backend.core.utils.timeouts import SERVICE_TIMEOUTS

        client = await get_client(service="hass", base_url="https://hass.local")

        expected = SERVICE_TIMEOUTS["hass"]
        assert client.timeout.read == expected

    async def test_unknown_service_uses_default_timeout(self):
        """An unknown service falls back to SERVICE_TIMEOUTS['default']."""
        from backend.core.utils.timeouts import SERVICE_TIMEOUTS

        client = await get_client(service="unknown_svc_xyz", base_url="https://example.com")

        expected = SERVICE_TIMEOUTS["default"]
        assert client.timeout.read == expected

    async def test_follow_redirects_enabled(self):
        client = await get_client(service="redirect_test", base_url="https://example.com")
        assert client.follow_redirects is True

    async def test_second_call_does_not_recreate(self):
        """On second call with same service, the existing client is returned without creating a new one."""
        c1 = await get_client(service="reuse2", base_url="https://example.com")
        c2 = await get_client(service="reuse2")

        assert c1 is c2
        assert len(http_pool_mod._clients) == 1


# ---------------------------------------------------------------------------
# close_all
# ---------------------------------------------------------------------------


class TestCloseAll:
    async def test_closes_all_clients(self):
        await get_client(service="s1", base_url="https://s1.example.com")
        await get_client(service="s2", base_url="https://s2.example.com")

        assert len(http_pool_mod._clients) == 2

        cnt = await close_all()

        assert cnt == 2
        assert len(http_pool_mod._clients) == 0

    async def test_close_empty_pool(self):
        cnt = await close_all()
        assert cnt == 0

    async def test_close_handles_client_error(self):
        """If a client.aclose() raises, close_all still clears the pool."""
        bad_client = AsyncMock(spec=httpx.AsyncClient)
        bad_client.aclose.side_effect = RuntimeError("close failed")

        http_pool_mod._clients["bad"] = bad_client

        cnt = await close_all()

        assert cnt == 1
        assert len(http_pool_mod._clients) == 0

    async def test_close_all_then_create_new(self):
        """After close_all, new get_client calls create fresh clients."""
        c1 = await get_client(service="fresh", base_url="https://example.com")
        await close_all()
        c2 = await get_client(service="fresh", base_url="https://example.com")

        assert c1 is not c2
