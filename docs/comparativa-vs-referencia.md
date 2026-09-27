# Comparativa vs. el proyecto de referencia del curso

Resumen de la comparación hecha entre este repo y la referencia oficial del
curso (rama `session_4` de `LIDR-academy/ai-engineering`, carpeta
`estimator/` — el backend FastAPI; `estimator-web/` es un frontend Rails
aparte, no comparado en detalle). Sirve para saber en qué estado quedó cada
punto y no repetir el análisis.

## Lo que estaba bien (y en algún punto por encima del original)

- **Contrato tipado correcto**: `EstimationRequest` (descripción + 3 enums)
  → texto libre, igual que el objetivo declarado de la sesión 4.
- **Versionado de prompts**: estructura
  `prompts/estimation/v1|v2/{system,user,examples}.j2` idéntica al patrón
  de referencia — pero la referencia en esa rama solo trae `v1`; aquí ya
  existía un `v2` real, con persona/tono distinto y testeado.
- **`loader.py`**: `StrictUndefined` (una variable no pasada revienta el
  render en vez de silenciarse) + fingerprint SHA-256 en logs.
- **Bonus `reference_projects`**: anclar la estimación a proyectos
  similares del cliente, no estaba en el contrato original.
- **Formulario tipado en Streamlit**: resuelve la "interfaz de producto"
  sin necesitar el Rails aparte de la referencia, conservando el chat de
  sesión 3 en otra pestaña.
- **Respuesta más informativa**: `EstimationResponse` añade `model`,
  `provider`, `cached` (la referencia solo devuelve `text` y
  `prompt_version`).

## Los 5 puntos flojos identificados

### 1. Caché en memoria, no Redis — ✅ RESUELTO

La caché vivía en un `OrderedDict` del proceso: se perdía al reiniciar y
no se compartía entre workers. Ahora es `EstimationCache` respaldada por
Redis, inyectada vía `app/dependencies.py`, con degradación a cache-miss
si Redis falla. Detalle completo en
[docs/redis-cache-migration.md](redis-cache-migration.md).
Commit: `2eccf20` en la rama `infra/redis-cache-fallback`.

### 2. Sin fallback de proveedor ni reintentos — ✅ RESUELTO

La referencia envuelve LiteLLM con un `Router` que hace fallback
automático de modelo primario a secundario. Aquí, en vez de un segundo
modelo de pago, `generate_estimation()` cae a **Gemini** (gratuito) si
falla el proveedor configurado (`call_openai`/`call_anthropic`) — decisión
tomada expresamente para no aumentar el gasto en producción. La respuesta
de fallback no se cachea (para no servir una respuesta vieja de Gemini
durante 24h una vez que el proveedor principal se recupera). Verificado
end-to-end contra la API real de Gemini: se detectó que el tier gratuito
devuelve `503` de forma intermitente (~1 de cada 4 llamadas en pruebas),
por lo que `call_gemini` incluye 1 reintento tras 1s. Cubierto por
`tests/test_llm_service.py` (fallback, no-cacheo del fallback, y el
reintento del propio Gemini). Commit pendiente de hacer en
`infra/redis-cache-fallback`.

### 3. Sin capa de inyección de dependencias — ✅ RESUELTO

`app/dependencies.py` ahora tiene también `get_llm_wrapper()` (además de
`get_cache()`), que devuelve un singleton `LLMWrapper` con `.complete()` y
`.complete_stream()`. La clase no guarda configuración en `__init__`: lee
`get_settings()` en cada llamada, a propósito, para que el singleton
`@lru_cache` no se quede pegado a una config vieja (relevante en tests que
mockean `get_settings()`). `call_openai`/`call_anthropic`/`call_gemini`
siguen siendo funciones de módulo — la clase las usa por dentro, pero
seguir permitiendo mockearlas sueltas en tests no tenía coste.

**Efecto colateral encontrado y corregido**: al cablear `get_llm_wrapper`
entre `dependencies.py` y `llm_service.py` apareció un import circular real
(`app.dependencies` → `app.services.cache` → `app/services/__init__.py` →
`app.services.llm_service` → `app.dependencies` otra vez). Root cause:
`app/services/__init__.py` reexportaba `generate_estimation` sin que nada
lo usara — puro riesgo sin beneficio. Se quitó esa reexportación y se hizo
el import de `LLMWrapper` dentro de `get_llm_wrapper()` (import diferido,
no al principio del archivo). Cubierto por `tests/test_imports.py` (nuevo):
lanza un intérprete de Python limpio por cada módulo clave y comprueba que
importa bien como el *primer* import del proceso — se confirmó que este
test sí habría detectado el bug (se reprodujo el fallo a propósito antes
de arreglarlo, y el test lo capturó).

### 4. `description` limitado a 2000 caracteres — ✅ RESUELTO

Subido a 20.000 caracteres (no los 80.000 de la referencia, a propósito:
cubre una transcripción real de reunión sin abrir la puerta a pegar textos
enormes que disparen el coste por llamada). Actualizado también el texto
de ayuda en `streamlit_app.py`. Cubierto por `tests/test_schemas.py`
(nuevo): rechaza `< 20` y `> 20000` caracteres, acepta una transcripción
larga de ejemplo.

### 5. Cobertura de tests desigual — 🟡 PARCIAL

La referencia separa `test_schemas.py`, `test_prompts.py`,
`test_estimate_endpoint.py`, `test_llm_wrapper.py`, `test_cache.py`. Aquí
`test_cache.py` ya existe y cubre bien la clase `EstimationCache` (paso 2
de hoy). Sigue faltando: tests dedicados de `llm_service.py` más allá del
único endpoint mockeado — nada cubre `call_anthropic`, el streaming, ni el
error de `_resolve_provider` con un proveedor no soportado.

## Estado general

| # | Punto | Estado |
|---|-------|--------|
| 1 | Caché → Redis | ✅ Resuelto |
| 2 | Fallback de proveedor (a Gemini, gratuito) | ✅ Resuelto |
| 3 | Inyección de dependencias | ✅ Resuelto |
| 4 | Límite de `description` | ✅ Resuelto |
| 5 | Cobertura de tests | 🟡 Parcial (cache, llm_service, schemas e imports sí; falta `_resolve_provider`/streaming) |

Los 5 puntos originales están resueltos o en estado parcial razonable. Lo
que queda es cobertura de tests fina (streaming, `_resolve_provider` con
proveedor no soportado) — no bloquea nada, es pulido.
