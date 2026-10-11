# 🧮 Estimador de Software — servicio IA + cliente

Servicio FastAPI que convierte una descripción de proyecto en una estimación técnica,
con prompts versionados en Jinja2 y un contrato tipado con el cliente.

> **Esta rama es la entrega de la sesión 06**: estrés del CAG conversacional antes de
> pasar a RAG. Lo nuevo está justo debajo; instalación, ejecución, tests y lo construido
> en sesiones anteriores, a continuación.

## 📈 Sesión 06 — estrés del CAG

Antes de pasar a RAG, se mide dónde empieza a romperse este CAG. Resultado y lectura en
[`evals/stress/REPORT.md`](evals/stress/REPORT.md); datos en `evals/stress/results.csv`.

**Observación por turno.** Cada `POST /sessions/{id}/estimate` emite un único evento
`turn_observed` (y lo devuelve en el campo `observation`; `GET /sessions/{id}` lo expone
como `last_turn_observed`) con los 13 campos del enunciado: turno, sesión, tamaño del
mensaje y de los adjuntos, mensajes en ventana, anclas, longitud del resumen, tokens de
entrada y salida, coste, latencia, tipo de acierto de caché y tier; más `llm_calls`,
`structured_attempts` y `tier_rule`. Tokens y coste suman **todas** las llamadas del turno
(estimador con reintentos, extractor y resumidor) gracias a un `UsageMeter` que envuelve
al LLM.

**Qué se ejecuta** (`evals/stress/`):

| Pieza | Qué hace |
|---|---|
| `scenarios.py` | 3 conversaciones de 10 turnos: un proyecto que **crece** (Nimbus), uno que **pivota** de React a Flutter (Orbit) y uno que **se contradice** en el presupuesto, 30.000 → 80.000 € (Atlas). Cada turno declara el hecho que debe recordarse |
| `fixtures/build_pdfs.py` | PDFs deterministas de 5, 20, 50 y 100 mil caracteres con marcadores al 10, 50 y 90 % del texto (no se versionan) |
| `metrics.py` | `LatencyBudgetMetric(20.000 ms)`, `CostBudgetMetric($0,02/turno)` y `MemoryDriftMetric` (coincidencia exacta en resumen, anclas y metadata) |
| `run.py` | Recorre escenarios y adjuntos y escribe una fila por turno en el CSV |
| `report.py` | Genera el REPORT (tabla resumen y tres curvas) e incrusta la lectura de `reading.md` |

> ⚠️ **Alcance reducido por coste.** El enunciado pide 20 turnos por escenario, 3
> repeticiones y el adjunto en todos los turnos. Aquí se hacen **10 turnos, 1 repetición y
> el adjunto solo en el turno 1**, a propósito, para no gastar de más: la ejecución
> reducida costó $1,11, y la completa costaría entre $7,5 y $10 solo con 20 turnos y
> 3 repeticiones (≈ $45–70 con el adjunto en todos los turnos). El detalle, junto con los
> presupuestos de 20 s y de 20.000 caracteres, está en la primera sección del REPORT.

**Cómo ejecutarlo:**

```bash
# Ensayo completo con el LLM falso: coste $0, unos segundos
uv run python -m evals.stress.run --in-process --fake-llm --output /tmp/fake.csv

# Ejecución real (medido: ~$1,1 y ~17 min con Haiku; freno por defecto: $1,5)
uv run python -m evals.stress.run --http http://localhost:8000 --max-cost 1.5
uv run python -m evals.stress.report
```

El runner **vacía la caché del turno 1 antes de una ejecución real** (claves
`session_turn1:*` en `REDIS_URL`, vía `SessionTurnCache.flush()`): con su TTL de 24 h,
una ejecución anterior haría que los turnos 1 acertaran en caché y falsearía coste y
latencia. Si Redis no responde, se para antes de hacer ninguna petición (código 3).
`--keep-turn1-cache` lo desactiva, y si aun así un turno 1 de escenario sale de caché,
la fila lo marca en `error` y el runner avisa.

