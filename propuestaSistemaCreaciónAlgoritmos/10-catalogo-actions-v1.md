# Catalogo Actions V1

## Objetivo

Cerrar el lenguaje operativo minimo de la v1:
- que `actions` existen
- que campos comparten
- que campos especificos exige cada una
- que acciones quedan fuera de la v1

## Principio de diseno

La v1 debe tener pocas `actions`, pero suficientemente expresivas.

Regla:
- evitar acciones redundantes
- evitar acciones demasiado magicas
- preferir composicion antes que explosión de verbos

## Nivel de versionado

Decision v1:
- el versionado principal vive en el `plan`
- las `actions` heredan esa version

Formato orientativo:

```python
plan = {
    "schema_version": 1,
    "plan_id": "plan_000124",
    "actions": [...],
    "next_state": {...},
    "reason": "...",
}
```

Consecuencia:
- no hace falta versionar cada action por separado en v1
- si el significado del catalogo cambia de forma incompatible, se incrementa
  `plan.schema_version`

## Estructura comun de una action

Todas las `actions` v1 deben compartir este sobre minimo:

```python
action = {
    "action_id": "act_0001",
    "type": "open_position",
    "symbol": "DE40",
    "reason": "...",
    "tags": {...},
}
```

Campos comunes:
- `action_id`: obligatorio, unico dentro del plan
- `type`: obligatorio
- `symbol`: obligatorio
- `reason`: obligatorio y legible para humanos
- `tags`: opcional

## Reglas comunes obligatorias

### 1. `action_id`

Debe ser:
- estable dentro del plan
- unico dentro del plan
- util para idempotencia y auditoria

### 2. `symbol`

Debe ser explicito incluso si el contexto ya trae un simbolo principal.

Motivo:
- evita ambiguedad
- prepara el sistema para estrategias multi-simbolo

### 3. `reason`

No es decorativo.
Debe explicar por que la estrategia quiso emitir esa action.

### 4. `tags`

Es metadata opcional.

Ejemplos:
- `entry_kind = initial`
- `setup = adx_di_long`
- `risk_bucket = aggressive`

## Catalogo oficial v1

`actions` incluidas en la v1:

- `open_position`
- `add_to_position`
- `close_position`
- `reduce_position`
- `move_stop_loss`
- `move_take_profit`
- `place_pending_order`
- `cancel_pending_order`
- `replace_pending_order`

## Action 1. `open_position`

Uso:
- abrir una nueva exposicion independiente

Schema orientativo:

```python
{
    "action_id": "act_0001",
    "type": "open_position",
    "symbol": "DE40",
    "side": "long",
    "size_spec": {...},
    "entry_spec": {...},
    "stop_spec": {...},
    "take_profit_spec": {...},
    "group_spec": {...},
    "reason": "...",
    "tags": {...},
}
```

Campos obligatorios:
- `side`
- `size_spec`
- `entry_spec`

Campos opcionales:
- `stop_spec`
- `take_profit_spec`
- `group_spec`
- `tags`

### Semantica

Por defecto crea:
- una nueva `leg`
- y, si aplica, un nuevo `entry_group`

Si `group_spec` indica reutilizacion de grupo, el motor puede asociar la nueva
leg a un grupo existente.

## Action 2. `add_to_position`

Uso:
- anadir una nueva `leg` a una exposicion ya existente

Schema orientativo:

```python
{
    "action_id": "act_0002",
    "type": "add_to_position",
    "symbol": "DE40",
    "target": {
        "resource_type": "entry_group",
        "mode": "by_id",
        "value": "grp_001",
    },
    "side": "long",
    "size_spec": {...},
    "entry_spec": {...},
    "stop_spec": {...},
    "take_profit_spec": {...},
    "reason": "...",
    "tags": {...},
}
```

Campos obligatorios:
- `target`
- `side`
- `size_spec`
- `entry_spec`

### Semantica

`add_to_position` no modifica una leg existente.
Crea una nueva `leg` dentro de un `entry_group` ya existente.

## Action 3. `close_position`

Uso:
- cerrar completamente un target

Schema orientativo:

```python
{
    "action_id": "act_0003",
    "type": "close_position",
    "symbol": "DE40",
    "target": {...},
    "close_spec": {
        "mode": "full",
    },
    "reason": "...",
    "tags": {...},
}
```

Campos obligatorios:
- `target`

### Targets validos

V1:
- `leg`
- `entry_group`
- `position_view` con cautela

### Semantica

Si el target es:
- `leg`: cierra esa leg
- `entry_group`: cierra todas las legs del grupo segun las reglas del grupo

## Action 4. `reduce_position`

Uso:
- cerrar parcialmente un target

Schema orientativo:

```python
{
    "action_id": "act_0004",
    "type": "reduce_position",
    "symbol": "DE40",
    "target": {...},
    "reduction_spec": {
        "mode": "pct",                 # pct | volume
        "value": 25,
        "allocation_policy": "proportional",
    },
    "reason": "...",
    "tags": {...},
}
```

Campos obligatorios:
- `target`
- `reduction_spec`

### Semantica

Si el target es:
- `leg`: reduce solo esa leg
- `entry_group`: reparte la reduccion segun `allocation_policy`

### `allocation_policy`

Obligatoria cuando el target pueda resolver a varias legs.

Valores recomendados v1:
- `proportional`
- `fifo`
- `lifo`
- `explicit_leg_targets`

## Action 5. `move_stop_loss`

Uso:
- mover el SL de una o varias legs

Schema orientativo:

