"""
Interfaz conversacional en Streamlit para el Proyecto 1 (Estimador de Software CAG).

Reutiliza la configuración (app.config) y el system prompt CAG (app.services.llm_service)
del backend FastAPI de la sesión 02. Ejecutar desde la raíz del proyecto con:

    uv run streamlit run streamlit_app.py
"""

import time

import streamlit as st
from anthropic import Anthropic

from app.config import get_settings
from app.context.examples import ESTIMATION_EXAMPLES
from app.services.llm_service import build_cag_system_prompt

MAX_TOKENS = 4000
TEMPERATURE = 0.3

st.set_page_config(page_title="Estimador de Software (CAG)", page_icon="🧮", layout="wide")

settings = get_settings()

if not settings.ANTHROPIC_API_KEY:
    st.error(
        "ANTHROPIC_API_KEY no está configurada. Define la variable en tu archivo .env "
        "(no la escribas en el código)."
    )
    st.stop()

client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
SYSTEM_PROMPT = build_cag_system_prompt()

if "messages" not in st.session_state:
    st.session_state.messages = []
if "last_metrics" not in st.session_state:
    st.session_state.last_metrics = None

# --- Sidebar: contexto CAG activo y métricas (Nivel 3) ---
with st.sidebar:
    st.header("Contexto CAG activo")
    st.caption(f"Proveedor: `{settings.LLM_PROVIDER}` · Modelo: `{settings.ANTHROPIC_MODEL}`")

    with st.expander("System prompt (solo lectura)"):
        st.text_area(
            "System prompt",
            SYSTEM_PROMPT,
            height=300,
            disabled=True,
            label_visibility="collapsed",
        )

    with st.expander(f"Ejemplos estáticos inyectados ({len(ESTIMATION_EXAMPLES)})"):
        for i, example in enumerate(ESTIMATION_EXAMPLES, start=1):
            st.markdown(f"**Ejemplo {i}**")
            st.caption(example["meeting_summary"])

    st.divider()
    st.subheader("Última llamada")
    metrics = st.session_state.last_metrics
    if metrics:
        st.metric("Modelo", metrics["model"])
        col1, col2 = st.columns(2)
        col1.metric("Tokens entrada", metrics["input_tokens"])
        col2.metric("Tokens salida", metrics["output_tokens"])
        st.metric("Tiempo de respuesta", f"{metrics['elapsed']:.2f} s")
    else:
        st.caption("Todavía no se ha realizado ninguna llamada.")

    st.divider()
    if st.button("Limpiar conversación", use_container_width=True):
        st.session_state.messages = []
        st.session_state.last_metrics = None
        st.rerun()

# --- Chat (Nivel 1 + Nivel 2) ---
st.title("🧮 Estimador de Software â€” CAG")
st.caption(
    "Pega la transcripción de una reunión de requerimientos y recibe una estimación "
    "técnica generada por el LLM, en streaming."
)

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
        start = time.time()

        def stream_deltas():
            """Generador de deltas de texto para st.write_stream (Nivel 2)."""
            with client.messages.stream(
                model=settings.ANTHROPIC_MODEL,
                max_tokens=MAX_TOKENS,
                # temperature=TEMPERATURE,  # SDK antiguo: messages.stream() no lo acepta
                system=SYSTEM_PROMPT,
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
            full_response = f"âš ï¸ Error al generar la estimación: {exc}"
            st.error(full_response)

        elapsed = time.time() - start

    st.session_state.messages.append({"role": "assistant", "content": full_response})

    usage = usage_holder.get("usage")
    st.session_state.last_metrics = {
        "model": settings.ANTHROPIC_MODEL,
        "input_tokens": usage.input_tokens if usage else "â€”",
        "output_tokens": usage.output_tokens if usage else "â€”",
        "elapsed": elapsed,
    }
    st.rerun()
