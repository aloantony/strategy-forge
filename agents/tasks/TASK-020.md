# TASK-020: Piramidado — algoritmo de detección y ejecución

- **ID**: TASK-020
- **Priority**: P1
- **Status**: done
- **Assigned**: Daniel
- **Blocked by**: nada
- **Blocks**: TASK-022, TASK-023

## Files to read
- `agents/daniel.md` — tu definición de rol y workflow
- `agents/context.md` — contexto del proyecto
- `trading.py` — funciones `apply_signal`, `get_open_position_direction`, `get_position_info`, `_send_order`
- `main.py` — bucle principal y llamadas a `apply_signal`
- `config.py` — `LOT`, `SL_POINTS`, `TP_POINTS` actuales
- `primeraEstrategia.md` — estrategia de referencia

## Description
El bot actual abre una única posición por señal con lot fijo. La estrategia requiere entradas piramiadas: si ya hay una posición abierta para esta estrategia y el precio ha avanzado 0.5×ATR desde el precio de la última entrada, se abre una nueva posición independiente con su propio SL (entrada − 1×ATR) y TP (entrada + 2×ATR). Daniel diseña el algoritmo completo de detección de condición de piramidado y especifica los cambios mínimos necesarios en `trading.py`.

## Technical context
- `apply_signal()` firma actual: `(symbol, signal, lot, sl_points, tp_points, magic_number, strategy_key, strategy_label, signal_reason)` — devuelve dict con acciones realizadas o None
- `get_position_info()` devuelve solo la primera posición encontrada por magic_number; el piramidado requiere múltiples posiciones simultáneas bajo el mismo magic_number
- Problema de diseño clave: cómo identificar la entrada más reciente (por `price_open` más alto en longs, o por `time` de apertura)
- Constraint de aislamiento: la estrategia no puede importar `trading` — la detección de piramidado debe ocurrir en el caller (main.py o capa de ejecución)
- **Magic number (decisión cerrada)**: todas las entradas piramiadas comparten el mismo magic number. Simplifica la consulta de posiciones y es coherente con el comment string encoding.
- Output: `agents/specs/TASK-020-pyramiding-spec.md`

## Acceptance criteria
- [ ] Algoritmo de detección de condición de piramidado especificado paso a paso
- [ ] Decisión sobre extender `apply_signal()` vs. crear `apply_pyramid_signal()` con justificación — sin cambiar comportamiento de estrategias sin piramidado
- [ ] Cómo `get_position_info` evoluciona para soportar múltiples posiciones bajo un mismo magic_number
- [ ] Cómo la estrategia generada comunica al caller que quiere ejecutar una entrada piramiada
- [ ] SL y TP del piramidado: especificados como precio absoluto (dependen del ATR en el momento de cada entrada)
- [ ] Spec especifica explícitamente que todas las entradas piramiadas usan el mismo magic number
- [ ] `agents/specs/TASK-020-pyramiding-spec.md` creado, autosuficiente para que Felix implemente TASK-023
