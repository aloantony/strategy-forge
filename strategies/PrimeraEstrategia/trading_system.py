# Trading Agent — https://github.com/aloantony/trading-agent
# Required Notice: Copyright 2026 aloantony (https://github.com/aloantony)
# Licensed under the PolyForm Noncommercial License 1.0.0 — see LICENSE, or
# <https://polyformproject.org/licenses/noncommercial/1.0.0>. Noncommercial use
# is free; commercial use, including production use, requires a written
# agreement with the copyright holder.

"""
SISTEMA DE TRADING - MÓDULOS DE CÁLCULO
========================================
Entrada de datos: DataFrame de pandas con columnas:
    - open, high, low, close, volume (minúsculas)
    - índice: DatetimeIndex

Sin ejecución real. Solo cálculos y lógica.
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import Optional


# ─────────────────────────────────────────────
# ESTRUCTURAS DE DATOS
# ─────────────────────────────────────────────

@dataclass
class Posicion:
    ticker: str
    precio_entrada: float
    sl: float
    tp: float
    tamano: float          # número de acciones
    riesgo_cartera: float  # % de la cartera en riesgo
    fecha_entrada: pd.Timestamp
    activa: bool = True

@dataclass
class Cartera:
    capital: float
    posiciones: list[Posicion] = field(default_factory=list)

    def riesgo_agregado(self, ticker: str) -> float:
        """Riesgo total activo en un ticker como % de la cartera."""
        return sum(
            p.riesgo_cartera
            for p in self.posiciones
            if p.ticker == ticker and p.activa
        )

    def ultima_entrada(self, ticker: str) -> Optional[Posicion]:
        """Devuelve la última posición activa abierta en un ticker."""
        activas = [p for p in self.posiciones if p.ticker == ticker and p.activa]
        return activas[-1] if activas else None


# ─────────────────────────────────────────────
# MÓDULO 1: INDICADORES
# ─────────────────────────────────────────────

def calcular_atr(df: pd.DataFrame, periodo: int = 14) -> pd.Series:
    """
    Calcula el ATR (Average True Range).
    Entrada: DataFrame con columnas high, low, close.
    Salida: Serie con el ATR para cada vela.
    """
    high = df['high']
    low = df['low']
    close_prev = df['close'].shift(1)

    tr = pd.concat([
        high - low,
        (high - close_prev).abs(),
        (low - close_prev).abs()
    ], axis=1).max(axis=1)

    atr = tr.ewm(alpha=1/periodo, adjust=False).mean()
    return atr


def calcular_adx(df: pd.DataFrame, periodo: int = 14) -> pd.DataFrame:
    """
    Calcula ADX, +DI y -DI.
    Entrada: DataFrame con columnas high, low, close.
    Salida: DataFrame con columnas adx, di_pos, di_neg.
    """
    high = df['high']
    low = df['low']
    close_prev = df['close'].shift(1)
    high_prev = high.shift(1)
    low_prev = low.shift(1)

    # Movimientos direccionales
    dm_pos = np.where((high - high_prev) > (low_prev - low), 
                       np.maximum(high - high_prev, 0), 0)
    dm_neg = np.where((low_prev - low) > (high - high_prev), 
                       np.maximum(low_prev - low, 0), 0)

    dm_pos = pd.Series(dm_pos, index=df.index)
    dm_neg = pd.Series(dm_neg, index=df.index)

    # True Range
    tr = pd.concat([
        high - low,
        (high - close_prev).abs(),
        (low - close_prev).abs()
    ], axis=1).max(axis=1)

    # Suavizado exponencial
    atr_s = tr.ewm(alpha=1/periodo, adjust=False).mean()
    dm_pos_s = dm_pos.ewm(alpha=1/periodo, adjust=False).mean()
    dm_neg_s = dm_neg.ewm(alpha=1/periodo, adjust=False).mean()

    di_pos = 100 * dm_pos_s / atr_s
    di_neg = 100 * dm_neg_s / atr_s

    dx = 100 * (di_pos - di_neg).abs() / (di_pos + di_neg)
    adx = dx.ewm(alpha=1/periodo, adjust=False).mean()

    return pd.DataFrame({'adx': adx, 'di_pos': di_pos, 'di_neg': di_neg}, index=df.index)


def calcular_sma_volumen(df: pd.DataFrame, periodo: int = 20) -> pd.Series:
    """
    Calcula la SMA del volumen.
    Entrada: DataFrame con columna volume.
    Salida: Serie con la media móvil del volumen.
    """
    return df['volume'].rolling(window=periodo).mean()


# ─────────────────────────────────────────────
# MÓDULO 2: TRIGGER
# ─────────────────────────────────────────────

def evaluar_trigger(adx_df: pd.DataFrame, umbral_adx: float = 25) -> pd.Series:
    """
    Detecta señales de entrada long.
    Condición: ADX > umbral Y +DI cruza por encima de -DI.
    Salida: Serie booleana, True en las velas con señal.
    """
    adx = adx_df['adx']
    di_pos = adx_df['di_pos']
    di_neg = adx_df['di_neg']

    tendencia_fuerte = adx > umbral_adx
    cruce_alcista = (di_pos > di_neg) & (di_pos.shift(1) <= di_neg.shift(1))

    return tendencia_fuerte & cruce_alcista


# ─────────────────────────────────────────────
# MÓDULO 3: SIZING
# ─────────────────────────────────────────────

def calcular_tamano_posicion(
    capital: float,
    precio_entrada: float,
    atr: float,
    volumen_actual: float,
    sma_volumen: float,
    riesgo_max: float = 0.01,    # 1% máximo por operación
    riesgo_base: float = 0.005   # 0.5% base con volumen normal
) -> dict:
    """
    Calcula el tamaño de la posición según volumen relativo.
    El riesgo escala con el ratio volumen/SMA, con techo en riesgo_max.

    Retorna:
        - riesgo_pct: porcentaje de la cartera en riesgo
        - capital_en_riesgo: euros/dólares en riesgo
        - num_acciones: número de acciones a comprar
        - sl: precio de stop loss
        - tp: precio de take profit
    """
    # Ratio de volumen
    ratio_volumen = volumen_actual / sma_volumen if sma_volumen > 0 else 1.0

    # Riesgo escalado con techo
    riesgo_pct = min(ratio_volumen * riesgo_base, riesgo_max)

    # Capital en riesgo
    capital_en_riesgo = capital * riesgo_pct

    # SL y TP
    sl = precio_entrada - atr
    tp = precio_entrada + (2 * atr)

    # Número de acciones: si salta el SL perdemos exactamente capital_en_riesgo
    distancia_sl = precio_entrada - sl
    num_acciones = capital_en_riesgo / distancia_sl if distancia_sl > 0 else 0

    return {
        'riesgo_pct': riesgo_pct,
        'capital_en_riesgo': round(capital_en_riesgo, 2),
        'num_acciones': round(num_acciones, 4),
        'sl': round(sl, 4),
        'tp': round(tp, 4)
    }


# ─────────────────────────────────────────────
# MÓDULO 4: LÓGICA DE ENTRADA Y PIRAMIDACIÓN
# ─────────────────────────────────────────────

def evaluar_entrada(
    ticker: str,
    precio_actual: float,
    atr_actual: float,
    volumen_actual: float,
    sma_volumen: float,
    cartera: Cartera,
    hay_trigger: bool,
    riesgo_agregado_max: float = 0.03   # 3% máximo por ticker
) -> Optional[Posicion]:
    """
    Decide si abrir una nueva posición (inicial o piramiada).
    Retorna una Posicion si se debe abrir, None si no.
    """
    # Verificar límite de riesgo agregado
    if cartera.riesgo_agregado(ticker) >= riesgo_agregado_max:
        return None

    ultima = cartera.ultima_entrada(ticker)

    # Entrada inicial: necesita trigger
    if ultima is None:
        if not hay_trigger:
            return None
    else:
        # Piramidación: el precio debe haber avanzado 0.5×ATR desde la última entrada
        avance_necesario = 0.5 * atr_actual
        if precio_actual < ultima.precio_entrada + avance_necesario:
            return None

    # Calcular sizing
    sizing = calcular_tamano_posicion(
        capital=cartera.capital,
        precio_entrada=precio_actual,
        atr=atr_actual,
        volumen_actual=volumen_actual,
        sma_volumen=sma_volumen
    )

    # Verificar que el nuevo riesgo no supera el límite agregado
    riesgo_tras_entrada = cartera.riesgo_agregado(ticker) + sizing['riesgo_pct']
    if riesgo_tras_entrada > riesgo_agregado_max:
        return None

    return Posicion(
        ticker=ticker,
        precio_entrada=precio_actual,
        sl=sizing['sl'],
        tp=sizing['tp'],
        tamano=sizing['num_acciones'],
        riesgo_cartera=sizing['riesgo_pct'],
        fecha_entrada=pd.Timestamp.now()
    )


# ─────────────────────────────────────────────
# MÓDULO 5: EJECUCIÓN SOBRE DATOS
# ─────────────────────────────────────────────

def ejecutar_sistema(
    df: pd.DataFrame,
    ticker: str,
    capital_inicial: float = 100_000
) -> pd.DataFrame:
    """
    Ejecuta el sistema completo sobre un DataFrame histórico.
    Retorna un DataFrame con todas las operaciones generadas.

    Entrada esperada: DataFrame con open, high, low, close, volume e índice DatetimeIndex.
    """
    # Calcular indicadores
    atr = calcular_atr(df)
    adx_df = calcular_adx(df)
    sma_vol = calcular_sma_volumen(df)
    triggers = evaluar_trigger(adx_df)

    cartera = Cartera(capital=capital_inicial)
    operaciones = []

    for fecha, row in df.iterrows():
        atr_val = atr.loc[fecha]
        vol_val = row['volume']
        sma_vol_val = sma_vol.loc[fecha]
        trigger_val = triggers.loc[fecha]
        precio = row['close']

        # Saltar si no hay datos suficientes
        if pd.isna(atr_val) or pd.isna(sma_vol_val):
            continue

        # Verificar SL y TP de posiciones abiertas
        for pos in cartera.posiciones:
            if not pos.activa or pos.ticker != ticker:
                continue
            if row['low'] <= pos.sl:
                pos.activa = False
                operaciones.append({
                    'fecha_entrada': pos.fecha_entrada,
                    'fecha_salida': fecha,
                    'tipo': 'SL',
                    'precio_entrada': pos.precio_entrada,
                    'precio_salida': pos.sl,
                    'num_acciones': pos.tamano,
                    'resultado': round((pos.sl - pos.precio_entrada) * pos.tamano, 2)
                })
            elif row['high'] >= pos.tp:
                pos.activa = False
                operaciones.append({
                    'fecha_entrada': pos.fecha_entrada,
                    'fecha_salida': fecha,
                    'tipo': 'TP',
                    'precio_entrada': pos.precio_entrada,
                    'precio_salida': pos.tp,
                    'num_acciones': pos.tamano,
                    'resultado': round((pos.tp - pos.precio_entrada) * pos.tamano, 2)
                })

        # Evaluar nueva entrada
        nueva_pos = evaluar_entrada(
            ticker=ticker,
            precio_actual=precio,
            atr_actual=atr_val,
            volumen_actual=vol_val,
            sma_volumen=sma_vol_val,
            cartera=cartera,
            hay_trigger=trigger_val
        )

        if nueva_pos is not None:
            nueva_pos.fecha_entrada = fecha
            cartera.posiciones.append(nueva_pos)

    return pd.DataFrame(operaciones)


# ─────────────────────────────────────────────
# EJEMPLO DE USO
# ─────────────────────────────────────────────

if __name__ == "__main__":
    # Sustituir por tu fuente de datos real
    # df = tu_fuente_de_datos(ticker, start, end)

    # Ejemplo con datos sintéticos
    np.random.seed(42)
    n = 200
    fechas = pd.date_range(start='2023-01-01', periods=n, freq='B')
    close = 100 + np.cumsum(np.random.randn(n) * 1.5)
    df_ejemplo = pd.DataFrame({
        'open':   close - np.random.rand(n),
        'high':   close + np.random.rand(n) * 2,
        'low':    close - np.random.rand(n) * 2,
        'close':  close,
        'volume': np.random.randint(500_000, 2_000_000, n)
    }, index=fechas)

    resultados = ejecutar_sistema(df_ejemplo, ticker='EJEMPLO', capital_inicial=100_000)

    if not resultados.empty:
        print(resultados.to_string(index=False))
        print(f"\nTotal operaciones : {len(resultados)}")
        print(f"Resultado total   : {resultados['resultado'].sum():.2f}")
        print(f"Win rate          : {(resultados['resultado'] > 0).mean():.1%}")
    else:
        print("Sin operaciones generadas con estos datos sintéticos.")
