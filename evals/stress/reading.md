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
