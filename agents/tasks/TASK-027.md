# TASK-027: Extender resultado de run_backtest con equity_curve, drawdown_curve y métricas adicionales

- **ID**: TASK-027
- **Priority**: P1
- **Status**: done
- **Assigned**: Daniel
- **Blocked by**: nada
- **Blocks**: TASK-028

## Files to read
- `agents/daniel.md` — tu definición de rol y workflow
- `agents/context.md` — contexto del proyecto
- `backtesting/runtime.py` — motor de backtest actual; prestar atención a `BacktestEngine`, `_mark_equity`, `_build_success_result`, y `equity_curve`

## Description

`BacktestEngine` ya construye `self.equity_curve` (lista de `{"time": epoch, "equity": float, "balance": float}`) durante la ejecución pero `_build_success_result` no la incluye en el dict de retorno. La GUI necesita estos datos para renderizar curva de equity, curva de drawdown y métricas adicionales. Daniel debe especificar exactamente qué añadir al resultado y cómo derivar la curva de drawdown desde la equity_curve existente.

## Technical context

- Relevant files: `backtesting/runtime.py`
- Relevant functions/classes: `BacktestEngine._build_success_result` (línea ~524), `BacktestEngine._mark_equity` (línea ~224), `BacktestEngine.equity_curve` (lista construida en ejecución)
- `equity_curve` actual: lista de dicts `{"time": int (epoch UTC), "equity": float, "balance": float}` — uno por cada vela visible procesada
- `closed_trades` ya existe como `self.closed_trades` pero el resultado solo expone el conteo (`closed_trades: int`), no la lista completa. La lista completa ya está en `_build_success_result` bajo clave `"trades"` (línea ~551).
- Restricción crítica: el resultado se serializa a JSON en `gui_charts.py` vía `json.dumps`. Todos los campos nuevos deben ser tipos JSON-nativos (int, float, str, list, dict). No datetime, no pd.Timestamp.
- Restricción de tamaño: **DECISIÓN CERRADA (2026-04-11)** — no hay downsampling. La `equity_curve` contiene exactamente 1 punto por vela procesada. M1/1 año → ~250k puntos; H1/1 año → ~6k puntos. La GUI recibe todos los puntos sin reducción.

### DECISIÓN CERRADA — Fuente de datos para backtesting (2026-04-11)

**Dukascopy es la fuente histórica primaria.** MT5 sigue siendo el feed de live trading únicamente.

- Dukascopy provee tick data gratuito del DAX (GER.IDX/EUR) desde ~2003, resampleable a cualquier timeframe OHLCV con la librería `dukascopy-python`. No hay dependencia de APIs de pago ni créditos gratuitos.
- El motor en `backtesting/runtime.py` recibirá datos ya preprocesados (OHLCV DataFrame). No llamará directamente a `mt5.copy_rates_range()`.
- **Arquitectura DataProvider** — interfaz Protocol ya decidida:
  ```python
  class DataProvider(Protocol):
      def get_rates_df(self, symbol: str, timeframe: str,
                       start: datetime, end: datetime) -> pd.DataFrame: ...
  ```
  Implementaciones: `MT5Provider` (live), `DukascopyProvider` (backtest histórico), `FileProvider` (parquet/CSV cacheado). El motor recibe un provider inyectado.
- Fuentes descartadas: Twelve Data (coste + créditos), yfinance (7 días M1 máximo), Tiingo (solo US), Polygon.io (no DAX).
- **Daniel no debe reinventar esta decisión.** La spec de TASK-027 debe asumir que los datos llegan como DataFrame estándar OHLCV, sin importar la fuente.

### DECISIÓN CERRADA — Modelo de ejecución dentro de la vela (2026-04-11)

Señal generada al cierre de vela N → ejecución intentada en vela N+1. Lógica de fill y SL/TP:

```python
# ENTRADA
if pending_buy and next['low'] <= buy_price:
    fill_price = min(next['open'], buy_price)   # gap-down: se llena al open
    execute_buy(fill_price)

if pending_sell and next['high'] >= sell_price:
    fill_price = max(next['open'], sell_price)  # gap-up: se llena al open
    execute_sell(fill_price)

# SL/TP en posición abierta
# Si ambos se tocan en la misma vela: SL primero (conservador, sin sesgo optimista)
if position_long:
    if next['low'] <= sl_price:
        close_position(sl_price)
    elif next['high'] >= tp_price:
        close_position(tp_price)
```

