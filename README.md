# 🧮 Estimador de Software — servicio IA + cliente

Servicio FastAPI que convierte una descripción de proyecto en una estimación técnica,
con prompts versionados en Jinja2 y un contrato tipado con el cliente.

## 🎯 Qué cambia en esta rama (sesión 05)

Hasta la sesión 04 el estimador era transaccional: una transcripción entra, una
estimación sale. Esta rama lo convierte en **conversacional**:

| Antes | Ahora |
|---|---|
| Cada petición es independiente | Sesiones con `session_id` (`POST /sessions`) |
| Solo texto | Adjuntos PDF y Word en `multipart/form-data` |
| Sin memoria | Historial con ventana deslizante + `project_metadata` en el system prompt |
| Formulario de una sola estimación | Pestaña "Conversación" con panel de memoria |

Detalle en [💬 Sesión 05](#-sesión-05--conversación-con-memoria-y-adjuntos). Lo que
cambió en sesiones anteriores sigue debajo.

### Sesión 04

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
│   ├── estimations.py       # POST /estimate, POST /estimate/stream, GET /prompt-versions
│   └── sessions.py          # POST /sessions, GET /sessions/{id}, POST /sessions/{id}/estimate
├── services/
│   ├── llm_service.py       # Wrapper de Anthropic (+ fallback a Gemini), recibe messages
│   ├── cache.py             # Caché de coincidencia exacta (Redis)
│   ├── sessions.py          # ConversationHistory, ProjectMetadata, Session, SessionStore
│   ├── attachments.py       # Extracción de texto de PDF y Word
│   ├── metadata_extractor.py # 2ª llamada al LLM: hechos del proyecto en JSON
│   └── conversation.py      # run_turn: orquesta un turno de la conversación
├── prompts/
│   ├── loader.py            # render_estimation_prompt / render_session_prompt / render_extraction_prompt
│   ├── estimation/
│   │   ├── v1/              # system.j2 · user.j2 · examples.j2
│   │   └── v2/              # variación deliberada: tono y ejemplos distintos
│   ├── session5/v1/         # prompt conversacional con bloque <project_metadata>
│   └── extraction/v1/       # prompt del extractor de metadata
└── context/
    └── examples.py          # Ejemplos CAG del chat libre (sesión 02)
streamlit_app.py             # Cliente: formulario · conversación (sesión 05) · chat
tests/                       # Tests de template, sesiones, adjuntos y servicio
```

## ⚙️ Instalación

```bash
uv sync --extra dev
```

`.env` en la raíz (ignorado por Git):

```env
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-haiku-4-5-20251001
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-flash-latest
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
uv run pytest -v                       # suite completa, sin red
uv run pytest tests/test_sessions.py -v  # tests de la sesión 05
```

Prueba real contra Anthropic (gasta unos céntimos de API, opcional):

```bash
RUN_LIVE_TESTS=1 uv run pytest -m live -v
```

### Tests de la sesión 05

`tests/test_sessions.py` usa un LLM falso (`FakeLLM`): verifica el cableado, no la
calidad del modelo.

1. **Metadata entre turnos**: dos peticiones en la misma sesión; el
   `project_metadata` acumula nombre, equipo y tecnologías, y el nombre del proyecto
   llega al system prompt del turno 2.
2. **Un PDF influye en la estimación**: la misma transcripción con y sin un PDF que
   menciona Kubernetes; solo con el adjunto aparece en la respuesta y en la metadata.
3. **Ventana deslizante**: 8 turnos; ninguna llamada al LLM lleva más de
   `1 system + 6 pares + 1 user`, y el turno 1 ya no viaja en el turno 8.

Más casos de error: sesión inexistente (404), formato no soportado (415), PDF
escaneado (aviso, no error), fallo del LLM (la sesión no queda a medias) y versión
de prompt desconocida (400).

### Tests de template (sesión 04)

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

## 🗃️ Caché y fallback

Coincidencia exacta sobre `sha256(provider + model + system + user)`, respaldada por
Redis (`REDIS_URL`, `CACHE_TTL`). Sobrevive a reinicios y se comparte entre workers; si
Redis no está disponible, degrada a "siempre cache miss" sin romper la petición.

Si Anthropic falla, `LLMWrapper` reintenta automáticamente con Gemini (gratuito) como
red de seguridad. Esa respuesta de fallback **no se cachea**, para no seguir sirviendo
una respuesta vieja de Gemini durante el TTL una vez que Anthropic se recupera.

El endpoint de streaming no cachea ni hace fallback: el cuerpo se consume una sola vez
y no hay forma limpia de reintentar a mitad de una respuesta sin mezclar texto de dos
modelos.

## 💬 Sesión 05 — Conversación con memoria y adjuntos

| Endpoint | Qué hace |
|---|---|
| `POST /api/v1/sessions` | Crea una sesión vacía → `{"session_id": "..."}` |
| `GET /api/v1/sessions/{id}` | `project_metadata`, historial y contadores |
| `POST /api/v1/sessions/{id}/estimate` | `multipart/form-data`: `transcript`, `project_type`, `detail_level`, `output_format` y `attachments` (opcional, varios) |

**Historial ≠ memoria.**
- *Historial* (`ConversationHistory`): los pares user/assistant que viajan a la API.
  Ventana deslizante de `MAX_TURNS=6` pares; el system prompt no se guarda, se
  regenera en cada turno.
- *Memoria* (`ProjectMetadata`): nombre del proyecto, equipo asumido, tecnologías y
  alcance acordado. Se inyecta en el system prompt dentro de `<project_metadata>`, así
  que sobrevive aunque el turno que la originó haya salido de la ventana.

Todo vive en un diccionario en memoria del proceso: reiniciar el servicio borra las
sesiones (el cliente crea una nueva y avisa). Es aceptable en esta fase.

**Adjuntos — camino B (extracción local).** `pypdf` para PDF y `python-docx` para Word
(párrafos y tablas). El texto se concatena al mensaje con `--- attachment: nombre ---`.
Elegido frente a enviar el PDF al LLM multimodal porque:

1. mantiene el fallback a Gemini sin un segundo camino de subida;
2. Word no se acepta como documento nativo y habría que extraerlo igualmente;
3. se testea sin red;
4. deja el texto listo para el chunking de RAG.

Coste: Límites: 3 MB por archivo y 20.000 caracteres extraídos (se trunca con
aviso); otros formatos → 415. En el historial solo queda una marca
`[adjuntos: x.pdf (N caracteres)]`: el texto completo se envía en el turno en que se sube.

**Extracción de `project_metadata` — extractor LLM.** Tras cada respuesta, una segunda
llamada (`max_tokens=500`, prompt en `app/prompts/extraction/v1/`) devuelve un JSON
validado con Pydantic y fusionado con lo anterior: un dato no mencionado no se borra y
las tecnologías se acumulan. Elegido frente a regex porque los hechos llegan en prosa
libre ("seremos cuatro", "los pagos van a la fase 2"), a cambio de una llamada extra
por turno. Si la extracción falla, se conserva la metadata anterior y el turno responde
igual.

Los prompts conversacionales viven en `app/prompts/session5/v1/`, separados de
`estimation/`, para no aparecer en el selector de versiones de `/estimate`. El endpoint
de sesiones no usa la caché de Redis: con historial, la clave no se repetiría nunca.

## 📝 Notas

- El SDK de `anthropic` fijado en este proyecto no acepta `temperature` en
  `messages.stream()`. Ninguna llamada a Anthropic (bloqueante ni streaming) lo usa
  por eso; Gemini (el fallback) sí fija `temperature=0.3`.
- La respuesta sigue siendo **texto libre**. Salida JSON estructurada, guardarraíles y
  cacheo semántico quedan para el directo.
