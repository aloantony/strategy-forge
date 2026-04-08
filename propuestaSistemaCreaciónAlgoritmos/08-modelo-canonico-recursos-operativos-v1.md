# Modelo Canonico Recursos Operativos V1

## Objetivo

Definir las entidades operativas del motor para soportar:
- entradas independientes
- pyramiding
- parciales
- ownership por instancia
- auditoria fuerte

## Problema de fondo

La palabra "posicion" es demasiado ambigua.

Puede significar:
- la posicion del broker
- la exposicion logica de una estrategia
- una entrada concreta
- una agregacion de varias entradas

Si no se separan esas capas, el motor se vuelve confuso y fragil.

## Decision estructural

El modelo canonico v1 distingue estas entidades:

- `pending_order`
- `fill`
- `broker_position`
- `leg`
- `entry_group`
- `position_view`

La entidad primaria para estrategias con entradas independientes es `leg`.

## Regla de oro

La verdad operativa del broker y la verdad logica de la estrategia no son lo
mismo.

Por eso:
- `broker_position` describe lo que existe en el broker
- `leg` describe la unidad de exposicion que la estrategia considera
  independiente

## 1. `pending_order`

Representa una orden viva aun no completada.

Formato orientativo:

```python
pending_order = {
    "order_id": "ord_001",
    "broker_order_id": "987654",
    "strategy_key": "adx_di_pyramid",
    "instance_id": "adx_di_pyramid::DE40",
    "symbol": "DE40",
    "side": "long",
    "order_kind": "limit",     # market | limit | stop
    "status": "working",       # working | partially_filled | cancelled | filled
    "requested_volume": 0.20,
    "remaining_volume": 0.20,
    "limit_price": 18405.0,
    "stop_loss": 18384.0,
    "take_profit": 18447.0,
    "entry_group_id": "grp_001",
    "target_leg_id": None,
    "opened_by_plan_id": "plan_000124",
    "opened_by_action_id": "act_0001",
    "created_at": "2026-04-06T13:40:00Z",
    "tags": {...},
}
```

## 2. `fill`

Representa un evento de ejecucion inmutable.

Formato orientativo:

```python
fill = {
    "fill_id": "fill_001",
    "broker_deal_id": "456789",
    "order_id": "ord_001",
    "strategy_key": "adx_di_pyramid",
    "instance_id": "adx_di_pyramid::DE40",
    "symbol": "DE40",
    "side": "long",
    "fill_kind": "open",       # open | reduce | close
    "volume": 0.20,
    "price": 18410.5,
    "commission": 0.0,
    "swap": 0.0,
    "occurred_at": "2026-04-06T13:40:01Z",
    "entry_group_id": "grp_001",
    "leg_id": "leg_001",
    "tags": {...},
}
```

Propiedades:
- no se modifica
- sirve para auditoria
- sirve para reconstruir legs y grupos

## 3. `broker_position`

Representa la realidad expuesta por el broker.

Formato orientativo:

```python
broker_position = {
    "broker_position_id": "pos_789",
    "symbol": "DE40",
    "side": "long",
    "volume": 0.20,
    "avg_entry_price": 18410.5,
    "stop_loss": 18389.1,
    "take_profit": 18453.3,
    "unrealized_pnl": 48.0,
    "opened_at": "2026-04-06T13:40:01Z",
    "position_mode": "hedging",
}
```

Importante:
- `broker_position` no debe ser la fuente canonica de ownership
- es una vista del broker, no la identidad logica del motor

## 4. `leg`

Es la unidad atomica de exposicion independiente.

Si una estrategia hace una entrada inicial y luego dos piramides:
- eso son tres `legs`

Formato orientativo:

```python
leg = {
    "leg_id": "leg_001",
    "strategy_key": "adx_di_pyramid",
    "instance_id": "adx_di_pyramid::DE40",
    "symbol": "DE40",
    "side": "long",
    "entry_group_id": "grp_001",
    "status": "open",          # pending_open | open | reducing | closed | cancelled
    "opened_by_plan_id": "plan_000124",
    "opened_by_action_id": "act_0001",
    "origin_order_id": "ord_001",
    "open_fill_ids": ["fill_001"],
    "close_fill_ids": [],
    "requested_volume": 0.20,
    "opened_volume": 0.20,
    "remaining_volume": 0.20,
    "avg_entry_price": 18410.5,
    "stop_loss": 18389.1,
    "take_profit": 18453.3,
    "linked_broker_position_ids": ["pos_789"],
    "opened_at": "2026-04-06T13:40:01Z",
    "closed_at": None,
    "tags": {
        "entry_kind": "initial",
        "pyramid_index": 0,
    },
}
```

## Por que `leg` es la unidad principal

Porque soporta de forma natural:
- entradas independientes
- pyramiding
- stops y TPs distintos por entrada
- parciales sobre una entrada concreta
- auditoria precisa

## 5. `entry_group`

Agrupa varias `legs` relacionadas dentro de una misma campana o tesis.

Ejemplos de uso:
- entrada inicial + piramides de la misma idea
- varias ordenes escalonadas que pertenecen al mismo setup

