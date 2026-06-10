"""
Módulo de backtesting para la estrategia de trading.
Simula operaciones con datos históricos y calcula métricas de rendimiento.
"""

import pandas as pd
from backend.brokers.mt5_import import mt5
from datetime import datetime, timedelta
import importlib
from backend.core import config
from backend.data import data_feed


def _load_backtest_strategy_module() -> tuple:
    default_key = str(getattr(config, "STRATEGY_KEY", "") or "").strip()
    if not default_key:
        active = getattr(config, "ACTIVE_STRATEGIES", [])
        if isinstance(active, (list, tuple)) and active:
            default_key = str(active[0] or "").strip()
    if not default_key:
        default_key = "ema_rsi_trend"

    explicit_module_ref = str(getattr(config, "STRATEGY_MODULE", "") or "").strip()
    candidate_refs = []
    if explicit_module_ref:
        candidate_refs.append(explicit_module_ref)
    candidate_refs.extend(
        [
            f"strategies.strategy_{default_key}",
            f"strategies.{default_key}",
        ]
    )

    seen = set()
    errors = []
    for module_ref in candidate_refs:
        cleaned = module_ref.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        try:
            module = importlib.reload(importlib.import_module(cleaned))
            return module, cleaned
        except Exception as error:
            errors.append(f"{cleaned}: {error}")

    details = "; ".join(errors) if errors else "sin detalle"
    raise RuntimeError(f"No se pudo cargar la estrategia del backtest. Intentos: {details}")


def _apply_strategy_to_dataframe(df: pd.DataFrame, strategy_module) -> pd.DataFrame:
    out = df.copy()

    if hasattr(strategy_module, "prepare_dataframe"):
        candidate = strategy_module.prepare_dataframe(out)
        if isinstance(candidate, pd.DataFrame):
            out = candidate

    if hasattr(strategy_module, "compute_dir1_and_signals"):
        candidate = strategy_module.compute_dir1_and_signals(out, config.ENABLE_SIGNALS)
        if isinstance(candidate, pd.DataFrame):
            out = candidate
    elif hasattr(strategy_module, "compute_signals"):
        candidate = strategy_module.compute_signals(out, config.ENABLE_SIGNALS)
        if isinstance(candidate, pd.DataFrame):
            out = candidate
    else:
        raise RuntimeError(
            "La estrategia no implementa compute_signals() ni compute_dir1_and_signals()."
        )

    out["up_sig"] = pd.to_numeric(out.get("up_sig", 0), errors="coerce").fillna(0).astype(int)
    out["dn_sig"] = pd.to_numeric(out.get("dn_sig", 0), errors="coerce").fillna(0).astype(int)
    return out


