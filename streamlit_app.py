"""Cliente Streamlit del estimador de software.

Tres modos:

- **Formulario** (sesión 04): formulario tipado que construye un ``EstimationRequest``
  y hace ``POST /estimate`` contra el servicio IA. El prompt se renderiza en el
  servidor desde una plantilla Jinja2 versionada.
- **Conversación** (sesión 05): sesión con ``session_id`` contra el servicio IA.
  Varios turnos sobre el mismo proyecto, adjuntos PDF/Word, y un panel lateral
  con el ``project_metadata`` (memoria) separado del historial.
- **Chat** (sesión 03): chat conversacional con streaming, que llama al LLM
  directamente con el system prompt CAG. Se conserva para no perder la entrega anterior.

Ejecutar desde la raíz del proyecto:

    uv run streamlit run streamlit_app.py
"""

import time

import requests
import streamlit as st
from anthropic import Anthropic

from app.config import get_settings
from app.context.examples import ESTIMATION_EXAMPLES
from app.prompts.loader import available_versions
from app.schemas import DetailLevel, OutputFormat, ProjectType
from app.services.llm_service import build_cag_system_prompt

MAX_TOKENS = 4000
REQUEST_TIMEOUT = 180

PROJECT_TYPE_LABELS = {
    ProjectType.WEB_SAAS: "SaaS web",
    ProjectType.MOBILE_APP: "App móvil",
    ProjectType.INTERNAL_TOOL: "Herramienta interna",
    ProjectType.DATA_PIPELINE: "Pipeline de datos",
}

DETAIL_LEVEL_LABELS = {
    DetailLevel.SUMMARY: "Resumen",
    DetailLevel.MEDIUM: "Medio",
    DetailLevel.DETAILED: "Detallado",
}

OUTPUT_FORMAT_LABELS = {
    OutputFormat.PHASES_TABLE: "Tabla por fases",
    OutputFormat.LINE_ITEMS: "Partidas por categoría",
    OutputFormat.NARRATIVE: "Narrativa",
}

st.set_page_config(page_title="Estimador de Software", page_icon="🧮", layout="wide")

settings = get_settings()

if not settings.ANTHROPIC_API_KEY:
    st.error(
        "No hay ninguna API key configurada. Define ANTHROPIC_API_KEY "
        "en tu archivo .env (no la escribas en el código)."
    )
    st.stop()

if "messages" not in st.session_state:
    st.session_state.messages = []
if "last_metrics" not in st.session_state:
    st.session_state.last_metrics = None
if "last_estimation" not in st.session_state:
    st.session_state.last_estimation = None
if "last_fallback" not in st.session_state:
    st.session_state.last_fallback = None
if "conv_session_id" not in st.session_state:
    st.session_state.conv_session_id = None
if "conv_turns" not in st.session_state:
    st.session_state.conv_turns = []
if "conv_notice" not in st.session_state:
    st.session_state.conv_notice = None
# Cambiar este número da claves nuevas al texto y a los adjuntos, que así se
# vacían; los selectores conservan su valor entre turnos.
if "conv_form_nonce" not in st.session_state:
    st.session_state.conv_form_nonce = 0


def create_session(base_url: str) -> str | None:
    """POST /sessions. ``None`` si el servicio no responde."""
    try:
        response = requests.post(f"{base_url}/sessions", timeout=10)
        response.raise_for_status()
        return response.json()["session_id"]
    except requests.exceptions.RequestException:
        return None


def reset_conversation(base_url: str, notice: str | None = None) -> None:
    st.session_state.conv_session_id = create_session(base_url)
    st.session_state.conv_turns = []
    st.session_state.conv_notice = notice


def fetch_session_state(base_url: str, session_id: str, retry: bool = True) -> dict | None:
    """GET /sessions/{id}. Si la sesión ya no existe (backend reiniciado),
    crea una nueva, avisa y devuelve su estado. ``None`` si no hay servicio.
    """
    try:
        response = requests.get(f"{base_url}/sessions/{session_id}", timeout=10)
    except requests.exceptions.RequestException:
        return None
    if response.status_code == 404 and retry:
        reset_conversation(
            base_url,
            notice="La sesión anterior expiró (el servicio se reinició). Se ha creado una nueva.",
        )
        new_id = st.session_state.conv_session_id
        return fetch_session_state(base_url, new_id, retry=False) if new_id else None
    if not response.ok:
        return None
    return response.json()


