"""Prueba real contra Anthropic: 8 turnos, compresión incluida, y el proyecto
no se "olvida".

Cuesta dinero (unos céntimos con Haiku) y depende de red, así que solo corre
con RUN_LIVE_TESTS=1:

    RUN_LIVE_TESTS=1 uv run python -m pytest -m live -v -s -p no:logging
"""

import os

import httpx
import pytest

from app.config import get_settings
from app.dependencies import get_session_cache, get_session_store
from app.main import app
from app.services.sessions import SessionStore

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.getenv("RUN_LIVE_TESTS") != "1" or not get_settings().ANTHROPIC_API_KEY,
        reason="Solo con RUN_LIVE_TESTS=1 y ANTHROPIC_API_KEY configurada",
    ),
]

TURNS = [
    "Reunión con el cliente: queremos construir 'Hotelia', un portal de reservas para "
    "hoteles pequeños, con React en el frontend y PostgreSQL.",
    "El presupuesto está cerrado en 40.000 euros y seremos 4 personas en el equipo.",
    "Añadimos un panel de administración para el hotel con calendario de disponibilidad.",
    "Queremos notificaciones por email al confirmar una reserva.",
    "Los pagos online quedan fuera del MVP; irán en una fase 2.",
    "Necesitamos que el portal esté en español e inglés.",
    "Añadimos un informe mensual de ocupación exportable a CSV.",
    "Recuérdame cómo se llama el proyecto, cuál es el presupuesto cerrado y dame el "
    "total de horas actualizado en una frase.",
]


@pytest.mark.asyncio
async def test_eight_real_turns_keep_memory_through_compression():
    store = SessionStore(max_turns=6)  # una sola instancia para toda la conversación
    app.dependency_overrides[get_session_store] = lambda: store
    # Se mide el camino sin caché: todas las llamadas van al modelo real.
    app.dependency_overrides[get_session_cache] = lambda: None
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=180) as c:
            sid = (await c.post("/api/v1/sessions")).json()["session_id"]
            for transcript in TURNS:
                response = await c.post(
                    f"/api/v1/sessions/{sid}/estimate",
                    data={
                        "transcript": transcript,
                        "detail_level": "summary",
                        "output_format": "narrative",
                    },
                )
                assert response.status_code == 200, response.text
            data = response.json()
    finally:
        app.dependency_overrides.clear()

    assert "Hotelia" in data["text"]
    assert data["project_metadata"]["project_name"]
    assert "Hotelia" in data["project_metadata"]["project_name"]
    assert data["anchors_count"] >= 1  # "presupuesto está cerrado" salió de la ventana
    assert data["summary_chars"] > 0  # turnos que no son ancla, resumidos
    assert data["result"]["total_hours_min"] <= data["result"]["total_hours_max"]
