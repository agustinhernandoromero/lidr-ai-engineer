"""Integración de sesiones multiturno (Paso 7 del enunciado).

Usan ``FakeLLM``: verifican el cableado (historial, metadata, adjuntos,
ventana), NO la calidad de las respuestas del modelo real. Para eso está
``tests/test_sessions_live.py``.
"""

import httpx
import pytest
import pytest_asyncio

from app.dependencies import get_llm_wrapper, get_session_cache, get_session_store
from app.main import app
from app.services.sessions import SessionStore
from tests.helpers import FakeLLM, make_pdf

MAX_TURNS = 6
FORM = {"project_type": "web_saas", "detail_level": "summary", "output_format": "narrative"}


@pytest.fixture
def llm():
    return FakeLLM()


@pytest_asyncio.fixture
async def client(llm):
    store = SessionStore(max_turns=MAX_TURNS)
    app.dependency_overrides[get_session_store] = lambda: store
    app.dependency_overrides[get_llm_wrapper] = lambda: llm
    # Nunca tocar Redis ni los embeddings reales de Gemini en los tests.
    app.dependency_overrides[get_session_cache] = lambda: None
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def new_session(client) -> str:
    response = await client.post("/api/v1/sessions")
    assert response.status_code == 201
    return response.json()["session_id"]


async def estimate(client, session_id, transcript, files=None, **params):
    return await client.post(
        f"/api/v1/sessions/{session_id}/estimate",
        data={"transcript": transcript, **FORM},
        files=files,
        params=params,
    )


@pytest.mark.asyncio
async def test_two_turns_update_project_metadata_and_reach_the_prompt(client, llm):
    sid = await new_session(client)

    first = await estimate(client, sid, "Proyecto Hotelia: portal de reservas en React.")
    assert first.status_code == 200
    assert first.json()["project_metadata"]["project_name"] == "Hotelia"

    second = await estimate(client, sid, "Seremos 4 personas y el backend irá en FastAPI.")
    data = second.json()

    assert data["turn"] == 2
    assert data["project_metadata"]["project_name"] == "Hotelia"
    assert data["project_metadata"]["assumed_team_size"] == 4
    assert data["project_metadata"]["mentioned_technologies"] == ["React", "FastAPI"]
    # La memoria viaja en el system prompt del turno 2, no solo en el historial.
    system_turn_2 = llm.estimator_calls[1][0]["content"]
    assert "Proyecto: Hotelia" in system_turn_2.split("</project_metadata>")[0]

    state = (await client.get(f"/api/v1/sessions/{sid}")).json()
    assert state["turn_count"] == 2
    assert state["project_metadata"] == data["project_metadata"]


@pytest.mark.asyncio
async def test_pdf_attachment_influences_the_estimation(client, llm):
    transcript = "Proyecto Hotelia: portal de reservas para hoteles pequeños."
    sid_plain = await new_session(client)
    plain = (await estimate(client, sid_plain, transcript)).json()

    sid_pdf = await new_session(client)
    pdf = make_pdf("El despliegue se hara en Kubernetes con 3 nodos")
    with_pdf = await estimate(
        client, sid_pdf, transcript, files=[("attachments", ("infra.pdf", pdf, "application/pdf"))]
    )
    data = with_pdf.json()

    assert with_pdf.status_code == 200
    assert "Kubernetes" not in plain["text"]
    assert "Kubernetes" in data["text"]
    assert "Kubernetes" in data["project_metadata"]["mentioned_technologies"]
    assert "Kubernetes" not in plain["project_metadata"]["mentioned_technologies"]
    current_user_msg = llm.estimator_calls[-1][-1]["content"]
    assert "--- attachment: infra.pdf ---" in current_user_msg

    # El historial guarda solo una marca, no el texto completo del PDF.
    history = (await client.get(f"/api/v1/sessions/{sid_pdf}")).json()["history"]
    assert "[adjuntos: infra.pdf (" in history[0]["user"]
    assert "3 nodos" not in history[0]["user"]


