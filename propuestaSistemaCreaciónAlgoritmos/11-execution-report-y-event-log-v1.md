# Execution Report y Event Log V1

## Objetivo

Cerrar la trazabilidad end-to-end del sistema.

Necesitamos dos capas distintas:
- una capa de lectura operativa rapida
- una capa de auditoria fina y replay

Por eso la propuesta v1 distingue:
- `execution_report`
- `event_log`

## Diferencia fundamental

### `execution_report`

Es el resumen estructurado de lo que paso con un plan concreto.

Sirve para:
- UI
- debugging rapido
- observabilidad operativa
- respuesta inmediata del motor

### `event_log`

Es la traza canonica, append-only, detallada y correlacionable.

Sirve para:
- auditoria
- replay
- reconstruccion historica
- analisis forense
- analitica posterior

## Regla de oro

El `execution_report` resume.
El `event_log` demuestra.

Si ambos se contradicen, la fuente de verdad canonica es el `event_log`.

## 1. `execution_report`

## Objetivo

Describir el destino de un `plan` de forma compacta, legible y estructurada.

## Forma general

```python
execution_report = {
    "report_schema_version": 1,
    "report_id": "rep_000124",
    "plan_id": "plan_000124",
    "run": {...},
    "strategy": {...},
    "status": "executed",
    "summary": "...",
    "stats": {...},
    "action_reports": [...],
    "state_update": {...},
    "timing": {...},
}
```

## Campos de cabecera

### `report_schema_version`

Versiona el schema del propio reporte.

```python
"report_schema_version": 1
```

### `report_id`

Identificador unico del reporte.

```python
"report_id": "rep_000124"
```

### `plan_id`

Debe copiar el `plan_id` del plan interpretado.

```python
"plan_id": "plan_000124"
```

## Bloque `run`

Describe el contexto operativo minimo del reporte.

```python
"run": {
    "iteration_id": "iter_000124",
    "mode": "live",
    "started_at": "2026-04-06T13:40:00Z",
    "finished_at": "2026-04-06T13:40:02Z",
}
```

## Bloque `strategy`

Identifica al emisor del plan.

```python
"strategy": {
    "strategy_key": "adx_di_pyramid",
    "instance_id": "adx_di_pyramid::DE40",
    "symbol": "DE40",
}
```

## `status` a nivel plan

Estados recomendados v1:
- `accepted`
- `executed`
- `partially_executed`
- `rejected_structural`
- `rejected_technical`
- `rejected_broker`
- `duplicate_skipped`
- `error`

### Semantica

- `accepted`: valido, pero aun no ejecutado del todo
- `executed`: todas las actions relevantes se completaron con exito
- `partially_executed`: algunas si, otras no
- `rejected_structural`: el plan estaba mal formado
- `rejected_technical`: el motor no pudo interpretarlo o aplicarlo tecnicamente
- `rejected_broker`: el broker rechazo la operativa relevante
- `duplicate_skipped`: era un plan ya aplicado
- `error`: fallo no clasificado o excepcional

## `summary`

Texto corto para humanos.

Ejemplos:
- `2/2 actions ejecutadas`
- `Plan rechazado: target no encontrado`
- `1 action ejecutada, 1 rechazada por broker`

## `stats`

Resumen cuantitativo.

```python
"stats": {
    "action_count": 2,
    "validated_count": 2,
    "executed_count": 1,
    "partially_executed_count": 0,
    "rejected_count": 1,
    "duplicate_count": 0,
}
```

## `action_reports`

Lista canonica de resultados por action.

## Schema base de `action_report`

```python
action_report = {
    "action_id": "act_0001",
    "type": "open_position",
    "status": "executed",
    "message": "...",
    "requested": {...},
    "resolved_targets": [...],
    "resolved_values": {...},
    "normalization": {...},
    "broker_result": {...},
    "resource_effects": {...},
    "timing": {...},
}
```

## Campos de `action_report`

### `requested`

La action original tal y como la emitio la estrategia.

### `resolved_targets`

Explica a que recursos concretos se aplico realmente la action.

