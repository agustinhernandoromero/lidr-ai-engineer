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