# --------------------------------------------------------------------------- #
# Sidebar
# --------------------------------------------------------------------------- #

with st.sidebar:
    st.header("Configuración")
    st.caption(f"Proveedor: `anthropic` · Modelo: `{settings.ANTHROPIC_MODEL}`")

    try:
        versions = available_versions()
    except Exception:  # noqa: BLE001
        versions = [settings.PROMPT_VERSION]

    prompt_version = st.selectbox(
        "Versión del prompt",
        versions,
        index=versions.index(settings.PROMPT_VERSION) if settings.PROMPT_VERSION in versions else 0,
        help="Selecciona la plantilla Jinja2 que renderizará el servicio.",
    )

    api_base_url = st.text_input("URL del servicio IA", settings.API_BASE_URL)

    conv_base_url = api_base_url.rstrip("/")
    if st.session_state.conv_session_id is None:
        st.session_state.conv_session_id = create_session(conv_base_url)

    st.divider()
    st.subheader("Memoria de la conversación")
    conv_state = (
        fetch_session_state(conv_base_url, st.session_state.conv_session_id)
        if st.session_state.conv_session_id
        else None
    )
    if conv_state is None:
        st.caption("Servicio no disponible: no se pudo crear la sesión.")
    else:
        st.caption(
            f"Sesión `{conv_state['session_id'][:8]}` · {conv_state['turn_count']} turnos en total"
        )
        st.metric(
            "Turnos en la ventana (historial)",
            f"{conv_state['history_turns']}/{conv_state['max_turns']}",
        )
        md = conv_state["project_metadata"]
        st.markdown("**project_metadata** (memoria, va en el system prompt)")
        st.table(
            {
                "Campo": ["Proyecto", "Equipo asumido", "Tecnologías", "Alcance acordado"],
                "Valor": [
                    md["project_name"] or "—",
                    f"{md['assumed_team_size']} personas" if md["assumed_team_size"] else "—",
                    ", ".join(md["mentioned_technologies"]) or "—",
                    md["agreed_scope"] or "—",
                ],
            }
        )
    if st.button("Nueva conversación", use_container_width=True):
        reset_conversation(conv_base_url)
        st.rerun()

    st.divider()
    st.subheader("Última llamada")
    metrics = st.session_state.last_metrics
    if metrics:
        for label, value in metrics.items():
            st.metric(label, value)
    else:
        st.caption("Todavía no se ha realizado ninguna llamada.")

    st.divider()
    with st.expander("Contexto CAG del modo chat"):
        st.caption(f"{len(ESTIMATION_EXAMPLES)} ejemplos estáticos inyectados.")
        for i, example in enumerate(ESTIMATION_EXAMPLES, start=1):
            st.markdown(f"**Ejemplo {i}**")
            st.caption(example["meeting_summary"])

    if st.button("Limpiar conversación", use_container_width=True):
        st.session_state.messages = []
        st.session_state.last_metrics = None
        st.session_state.last_estimation = None
        st.session_state.last_fallback = None
        st.rerun()


st.title("🧮 Estimador de Software")

tab_form, tab_conv, tab_chat = st.tabs(
    ["Formulario tipado", "Conversación (sesión 05)", "Chat libre (sesión 03)"]
)


# --------------------------------------------------------------------------- #
# Modo formulario: contrato tipado contra el servicio IA
# --------------------------------------------------------------------------- #

