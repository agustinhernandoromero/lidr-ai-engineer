# Estrés del CAG — sesión 06

Datos: `evals/stress/results.csv`. Generado por `evals/stress/report.py`.

## Resumen

| Bloque | Escenario | Adjunto (KB) | Filas | Latencia P50 sin caché (ms) | Latencia P95 sin caché (ms) | Coste total ($) | Caché exacta | Caché semántica | Recuerdo medio |
|---|---|---|---|---|---|---|---|---|---|
| multiturn | growing | 0 | 10 | 28288 | 66230 | 0.3911 | 0% | 0% | 1.00 |
| multiturn | pivot | 0 | 10 | 31750 | 45484 | 0.3472 | 0% | 0% | 0.89 |
| multiturn | contradiction | 0 | 10 | 19554 | 55398 | 0.2621 | 0% | 0% | 0.65 |
| attachment | attachment | 0 | 4 | 13457 | 13457 | 0.0104 | 75% | 0% | — |
| attachment | attachment | 5 | 4 | 16626 | 16626 | 0.0132 | 75% | 0% | 1.00 |
| attachment | attachment | 20 | 4 | 15493 | 15493 | 0.0211 | 75% | 0% | 1.00 |
| attachment | attachment | 50 | 4 | 28563 | 28563 | 0.0366 | 75% | 0% | 0.33 |
| attachment | attachment | 100 | 4 | 15048 | 15048 | 0.0293 | 75% | 0% | 0.33 |

## Curva 1 — latencia frente a tokens de entrada (turnos sin caché)

| tokens_in | Turnos | Latencia media (ms) | Latencia P95 (ms) |
|---|---|---|---|
| 0–5.000 | 2 | 13659 | 15276 |
| 5.000–10.000 | 11 | 18173 | 26275 |
| 10.000–15.000 | 4 | 24083 | 27215 |
| 15.000–20.000 | 4 | 25259 | 31750 |
| ≥ 20.000 | 14 | 43982 | 66230 |

## Curva 2 — coste acumulado (USD) frente a turno

| Turno | growing | pivot | contradiction |
|---|---|---|---|
| 1 | 0.0167 | 0.0085 | 0.0096 |
| 2 | 0.0351 | 0.0205 | 0.0225 |
| 3 | 0.0597 | 0.0345 | 0.0367 |
| 4 | 0.0864 | 0.0516 | 0.0535 |
| 5 | 0.1174 | 0.0858 | 0.0734 |
| 6 | 0.1766 | 0.1487 | 0.0954 |
| 7 | 0.2218 | 0.1968 | 0.1216 |
| 8 | 0.2672 | 0.2448 | 0.1782 |
| 9 | 0.3152 | 0.2965 | 0.2055 |
| 10 | 0.3911 | 0.3472 | 0.2621 |

## Curva 3 — recuerdo de hechos frente a N

| N | growing (memoria / +ventana) | pivot (memoria / +ventana) | contradiction (memoria / +ventana) | Nombre del proyecto recordado |
|---|---|---|---|---|
| 1 | — / — | — / — | — / — | 3/3 |
| 3 | 1.00 / 1.00 | 1.00 / 1.00 | 0.50 / 1.00 | 3/3 |
| 6 | 1.00 / 1.00 | 0.80 / 1.00 | 0.60 / 1.00 | 3/3 |
| 10 | 1.00 / 1.00 | 0.78 / 1.00 | 0.78 / 1.00 | 3/3 |

## Adjuntos

