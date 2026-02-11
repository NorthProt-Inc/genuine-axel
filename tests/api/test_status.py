"""Tests for backend.api.status -- Health and status endpoints."""

import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# GET /auth/status
# ---------------------------------------------------------------------------


class TestAuthStatus:

    @patch("backend.api.deps.AXNMIHN_API_KEY", "")
    def test_no_key_configured(self, no_auth_client):
        resp = no_auth_client.get("/auth/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["is_admin"] is True
        assert body["auth_required"] is False

    @patch("backend.api.deps.AXNMIHN_API_KEY", "correct-key")
    def test_authorized_request(self, client):
        resp = client.get(
            "/auth/status",
            headers={"Authorization": "Bearer correct-key"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["is_admin"] is True

    @patch("backend.api.deps.AXNMIHN_API_KEY", "correct-key")
    def test_unauthorized_request(self, client):
        resp = client.get("/auth/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["is_admin"] is False


# ---------------------------------------------------------------------------
# GET /llm/providers
# ---------------------------------------------------------------------------


class TestLLMProviders:

    @patch("backend.api.status.get_all_providers")
    def test_returns_providers(self, mock_providers, no_auth_client):
        mock_providers.return_value = [
            {"id": "gemini", "name": "Gemini", "icon": "G", "available": True},
            {"id": "anthropic", "name": "Anthropic", "icon": "A", "available": False},
        ]
        resp = no_auth_client.get("/llm/providers")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["providers"]) == 2
        assert body["default"] is not None


# ---------------------------------------------------------------------------
# GET /models
# ---------------------------------------------------------------------------


class TestGetModels:

    @patch("backend.api.status.get_all_models")
    def test_returns_models(self, mock_models, no_auth_client):
        mock_models.return_value = [{"id": "axel", "name": "Axel"}]
        resp = no_auth_client.get("/models")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["models"]) == 1
        assert body["default"] == "gemini"


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------


class TestHealthCheck:

    @patch("backend.api.status.get_all_providers")
    def test_healthy(self, mock_providers, no_auth_client, mock_state):
        mock_providers.return_value = [
            {"id": "gemini", "name": "Gemini", "available": True},
        ]
        resp = no_auth_client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "healthy"
        assert "modules" in body
        assert "memory" in body["modules"]
        assert "llm" in body["modules"]
        assert body["modules"]["memory"]["status"] == "ok"

    @patch("backend.api.status.get_all_providers")
    def test_unhealthy_no_memory(self, mock_providers, no_auth_client, mock_state):
        mock_providers.return_value = [
            {"id": "gemini", "name": "Gemini", "available": True},
        ]
        mock_state.memory_manager = None
        resp = no_auth_client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "unhealthy"
        assert "Memory system not initialized" in (body.get("issues") or [])

    @patch("backend.api.status.get_all_providers")
    def test_unhealthy_no_llm(self, mock_providers, no_auth_client, mock_state):
        mock_providers.return_value = [
            {"id": "gemini", "name": "Gemini", "available": False},
        ]
        resp = no_auth_client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        # memory is ok but LLM is not -> unhealthy
        assert body["status"] == "unhealthy"

    @patch("backend.api.status.get_all_providers")
    def test_degraded_with_issues(self, mock_providers, no_auth_client, mock_state):
        """Memory + LLM ok but identity is off -> degraded is unlikely,
        but at least we test the response shape."""
        mock_providers.return_value = [
            {"id": "gemini", "name": "Gemini", "available": True},
        ]
        mock_state.identity_manager = None
        resp = no_auth_client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] in ("healthy", "degraded")

    @patch("backend.api.status.get_all_providers")
    def test_health_response_shape(self, mock_providers, no_auth_client, mock_state):
        mock_providers.return_value = [
            {"id": "gemini", "name": "Gemini", "available": True},
        ]
        resp = no_auth_client.get("/health")
        body = resp.json()
        assert "version" in body
        assert "timestamp" in body
        assert "uptime_info" in body
        assert "api_keys" in body


# ---------------------------------------------------------------------------
# GET /health/quick
# ---------------------------------------------------------------------------


class TestHealthQuick:

    @patch("backend.api.status.get_all_providers")
    def test_ok(self, mock_providers, no_auth_client, mock_state):
        mock_providers.return_value = [
            {"id": "gemini", "name": "Gemini", "available": True},
        ]
        resp = no_auth_client.get("/health/quick")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["memory"] == "ok"
        assert body["llm"] == "ok"

    @patch("backend.api.status.get_all_providers")
    def test_degraded(self, mock_providers, no_auth_client, mock_state):
        mock_providers.return_value = []
        mock_state.memory_manager = None
        resp = no_auth_client.get("/health/quick")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "degraded"


# ---------------------------------------------------------------------------
# GET /code/summary and /code/files (auth required)
# ---------------------------------------------------------------------------


class TestCodeEndpoints:

    @patch("backend.api.status.get_code_summary")
    def test_code_summary(self, mock_summary, authed_client):
        mock_summary.return_value = "Codebase has 50 files"
        resp = authed_client.get("/code/summary")
        assert resp.status_code == 200
        body = resp.json()
        assert body["summary"] == "Codebase has 50 files"

    @patch("backend.api.status.list_source_files")
    def test_code_files(self, mock_files, authed_client):
        mock_files.return_value = [{"path": "backend/app.py", "lines": 200}]
        resp = authed_client.get("/code/files")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["files"]) == 1

    @patch("backend.api.deps.AXNMIHN_API_KEY", "secret")
    def test_code_summary_requires_auth(self, client):
        resp = client.get("/code/summary")
        assert resp.status_code == 401

    @patch("backend.api.deps.AXNMIHN_API_KEY", "secret")
    def test_code_files_requires_auth(self, client):
        resp = client.get("/code/files")
        assert resp.status_code == 401
