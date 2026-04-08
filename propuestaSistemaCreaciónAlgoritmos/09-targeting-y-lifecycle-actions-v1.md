# Targeting y Lifecycle Actions V1

## Objetivo

Definir:
- como una `action` apunta a un recurso concreto
- como resuelve el motor ese objetivo
- que transiciones de estado son validas para cada recurso operativo

Sin esto, acciones como:
- `close_position`
- `reduce_position`
- `move_stop_loss`
- `replace_pending_order`

quedan demasiado ambiguas.

## Principio rector

Una `action` nunca debe operar sobre "lo primero que encuentre".

Debe apuntar a:
- un recurso explicito
- o un selector declarativo bien definido

## Dos modos de targeting

Las `actions` v1 deben soportar dos familias de targeting:

### 1. Targeting explicito

La estrategia conoce exactamente el recurso.

Ejemplos:
- `leg_id = leg_003`
- `entry_group_id = grp_001`
- `order_id = ord_005`

### 2. Targeting por selector

La estrategia no conoce el id exacto, pero usa un selector declarativo.

Ejemplos:
- `latest_owned_long_leg`
- `oldest_open_leg_in_group`
- `all_open_legs_in_group`

## Regla de preferencia

Regla v1:
- preferir ids explicitos cuando la estrategia ya conoce el recurso
- usar selectores solo cuando aporten comodidad real

Motivo:
- mas estabilidad
- menos ambiguedad
- mas trazabilidad

## Estructura comun de target

Formato orientativo:

```python
target = {
    "resource_type": "leg",     # leg | entry_group | pending_order | position_view
    "mode": "by_id",            # by_id | by_selector
    "value": "leg_003",
    "selector_args": {...},
}
```

## Resource types permitidos v1

Tipos base:
- `leg`
- `entry_group`
- `pending_order`
- `position_view`

Regla:
- `broker_position` no deberia ser target directo de estrategia por defecto

Motivo:
- el ownership y la semantica principal viven en recursos logicos del motor

## Targeting por recurso

## 1. Targeting de `leg`

Uso recomendado para:
- cerrar una entrada concreta
- reducir una entrada concreta
- mover SL o TP de una entrada concreta

### Formas validas

Por id:

```python
{
    "resource_type": "leg",
    "mode": "by_id",
    "value": "leg_003",
}
```

Por selector:

```python
{
    "resource_type": "leg",
    "mode": "by_selector",
    "value": "latest_owned_long_leg",
}
```

### Selectores v1 recomendados para `leg`

- `latest_owned_leg`
- `latest_owned_long_leg`
- `latest_owned_short_leg`
- `oldest_owned_leg`
- `oldest_open_leg_in_group`
- `latest_open_leg_in_group`
- `all_open_legs_in_group`

Si el selector necesita contexto extra:

```python
{
    "resource_type": "leg",
    "mode": "by_selector",
    "value": "all_open_legs_in_group",
    "selector_args": {
        "entry_group_id": "grp_001",
    },
}
```

## 2. Targeting de `entry_group`

Uso recomendado para:
- cerrar una campana completa
- aplicar una politica comun de SL
- operar sobre un setup compuesto

### Formas validas

Por id:

```python
{
    "resource_type": "entry_group",
    "mode": "by_id",
    "value": "grp_001",
}
```

Por selector:

```python
{
    "resource_type": "entry_group",
    "mode": "by_selector",
    "value": "latest_open_group",
}
```

### Selectores v1 recomendados para `entry_group`

- `latest_open_group`
- `oldest_open_group`
- `latest_open_group_by_tag`

## 3. Targeting de `pending_order`

Uso recomendado para:
- cancelar una orden concreta
- reemplazar una orden concreta
- modificar una limit o stop concreta

### Formas validas

Por id:

```python
{
    "resource_type": "pending_order",
    "mode": "by_id",
    "value": "ord_005",
}
```

Por selector:

```python
{
    "resource_type": "pending_order",
    "mode": "by_selector",
    "value": "latest_working_order",
}
```

### Selectores v1 recomendados para `pending_order`

- `latest_working_order`
- `oldest_working_order`
- `all_working_orders`

## 4. Targeting de `position_view`

Debe usarse con cautela.

Uso recomendado:
- acciones de conveniencia
- consultas
- operaciones de grupo bien definidas

No uso recomendado:
- ownership primario
- acciones sensibles si la vista agrega recursos heterogeneos

## Reglas de resolucion

## 1. Ownership obligatorio

Antes de resolver un target, el motor debe comprobar:
- que el recurso pertenece al `instance_id` de la estrategia

Si no pertenece:
- rechazo tecnico

## 2. Estado compatible

Antes de ejecutar una action, el target debe estar en estado compatible.

Ejemplos:
- no mover SL de una `leg` cerrada
- no cancelar una `pending_order` ya cancelada
- no reducir una `leg` con `remaining_volume = 0`

## 3. Selector determinista o explicito

Si un selector puede devolver varios recursos, eso debe estar previsto.

Dos casos:

### Caso A. La action espera uno solo

Entonces el selector debe ser determinista y devolver exactamente uno.

Si devuelve:
- cero -> error de resolucion
- mas de uno -> error de ambiguedad

### Caso B. La action espera varios

Entonces el contrato debe decirlo explicitamente.

