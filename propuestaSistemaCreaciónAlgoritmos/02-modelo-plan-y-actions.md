# Modelo Plan y Actions

## Problema a resolver

Si cada estrategia habla directamente con el broker:
- duplica logica tecnica
- diverge entre live y backtest
- complica el debug
- reduce la trazabilidad
- aumenta el riesgo de bugs operativos

Por eso la estrategia no deberia enviar ordenes por su cuenta.
Deberia devolver un `plan`.

## Idea central

La estrategia no dice:
- "llama a MT5 asi"

La estrategia dice:
- "quiero hacer estas acciones"

Luego el motor traduce ese plan a operaciones reales.

## Forma minima del resultado

```python
result = {
    "actions": [...],
    "next_state": {...},
    "reason": "...",
}
```

Reglas:
- `actions` debe ser serializable
- `next_state` debe ser serializable
- `reason` debe resumir por que se tomo la decision

## Catalogo inicial de actions

Las `actions` deberian ser declarativas. Catalogo inicial propuesto:

- `open_position`
- `add_to_position`
- `close_position`
- `reduce_position`
- `move_stop_loss`
- `move_take_profit`
- `cancel_pending_order`
- `place_pending_order`
- `replace_pending_order`

El catalogo oficial v1 se cierra en:
- `10-catalogo-actions-v1.md`

Regla:
- si no hay acciones, se usa `actions = []`
- no hace falta una action `do_nothing`

## Campos base que deberia tener una action

Cada action deberia incluir al menos:

```python
action = {
    "type": "open_position",
    "symbol": "DE40",
    "side": "long",
    "size_spec": {...},
    "entry_spec": {...},
    "stop_spec": {...},
    "take_profit_spec": {...},
    "tags": {...},
    "reason": "...",
}
```

Interpretacion:
- `type`: que accion quiere la estrategia
- `symbol`: sobre que activo actuar
- `side`: long o short si aplica
- `size_spec`: como se calcula el tamano
- `entry_spec`: a mercado, limit, stop, etc.
- `stop_spec`: stop fijo, ATR, break even, trailing, etc.
- `take_profit_spec`: TP fijo, multiple, trailing, parcial, etc.
- `tags`: metadata para trazabilidad
- `reason`: motivo humano resumido

## Ejemplos de especificaciones utiles

### Size spec

La estrategia no deberia mandar solo `lot=0.12`.
Deberia poder mandar cosas como:

```python
{"mode": "risk_pct_of_equity", "value": 0.5}
```

o:

```python
{"mode": "fixed_lots", "value": 0.10}
```

o:

```python
{
    "mode": "formula",
    "formula_id": "volume_ratio_based",
    "inputs": {
        "base_risk_pct": 0.5,
        "cap_risk_pct": 1.0,
        "volume_ratio_field": "volume_ratio_20",
    },
}
```

### Stop spec

```python
{"mode": "atr_multiple", "atr_field": "atr_14", "multiple": 1.0}
```

o:

```python
{"mode": "price_offset", "points": 300}
```

### Take profit spec

```python
{"mode": "rr_multiple", "multiple": 2.0}
```

o:

```python
{
    "mode": "multi_target",
    "targets": [
        {"rr": 1.0, "close_pct": 50},
        {"rr": 2.0, "close_pct": 50},
    ],
}
```

## Ejemplo mental con tu estrategia

Para una entrada inicial, la estrategia podria devolver algo parecido a:

```python
{
    "actions": [
        {
            "type": "open_position",
            "symbol": "DE40",
            "side": "long",
            "size_spec": {
                "mode": "formula",
                "formula_id": "volume_ratio_based",
                "inputs": {
                    "base_risk_pct": 0.5,
                    "cap_risk_pct": 1.0,
                    "volume_ratio_field": "volume_ratio_20",
                },
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
            "tags": {
                "entry_kind": "initial",
                "setup": "adx_di_long",
            },
            "reason": "ADX > 25 y cruce alcista de +DI sobre -DI",
        }
    ],
    "next_state": {
        "pyramid_count": 1,
        "last_entry_kind": "initial",
    },
    "reason": "Nueva entrada valida segun reglas de la estrategia",
}
```

Y para una nueva piramide:

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
            "tags": {
                "entry_kind": "pyramid",
            },
            "reason": "Precio avanzo 0.5 ATR desde la ultima entrada",
        }
    ],
    "next_state": {
        "pyramid_count": 2,
        "last_entry_kind": "pyramid",
    },
    "reason": "Piramidacion permitida por la estrategia",
}
```

## Propiedades obligatorias del plan

El `plan` debe ser:
- declarativo
- interpretable por el motor
- agnostico del broker
- reutilizable en live, paper y backtest
- auditable
- serializable
- suficientemente expresivo para logica avanzada

## Regla de oro

La estrategia debe tener libertad para decidir.
El motor debe tener disciplina para ejecutar.

Ese equilibrio es el nucleo del supersistema.
