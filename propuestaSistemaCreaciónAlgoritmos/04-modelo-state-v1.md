# Modelo State V1

## Objetivo

El `state` es la memoria privada de una estrategia entre ciclos.

No representa la verdad del broker.
Representa lo que la estrategia necesita recordar para decidir mejor.

## Frontera correcta

Seguimos esta regla:

- `context` = realidad actual observada por el sistema
- `state` = memoria privada de la estrategia

Ejemplos de cosas que pertenecen al `context`:
- posiciones abiertas reales
- ordenes pendientes reales
- fills reales
- equity actual
- velas e indicadores del snapshot

Ejemplos de cosas que pertenecen al `state`:
- numero de piramides realizadas
- precio de la ultima entrada que la estrategia considera relevante
- cooldowns internos
- contadores diarios
- ultimo regimen detectado
- banderas internas de control

## Regla de soberania

El motor no debe imponer una semantica financiera fuerte al contenido del
`state`.

La estrategia debe tener libertad para definir su memoria.

Por eso el modelo correcto es de dos capas:
- una envoltura comun controlada por el motor
- un bloque libre controlado por la estrategia

## Estructura propuesta v1

```python
state = {
    "schema_version": 1,
    "instance": {...},
    "meta": {...},
    "strategy_state": {...},
}
```

## 1. `schema_version`

Sirve para versionar el formato externo del `state`.

Ejemplo:

```python
"schema_version": 1
```

Esto permite migraciones futuras sin romper estrategias ya guardadas.

## 2. `instance`

Identifica de forma estable a quien pertenece este `state`.

Formato sugerido:

```python
"instance": {
    "instance_id": "adx_di_pyramid::DE40",
    "strategy_key": "adx_di_pyramid",
    "symbol": "DE40",
}
```

Notas:
- `instance_id` debe ser la clave canonica de persistencia
- si algun dia existen varias instancias de la misma estrategia sobre el mismo
  simbolo, `instance_id` debe diferenciarlas

## 3. `meta`

Es metadata tecnica del `state`, no logica de trading.

Formato sugerido:

```python
"meta": {
    "revision": 12,
    "created_at": "2026-04-06T13:00:00Z",
    "updated_at": "2026-04-06T13:40:00Z",
    "last_decision_id": "iter_000124",
}
```

Para que sirve:
- trazabilidad
- control de concurrencia
- auditoria
- depuracion

## 4. `strategy_state`

Aqui vive la memoria libre de la estrategia.

El motor no deberia exigir un esquema de negocio fijo dentro de este bloque.

Ejemplo:

```python
"strategy_state": {
    "pyramiding": {
        "count": 1,
        "last_entry_price": 18410.5,
        "last_entry_time": "2026-04-06T12:10:00Z",
    },
    "risk": {
        "session_open_risk_pct": 2.1,
    },
    "cooldowns": {
        "new_entries_blocked_until": None,
    },
    "regime": {
        "bias": "long_only",
    },
}
```

## Regla de diseno interna

El motor define el sobre.
La estrategia define el contenido.

Eso mantiene libertad total sin perder orden tecnico.

## Propiedades obligatorias del state

El `state` v1 debe ser:
- serializable
- pequeno y significativo
- determinista
- versionable
- restaurable tras reinicio
- independiente de objetos del broker

## Que NO debe guardarse en el state

No deberian guardarse:
- handles o conexiones MT5
- DataFrames completos
- historial grande de velas
- copias enteras de posiciones reales del broker
- caches opacas no serializables
- objetos Python arbitrarios

Regla clave:
- si algo pertenece a la realidad observable actual, va al `context`
- si algo es memoria privada util para decidir mas tarde, va al `state`

## Antipatrones importantes

### 1. Duplicar la verdad del broker

Ejemplo malo:
- guardar en `state` una copia completa de todas las posiciones abiertas

Problema:
- si el broker cambia y el `state` no, aparecen desincronizaciones

