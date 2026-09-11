# Strategy Forge — https://github.com/aloantony/strategy-forge
# Required Notice: Copyright 2026 aloantony (https://github.com/aloantony)
# Licensed under the PolyForm Noncommercial License 1.0.0 — see LICENSE, or
# <https://polyformproject.org/licenses/noncommercial/1.0.0>. Noncommercial use
# is free; commercial use, including production use, requires a written
# agreement with the copyright holder.

"""
backend/strategy_builder/indicators.py — Registry único de indicadores del Builder.

Única fuente de verdad para todo lo que antes estaba cuadruplicado entre
generator.py (emisores if/elif), mtf_generator.py (subset ATR/VORTEX con helpers
divergentes), builder_service.py (catálogo con labels) y el JS de gui_charts:

- params de cada indicador (key/tipo/default/min/max/step + labels en español)
- plantillas de columnas generadas y sus etiquetas humanas
- líneas de cómputo emitidas en el código generado y helpers que requieren
- constantes de módulo, entradas del bloque PARAMS y campos de Data Window
- rol de overlay en el gráfico (trend/bands/supertrend/tci)

Convención de plantillas: "{period}", "{lookback}" y "{multiplier}" se interpolan
con los params de la instancia. Los helpers son funciones puras embebidas en el
.py generado (las estrategias son standalone: solo importan pandas).
"""

# ---------------------------------------------------------------------------
# Helpers embebidos en el código generado (un solo set, compartido v1/MTF).
# ATR unificado en suavizado Wilder (ewm) — la variante rolling que usaba el
# generador MTF v2 queda retirada; los .py ya generados no cambian hasta re-guardar.
# ---------------------------------------------------------------------------

HELPER_TEMPLATES = {
    "_numeric": """\
def _numeric(df: pd.DataFrame, key: str) -> pd.Series:
    return pd.to_numeric(df.get(key), errors="coerce")""",

    "_volume_series": """\
def _volume_series(df: pd.DataFrame) -> pd.Series:
    if "tick_volume" in df.columns:
        return pd.to_numeric(df.get("tick_volume"), errors="coerce")
    if "volume" in df.columns:
        return pd.to_numeric(df.get("volume"), errors="coerce")
    return pd.Series(1.0, index=df.index, dtype="float64")""",

    "_rsi": """\
def _rsi(close: pd.Series, length: int) -> pd.Series:
    delta    = close.diff()
    gain     = delta.clip(lower=0.0)
    loss     = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / length, min_periods=length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / length, min_periods=length, adjust=False).mean()
    rs       = avg_gain / avg_loss.replace(0.0, float("nan"))
    return 100.0 - (100.0 / (1.0 + rs))""",

    "_atr": """\
def _atr(high: pd.Series, low: pd.Series, close: pd.Series, length: int) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low,
         (high - prev_close).abs(),
         (low  - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1.0 / length, min_periods=length, adjust=False).mean()""",

    "_intraday_vwap": """\
def _intraday_vwap(df: pd.DataFrame,
                   high: pd.Series, low: pd.Series,
                   close: pd.Series, volume: pd.Series) -> pd.Series:
    typical_price  = (high + low + close) / 3.0
    weighted_price = typical_price * volume
    if "time" in df.columns:
        session_key = pd.to_datetime(df["time"], utc=True, errors="coerce").dt.floor("D")
    else:
        session_key = pd.Series(0, index=df.index)
    cum_wp  = weighted_price.groupby(session_key).cumsum()
    cum_vol = volume.groupby(session_key).cumsum().replace(0.0, float("nan"))
    return cum_wp / cum_vol""",

    "_adx_di": """\
def _adx_di(high: pd.Series, low: pd.Series, close: pd.Series, length: int):
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low,
         (high - prev_close).abs(),
         (low  - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    up_move   = high - high.shift(1)
    down_move = low.shift(1) - low
    import numpy as _np
    plus_dm  = pd.Series(_np.where((up_move > down_move) & (up_move > 0),   up_move,   0.0), index=high.index)
    minus_dm = pd.Series(_np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=high.index)
    alpha = 1.0 / length
    kw = {"alpha": alpha, "min_periods": length, "adjust": False}
    atr_w     = tr.ewm(**kw).mean()
    safe_atr  = atr_w.replace(0.0, float("nan"))
    plus_di   = 100.0 * plus_dm.ewm(**kw).mean()  / safe_atr
    minus_di  = 100.0 * minus_dm.ewm(**kw).mean() / safe_atr
    di_sum    = (plus_di + minus_di).replace(0.0, float("nan"))
    dx        = 100.0 * (plus_di - minus_di).abs() / di_sum
    adx       = dx.ewm(**kw).mean()
    pprev, mprev = plus_di.shift(1), minus_di.shift(1)
    plus_cross  = ((plus_di  > minus_di) & (pprev <= mprev)).astype(int)
    minus_cross = ((minus_di > plus_di)  & (mprev <= pprev)).astype(int)
    return adx, plus_di, minus_di, plus_cross, minus_cross""",

    "_vortex": """\
def _vortex(high: pd.Series, low: pd.Series, close: pd.Series, length: int):
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low).abs(),
         (high - prev_close).abs(),
         (low  - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    vm_plus  = (high - low.shift(1)).abs()
    vm_minus = (low  - high.shift(1)).abs()
    tr_sum   = tr.rolling(length).sum().replace(0.0, float("nan"))
    vi_plus  = vm_plus.rolling(length).sum() / tr_sum
    vi_minus = vm_minus.rolling(length).sum() / tr_sum
    direction = pd.Series(-1, index=high.index, dtype="int64").mask(vi_plus > vi_minus, 1)
    cross_up = ((vi_plus > vi_minus) & (vi_plus.shift(1) <= vi_minus.shift(1))).astype(int)
    cross_down = ((vi_minus > vi_plus) & (vi_minus.shift(1) <= vi_plus.shift(1))).astype(int)
    return vi_plus, vi_minus, direction, cross_up, cross_down""",
}

