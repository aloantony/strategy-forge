# TASK-043: GUI spec — panel "Quick Params" por estrategia

- **ID**: TASK-043
- **Priority**: P1
- **Status**: done
- **Assigned**: Grace
- **Blocked by**: TASK-042
- **Blocks**: TASK-044

## Files to read

- `agents/grace.md` — tu definición de rol y workflow
- `agents/context-core.md` — contexto del proyecto
- `agents/specs/TASK-042-params-schema-spec.md` — spec de Daniel (backend): schema de PARAMS, formato de params_schema/params_values en el registry entry, y qué campos llegan en el payload de estrategia
- `gui_charts.py` — secciones relevantes (leer antes de especificar nada):
  - `_get_strategy_payload()` (~L647-703) — construye el payload de cada estrategia
  - `_render_strategy_panel()` (~L1833-1859) — renderiza la lista de estrategias
  - `window.renderBuilderButtons()` (~L2135-2155) — añade botones "Editar" (solo si `has_config`)
  - `window.renderStrategyList()` (~L5474-5569) — renderiza filas DOM de cada estrategia
  - `on_side_panel_event()` (~L5945-6009) — dispatcher de eventos JS→Python
  - `_on_strategy_builder_open()` (~L6053-6102) — patrón de referencia: cómo se lee .json y se abre un panel
  - `_on_strategy_builder_save()` (~L6288-6356) — patrón de referencia: cómo se guarda y recarga

## Description

Diseñar la spec completa de GUI para el panel de edición rápida de parámetros de estrategia ("Quick Params"). Grace NO modifica código. Produce una spec precisa para Felix.

## Technical context

### Comportamiento esperado

Para cada estrategia en la lista:
- Si `params_schema` existe (Builder-generated o manual con `PARAMS`): mostrar botón "Params" en la fila
- Si no: comportamiento idéntico al actual

Flujo al hacer click en "Params":
1. JS envía evento `strategy_params_open;;;{key}` → Python
2. Python lee `params_schema` y `params_values` del registry entry
3. Python llama `window.openParamsPanel(payload)` con JSON del schema y valores actuales
4. Modal/panel se abre con inputs numéricos (int/float) para cada param
5. Usuario edita → Save → JS envía `strategy_params_save;;;{key};;;{json_de_overrides}` → Python
6. Python guarda (Track A: actualiza .json + regenera .py; Track B: escribe .params.json)
7. Python muestra confirmación en UI: "Parámetros guardados. Se aplicarán en el próximo ciclo."

### Tipos de input en v1
Solo `int` y `float` — inputs numéricos con min/max/step. No hay checkboxes ni dropdowns en esta iteración.

### Constraint de seguridad
- Los `.py` manuales NUNCA se tocan
- El botón "Editar" existente (abre Builder completo) no se elimina — sigue disponible para Builder-generated
- El botón "Params" es ADICIONAL al "Editar" para Builder-generated, y el ÚNICO para manuales con PARAMS

### Patrón de referencia para el evento JS→Python
```javascript
// Botón "Editar" (existente, línea ~2150):
window.callbackFunction(handler + "_~_strategy_builder_open;;;" + key);

// Nuevo botón "Params" (a diseñar):
window.callbackFunction(handler + "_~_strategy_params_open;;;" + key);
```

### Patrón de referencia para Python→JS con JSON
```python
# Patrón establecido (ver _on_strategy_builder_open):
payload = json.dumps({...})
window.openParamsPanel(payload)  # nuevo JS function
```

## Acceptance criteria

- [ ] Spec producida en `agents/specs/TASK-043-quick-params-gui-spec.md`
- [ ] Spec incluye sección `## Backend Summary` (≤15 líneas) con los campos que llegan en el payload
- [ ] Spec define el punto exacto de inserción del botón "Params" en `renderBuilderButtons()` o equivalente, con línea de referencia y landmark
- [ ] Spec define `_on_strategy_params_open(key)`: qué lee del registry, qué JSON construye, cómo llama a `window.openParamsPanel()`
- [ ] Spec define `_on_strategy_params_save(key, overrides_json)`: lógica de guardado Track A (Builder) vs Track B (manual), confirmación en UI
- [ ] Spec define `window.openParamsPanel(payload)`: estructura del modal, cómo genera inputs dinámicamente desde el schema, botón Save, botón Cancel
- [ ] Spec define `window.closeParamsPanel()`: cómo desmonta el modal
- [ ] Spec verifica threading: `_on_strategy_params_save` puede llamar `chart.run_script()` para mostrar confirmación — ¿desde qué thread se invoca? Grace debe confirmarlo y especificar el patrón correcto
- [ ] Spec documenta idempotencia: si el usuario abre el panel dos veces, el DOM no se duplica
- [ ] Spec no elimina ni modifica el flujo "Editar" existente
