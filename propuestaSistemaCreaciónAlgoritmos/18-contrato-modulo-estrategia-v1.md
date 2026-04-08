# Contrato Del Modulo De Estrategia v1

## Objetivo

Definir la forma exacta que debe tener un modulo Python de estrategia para ser
ejecutado por el runtime nuevo.

Este documento responde a:
- que debe exportar el modulo
- como se detecta si es legacy o v1
- que firma tiene `decide()`
- que metadata declara la estrategia
- que hooks opcionales se admiten

## Principio de compatibilidad con el repo actual

El contrato v1 debe aprovechar lo que ya funciona hoy:
- modulos Python dentro de `strategies/`
- discovery por archivo y por modulo
- carga dinamica por import
- bajo acoplamiento con el core

Eso significa:
- no introducimos clases obligatorias
- no introducimos registro manual centralizado
- no obligamos a instalar paquetes especiales

La unidad de despliegue sigue siendo:
- un archivo Python en `strategies/`

## Deteccion de tipo de estrategia

El runtime debe detectar el contrato de este modo:

1. Si el modulo expone `decide` y `STRATEGY_API_VERSION = 1`, se trata como
   estrategia v1.
2. Si no, pero expone `get_last_signal()` o `get_last_signal_payload()`, entra
   por el adaptador legacy.
3. Si no cumple ninguno, el modulo no es ejecutable como estrategia.

Regla:
- el contrato v1 debe tener prioridad sobre el legado

## Forma recomendada del modulo

Un modulo v1 sigue siendo un modulo funcional, no orientado a clases.

Preferimos esto:

```python
STRATEGY_API_VERSION = 1
TIMEFRAME = "M15"

def initial_state(context: dict) -> dict:
    ...

def decide(context: dict, state: dict) -> dict:
    ...
```

Y no esto como requisito obligatorio:
- clases `Strategy`
- herencia
- decoradores de registro
- side effects al importar

## Exportaciones requeridas

## `STRATEGY_API_VERSION = 1`

Obligatorio.

Sirve para:
- distinguir v1 de legacy
- permitir futuras versiones del contrato
- evitar heuristicas fragiles basadas solo en nombres de funciones

## `decide(context: dict, state: dict) -> dict`

Obligatorio.

Es el entry point canonico de la estrategia.

Debe:
- leer `context`
- leer `state`
- decidir
- devolver `plan + next_state`

No debe:
- tocar broker
- tocar SQLite
- abrir archivos
- depender de globals mutables del proyecto

## Exportaciones recomendadas

## `TIMEFRAME = "M15"`

Muy recomendado.

Mantiene continuidad con el sistema actual, donde el timeframe ya puede
declararse en el modulo.

Si la estrategia usa un timeframe principal claro, debe declararlo aqui.

## `DISPLAY_NAME`

Recomendado.

Sirve como fallback de presentacion si la GUI o el registro no tienen una
etiqueta mejor.

## `DESCRIPTION`

Recomendado.

Sirve para:
- UI
- catalogo de estrategias
- auditoria
- tooling futuro

## `STATE_SCHEMA_VERSION`

Recomendado.

No reemplaza el versionado global de persistencia.

Sirve para versionar la estructura interna de `strategy_state` que pertenece a
la estrategia.

## `DATA_WINDOW_FIELDS`

Opcional, pero recomendable si la estrategia quiere exponer valores propios a la
GUI.

Se mantiene por compatibilidad conceptual con el sistema actual.

## `CONTEXT_REQUIREMENTS`

Opcional, pero muy importante a medio plazo.

Declara que necesita la estrategia del `context` para evitar dos extremos:
- contextos demasiado pobres
- contextos gigantes construidos sin necesidad

Ejemplo de forma recomendada:

```python
CONTEXT_REQUIREMENTS = {
    "primary_timeframe": "M15",
    "timeframes": ["M15", "H1"],
    "history_bars": {"M15": 600, "H1": 300},
    "needs_quote": True,
    "needs_account": True,
    "needs_execution_views": ["owned_legs", "owned_entry_groups", "views"],
}
```

## Metadata agrupada opcional

Si se quiere reducir proliferacion de constantes, se puede admitir un contenedor
como:

```python
STRATEGY_INFO = {
    "display_name": "ADX Pyramid Trend",
    "description": "...",
    "tags": ["trend", "adx", "pyramid"],
}
```

Pero en v1 no debe ser el unico mecanismo requerido.

Razon:
- mantener simple el contrato
- no romper el estilo funcional actual

## Hooks opcionales admitidos

## `initial_state(context: dict) -> dict`