with tab_form:
    st.caption(
        "Describe el proyecto y elige las opciones. El cliente envía un "
        "`EstimationRequest` al servicio, que renderiza el prompt versionado."
    )

    with st.form("estimation_form"):
        description = st.text_area(
            "Descripción del proyecto",
            height=200,
            placeholder=(
                "Plataforma web para que una red de gimnasios gestione altas de socios, "
                "reservas de clases y cobros mensuales…"
            ),
            help="Entre 20 y 20.000 caracteres.",
        )

        col1, col2, col3 = st.columns(3)
        project_type = col1.selectbox(
            "Tipo de proyecto",
            list(ProjectType),
            format_func=lambda x: PROJECT_TYPE_LABELS[x],
        )
        detail_level = col2.selectbox(
            "Nivel de detalle",
            list(DetailLevel),
            index=1,
            format_func=lambda x: DETAIL_LEVEL_LABELS[x],
        )
        output_format = col3.selectbox(
            "Formato de salida",
            list(OutputFormat),
            format_func=lambda x: OUTPUT_FORMAT_LABELS[x],
        )

        submitted = st.form_submit_button("Generar estimación", type="primary")

    if submitted:
        if len(description.strip()) < 20:
            st.error("La descripción debe tener al menos 20 caracteres.")
        else:
            payload = {
                "description": description.strip(),
                "project_type": project_type.value,
                "detail_level": detail_level.value,
                "output_format": output_format.value,
            }

            started = time.time()
            try:
                response = requests.post(
                    f"{api_base_url.rstrip('/')}/estimate",
                    json=payload,
                    params={"prompt_version": prompt_version},
                    timeout=REQUEST_TIMEOUT,
                )
                response.raise_for_status()
                data = response.json()
            except requests.exceptions.ConnectionError:
                st.error(
                    f"No se pudo conectar con el servicio en {api_base_url}. "
                    "Levántalo con `uv run uvicorn app.main:app --reload`."
                )
                data = None
            except requests.exceptions.HTTPError as exc:
                detail = ""
                try:
                    detail = exc.response.json().get("detail", "")
                except Exception:  # noqa: BLE001
                    detail = exc.response.text
                st.error(f"El servicio devolvió {exc.response.status_code}: {detail}")
                data = None
            except Exception as exc:  # noqa: BLE001
                st.error(f"Error inesperado: {exc}")
                data = None

            if data:
                elapsed = time.time() - started
                st.session_state.last_estimation = data["text"]
                st.session_state.last_metrics = {
                    "Modelo": data["model"],
                    "Versión prompt": data["prompt_version"],
                    "Caché": "hit" if data["cached"] else "miss",
                    "Tiempo": f"{elapsed:.2f} s",
                }
                st.session_state.last_fallback = (
                    data["model"] if data.get("fallback_used") else None
                )
                st.rerun()

    if st.session_state.last_estimation:
        st.divider()
        if st.session_state.last_fallback:
            st.warning(
                f"El proveedor principal falló: esta respuesta la generó el "
                f"modelo de respaldo (`{st.session_state.last_fallback}`)."
            )
        st.markdown(st.session_state.last_estimation)


# --------------------------------------------------------------------------- #
# Modo conversación (sesión 05): memoria + adjuntos contra el servicio IA
# --------------------------------------------------------------------------- #

