# 🧮 Estimador de Software — servicio IA + cliente

Servicio FastAPI que convierte una descripción de proyecto en una estimación técnica,
con prompts versionados en Jinja2 y un contrato tipado con el cliente.

## 🎯 Qué cambia en esta rama

La sesión 03 dejaba un chat libre y un prompt construido como f-string dentro del
wrapper. Esta rama sustituye ambas cosas:

| Antes | Ahora |
|---|---|
| `transcription: str` como única entrada | `EstimationRequest` con enums de tipo, detalle y formato |
| Prompt f-string en `llm_service.py` | Plantillas `.j2` versionadas + `loader.py` |
| Un solo mensaje concatenado al LLM | `system` y `user` como mensajes separados |
| Sin tests de prompt | Suite de template que corre en milisegundos, sin red |

El chat libre **no se elimina**: convive con el formulario en una segunda pestaña del
cliente, para que la entrega de la sesión 03 siga siendo verificable.

## 🏗️ Estructura

```
app/
├── main.py                  # FastAPI + structlog + middleware de request_id
├── config.py                # Settings (pydantic-settings, .env)
├── schemas.py               # Contrato tipado cliente ↔ servicio
├── observability.py         # Configuración de structlog
├── routers/
│   └── estimations.py       # POST /estimate, POST /estimate/stream, GET /prompt-versions
├── services/
│   ├── llm_service.py       # Wrapper OpenAI/Anthropic + orquestación
│   └── cache.py             # Caché de coincidencia exacta (LRU en memoria)
├── prompts/
│   ├── loader.py            # render_estimation_prompt(request, version) -> (system, user)
│   └── estimation/
│       ├── v1/              # system.j2 · user.j2 · examples.j2
│       └── v2/              # variación deliberada: tono y ejemplos distintos
└── context/
    └── examples.py          # Ejemplos CAG del chat libre (sesión 02)
streamlit_app.py             # Cliente: pestaña formulario + pestaña chat
tests/prompts/               # Tests de template
```

## ⚙️ Instalación

```bash
uv sync --extra dev
```

`.env` en la raíz (ignorado por Git):

```env
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-haiku-4-5-20251001
API_BASE_URL=http://localhost:8000/api/v1
PROMPT_VERSION=v1
```

Sin comillas ni espacios alrededor del `=`: `python-dotenv` no parsea la línea y la
variable queda a `None`.

## 🚀 Ejecución

El cliente llama al servicio por HTTP, así que hacen falta dos procesos:

```bash
# Terminal 1 — servicio IA
uv run uvicorn app.main:app --reload

# Terminal 2 — cliente
uv run streamlit run streamlit_app.py
```

Servicio en `http://localhost:8000/docs`, cliente en `http://localhost:8501`.

## ✅ Tests

```bash
uv run pytest tests/prompts -v
```

Son tests **del template, no del modelo**: no hacen red y corren en milisegundos.
Cubren tres cosas:

1. Que `description` llega literal dentro del bloque `<project_description>`.
2. Que el bloque condicional de `output_format` inyecta `phases_table` y
   `confidence_pct` solo cuando toca, y no los inyecta en `narrative`.
3. Que `detail_level=detailed` añade la instrucción de listar asunciones por fase,
   y que `summary` no la incluye.

Lo que **no** cubren: si el modelo obedece esas instrucciones. Eso es evaluación del
modelo, no del template, y requiere otra clase de suite.

## 🔀 Versionado de prompts

Cada versión es un directorio completo bajo `app/prompts/estimation/`. Cambiar de
versión no toca código:

```python
system, user = render_estimation_prompt(request, version="v2")
```

O desde la API:

```bash
curl -X POST "http://localhost:8000/api/v1/estimate?prompt_version=v2" \
  -H "Content-Type: application/json" \
  -d '{
    "description": "Plataforma web para gestionar altas de socios y reservas de clases en una red de gimnasios.",
    "project_type": "web_saas",
    "detail_level": "detailed",
    "output_format": "phases_table"
  }'
```

`v2` mantiene el mismo contrato de formato pero cambia el tono (de consultor a
principal engineer hablando con un CTO) y sustituye los ejemplos por dos referencias
de calibración con su desviación real frente a lo estimado.

`GET /prompt-versions` lista las disponibles. El `Environment` usa `StrictUndefined`,
así que una variable ausente rompe en el render y la recoge el test, no producción.

## 📊 Observabilidad

`structlog` emite consola legible en `development` y JSON en cualquier otro entorno.
Cada petición HTTP lleva un `request_id` en contextvars y en la cabecera
`X-Request-ID`. Eventos relevantes: `prompt_rendered` (con versión y hash del
contenido renderizado), `llm_call_completed`, `cache_hit` / `cache_miss`.

El hash del prompt renderizado es lo que permite responder a "¿qué texto exacto vio
el modelo en esta petición?" sin guardar el prompt entero en los logs.

## 🗃️ Caché

Coincidencia exacta sobre `sha256(provider + model + system + user)`, LRU en memoria
del proceso con 128 entradas. No sobrevive a un reinicio ni se comparte entre workers.
El endpoint de streaming no cachea: el cuerpo se consume una sola vez.

## 📝 Notas

- El SDK de `anthropic` fijado en este proyecto no acepta `temperature` en
  `messages.stream()`. Las llamadas en streaming van sin ese parámetro a propósito;
  las bloqueantes sí lo usan en OpenAI.
- La respuesta sigue siendo **texto libre**. Salida JSON estructurada, guardarraíles y
  cacheo semántico quedan para el directo.
