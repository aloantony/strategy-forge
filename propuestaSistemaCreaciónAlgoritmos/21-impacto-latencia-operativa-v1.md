# Impacto En Latencia Operativa v1

## Pregunta

Si las decisiones de arquitectura ya fijadas pueden afectar la latencia de las
operaciones.

Respuesta corta:
- si, algunas la aumentan
- pero de forma deliberada y controlada
- a cambio reducen mucho el riesgo de ejecucion incorrecta

La clave es distinguir:
- latencia de decision
- latencia de ejecucion
- latencia total percibida
- latencia de recuperacion cuando algo falla

## Respuesta corta y honesta

Si.

Las decisiones que hemos tomado añaden algo de latencia tecnica frente a un
bot minimalista que:
- mira una senal
- llama directo a `order_send`
- y no revalida nada

Pero ese bot mas rapido tambien es mucho mas propenso a:
- dobles entradas
- cierres incorrectos
- retries ciegos
- desincronizacion con broker
- corrupcion del libro interno

Nuestra propuesta cambia:
- un poco mas de latencia media
- por mucha mas coherencia y seguridad tecnica

## Donde se añade latencia

## 1. Refresh broker previo a decision

Cada iteracion para simbolos activos hace al menos una lectura ligera:
- posiciones
- ordenes pendientes

Eso añade coste, aunque moderado.

Impacto:
- aumenta algo la latencia del ciclo completo
- mejora mucho la calidad del `decision_snapshot`

## 2. Revalidacion antes de ejecutar

Antes de ejecutar un plan:
- se toma `execution_snapshot`
- se relee broker del simbolo
- se resuelven targets otra vez

Eso añade un paso que hoy en el sistema actual es mucho mas pobre.

Impacto:
- sube latencia antes del envio final
- evita actuar sobre estado viejo

## 3. Serializacion por simbolo

Si dos planes tocan el mismo simbolo:
- no se ejecutan a la vez
- van en cola

Eso puede introducir espera adicional bajo carga.

Impacto:
- peor throughput por simbolo
- mucha mejor coherencia por simbolo

## 4. Lock global de broker en v1

Hemos decidido mantener I/O mutante con MT5 en modo conservador:
- serial global

Eso significa que aunque dos simbolos sean independientes a nivel logico:
- el envio fisico a broker no sera totalmente paralelo en v1

Impacto:
- latencia adicional en escenarios multi-simbolo muy activos
- menos riesgo de problemas raros de thread-safety con MT5

## 5. Persistencia y logging

Guardar:
- `plans`
- `execution_reports`
- `event_log`
- recursos canonicos

añade escritura local y algo de procesamiento.

Impacto:
- pequeno frente a red/broker
- relevante si el sistema hiciera muchisimas acciones por segundo

En este proyecto, lo normal es que el cuello de botella sea MT5 o broker, no
SQLite.

## 6. Reconciliacion tras ambiguedad

Si una orden queda en estado ambiguo:
- no se reintenta al instante
- primero se reconcilia

Eso claramente aumenta la latencia de recuperacion.

Impacto:
- peor tiempo de reaccion ante error ambiguo
- muchisimo menor riesgo de duplicar la operacion

## Donde NO deberia penalizar demasiado

## 1. Decision en paralelo

Las estrategias siguen pudiendo decidir en paralelo por instancia.

Eso amortigua parte del coste extra de la arquitectura.

## 2. Snapshot estable por iteracion

Construir un snapshot no significa copiar el universo entero infinitamente.

Si se implementa bien:
- se reutiliza mercado por simbolo/timeframe
- se serializa solo la metadata necesaria

## 3. SQLite local

Mientras se use en local y con transacciones cortas:
- el coste suele ser bajo
- sobre todo comparado con la latencia externa del broker

## Donde SI puede notarse de verdad

La latencia se puede notar de verdad en estos casos:

## Caso 1: alta contencion sobre el mismo simbolo

Muchas estrategias o muchos planes sobre `EURUSD`, por ejemplo.

Como hay:
- cola por simbolo
- revalidacion
- broker lock global

la espera acumulada puede crecer.

## Caso 2: estrategias hiperfrecuentes

Si quisieras HFT o reaccion intrabar ultra agresiva:
- esta arquitectura v1 es demasiado conservadora

No esta pensada para exprimir microsegundos.
Esta pensada para trading automatizado robusto.

## Caso 3: broker lento o inestable

Si MT5 o el broker tardan en responder:
- toda la politica de reconciliacion y retries hace mas visible esa lentitud

Pero la lentitud ya existia.
La arquitectura no la crea; la hace gestionable.

## Lo importante: latencia media vs latencia segura

Hay una trampa comun en estos sistemas:
- optimizar para mandar antes la orden
- aunque eso aumente mucho la probabilidad de mandar la orden equivocada

Yo prefiero separar dos conceptos:

- latencia media minima
- latencia segura minima

La propuesta no optimiza la primera al maximo.
Optimiza la segunda.

Es decir:
- intenta ser lo mas rapida posible
- sin dejar de ser confiable

## Impacto esperado por tipo de operativa

## Swing / intradia tranquilo

Impacto:
- practicamente irrelevante

Si operas en:
- M5
- M15
- H1

unos cientos de milisegundos o algun segundo extra en casos raros no cambian la
estrategia de fondo.

## Intradia mas agresivo

Impacto:
- moderado

Puede importar en entradas muy ajustadas, pero sigue siendo razonable si el
sistema no busca ultra alta frecuencia.

## Scalping muy rapido / HFT

Impacto:
- alto

Esta v1 no esta diseñada para competir en ese terreno.

## Mi lectura para tu proyecto

Por lo que vienes planteando, tu objetivo es:
- un supersistema potente
- con estrategias ricas
- con pyramiding
- con estado
- con control de ownership
- con auditoria fuerte

Para ese objetivo, la decision correcta no es:
- minimizar latencia a cualquier precio

La decision correcta es:
- minimizar errores de ejecucion sin volver el sistema torpe

## Regla practica que yo defenderia

Para este proyecto:
- aceptar una pequena penalizacion de latencia normal
- no aceptar duplicados, cierres cruzados o reconciliacion pobre

En otras palabras:
- mejor 150 ms mas lento y correcto
- que 150 ms mas rapido y capaz de romper el libro

## Como contener esa latencia sin romper la arquitectura

Hay varias medidas compatibles con lo ya decidido:

1. Mantener decision en paralelo.
2. Hacer refresh broker ligero antes de decidir y no reconciliacion completa en
   cada ciclo.
3. Reconciliacion completa solo cuando toca:
   - ambiguedad
   - drift
   - timer periodico
   - bootstrap
4. Usar transacciones SQLite cortas.
5. Reutilizar datos de mercado por iteracion.
6. Mantener `symbol_book_lock` por simbolo y no un lock logico global.
7. Dejar el lock global solo para I/O fisico MT5 en v1.

## Decision final

Si, la arquitectura propuesta añade latencia operativa.

Pero no me parece una mala noticia.

Me parece el coste correcto de pasar de:
- un bot de senales simple

a:
- un motor de estrategias serias con estado, ownership, reconciliacion y
  auditoria

La pregunta correcta no es:
- "anade latencia?"

La pregunta correcta es:
- "la latencia adicional esta justificada por la seguridad y coherencia que
  gana el sistema?"

Mi respuesta aqui es:
- si, para este proyecto, claramente si
