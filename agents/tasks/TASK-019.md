# TASK-019: ADX+DI — catálogo, columnas y modelo de cruce

- **ID**: TASK-019
- **Priority**: P1
- **Status**: done
- **Assigned**: Daniel
- **Blocked by**: nada
- **Blocks**: TASK-025

## Files to read
- `agents/daniel.md` — tu definición de rol y workflow
- `agents/context.md` — contexto del proyecto
- `agents/specs/TASK-014a-indicator-catalogue.md` — catálogo existente (añadir entradas ADX)
- `agents/specs/TASK-014b-condition-tree-model.md` — modelo de condición (evaluar extensión para cruces)
- `strategies/builder.py` — ver `VALID_INDICATOR_IDS`, `ALWAYS_AVAILABLE_COLUMNS`, lógica del emitter

## Description
ADX (Average Directional Index) y sus componentes +DI y -DI no están en el catálogo de indicadores. La condición de entrada de la estrategia usa un *cruce* de +DI por encima de -DI, que el `ConditionNode` actual no puede representar (solo compara valores puntuales). Daniel debe: (1) especificar ADX/+DI/-DI como nuevos indicadores del catálogo, y (2) diseñar cómo extender el modelo de condición para soportar cruces de dos columnas entre velas consecutivas.

## Technical context
- Fórmulas estándar ADX (Wilder, 14 períodos): True Directional Movement (+DM, -DM), True Range, suavizado EWM, +DI = 100×EWM(+DM)/ATR, -DI = 100×EWM(-DM)/ATR, DX = 100×|+DI−-DI|/(+DI+-DI), ADX = EWM(DX)
- Columnas a definir: `adx_<period>`, `plus_di_<period>`, `minus_di_<period>` (convenio a confirmar)
- El cruce `+DI cruza por encima de -DI` equivale a: `df.iloc[-2]["plus_di_14"] > df.iloc[-2]["minus_di_14"]` AND `df.iloc[-3]["plus_di_14"] <= df.iloc[-3]["minus_di_14"]` — esto requiere usar `df.iloc[-3]`, que el emitter actual no expone
- Opciones a evaluar: (A) nuevo tipo de nodo `"crossover"` en el ConditionNode, (B) columna booleana derivada `plus_di_cross_<period>` computada en `prepare_dataframe`, (C) combinación de dos hojas con `df.iloc[-2]` y `df.iloc[-3]`
- Output: `agents/specs/TASK-019-adx-di-crossover-spec.md`

## Acceptance criteria
- [ ] Fórmulas de ADX, +DI y -DI especificadas con precisión (método de suavizado, lookback mínimo de datos)
- [ ] Nombres de columna canónicos definidos (`adx_<period>`, `plus_di_<period>`, `minus_di_<period>` o alternativa justificada)
- [ ] Las tres columnas añadidas a la tabla de la sección 3 del catálogo (requieren `prepare_dataframe`)
- [ ] Opción seleccionada para representar el cruce en el modelo de condición, con justificación
- [ ] Pseudocódigo del emitter de Python para la opción seleccionada
- [ ] Restricción de lookback documentada: cuántas velas históricas mínimas necesita ADX para ser fiable con período=14
- [ ] `agents/specs/TASK-019-adx-di-crossover-spec.md` creado y autosuficiente para que Felix implemente TASK-025
