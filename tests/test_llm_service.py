"""Tests de orquestación de ``generate_estimation``: caché y fallback a Gemini.

No golpean ninguna API real: ``call_anthropic``/``call_gemini`` y la caché van
mockeadas. El objetivo es probar las reglas de negocio, no los SDKs de
terceros.
"""

from unittest.mock import Mock, patch

import pytest

from app.config import Settings
from app.schemas import DetailLevel, EstimationRequest, OutputFormat, ProjectType
from app.services.llm_service import call_gemini, generate_estimation

DESCRIPTION = (
    "Plataforma web para que una red de gimnasios gestione altas de socios, "
    "reservas de clases y cobros mensuales por domiciliación bancaria."
)


def build_request() -> EstimationRequest:
    return EstimationRequest(
        description=DESCRIPTION,
        project_type=ProjectType.WEB_SAAS,
        detail_level=DetailLevel.MEDIUM,
        output_format=OutputFormat.PHASES_TABLE,
    )


def fake_cache(hit: dict | None = None) -> Mock:
    """Caché falsa: por defecto siempre miss, para forzar la llamada al LLM."""
    cache = Mock()
    cache.make_key.return_value = "fake-key"
    cache.get.return_value = hit
    return cache


@pytest.mark.asyncio
@patch("app.services.llm_service.get_cache")
@patch("app.services.llm_service.get_settings")
@patch("app.services.llm_service.call_anthropic")
async def test_primary_success_is_cached_and_not_flagged_as_fallback(
    mock_call_anthropic, mock_get_settings, mock_get_cache
):
    mock_get_settings.return_value = Settings()
    mock_call_anthropic.return_value = {
        "text": "Estimación real",
        "model": "claude-haiku-4-5",
        "provider": "anthropic",
    }
    cache = fake_cache()
    mock_get_cache.return_value = cache

    result = await generate_estimation(build_request())

    assert result["provider"] == "anthropic"
    assert result["fallback_used"] is False
    cache.set.assert_called_once()


@pytest.mark.asyncio
@patch("app.services.llm_service.get_cache")
@patch("app.services.llm_service.get_settings")
@patch("app.services.llm_service.call_gemini")
@patch("app.services.llm_service.call_anthropic")
async def test_falls_back_to_gemini_when_primary_fails(
    mock_call_anthropic, mock_call_gemini, mock_get_settings, mock_get_cache
):
    mock_get_settings.return_value = Settings()
    mock_call_anthropic.side_effect = Exception("Anthropic caído")
    mock_call_gemini.return_value = {
        "text": "Estimación de respaldo",
        "model": "gemini-flash-latest",
        "provider": "gemini",
    }
    mock_get_cache.return_value = fake_cache()

    result = await generate_estimation(build_request())

    assert result["provider"] == "gemini"
    assert result["fallback_used"] is True
    mock_call_gemini.assert_called_once()


@pytest.mark.asyncio
@patch("app.services.llm_service.get_cache")
@patch("app.services.llm_service.get_settings")
@patch("app.services.llm_service.call_gemini")
@patch("app.services.llm_service.call_anthropic")
async def test_fallback_response_is_not_cached(
    mock_call_anthropic, mock_call_gemini, mock_get_settings, mock_get_cache
):
    """Evita servir 24h una respuesta de Gemini una vez que Anthropic se recupera."""
    mock_get_settings.return_value = Settings()
    mock_call_anthropic.side_effect = Exception("Anthropic caído")
    mock_call_gemini.return_value = {
        "text": "Estimación de respaldo",
        "model": "gemini-flash-latest",
        "provider": "gemini",
    }
    cache = fake_cache()
    mock_get_cache.return_value = cache

    await generate_estimation(build_request())

    cache.set.assert_not_called()


@pytest.mark.asyncio
@patch("app.services.llm_service.get_cache")
@patch("app.services.llm_service.get_settings")
async def test_cache_hit_short_circuits_before_calling_any_provider(
    mock_get_settings, mock_get_cache
):
    mock_get_settings.return_value = Settings()
    cached_value = {
        "text": "Estimación cacheada",
        "model": "claude-haiku-4-5",
        "provider": "anthropic",
    }
    mock_get_cache.return_value = fake_cache(hit=cached_value)

    with (
        patch("app.services.llm_service.call_anthropic") as mock_call_anthropic,
        patch("app.services.llm_service.call_gemini") as mock_call_gemini,
    ):
        result = await generate_estimation(build_request())

    assert result["cached"] is True
    assert result["fallback_used"] is False
    mock_call_anthropic.assert_not_called()
    mock_call_gemini.assert_not_called()


@patch("app.services.llm_service.time.sleep")
@patch("google.genai.Client")
def test_call_gemini_retries_once_on_server_error(mock_client_cls, mock_sleep):
    """El tier gratuito de Gemini da 503 de forma intermitente: un reintento
    tras 1s debe bastar para recuperarse sin propagar el error.
    """
    from google.genai import errors

    settings = Settings(GEMINI_API_KEY="fake-key")
    mock_client = Mock()
    mock_client_cls.return_value = mock_client
    mock_client.models.generate_content.side_effect = [
        errors.ServerError(code=503, response_json={"error": "high demand"}),
        Mock(text="Hola de respaldo"),
    ]

    result = call_gemini("system", "user", settings)

    assert result == {
        "text": "Hola de respaldo",
        "model": settings.GEMINI_MODEL,
        "provider": "gemini",
    }
    assert mock_client.models.generate_content.call_count == 2
    mock_sleep.assert_called_once_with(1)


@patch("app.services.llm_service.time.sleep")
@patch("google.genai.Client")
def test_call_gemini_propagates_error_after_failed_retry(mock_client_cls, mock_sleep):
    """Si Gemini falla dos veces seguidas, el error sí debe propagarse: no hay
    más redes de seguridad después de esta.
    """
    from google.genai import errors

    settings = Settings(GEMINI_API_KEY="fake-key")
    mock_client = Mock()
    mock_client_cls.return_value = mock_client
    mock_client.models.generate_content.side_effect = errors.ServerError(
        code=503, response_json={"error": "high demand"}
    )

    with pytest.raises(errors.ServerError):
        call_gemini("system", "user", settings)

    assert mock_client.models.generate_content.call_count == 2
    mock_sleep.assert_called_once_with(1)