Opcional.

Se usa cuando no existe estado persistido previo para la instancia.

Debe devolver solo el bloque `strategy_state`, no el envelope tecnico del motor.

Si no existe:
- el runtime usa `{}` como estado inicial por defecto

## `migrate_state(state: dict, from_version: int | None) -> dict`

Opcional.

Sirve para migrar el `strategy_state` propio cuando cambia
`STATE_SCHEMA_VERSION`.

No debe migrar:
- tablas SQLite
- envelope global del motor
- recursos canonicos externos

Solo el estado propio de la estrategia.

## `get_timeframe() -> str`

Opcional.

Puede admitirse por continuidad con el sistema actual.

Regla:
- si existen `TIMEFRAME` y `get_timeframe()`, el runtime debe definir una
  precedencia clara

Recomendacion v1:
- `get_timeframe()` tiene prioridad solo si realmente hay necesidad dinamica
- en la mayoria de casos, preferir `TIMEFRAME`

## Hooks que NO conviene meter en v1

No conviene oficializar todavia:
- `before_execute()`
- `after_fill()`
- `on_tick()`
- `on_order_update()`
- acceso directo a un `broker_client`

Razon:
- complican demasiado el modelo
- abren la puerta a side effects y estados implícitos
- rompen la idea de `context + state -> plan + next_state`

## Contrato exacto de `decide()`

## Firma

```python
def decide(context: dict, state: dict) -> dict:
    ...
```

## Semantica de entrada

### `context`

Es una foto de solo lectura del sistema.

Su forma detallada se define en [03-modelo-contexto-v1.md](C:/RealProjects/TradingAgent/trading-agent/propuestaSistemaCreaciónAlgoritmos/03-modelo-contexto-v1.md).

La estrategia debe tratarlo como inmutable aunque tecnicamente sea un `dict`.

### `state`

Es el `strategy_state` propio de la estrategia.

No es:
- el envelope tecnico completo
- la verdad del broker
- una vista completa de persistencia

El runtime debe deserializar el estado persistido y entregar solo la parte
propia de la estrategia.

Su contrato detallado se apoya en [04-modelo-state-v1.md](C:/RealProjects/TradingAgent/trading-agent/propuestaSistemaCreaciónAlgoritmos/04-modelo-state-v1.md).

## Semantica de salida

`decide()` debe devolver un `decision` con al menos:
- `plan`
- `next_state`

Forma minima:

```python
{
    "plan": {...},
    "next_state": {...},
}
```

No se admite como salida valida:
- `None`
- solo una lista de acciones
- solo `"buy"` o `"sell"`

## Regla de no-op

Si la estrategia no quiere actuar:
- debe devolver un `plan` valido
- con `actions = []`

Eso es mejor que devolver `None` porque:
- mantiene trazabilidad
- permite audit log uniforme
- simplifica testing y replay

## Estructura minima recomendada de `plan`

El `plan` debe alinearse con [02-modelo-plan-y-actions.md](C:/RealProjects/TradingAgent/trading-agent/propuestaSistemaCreaciónAlgoritmos/02-modelo-plan-y-actions.md) y [10-catalogo-actions-v1.md](C:/RealProjects/TradingAgent/trading-agent/propuestaSistemaCreaciónAlgoritmos/10-catalogo-actions-v1.md).

Minimo recomendado:
- `schema_version`
- `plan_id`
- `instance_id`
- `symbol`
- `reason`
- `actions`

Responsabilidad del runtime:
- completar ids si la estrategia no los genera
- validar schema antes de ejecutar

Responsabilidad de la estrategia:
- decidir la intencion de trading
- producir una razon coherente

## Estructura de `next_state`

`next_state` debe ser:
- serializable
- propio de la estrategia
- libre de objetos no persistibles

No conviene meter dentro:
- `DataFrame`
- objetos MT5
- handles de archivos
- conexiones
- funciones

Si la estrategia necesita recordar algo, debe guardar solo datos simples:
- numeros
- strings
- listas o dicts serializables
- timestamps normalizados

## Responsabilidad de ids y metadata

La estrategia puede generar:
- `plan_id`
- `action_id`
- metadata adicional

Pero no debe ser obligatorio en v1 temprana.

El runtime puede completar lo faltante para:
- idempotencia
- correlacion
- persistencia

## Politica de pureza y side effects

Una estrategia v1 debe ser lo mas cercana posible a una funcion pura.

Se permite:
- calculo con `pandas`
- uso de libreria standard
- lectura de `context`
- transformacion de `state`