# Orden de emisión de helpers en el fichero generado (estable).
HELPER_ORDER = ["_numeric", "_volume_series", "_rsi", "_atr", "_intraday_vwap", "_adx_di", "_vortex"]


# ---------------------------------------------------------------------------
# Specs de indicadores.
#
# Campos por spec:
#   label / description    — etiquetas humanas (catálogo del Builder)
#   pre_computed           — True si las columnas ya vienen del feed del gráfico
#   params                 — [{key,label,type,default,min,max,step}]
#   columns                — [{template,label}] columnas generadas (templates {param})
#   constants              — plantillas de constantes de módulo
#   params_block           — entradas del dict PARAMS generado
#   compute                — líneas de cómputo (cuerpo de prepare_dataframe, indent 4)
#   helpers                — helpers de HELPER_TEMPLATES que requiere
#   needs                  — series base que usa: subset de {close, high, low, volume}
#   data_window            — [{key,label,format,section}] (templates {param})
#   overlay                — ("trend"|"bands", label_tpl, [(alias, col_tpl)...]) o
#                            ("flag", "supertrend"|"tci") o None
# ---------------------------------------------------------------------------

INDICATOR_SPECS = {
    "EMA": {
        "label": "Media móvil exponencial (EMA)",
        "description": "Media que reacciona rápido a los cambios de precio.",
        "pre_computed": False,
        "params": [{"key": "period", "label": "Período", "type": "int", "default": 9, "min": 2, "max": 500, "step": 1}],
        "columns": [{"template": "ema_{period}", "label": "EMA ({period})"}],
        "constants": ["EMA_{period}_PERIOD = {period}"],
        "params_block": [{"key": "ema_{period}_period", "label": "EMA {period} Period", "type": "int", "value_param": "period", "min": 2, "max": 500}],
        "compute": ["    ema_{period} = close.ewm(span={period}, adjust=False).mean()"],
        "helpers": [],
        "needs": {"close"},
        "data_window": [{"key": "ema_{period}", "label": "EMA ({period})", "format": "price", "section": "Trend"}],
        "overlay": ("trend", "EMA ({period})", [("average", "ema_{period}")]),
    },
    "SMA": {
        "label": "Media móvil simple (SMA)",
        "description": "Media aritmética del precio en N velas.",
        "pre_computed": False,
        "params": [{"key": "period", "label": "Período", "type": "int", "default": 20, "min": 2, "max": 500, "step": 1}],
        "columns": [{"template": "sma_{period}", "label": "SMA ({period})"}],
        "constants": ["SMA_{period}_PERIOD = {period}"],
        "params_block": [{"key": "sma_{period}_period", "label": "SMA {period} Period", "type": "int", "value_param": "period", "min": 2, "max": 500}],
        "compute": ["    sma_{period} = close.rolling({period}, min_periods={period}).mean()"],
        "helpers": [],
        "needs": {"close"},
        "data_window": [{"key": "sma_{period}", "label": "SMA ({period})", "format": "price", "section": "Trend"}],
        "overlay": ("trend", "SMA ({period})", [("average", "sma_{period}")]),
    },
    "RSI": {
        "label": "Índice de fuerza relativa (RSI)",
        "description": "Oscilador 0-100: sobreventa por debajo de 30, sobrecompra por encima de 70.",
        "pre_computed": False,
        "params": [{"key": "period", "label": "Período", "type": "int", "default": 14, "min": 2, "max": 200, "step": 1}],
        "columns": [{"template": "rsi_{period}", "label": "RSI ({period})"}],
        "constants": ["RSI_{period}_PERIOD = {period}"],
        "params_block": [{"key": "rsi_{period}_period", "label": "RSI {period} Period", "type": "int", "value_param": "period", "min": 2, "max": 200}],
        "compute": ["    rsi_{period} = _rsi(close, {period})"],
        "helpers": ["_rsi"],
        "needs": {"close"},
        "data_window": [{"key": "rsi_{period}", "label": "RSI ({period})", "format": "number", "section": "Momentum"}],
        "overlay": None,
    },
    "BB": {
        "label": "Bandas de Bollinger",
        "description": "Bandas de volatilidad alrededor de una media.",
        "pre_computed": False,
        "params": [
            {"key": "period", "label": "Período", "type": "int", "default": 20, "min": 2, "max": 500, "step": 1},
            {"key": "multiplier", "label": "Multiplicador", "type": "float", "default": 2.0, "min": 0.1, "max": 10.0, "step": 0.1},
        ],
        "columns": [
            {"template": "bb_basis_{period}", "label": "Banda media de Bollinger ({period})"},
            {"template": "bb_upper_{period}", "label": "Banda superior de Bollinger ({period})"},
            {"template": "bb_lower_{period}", "label": "Banda inferior de Bollinger ({period})"},
            {"template": "bb_width_pct_{period}", "label": "Anchura de Bollinger % ({period})"},
        ],
        "constants": ["BB_{period}_PERIOD = {period}", "BB_{period}_MULT = {multiplier}"],
        "params_block": [
            {"key": "bb_{period}_period", "label": "BB {period} Period", "type": "int", "value_param": "period", "min": 2, "max": 500},
            {"key": "bb_{period}_mult", "label": "BB {period} Mult", "type": "float", "value_param": "multiplier", "min": 0.1, "max": 10.0},
        ],
        "compute": [
            "    bb_basis_{period}     = close.rolling({period}, min_periods={period}).mean()",
            "    bb_std_{period}       = close.rolling({period}, min_periods={period}).std(ddof=0)",
            "    bb_upper_{period}     = bb_basis_{period} + (bb_std_{period} * {multiplier})",
            "    bb_lower_{period}     = bb_basis_{period} - (bb_std_{period} * {multiplier})",
            "    bb_width_pct_{period} = (bb_upper_{period} - bb_lower_{period}) / bb_basis_{period}.replace(0.0, float('nan'))",
        ],
        "helpers": [],
        "needs": {"close"},
        "data_window": [
            {"key": "bb_basis_{period}", "label": "BB Basis ({period})", "format": "price", "section": "Bollinger"},
            {"key": "bb_upper_{period}", "label": "BB Upper ({period})", "format": "price", "section": "Bollinger"},
            {"key": "bb_lower_{period}", "label": "BB Lower ({period})", "format": "price", "section": "Bollinger"},
            {"key": "bb_width_pct_{period}", "label": "BB Width % ({period})", "format": "percent", "section": "Bollinger"},
        ],
        "overlay": ("bands", "Bollinger Bands ({period})", [
            ("average", "bb_basis_{period}"),
            ("upper", "bb_upper_{period}"),
            ("lower", "bb_lower_{period}"),
        ]),
    },
    "DONCHIAN": {
        "label": "Canal de Donchian",
        "description": "Máximo y mínimo de las últimas N velas (ruptura de rangos).",
        "pre_computed": False,
        "params": [{"key": "period", "label": "Período", "type": "int", "default": 12, "min": 2, "max": 500, "step": 1}],
        "columns": [
            {"template": "donchian_high_{period}", "label": "Canal Donchian superior ({period})"},
            {"template": "donchian_low_{period}", "label": "Canal Donchian inferior ({period})"},
            {"template": "donchian_mid_{period}", "label": "Canal Donchian medio ({period})"},
        ],
        "constants": ["DONCHIAN_{period}_PERIOD = {period}"],
        "params_block": [{"key": "donchian_{period}_period", "label": "Donchian {period} Period", "type": "int", "value_param": "period", "min": 2, "max": 500}],
        "compute": [
            "    donchian_high_{period} = high.rolling({period}, min_periods={period}).max().shift(1)",
            "    donchian_low_{period}  = low.rolling({period}, min_periods={period}).min().shift(1)",
            "    donchian_mid_{period}  = (donchian_high_{period} + donchian_low_{period}) / 2.0",
        ],
        "helpers": [],
        "needs": {"high", "low"},
        "data_window": [
            {"key": "donchian_high_{period}", "label": "Donchian High ({period})", "format": "price", "section": "Donchian"},
            {"key": "donchian_low_{period}", "label": "Donchian Low ({period})", "format": "price", "section": "Donchian"},
            {"key": "donchian_mid_{period}", "label": "Donchian Mid ({period})", "format": "price", "section": "Donchian"},
        ],
        "overlay": ("bands", "Donchian Channel ({period})", [
            ("average", "donchian_mid_{period}"),
            ("upper", "donchian_high_{period}"),
            ("lower", "donchian_low_{period}"),
        ]),
    },
    "ATR": {
        "label": "Rango medio verdadero (ATR)",
        "description": "Mide la volatilidad: cuánto se mueve el precio por vela.",
        "pre_computed": False,
        "params": [{"key": "period", "label": "Período", "type": "int", "default": 14, "min": 1, "max": 200, "step": 1}],
        "columns": [
            {"template": "atr_{period}", "label": "ATR ({period})"},
            {"template": "atr_pct_{period}", "label": "ATR % ({period})"},
        ],
        "constants": ["ATR_{period}_PERIOD = {period}"],
        "params_block": [{"key": "atr_{period}_period", "label": "ATR {period} Period", "type": "int", "value_param": "period", "min": 1, "max": 200}],
        "compute": [
            "    atr_{period}     = _atr(high, low, close, {period})",
            "    atr_pct_{period} = atr_{period} / close.replace(0.0, float('nan'))",
        ],
        "helpers": ["_atr"],
        "needs": {"close", "high", "low"},
        "data_window": [
            {"key": "atr_{period}", "label": "ATR ({period})", "format": "price", "section": "Volatility"},
            {"key": "atr_pct_{period}", "label": "ATR % ({period})", "format": "percent", "section": "Volatility"},
        ],
        "overlay": None,
    },
    "VWAP": {
        "label": "Precio medio ponderado por volumen (VWAP)",
        "description": "Precio medio de la sesión ponderado por volumen.",
        "pre_computed": False,
        "params": [],
        "columns": [{"template": "vwap", "label": "VWAP"}],
        "constants": [],
        "params_block": [],
        "compute": ["    vwap = _intraday_vwap(out, high, low, close, volume)"],
        "helpers": ["_volume_series", "_intraday_vwap"],
        "needs": {"close", "high", "low", "volume"},
        "data_window": [{"key": "vwap", "label": "VWAP", "format": "price", "section": "VWAP"}],
        "overlay": ("trend", "VWAP", [("average", "vwap")]),
    },
    "VOLUME_RATIO": {
        "label": "Ratio de volumen",
        "description": "Volumen actual frente a su media: >1 significa volumen alto.",
        "pre_computed": False,
        "params": [{"key": "lookback", "label": "Velas de referencia", "type": "int", "default": 30, "min": 2, "max": 500, "step": 1}],
        "columns": [{"template": "volume_ratio_{lookback}", "label": "Ratio de volumen ({lookback})"}],
        "constants": ["VOLUME_RATIO_{lookback}_LOOKBACK = {lookback}"],
        "params_block": [{"key": "volume_ratio_{lookback}_lookback", "label": "Volume Ratio {lookback} Lookback", "type": "int", "value_param": "lookback", "min": 2, "max": 500}],
        "compute": [
            "    vol_ma_{lookback}       = volume.rolling({lookback}, min_periods=5).mean()",
            "    volume_ratio_{lookback} = volume / vol_ma_{lookback}.replace(0.0, float('nan'))",
        ],
        "helpers": ["_volume_series"],
        "needs": {"close", "volume"},
        "data_window": [{"key": "volume_ratio_{lookback}", "label": "Volume Ratio ({lookback})", "format": "number", "section": "Volume"}],
        "overlay": None,
    },
    "ADX_DI": {
        "label": "ADX + DI (fuerza de tendencia)",
        "description": "ADX mide la fuerza de la tendencia; DI+ y DI− su dirección.",
        "pre_computed": False,
        "params": [{"key": "period", "label": "Período", "type": "int", "default": 14, "min": 2, "max": 200, "step": 1}],
        "columns": [
            {"template": "adx_{period}", "label": "ADX ({period})"},
            {"template": "plus_di_{period}", "label": "DI+ ({period})"},
            {"template": "minus_di_{period}", "label": "DI− ({period})"},
            {"template": "plus_di_cross_{period}", "label": "Cruce alcista del DI+ ({period})"},
            {"template": "minus_di_cross_{period}", "label": "Cruce bajista del DI− ({period})"},
        ],
        "constants": ["ADX_DI_{period}_PERIOD = {period}"],
        "params_block": [{"key": "adx_di_{period}_period", "label": "ADX/DI {period} Period", "type": "int", "value_param": "period", "min": 2, "max": 200}],
        "compute": [
            "    adx_{period}, plus_di_{period}, minus_di_{period}, "
            "plus_di_cross_{period}, minus_di_cross_{period} = "
            "_adx_di(high, low, close, {period})",
        ],
        "helpers": ["_adx_di"],
        "needs": {"close", "high", "low"},
        "data_window": [
            {"key": "adx_{period}", "label": "ADX ({period})", "format": "number", "section": "ADX"},
            {"key": "plus_di_{period}", "label": "+DI ({period})", "format": "number", "section": "ADX"},
            {"key": "minus_di_{period}", "label": "-DI ({period})", "format": "number", "section": "ADX"},
            {"key": "plus_di_cross_{period}", "label": "+DI Cross ({period})", "format": "int", "section": "ADX"},
            {"key": "minus_di_cross_{period}", "label": "-DI Cross ({period})", "format": "int", "section": "ADX"},
        ],
        "overlay": None,
    },
    "VORTEX": {
        "label": "Vortex (cambios de tendencia)",
        "description": "Detecta giros de tendencia comparando los movimientos VI+ y VI−.",
        "pre_computed": False,
        "params": [{"key": "period", "label": "Período", "type": "int", "default": 14, "min": 2, "max": 200, "step": 1}],
        "columns": [
            {"template": "vi_plus_{period}", "label": "Vortex VI+ ({period})"},
            {"template": "vi_minus_{period}", "label": "Vortex VI− ({period})"},
            {"template": "vortex_dir_{period}", "label": "Dirección Vortex ({period})"},
            {"template": "vortex_cross_up_{period}", "label": "Cruce alcista Vortex ({period})"},
            {"template": "vortex_cross_down_{period}", "label": "Cruce bajista Vortex ({period})"},
        ],
        "constants": ["VORTEX_{period}_PERIOD = {period}"],
        "params_block": [{"key": "vortex_{period}_period", "label": "Vortex {period} Period", "type": "int", "value_param": "period", "min": 2, "max": 200}],
        "compute": [
            "    vi_plus_{period}, vi_minus_{period}, vortex_dir_{period}, "
            "vortex_cross_up_{period}, vortex_cross_down_{period} = "
            "_vortex(high, low, close, {period})",
        ],
        "helpers": ["_vortex"],
        "needs": {"close", "high", "low"},
        "data_window": [
            {"key": "vi_plus_{period}", "label": "VI+ ({period})", "format": "number", "section": "Vortex"},
            {"key": "vi_minus_{period}", "label": "VI- ({period})", "format": "number", "section": "Vortex"},
            {"key": "vortex_dir_{period}", "label": "Vortex Dir ({period})", "format": "int", "section": "Vortex"},
            {"key": "vortex_cross_up_{period}", "label": "Vortex Cross Up ({period})", "format": "int", "section": "Vortex"},
            {"key": "vortex_cross_down_{period}", "label": "Vortex Cross Down ({period})", "format": "int", "section": "Vortex"},
        ],
        "overlay": None,
    },
    "HMA": {
        "label": "Media de Hull (HMA)",
        "description": "Media suave y rápida ya calculada por el gráfico.",
        "pre_computed": True,
        "params": [],
        "columns": [{"template": "hma", "label": "HMA"}],
        "constants": [],
        "params_block": [],
        "compute": [],
        "helpers": [],
        "needs": set(),
        "data_window": [{"key": "hma", "label": "HMA (55)", "format": "price", "section": "Trend"}],
        "overlay": ("trend", "HMA (55)", [("average", "hma")]),
    },
    "SUPERTREND": {
        "label": "Supertrend",
        "description": "Guía de tendencia que cambia de lado del precio (ya calculada).",
        "pre_computed": True,
        "params": [],
        "columns": [
            {"template": "supertrend", "label": "Supertrend"},
            {"template": "supertrend_dir", "label": "Dirección Supertrend (1 alcista / -1 bajista)"},
        ],
        "constants": [],
        "params_block": [],
        "compute": [],
        "helpers": [],
        "needs": set(),
        "data_window": [
            {"key": "supertrend_dir", "label": "Supertrend Dir", "format": "number", "section": "Supertrend"},
            {"key": "supertrend", "label": "Supertrend", "format": "price", "section": "Supertrend"},
        ],
        "overlay": ("flag", "supertrend"),
    },
    "TCI": {
        "label": "Oscilador TCI",
        "description": "Oscilador de impulso normalizado por volatilidad (ya calculado).",
        "pre_computed": True,
        "params": [],
        "columns": [
            {"template": "tci", "label": "TCI"},
            {"template": "tci_signal", "label": "Señal TCI"},
            {"template": "tci_hist", "label": "Histograma TCI"},
        ],
        "constants": [],
        "params_block": [],
        "compute": [],
        "helpers": [],
        "needs": set(),
        "data_window": [
            {"key": "tci", "label": "TCI", "format": "number", "section": "TCI"},
            {"key": "tci_signal", "label": "TCI Signal", "format": "number", "section": "TCI"},
            {"key": "tci_hist", "label": "TCI Hist", "format": "number", "section": "TCI"},
        ],
        "overlay": ("flag", "tci"),
    },
}

