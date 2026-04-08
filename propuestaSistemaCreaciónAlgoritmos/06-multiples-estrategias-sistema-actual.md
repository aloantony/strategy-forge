# Multiples Estrategias Sistema Actual

## Respuesta corta

Si, parcialmente.

El sistema actual ya resuelve una parte importante del problema:
- cargar varias estrategias activas
- analizarlas en paralelo
- separar operaciones por `magic_number`
- mostrar su identidad en la GUI

Pero no resuelve el problema completo que queremos para el supersistema.

## Que si hace bien hoy

### 1. Multiples estrategias activas

El runtime carga varias estrategias desde `ACTIVE_STRATEGIES` y les asigna una
entrada propia en memoria.

Eso ya permite:
- varias estrategias activas a la vez
- varios timeframes
- varias analisis por ciclo

### 2. Separacion por `magic_number`

La separacion real entre estrategias se hace por `magic_number`.

Consecuencias:
- una estrategia puede abrir posiciones sin mezclar su identidad con otra
- al cerrar o consultar posicion, se filtra por `symbol + magic_number`

### 3. Analisis concurrente

El sistema actual puede analizar varias estrategias en paralelo y luego
ejecutarlas de forma secuencial.

Eso ya es una base razonable para convivencia multi-estrategia.

### 4. Visibilidad en GUI

La GUI mantiene `strategy_registry`, resuelve magics y puede etiquetar deals y
acciones por estrategia.

Eso ayuda a observabilidad, aunque sigue siendo una capa bastante acoplada al
modelo actual.

## Que NO resuelve todavia

## 1. Coordinacion rica entre estrategias

Hoy las estrategias conviven, pero no existe una capa explicita donde el motor
administre una relacion rica entre ellas.

Falta:
- contexto multi-estrategia formal
- exposicion agregada por estrategia como contrato canonico
- identificacion de instancias mas alla del `magic_number`
- protocolo claro de resolucion de conflictos

## 2. Modelo de acciones

Hoy la salida real de estrategia sigue siendo:
- `buy`
- `sell`
- `none`

No existe todavia un contrato donde varias estrategias emitan `actions`
declarativas avanzadas y el motor las interprete.

## 3. Estado persistente por estrategia

El sistema actual no tiene el modelo formal nuevo de:
- `context`
- `state`
- `plan`
- `execution_report`

Por tanto, la convivencia existe, pero no con memoria estrategica versionada ni
persistencia atomica por instancia.

## 4. Gestion fina de posiciones por estrategia

Esta es la limitacion mas fuerte.

Hoy el alcance operativo de una estrategia esta esencialmente agregado por
`symbol + magic_number`.

Eso implica varias restricciones:
- no hay modelo explicito de legs independientes
- no hay parciales declarativos ricos
- no hay gestion nativa de piramides como entidades separadas
- no hay targeting fino de una entrada concreta dentro de la misma estrategia

En la practica, el modelo actual entiende mejor:
- una estrategia
- un simbolo
- una direccion dominante

que:
- una estrategia con varias entradas independientes vivas a la vez

## 5. Reporte e idempotencia

Hoy tampoco existe un contrato fuerte de:
- `plan_id`
- `action_id`
- `execution_report`
- `skipped_duplicate`

Asi que la convivencia actual funciona, pero no tiene el nivel de trazabilidad e
idempotencia que buscamos.

## Conclusión

El sistema actual ya tiene convivencia basica multi-estrategia.

Eso es valioso y no hay que tirarlo.

Pero esa convivencia esta construida sobre un modelo todavia simple:
- senal por estrategia
- ejecucion centralizada fija
- separacion por `magic_number`

El supersistema propuesto va un paso mucho mas alla:
- contexto formal
- state formal
- plan formal
- interprete de actions
- ejecucion auditable
- convivencia de estrategias e instancias con mas granularidad