| Adjunto (KB) | Rep | Caché | Chars adjunto | tokens_in | Latencia (ms) | Coste ($) | Recuerdo adjunto |
|---|---|---|---|---|---|---|---|
| 0 | 1 | none | 0 | 5772 | 13456.6 | 0.010357 | — |
| 0 | 2 | exact | 0 | 0 | 1.8 | 0.0 | — |
| 0 | 3 | exact | 0 | 0 | 1.8 | 0.0 | — |
| 0 | 4 | exact | 0 | 0 | 1.7 | 0.0 | — |
| 5 | 1 | none | 5036 | 6690 | 16626.1 | 0.01319 | 1.0 |
| 5 | 2 | exact | 5036 | 0 | 2.3 | 0.0 | 1.0 |
| 5 | 3 | exact | 5036 | 0 | 1.8 | 0.0 | 1.0 |
| 5 | 4 | exact | 5036 | 0 | 1.8 | 0.0 | 1.0 |
| 20 | 1 | none | 20039 | 15118 | 15493.1 | 0.021098 | 1.0 |
| 20 | 2 | exact | 20039 | 0 | 2.0 | 0.0 | 1.0 |
| 20 | 3 | exact | 20039 | 0 | 2.2 | 0.0 | 1.0 |
| 20 | 4 | exact | 20039 | 0 | 2.3 | 0.0 | 1.0 |
| 50 | 1 | none | 20043 | 24405 | 28562.9 | 0.03658 | 0.333 |
| 50 | 2 | exact | 20043 | 0 | 2.0 | 0.0 | 0.333 |
| 50 | 3 | exact | 20043 | 0 | 2.0 | 0.0 | 0.333 |
| 50 | 4 | exact | 20043 | 0 | 2.0 | 0.0 | 0.333 |
| 100 | 1 | none | 20043 | 23306 | 15048.5 | 0.029346 | 0.333 |
| 100 | 2 | exact | 20043 | 0 | 1.9 | 0.0 | 0.333 |
| 100 | 3 | exact | 20043 | 0 | 2.0 | 0.0 | 0.333 |
| 100 | 4 | exact | 20043 | 0 | 2.0 | 0.0 | 0.333 |

## Lectura

**¿Dónde empieza a romperse mi CAG y qué dimensión domina?** Lo primero que se rompe es la
**latencia**, seguida muy de cerca por el **coste**. Hacia el turno 5–6 el contexto de un
turno supera los 20.000 tokens de entrada y la latencia media pasa de 18 s (5.000–10.000
tokens) a 44 s (P95 66 s). El presupuesto de 20 s solo se cumple en 10 de los 30 turnos
multiturno, y el de $0,02 por turno en 11 de 30. **El coste del turno 10 multiplica entre
4,5 y 6 veces el del turno 1** (growing: $0,0167 → $0,0759), y una conversación de 10 turnos
cuesta entre $0,26 y $0,39. El crecimiento no es solo lineal por el historial: con el
proyecto crece también la propia respuesta estructurada (más fases, más de 15 exclusiones,
resúmenes de más de 1.500 caracteres) hasta romper los límites del esquema. Eso provoca
**21 reintentos en 30 turnos** (12 por confianza baja sin el prefijo "Fuera de alcance:"),
y cada reintento reenvía todo el contexto. Es un **fallo duro**, pero silencioso para el
usuario: Pydantic lo detecta y el turno acaba saliendo, aunque al doble de precio. La memoria
aguanta mejor en apariencia: el nombre del proyecto se recuerda en los 3 escenarios en
N = 10, y con la ventana todos los hechos siguen presentes en N = 10. Pero la **memoria
persistente** (resumen, anclas y metadata, lo único que sobrevive cuando la ventana se vacía)
**degrada en silencio**: baja a 0,78 en pivot y en contradiction, y contradiction llegó a
0,50 en N = 3. En pivot, `mentioned_technologies` acumula React Native, React y Flutter a la
vez, porque la fusión solo añade y nunca retira. En contradiction, el turno 9 promueve a
**ancla vinculante el presupuesto viejo (30.000 €)** mientras el vigente (80.000 €) no
aparece en ninguna memoria persistente. Ningún test se pone rojo por esto, y es lo más
peligroso del sistema: el modelo recibe como compromiso firme un dato ya corregido.