No se permite como parte del contrato:
- IO arbitrario
- consultas al broker
- escrituras a base de datos
- modificacion de globals del core

## Politica de errores

Si la estrategia encuentra una situacion normal de negocio:
- no debe lanzar excepcion
- debe devolver un `plan` no-op si corresponde

Si la estrategia detecta corrupcion o imposibilidad tecnica interna:
- puede lanzar excepcion
- el runtime debe tratar eso como error de decision, no de ejecucion

La frontera correcta es:
- "no hay setup" => no-op
- "mi estado no se puede interpretar" => excepcion

## Politica de versionado

Hay dos versionados distintos.

### Versionado del contrato del modulo

Lo marca:
- `STRATEGY_API_VERSION`

En este documento:
- `1`

### Versionado del estado propio de la estrategia

Lo marca:
- `STATE_SCHEMA_VERSION`

Eso permite:
- evolucionar el contrato general mas tarde
- sin mezclarlo con la version interna de cada algoritmo

## Politica de imports

Se mantiene la filosofia de `strategies/README.md`:
- puede usar `pandas`
- puede usar libreria standard
- no debe importar `trading`, `config`, `data_feed`, GUI ni partes del core

Razón:
- mejor aislamiento
- mejor test unitario
- menos acoplamiento accidental

## Politica de discovery

Las estrategias v1 deben seguir siendo descubribles igual que hoy:
- por archivo en `strategies/`
- por modulo `strategies.xxx`
- por ruta si se admite carga directa

No se requiere:
- registro manual
- manifest externo obligatorio

## Ejemplo de modulo v1

```python
"""ADX Pyramid Trend v1."""

import pandas as pd

STRATEGY_API_VERSION = 1
TIMEFRAME = "M15"
DISPLAY_NAME = "ADX Pyramid Trend"
DESCRIPTION = "Tendencia con ADX, entradas iniciales y piramidacion."
STATE_SCHEMA_VERSION = 1

CONTEXT_REQUIREMENTS = {
    "primary_timeframe": "M15",
    "timeframes": ["M15"],
    "history_bars": {"M15": 500},
    "needs_quote": True,
    "needs_account": True,
    "needs_execution_views": ["owned_legs", "owned_entry_groups", "views"],
}

DATA_WINDOW_FIELDS = [
    {"key": "adx", "label": "ADX", "format": "float", "section": "Trend"},
    {"key": "plus_di", "label": "+DI", "format": "float", "section": "Trend"},
    {"key": "minus_di", "label": "-DI", "format": "float", "section": "Trend"},
]

def initial_state(context: dict) -> dict:
    return {
        "pyramid_count": 0,
        "last_entry_price": None,
        "cooldown_until": None,
    }

def decide(context: dict, state: dict) -> dict:
    state = dict(state or {})
    market = context["market"]["timeframes"]["M15"]
    df = market["bars"]
    symbol = context["symbol"]["name"]
    instance_id = context["instance"]["id"]

    if len(df) < 3:
        return {
            "plan": {
                "schema_version": 1,
                "symbol": symbol,
                "instance_id": instance_id,
                "reason": "No hay suficientes velas",
                "actions": [],
            },
            "next_state": state,
        }

    last = df.iloc[-2]

    if float(last["adx"]) > 25 and float(last["plus_di"]) > float(last["minus_di"]):
        return {
            "plan": {
                "schema_version": 1,
                "symbol": symbol,
                "instance_id": instance_id,
                "reason": "ADX fuerte con sesgo long",
                "actions": [
                    {
                        "type": "open_position",
                        "symbol": symbol,
                        "side": "long",
                        "size_spec": {"mode": "risk_pct", "value": 1.0},
                        "stop_spec": {"mode": "atr_multiple", "atr_period": 14, "value": 1.0},
                        "take_profit_spec": {"mode": "risk_multiple", "value": 2.0},
                        "reason": "Entrada inicial",
                    }
                ],
            },
            "next_state": {
                **state,
                "last_signal": "buy",
            },
        }

    return {
        "plan": {
            "schema_version": 1,
            "symbol": symbol,
            "instance_id": instance_id,
            "reason": "Sin setup",
            "actions": [],
        },
        "next_state": state,
    }
```

## Decision de diseño

El contrato v1 del modulo debe ser:
- funcional
- pequeno
- explicito
- compatible con discovery actual

La estrategia debe aportar:
- metadata minima
- `decide()`
- estado propio opcional

El motor debe aportar:
- context builder
- persistencia
- validacion
- ejecucion
- observabilidad

Esa frontera es la que mantiene el supersistema potente sin convertir cada
estrategia en un mini framework.