with tab_conv:
    st.caption(
        "Conversación de varios turnos sobre el mismo proyecto. El servicio guarda el "
        "historial (ventana deslizante) y extrae los hechos del proyecto al panel lateral."
    )
    if st.session_state.conv_notice:
        st.info(st.session_state.conv_notice)
        st.session_state.conv_notice = None

    for turn in st.session_state.conv_turns:
        with st.chat_message("user"):
            st.markdown(turn["transcript"])
            if turn["files"]:
                st.caption("📎 " + ", ".join(turn["files"]))
        with st.chat_message("assistant"):
            for warning in turn["warnings"]:
                st.warning(warning)
            if turn["fallback_used"]:
                st.warning(f"Respuesta generada por el modelo de respaldo (`{turn['model']}`).")
            st.markdown(turn["text"])
            st.caption(
                f"Turno {turn['turn']} · {turn['provider']} · `{turn['model']}` · "
                f"{turn['history_turns']} pares de historial enviados · {turn['elapsed']:.1f} s"
            )

    nonce = st.session_state.conv_form_nonce
    with st.form("conversation_form"):
        conv_transcript = st.text_area(
            "Mensaje / transcripción",
            height=150,
            placeholder="Proyecto Hotelia: portal de reservas para hoteles pequeños…",
            help="Entre 20 y 20.000 caracteres.",
            key=f"conv_transcript_{nonce}",
        )
        c1, c2, c3 = st.columns(3)
        conv_project_type = c1.selectbox(
            "Tipo de proyecto",
            list(ProjectType),
            format_func=lambda x: PROJECT_TYPE_LABELS[x],
            key="conv_project_type",
        )
        conv_detail_level = c2.selectbox(
            "Nivel de detalle",
            list(DetailLevel),
            index=1,
            format_func=lambda x: DETAIL_LEVEL_LABELS[x],
            key="conv_detail_level",
        )
        conv_output_format = c3.selectbox(
            "Formato de salida",
            list(OutputFormat),
            format_func=lambda x: OUTPUT_FORMAT_LABELS[x],
            key="conv_output_format",
        )
        conv_files = st.file_uploader(
            "Adjuntos (PDF o Word, máx. 3 MB cada uno)",
            type=["pdf", "docx"],
            accept_multiple_files=True,
            key=f"conv_files_{nonce}",
        )
        conv_submitted = st.form_submit_button("Enviar turno", type="primary")

    if conv_submitted:
        sid = st.session_state.conv_session_id
        if not sid:
            st.error("No hay sesión: comprueba que el servicio IA está levantado.")
        elif len(conv_transcript.strip()) < 20:
            st.error("El mensaje debe tener al menos 20 caracteres.")
        else:
            files = [
                ("attachments", (f.name, f.getvalue(), f.type or "application/octet-stream"))
                for f in conv_files or []
            ]
            started = time.time()
            data = None
            try:
                with st.spinner("Estimando (2 llamadas: estimación + extracción de memoria)…"):
                    response = requests.post(
                        f"{conv_base_url}/sessions/{sid}/estimate",
                        data={
                            "transcript": conv_transcript.strip(),
                            "project_type": conv_project_type.value,
                            "detail_level": conv_detail_level.value,
                            "output_format": conv_output_format.value,
                        },
                        files=files or None,
                        timeout=REQUEST_TIMEOUT,
                    )
                if response.status_code == 404:
                    reset_conversation(
                        conv_base_url,
                        notice=(
                            "La sesión expiró (el servicio se reinició). "
                            "Se ha creado una nueva: pulsa «Enviar turno» de nuevo."
                        ),
                    )
                    st.rerun()
                response.raise_for_status()
                data = response.json()
            except requests.exceptions.HTTPError as exc:
                try:
                    detail = exc.response.json().get("detail", "")
                except Exception:  # noqa: BLE001
                    detail = exc.response.text
                st.error(f"El servicio devolvió {exc.response.status_code}: {detail}")
            except requests.exceptions.ConnectionError:
                st.error(f"No se pudo conectar con el servicio en {conv_base_url}.")
            except requests.exceptions.Timeout:
                st.error("El servicio tardó demasiado en responder.")

            if data:
                st.session_state.conv_turns.append(
                    {
                        "transcript": conv_transcript.strip(),
                        "files": [f.name for f in conv_files or []],
                        "elapsed": time.time() - started,
                        **data,
                    }
                )
                st.session_state.conv_form_nonce += 1
                st.rerun()


# --------------------------------------------------------------------------- #
# Modo chat: entrega de la sesión 03, con streaming
# --------------------------------------------------------------------------- #

with tab_chat:
    st.caption(
        "Chat conversacional con streaming. Llama al LLM directamente con el system "
        "prompt CAG, sin pasar por el servicio ni por el contrato tipado."
    )

    if not settings.ANTHROPIC_API_KEY:
        st.info("El modo chat requiere una ANTHROPIC_API_KEY.")
    else:
        client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        system_prompt = build_cag_system_prompt()

        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

        prompt = st.chat_input("Pega aquí la transcripción de la reunión...")

        if prompt:
            st.session_state.messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)

            with st.chat_message("assistant"):
                usage_holder = {}
                started = time.time()

                def stream_deltas():
                    with client.messages.stream(
                        model=settings.ANTHROPIC_MODEL,
                        max_tokens=MAX_TOKENS,
                        system=system_prompt,
                        messages=[
                            {
                                "role": "user",
                                "content": f"Transcripción de la reunión:\n\n{prompt}",
                            }
                        ],
                    ) as stream:
                        for text in stream.text_stream:
                            yield text
                        usage_holder["usage"] = stream.get_final_message().usage

                try:
                    full_response = st.write_stream(stream_deltas())
                except Exception as exc:  # noqa: BLE001
                    full_response = f"⚠️ Error al generar la estimación: {exc}"
                    st.error(full_response)

                elapsed = time.time() - started

            st.session_state.messages.append(
                {"role": "assistant", "content": full_response}
            )

            usage = usage_holder.get("usage")
            st.session_state.last_metrics = {
                "Modelo": settings.ANTHROPIC_MODEL,
                "Tokens entrada": usage.input_tokens if usage else "—",
                "Tokens salida": usage.output_tokens if usage else "—",
                "Tiempo": f"{elapsed:.2f} s",
            }
            st.rerun()
