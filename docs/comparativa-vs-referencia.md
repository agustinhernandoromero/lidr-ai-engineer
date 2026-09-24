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

### 2. Sin fallback de proveedor ni reintentos — ⏳ PENDIENTE

La referencia envuelve LiteLLM con un `Router` que hace fallback
automático de modelo primario a secundario, reintentos configurables,
timeout y tracking de coste en USD por llamada. Aquí `llm_service.py`
llama directo al SDK de OpenAI o Anthropic según el único proveedor
configurado en `.env`: si esa API falla, no hay red de seguridad, la
petición simplemente falla. Es el hueco funcional más importante que
queda.

### 3. Sin capa de inyección de dependencias — 🟡 PARCIAL

La referencia tiene `dependencies.py` con singletons (`get_cache`,
`get_llm_wrapper`) inyectados vía `Depends()`, lo que permite
sobreescribirlos limpiamente en tests. Aquí ya existe `get_cache()`
siguiendo ese patrón (paso 1 de hoy), pero el LLM wrapper sigue siendo
funciones sueltas (`call_openai`, `call_anthropic`, `_resolve_provider`)
sin envolver en una clase inyectable. Queda ligado al punto 2: cuando se
implemente el fallback, tiene sentido envolverlo en una clase y exponerla
vía `get_llm_wrapper()`.

### 4. `description` limitado a 2000 caracteres — ⏳ PENDIENTE

La referencia permite hasta 80000 caracteres; aquí el límite es 2000.
Los ejemplos de datos del propio repo (`data/transcription_meeting.txt`,
~1069 caracteres) caben, pero una transcripción real de una reunión larga
—que es el caso de uso principal— podría no caber. Cambio sencillo en
`app/schemas.py` (`EstimationRequest.description`), pendiente de decidir
un límite razonable.

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
| 2 | Fallback de proveedor | ⏳ Pendiente |
| 3 | Inyección de dependencias | 🟡 Parcial (cache sí, LLM wrapper no) |
| 4 | Límite de `description` | ⏳ Pendiente |
| 5 | Cobertura de tests | 🟡 Parcial (cache sí, llm_service no) |

Los puntos 2 y 3 conviene abordarlos juntos en la próxima sesión, ya que
el fallback requiere envolver el LLM wrapper en una clase, momento natural
para inyectarla igual que se hizo con la caché.
