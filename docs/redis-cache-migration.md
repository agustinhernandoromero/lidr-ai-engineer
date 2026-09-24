# Migración de la caché: memoria → Redis

Notas de la sesión de trabajo en la rama `infra/redis-cache-fallback`
(partiendo de `sesion-04-chat-vs-producto`, commit `3935be3`). Sirven para
retomar el trabajo aunque se pierda el contexto de la conversación.

## Por qué lo hicimos

Al comparar el proyecto con la referencia del curso (`session_4/estimator`
en el repo de LIDR), se detectaron varios huecos de robustez. Este
documento cubre el primero: la caché de respuestas del LLM vivía en un
`OrderedDict` dentro del proceso de Python (`app/services/cache.py`).
Problema concreto:

- **Se pierde al reiniciar** el servidor (cada `--reload` o deploy la vacía).
- **No se comparte entre workers**: si algún día corres
  `uvicorn --workers 4`, cada proceso tiene su propio diccionario, así que
  una petición puede caer en el worker A (miss, llama al LLM) y la misma
  petición justo después en el worker B (otro miss).

La referencia del curso resuelve esto con Redis: un proceso externo
compartido por todos los workers, que persiste aunque la API se reinicie.

## Qué NO cambió

La lógica de caché sigue siendo "exact-match": la clave es un hash
determinista de `(provider, model, system_prompt, user_message)`. Cambiar
una coma en el prompt genera una clave distinta y, por tanto, un cache miss.
Lo único que cambió es **dónde se guarda** ese diccionario.

## Cambios, paso a paso

### 1. Dependencias y configuración

- `pyproject.toml`: `redis` en dependencias principales (lo usa la app en
  producción); `fakeredis` en `dev` (solo lo usan los tests, no debe
  instalarse en producción).
- `app/config.py`: nuevas settings `REDIS_URL` (default
  `redis://localhost:6379/0`) y `CACHE_TTL` (default `86400`, 24h).
- `.env.example`: documentadas ambas, con el comando Docker para levantar
  Redis en local.

### 2. La clase `EstimationCache` (`app/services/cache.py`)

Antes eran funciones sueltas de módulo (`make_key`, `get`, `set`) operando
sobre un `OrderedDict` global. Ahora es una clase que envuelve un cliente
`redis.Redis`:

- `EstimationCache.from_url(url, ttl)` — factory a partir de la
  `REDIS_URL`.
- `make_key(...)` — igual que antes pero serializando con
  `json.dumps(sort_keys=True)` en vez de concatenar strings (más robusto
  ante colisiones).
- `get(key)` / `set(key, value)` — hablan con Redis. **Si Redis falla**
  (`redis.RedisError`), no propagan la excepción: `get` devuelve `None`
  (se trata como cache miss) y `set` simplemente no escribe. La API nunca
  se cae por culpa de la caché.

### 3. Inyección del singleton (`app/dependencies.py`, nuevo)

Mismo patrón que ya existía para `get_settings()`: una función decorada
con `@lru_cache` que construye el objeto una sola vez y lo reutiliza en
todo el proceso.

```python
@lru_cache
def get_cache() -> EstimationCache:
    settings = get_settings()
    return EstimationCache.from_url(settings.REDIS_URL, ttl=settings.CACHE_TTL)
```

### 4. `app/services/llm_service.py`

`generate_estimation()` ya no importa el módulo `cache`; ahora hace
`cache = get_cache()` al principio (igual que ya hacía con
`settings = get_settings()`) y llama a sus métodos.

## Tests (`tests/test_cache.py`, nuevo)

Dos escenarios, cada uno con una herramienta distinta — esto es importante,
no son redundantes:

1. **"Redis funciona"** → `fakeredis.FakeRedis`, una implementación en
   memoria que respeta la misma interfaz que `redis.Redis`. Prueba
   `make_key` (determinismo, sensibilidad a cada campo), el roundtrip
   `set`→`get`, y que el TTL se aplica.
2. **"Redis está caído"** → un `Mock` cuyo `.get()`/`.set()` lanzan
   `redis.ConnectionError` a propósito. Prueba que `EstimationCache`
   degrada a `None` sin lanzar excepción.

`fakeredis` prueba que la caché funciona; el mock que falla prueba que
*cuando no funciona*, no tumba la API.

## Verificación manual con Redis real

Con Docker Desktop abierto:

```bash
docker run -d --name redis -p 6379:6379 redis:7-alpine
docker exec redis redis-cli ping   # → PONG
```

Se hizo una prueba con dos peticiones idénticas a `/api/v1/estimate`
(LLM mockeado): la 1ª dio `cache_miss` + `cached=False`; la 2ª dio
`cache_hit` + `cached=True` sin volver a llamar al LLM. Se confirmó
también con `redis-cli keys '*'` y `redis-cli ttl <clave>` (~86389s,
coherente con `CACHE_TTL=86400`).

Para retomar en otra sesión: `docker start redis` (se paró al final de
esta sesión con `docker stop redis`, los datos no se borran a menos que
se haga `docker rm`).

## Resultado

- 30/30 tests pasan (20 preexistentes + 10 nuevos de `test_cache.py`).
- Commit: `2eccf20` — *"Reemplazar caché en memoria por Redis (persistente
  y compartida)"*, en `infra/redis-cache-fallback`.
- La rama `sesion-04-chat-vs-producto` (la entrega del curso) no se tocó.

## Pendiente (siguiente sesión)

De la comparativa original con la referencia del curso, quedan dos puntos
relacionados entre sí:

1. **Fallback entre proveedores LLM**: la referencia envuelve LiteLLM con
   un `Router` que hace fallback automático de modelo primario a
   secundario, reintentos configurables y tracking de coste en USD. Hoy
   `llm_service.py` llama directo al SDK de OpenAI o Anthropic según un
   único proveedor configurado — si esa API falla, no hay red de
   seguridad.
2. **DI del LLM wrapper**: seguir el mismo patrón que `get_cache()` para
   inyectar el wrapper del LLM, en vez de las funciones sueltas actuales
   (`call_openai`, `call_anthropic`, etc.).

Puntos ya identificados pero no abordados todavía: `description` limitado
a 2000 caracteres (vs 80000 en la referencia — una transcripción real de
reunión podría no caber), y la cobertura de tests de `llm_service.py` más
allá del único endpoint mockeado.
