# Template de estrategias

Este archivo describe el template para crear estrategias compatibles con el bot.

## Ubicacion

Guarda tu estrategia como un modulo Python dentro de `strategies/`.

Ejemplos de nombre válido:
- `strategies/mi_estrategia.py`
- `strategies/strategy_ema_cross.py`

## Aviso de seguridad

Cada archivo `.py` en `strategies/` es cargado y ejecutado por el bot en tiempo real. **Solo agrega archivos que hayas escrito tú mismo o revisado cuidadosamente.** Nunca copies una estrategia de una fuente no confiable.

## Reglas basicas

- La estrategia no debe depender de otras partes del proyecto.
- Puedes usar librerias standard y `pandas`.
- Evita importar `config`, `data_feed`, `trading`, `mt5_connection`, o la GUI.
- Mantiene efectos secundarios al minimo (no abrir conexiones, no tocar IO).

## API minima (requerida)

Debes implementar al menos:
- `get_last_signal(df, verbose=False) -> str`

Retorna:
- `"buy"`, `"sell"`, o `"none"`.

## API opcional (recomendada)

- `TIMEFRAME = "M1"` (o `"M5"`, `"M15"`, `"M30"`, `"H1"`, `"H4"`, `"D1"`)
  - Define el timeframe de velas sobre el que opera la estrategia.
  - La GUI usará este timeframe para cargar y mostrar las velas.
  - Usa string para evitar dependencias con MT5 en la estrategia.
- `get_timeframe() -> str`
  - Alternativa si necesitas decidir el timeframe de forma dinamica.
- `prepare_dataframe(df) -> pd.DataFrame`
  - Prepara columnas propias necesarias para la estrategia.
- `DATA_WINDOW_FIELDS = [...]`
  - Lista de campos para el Data Window de la GUI.
  - Formato recomendado:
    - `{"key": "ema_fast", "label": "EMA Fast", "format": "price", "section": "EMA Cross"}`
  - Claves opcionales:
    - `group`: para respetar visibilidad de Object Tree.
    - `shift`: desplaza la serie (ej. `1` para usar vela cerrada).
- `MAGIC_NUMBER = 123456789`
  - Opcional para forzar un magic number fijo por estrategia.
  - Si no se define, la GUI genera uno estable automáticamente.
- `compute_dir1_and_signals(df, enable_signals) -> pd.DataFrame`
  - O bien `compute_signals(df, enable_signals) -> pd.DataFrame`.
- `get_last_signal_payload(df, verbose=False) -> dict`
  - Permite devolver señal + motivo para UI/tooltip.
  - Ejemplo: `{"signal": "buy", "reason": "Cruce EMA alcista"}`.
La GUI llamara en este orden:
1. `prepare_dataframe` (si existe)
2. `compute_dir1_and_signals` o `compute_signals` (si existe)
3. `get_last_signal_payload` (si existe)
4. `get_last_signal`

## Columnas recomendadas

El `df` suele incluir columnas de mercado como:
- `time`, `open`, `high`, `low`, `close`, `tick_volume`

Si agregas columnas propias, documentalas dentro del modulo.

## Plantilla basica

```python
"""Estrategia personalizada (template)."""

from datetime import datetime
import pandas as pd


def log_strategy(message: str):
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] [STRATEGY] {message}")


# Opcional
# def prepare_dataframe(df: pd.DataFrame) -> pd.DataFrame:
#     df = df.copy()
#     # calcula columnas propias
#     return df


# Opcional
# def compute_signals(df: pd.DataFrame, enable_signals: bool) -> pd.DataFrame:
#     df = df.copy()
#     # agrega columnas de senales
#     return df


def get_last_signal(df: pd.DataFrame, verbose: bool = False) -> str:
    """
    Devuelve "buy", "sell" o "none".
    Usa la ultima vela cerrada: indice len(df) - 2.
    """
    if len(df) < 2:
        if verbose:
            log_strategy("Not enough data")
        return "none"

    row = df.iloc[len(df) - 2]

    # TODO: reemplaza por tu logica real
    if row["close"] > row["open"]:
        if verbose:
            log_strategy("Signal: BUY")
        return "buy"
    if row["close"] < row["open"]:
        if verbose:
            log_strategy("Signal: SELL")
        return "sell"

    return "none"
```

## Ejemplo M1 (EMA cross)

```python
TIMEFRAME = "M1"
EMA_FAST = 9
EMA_SLOW = 21

def prepare_dataframe(df):
    df["ema_fast"] = df["close"].ewm(span=EMA_FAST, adjust=False).mean()
    df["ema_slow"] = df["close"].ewm(span=EMA_SLOW, adjust=False).mean()
    return df

def get_last_signal(df, verbose=False):
    if len(df) < 3:
        return "none"
    last_idx = len(df) - 2
    prev_idx = last_idx - 1
    fast = df.iloc[last_idx]["ema_fast"]
    slow = df.iloc[last_idx]["ema_slow"]
    fast_prev = df.iloc[prev_idx]["ema_fast"]
    slow_prev = df.iloc[prev_idx]["ema_slow"]
    if fast_prev <= slow_prev and fast > slow:
        return "buy"
    if fast_prev >= slow_prev and fast < slow:
        return "sell"
    return "none"
```

## Ejemplo M1 (vela confirmada)

```python
TIMEFRAME = "M1"
MIN_BODY_POINTS = 40.0

def get_last_signal(df, verbose=False):
    if len(df) < 2:
        return "none"
    row = df.iloc[len(df) - 2]
    body = row["close"] - row["open"]
    points = abs(body) * 10 ** 2  # ajusta según dígitos del símbolo
    if points >= MIN_BODY_POINTS:
        return "buy" if body > 0 else "sell"
    return "none"
```

## Como activar tu estrategia

Opcion A (config): edita `config.py`:
```python
ACTIVE_STRATEGIES = ["mi_estrategia"]
```

Opcion B (GUI): en el panel **Estrategias**, activa la estrategia desde la lista. No se requiere reiniciar.

## Validacion

Prueba con datos historicos o en demo antes de usar en real.
