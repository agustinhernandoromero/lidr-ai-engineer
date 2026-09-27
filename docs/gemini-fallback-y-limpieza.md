# Fallback a Gemini, DI del LLM wrapper y limpieza de OpenAI

Notas de la segunda mitad de la sesión de trabajo en `infra/redis-cache-fallback`
(después de la migración de caché a Redis, ver
[docs/redis-cache-migration.md](redis-cache-migration.md)). Todo esto ya está
fusionado en `sesion-04-chat-vs-producto` — ver
[docs/entrega-y-ramas.md](entrega-y-ramas.md).

## 1. Por qué un fallback, y por qué Gemini

Antes de esto, `llm_service.py` llamaba directo al proveedor configurado en
`LLM_PROVIDER` (Anthropic u OpenAI). Si esa llamada fallaba —rate limit,
timeout, caída del servicio— la petición simplemente fallaba. No había red
de seguridad.

Decisión explícita del usuario: **si Anthropic falla, probar un proveedor
gratuito**, no uno de pago, porque el objetivo es no aumentar el gasto en
producción. Se eligió **Google Gemini** (tier gratuito vía
[aistudio.google.com/apikey](https://aistudio.google.com/apikey)) frente a
otras opciones evaluadas (Groq, Ollama local) por tener cuota gratuita real
sin depender de tener un servidor propio corriendo.

## 2. Diseño

- `call_gemini(system, user, settings)` en `llm_service.py`, con el SDK
  `google-genai` (`from google import genai`).
- `GEMINI_API_KEY` y `GEMINI_MODEL` en `config.py` / `.env.example`.
- **El fallback solo aplica al endpoint no-streaming** (`/estimate`). El
  streaming (`/estimate/stream`) se queda sin fallback a propósito: si el
  proveedor principal falla a mitad de una respuesta en streaming, no hay
  forma limpia de reintentar sin mezclar texto de dos modelos distintos en
  la misma respuesta.
- **El fallback no se cachea.** Si se cacheara la respuesta de Gemini bajo
  la clave de Anthropic, se seguiría sirviendo esa respuesta vieja durante
  las 24h del TTL aunque Anthropic ya se hubiera recuperado. Se prefiere
  pagar la latencia extra de volver a intentar Anthropic en cada petición
  mientras esté caído (Gemini es gratis, así que no hay coste real en
  reintentarlo cada vez).
- El campo `fallback_used: bool` se añadió a `EstimationResponse` para que
  el cliente sepa si la respuesta vino del proveedor principal o del
  respaldo. Streamlit lo muestra como aviso (`st.warning`) cuando aplica.

## 3. El bug real que apareció en pruebas: 503 intermitente de Gemini

Al verificar el fallback contra la API real de Gemini (no mockeada), se
detectó que el tier gratuito devuelve `503 Service Unavailable`
("currently experiencing high demand") de forma intermitente — en las
pruebas, 1 de cada 4 llamadas aproximadamente. Como Gemini es la propia
red de seguridad, que falle 1 de cada 4 veces la hace poco fiable.

Solución: `call_gemini` reintenta **una vez** tras esperar 1 segundo si
recibe un `google.genai.errors.ServerError`. No se aplica backoff
exponencial porque con un único reintento no aporta nada, solo
complejidad.

```python
try:
    response = client.models.generate_content(model=..., contents=user, config=config)
except errors.ServerError:
    time.sleep(1)
    response = client.models.generate_content(model=..., contents=user, config=config)
```

Cubierto por dos tests en `tests/test_llm_service.py`: uno que confirma
que el segundo intento recupera la respuesta, otro que confirma que si
falla dos veces seguidas el error sí se propaga (no hay más redes de
seguridad después de Gemini).

También se detectó en pruebas reales que el nombre de modelo
`gemini-2.0-flash` ya no existe en el catálogo (Google lo retiró). Se usa
`gemini-flash-latest`, un alias que apunta siempre al modelo flash
vigente, precisamente para no volver a depender de un nombre de modelo
concreto que puede quedar obsoleto.

## 4. DI del LLM wrapper (`LLMWrapper` + `get_llm_wrapper()`)

Mismo patrón que `get_cache()`: un singleton en `app/dependencies.py`. La
clase `LLMWrapper` expone `.complete(system, user)` (con el fallback
integrado) y `.complete_stream(system, user)` (sin fallback).

Decisión de diseño importante: la clase **no guarda configuración en
`__init__`**. Cada método llama a `get_settings()` en el momento de
usarla. Si guardara la configuración al construirse, el singleton
`@lru_cache` de `get_llm_wrapper()` se quedaría pegado a la primera
configuración que viera para siempre — lo que rompería cualquier test que
mockee `get_settings()` para forzar un proveedor o una API key concretos,
ya que el singleton persiste entre tests dentro del mismo proceso de
pytest.

## 5. El import circular que apareció al cablear la DI (bug real, no hipotético)

Al conectar `get_llm_wrapper` entre `dependencies.py` y `llm_service.py`
apareció un `ImportError` real:

```
app.dependencies → app.services.cache → app/services/__init__.py
  → app.services.llm_service → app.dependencies (otra vez, a medio cargar)
```

**Root cause**: `app/services/__init__.py` reexportaba
`generate_estimation` (`from app.services.llm_service import
generate_estimation`) sin que nada en el proyecto usara esa forma de
importarlo (`grep` confirmó cero usos de `from app.services import
generate_estimation`). Esa reexportación forzaba cargar `llm_service.py`
completo cada vez que se importaba *cualquier cosa* de `app.services.*`,
incluido `app.services.cache` — y ahí es donde se cerraba el círculo.

**Por qué no se veía en los tests**: el bug solo se manifiesta cuando
`app.dependencies` (o `app.services.cache`) es el *primer* módulo que se
importa en un proceso de Python nuevo. En la suite de tests normal,
`app.main` se importa primero (vía `test_api.py`), lo que precarga todo en
el orden correcto y esconde el problema. Se reprodujo a propósito
importando `app.dependencies` como primer import en un intérprete limpio.

**Fix**: se quitó la reexportación de `app/services/__init__.py` (queda
vacío, solo con el docstring), y el import de `LLMWrapper` dentro de
`get_llm_wrapper()` se hizo diferido (dentro de la función, no al
principio del archivo).

**Test de regresión**: `tests/test_imports.py` lanza un intérprete de
Python limpio (`subprocess`) por cada módulo clave
(`app.dependencies`, `app.services.cache`, `app.services.llm_service`,
`app.main`) y comprueba que importa sin error como el *primer* import del
proceso. Se verificó que el test SÍ detecta el bug: se reprodujo el
`__init__.py` roto a propósito, el test falló con el mismo traceback real,
y se volvió a arreglar.

## 6. Limpieza de OpenAI

Al revisar el código, saltó una pregunta legítima: ¿por qué hay un
`if provider == "openai": ... else: call_anthropic(...)` si `LLM_PROVIDER`
siempre ha sido `anthropic`? Respuesta: es un switch que nunca se llegó a
usar en la práctica — flexibilidad hipotética, no real.

Se quitó por completo:

- `call_openai`, `stream_openai` de `llm_service.py`.
- `_resolve_provider`, `_model_for` (ya no hacían falta con un único
  proveedor principal).
- `OPENAI_API_KEY`, `OPENAI_MODEL`, `LLM_PROVIDER` de `config.py`.
- La dependencia `openai` de `pyproject.toml` (desinstalada del entorno
  con `uv sync`).
- Las comprobaciones de `OPENAI_API_KEY`/`LLM_PROVIDER` en
  `streamlit_app.py` (sidebar y modo chat).
- El `/health` ya no lee `LLM_PROVIDER` (queda fijo `"anthropic"`).

`generate_estimation`/`LLMWrapper` ahora hablan directo con Anthropic, sin
ninguna rama condicional de proveedor — solo el `try/except` que dispara
el fallback a Gemini.

**Nota importante para el futuro**: esta limpieza vive en
`infra/redis-cache-fallback` y, tras la fusión, también en
`sesion-04-chat-vs-producto`. Si algún día hace falta OpenAI de vuelta
(por ejemplo, para una revisión del curso que espere ver los dos
proveedores), existe una rama de reserva con el código de OpenAI intacto
— ver [docs/entrega-y-ramas.md](entrega-y-ramas.md).

## 7. Verificación en real (no mockeada)

- **Redis + Streamlit + FastAPI de punta a punta**: formulario real en el
  navegador (Playwright) → petición real a Anthropic → estimación real
  generada → segunda petición idéntica → `cache_hit` real de Redis
  (19.01s → 2.05s), confirmado también con `redis-cli keys` y `redis-cli
  ttl` desde dentro del contenedor Docker.
- **Fallback a Gemini con Anthropic simulado caído**: mockeando
  `call_anthropic` para lanzar una excepción, `call_gemini` respondió de
  verdad (sin mockear) con una estimación completa y coherente,
  `fallback_used: true`, `provider: gemini`.
- **Intento de probar el fallback también desde la UI en vivo**: se
  intentó romper la `ANTHROPIC_API_KEY` en `.env` y reiniciar el backend
  para forzar el fallback visible en Streamlit. El intento no llegó a
  completarse: `pkill`/`ps` en git-bash sobre Windows no ven bien los
  procesos nativos lanzados por `uv run`, así que el proceso viejo (con la
  key buena) siguió sirviendo todo el rato sin que nos diéramos cuenta al
  momento. Los logs del backend lo dejaron claro a posteriori. No se
  insistió porque el fallback ya estaba verificado por otras dos vías
  (tests automatizados + llamada directa a la API). La `.env` se restauró
  con la key correcta inmediatamente.
