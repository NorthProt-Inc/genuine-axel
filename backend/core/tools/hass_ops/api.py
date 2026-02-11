"""Low-level Home Assistant API communication."""

import asyncio
from typing import Optional, Dict
import httpx
from backend.core.logging import get_logger
from backend.core.utils.http_pool import get_client
from backend.core.utils.circuit_breaker import HASS_CIRCUIT
from .config import HASSResult, _get_hass_config, _get_hass_credentials

_log = get_logger("tools.hass.api")


async def _hass_api_call(
    method: str,
    endpoint: str,
    payload: Optional[Dict] = None,
    retries: Optional[int] = None
) -> HASSResult:
    """Make an HTTP request to Home Assistant API with retry logic.
    
    Args:
        method: HTTP method (GET or POST)
        endpoint: API endpoint path
        payload: Optional JSON payload for POST requests
        retries: Number of retries (defaults to HASS_MAX_RETRIES)
    
    Returns:
        HASSResult with success status, message, data, and error
    """
    # Get config values at runtime to avoid circular import
    hass_timeout, hass_max_retries = _get_hass_config()
    if retries is None:
        retries = hass_max_retries

    _log.debug("HASS req", endpoint=endpoint, method=method)

    # Check circuit breaker first
    if not HASS_CIRCUIT.can_execute():
        timeout_remaining = HASS_CIRCUIT.get_timeout_remaining()
        HASS_CIRCUIT.record_rejected()
        _log.warning("HASS circuit open", timeout_remaining=timeout_remaining)
        return HASSResult(
            success=False,
            message="",
            error=f"Home Assistant circuit breaker is OPEN. Retry after {timeout_remaining:.0f}s"
        )

    hass_url, hass_token = _get_hass_credentials()

    if not hass_token:
        _log.error("HASS fail", err="HASS_TOKEN not configured")
        return HASSResult(
            success=False,
            message="",
            error="HASS_TOKEN not configured. Set the HASS_TOKEN environment variable."
        )

    headers = {
        "Authorization": f"Bearer {hass_token}",
        "Content-Type": "application/json"
    }

    last_error = None

    for attempt in range(retries + 1):
        try:
            client = await get_client(
                service="hass",
                base_url=hass_url,
                headers=headers,
                timeout=hass_timeout
            )

            if method.upper() == "GET":
                resp = await client.get(endpoint)
                result = _process_response_httpx(resp, endpoint)
                if result.success:
                    HASS_CIRCUIT.record_success()
                    _log.info("HASS ok", endpoint=endpoint, method=method)
                else:
                    HASS_CIRCUIT.record_failure()
                return result
            elif method.upper() == "POST":
                resp = await client.post(endpoint, json=payload)
                result = _process_response_httpx(resp, endpoint)
                if result.success:
                    HASS_CIRCUIT.record_success()
                    _log.info("HASS ok", endpoint=endpoint, method=method)
                else:
                    HASS_CIRCUIT.record_failure()
                return result
            else:
                _log.error("HASS fail", err=f"Unsupported method: {method}")
                return HASSResult(
                    success=False,
                    message="",
                    error=f"Unsupported HTTP method: {method}"
                )
        except httpx.TimeoutException:
            HASS_CIRCUIT.record_failure()
            last_error = "Connection timeout - Home Assistant may be unreachable"
            _log.warning("HASS retry", endpoint=endpoint, attempt=attempt+1, err="timeout")
        except httpx.RequestError as e:
            HASS_CIRCUIT.record_failure()
            last_error = f"Connection error: {str(e)}"
            _log.warning("HASS retry", endpoint=endpoint, attempt=attempt+1, err=str(e)[:100])
        except Exception as e:
            HASS_CIRCUIT.record_failure()
            last_error = f"Unexpected error: {str(e)}"
            _log.warning("HASS retry", endpoint=endpoint, attempt=attempt+1, err=str(e)[:100])

        if attempt < retries:
            await asyncio.sleep(0.5 * (attempt + 1))

    _log.error("HASS fail", endpoint=endpoint, err=last_error[:100] if last_error else "Unknown")
    return HASSResult(
        success=False,
        message="",
        error=last_error or "Unknown error after retries"
    )


