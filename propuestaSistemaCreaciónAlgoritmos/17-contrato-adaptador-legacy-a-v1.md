# Contrato Del Adaptador Legacy A v1

## Objetivo

Definir con precision como una estrategia legacy del repo actual se comporta
dentro del runtime nuevo sin obligarla a reescribirse.

El adaptador existe para una sola cosa:
- preservar comportamiento legacy
- mientras el motor ya opera con `context + state -> plan + next_state`

No existe para inventar capacidades nuevas a una estrategia vieja.

## Estrategias cubiertas por este adaptador

Una estrategia entra por el adaptador si expone el contrato actual:
- `prepare_dataframe(df)` opcional
- `compute_signals(df)` o equivalente opcional
- `get_last_signal(df)` o
- `get_last_signal_payload(df)`

Y NO expone:
- `decide(context, state)`

Si expone `decide(context, state)`, el adaptador no debe intervenir.

## Responsabilidades del adaptador

El adaptador debe:
- ejecutar el pipeline legacy de calculo
- normalizar la salida a un `signal_payload`
- leer el contexto de ejecucion actual de la instancia
- convertir esa salida a un `plan` v1 compatible
- devolver `next_state` estable y serializable
- etiquetar claramente que la decision vino del modo legacy

El adaptador NO debe:
- deducir pyramiding
- inventar parciales
- crear `pending_orders` complejas
- introducir logica financiera no presente en la estrategia original

## Entrada minima del adaptador

El adaptador necesita:
- `instance_id`
- `strategy_key`
- `module`
- `context`
- `state`
- `market_frame` o equivalente ya preparado para la estrategia

El `context` debe contener al menos:
- `symbol`
- `clock`
- `account`
- `execution.owned_legs`
- `execution.owned_entry_groups`
- `execution.views`
- `instance.runtime.legacy_execution_defaults`

`legacy_execution_defaults` debe incluir como minimo:
- `lot`
- `sl_points`
- `tp_points`

Esos valores existen para reproducir el comportamiento actual mientras la
estrategia legacy siga dependiendo de parametros globales.

## Salida canonica del adaptador

El adaptador devuelve un `decision` v1:

- `plan`
- `next_state`

Y opcionalmente metadata de runtime:
- `adapter_mode = legacy_signal`
- `legacy_api = get_last_signal | get_last_signal_payload`

## Normalizacion de la salida legacy

La salida legacy debe pasar por las mismas reglas de normalizacion del runtime
actual:

- `buy` -> `buy`
- `sell` -> `sell`
- cualquier otra cosa -> `none`

Si la estrategia devuelve payload, se admite:
- `signal`
- `side`
- `action`
- `decision`

Y como razon textual:
- `reason`
- `motivo`
- `message`
- `detail`
- `why`

La razon debe truncarse igual que hoy si se define una politica comun de
longitud.

## Semantica de compatibilidad que hay que preservar

El adaptador debe reproducir la politica observable de `apply_signal()`:

### Caso 1: `signal = none`

Salida:
- `plan.actions = []`

Semantica:
- no abrir
- no cerrar
- no modificar

### Caso 2: `signal = buy`

Si la instancia no tiene exposicion propia en el simbolo:
- `open_position` long

Si la instancia tiene exposicion short propia:
- `close_position`
- `open_position` long

Si la instancia ya tiene exposicion long propia:
- `actions = []`

### Caso 3: `signal = sell`

Si la instancia no tiene exposicion propia en el simbolo:
- `open_position` short

Si la instancia tiene exposicion long propia:
- `close_position`
- `open_position` short

Si la instancia ya tiene exposicion short propia:
- `actions = []`

## Unidad de lectura de exposicion durante el modo legacy

El adaptador NO debe razonar en terminos de `magic_number` como contrato
principal.

Debe razonar sobre recursos canonicos del runtime, idealmente:
- `position_view` owned por la instancia

Solo durante etapas tempranas de adopcion, si aun no existen `legs` reales, se
admite una vista derivada temporal desde el estado legacy.

Regla:
- la compatibilidad se expresa en la nueva ontologia
- no al reves

## Forma del `plan` sintetico

El `plan` emitido por el adaptador debe quedar claramente marcado como legado.

Campos recomendados:
- `schema_version`
- `plan_id`
- `instance_id`
- `symbol`
- `reason`
- `actions`
- `meta.origin = legacy_adapter`
- `meta.legacy_signal`
- `meta.legacy_reason`
- `meta.compat_mode = signal_translation`

## Forma de las `actions` sinteticas