VALID_INDICATOR_IDS = set(INDICATOR_SPECS)

# Indicadores computables por timeframe en estrategias MTF (los pre_computed
# dependen del feed del gráfico y solo existen en el frame base).
MTF_INDICATOR_IDS = [iid for iid, spec in INDICATOR_SPECS.items() if not spec["pre_computed"]]


def spec(ind_id: str) -> dict:
    return INDICATOR_SPECS[str(ind_id or "").upper()]


def format_template(template: str, params: dict) -> str:
    """Interpola {period}/{lookback}/{multiplier} con los params de la instancia."""
    out = template
    for key, value in (params or {}).items():
        out = out.replace("{" + key + "}", str(value))
    return out


def indicator_columns(ind_id: str, params: dict) -> list[str]:
    """Columnas que genera una instancia de indicador."""
    return [format_template(c["template"], params) for c in spec(ind_id)["columns"]]


def compute_lines(ind_id: str, params: dict) -> list[str]:
    """Líneas de cómputo (indent 4) para el cuerpo de prepare_dataframe/_prepare_frame."""
    return [format_template(line, params) for line in spec(ind_id)["compute"]]


def helpers_for(indicator_instances: list[dict]) -> list[str]:
    """Bloques de helper functions necesarios, en orden estable. Incluye _numeric siempre."""
    needed = {"_numeric"}
    for ind in indicator_instances:
        s = INDICATOR_SPECS.get(str(ind.get("id") or "").upper())
        if s and not s["pre_computed"]:
            needed.update(s["helpers"])
    return [HELPER_TEMPLATES[name] for name in HELPER_ORDER if name in needed]


def needed_series(indicator_instances: list[dict]) -> set[str]:
    """Series base que requieren los indicadores no pre-computados (close/high/low/volume)."""
    needs: set[str] = set()
    for ind in indicator_instances:
        s = INDICATOR_SPECS.get(str(ind.get("id") or "").upper())
        if s and not s["pre_computed"]:
            needs.update(s["needs"])
    return needs


def catalog_for_meta() -> list[dict]:
    """Catálogo serializable para /api/builder/meta (labels humanas, templates)."""
    out = []
    for ind_id, s in INDICATOR_SPECS.items():
        out.append({
            "id": ind_id,
            "label": s["label"],
            "description": s["description"],
            "pre_computed": s["pre_computed"],
            "params": [dict(p) for p in s["params"]],
            "columns": [{"template": c["template"], "label": c["label"]} for c in s["columns"]],
        })
    return out
