# Strategy Forge — https://github.com/aloantony/strategy-forge
# Required Notice: Copyright 2026 aloantony (https://github.com/aloantony)
# Licensed under the PolyForm Noncommercial License 1.0.0 — see LICENSE, or
# <https://polyformproject.org/licenses/noncommercial/1.0.0>. Noncommercial use
# is free; commercial use, including production use, requires a written
# agreement with the copyright holder.

"""
StrategyContextBuilder v1.
Construye el dict de contexto completo para una estrategia según doc 03.
"""

from datetime import datetime, timezone


class StrategyContextBuilder:
    """
    Construye el context dict completo que se pasa a decide(context, state).

    Depende de:
    - mt5: módulo MetaTrader5 (inyectado para facilitar tests)
    - dal_uow: UnitOfWork para leer legs/groups propios de la instancia
    """

    def __init__(self, mt5_module, uow):
        self._mt5 = mt5_module
        self._uow = uow

    def build(
        self,
        strategy_key: str,
        symbol: str,
        timeframe_label: str,
        df,           # pd.DataFrame con las velas ya procesadas
        instance_id: str,
        state_revision: int = 0,
        symbol_book_revision: int = 0,
        iteration_id: str = "",
        mode: str = "live",
        legacy_defaults: dict | None = None,
    ) -> dict:
        now_utc = datetime.now(timezone.utc)

        run = self._build_run(
            strategy_key, symbol, timeframe_label, instance_id,
            state_revision, symbol_book_revision, iteration_id, mode,
        )
        clock = self._build_clock(now_utc)
        market = self._build_market(symbol, timeframe_label, df)
        instrument = self._build_instrument(symbol)
        account = self._build_account()
        portfolio = self._build_portfolio(symbol, strategy_key, instance_id)
        execution = self._build_execution(instance_id, symbol)
        engine = self._build_engine()

        # Defaults legacy expuestos dentro de instance.runtime para el adaptador
        instance_runtime = {
            "legacy_execution_defaults": legacy_defaults or {},
        }

        return {
            "run": run,
            "clock": clock,
            "market": market,
            "instrument": instrument,
            "account": account,
            "portfolio": portfolio,
            "execution": execution,
            "engine": engine,
            "symbol": {"name": symbol},
            "instance": {
                "id": instance_id,
                "strategy_key": strategy_key,
                "runtime": instance_runtime,
            },
        }

    # ------------------------------------------------------------------
    # Secciones del contexto
    # ------------------------------------------------------------------

    def _build_run(
        self,
        strategy_key, symbol, timeframe_label, instance_id,
        state_revision, symbol_book_revision, iteration_id, mode,
    ) -> dict:
        return {
            "mode": mode,
            "iteration_id": iteration_id,
            "strategy_key": strategy_key,
            "symbol": symbol,
            "primary_timeframe": timeframe_label,
            "symbol_book_revision": symbol_book_revision,
            "state_revision": state_revision,
        }

    def _build_clock(self, now_utc: datetime) -> dict:
        mt5 = self._mt5
        broker_time = None
        try:
            tick = mt5.symbol_info_tick(None)  # No usamos symbol aquí, solo el tiempo del server
        except Exception:
            tick = None

        # Intentar obtener hora del server MT5
        try:
            server_time = getattr(mt5, "terminal_info", lambda: None)()
            if server_time and hasattr(server_time, "server_time"):
                broker_time = datetime.fromtimestamp(
                    server_time.server_time, tz=timezone.utc
                ).isoformat()
        except Exception:
            broker_time = None

        return {
            "now_utc": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "broker_time": broker_time,
            "trading_day": now_utc.strftime("%Y-%m-%d"),
            "weekday": now_utc.weekday(),
            "market_open": True,  # Se actualiza por la capa superior si hace falta
        }

    def _build_market(self, symbol: str, timeframe_label: str, df) -> dict:
        bars = []
        if df is not None and len(df) > 0:
            # Convertir a lista de dicts
            try:
                bars_raw = df.to_dict(orient="records")
                for bar in bars_raw:
                    # Normalizar timestamp
                    time_val = bar.get("time")
                    if hasattr(time_val, "isoformat"):
                        time_str = time_val.isoformat() + "Z" if time_val.tzinfo is None else time_val.isoformat()
                    else:
                        time_str = str(time_val) if time_val is not None else ""

                    # Separar indicadores del OHLCV
                    ohlcv_keys = {"time", "open", "high", "low", "close", "tick_volume", "spread", "real_volume", "volume"}
                    indicators = {k: float(v) for k, v in bar.items() if k not in ohlcv_keys and v is not None and isinstance(v, (int, float))}

                    bars.append({
                        "time": time_str,
                        "open": float(bar.get("open", 0)),
                        "high": float(bar.get("high", 0)),
                        "low": float(bar.get("low", 0)),
                        "close": float(bar.get("close", 0)),
                        "tick_volume": int(bar.get("tick_volume", 0)),
                        "indicators": indicators,
                    })
            except Exception:
                bars = []

        quote = self._build_quote(symbol)

        return {
            "quote": quote,
            "frames": {
                timeframe_label: {
                    "bars": bars,
                }
            },
        }

    def _build_quote(self, symbol: str) -> dict:
        mt5 = self._mt5
        try:
            tick = mt5.symbol_info_tick(symbol)
            if tick:
                bid = float(tick.bid)
                ask = float(tick.ask)
                mid = (bid + ask) / 2.0
                info = mt5.symbol_info(symbol)
                point = float(info.point) if info else 0.0
                spread_points = round((ask - bid) / point, 1) if point > 0 else 0.0
                return {"bid": bid, "ask": ask, "mid": mid, "spread_points": spread_points}
        except Exception:
            pass
        return {"bid": 0.0, "ask": 0.0, "mid": 0.0, "spread_points": 0.0}

    def _build_instrument(self, symbol: str) -> dict:
        mt5 = self._mt5
        try:
            info = mt5.symbol_info(symbol)
            if info:
                return {
                    "symbol": symbol,
                    "base_currency": getattr(info, "currency_base", ""),
                    "profit_currency": getattr(info, "currency_profit", ""),
                    "digits": int(getattr(info, "digits", 0)),
                    "point": float(getattr(info, "point", 0)),
                    "tick_size": float(getattr(info, "trade_tick_size", 0)),
                    "tick_value": float(getattr(info, "trade_tick_value", 0)),
                    "volume_min": float(getattr(info, "volume_min", 0.01)),
                    "volume_max": float(getattr(info, "volume_max", 100.0)),
                    "volume_step": float(getattr(info, "volume_step", 0.01)),
                    "stop_level_points": float(getattr(info, "trade_stops_level", 0)),
                    "freeze_level_points": float(getattr(info, "trade_freeze_level", 0)),
                }
        except Exception:
            pass
        return {
            "symbol": symbol,
            "base_currency": "",
            "profit_currency": "",
            "digits": 0,
            "point": 0.0,
            "tick_size": 0.0,
            "tick_value": 0.0,
            "volume_min": 0.01,
            "volume_max": 100.0,
            "volume_step": 0.01,
            "stop_level_points": 0.0,
            "freeze_level_points": 0.0,
        }

    def _build_account(self) -> dict:
        mt5 = self._mt5
        try:
            acc = mt5.account_info()
            if acc:
                return {
                    "balance": float(acc.balance),
                    "equity": float(acc.equity),
                    "margin_used": float(acc.margin),
                    "margin_free": float(acc.margin_free),
                    "currency": str(acc.currency),
                    "position_mode": "hedging",  # MT5 por defecto; se puede leer de acc si está disponible
                }
        except Exception:
            pass
        return {
            "balance": 0.0,
            "equity": 0.0,
            "margin_used": 0.0,
            "margin_free": 0.0,
            "currency": "USD",
            "position_mode": "hedging",
        }

    def _build_portfolio(self, symbol: str, strategy_key: str, instance_id: str) -> dict:
        mt5 = self._mt5
        gross = 0.0
        net = 0.0
        open_risk = 0.0

        try:
            positions = mt5.positions_get(symbol=symbol) or []
            for pos in positions:
                vol = float(pos.volume)
                price = float(pos.price_open)
                gross += vol * price
                if pos.type == 0:  # POSITION_TYPE_BUY
                    net += vol * price
                else:
                    net -= vol * price
        except Exception:
            pass

        equity = 0.0
        try:
            acc = mt5.account_info()
            if acc:
                equity = float(acc.equity)
        except Exception:
            pass

        open_risk_pct = (open_risk / equity * 100) if equity > 0 else 0.0

        return {
            "gross_exposure": gross,
            "net_exposure": net,
            "open_risk_amount": open_risk,
            "open_risk_pct_equity": open_risk_pct,
            "by_symbol": {
                symbol: {
                    "gross_exposure": gross,
                    "open_risk_amount": open_risk,
                    "open_risk_pct_equity": open_risk_pct,
                }
            },
            "by_strategy": {
                strategy_key: {
                    "gross_exposure": gross,
                    "open_risk_amount": open_risk,
                    "open_risk_pct_equity": open_risk_pct,
                }
            },
        }

    def _build_execution(self, instance_id: str, symbol: str) -> dict:
        owned_legs = []
        owned_entry_groups = []
        broker_positions = []

        try:
            owned_legs = self._uow.legs.list_open_by_instance(instance_id)
            owned_entry_groups = self._uow.entry_groups.list_open_by_instance(instance_id)
        except Exception:
            pass

        try:
            mt5 = self._mt5
            positions = mt5.positions_get(symbol=symbol) or []
            broker_positions = [
                {
                    "ticket": int(pos.ticket),
                    "symbol": str(pos.symbol),
                    "type": int(pos.type),
                    "volume": float(pos.volume),
                    "price_open": float(pos.price_open),
                    "sl": float(pos.sl),
                    "tp": float(pos.tp),
                    "profit": float(pos.profit),
                    "magic": int(pos.magic),
                    "comment": str(pos.comment),
                }
                for pos in positions
            ]
        except Exception:
            pass

        return {
            "broker_positions": broker_positions,
            "pending_orders": [],
            "recent_fills": [],
            "owned_legs": owned_legs,
            "owned_entry_groups": owned_entry_groups,
            "views": {
                "instance_book_revision": 0,
                "symbol_book_revision": 0,
            },
        }

    def _build_engine(self) -> dict:
        return {
            "supports_partial_close": True,
            "supports_pending_orders": True,
            "supports_position_tagging": True,
            "max_actions_per_cycle": 20,
        }