## 🕘 Sesiones anteriores

### Sesión 05

Hasta la sesión 04 el estimador era transaccional: una transcripción entra, una
estimación sale. Esta rama lo convierte en **conversacional**:

| Antes | Ahora |
|---|---|
| Cada petición es independiente | Sesiones con `session_id` (`POST /sessions`) |
| Solo texto | Adjuntos PDF y Word en `multipart/form-data` |
| Sin memoria | Historial con ventana deslizante + `project_metadata` en el system prompt |
| Formulario de una sola estimación | Pestaña "Estimación conversacional" con panel de memoria |

Detalle en [💬 Sesión 05](#-sesión-05--conversación-con-memoria-y-adjuntos). Lo que
cambió en sesiones anteriores sigue debajo.

#### Sesión 04

La sesión 03 dejaba un chat libre y un prompt construido como f-string dentro del
wrapper. Esta rama sustituye ambas cosas:

| Antes | Ahora |
|---|---|
| `transcription: str` como única entrada | `EstimationRequest` con enums de tipo, detalle y formato |
| Prompt f-string en `llm_service.py` | Plantillas `.j2` versionadas + `loader.py` |
| Un solo mensaje concatenado al LLM | `system` y `user` como mensajes separados |
| Sin tests de prompt | Suite de template que corre en milisegundos, sin red |
| Cualquier texto llega al LLM | Guardrails de entrada (inyección, datos personales, moderación → 400) y de salida |

El chat libre **no se elimina**: convive con el formulario en una segunda pestaña del
cliente, para que la entrega de la sesión 03 siga siendo verificable.

## 🏗️ Estructura

```
app/
├── main.py                  # FastAPI + structlog + middleware de request_id
├── config.py                # Settings (pydantic-settings, .env)
├── schemas.py               # Contrato tipado cliente ↔ servicio
├── observability.py         # Configuración de structlog
├── dependencies.py          # Singletons: caché, LLM, sesiones y caché del turno 1
├── routers/
│   ├── estimations.py       # POST /estimate, POST /estimate/stream, GET /prompt-versions
│   └── sessions.py          # POST /sessions, GET /sessions/{id}, POST /sessions/{id}/estimate(-acb)
├── guardrails/
│   ├── input.py             # inyección, datos personales y moderación → 400
│   └── output.py            # "Fuera de alcance:" sin gastar un reintento
├── services/
│   ├── llm_service.py       # Wrapper de Anthropic (+ fallback a Gemini), recibe messages
│   ├── cache.py             # Caché de coincidencia exacta (Redis)
│   ├── sessions.py          # ConversationHistory, ProjectMetadata, Session, SessionStore
│   ├── attachments.py       # Extracción de texto de PDF y Word
│   ├── metadata_extractor.py # 2ª llamada al LLM: hechos del proyecto en JSON
│   ├── structured_estimator.py # JSON validado + reintento + render a Markdown
│   ├── compression/         # anchors.py · summarizer.py · policy.py
│   ├── tier_resolver.py     # para quién se redacta (reglas explicables)
│   ├── session_cache.py     # caché exacta + semántica del turno 1
│   ├── usage_meter.py       # tokens, coste y llamadas agregados por turno (sesión 06)
│   ├── critic.py            # Actor-Critic-Boss: auditoría del borrador (JSON validado)
│   ├── boss.py              # Actor-Critic-Boss: aceptar, rehacer o sintetizar (sin LLM)
│   └── conversation.py      # run_turn: orquesta un turno de la conversación
├── prompts/
│   ├── loader.py            # render_estimation_prompt / render_session_prompt / render_extraction_prompt
│   ├── estimation/
│   │   ├── v1/              # system.j2 · user.j2 · examples.j2
│   │   └── v2/              # variación deliberada: tono y ejemplos distintos
│   ├── session5/v1/         # prompt conversacional con bloque <project_metadata>
│   ├── session5/v2/         # + anclas, resumen, tier y respuesta JSON en horas
│   ├── conversation_summary/v1/ # prompt del resumen acumulativo
│   ├── extraction/v1/       # prompt del extractor de metadata
│   └── critic/v1/           # prompt del crítico del Actor-Critic-Boss
└── context/
    └── examples.py          # Ejemplos CAG del chat libre (sesión 02)
evals/
├── metrics.py               # MetricResult, SchemaAdherence y métricas del golden
├── dataset.py               # GoldenCase + load_dataset
├── golden_dataset.json      # 16 casos con lo esperado
├── run.py                   # runner: actor frente a ACB → results.json
├── report.py                # results.json + reading.md → REPORT.md
├── REPORT.md · results.json # resultado del golden
└── stress/                  # Sesión 06: estrés del CAG
    ├── scenarios.py         # 3 escenarios de 10 turnos con hechos a recordar
    ├── metrics.py           # LatencyBudget, CostBudget, MemoryDrift
    ├── run.py               # runner → results.csv (vacía la caché y frena por coste)
    ├── report.py            # results.csv + reading.md → REPORT.md
    ├── fixtures/build_pdfs.py # PDFs sintéticos con marcadores (no se versionan)
    └── REPORT.md · results.csv · reading.md   # entregables
streamlit_app.py             # Cliente: formulario · conversación (sesión 05) · chat
tests/                       # Tests de template, sesiones, adjuntos, memoria y servicio
Dockerfile · docker-compose.yml # Servicio IA + Redis en contenedores
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

### Con Docker

```bash
docker compose up --build        # servicio IA + Redis
uv run streamlit run streamlit_app.py   # el cliente corre fuera, contra :8000
```

`Dockerfile` en dos etapas con uv (dependencias exactas de `uv.lock`, sin root y con
healthcheck en `/health`). El compose lee tu `.env`, apunta `REDIS_URL` al contenedor de
Redis y pone `APP_ENV=production` (logs en JSON). El `.env` no entra en la imagen.

## ✅ Tests

```bash
uv run pytest -v                       # suite completa, sin red (LLM falso)
uv run pytest tests/test_sessions.py -v  # tests de la sesión 05
```

Prueba real contra Anthropic: 8 turnos con compresión (gasta unos céntimos, opcional):

```bash
RUN_LIVE_TESTS=1 uv run pytest -m live -v -s -p no:logging
```

(En Windows con Control de aplicaciones, `uv run python -m pytest` en lugar de
`uv run pytest`.)

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

## 🛡️ Sesión 04 — Guardrails

**Entrada** (`app/guardrails/input.py`). Antes de llamar al LLM y antes de la caché se
revisan la transcripción **y el texto de los adjuntos**, de lo gratis a lo de pago:

| Capa | Cómo | Si no pasa |
|---|---|---|
| Inyección de prompt | Reglas fijas en español e inglés: pedir que se olviden o ignoren las instrucciones, imponer un rol ("ahora eres un…", "you are now a…"), etiquetas `<system>`. Una corrección normal ("olvida lo anterior: el presupuesto es 80.000") pasa | 400 `prompt_injection` |
| Datos personales | Reglas fijas: email, IBAN y teléfono (con prefijo internacional o español de 9 cifras en sus formatos habituales; rangos como "8.000-12.000 horas" no saltan) | 400 `pii` |
| Moderación | Una llamada corta a Haiku (≈ $0,0004 por turno sin adjuntos). Si falla, deja pasar el texto; se apaga con `GUARDRAILS_MODERATION_ENABLED=false` | 400 `moderation` |

El cuerpo del 400 es `{"detail": {"reason": ..., "message": ...}}` en las cuatro rutas
de estimación, y Streamlit lo muestra como aviso. Como van antes de la caché, un
acierto de caché también paga la moderación.

**Salida** (`app/guardrails/output.py`). Si la confianza es < 30 y el resumen no empieza
por "Fuera de alcance:", se añade el prefijo antes de validar en vez de gastar un
reintento, que reenviaría todo el contexto. La regla del esquema sigue como última
defensa.

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

Coste: se pierden imágenes y diagramas, y un PDF escaneado no aporta texto (se avisa en
`warnings`). Límites: 3 MB por archivo y 20.000 caracteres extraídos (se trunca con
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
de sesiones no usa la caché de Redis: con historial, la clave no se repetiría nunca
(salvo el turno 1, ver abajo).

## 🧠 Sesión 05 — directo: estructura, memoria comprimida, tier y caché

Sobre la conversación anterior, `POST /api/v1/sessions/{id}/estimate` (prompt
`session5/v2`, por defecto) añade cuatro piezas, y `POST /api/v1/sessions/{id}/estimate-acb`
una quinta, el Actor-Critic-Boss. `/estimate` no cambia.

**Salida estructurada.** El modelo devuelve un `EstimationResult` en **horas**: fases
(cada una con mínimo, máximo y confianza) **antes** que los totales, supuestos y
exclusiones. Las fases van primero a propósito: el modelo genera de izquierda a derecha,
se compromete con cada fase y luego solo suma. Reglas de negocio (validadores Pydantic):
las fases suman los totales, mínimo ≤ máximo y, con confianza < 30 %, el resumen empieza
por `Fuera de alcance:`. Los **euros los calcula el código** (horas × `HOURLY_RATE_EUR`,
50 €/h por defecto): los LLM calculan mal y la tarifa es una decisión de negocio.

La forma del JSON la fuerza la API (`output_config` con esquema JSON en Anthropic,
`response_json_schema` en Gemini). Si una regla falla, se reenvía al modelo su propio
JSON con el error ("las fases suman 420 h pero total_hours_min dice 400") y se reintenta
hasta `STRUCTURED_MAX_RETRIES` (2) veces; agotado, 502 y la sesión no cambia. No se usa
`messages.parse()` porque valida dentro del SDK y no devuelve el texto que el reintento
necesita. El Markdown que ve el usuario (`output_format`) se genera en código desde el JSON.

**Memoria comprimida.** Cuando la ventana supera `MAX_TURNS` (6), los turnos que salen
no se pierden:

| Destino | Cuándo | Coste |
|---|---|---|
| **Ancla** (literal, nunca se expulsa) | El mensaje del cliente contiene un compromiso: NDA, contrato firmado, alcance o presupuesto cerrado, RGPD/ISO 27001/ENS…, fecha inamovible, "el cliente se compromete" (regex ES + EN) | 0 llamadas |
| **Resumen acumulativo** | El resto: se funde con el resumen anterior en uno nuevo | 1 llamada por turno desde el 7 |

Anclas y resumen se inyectan en el system prompt (`<anchors>`, `<conversation_summary>`)
junto a `<project_metadata>`. Si el resumidor falla, se conserva el resumen anterior.

**Tier dinámico.** Para quién se redacta, sin llamadas al LLM; gana la primera regla:

| Regla | Tier | Cuándo |
|---|---|---|
| `explicit_override` | el elegido | El cliente lo fija (campo `tier`) |
| `nda_detected` | executive | NDA / confidencial / bajo embargo |
| `regulatory_context` | executive | RGPD, HIPAA, ISO 27001, ENS, PCI-DSS… |
| `technical_audience` | developer | ≥ 2 términos técnicos distintos (Kubernetes, Kafka…) |
| `small_team_pm` | pm | Equipo asumido ≤ 2 |
| `default` | default | Ninguna |

**Caché del turno 1.** Solo el turno 1 es cacheable: sin historial, su respuesta depende
del formulario, el tier, el mensaje y los adjuntos, igual que `/estimate`. Desde el
turno 2 depende de toda la conversación. Primero caché **exacta** (Redis) y después
**semántica**: embedding del mensaje con Gemini (`gemini-embedding-001`, tier gratuito) y
similitud coseno ≥ 0,92 contra entradas del mismo formulario, tier y adjuntos, calculada
en Python sobre el Redis normal. Un acierto no llama a ningún LLM. Las respuestas del
fallback no se cachean; si Redis o los embeddings fallan, el turno sigue sin caché.
`SEMANTIC_CACHE_LOG_ONLY=true` mide similitudes sin servir aciertos (calibración).

**Actor-Critic-Boss.** `POST /api/v1/sessions/{id}/estimate-acb` recibe el mismo
formulario que `/estimate` (en Streamlit, la casilla "Revisar con crítico"). El estimador
hace un borrador (**actor**); un segundo modelo lo audita y devuelve fallos estructurados
con categoría, gravedad y campo afectado (**crítico**, `app/services/critic.py`, prompt
`critic/v1`); un código sin LLM decide (**jefe**, `app/services/boss.py`):

| Veredicto del crítico | Decisión del jefe |
|---|---|
| Aceptar | Devuelve el borrador |
| Rehacer, y quedan rondas (`ACB_MAX_ITERATIONS`, 2) | El actor lo rehace con los fallos |
| Rechazar, o sin rondas | Último borrador con los fallos pendientes delante y la confianza a la mitad (nunca por debajo de 30 ni por encima de la original) |

El crítico ve lo mismo que el actor (mensaje, adjuntos, turnos recientes, memoria y
tier) y tiene una categoría propia, `dato_superado`, para cuando la estimación usa un
dato que la conversación ya corrigió, como un presupuesto anterior. Si el crítico falla,
pasa el borrador; si falla una ronda de rehacer, se devuelve el borrador anterior. La
respuesta añade `acb` con el rastro de cada ronda. Cuesta entre 1,5 y 3 veces un turno
normal y no usa la caché del turno 1.

**Evals.** `evals/metrics.py` define `MetricResult(name, score, passed, details)`,
`run_all_metrics` y `SchemaAdherenceMetric`, que vuelve a comprobar las reglas de negocio
para detectar si un cambio futuro las relaja. Encima va un **golden dataset**
(`evals/golden_dataset.json`): 16 casos en español con lo que se espera de un buen
estimador (palabras clave, alguna tecnología, rangos anchos de fases, horas y semanas, y
el tier). Cuatro métricas deterministas (`schema_adherence`, `hours_bounds`,
`content_recall`, `tier`) puntúan cada respuesta, y el runner pasa los casos por el
estimador normal y por el Actor-Critic-Boss para compararlos:

```bash
uv run python -m evals.run --in-process --fake-llm --mode ambos   # ensayo, $0
uv run python -m evals.run --http http://localhost:8000 --mode ambos
uv run python -m evals.report                                      # evals/REPORT.md
```

Un bloqueo del guardrail cuenta como acierto solo si el caso esperaba quedar fuera de
alcance. Resultado y lectura en [`evals/REPORT.md`](evals/REPORT.md).

La respuesta del endpoint añade `result`, `cost_min_eur`/`cost_max_eur`, `tier`/`tier_rule`,
`anchors_count`, `summary_chars`, `structured_attempts` y `cache_hit_kind`; y
`GET /sessions/{id}` expone resumen, anclas y último tier.

## 📝 Notas

- El SDK de `anthropic` fijado en este proyecto no acepta `temperature` en
  `messages.stream()`. Ninguna llamada a Anthropic (bloqueante ni streaming) lo usa
  por eso; Gemini (el fallback) sí fija `temperature=0.3`.
- La respuesta sigue siendo **texto libre**. Salida JSON estructurada, guardarraíles y
  cacheo semántico quedan para el directo.
