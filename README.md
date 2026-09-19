# 🖥️ Sesión 03: Interfaz conversacional con Streamlit

Capa de interfaz sobre el estimador de software CAG de la [sesión 02](../../tree/sesion-02-cag).
Permite pegar una transcripción de reunión en un chat web y ver la estimación generándose
token a token, sin pasar por `curl`, Postman ni Swagger.

## 🔌 Qué reutiliza del backend

La app **no duplica lógica**. Importa directamente del paquete `app/`:

| Import | Uso en la interfaz |
|---|---|
| `app.config.get_settings()` | API key, modelo y proveedor, leídos de `.env` vía `pydantic-settings` |
| `app.services.llm_service.build_cag_system_prompt()` | Mismo system prompt que el endpoint `POST /api/v1/estimate` |
| `app.context.examples.ESTIMATION_EXAMPLES` | Ejemplos estáticos CAG, mostrados en el panel lateral |

La única diferencia con `call_anthropic()` es el modo de llamada: `client.messages.stream(...)`
en lugar de `client.messages.create(...)`. Parámetros idénticos (`max_tokens=4000`, `temperature=0.3`).

## 📐 Niveles implementados

- **Nivel 1 — Chat básico**: `st.chat_message` + `st.chat_input`, historial persistido en `st.session_state.messages`.
- **Nivel 2 — Streaming**: generador de deltas (`stream.text_stream`) consumido por `st.write_stream`.
- **Nivel 3 — Contexto CAG visible**: `st.sidebar` con system prompt en solo lectura, los ejemplos
  estáticos inyectados, y métricas de la última llamada (modelo, tokens de entrada/salida, latencia).

## ⚙️ Instalación

```bash
uv sync --extra dev
```

Configura `.env` en la raíz (nunca se commitea, está en `.gitignore`):

```env
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-haiku-4-5-20251001
```

## 🚀 Ejecución

```bash
uv run streamlit run streamlit_app.py
```

Abre `http://localhost:8501`. El backend FastAPI sigue disponible de forma independiente:

```bash
uv run uvicorn app.main:app --reload
```

## 🔐 Gestión de secretos

La clave nunca aparece en el código. Se resuelve en este orden:

1. `Settings` (pydantic-settings) lee `.env` o las variables de entorno del sistema.
2. `streamlit_app.py` valida `settings.ANTHROPIC_API_KEY` al arrancar y corta con `st.stop()`
   si falta, mostrando un error explícito en vez de fallar en la primera llamada.

Para despliegue en Streamlit Community Cloud, define `ANTHROPIC_API_KEY` en `st.secrets`:
`pydantic-settings` la recogerá igualmente porque Streamlit la expone como variable de entorno.

## ✅ Lista de verificación

- [x] `streamlit run streamlit_app.py` abre la interfaz de chat en el navegador
- [x] Se puede pegar una transcripción y recibir una estimación de software
- [x] La conversación persiste en pantalla entre turnos
- [x] La respuesta se muestra en streaming, no de golpe
- [x] La API key se lee de `.env`, no está en el código
- [x] Panel lateral con system prompt, contexto CAG y métricas de la última llamada
