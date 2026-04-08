# Convivencia Multiples Estrategias V1

## Objetivo

Definir como conviven varias estrategias a la vez en una misma cuenta:
- si pueden compartir simbolo
- como compiten por exposicion
- como se identifican sus posiciones
- como evita el motor que se pisen entre si

## Resumen ejecutivo

Decision v1:
- varias estrategias pueden coexistir en la misma cuenta
- por defecto ven el estado global de la cuenta
- por defecto solo pueden actuar sobre recursos que poseen
- compartir simbolo esta permitido
- la convivencia exacta depende de `account.position_mode`

## Principio central

La cuenta es compartida.
La propiedad operativa es aislada.

Eso significa:
- todas las estrategias comparten equity, margen y mercado
- pero no deben modificar posiciones u ordenes ajenas por accidente

## Unidad de convivencia

La unidad real no debe ser solo "estrategia".
Debe ser `strategy_instance`.

Formato conceptual:

```python
strategy_instance = {
    "strategy_key": "adx_di_pyramid",
    "instance_id": "adx_di_pyramid::DE40",
    "symbol": "DE40",
}
```

Motivo:
- una misma estrategia podria correr varias veces
- incluso sobre el mismo simbolo con perfiles distintos
- la propiedad debe estar ligada a la instancia, no solo al nombre del archivo

## Niveles de realidad

Conviene pensar en tres niveles:

### 1. Cuenta

Compartido por todas las estrategias:
- balance
- equity
- margen
- exposicion total

### 2. Symbol book

Todo lo que ocurre sobre un simbolo concreto.

Ejemplo:
- todas las posiciones y ordenes relacionadas con `DE40`

### 3. Instance book

Subconjunto del symbol book perteneciente a una instancia concreta.

Ejemplo:
- todas las legs de `adx_di_pyramid::DE40`

## Regla de visibilidad

Por defecto:
- todas las estrategias pueden observar la cuenta global
- todas las estrategias pueden observar exposicion agregada por simbolo
- una estrategia puede observar explicitamente sus propios recursos

Esto es necesario para que una estrategia pueda autodisciplinarse si quiere.

## Regla de mutacion

Por defecto:
- una estrategia solo puede abrir, cerrar o modificar recursos de su propia
  `strategy_instance`

Consecuencia:
- no puede mover el stop de otra estrategia
- no puede cerrar parciales de otra estrategia
- no puede cancelar pending orders de otra estrategia

## Como se identifican posiciones y ordenes

Cada recurso operativo debe llevar identidad rica.

Campos minimos propuestos:

```python
position = {
    "broker_position_id": "...",
    "symbol": "DE40",
    "side": "long",
    "strategy_key": "adx_di_pyramid",
    "instance_id": "adx_di_pyramid::DE40",
    "entry_group_id": "grp_001",
    "leg_id": "leg_002",
    "opened_by_plan_id": "plan_000124",
    "opened_by_action_id": "act_0001",
    "tags": {...},
}
```

Objetivo de cada identificador:
- `broker_position_id`: referencia real del broker
- `strategy_key`: trazabilidad humana
- `instance_id`: propietario logico real
- `entry_group_id`: agrupar entradas relacionadas si hace falta
- `leg_id`: identificar entradas independientes
- `opened_by_plan_id` y `opened_by_action_id`: auditoria e idempotencia

## Regla de ownership

El ownership operativo debe resolverse por `instance_id`.

No por:
- nombre visible en GUI
- comentario textual
- heuristicas fragiles

El comentario del broker puede ayudar, pero no debe ser la fuente canonica de
ownership.

## Compartir simbolo

### Decision v1

Si, varias estrategias pueden compartir simbolo.

Pero hay dos casos distintos.

## Caso A. Cuenta `hedging`

Si `account.position_mode == "hedging"`:
- varias instancias pueden tener posiciones independientes sobre el mismo simbolo
- incluso pueden tener sentidos opuestos
- el broker permite varias posiciones separadas

Este es el escenario ideal para el supersistema.

Ejemplos validos:
- estrategia A long `DE40`
- estrategia B long `DE40`
- estrategia A long `DE40` y estrategia B short `DE40`

Siempre que cada una opere solo sobre sus propios recursos.

## Caso B. Cuenta `netting`

Si `account.position_mode == "netting"`:
- el broker mantiene una unica posicion neta por simbolo
- por tanto la independencia fuerte entre estrategias sobre el mismo simbolo no
  existe de forma natural a nivel broker

Esto cambia completamente la convivencia.

### Decision v1 para `netting`

En v1, la politica por defecto debe ser:
- `single_owner_per_symbol`

Eso significa:
- un simbolo ejecutable tiene un unico propietario activo
- otras estrategias pueden observarlo
- pero no deben emitir actions operativas sobre ese mismo simbolo

