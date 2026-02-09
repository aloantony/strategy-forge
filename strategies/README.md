# Template de estrategias

Este archivo describe el template para crear estrategias compatibles con el bot.

## Ubicacion

Guarda tu estrategia como un modulo Python dentro de `strategies/`.

Ejemplos:
- `strategies/mi_estrategia.py`
- `strategies/strategy_baseline.py`

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

- `prepare_dataframe(df) -> pd.DataFrame`
  - Prepara columnas propias necesarias para la estrategia.
- `compute_dir1_and_signals(df, enable_signals) -> pd.DataFrame`
  - O bien `compute_signals(df, enable_signals) -> pd.DataFrame`.
- `get_test_signal() -> str`
  - Usado cuando `TEST_MODE=True`.

La GUI llamara en este orden:
1. `prepare_dataframe` (si existe)
2. `compute_dir1_and_signals` o `compute_signals` (si existe)
3. `get_last_signal`

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


# Opcional
# def get_test_signal() -> str:
#     return "buy"
```

## Como activar tu estrategia

Opcion A (config):
- Edita `config.py`:
  - `STRATEGY_KEY = "mi_estrategia"`
  - `STRATEGY_MODULE = "strategies.mi_estrategia"`

Opcion B (GUI):
- En el panel de estrategias, carga el modulo o arrastra el archivo `.py`.

## Validacion

Prueba con datos historicos o en demo antes de usar en real.
