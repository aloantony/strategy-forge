# Contrato Interprete Actions

## Objetivo

El interprete de `actions` es la pieza que toma el `plan` declarativo de una
estrategia y lo convierte en ejecucion real.

Su funcion no es redisenar la logica de trading.
Su funcion es:
- interpretar
- validar tecnicamente
- normalizar
- ejecutar
- dejar trazabilidad

## Principio rector

La estrategia decide la intencion.
El interprete decide la traduccion tecnica.

Eso significa:
- la estrategia dice que quiere hacer
- el interprete convierte eso en operaciones ejecutables
- el interprete no debe imponer limites financieros hardcodeados
- el interprete si debe impedir operaciones tecnicamente invalidas

## Frontera de responsabilidad

### La estrategia es responsable de

- logica de entrada
- logica de salida
- sizing deseado
- stop y take profit deseados
- pyramiding
- parciales
- reglas internas de riesgo
- contenido de `strategy_state`

### El interprete es responsable de

- validar el formato de cada action
- resolver referencias tecnicas
- convertir `size_spec` a volumen ejecutable
- convertir `entry_spec`, `stop_spec` y `take_profit_spec` a precios reales
- redondear volumen y precios
- respetar restricciones tecnicas del broker
- evitar duplicados accidentales
- producir reportes de ejecucion

## Flujo general

Pipeline propuesto:

1. El motor construye `context`.
2. El motor carga `state`.
3. La estrategia devuelve `plan`.
4. El interprete valida el plan.
5. El interprete normaliza cada `action`.
6. El interprete compila acciones ejecutables.
7. El ejecutor habla con el broker.
8. El motor registra `execution_report`.
9. El motor persiste `next_state`.

## Entrada formal del interprete

El interprete deberia recibir algo conceptualmente parecido a esto:

```python
input_payload = {
    "context": {...},
    "state": {...},
    "plan": {
        "actions": [...],
        "next_state": {...},
        "reason": "...",
    },
}
```

## Salida formal del interprete

La salida no deberia ser solo `ok/fail`.
Debe ser un `execution_report`.

Formato orientativo:

```python
execution_report = {
    "plan_id": "plan_000124",
    "strategy_key": "adx_di_pyramid",
    "symbol": "DE40",
    "status": "executed",
    "summary": "...",
    "action_reports": [...],
}
```

## Diferencia entre plan y execution report

`plan`:
- lo que la estrategia queria hacer

`execution_report`:
- lo que el sistema pudo hacer realmente

Esa separacion es obligatoria.

Si no existe, luego es imposible responder con rigor preguntas como:
- la estrategia quiso abrir o no quiso abrir
- el motor lo interpreto mal
- el broker rechazo la orden
- hubo redondeo de volumen

## Fases internas del interprete

## 1. Validacion estructural

Comprueba:
- que `actions` exista y sea lista
- que cada action tenga `type`
- que el schema basico sea correcto
- que `next_state` sea serializable

Aqui se rechaza:
- formato roto
- campos obligatorios ausentes
- tipos imposibles

## 2. Validacion de capacidad

Comprueba si el motor soporta ese tipo de action.

Ejemplos:
- `reduce_position` no soportado
- `place_pending_order` no soportado
- `move_take_profit` soportado

La referencia de soporte deberia venir de `context.engine`.

## 3. Resolucion de referencias

El interprete debe traducir referencias abstractas a entidades concretas.

Ejemplos:
- `target_position = latest_long_leg`
- `target_position = position_id`
- `target_symbol = DE40`

Esto es importante para acciones como:
- `add_to_position`
- `close_position`
- `reduce_position`
- `move_stop_loss`

## 4. Resolucion de especificaciones

El interprete debe convertir especificaciones abstractas a valores concretos.

### Size resolution

Ejemplos:
- `risk_pct_of_equity`
- `fixed_lots`
- formula personalizada

Resultado:
- volumen concreto candidato

### Price resolution

Ejemplos:
- entrada a mercado
- entrada limit
- SL por multiple ATR
- TP por multiple R

Resultado:
- precio de entrada
- `stop_loss`
- `take_profit`

## 5. Normalizacion tecnica

Una vez resueltos los valores, el interprete debe normalizar:
- lotes a `volume_step`
- precios a `tick_size`
- stops a distancia minima permitida
- simbolos y precision

Importante:
- esto es normalizacion tecnica
- no es reinterpretacion financiera de la estrategia

Ejemplo correcto:
- la estrategia pide riesgo 0.53 por ciento
- el interprete traduce eso a 0.17 lotes
- el broker solo permite 0.16 o 0.18
- el interprete redondea segun politica tecnica definida

## 6. Compilacion ejecutable

El interprete genera una o varias operaciones concretas para el ejecutor.

