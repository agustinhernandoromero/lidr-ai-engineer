"""Cliente Streamlit del estimador de software.

Dos modos:

- **Formulario** (sesión 04): formulario tipado que construye un ``EstimationRequest``
  y hace ``POST /estimate`` contra el servicio IA. El prompt se renderiza en el
  servidor desde una plantilla Jinja2 versionada.
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

tab_form, tab_chat = st.tabs(["Formulario tipado", "Chat libre (sesión 03)"])


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