**Daniel no debe reinventar este modelo.** La spec de TASK-027 debe implementarlo verbatim. El criterio "SL primero cuando ambos se tocan" es intencional y no está sujeto a revisión.

## What Daniel must produce

Un spec en `agents/specs/TASK-027-backtest-result-extension.md` que incluya:

1. **Lista exacta de campos nuevos** a añadir en `_build_success_result`, con tipo y descripción de cada uno.
2. **Derivación de `drawdown_curve`**: si se calcula on-the-fly desde `equity_curve` o si se añade tracking en `_mark_equity`. Formato del array resultante (campos por punto).
3. ~~**Decisión sobre downsampling**~~: **RESUELTA (2026-04-11) — no hay downsampling**. La GUI recibe todos los puntos (1 por vela). Daniel no necesita incluir criterio de submuestreo en la spec.
4. **Métricas adicionales opcionales** a evaluar: Profit Factor (`gross_wins / gross_losses`), Average Win, Average Loss, Expectancy (`win_rate * avg_win - loss_rate * avg_loss`). Daniel decide cuáles incluir con justificación.
5. **Pseudocode del cambio** en `_build_success_result` — suficientemente detallado para que Felix lo implemente verbatim sin decisiones de diseño.

## Acceptance criteria
- [ ] Spec existe en `agents/specs/TASK-027-backtest-result-extension.md`
- [ ] Spec define el formato completo del campo `equity_curve` tal como aparecerá en el resultado
- [ ] Spec define el campo `drawdown_curve` con su formato y método de cálculo
- [x] ~~Spec toma una decisión explícita sobre downsampling con criterio cuantitativo~~ — RESUELTA por usuario (2026-04-11): no hay downsampling; 1 punto por vela, todos los puntos se envían a la GUI
- [ ] Spec incluye pseudocode de los cambios en `_build_success_result` y/o `_mark_equity`
- [ ] Spec define al menos Profit Factor y Expectancy como campos nuevos (o justifica su exclusión)
- [ ] Ningún campo nuevo introduce tipos no-JSON-serializables

---

### DECISIÓN CERRADA 5 — Arquitectura de providers y símbolo canónico (2026-04-11)

**Problema**: El motor de backtest estaba acoplado a MT5 para obtener histórico Y metadatos del instrumento (`point`, `tick_size`, `tick_value`). MT5 no debe ser la base del diseño — como mucho, un adapter opcional.

#### Símbolo canónico interno

El sistema usa nombres internos canónicos independientes de cualquier provider. Cada provider tiene su propio mapa de traducción:
- Canónico: `GER40`
- MT5: `#Germany40`
- Dukascopy: `DEU.IDX/EUR`

#### Roles de cada provider

- **Parquet/CSV local**: fuente por defecto del backtest. Sin llamadas online en cada ejecución.
- **Dukascopy**: fuente externa gratuita principal para descarga y refresco de histórico.
- **MT5**: adapter opcional. Valor para compatibilidad o contraste, no como fuente maestra.

#### Metadatos del instrumento (opción C — híbrido)

Los metadatos (`point`, `tick_size`, `tick_value`) viven en el registro canónico como valores por defecto. Un provider puede sobreescribirlos si los conoce. Estructura del registro:

```python
"GER40": {
    "point": 1.0,
    "tick_size": 1.0,
    "tick_value": 1.0,
    "providers": {
        "mt5": "#Germany40",
        "dukascopy": "DEU.IDX/EUR"
    }
}
```

#### Caché local por provider

Los datos descargados se almacenan localmente en parquet/CSV, separados por provider. No se mezclan datos de distintas fuentes. El backtest lee siempre del archivo local correspondiente.

#### UI

La interfaz siempre muestra qué provider se usó para el backtest, porque los resultados varían según la fuente.

#### Qué debe hacer Daniel en su spec

