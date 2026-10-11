# Golden dataset — actor frente a Actor-Critic-Boss

Datos: `evals/results.json` (modelo `claude-haiku-4-5-20251001`, 2026-10-11T17:41:07+00:00). Generado por `evals/report.py`.

## Resumen por modo

| Modo | Casos | Esquema | Horas | Contenido | Tier | Métricas OK | Coste total ($) | Coste medio por caso ($) | Latencia media (ms) |
|---|---|---|---|---|---|---|---|---|---|
| actor | 16 | 16/16 | 4/16 | 16/16 | 15/16 | 51/64 (80%) | 0.1819 | 0.0114 | 18477 |
| acb | 16 | 16/16 | 6/16 | 16/16 | 15/16 | 53/64 (83%) | 0.2507 | 0.0157 | 21873 |

## Caso a caso

| Caso | Actor | ACB | Decisión del jefe | Falló en actor | Falló en ACB |
|---|---|---|---|---|---|
| caso-01-saas-crm | 0.75 | 1.00 | aceptar | hours_bounds | — |
| caso-02-movil-fidelizacion | 0.75 | 0.75 | aceptar | hours_bounds | hours_bounds |
| caso-03-interna-incorporacion | 0.75 | 1.00 | aceptar | hours_bounds | — |
| caso-04-pipeline-etl | 0.75 | 0.75 | aceptar | hours_bounds | hours_bounds |
| caso-05-fuera-vago | 1.00 | 1.00 | aceptar | — | — |
| caso-06-fuera-inyeccion | 1.00 (bloqueado) | 1.00 (bloqueado) | — | — | — |
| caso-07-nda-ejecutivo | 0.75 | 1.00 | aceptar | hours_bounds | — |
| caso-08-rgpd-ejecutivo | 1.00 | 1.00 | aceptar | — | — |
| caso-09-hipaa-ejecutivo | 0.75 | 0.75 | aceptar | hours_bounds | hours_bounds |
| caso-10-equipo-pequeno | 0.75 | 0.50 | aceptar | tier | hours_bounds, tier |
| caso-11-dev-microservicios | 0.75 | 0.75 | aceptar | hours_bounds | hours_bounds |
| caso-12-streaming-kafka | 0.75 | 0.75 | aceptar | hours_bounds | hours_bounds |
| caso-13-fintech-movil | 0.75 | 0.75 | aceptar | hours_bounds | hours_bounds |
| caso-14-interna-conocimiento | 0.75 | 0.75 | aceptar | hours_bounds | hours_bounds |
| caso-15-marketplace | 0.75 | 0.75 | aceptar | hours_bounds | hours_bounds |
| caso-16-plazo-imposible | 0.75 | 0.75 | aceptar | hours_bounds | hours_bounds |

## Qué cambió el ACB

**Arregló (3):** caso-01-saas-crm (0.75 → 1.00), caso-03-interna-incorporacion (0.75 → 1.00), caso-07-nda-ejecutivo (0.75 → 1.00)

**Rompió (1):** caso-10-equipo-pequeno (0.75 → 0.50)

**Igual (12)**

## Decisiones del jefe

- aceptar: 15
- rehacer: 0
- sintetizar: 0

## Lectura

**¿Mejora el Actor-Critic-Boss la calidad, y a qué precio?** Poco y caro. El ACB acierta
53 de 64 métricas frente a 51 del actor (83 % frente a 80 %) y cuesta un 38 % más
($0,25 frente a $0,18 en 16 casos). Arregla tres casos (01, 03 y 07, que suben las horas
hasta el rango) y empeora uno (caso-10, por solo 4 horas por debajo del mínimo). Pero el
crítico **aceptó los 15 borradores que revisó** (el de inyección no llega al LLM): solo
pidió rehacer dos veces (07 y 11) y en ambos casos aceptó la segunda versión. La mejora no viene de que el crítico detecte el
fallo de fondo, sino de que el segundo intento del actor sale algo más alto. Donde todo
coincide, las métricas ya estaban bien en los dos modos: el contenido se recuerda en el
100 % de los casos, los dos fuera de alcance se detectan (el vago con "Fuera de alcance:",
la inyección bloqueada por el guardrail a $0) y el tier acierta en todo salvo caso-10, la
limitación conocida de `small_team_pm` en el turno 1.

**¿Qué falla de verdad?** Las horas, y siempre por debajo: los 22 fallos de `hours_bounds`
están bajo el mínimo del rango; ninguno por encima. No es un rango mal puesto: el
estimador se contradice a sí mismo. En los cinco casos con equipo conocido, sus horas
cubren solo entre el 24 % y el 47 % de la capacidad que implican su propio plazo y su
propio equipo. El CRM con 3 personas y 8 semanas son 768 h de capacidad, pero estima
175–275 h; los microservicios con 5 personas y 26 semanas son 4.160 h, pero estima
520–1.010 h. El caso del plazo imposible lo muestra mejor que ninguno: los dos modos
prometen las 2 semanas pedidas y el ACB baja a 56–95 h un e-commerce de 500 productos con
pagos, y el crítico lo acepta. El crítico no lo detecta porque su regla de
`estimacion_irreal` solo salta con desvíos de más del 50 % "a ojo" y nadie le da la cuenta
de capacidad. El arreglo más barato no es otro LLM, sino una comprobación determinista:
horas frente a equipo × semanas × 32 h, como validador del esquema (reintento) o como dato
para el crítico. Esa es la siguiente mejora que este golden dataset justifica, y el mismo
examen dirá si funciona.

*Limitaciones:* una sola ejecución por modo (sin varianza); los rangos de horas son
reglas de oficio y la métrica exige que el intervalo estimado quepa entero, lo que
penaliza ensanchar el rango; la caché del turno 1 estuvo desactivada para que actor y ACB
partan igual. Coste total de la ejecución: $0,43 (32 ejecuciones).

## Método

- **Casos:** 16 en `evals/golden_dataset.json` (14 dentro de alcance, 2 fuera; 7 con tier
  distinto de `default`). Cada caso va en una sesión nueva, de un solo turno.
- **Métricas** (`evals/metrics.py`, deterministas, sin LLM-as-judge):
  `schema_adherence` (reglas de negocio), `hours_bounds` (fases, horas y semanas dentro de
  rangos anchos; el intervalo estimado debe caber en el esperado), `content_recall` (lo
  pedido aparece en resumen, fases o supuestos) y `tier` (audiencia detectada).
- **Fuera de alcance:** acierta si el resumen empieza por "Fuera de alcance:" o si un
  guardrail lo bloqueó (400). Un bloqueo de un caso normal cuenta como fallo.
- **caso-10 falla a propósito:** `small_team_pm` lee el tamaño de equipo de la memoria,
  vacía en el turno 1, así que un caso de un solo turno nunca da `pm`.
- **Caché:** la del turno 1 se vacía antes de la ejecución; el ACB no la usa.
