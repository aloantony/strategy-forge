# TASK-025: Añadir ADX+DI y cruce al Builder y generar la estrategia

- **ID**: TASK-025
- **Priority**: P1
- **Status**: in-progress
- **Assigned**: Felix
- **Blocked by**: TASK-019, TASK-023, TASK-024
- **Blocks**: nada

## Files to read
- `agents/felix.md` — tu definición de rol y workflow
- `agents/context.md` — contexto del proyecto
- `agents/specs/TASK-019-adx-di-crossover-spec.md` — spec ADX+DI+cruce de Daniel
- `agents/specs/TASK-020-pyramiding-spec.md` — para saber qué campos incluir en `get_last_signal_payload`
- `agents/specs/TASK-021-dynamic-sizing-risk-spec.md` — para saber qué campos incluir en `get_last_signal_payload`
- `strategies/builder.py` — implementación actual del Builder
- `agents/specs/TASK-014a-indicator-catalogue.md` — catálogo existente
- `primeraEstrategia.md` — estrategia a generar

## Description
Implementar soporte de ADX, +DI y -DI en `strategies/builder.py` (nuevo indicador, `prepare_dataframe`, emitter de cruce), y a continuación generar `strategies/strategy_primera_estrategia.py` con la configuración completa de la estrategia recibida.

## Technical context
- La estrategia resultante debe respetar el aislamiento: no importa `config`, `trading` ni `gui_charts`
- `get_last_signal` devuelve `"buy"` solo cuando ADX > 25 Y (+DI cruza por encima de -DI)
- `get_last_signal_payload` debe incluir los campos de piramidado y sizing (según specs TASK-020 y TASK-021)
- La estrategia es long-only: nunca devuelve `"sell"`
- El archivo generado debe ser sintácticamente válido (`ast.parse` no lanza error)
- El companion `.json` se escribe junto al `.py`

## Acceptance criteria
- [ ] `strategies/builder.py` soporta `"ADX"` como nuevo `VALID_INDICATOR_ID`
- [ ] `prepare_dataframe` generada computa `adx_14`, `plus_di_14`, `minus_di_14` correctamente (Wilder smoothing)
- [ ] El emitter de cruce genera código Python correcto para la condición de cruce entre velas consecutivas
- [ ] `strategy_primera_estrategia.py` generado y sintácticamente válido
- [ ] `strategy_primera_estrategia.json` companion escrito junto al `.py`
- [ ] La estrategia devuelve `"buy"` en condiciones correctas y `"none"` en el resto; nunca devuelve `"sell"`
- [ ] `get_last_signal_payload` incluye todos los campos de piramidado y sizing especificados por Daniel