Ejemplo:

```python
"resolved_targets": [
    {
        "resource_type": "leg",
        "resource_id": "leg_003",
    }
]
```

### `resolved_values`

Valores ya traducidos a forma ejecutable.

Ejemplo:

```python
"resolved_values": {
    "volume": 0.17,
    "entry_price": 18412.0,
    "stop_loss": 18389.1,
    "take_profit": 18453.3,
}
```

### `normalization`

Debe registrar toda adaptacion tecnica relevante.

Ejemplo:

```python
"normalization": {
    "volume": {
        "requested": 0.173,
        "normalized": 0.17,
        "rule": "volume_step_round_down",
    },
    "price": {
        "requested_stop_loss": 18389.07,
        "normalized_stop_loss": 18389.1,
        "rule": "tick_size_round",
    },
}
```

### `broker_result`

No debe ser solo un booleano.

Ejemplo:

```python
"broker_result": {
    "retcode": 10009,
    "broker_order_id": "987654",
    "broker_position_id": "pos_789",
    "broker_deal_ids": ["456789"],
    "comment": "Request completed",
}
```

### `resource_effects`

Que cambio en el modelo canonico del motor.

Ejemplo:

```python
"resource_effects": {
    "created_legs": ["leg_003"],
    "updated_legs": [],
    "closed_legs": [],
    "created_orders": ["ord_007"],
    "updated_groups": ["grp_001"],
}
```

## `state_update`

Resume que paso con `next_state`.

Formato orientativo:

```python
"state_update": {
    "previous_revision": 12,
    "new_revision": 13,
    "persisted": True,
}
```

## `timing`

Mide latencias del plan.

Formato orientativo:

```python
"timing": {
    "decision_to_execution_ms": 320,
    "total_report_ms": 510,
}
```

## 2. `event_log`

## Objetivo

Registrar de forma append-only los eventos relevantes del motor.

No reemplaza al reporte:
- lo fundamenta

## Regla estructural

Cada evento debe usar un sobre comun.

## Sobre comun de evento

```python
event = {
    "event_schema_version": 1,
    "event_id": "evt_000001",
    "event_type": "plan_received",
    "occurred_at": "2026-04-06T13:40:00.120Z",
    "run": {...},
    "strategy": {...},
    "correlation": {...},
    "payload": {...},
}
```

## Campos comunes del evento

### `event_schema_version`

Version del schema del evento.

### `event_id`

Identificador unico e inmutable.

### `event_type`

Tipo concreto del evento.

### `occurred_at`

Timestamp UTC preciso del evento.

### `run`

Ejemplo:

```python
"run": {
    "iteration_id": "iter_000124",
    "mode": "live",
}
```

### `strategy`

Ejemplo:

```python
"strategy": {
    "strategy_key": "adx_di_pyramid",
    "instance_id": "adx_di_pyramid::DE40",
    "symbol": "DE40",
}
```

### `correlation`

Bloque de correlacion fuerte entre eventos.

Formato orientativo:

```python
"correlation": {
    "plan_id": "plan_000124",
    "action_id": "act_0001",
    "report_id": "rep_000124",
    "entry_group_id": "grp_001",
    "leg_id": "leg_003",
    "order_id": "ord_007",
    "broker_order_id": "987654",
    "broker_position_id": "pos_789",
    "fill_id": "fill_001",
}
```

No todos los campos existen en todos los eventos.

## Catalogo inicial de eventos v1

Eventos recomendados:
- `plan_received`
- `plan_validated`
- `plan_rejected`
- `action_validated`
- `action_target_resolved`
- `action_normalized`
- `action_duplicate_skipped`
- `broker_request_sent`
- `broker_response_received`
- `fill_recorded`
- `pending_order_state_changed`
- `leg_state_changed`
- `entry_group_state_changed`
- `state_persisted`
- `report_emitted`
- `error_raised`

## Semantica de eventos clave

## `plan_received`

Se emite cuando el motor acepta el payload de entrada para procesarlo.

Payload orientativo:

```python
"payload": {
    "schema_version": 1,
    "action_count": 2,
}
```

## `plan_validated`

Se emite cuando el plan supera validacion estructural y tecnica inicial.

## `plan_rejected`

Se emite cuando el plan no puede continuar.

Payload orientativo:

```python
"payload": {
    "reason_code": "target_not_owned",
    "message": "La action apunta a una leg ajena",
}
```

## `action_target_resolved`

Muestra a que recurso concreto apunto realmente la action.

Payload orientativo:

```python
"payload": {
    "resource_type": "leg",
    "resource_ids": ["leg_003"],
}
```

## `action_normalized`

Registra los cambios tecnicos aplicados por el motor.

## `broker_request_sent`

Registra la peticion operativa real enviada al broker.

Importante:
- puede haber datos sensibles
- el payload real puede requerir politica de mascarado o redaccion

## `broker_response_received`

Registra la respuesta cruda o resumida del broker.

## `fill_recorded`

Es uno de los eventos mas importantes.

Debe registrar:
- volumen
- precio
- lado
- tipo de fill
- recursos afectados

## `pending_order_state_changed`

Ejemplo:
- `working -> filled`
- `working -> cancelled`

## `leg_state_changed`

Ejemplo:
- `pending_open -> open`
- `open -> reducing`
- `reducing -> closed`

## `entry_group_state_changed`

Ejemplo:
- `open -> partially_closed`
- `partially_closed -> closed`

## `state_persisted`

Debe registrar al menos:
- revision previa
- revision nueva
- resultado de persistencia

## `report_emitted`

Marca la emision final del `execution_report`.

## `error_raised`

Se emite cuando ocurre un error excepcional no modelado como rechazo normal.

## Orden logico esperado de eventos

Secuencia tipica:

1. `plan_received`
2. `plan_validated`
3. `action_validated`
4. `action_target_resolved`
5. `action_normalized`
6. `broker_request_sent`
7. `broker_response_received`
8. `fill_recorded`
9. `leg_state_changed`
10. `entry_group_state_changed`
11. `state_persisted`
12. `report_emitted`

No todos los planes generaran todos los eventos.

## Relacion entre `execution_report` y `event_log`

El `execution_report` puede verse como una vista materializada del event log.

Regla recomendada:
- el reporte se construye a partir de resultados del proceso
- pero debe poder reconciliarse con eventos concretos

Por eso ambos deben compartir ids:
- `plan_id`
- `action_id`
- `report_id`
- ids de recursos

## Reglas de trazabilidad minima

Todo cambio importante debe ser rastreable por:
- `strategy_key`
- `instance_id`
- `iteration_id`
- `plan_id`
- `action_id`

Y cuando aplique:
- `entry_group_id`
- `leg_id`
- `order_id`
- `fill_id`

## Politica de granularidad

Regla v1:
- registrar hechos relevantes
- no registrar ruido inutil

Ejemplo de buen detalle:
- una normalizacion de volumen
- un rechazo por target ambiguo
- un fill parcial

Ejemplo de mal detalle:
- logs de depuracion arbitrarios sin schema

## Ejemplo aplicado a `primeraEstrategia.md`

Escenario:
- `add_to_position` crea una nueva piramide

Traza minima deseada:

1. `plan_received`
2. `action_validated`
3. `action_target_resolved` con `entry_group_id = grp_001`
4. `action_normalized` con volumen y SL/TP normalizados
5. `broker_request_sent`
6. `broker_response_received`
7. `fill_recorded` con `leg_id = leg_003`
8. `leg_state_changed` a `open`
9. `entry_group_state_changed` si cambia su agregacion
10. `state_persisted`
11. `report_emitted`

Y el `execution_report` debe resumir todo eso de forma compacta.

## Decision actual

La propuesta v1 es:
- `execution_report` como resumen estructurado por plan
- `event_log` como traza canonica append-only
- ids compartidos para correlacion completa
- normalizaciones, rechazos, fills y cambios de estado visibles
- el `event_log` es la fuente de verdad final para auditoria y replay