@pytest.mark.asyncio
async def test_history_sent_to_llm_never_exceeds_max_turns(client, llm):
    sid = await new_session(client)

    for i in range(1, 9):
        response = await estimate(client, sid, f"Turno {i}: el cliente añade el requisito {i}.")
        assert response.status_code == 200
        assert response.json()["history_turns"] == min(i - 1, MAX_TURNS)

    for messages in llm.estimator_calls:
        # 1 system + como mucho MAX_TURNS pares + el user del turno actual
        assert len(messages) <= 1 + 2 * MAX_TURNS + 1
        assert sum(m["role"] == "system" for m in messages) == 1

    # En el turno 8 la ventana contiene los turnos 2-7: el 1 ya se ha descartado.
    last_call = " ".join(m["content"] for m in llm.estimator_calls[-1])
    assert "Turno 1:" not in last_call
    assert "Turno 2:" in last_call and "Turno 8:" in last_call

    state = (await client.get(f"/api/v1/sessions/{sid}")).json()
    assert state["turn_count"] == 8
    assert state["history_turns"] == MAX_TURNS


@pytest.mark.asyncio
async def test_unknown_session_is_404(client):
    assert (await client.get("/api/v1/sessions/no-existe")).status_code == 404
    response = await estimate(client, "no-existe", "Proyecto Hotelia: portal de reservas.")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_unsupported_attachment_is_415_and_session_untouched(client):
    sid = await new_session(client)
    response = await estimate(
        client,
        sid,
        "Proyecto Hotelia: portal de reservas.",
        files=[("attachments", ("notas.txt", b"hola", "text/plain"))],
    )
    assert response.status_code == 415
    assert (await client.get(f"/api/v1/sessions/{sid}")).json()["turn_count"] == 0


@pytest.mark.asyncio
async def test_short_transcript_is_422(client):
    sid = await new_session(client)
    assert (await estimate(client, sid, "hola")).status_code == 422


@pytest.mark.asyncio
async def test_llm_failure_does_not_corrupt_session(client):
    failing = FakeLLM(fail_estimator=True)
    app.dependency_overrides[get_llm_wrapper] = lambda: failing
    sid = await new_session(client)

    response = await estimate(client, sid, "Proyecto Hotelia: portal de reservas en React.")

    assert response.status_code == 500
    state = (await client.get(f"/api/v1/sessions/{sid}")).json()
    assert state["turn_count"] == 0
    assert state["history"] == []
    assert state["project_metadata"]["project_name"] is None


@pytest.mark.asyncio
async def test_unknown_prompt_version_is_400(client):
    sid = await new_session(client)
    response = await estimate(
        client, sid, "Proyecto Hotelia: portal de reservas.", prompt_version="v99"
    )
    assert response.status_code == 400
    assert (await client.get(f"/api/v1/sessions/{sid}")).json()["turn_count"] == 0


@pytest.mark.asyncio
async def test_scanned_pdf_returns_warning_not_error(client):
    sid = await new_session(client)
    response = await estimate(
        client,
        sid,
        "Proyecto Hotelia: portal de reservas.",
        files=[("attachments", ("escaneado.pdf", make_pdf(""), "application/pdf"))],
    )
    assert response.status_code == 200
    assert any("escaneado.pdf" in w for w in response.json()["warnings"])


@pytest.mark.asyncio
async def test_empty_llm_answer_is_502_and_not_stored_in_history(client):
    """Un texto vacío en el historial haría que Anthropic rechazara todos los
    turnos siguientes: el turno se rechaza sin tocar la sesión."""
    app.dependency_overrides[get_llm_wrapper] = lambda: FakeLLM(estimator_text="   ")
    sid = await new_session(client)

    response = await estimate(client, sid, "Proyecto Hotelia: portal de reservas en React.")

    assert response.status_code == 502
    state = (await client.get(f"/api/v1/sessions/{sid}")).json()
    assert state["turn_count"] == 0
    assert state["history"] == []


@pytest.mark.asyncio
async def test_response_carries_structured_result_euros_and_tier(client):
    sid = await new_session(client)
    data = (await estimate(client, sid, "Proyecto Hotelia: portal de reservas en React.")).json()

    assert data["result"]["total_hours_min"] == 100
    assert data["cost_min_eur"] == 5000 and data["cost_max_eur"] == 7500
    assert data["tier"] == "default" and data["tier_rule"] == "default"
    assert data["cache_hit_kind"] == "none"
    assert "| Desarrollo |" not in data["text"]  # FORM pide narrative
    assert "5.000–7.500 €" in data["text"]