**¿Qué caso límite justifica saltar a RAG?** Los adjuntos lo muestran con más claridad que
nada. Con el límite real de 20.000 caracteres, los PDF de 50 y 100 mil caracteres llegan
truncados a 20.043. El coste y los tokens se aplanan (≈ 24.000 tokens de entrada), pero el
**recuerdo del adjunto cae de 1,00 a 0,33**: los requisitos situados al 50 % y al 90 % del
documento (Twilio, Salesforce) desaparecen sin más aviso que un warning. Un CAG solo puede
meter lo que cabe; una especificación de 20 páginas ya no cabe, y truncar no es degradar
con gracia, es perder la mitad del documento en silencio. El segundo caso límite es una
conversación que **corrige hechos**: acumular memoria (resumen + anclas) conserva lo antiguo
junto a lo nuevo sin saber cuál manda, mientras que recuperar el fragmento relevante y más
reciente en cada turno lo resolvería. El tercero es económico: a partir de unos 6 turnos
cada turno cuesta alrededor de $0,05 y 45 s por reenviar entre 25.000 y 45.000 tokens que en
su mayoría no hacen falta para responder. RAG sustituye "mandarlo todo" por "mandar lo
pertinente". La caché exacta del turno 1 ayuda en lo repetido (2 ms frente a 13–29 s), pero
no toca este problema: en esta ejecución la semántica no acertó ninguna vez y a partir del
turno 2 no se puede cachear.

*Limitaciones de esta medición:* escala mínima (una conversación por escenario, sin
repeticiones del multiturno, así que no hay varianza); los hechos se comparan por
coincidencia exacta ("30.000" frente a "30 000 €" cuenta como fallo); los turnos fallidos no
registrarían su coste, aunque en esta ejecución no falló ninguno; no se midieron ráfagas
concurrentes; y la ejecución costó **$1,11** en total, frente a una estimación previa de
$0,60, precisamente por los reintentos que describe el primer párrafo.

## Método

- **Escala** (decidida para no gastar de más): 3 conversaciones de 10 turnos, una por
  escenario, y 5 tamaños de adjunto × 4 repeticiones en el turno 1 (50 filas). Las
  curvas por N se leen en los turnos 1, 3, 6 y 10 de la misma conversación.
- **Constantes sin tocar**: ventana `MAX_TURNS=6`, `MAX_ATTACHMENT_CHARS=20.000`,
  umbral semántico 0,92. "KB" de adjunto = miles de caracteres de texto del PDF.
- **Observación**: un evento `turn_observed` por turno (13 campos + `llm_calls`,
  `structured_attempts`, `tier_rule`) que agrega todas las llamadas del turno; un único
  evento se convierte a CSV en una pasada, sin reconciliar marcas de tiempo.
- **Métricas** en `evals/stress/metrics.py` (aparte de `evals/metrics.py` porque evalúan
  la observación y el snapshot, no un `EstimationResult`): `LatencyBudgetMetric(20.000 ms)`,
  `CostBudgetMetric($0,02)`, `MemoryDriftMetric` (coincidencia exacta sin mayúsculas en
  resumen, anclas y metadata). `memory_recall_with_window` añade la ventana para separar
  "olvidado" de "aún en ventana".
- **Repeticiones de adjuntos**: las repeticiones 2–4 aciertan en la caché exacta; miden la
  caché, no la latencia del LLM. Por eso la latencia P50/P95 se calcula solo sobre turnos
  sin caché, y coste y recuerdo de esas repeticiones son copias de la primera.
- **Latencia**: `latency_ms` cubre el turno en el servicio (render, caché, LLM, extracción,
  compresión); no incluye la extracción del PDF en el router ni el tiempo de red.
- **Turno 1**: no tiene hechos anteriores que recordar; su recuerdo queda en blanco y no
  cuenta en las medias.
- **No medido**: ráfagas concurrentes (sin bloque en el enunciado) y conversaciones de
  más de 10 turnos.