Formato orientativo:

```python
entry_group = {
    "entry_group_id": "grp_001",
    "strategy_key": "adx_di_pyramid",
    "instance_id": "adx_di_pyramid::DE40",
    "symbol": "DE40",
    "side": "long",
    "status": "open",          # open | partially_closed | closed | cancelled
    "root_leg_id": "leg_001",
    "leg_ids": ["leg_001", "leg_002", "leg_003"],
    "created_by_plan_id": "plan_000124",
    "created_at": "2026-04-06T13:40:01Z",
    "closed_at": None,
    "tags": {
        "setup": "adx_di_long",
    },
}
```

## `leg_id` vs `entry_group_id`

Diferencia esencial:

- `leg_id`:
  - una entrada concreta
  - unidad atomica de gestion independiente

- `entry_group_id`:
  - familia de entradas relacionadas
  - unidad de coordinacion superior

Ejemplo:
- `leg_001` = entrada inicial
- `leg_002` = primera piramide
- `leg_003` = segunda piramide
- todas pertenecen a `grp_001`

## 6. `position_view`

Es una vista derivada, no una entidad primaria.

Sirve para dar comodidad a la estrategia o a la GUI.

Formato orientativo:

```python
position_view = {
    "view_id": "view_001",
    "strategy_key": "adx_di_pyramid",
    "instance_id": "adx_di_pyramid::DE40",
    "symbol": "DE40",
    "side": "long",
    "leg_ids": ["leg_001", "leg_002"],
    "total_volume": 0.35,
    "avg_entry_price": 18418.2,
    "stop_loss_policy": "mixed",
    "take_profit_policy": "mixed",
    "unrealized_pnl": 61.0,
}
```

Uso:
- resumen para GUI
- resumen para contexto
- agregados convenientes para formulas

No uso:
- ownership principal
- trazabilidad primaria

## Relaciones entre entidades

Flujo tipico:

1. La estrategia emite `open_position`.
2. El interprete crea `pending_order`.
3. El broker produce uno o varios `fills`.
4. Esos fills abren un `leg`.
5. Ese `leg` queda dentro de un `entry_group`.
6. El broker expone ademas un `broker_position`.
7. El motor puede construir un `position_view`.

## Regla de creacion de legs

Regla v1 recomendada:
- una `action` de apertura crea como maximo una nueva `leg`
- aunque reciba varios fills parciales

Eso mantiene una relacion clara entre:
- decision de estrategia
- auditoria
- exposicion logica

## Regla de cierres y reducciones

### `reduce_position`

Debe apuntar preferentemente a:
- `leg_id`
- o `entry_group_id`

Si apunta a `entry_group_id`, el motor necesita una politica explicita.

Politicas posibles:
- `fifo`
- `lifo`
- `proportional`
- `explicit_leg_targets`

Decision v1:
- no asumir politica implicita si no viene definida

### `close_position`

Misma idea:
- mejor cerrar un `leg_id`
- o un `entry_group_id` con politica declarada

## Hedging vs netting

## Caso `hedging`

Mapeo natural:
- una `leg` puede corresponderse con una `broker_position`
- un `entry_group` puede contener varias positions del broker

Este es el modo ideal para el modelo propuesto.

## Caso `netting`

Mapeo menos natural:
- varias `legs` logicas pueden quedar reflejadas en una unica posicion neta del
  broker

Por eso, incluso si el broker netea:
- el motor debe seguir conservando `legs` y `entry_groups` logicos

Eso permite:
- mantener trazabilidad
- no perder la semantica estrategica

En la propuesta v1, esto queda parcialmente contenido por la politica ya
definida:
- `single_owner_per_symbol` en cuentas `netting`

## Ownership canonico

Toda entidad operativa creada por el motor debe cargar:
- `strategy_key`
- `instance_id`
- `opened_by_plan_id` o equivalente

Y cuando tenga sentido:
- `entry_group_id`
- `leg_id`

## Action targeting recomendado

Las `actions` deben poder apuntar a estos niveles:

### Nivel leg

Para:
- cerrar una entrada concreta
- mover el stop de una entrada concreta
- reducir una entrada concreta

### Nivel entry_group

Para:
- cerrar una campana completa
- mover reglas comunes
- actuar sobre un setup compuesto

### Nivel view

Solo para operaciones de conveniencia o consulta.
No debe ser la unica fuente de verdad si hay ambiguedad.

## Ejemplo aplicado a `primeraEstrategia.md`

Secuencia:

1. Entrada inicial:
   - crea `grp_001`
   - crea `leg_001`

2. Primera piramide:
   - reutiliza `grp_001`
   - crea `leg_002`

3. Segunda piramide:
   - reutiliza `grp_001`
   - crea `leg_003`

Resultado:
- tres entradas independientes
- una campana compartida
- ownership claro
- trazabilidad exacta

## Decision actual

La propuesta canonica v1 es:
- `leg` como unidad primaria de exposicion independiente
- `entry_group` como unidad de agrupacion superior
- `broker_position` como realidad externa del broker
- `position_view` como agregado derivado
- `pending_order` y `fill` como recursos/eventos base de auditoria