@pytest.mark.asyncio
async def test_tier_override_and_invalid_tier(client):
    sid = await new_session(client)
    ok = await client.post(f"/api/v1/sessions/{sid}/estimate",
                           data={"transcript": "Proyecto Hotelia: portal de reservas.", **FORM, "tier": "pm"})
    assert ok.json()["tier"] == "pm" and ok.json()["tier_rule"] == "explicit_override"
    bad = await client.post(f"/api/v1/sessions/{sid}/estimate",
                            data={"transcript": "Proyecto Hotelia: portal de reservas.", **FORM, "tier": "ceo"})
    assert bad.status_code == 422


@pytest.mark.asyncio
async def test_structured_failure_is_502_and_session_untouched(client):
    app.dependency_overrides[get_llm_wrapper] = lambda: FakeLLM(
        structured_responses=["no json", "no json", "no json"])
    sid = await new_session(client)
    response = await estimate(client, sid, "Proyecto Hotelia: portal de reservas en React.")
    assert response.status_code == 502
    assert (await client.get(f"/api/v1/sessions/{sid}")).json()["turn_count"] == 0


@pytest.mark.asyncio
async def test_anchor_survives_eviction_and_reaches_the_prompt(client, llm):
    sid = await new_session(client)
    await estimate(client, sid, "Proyecto Hotelia: el presupuesto está cerrado en 30.000 euros.")
    for i in range(2, 9):
        await estimate(client, sid, f"Turno {i}: el cliente añade el requisito {i}.")

    # El turno 1 sale de la ventana al cerrar el turno 7 y se promueve a ancla;
    # el prompt del turno 8 ya lo lleva en el bloque <anchors>.
    state = (await client.get(f"/api/v1/sessions/{sid}")).json()
    assert state["anchors_count"] == 1
    assert state["anchors"][0]["rule"] == "budget_locked"
    assert state["history_turns"] == MAX_TURNS
    last_system = llm.estimator_calls[-1][0]["content"]
    assert "presupuesto está cerrado en 30.000" in last_system


@pytest.mark.asyncio
async def test_turn_eight_creates_summary(client, llm):
    sid = await new_session(client)
    for i in range(1, 9):
        await estimate(client, sid, f"Turno {i}: el cliente añade el requisito {i}.")
    state = (await client.get(f"/api/v1/sessions/{sid}")).json()
    assert state["summary_chars"] > 0
    assert len(llm.summarizer_calls) == 2  # turnos 7 y 8
    assert "Resumen acumulado" in llm.estimator_calls[-1][0]["content"]


@pytest_asyncio.fixture
async def cached_client(llm):
    import fakeredis
    from app.services.session_cache import SessionTurnCache

    store = SessionStore(max_turns=MAX_TURNS)
    cache = SessionTurnCache(fakeredis.FakeRedis(decode_responses=True), embedder=None,
                             threshold=0.92, log_only=False, ttl=60)
    app.dependency_overrides[get_session_store] = lambda: store
    app.dependency_overrides[get_llm_wrapper] = lambda: llm
    app.dependency_overrides[get_session_cache] = lambda: cache
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_turn_one_exact_hit_only_pays_moderation(cached_client, llm):
    text = "Proyecto Hotelia: portal de reservas en React."
    first = (await estimate(cached_client, await new_session(cached_client), text)).json()
    calls_before = len(llm.calls)
    sid2 = await new_session(cached_client)
    second = (await estimate(cached_client, sid2, text)).json()

    assert first["cache_hit_kind"] == "none" and second["cache_hit_kind"] == "exact"
    # Los guardrails van antes de la caché: un acierto solo paga la moderación.
    assert llm.kinds[calls_before:] == ["moderator"]
    assert second["project_metadata"]["project_name"] == "Hotelia"
    state = (await cached_client.get(f"/api/v1/sessions/{sid2}")).json()
    assert state["turn_count"] == 1 and len(state["history"]) == 1


@pytest.mark.asyncio
async def test_turn_two_never_uses_cache(cached_client):
    sid = await new_session(cached_client)
    await estimate(cached_client, sid, "Proyecto Hotelia: portal de reservas en React.")
    second = (await estimate(cached_client, sid, "Proyecto Hotelia: portal de reservas en React.")).json()
    assert second["cache_hit_kind"] == "none"


