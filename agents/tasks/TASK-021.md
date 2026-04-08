# TASK-021: Sizing dinámico y control de riesgo por ticker

- **ID**: TASK-021
- **Priority**: P1
- **Status**: done
- **Assigned**: Daniel
- **Blocked by**: nada
- **Blocks**: TASK-022, TASK-024

## Files to read
- `agents/daniel.md` — tu definición de rol y workflow
- `agents/context.md` — contexto del proyecto
- `trading.py` — `_send_order`, `apply_signal`, `normalize_volume`
- `config.py` — `LOT`, `SL_POINTS`, `TP_POINTS`
- `agents/specs/TASK-014a-indicator-catalogue.md` — ver `volume_ratio_<lookback>` existente
- `primeraEstrategia.md` — estrategia de referencia

## Description
El bot usa `config.LOT` fijo para todas las operaciones. La estrategia requiere tamaño dinámico: `lot = (tick_volume_actual / SMA_volumen_20) × 0.5%`, con techo en `1% del balance`. Antes de abrir cualquier entrada debe verificarse que el riesgo agregado simultáneo no supere el 3% del balance. Daniel diseña los algoritmos de cálculo de lot dinámico y verificación de riesgo agregado.

## Technical context
- **Base de cálculo (decisión cerrada)**: usar `account_info().balance`, NO equity flotante. Evita que el P&L no realizado afecte el sizing de nuevas entradas.
- El volumen actual es `df.iloc[-2]["tick_volume"]`; la SMA de 20 períodos del volumen puede reutilizar `volume_ratio_<lookback>` del catálogo o necesitar un concepto distinto — Daniel decide
- El "riesgo por entrada" = `lot × (precio_entrada − SL) / valor_por_punto`; necesita `contract_size` y `tick_value` de `mt5.symbol_info()`
- El "riesgo agregado" = suma del riesgo actual de todas las posiciones abiertas de esta estrategia + riesgo de la nueva entrada
- Constraint de aislamiento: el sizing no puede calcularse dentro de la estrategia. Daniel debe especificar qué datos pasa la estrategia al caller via `get_last_signal_payload`
- Output: `agents/specs/TASK-021-dynamic-sizing-risk-spec.md`

## Acceptance criteria
- [ ] Fórmula de lot dinámico con unidades explícitas: cómo convertir `(vol_ratio × 0.5% × balance)` a lotes MT5 — usar `balance`, no `equity`
- [ ] Fórmula de riesgo por entrada (en dinero y en % de balance) con precisión — usar `balance`
- [ ] Algoritmo de verificación de riesgo agregado: riesgo actual de posiciones abiertas + nueva entrada vs. 3% del balance
- [ ] Qué campos nuevos debe incluir `get_last_signal_payload` para que el caller calcule el lot y verifique el riesgo
- [ ] Decisión sobre si el techo del 1% se aplica por entrada o por estrategia total, con justificación
- [ ] Riesgos de precisión numérica documentados (redondeo de lotes, casos extremos)
- [ ] `agents/specs/TASK-021-dynamic-sizing-risk-spec.md` creado, autosuficiente para que Felix implemente TASK-024
