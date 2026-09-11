"""Automated tests for FastAPI endpoints and CAG service."""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app
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


@patch("app.services.llm_service.call_openai")
def test_estimate_endpoint_openai_mock(mock_call_openai):
    """Verify POST /api/v1/estimate with mocked OpenAI call."""
    mock_call_openai.return_value = {
        "estimation": "## Estimación: Landing Page con HubSpot\n- Total: 60 horas",
        "model": "gpt-4o-mini",
        "provider": "openai",
    }

    payload = {
        "transcription": "En la reunión con el equipo de marketing se pidió una landing page con HubSpot."
    }

    response = client.post("/api/v1/estimate", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "estimation" in data
    assert data["provider"] == "openai"
    assert data["model"] == "gpt-4o-mini"
    assert "Landing Page con HubSpot" in data["estimation"]


def test_estimate_endpoint_validation_error():
    """Verify validation error when transcription is too short."""
    response = client.post("/api/v1/estimate", json={"transcription": "hola"})
    assert response.status_code == 422
