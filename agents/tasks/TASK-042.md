# TASK-042: PARAMS schema, merge logic y params injection en main.py

- **ID**: TASK-042
- **Priority**: P1
- **Status**: done
- **Assigned**: Daniel
- **Blocked by**: —
- **Blocks**: TASK-043, TASK-044

## Files to read

- `agents/daniel.md` — tu definición de rol y workflow
- `agents/context-core.md` — contexto del proyecto
- `main.py` — `_load_strategy_module()` (~L106-131), `_analyze_strategy()` (~L381-402), `runtime_get_strategy_signal_payload()`, `load_active_strategies()`
- `strategy_builder/generator.py` — `render_strategy_source()` (~L89-143), `_emit_module_constants()` (~L518-558)
- `strategies/strategy_primera_estrategia.py` — ejemplo de estrategia Builder-generated con constantes embebidas
- `strategies/strategy_primera_estrategia.json` — companion JSON, fuente de verdad de params

## Description

Diseñar el mecanismo de parámetros editables para estrategias. El resultado es una spec formal (pseudocode) para dos implementadores:
1. **main.py** — detección de PARAMS, carga de overrides, inyección via kwargs
2. **generator.py** — emisión de bloque PARAMS en `.py` generados (documental/compatible)

Daniel NO implementa código. Produce pseudocode preciso que Felix implementará en TASK-044.

## Technical context

### Constraint crítico
Los `.py` manuales NUNCA se escriben. Los `.py` Builder-generated pueden regenerarse via el generador (patrón establecido). Cuando el usuario edita params de una estrategia Builder, se actualiza el `.json` → se regenera el `.py` completo.

### Dos tracks

**Track A — Builder-generated (tiene `.json` companion)**
- Los parámetros de indicadores ya viven en `.json` bajo `indicators[].params`
- Editar → actualizar `.json` → `generate_strategy_file()` → `.py` regenerado
- El `.py` recargado en el siguiente tick via `importlib.reload` (ya existe en main.py)
- Daniel no necesita diseñar el guardado (eso es GUI, TASK-043). Solo el reload mechanism.

**Track B — Manual (`.py` sin `.json`, con `PARAMS` dict declarado)**

El autor declara voluntariamente en su `.py`:
```python
PARAMS = {
    "atr_period": {"label": "ATR Period", "type": "int", "default": 14, "min": 1, "max": 200},
}
```

El sistema:
1. Lee `getattr(module, "PARAMS", None)` al cargar el módulo — READONLY
2. Sobreescrituras del usuario se guardan en `.params.json` companion (mismo dir que el `.py`)
3. Engine detecta via `inspect.signature` si `get_last_signal` acepta kwarg `params`
4. Si acepta: llama con `params=merged_params` donde `merged_params` = defaults de PARAMS + overrides de `.params.json`
5. Si no acepta: comportamiento idéntico al actual — cero impacto en estrategias existentes

### Schema de PARAMS (punto de partida para Daniel)
Tipos soportados en v1: `"int"` y `"float"` únicamente. Campos:
- `label`: string — nombre para mostrar en GUI
- `type`: `"int"` | `"float"`
- `default`: valor por defecto (mismo tipo)
- `min`: mínimo permitido
- `max`: máximo permitido

### Relay en main.py
El entry de estrategia en `strategy_registry` (o la estructura interna de `main.py`) debe almacenar:
- `params_schema`: el dict `PARAMS` del módulo (o None si no existe)
- `params_values`: los valores actuales (merged defaults + overrides)

Esto es necesario para que la GUI pueda leer los params actuales al abrir el panel.

## Acceptance criteria

- [ ] Spec producida en `agents/specs/TASK-042-params-schema-spec.md`
- [ ] La spec define el schema exacto de `PARAMS` con tipos y validaciones
- [ ] La spec define `_load_strategy_params(module, strategy_key, strategies_dir) -> dict` en pseudocode — merge de defaults + `.params.json`
- [ ] La spec define cómo `_load_strategy_module()` extrae y almacena `params_schema` y `params_values` en el entry
- [ ] La spec define cómo `_analyze_strategy()` detecta si `get_last_signal` acepta `params` kwarg y lo pasa
- [ ] La spec define qué emite `generator.py` para el bloque `PARAMS` en Builder-generated strategies (derivado de `indicators[].params`)
- [ ] La spec documenta el comportamiento ante módulo sin `PARAMS`: sin cambios respecto al comportamiento actual
- [ ] La spec documenta el comportamiento ante módulo con `PARAMS` pero función sin kwarg `params`: sin cambios