### `open_position`

Debe usar:
- `symbol`
- `side`
- `size_spec`
- `stop_spec`
- `take_profit_spec`
- `reason`

En modo legacy:
- `size_spec` sale de `legacy_execution_defaults.lot`
- `stop_spec` sale de `legacy_execution_defaults.sl_points`
- `take_profit_spec` sale de `legacy_execution_defaults.tp_points`

### `close_position`

Debe apuntar al recurso owned de la instancia.

Target recomendado:
- `position_view` owned de la instancia en ese simbolo y sentido opuesto

Si en fases posteriores ya existe granularidad suficiente, puede resolver a:
- `entry_group` completo, o
- conjunto de `legs` owned

Pero el efecto observable debe seguir siendo:
- cerrar toda la exposicion opuesta propia de esa instancia

## `next_state` en modo legacy

Por defecto, una estrategia legacy no necesita memoria propia rica.

Por eso, el `next_state` del adaptador debe ser conservador:
- preservar envelope comun
- no inventar memoria de negocio

Se admite guardar metadata tecnica minima como:
- `last_signal`
- `last_reason`
- `last_decision_at`
- `adapter_revision`

Pero solo para trazabilidad, no para alterar la logica de la estrategia.

## Invariantes del adaptador

1. No puede crear mas expresividad de la que tenia la estrategia original.
2. No puede convertir una estrategia legacy en multi-leg avanzada por arte de magia.
3. Repetir la misma senal en la misma direccion con exposicion ya abierta debe
   seguir produciendo "no-op".
4. Una inversion de direccion debe seguir siendo "cerrar y abrir" y no otra
   heuristica.
5. El usuario debe poder distinguir en logs y reportes que la decision vino del
   adaptador legacy.

## Interaccion con el interprete nuevo

El adaptador no ejecuta nada.

Su responsabilidad termina en:
- devolver `plan`
- devolver `next_state`

Luego:
- el interprete resuelve targets
- normaliza tecnicamente
- ejecuta
- persiste `execution_report` y eventos

Eso evita que el adaptador se convierta en un mini `trading.py`.

## Politica de errores

Si la estrategia legacy lanza excepcion:
- no debe emitirse una accion parcial
- se registra error de decision
- `plan` puede omitirse o emitirse como rechazado sin acciones, segun la
  politica de runtime elegida

Si la estrategia devuelve una salida invalida:
- se normaliza a `none`
- se registra evento de normalizacion

Si faltan `legacy_execution_defaults`:
- eso es error de configuracion del runtime, no de la estrategia

## Politica de idempotencia

Aunque el origen sea legacy, el `plan` sintetico debe cumplir las mismas reglas
de idempotencia:
- `plan_id` unico por ciclo de decision
- `action_id` unico por accion sintetica

No se deben generar ids ambiguos por usar solo:
- `symbol`
- `signal`
- timestamp sin contexto

## Ejemplo de traduccion

Entrada legacy:

```python
signal_payload = {
    "signal": "buy",
    "reason": "Cruce EMA con RSI saliendo de sobreventa"
}
```

Contexto owned:
- no hay exposicion propia abierta

Salida v1 sintetica:

```python
decision = {
    "plan": {
        "schema_version": 1,
        "symbol": "EURUSD",
        "reason": "Cruce EMA con RSI saliendo de sobreventa",
        "meta": {
            "origin": "legacy_adapter",
            "legacy_signal": "buy",
            "compat_mode": "signal_translation",
        },
        "actions": [
            {
                "type": "open_position",
                "symbol": "EURUSD",
                "side": "long",
                "size_spec": {"mode": "fixed_lot", "value": 0.1},
                "stop_spec": {"mode": "points_from_entry", "value": 300},
                "take_profit_spec": {"mode": "points_from_entry", "value": 600},
                "reason": "Cruce EMA con RSI saliendo de sobreventa",
            }
        ],
    },
    "next_state": {...},
}
```

## Condicion de retirada del adaptador

El adaptador puede retirarse solo cuando se cumplan las dos cosas:

1. El runtime nuevo ya es la ruta estable de decision y ejecucion.
2. Las estrategias que siguen activas ya implementan contrato v1 o aceptan
   quedarse en una capa legacy aislada y claramente deprecada.

## Decision final

El adaptador legacy -> v1 es una capa de compatibilidad estricta.

No es:
- un traductor inteligente
- un motor de estrategia
- un atajo para evitar definir bien el contrato v1

Su trabajo correcto es mucho mas humilde:
- envolver
- marcar
- traducir
- y apartarse