- Definir el protocolo `DataProvider` completo: `get_rates_df()` + `get_instrument_info()` (para metadatos)
- Especificar la estructura del registro canónico de símbolos
- Especificar la lógica de resolución: registro canónico como fallback, provider override si disponible
- Identificar todos los puntos en `backtesting/runtime.py` y `trading.py` donde se llama a MT5 para metadatos (`symbol_info`, `point`, `tick_size`, `tick_value`) y especificar cómo se reemplazan
- Especificar la estructura de caché local (directorio, naming convention por provider y símbolo)
- Especificar el campo de provider en el resultado del backtest (para que la GUI lo muestre)

No hay riesgos de seguridad: el registro es un archivo local de configuración, sin input de usuario ni ejecución de código externo.

**Daniel no debe reinventar esta decisión.** La spec de TASK-027 debe asumir esta arquitectura y especificar los cambios en los puntos de acceso a metadatos verbatim.

---

### DECISIÓN CERRADA 3 — Eliminar indicadores hardcodeados del motor de backtest (2026-04-11)

**Problema**: `backtesting/runtime.py` líneas 88-102 aplica siempre `add_baseline_bands`, `add_supertrend` y `add_tci` al DataFrame antes de pasárselo a la estrategia, independientemente de si la estrategia los necesita.

**Decisión**: El motor de backtest no debe añadir ningún indicador al DataFrame base. La preparación del DataFrame es responsabilidad exclusiva de cada estrategia via su método `prepare_dataframe(df)`. El motor solo entrega OHLCV + columnas derivadas estándar (las que ya añade `data_feed.add_source_columns`).

**Qué debe especificar Daniel**:
- Especificar la eliminación de las tres llamadas hardcodeadas (`add_baseline_bands`, `add_supertrend`, `add_tci`) del pipeline de preparación del motor (líneas 88-102 de `backtesting/runtime.py`)
- Confirmar que `apply_strategy_processing` en `strategy_runtime.py` ya llama a `prepare_dataframe` del módulo de estrategia (lo hace — líneas 65-68) — por lo tanto no hay nada que añadir al motor, solo eliminar las tres llamadas
- Documentar en la spec qué columnas garantiza el motor como "siempre presentes" en el DataFrame que recibe la estrategia: OHLCV + columnas de `data_feed.add_source_columns`

**Daniel no debe reinventar esta decisión.** La spec de TASK-027 debe asumir este contrato de columnas garantizadas y especificar la eliminación de las tres llamadas verbatim.

---

### DECISIÓN CERRADA 4 — Parametrizar las reglas de ejecución avanzada (2026-04-11)

**Problema**: `_open_advanced_buy()` en `backtesting/runtime.py` tiene hardcodeados los parámetros de ejecución de la primera estrategia:
- SL = `entry_price - 1×atr_value`
- TP = `entry_price + 2×atr_value`
- Umbral de piramidado = `last_entry + 0.5×atr_value`
- Solo longs (`direction=1`)

Si una segunda estrategia usa piramidado con multiplicadores distintos, el motor aplicaría los de la primera estrategia igualmente.

**Decisión**: Los multiplicadores deben venir en el payload de la señal. El motor los lee del payload y no asume ningún valor por defecto más allá de lo que la estrategia declare. Payload extendido:

```python
{
    "signal": "buy",
    "pyramiding": True,
    "atr_value": 150.0,
    "sl_atr_mult": 1.0,      # la estrategia decide
    "tp_atr_mult": 2.0,      # la estrategia decide
    "pyramid_atr_mult": 0.5  # la estrategia decide
}
```

**Qué debe especificar Daniel en su spec**:
- Especificar los tres nuevos campos del payload (`sl_atr_mult`, `tp_atr_mult`, `pyramid_atr_mult`)
- Especificar que `_open_advanced_buy` los lee del payload en lugar de usar literales
- Especificar cómo actualizar `normalize_signal_payload` en `strategy_runtime.py` para incluir y validar los tres nuevos campos (valores por defecto razonables si la estrategia no los declara: 1.0, 2.0, 0.5 respectivamente — compatibilidad con la primera estrategia existente)
- Confirmar que `strategy_runtime.py` es el único punto donde se normaliza el payload (lo es)

**Daniel no debe reinventar esta decisión.** La spec de TASK-027 debe especificar estos cambios verbatim.