class BacktestEngine:
    # esta clase simula operaciones pasadas para ver como habria ido la estrategia.
    """
    Motor de backtesting que simula operaciones con datos históricos.
    """
    
    def __init__(self, symbol: str, timeframe, lot: float, sl_points: float, tp_points: float):
        # esta funcion sirve para preparar todo al inicio.
        """
        Inicializa el motor de backtesting.
        
        Args:
            symbol: Símbolo a operar.
            timeframe: Timeframe de MT5.
            lot: Tamaño de la posición en lotes.
            sl_points: Stop Loss en puntos.
            tp_points: Take Profit en puntos.
        """
        if mt5 is None:
            raise RuntimeError(
                "backtest.py requiere MT5. Para backtesting cross-platform usa: "
                "python -m backtesting runtime --data-source dukascopy"
            )
        self.symbol = symbol
        self.timeframe = timeframe
        self.lot = lot
        self.sl_points = sl_points
        self.tp_points = tp_points
        
        # Estado de la simulación
        self.positions = []  # Lista de posiciones abiertas/cerradas
        self.current_position = None  # Posición actual
        self.equity_curve = []  # Evolución del equity
        self.initial_balance = 10000.0  # Balance inicial
        self.balance = self.initial_balance
        
        # Métricas
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0
        self.total_profit = 0.0
        self.max_drawdown = 0.0
        self.peak_equity = self.initial_balance
        
        # Información del símbolo
        symbol_info = mt5.symbol_info(symbol)
        if symbol_info is None:
            raise Exception(f"Símbolo {symbol} no encontrado")
        self.point = symbol_info.point
        self.contract_size = symbol_info.trade_contract_size
        self.tick_value = symbol_info.trade_tick_value
    
    def calculate_profit(self, entry_price: float, exit_price: float, direction: int, volume: float) -> float:
        # esta funcion sirve para calculate profit.
        """
        Calcula el profit de una operación.
        
        Args:
            entry_price: Precio de entrada.
            exit_price: Precio de salida.
            direction: 1 para BUY, -1 para SELL.
            volume: Volumen en lotes.
        
        Returns:
            float: Profit en la moneda de la cuenta.
        """
        price_diff = (exit_price - entry_price) * direction
        profit = price_diff * volume * self.contract_size / self.point * self.tick_value
        return profit
    
    def check_sl_tp(self, candle: pd.Series, position: dict) -> tuple[bool, str, float]:
        # esta funcion sirve para comprobar sl tp.
        """
        Verifica si se activó el SL o TP.
        
        Args:
            candle: Vela actual con high, low, close.
            position: Diccionario con información de la posición.
        
        Returns:
            tuple: (bool, str, float) - (True si se cerró, razón, precio de cierre)
        """
        entry_price = position['entry_price']
        direction = position['direction']
        sl = position['sl']
        tp = position['tp']
        
        if direction == 1:  # BUY
            # Verificar TP primero (más favorable)
            if tp > 0 and candle['high'] >= tp:
                return True, 'TP', tp
            # Verificar SL
            if sl > 0 and candle['low'] <= sl:
                return True, 'SL', sl
        else:  # SELL
            # Verificar TP primero
            if tp > 0 and candle['low'] <= tp:
                return True, 'TP', tp
            # Verificar SL
            if sl > 0 and candle['high'] >= sl:
                return True, 'SL', sl
        
        return False, '', 0.0
    
    def open_position(self, candle: pd.Series, direction: int, signal_type: str):
        # esta funcion sirve para abrir posicion.
        """
        Abre una nueva posición.
        
        Args:
            candle: Vela actual.
            direction: 1 para BUY, -1 para SELL.
            signal_type: Tipo de señal ("buy" o "sell").
        """
        # Cerrar posición existente si hay una en dirección opuesta
        if self.current_position and self.current_position['direction'] != direction:
            self.close_position(candle, 'REVERSAL')
        
        # Si ya hay posición en la misma dirección, no hacer nada
        if self.current_position and self.current_position['direction'] == direction:
            return
        
        # Calcular precios de entrada, SL y TP
        entry_price = candle['close']  # Entramos al cierre de la vela
        
        if direction == 1:  # BUY
            sl = entry_price - (self.sl_points * self.point) if self.sl_points > 0 else 0
            tp = entry_price + (self.tp_points * self.point) if self.tp_points > 0 else 0
        else:  # SELL
            sl = entry_price + (self.sl_points * self.point) if self.sl_points > 0 else 0
            tp = entry_price - (self.tp_points * self.point) if self.tp_points > 0 else 0
        
        self.current_position = {
            'entry_time': candle['time'],
            'entry_price': entry_price,
            'direction': direction,
            'volume': self.lot,
            'sl': sl,
            'tp': tp,
            'signal_type': signal_type
        }
    
    def close_position(self, candle: pd.Series, reason: str):
        # esta funcion sirve para cerrar posicion.
        """
        Cierra la posición actual.
        
        Args:
            candle: Vela actual.
            reason: Razón del cierre ("SL", "TP", "REVERSAL", "SIGNAL").
        """
        if self.current_position is None:
            return
        
        exit_price = candle['close']
        
        # Verificar si se activó SL o TP
        sl_tp_hit, sl_tp_reason, sl_tp_price = self.check_sl_tp(candle, self.current_position)
        
        if sl_tp_hit:
            exit_price = sl_tp_price
            reason = sl_tp_reason
        
        # Calcular profit
        profit = self.calculate_profit(
            self.current_position['entry_price'],
            exit_price,
            self.current_position['direction'],
            self.current_position['volume']
        )
        
        # Guardar posición cerrada
        closed_position = {
            **self.current_position,
            'exit_time': candle['time'],
            'exit_price': exit_price,
            'profit': profit,
            'reason': reason
        }
        self.positions.append(closed_position)
        
        # Actualizar balance y métricas
        self.balance += profit
        self.total_trades += 1
        self.total_profit += profit
        
        if profit > 0:
            self.winning_trades += 1
        else:
            self.losing_trades += 1
        
        # Actualizar equity curve
        self.equity_curve.append({
            'time': candle['time'],
            'balance': self.balance,
            'profit': profit
        })
        
        # Actualizar drawdown
        if self.balance > self.peak_equity:
            self.peak_equity = self.balance
        
        drawdown = ((self.peak_equity - self.balance) / self.peak_equity) * 100
        if drawdown > self.max_drawdown:
            self.max_drawdown = drawdown
        
        self.current_position = None
    
    def run(self, start_date: datetime, end_date: datetime):
        # esta funcion sirve para ejecutar el proceso completo.
        """
        Ejecuta el backtesting en el rango de fechas especificado.
        
        Args:
            start_date: Fecha de inicio.
            end_date: Fecha de fin.
        """
        print(f"\n{'='*80}")
        print(f"INICIANDO BACKTEST")
        print(f"{'='*80}")
        print(f"Símbolo: {self.symbol}")
        print(f"Período: {start_date.strftime('%Y-%m-%d')} a {end_date.strftime('%Y-%m-%d')}")
        print(f"Lote: {self.lot}")
        print(f"SL: {self.sl_points} puntos | TP: {self.tp_points} puntos")
        print(f"{'='*80}\n")
        
        # Obtener datos históricos
        print("Obteniendo datos históricos...")
        rates = mt5.copy_rates_range(self.symbol, self.timeframe, start_date, end_date)
        if rates is None or len(rates) == 0:
            raise Exception(f"No se pudieron obtener datos para {self.symbol} en el rango especificado")
        
        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        
        print(f"✓ {len(df)} velas obtenidas\n")
        
        # Procesar datos
        print("Procesando datos...")
        strategy_module, strategy_ref = _load_backtest_strategy_module()
        print(f"Estrategia backtest: {strategy_ref}")
        df = data_feed.add_source_columns(df, config.SOURCE_MODE)
        df = data_feed.add_baseline_bands(
            df,
            config.MA_LENGTH,
            config.ATR_LENGTH,
            config.ATR_MULT
        )
        df = _apply_strategy_to_dataframe(df, strategy_module)
        print("✓ Datos procesados\n")
        
        # Simular trading
        print("Simulando operaciones...")
        for i in range(len(df)):
            candle = df.iloc[i]
            
            # Saltar velas sin datos válidos
            if pd.isna(candle.get('close')):
                continue
            
            # Verificar señales (usar vela anterior si no es la primera)
            if i > 0:
                prev_candle = df.iloc[i - 1]
                
                # Señal de compra
                if prev_candle['up_sig']:
                    self.open_position(candle, 1, 'BUY')
                
                # Señal de venta
                if prev_candle['dn_sig']:
                    self.open_position(candle, -1, 'SELL')
            
            # Verificar SL/TP si hay posición abierta
            if self.current_position:
                sl_tp_hit, reason, _ = self.check_sl_tp(candle, self.current_position)
                if sl_tp_hit:
                    self.close_position(candle, reason)
            
            # Actualizar equity curve incluso sin operaciones
            if not self.current_position:
                self.equity_curve.append({
                    'time': candle['time'],
                    'balance': self.balance,
                    'profit': 0.0
                })
        
        # Cerrar posición final si existe
        if self.current_position:
            last_candle = df.iloc[-1]
            self.close_position(last_candle, 'END_OF_DATA')
        
        print("✓ Simulación completada\n")
    
    def get_results(self) -> dict:
        # esta funcion sirve para obtener results.
        """
        Calcula y retorna las métricas del backtesting.
        
        Returns:
            dict: Diccionario con todas las métricas.
        """
        if self.total_trades == 0:
            return {
                'total_trades': 0,
                'message': 'No se ejecutaron operaciones en el período'
            }
        
        win_rate = (self.winning_trades / self.total_trades) * 100
        avg_win = sum(p['profit'] for p in self.positions if p['profit'] > 0) / self.winning_trades if self.winning_trades > 0 else 0
        avg_loss = sum(p['profit'] for p in self.positions if p['profit'] < 0) / self.losing_trades if self.losing_trades > 0 else 0
        profit_factor = abs(avg_win * self.winning_trades / (avg_loss * self.losing_trades)) if avg_loss != 0 and self.losing_trades > 0 else 0
        final_balance = self.balance
        total_return = ((final_balance - self.initial_balance) / self.initial_balance) * 100
        
        return {
            'initial_balance': self.initial_balance,
            'final_balance': final_balance,
            'total_profit': self.total_profit,
            'total_return_pct': total_return,
            'total_trades': self.total_trades,
            'winning_trades': self.winning_trades,
            'losing_trades': self.losing_trades,
            'win_rate': win_rate,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor,
            'max_drawdown': self.max_drawdown,
            'positions': self.positions
        }
    
    def print_results(self):
        # esta funcion sirve para mostrar results.
        """
        Imprime los resultados del backtesting de forma legible.
        """
        results = self.get_results()
        
        if 'message' in results:
            print(results['message'])
            return
        
        print(f"\n{'='*80}")
        print(f"RESULTADOS DEL BACKTEST")
        print(f"{'='*80}\n")
        
        print(f"💰 BALANCE:")
        print(f"   Inicial: {results['initial_balance']:.2f}")
        print(f"   Final: {results['final_balance']:.2f}")
        print(f"   Profit Total: {results['total_profit']:.2f} ({results['total_return_pct']:+.2f}%)\n")
        
        print(f"📊 OPERACIONES:")
        print(f"   Total: {results['total_trades']}")
        print(f"   Ganadoras: {results['winning_trades']} ({results['win_rate']:.2f}%)")
        print(f"   Perdedoras: {results['losing_trades']} ({100 - results['win_rate']:.2f}%)\n")
        
        print(f"📈 MÉTRICAS:")
        print(f"   Ganancia promedio: {results['avg_win']:.2f}")
        print(f"   Pérdida promedio: {results['avg_loss']:.2f}")
        print(f"   Profit Factor: {results['profit_factor']:.2f}")
        print(f"   Max Drawdown: {results['max_drawdown']:.2f}%\n")
        
        # Resumen por tipo de cierre
        closes_by_reason = {}
        for pos in results['positions']:
            reason = pos['reason']
            if reason not in closes_by_reason:
                closes_by_reason[reason] = {'count': 0, 'profit': 0.0}
            closes_by_reason[reason]['count'] += 1
            closes_by_reason[reason]['profit'] += pos['profit']
        
        print(f"🔚 CIERRES POR RAZÓN:")
        for reason, data in closes_by_reason.items():
            print(f"   {reason}: {data['count']} operaciones, Profit: {data['profit']:.2f}")
        
        print(f"\n{'='*80}\n")


def run_backtest(symbol: str, timeframe, start_date: datetime, end_date: datetime,
                 lot: float = None, sl_points: float = None, tp_points: float = None):
    # esta funcion lanza una prueba con datos pasados y devuelve el resumen.
    """
    Función de conveniencia para ejecutar un backtest.
    
    Args:
        symbol: Símbolo a operar.
        timeframe: Timeframe de MT5.
        start_date: Fecha de inicio.
        end_date: Fecha de fin.
        lot: Tamaño de la posición (usa config si es None).
        sl_points: Stop Loss en puntos (usa config si es None).
        tp_points: Take Profit en puntos (usa config si es None).
    """
    engine = BacktestEngine(
        symbol,
        timeframe,
        lot or config.LOT,
        sl_points or config.SL_POINTS,
        tp_points or config.TP_POINTS
    )
    
    engine.run(start_date, end_date)
    engine.print_results()
    
    return engine


