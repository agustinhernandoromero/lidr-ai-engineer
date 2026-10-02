"""Prueba real contra Anthropic: 3 turnos y el proyecto no se "olvida".

Cuesta dinero (unos céntimos con Haiku) y depende de red, así que solo corre
con RUN_LIVE_TESTS=1:

    RUN_LIVE_TESTS=1 uv run pytest -m live -v
"""

import os

import httpx
import pytest

from app.config import get_settings
from app.dependencies import get_session_store
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
    "Segunda reunión: seremos 4 personas en el equipo y dejamos los pagos online "
    "fuera del MVP.",
    "Recuérdame cómo se llama el proyecto y dame el total de horas actualizado en una frase.",
]


@pytest.mark.asyncio
async def test_three_real_turns_keep_project_name():
    app.dependency_overrides[get_session_store] = lambda: SessionStore(max_turns=6)
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
    assert data["project_metadata"]["assumed_team_size"] == 4
