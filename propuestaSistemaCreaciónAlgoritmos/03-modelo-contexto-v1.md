# Modelo Contexto V1

## Objetivo

El `contexto` debe dar a la estrategia toda la verdad relevante del sistema en
modo solo lectura.

La estrategia no debe:
- consultar MT5 por su cuenta
- reconstruir estado tecnico por fuera del motor
- depender de globals compartidas

## Frontera semantica

Mantenemos esta separacion:

`contexto + estado_anterior -> plan + estado_nuevo`

Por tanto:
- `contexto` = realidad actual observada por el sistema
- `estado_anterior` = memoria privada de la estrategia

Aunque en el transporte real ambos puedan viajar dentro del mismo payload, no
deben confundirse conceptualmente.

## Propiedades obligatorias del contexto

El `contexto` v1 debe ser:
- consistente
- inmutable para la estrategia
- construido por el motor en un solo snapshot
- reutilizable en live, paper y backtest
- trazable y auditable

## Regla de formato

Hay dos niveles utiles:

1. Formato canonico
- serializable
- agnostico del broker
- pensado para logging, replay y backtest

2. Vista Python
- adaptadores comodos para consumo de estrategias Python
- por ejemplo `pd.DataFrame` para velas

Conclusion:
- el formato canonico no debe depender de pandas
- la capa Python si puede ofrecer DataFrames derivados

## Estructura propuesta v1

```python
context = {
    "run": {...},
    "clock": {...},
    "market": {...},
    "instrument": {...},
    "account": {...},
    "portfolio": {...},
    "execution": {...},
    "engine": {...},
}
```

## 1. `run`

Describe el marco operativo del ciclo actual.

Campos v1:

```python
"run": {
    "mode": "live",          # live | demo | paper | backtest
    "iteration_id": "...",
    "decision_snapshot_id": "...",
    "strategy_key": "...",
    "symbol": "DE40",
    "primary_timeframe": "M15",
    "symbol_book_revision": 42,
    "state_revision": 17,
}
```

Para que sirve:
- saber en que modo esta corriendo la estrategia
- asociar decisiones a una iteracion concreta
- saber contra que snapshot decidio
- correlacionar decision con revisiones locales
- dejar trazabilidad limpia en logs y replay

## 2. `clock`

Describe el tiempo del snapshot.

Campos v1:

```python
"clock": {
    "now_utc": "2026-04-06T13:40:00Z",
    "broker_time": "2026-04-06T15:40:00+02:00",
    "trading_day": "2026-04-06",
    "weekday": 1,
    "market_open": True,
}
```

Para que sirve:
- filtros horarios
- control de cooldowns
- reglas de sesion y reinicios diarios

## 3. `market`

Es la parte mas importante para decidir entradas y salidas.

Campos v1:

```python
"market": {
    "quote": {
        "bid": 18452.1,
        "ask": 18453.0,
        "mid": 18452.55,
        "spread_points": 9.0,
    },
    "frames": {
        "M1": {
            "bars": [...],
        },
        "M15": {
            "bars": [...],
        },
    },
}
```

### Sobre `bars`

Cada frame debe incluir velas ordenadas cronologicamente.

Formato canonico sugerido:

```python
"bars": [
    {
        "time": "2026-04-06T13:15:00Z",
        "open": 18420.0,
        "high": 18428.0,
        "low": 18418.5,
        "close": 18425.2,
        "tick_volume": 1532,
        "indicators": {
            "atr_14": 21.4,
            "adx_14": 28.2,
            "plus_di_14": 31.0,
            "minus_di_14": 18.5,
            "sma_volume_20": 1260.0,
        },
    },
]
```

La vista Python podria convertir esto en:
- `context.market.frames["M15"].df`

o en una estructura equivalente.

Para que sirve:
- detectar trigger
- medir volatilidad
- calcular sizing
- comparar varias temporalidades

## 4. `instrument`

Describe las reglas tecnicas del activo.

Campos v1:

```python
"instrument": {
    "symbol": "DE40",
    "base_currency": "EUR",
    "profit_currency": "EUR",
    "digits": 1,
    "point": 0.1,
    "tick_size": 0.1,
    "tick_value": 1.0,
    "volume_min": 0.01,
    "volume_max": 100.0,
    "volume_step": 0.01,
    "stop_level_points": 0.0,
    "freeze_level_points": 0.0,
}
```

Para que sirve:
- convertir riesgo a tamano real
- redondear volumen y precios
- evitar planes imposibles tecnicamente

## 5. `account`

Describe el estado de la cuenta.

Campos v1:

```python
"account": {
    "balance": 10000.0,
    "equity": 10120.0,
    "margin_used": 540.0,
    "margin_free": 9580.0,
    "currency": "EUR",
    "position_mode": "hedging",   # hedging | netting
}
```

Para que sirve:
- sizing por porcentaje de equity
- control de degradacion o expansion del riesgo
- decidir que modelo de convivencia multi-estrategia es realmente posible