```python
{
    "action_id": "act_0005",
    "type": "move_stop_loss",
    "symbol": "DE40",
    "target": {...},
    "stop_spec": {...},
    "reason": "...",
    "tags": {...},
}
```

Campos obligatorios:
- `target`
- `stop_spec`

### Semantica

No cambia ownership ni volumen.
Solo modifica la proteccion de salida del target compatible.

## Action 6. `move_take_profit`

Uso:
- mover el TP de una o varias legs

Schema orientativo:

```python
{
    "action_id": "act_0006",
    "type": "move_take_profit",
    "symbol": "DE40",
    "target": {...},
    "take_profit_spec": {...},
    "reason": "...",
    "tags": {...},
}
```

Campos obligatorios:
- `target`
- `take_profit_spec`

## Action 7. `place_pending_order`

Uso:
- crear una orden pendiente

Schema orientativo:

```python
{
    "action_id": "act_0007",
    "type": "place_pending_order",
    "symbol": "DE40",
    "side": "long",
    "size_spec": {...},
    "entry_spec": {
        "mode": "limit",
        "price": 18405.0,
    },
    "stop_spec": {...},
    "take_profit_spec": {...},
    "group_spec": {...},
    "reason": "...",
    "tags": {...},
}
```

Campos obligatorios:
- `side`
- `size_spec`
- `entry_spec`

### Regla

En v1, `entry_spec.mode` debe ser compatible con orden pendiente.

Valores esperados:
- `limit`
- `stop`

## Action 8. `cancel_pending_order`

Uso:
- cancelar una orden pendiente concreta o resuelta por selector

Schema orientativo:

```python
{
    "action_id": "act_0008",
    "type": "cancel_pending_order",
    "symbol": "DE40",
    "target": {
        "resource_type": "pending_order",
        "mode": "by_id",
        "value": "ord_005",
    },
    "reason": "...",
    "tags": {...},
}
```

Campos obligatorios:
- `target`

## Action 9. `replace_pending_order`

Uso:
- reemplazar una pending existente por una nueva definicion

Schema orientativo:

```python
{
    "action_id": "act_0009",
    "type": "replace_pending_order",
    "symbol": "DE40",
    "target": {
        "resource_type": "pending_order",
        "mode": "by_id",
        "value": "ord_005",
    },
    "new_order_spec": {
        "side": "long",
        "size_spec": {...},
        "entry_spec": {...},
        "stop_spec": {...},
        "take_profit_spec": {...},
    },
    "reason": "...",
    "tags": {...},
}
```

Campos obligatorios:
- `target`
- `new_order_spec`

### Semantica

El motor puede implementarla como:
- cancelacion de la orden antigua
- creacion de una nueva orden

Eso debe quedar visible en el `execution_report`.

## Specs auxiliares v1

## `size_spec`

Modos recomendados:
- `fixed_lots`
- `risk_pct_of_equity`
- `volume`
- `formula`

Ejemplos:

```python
{"mode": "fixed_lots", "value": 0.10}
```

```python
{"mode": "risk_pct_of_equity", "value": 0.5}
```

## `entry_spec`

Modos recomendados:
- `market`
- `limit`
- `stop`

Ejemplos:

```python
{"mode": "market"}
```

```python
{"mode": "limit", "price": 18405.0}
```

## `stop_spec`

Modos recomendados:
- `price`
- `price_offset`
- `atr_multiple`
- `break_even`
- `break_even_plus`

## `take_profit_spec`

Modos recomendados:
- `price`
- `rr_multiple`
- `price_offset`
- `multi_target`

## `group_spec`

Uso:
- indicar si se crea grupo nuevo
- o se reutiliza uno existente

Ejemplos:

```python
{"mode": "new_group"}
```

```python
{
    "mode": "existing_group",
    "target": {
        "resource_type": "entry_group",
        "mode": "by_id",
        "value": "grp_001",
    },
}
```

## Actions excluidas de la v1

Quedan explicitamente fuera de la v1:
- `do_nothing`
- `close_all_for_strategy`
- `move_to_break_even_all`
- `reverse_position`
- `hedge_position`
- `rebalance_portfolio`
- `pause_strategy`

Motivo:
- algunas son redundantes
- otras mezclan varias intenciones a la vez
- otras pertenecen a capas superiores del sistema

## Reglas de minimalismo

### 1. `do_nothing`

No hace falta.

Si no hay acciones:
- `actions = []`

### 2. `close_all_for_strategy`

Es demasiado amplia para v1.
Se puede construir con:
- selector de grupos o legs
- varias `close_position`

### 3. `reverse_position`

Mejor modelarla como composicion explicita:
1. cerrar
2. abrir en sentido contrario

Eso da mas trazabilidad.

## Ejemplo aplicado a `primeraEstrategia.md`

Catalogo realmente necesario para esa estrategia:
- `open_position`
- `add_to_position`
- `close_position`
- `reduce_position` si un dia quieres parciales
- `move_stop_loss` si anades trailing o break even

Con eso ya cubres:
- entrada inicial
- pyramiding
- cierre por leg
- cierre por grupo
- evolucion de stops

## Decision actual

El catalogo oficial v1 queda en:
- `open_position`
- `add_to_position`
- `close_position`
- `reduce_position`
- `move_stop_loss`
- `move_take_profit`
- `place_pending_order`
- `cancel_pending_order`
- `replace_pending_order`

Reglas clave:
- versionado en `plan.schema_version`
- `action_id` obligatorio
- `symbol` obligatorio
- `reason` obligatorio
- sin acciones redundantes o demasiado magicas en v1