Correcto:
- el broker y el motor dicen cuales son las posiciones reales
- la estrategia solo guarda referencias o memoria complementaria si la necesita

### 2. Usar el state como vertedero

Ejemplo malo:
- guardar todos los calculos intermedios de cada ciclo aunque puedan
  recalcularse facilmente

Problema:
- el `state` crece, se ensucia y se vuelve fragil

Correcto:
- guardar solo lo que de verdad haga falta recordar

### 3. Mezclar negocio con metadata tecnica

Ejemplo malo:
- meter `revision` y `updated_at` dentro de `strategy_state`

Correcto:
- metadata tecnica en `meta`
- memoria estrategica en `strategy_state`

## Persistencia v1

### Decisiones acordadas

El `state` debe:
- cargarse al inicio de cada ciclo
- entregarse a la estrategia como `estado_anterior`
- persistirse solo a traves del motor
- escribirse de forma atomica

La estrategia nunca deberia escribir directamente su estado en disco.

## Flujo propuesto de persistencia

1. El motor resuelve `instance_id`.
2. El motor carga el `state` persistido mas reciente.
3. Si no existe, crea uno vacio con la envoltura base.
4. El motor llama a la estrategia con `context + state`.
5. La estrategia devuelve `actions + next_state + reason`.
6. El motor valida el resultado.
7. El motor persiste `next_state` de forma atomica.

## Regla importante sobre persistencia

Lo que se persiste es `next_state`, no mutaciones parciales sueltas.

Eso da varias ventajas:
- modelo mental limpio
- menos side effects
- mejor trazabilidad
- mayor facilidad para replay

## Escritura atomica

El almacenamiento concreto puede cambiar en el futuro, pero la semantica debe
ser esta:
- o queda guardada la nueva version completa del state
- o se conserva la version anterior completa

Nunca un estado a medio escribir.

## Control de concurrencia

Como puede haber varias estrategias o workers, el `state` debe incluir una
`revision` en `meta`.

Eso permite al motor detectar condiciones de carrera del tipo:
- un worker intenta escribir revision 12
- pero ya existe revision 13

En ese caso el motor decide:
- rechazar la escritura
- reintentar
- o volver a ejecutar la estrategia con snapshot nuevo

La politica exacta queda abierta, pero la `revision` debe existir.

## Backend de persistencia

La eleccion exacta del backend sigue abierta.

Opciones validas:
- archivo JSON por `instance_id`
- SQLite
- base de datos mas robusta

Decision actual:
- el contrato logico del `state` se define antes que el backend

## Ejemplo minimo para tu estrategia

Una estrategia como la de `primeraEstrategia.md` podria necesitar algo asi:

```python
state = {
    "schema_version": 1,
    "instance": {
        "instance_id": "adx_di_pyramid::DE40",
        "strategy_key": "adx_di_pyramid",
        "symbol": "DE40",
    },
    "meta": {
        "revision": 4,
        "created_at": "2026-04-06T09:00:00Z",
        "updated_at": "2026-04-06T13:40:00Z",
        "last_decision_id": "iter_000124",
    },
    "strategy_state": {
        "pyramiding": {
            "count": 1,
            "last_entry_price": 18410.5,
            "last_entry_time": "2026-04-06T12:10:00Z",
        },
        "risk": {
            "session_open_risk_pct": 2.1,
        },
        "session": {
            "trading_day": "2026-04-06",
        },
        "cooldowns": {
            "new_entries_blocked_until": None,
        },
    },
}
```

Con eso la estrategia puede recordar:
- cuantas piramides hizo
- desde que precio mide el siguiente avance de 0.5 ATR
- cuanto riesgo de sesion cree llevar
- si esta bloqueada temporalmente

## Decision actual

La propuesta formal es:
- `state` separado de `context`
- sobre comun controlado por el motor
- contenido libre controlado por la estrategia
- persistencia atomica gobernada por el motor
- `revision` obligatoria para concurrencia y auditoria