Ejemplo:
- `all_open_legs_in_group`

## 4. Nada de heuristicas ocultas

El motor no debe inventarse reglas silenciosas como:
- "cierro la mas nueva porque si"
- "muevo el stop de la mayor posicion"

Si existe una politica:
- debe estar declarada en la action
- o ser parte del selector

## Estructura orientativa de acciones sensibles

### `close_position`

```python
{
    "type": "close_position",
    "target": {
        "resource_type": "leg",
        "mode": "by_id",
        "value": "leg_003",
    },
    "reason": "...",
}
```

### `reduce_position`

```python
{
    "type": "reduce_position",
    "target": {
        "resource_type": "entry_group",
        "mode": "by_id",
        "value": "grp_001",
    },
    "reduction_spec": {
        "mode": "pct",
        "value": 25,
        "allocation_policy": "proportional",
    },
    "reason": "...",
}
```

### `move_stop_loss`

```python
{
    "type": "move_stop_loss",
    "target": {
        "resource_type": "leg",
        "mode": "by_selector",
        "value": "latest_open_leg_in_group",
        "selector_args": {
            "entry_group_id": "grp_001",
        },
    },
    "stop_spec": {
        "mode": "break_even_plus",
        "offset_points": 10,
    },
    "reason": "...",
}
```

## Lifecycle por recurso

## 1. Lifecycle de `pending_order`

Estados v1:
- `working`
- `partially_filled`
- `filled`
- `cancelled`
- `rejected`
- `expired`

### Transiciones validas

- `working -> partially_filled`
- `working -> filled`
- `working -> cancelled`
- `working -> rejected`
- `working -> expired`
- `partially_filled -> filled`
- `partially_filled -> cancelled`

### Transiciones invalidas

- `filled -> working`
- `cancelled -> working`
- `rejected -> working`

## 2. Lifecycle de `leg`

Estados v1:
- `pending_open`
- `open`
- `reducing`
- `closed`
- `cancelled`

### Semantica

- `pending_open`: la decision existe, pero aun no hay exposicion abierta estable
- `open`: la leg esta viva y puede mutarse
- `reducing`: la leg esta siendo cerrada parcialmente
- `closed`: ya no tiene volumen restante
- `cancelled`: la apertura prevista no llego a materializarse

### Transiciones validas

- `pending_open -> open`
- `pending_open -> cancelled`
- `open -> reducing`
- `open -> closed`
- `reducing -> open`
- `reducing -> closed`

### Transiciones invalidas

- `closed -> open`
- `cancelled -> open`

## 3. Lifecycle de `entry_group`

Estados v1:
- `open`
- `partially_closed`
- `closed`
- `cancelled`

### Semantica

- `open`: tiene al menos una leg viva
- `partially_closed`: algunas legs o volumenes ya se cerraron, pero sigue vivo
- `closed`: ya no tiene exposicion viva
- `cancelled`: la campana prevista no llego a abrirse realmente

### Transiciones validas

- `open -> partially_closed`
- `open -> closed`
- `open -> cancelled`
- `partially_closed -> closed`

### Transiciones invalidas

- `closed -> open`
- `cancelled -> open`

## Eventos que disparan transiciones

### `pending_order`

Eventos:
- fill parcial
- fill completo
- cancelacion
- rechazo broker
- expiracion

### `leg`

Eventos:
- primer fill de apertura
- parcial de cierre
- cierre completo
- cancelacion de apertura

### `entry_group`

Eventos:
- apertura de primera leg
- cierre parcial del conjunto
- cierre completo de todas las legs
- cancelacion total sin fills

## Regla de agregacion

`entry_group` y `position_view` se recalculan a partir de eventos y estados de
`legs`.

Consecuencia:
- no deben actualizarse con logica paralela y arbitraria
- deben derivarse de reglas consistentes del motor

## Reglas especiales para acciones multi-target

Si una action apunta a varios recursos:
- el `action_report` debe listar cada target resuelto
- el motor debe dejar claro cuales tuvieron exito y cuales no

Ejemplo:
- `close_position` sobre `all_open_legs_in_group`

No debe quedar como:
- "algo se cerro"

Debe quedar como:
- `leg_001` cerrada
- `leg_002` rechazada
- `leg_003` ya estaba cerrada

## Politica de errores de resolucion

Errores v1 recomendados:
- `target_not_found`
- `target_not_owned`
- `target_ambiguous`
- `target_incompatible_state`
- `selector_requires_args`
- `selector_returned_multiple`
- `selector_returned_none`

## Ejemplo aplicado a `primeraEstrategia.md`

Escenario:
- `grp_001` contiene `leg_001`, `leg_002`, `leg_003`

Casos:

1. Mover SL solo de la ultima piramide:
   - target `leg_003`

2. Cerrar toda la campana:
   - target `entry_group_id = grp_001`

3. Reducir 50 por ciento del grupo proporcionalmente:
   - target `grp_001`
   - `allocation_policy = proportional`

4. Cerrar solo la ultima leg abierta:
   - selector `latest_open_leg_in_group`

## Decision actual

La propuesta v1 es:
- targeting explicito o por selector declarativo
- ownership obligatorio por `instance_id`
- sin heuristicas ocultas
- lifecycle explicito para `pending_order`, `leg` y `entry_group`
- transiciones y errores de resolucion visibles en el `action_report`

