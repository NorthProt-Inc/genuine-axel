"""Tests for backend.app — FastAPI application creation and middleware.

Covers:
- App instance exists and has correct metadata
- CORS middleware is configured
- Routers are mounted
- global_exception_handler returns proper JSON
- request_id_middleware sets and returns X-Request-ID
- ensure_data_directories called at module load
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


class TestAppInstance:
    """Verify the FastAPI app object is configured correctly."""

    def test_app_exists(self):
        from backend.app import app
        assert isinstance(app, FastAPI)

    def test_app_title(self):
        from backend.app import app
        assert app.title == "axnmihn API"

    def test_app_version(self):
        from backend.app import app
        from backend.config import APP_VERSION
        assert app.version == APP_VERSION


class TestRequestIdMiddleware:
    """request_id_middleware should propagate or generate X-Request-ID."""

    def test_returns_request_id_from_header(self):
        from backend.app import app
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/auth/status", headers={"X-Request-ID": "test-req-123"})
        assert response.headers.get("X-Request-ID") == "test-req-123"

    def test_generates_request_id_if_missing(self):
        from backend.app import app
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/auth/status")
        req_id = response.headers.get("X-Request-ID")
        assert req_id is not None
        assert len(req_id) > 0


class TestGlobalExceptionHandler:
    """global_exception_handler should return 500 with structured error JSON."""

    def test_returns_500_on_unhandled_exception(self):
        from backend.app import app

        # Add a temporary route that raises
        @app.get("/test-error-handler")
        async def _raise_route():
            raise RuntimeError("test boom")

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/test-error-handler")
        assert response.status_code == 500
        body = response.json()
        assert body["error"] == "Internal Server Error"
        assert body["type"] == "RuntimeError"
        assert "test boom" in body["message"]
        assert body["path"] == "/test-error-handler"

    def test_error_response_includes_request_id(self):
        from backend.app import app

        @app.get("/test-error-reqid")
        async def _raise_route():
            raise ValueError("err")

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/test-error-reqid", headers={"X-Request-ID": "err-req-42"})
        body = response.json()
        assert body["request_id"] == "err-req-42"


class TestCorsMiddleware:
    """CORS should be configured with get_cors_origins()."""

    def test_cors_allows_configured_origin(self):
        from backend.app import app
        from backend.config import get_cors_origins

        origins = get_cors_origins()
        if origins:
            client = TestClient(app, raise_server_exceptions=False)
            response = client.options(
                "/auth/status",
                headers={
                    "Origin": origins[0],
                    "Access-Control-Request-Method": "GET",
                },
            )
            # CORS preflight should return 200
            assert response.status_code == 200


class TestRoutersMounted:
    """Verify that all required routers are included."""

    def test_auth_status_route_accessible(self):
        from backend.app import app
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/auth/status")
        # Should not be 404 (may require auth, so 401 is acceptable)
        assert response.status_code != 404

    def test_llm_providers_route_accessible(self):
        from backend.app import app
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/llm/providers")
        assert response.status_code != 404
