import asyncio
from typing import Optional, Dict
import httpx
from backend.core.logging import get_logger
from backend.core.utils.timeouts import SERVICE_TIMEOUTS

_log = get_logger("core.http_pool")

POOL_LIMITS = httpx.Limits(
    max_connections=100,
    max_keepalive_connections=20,
)

_clients: Dict[str, httpx.AsyncClient] = {}
_lock = asyncio.Lock()

async def get_client(
    service: str = "default",
    base_url: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: Optional[float] = None,
) -> httpx.AsyncClient:

    async with _lock:
        if service not in _clients:
            service_timeout = timeout or SERVICE_TIMEOUTS.get(service, SERVICE_TIMEOUTS["default"])
            _clients[service] = httpx.AsyncClient(
                base_url=base_url,
                headers=headers,
                limits=POOL_LIMITS,
                timeout=httpx.Timeout(service_timeout, connect=5.0),
                follow_redirects=True,
            )
            _log.debug("Client created", service=service, timeout=service_timeout)
        else:
            _log.debug("Client reused", service=service, pool_cnt=len(_clients))
        return _clients[service]

async def close_all() -> int:

    async with _lock:
        cnt = len(_clients)
        _log.debug("Pool cleanup starting", client_cnt=cnt)
        for service, client in _clients.items():
            try:
                await client.aclose()
                _log.debug("Client closed", service=service)
            except Exception as e:
                _log.warning("Client close error", service=service, error=str(e))
        _clients.clear()
        _log.debug("Pool cleanup done", closed_cnt=cnt)
        return cnt
