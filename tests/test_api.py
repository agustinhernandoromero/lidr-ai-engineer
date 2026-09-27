"""Automated tests for FastAPI endpoints and CAG service."""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.config import Settings
from app.services.llm_service import build_cag_system_prompt

client = TestClient(app)


def test_health_check_endpoint():
    """Verify GET /health returns 200 and expected status."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data.get("status") == "ok"
    assert "app_name" in data
    assert "provider" in data


def test_swagger_docs_accessible():
    """Verify OpenAPI and Swagger /docs endpoints are accessible."""
    response = client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert "paths" in schema
    assert "/api/v1/estimate" in schema["paths"]
    assert "/health" in schema["paths"]


def test_cag_system_prompt_builder():
    """Verify that CAG system prompt properly embeds static examples."""
    prompt = build_cag_system_prompt()
    assert "Arquitecto de Software" in prompt
    assert "CONTEXTO DE REFERENCIA (EJEMPLOS HISTÓRICOS)" in prompt
    assert "EJEMPLO 1" in prompt
    assert "EJEMPLO 2" in prompt
    assert "Estimación" in prompt


@patch("app.services.llm_service.get_settings")
@patch("app.services.llm_service.call_anthropic")
def test_estimate_endpoint_anthropic_mock(mock_call_anthropic, mock_get_settings):
    """Verify POST /api/v1/estimate with mocked Anthropic call.

    Settings are overridden so this test never depends on ambient config and
    never risks invoking a real LLM provider.
    """
    mock_get_settings.return_value = Settings()
    mock_call_anthropic.return_value = {
        "text": "## Estimación: Landing Page con HubSpot\n- Total: 60 horas",
        "model": "claude-haiku-4-5-20251001",
        "provider": "anthropic",
    }

    payload = {
        "description": "En la reunión con el equipo de marketing se pidió una landing page con HubSpot para captar leads.",
        "project_type": "web_saas",
        "detail_level": "summary",
        "output_format": "narrative",
    }

    response = client.post("/api/v1/estimate", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "text" in data
    assert data["provider"] == "anthropic"
    assert data["model"] == "claude-haiku-4-5-20251001"
    assert "Landing Page con HubSpot" in data["text"]


def test_estimate_endpoint_validation_error():
    """Verify validation error when description is too short."""
    response = client.post(
        "/api/v1/estimate",
        json={
            "description": "hola",
            "project_type": "web_saas",
            "detail_level": "summary",
            "output_format": "narrative",
        },
    )
    assert response.status_code == 422