Nota:
- `position_mode` es critico para saber si varias estrategias pueden mantener
  posiciones independientes sobre el mismo simbolo a nivel broker

## 6. `portfolio`

Describe exposicion agregada.

Campos v1:

```python
"portfolio": {
    "gross_exposure": 12500.0,
    "net_exposure": 6200.0,
    "open_risk_amount": 210.0,
    "open_risk_pct_equity": 2.07,
    "by_symbol": {
        "DE40": {
            "gross_exposure": 12500.0,
            "open_risk_amount": 210.0,
            "open_risk_pct_equity": 2.07,
        }
    },
    "by_strategy": {
        "adx_di_pyramid": {
            "gross_exposure": 12500.0,
            "open_risk_amount": 210.0,
            "open_risk_pct_equity": 2.07,
        }
    },
}
```

Para que sirve:
- que la estrategia pueda imponerse sus propios limites
- por ejemplo 3 por ciento maximo por ticker o por estrategia

## 7. `execution`

Describe la realidad operativa observada por el motor.

Campos v1:

```python
"execution": {
    "broker_positions": [...],
    "pending_orders": [...],
    "recent_fills": [...],
    "owned_legs": [...],
    "owned_entry_groups": [...],
    "views": {...},
}
```

### Broker positions

Las posiciones reales del broker deben seguir visibles.
Pero ya no son suficientes para modelar entradas independientes.

Por eso el contexto debe exponer dos niveles:
- realidad del broker
- recursos logicos de la estrategia

La definicion canonica detallada queda en:
- `08-modelo-canonico-recursos-operativos-v1.md`

### Owned legs

Las `owned_legs` son la unidad principal para una estrategia con entradas
independientes.

Ejemplo:

```python
"owned_legs": [
    {
        "leg_id": "leg_001",
        "instance_id": "adx_di_pyramid::DE40",
        "entry_group_id": "grp_001",
        "symbol": "DE40",
        "side": "long",
        "status": "open",
        "remaining_volume": 0.20,
        "avg_entry_price": 18410.5,
        "stop_loss": 18389.1,
        "take_profit": 18453.3,
        "tags": {
            "entry_kind": "initial",
            "pyramid_index": 0,
        },
    },
]
```

### Owned entry groups

Permiten agrupar varias legs relacionadas dentro de una misma campana o tesis.

Ejemplo:

```python
"owned_entry_groups": [
    {
        "entry_group_id": "grp_001",
        "instance_id": "adx_di_pyramid::DE40",
        "symbol": "DE40",
        "strategy_key": "adx_di_pyramid",
        "side": "long",
        "status": "open",
        "leg_ids": ["leg_001", "leg_002"],
        "tags": {
            "setup": "adx_di_long",
        },
    },
]
```

### Pending orders

Permite estrategias con ordenes stop o limit.

### Recent fills

Permite:
- detectar ejecuciones recientes
- evitar doble disparo en el mismo bar
- auditar comportamiento del motor

### Views

`views` permite exponer agregados convenientes sin convertirlos en la fuente de
verdad principal.

Ejemplos:
- `owned_position_views`
- `symbol_book_revision`
- `instance_book_revision`

## 8. `engine`

Describe reglas y capacidades del motor, no del broker.

Campos v1:

```python
"engine": {
    "supports_partial_close": True,
    "supports_pending_orders": True,
    "supports_position_tagging": True,
    "max_actions_per_cycle": 20,
}
```

Para que sirve:
- que la estrategia sepa que tipos de `actions` puede emitir
- mantener una frontera limpia entre modelo y ejecucion real

## Que NO debe estar en el contexto

No deben incluirse:
- objetos mutables compartidos entre estrategias
- conexiones o handles de MT5
- referencias a hilos o colas internas
- funciones con efectos secundarios
- caches opacas imposibles de serializar

## Ejemplo de payload completo

```python
payload = {
    "context": {...},
    "state": {...},
}
```

Donde:
- `context` es snapshot de solo lectura
- `state` es memoria privada previa de la estrategia

La estrategia devuelve:

```python
result = {
    "actions": [...],
    "next_state": {...},
    "reason": "...",
}
```

## Minimo viable realista para v1

Si hubiera que recortar sin romper el modelo, el contexto minimo serio seria:
- `run`
- `clock`
- `market.quote`
- `market.frames`
- `instrument`
- `account`
- `portfolio.by_symbol`
- `execution.owned_legs`

Con eso ya se puede soportar una estrategia como la de `primeraEstrategia.md`:
- trigger con ADX y DI
- sizing por volumen relativo
- stop y TP por ATR
- control de riesgo por ticker
- entrada inicial o piramidada

## Decision actual

La propuesta formal para el supersistema es:
- contexto rico y de solo lectura
- estado separado del contexto
- plan declarativo como salida
- ejecucion tecnica centralizada en el motor