def _process_response_httpx(resp: httpx.Response, endpoint: str = "") -> HASSResult:
    """Process HTTP response from Home Assistant API.
    
    Args:
        resp: httpx Response object
        endpoint: API endpoint (for logging)
    
    Returns:
        HASSResult with parsed response data
    """
    _log.debug("HASS res", endpoint=endpoint, status=resp.status_code)
    if resp.status_code in (200, 201):
        try:
            data = resp.json()
            return HASSResult(
                success=True,
                message="OK",
                data=data
            )
        except Exception:
            return HASSResult(success=True, message="OK", data={})
    elif resp.status_code == 401:
        return HASSResult(
            success=False,
            message="",
            error="Authentication failed - check HASS_TOKEN"
        )
    elif resp.status_code == 404:
        return HASSResult(
            success=False,
            message="",
            error="Entity not found"
        )
    else:
        return HASSResult(
            success=False,
            message="",
            error=f"HASS API error {resp.status_code}: {resp.text[:200]}"
        )


async def hass_get_state(entity_id: str) -> HASSResult:
    """Get the current state of a Home Assistant entity.
    
    Args:
        entity_id: Entity ID (e.g., "light.living_room")
    
    Returns:
        HASSResult with entity state and attributes
    """
    _log.debug("HASS get state", ent=entity_id)

    if not entity_id or "." not in entity_id:
        _log.warning("HASS fail", ent=entity_id, err="Invalid entity_id")
        return HASSResult(
            success=False,
            message="",
            error=f"Invalid entity_id: {entity_id}"
        )

    result = await _hass_api_call("GET", f"/api/states/{entity_id}")

    if result.success and result.data:
        attrs = result.data.get("attributes", {})
        state = result.data.get("state")
        result.message = (
            f"{attrs.get('friendly_name', entity_id)}: "
            f"{state}"
            f"{attrs.get('unit_of_measurement', '')}"
        )
        _log.debug("HASS state ok", ent=entity_id, state=state)

    return result


async def get_all_states(known_only: bool = False) -> HASSResult:
    """Get states of Home Assistant entities.

    Args:
        known_only: If True, filter to registered entities only.
            Defaults to False (return all entities).
    
    Returns:
        HASSResult with list of entity states
    """
    from .config import _get_device_config
    
    _log.debug("HASS get all states", known_only=known_only)
    result = await _hass_api_call("GET", "/api/states")

    if result.success and result.data:
        from typing import Any
        states: list[Any] = result.data if isinstance(result.data, list) else []
        if known_only:
            known_entities = _get_device_config().known_entities
            filtered = [
                state for state in states
                if isinstance(state, dict) and state.get("entity_id") in known_entities
            ]
            result.data = filtered  # type: ignore[assignment]
            result.message = f"Retrieved {len(filtered)} known entity states"
        else:
            result.message = f"Retrieved {len(states)} entity states"
        _log.debug("HASS all states ok", cnt=len(states))

    return result


async def hass_list_entities(domain: Optional[str] = None) -> HASSResult:
    """List all entities or entities in a specific domain.
    
    Args:
        domain: Optional domain filter (e.g., "light", "sensor")
    
    Returns:
        HASSResult with entity list or domain summary
    """
    from typing import Any
    
    _log.debug("HASS list entities", domain=domain)
    result = await _hass_api_call("GET", "/api/states")

    if not result.success:
        return result

    all_entities: list[Any] = result.data if isinstance(result.data, list) else []

    if domain:
        # Return entities in the specified domain
        filtered = [
            {
                "entity_id": e.get("entity_id"),
                "friendly_name": e.get("attributes", {}).get("friendly_name", e.get("entity_id")),
                "state": e.get("state")
            }
            for e in all_entities
            if isinstance(e, dict) and e.get("entity_id", "").startswith(f"{domain}.")
        ]
        _log.debug("HASS entities ok", domain=domain, cnt=len(filtered))
        return HASSResult(
            success=True,
            message=f"Found {len(filtered)} {domain} entities",
            data={"domain": domain, "entities": filtered}
        )
    else:
        # Return domain summary
        domains: dict[str, int] = {}
        for e in all_entities:
            entity_id = e.get("entity_id", "") if isinstance(e, dict) else ""
            if "." in entity_id:
                d = entity_id.split(".")[0]
                domains[d] = domains.get(d, 0) + 1

        _log.debug("HASS entities ok", domains=len(domains), total=len(all_entities))
        return HASSResult(
            success=True,
            message=f"Found {len(all_entities)} total entities across {len(domains)} domains",
            data={"domains": domains, "total": len(all_entities)}
        )
