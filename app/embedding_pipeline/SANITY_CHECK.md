# Sanity check de embeddings

Ejecutado el 2026-10-18 con `scripts/compare.py` dentro del contenedor
(`docker compose exec api python scripts/compare.py --text-a "..." --text-b "..."`). Ese
script era de la sesión 07; en la 08 lo sustituye `query_examples.py`, y los embeddings
pasan a 1536 dimensiones.

> **Modelo:** `gemini-embedding-001` (3072 dimensiones, vectores normalizados: norma 1,0000
> en los seis textos), no `text-embedding-3-small`. Motivo y alcance en
> [Modelo usado](#modelo-usado). Los umbrales orientativos del enunciado (> 0,6 / < 0,4)
> están pensados para el modelo de OpenAI.

## Resultados

| Pareja | Texto 1 | Texto 2 | Expectativa | Similitud coseno |
|---|---|---|---|---|
| A — cercanos | OAuth 2.0 authentication backend with JWT tokens for fintech mobile app | Authorization service using JSON Web Tokens for a banking application | alta (> 0,6) | **0,7673** |
| B — no relacionados | OAuth 2.0 authentication backend with JWT tokens for fintech mobile app | Database migration from MySQL to PostgreSQL with zero downtime | baja (< 0,4) | **0,5588** |
| C — genéricos | Backend services | API development | sin expectativa fija | **0,6569** |

## Comentario

El orden es el esperado (A > C > B) y A queda claramente por encima de B (+0,21), así que el
modelo discrimina cercano frente a lejano. Lo que no encaja es la escala: B da 0,56, muy por
encima del 0,4 orientativo; Gemini tiene un "suelo" alto y dos textos técnicos de backend
nunca quedan cerca de 0. Llama la atención C: dos frases de dos palabras, sin contexto,
puntúan 0,66, más cerca de A que de B. Con textos genéricos el modelo ve "desarrollo backend"
en ambos y los acerca, aunque no describan lo mismo. Conclusión: los umbrales absolutos no
se trasladan de un modelo a otro y hay que calibrarlos sobre el propio corpus.

## Calibración sobre el corpus (dato para el directo)

Similitud coseno entre todos los pares de los 58 chunks de `data/budgets_sample.json`
(1.653 pares, vectores de `POST /embeddings/ingest`):

| Pares | Mínimo | Mediana | Máximo |
|---|---|---|---|
| Todos | 0,633 | 0,726 | 0,917 |
| Mismo presupuesto (85) | 0,775 | **0,845** | 0,917 |
| Distinto presupuesto (1.568) | 0,633 | **0,724** | 0,834 |

- **La cabecera del presupuesto pesa casi tanto como el componente.** Ocupa ~40 de los ~85
  tokens de cada chunk. Los vecinos más cercanos de `BUD-2024-014::AUTH-001` (OAuth, banca)
  son sus hermanos del mismo presupuesto (PSD2 0,917; cuentas 0,885; monitorización 0,855);
  la autenticación de la clínica (`BUD-2024-005::AUTH-001`, 0,834) queda cuarta. Con
  `BUD-2022-016::MIG-001`, su hermano `SEO-001` (0,827) supera por una milésima a la otra
  migración a PostgreSQL (`BUD-2025-015::DB-001`, 0,826).
- **La plantilla común sube el suelo.** Ningún par del corpus baja de 0,63; la pareja B
  dentro del corpus (auth de banca frente a migración) da 0,69, más que los textos sueltos
  (0,56), porque comparten formato y cabecera.
- Para la búsqueda de la sesión 08 esto importa: un brief sin cabecera se compara contra
  chunks que sí la llevan. Cambiar el chunking queda fuera del alcance de este ejercicio.

## Modelo usado

El enunciado fija `text-embedding-3-small`. Se usa `gemini-embedding-001` porque no hay
cuenta de OpenAI; la clave de Gemini ya existía en el proyecto (caché semántica de la
sesión 05). Los cinco criterios de selección:

| Criterio | `gemini-embedding-001` en este proyecto |
|---|---|
| Dimensionalidad | 3072 por defecto (sin forzar dimensión menor); irrelevante con 58 chunks |
| Idioma | Multilingüe: sirve para componentes en inglés y briefs en español |
| Dominio | Generalista, como el modelo del curso; no hay modelo de "presupuestos de software" |
| Hosting y coste | API; nivel gratuito, coste real $0 (a precio de pago, $0,15/M tokens) |
| Licencia | Propietario; el nivel gratuito puede usar los datos para entrenar (aquí son sintéticos) |

`OpenAIEmbedder` (`text-embedding-3-small`) está implementado con la misma interfaz y se
activa con `EMBEDDING_PROVIDER=openai`, pero **no se ha ejecutado contra la API real**
(solo verificado con un cliente simulado). Con OpenAI los valores de esta tabla cambiarían.