@pytest.mark.asyncio
async def test_semantic_hit_reextracts_metadata_from_the_real_transcript(llm):
    """La estimación puede reutilizarse, pero los hechos del proyecto salen del
    mensaje real, no del que se cacheó."""
    import fakeredis
    from app.services.session_cache import SessionTurnCache

    emb = {"Proyecto Hotelia: portal de reservas en React.": [1.0, 0.0],
           "Proyecto Hotelia: portal de reservas con FastAPI.": [0.99, 0.01]}
    cache = SessionTurnCache(fakeredis.FakeRedis(decode_responses=True), embedder=lambda t: emb[t],
                             threshold=0.92, log_only=False, ttl=60)
    store = SessionStore(max_turns=MAX_TURNS)
    app.dependency_overrides[get_session_store] = lambda: store
    app.dependency_overrides[get_llm_wrapper] = lambda: llm
    app.dependency_overrides[get_session_cache] = lambda: cache
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            await estimate(c, await new_session(c), "Proyecto Hotelia: portal de reservas en React.")
            second = (await estimate(c, await new_session(c),
                                     "Proyecto Hotelia: portal de reservas con FastAPI.")).json()
    finally:
        app.dependency_overrides.clear()

    assert second["cache_hit_kind"] == "semantic"
    assert second["project_metadata"]["mentioned_technologies"] == ["FastAPI"]


@pytest.mark.asyncio
async def test_each_turn_returns_an_aggregated_observation(client):
    from app.services.conversation import OBSERVATION_FIELDS

    sid = await new_session(client)
    pdf = make_pdf("Despliegue en Kubernetes")
    data = (await estimate(client, sid, "Proyecto Hotelia: portal de reservas en React.",
                           files=[("attachments", ("a.pdf", pdf, "application/pdf"))])).json()
    obs = data["observation"]

    assert set(OBSERVATION_FIELDS) <= set(obs)
    assert len(OBSERVATION_FIELDS) == 13
    assert obs["turn_index"] == 1 and obs["session_id"] == sid
    assert obs["attachments_total_chars"] > 0
    assert obs["enriched_transcript_chars"] > obs["attachments_total_chars"]
    assert obs["messages_in_window"] == 2
    assert obs["cache_hit_kind"] == "none" and obs["last_resolved_tier"] == "default"
    assert obs["llm_calls"] == 3  # moderador + estimador + extractor
    assert obs["latency_ms"] >= 0

    state = (await client.get(f"/api/v1/sessions/{sid}")).json()
    assert state["last_turn_observed"] == obs


@pytest.mark.asyncio
async def test_observation_counts_summarizer_and_window_after_compression(client):
    sid = await new_session(client)
    for i in range(1, 8):
        data = (await estimate(client, sid, f"Turno {i}: el cliente añade el requisito {i}.")).json()
    obs = data["observation"]
    assert obs["turn_index"] == 7
    assert obs["llm_calls"] == 4  # moderador + estimador + extractor + resumidor
    assert obs["messages_in_window"] == 2 * MAX_TURNS
    assert obs["summary_chars"] > 0


@pytest.mark.asyncio
async def test_invalid_cached_payload_falls_back_to_the_llm(llm):
    """Un payload de caché de un esquema antiguo se trata como fallo de caché."""
    from app.services.session_cache import CacheHit

    class StaleCache:
        stored = []

        def exact_key(self, *a):
            return "k"

        def bucket(self, *a):
            return "b"

        def lookup(self, **k):
            return CacheHit(kind="exact", payload={"result": {"viejo": True}})

        def store(self, **k):
            self.stored.append(k)

    cache = StaleCache()
    store = SessionStore(max_turns=MAX_TURNS)  # una sola instancia para las dos peticiones
    app.dependency_overrides[get_session_store] = lambda: store
    app.dependency_overrides[get_llm_wrapper] = lambda: llm
    app.dependency_overrides[get_session_cache] = lambda: cache
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            data = (await estimate(c, await new_session(c), "Proyecto Hotelia: portal de reservas.")).json()
    finally:
        app.dependency_overrides.clear()

    assert data["cache_hit_kind"] == "none"
    assert len(llm.estimator_calls) == 1  # se llamó al LLM
    assert len(cache.stored) == 1  # y se guardó la respuesta buena