Ejemplo:
- una `open_position` puede compilarse a una orden market con SL y TP
- una `reduce_position` puede compilarse a una orden parcial de cierre
- una `replace_pending_order` puede compilarse a cancelar + crear nueva

## 7. Ejecucion

La capa ejecutora habla con el broker.

Aqui ya pueden pasar cosas como:
- orden aceptada
- orden rechazada
- fill parcial
- slippage
- timeout

## 8. Reporte

Cada action debe generar un `action_report`.

Formato orientativo:

```python
action_report = {
    "action_id": "act_0001",
    "type": "open_position",
    "status": "executed",
    "requested": {...},
    "resolved": {...},
    "broker_result": {...},
    "message": "...",
}
```

## Estados recomendados para `action_report`

Estados v1 recomendados:
- `validated`
- `executed`
- `partially_executed`
- `rejected_technical`
- `rejected_broker`
- `skipped_duplicate`
- `not_supported`
- `error`

## Regla sobre rechazos

El interprete puede rechazar una action por:
- invalidez estructural
- incapacidad tecnica del motor
- imposibilidad tecnica del broker

El interprete NO deberia rechazarla por:
- no gustarle la logica financiera
- considerar que el riesgo es demasiado alto segun reglas hardcodeadas del core

Salvo que el usuario haya activado explicitamente capas opcionales de proteccion.

## Idempotencia y duplicados

Este punto es critico.

Si el mismo `plan` se procesa dos veces por error, no deberia abrir dos veces
la misma operacion accidentalmente.

Por eso deberian existir:
- `plan_id`
- `action_id`
- `last_decision_id` en `state.meta`

Y el motor deberia recordar acciones ya ejecutadas recientemente.

Politica deseada:
- misma `action_id` ya ejecutada -> `skipped_duplicate`

## Orden de procesamiento

Por defecto, las `actions` deben procesarse en el orden dado por la estrategia.

Eso permite componer secuencias intencionales como:
1. cerrar parcial
2. mover stop
3. colocar nueva pending order

El motor no deberia reordenarlas libremente.

## Atomicidad logica

No todas las `actions` pueden ser atomicas a nivel broker.
Pero si debe existir atomicidad logica a nivel de reporte.

Eso significa:
- el sistema debe dejar claro que acciones del plan se ejecutaron
- cuales no
- y en que orden

Nunca debe quedar un resultado ambiguo.

## Politica de normalizacion

La normalizacion debe ser visible.

Ejemplo:
- la estrategia pidio `0.173 lots`
- el motor ejecuto `0.17 lots`

Eso debe aparecer en el `action_report`.

Regla:
- nada importante debe pasar de forma silenciosa

## Ejemplo aplicado a tu estrategia

La estrategia devuelve:

```python
{
    "actions": [
        {
            "type": "add_to_position",
            "symbol": "DE40",
            "side": "long",
            "size_spec": {
                "mode": "risk_pct_of_equity",
                "value": 0.5,
            },
            "stop_spec": {
                "mode": "atr_multiple",
                "atr_field": "atr_14",
                "multiple": 1.0,
            },
            "take_profit_spec": {
                "mode": "rr_multiple",
                "multiple": 2.0,
            },
            "reason": "Precio avanzo 0.5 ATR desde la ultima entrada",
        }
    ],
    "next_state": {...},
    "reason": "Piramidacion permitida",
}
```

El interprete:
- localiza la posicion objetivo
- calcula el volumen real
- calcula SL y TP reales
- redondea segun el instrumento
- ejecuta
- y genera reporte

Ejemplo de resultado:

```python
{
    "plan_id": "plan_000124",
    "strategy_key": "adx_di_pyramid",
    "symbol": "DE40",
    "status": "executed",
    "summary": "1/1 actions ejecutadas",
    "action_reports": [
        {
            "action_id": "act_0001",
            "type": "add_to_position",
            "status": "executed",
            "requested": {
                "size_spec": {"mode": "risk_pct_of_equity", "value": 0.5},
            },
            "resolved": {
                "volume": 0.17,
                "stop_loss": 18389.1,
                "take_profit": 18453.3,
            },
            "broker_result": {
                "ticket": 12345678,
            },
            "message": "Add long ejecutado correctamente",
        }
    ],
}
```

## Relacion con capas opcionales de seguridad

Si algun dia existen protecciones globales, no deben contaminar el contrato
base del interprete.

Deberian modelarse como capas opcionales y explicitas, por ejemplo:
- `optional_safety_policy`
- `optional_account_guardrails`

Asi se mantiene la filosofia acordada:
- libertad total por defecto
- protecciones solo si el usuario las activa

## Decision actual

El contrato propuesto del interprete es:
- recibe `context + state + plan`
- valida estructura y capacidades
- resuelve specs abstractas
- normaliza tecnicamente
- ejecuta sin redecidir la logica financiera
- produce `execution_report` detallado
- protege contra duplicados con ids y revision