Motivo:
- evita ambiguedades imposibles de auditar
- evita que una estrategia netee o deshaga accidentalmente la posicion de otra
- evita necesitar un libro sintetico complejo en la v1

### Decision de alcance actual

Aunque la politica conservadora de `netting` queda fijada, el diseno detallado
de un libro sintetico compartido para cuentas `netting` queda fuera del alcance
actual del debate.

Por ahora la propuesta activa es:
- `hedging-first`
- `netting` soportado solo en modo conservador `single_owner_per_symbol`
- sin abrir aun la rama de diseno avanzada de libro sintetico compartido

## Competencia por exposicion

Todas las estrategias compiten por recursos reales de cuenta:
- equity
- margen
- exposicion total
- capacidad operativa del broker

### Decision filosofica

El motor no imponera limites financieros duros hardcodeados.

Por tanto:
- no vetara una estrategia por "riesgo excesivo" segun una regla fija del core
- si una estrategia quiere autocontrolarse, debe usar `context.portfolio` y
  decidirlo ella misma

### Que si puede pasar

Aunque no haya veto financiero hardcodeado, si puede haber resultado tecnico:
- margen insuficiente
- volumen minimo o maximo no valido
- modo de cuenta incompatible
- simbolo reservado por otra instancia en `netting`

Eso si es responsabilidad del motor.

## Como evitar que se pisen

La convivencia sana necesita varias barreras.

## 1. Ownership estricto

Por defecto, una action solo puede apuntar a:
- posiciones de su `instance_id`
- ordenes de su `instance_id`

## 2. Locks de ejecucion

La evaluacion puede ser paralela.
La mutacion operativa no.

Regla v1:
- ejecucion serializada por `symbol`

Eso permite:
- paralelismo entre simbolos distintos
- coherencia al operar sobre el mismo simbolo

Motivo:
- dos estrategias sobre `DE40` no deben abrir o cerrar a ciegas sobre un
  snapshot obsoleto del mismo libro

## 3. Revalidacion antes de ejecutar

Antes de mandar la orden real, el motor debe revalidar:
- ownership del objetivo
- existencia actual del recurso
- revision del symbol book
- compatibilidad con el `position_mode`

Si algo cambio, la action puede:
- fallar tecnicamente
- o reintentarse con snapshot nuevo

## 4. Idempotencia

El motor debe detectar duplicados por:
- `plan_id`
- `action_id`
- `instance_id`

Esto evita dobles ejecuciones accidentales.

## 5. Action targeting explicito

Acciones sensibles como:
- `close_position`
- `reduce_position`
- `move_stop_loss`

no deberian apuntar a "lo que pille".

Deben apuntar a objetivos claros, por ejemplo:
- `leg_id`
- `entry_group_id`
- o selector bien definido como `latest_owned_long_leg`

## Modelo de convivencia por defecto

### Modo base v1

Modo recomendado por defecto:
- visibilidad global
- mutacion local
- simbolo compartible
- ownership por `instance_id`

Interpretacion:
- todas ven el tablero
- cada una mueve solo sus piezas

## Modos futuros opcionales

No forman parte del contrato base v1, pero pueden existir despues:

### 1. `shared_symbol_book`

Varias estrategias cooperan deliberadamente sobre el mismo libro neto del
simbolo.

Requiere:
- semantica mucho mas compleja
- reglas de prioridad
- reconciliacion avanzada

### 2. `portfolio_supervisor`

Una estrategia superior puede vetar o modular otras estrategias.

No es el modelo base acordado.

## Ejemplo 1. Dos estrategias sobre el mismo simbolo en `hedging`

Instancias:
- `trend_follow::DE40`
- `mean_revert::DE40`

Escenario:
- la primera abre una long
- la segunda abre una short

Resultado v1:
- ambas pueden coexistir
- cada una mantiene sus propias legs
- cada una solo modifica sus propios recursos

## Ejemplo 2. Dos estrategias sobre el mismo simbolo en `netting`

Instancias:
- `trend_follow::DE40`
- `mean_revert::DE40`

Escenario:
- la primera ya es propietaria activa del symbol book `DE40`
- la segunda intenta abrir accion operativa sobre `DE40`

Resultado v1:
- la segunda no puede ejecutar esa action
- el motor devuelve rechazo tecnico por politica `single_owner_per_symbol`

## Decision actual

La propuesta formal v1 es:
- la unidad de propiedad es `strategy_instance`
- varias estrategias pueden compartir cuenta
- varias estrategias pueden compartir simbolo
- en `hedging`, la convivencia completa es posible
- en `netting`, por defecto rige `single_owner_per_symbol`
- el motor evita interferencias con ownership, locks por simbolo,
  revalidacion e idempotencia
