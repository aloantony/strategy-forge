import trading
import MetaTrader5 as mt5
from src.broker.interface import IBrokerAdapter, InstrumentInfo, OrderResult, AccountInfo

TRADE_RETCODE_DONE = 10009


class MT5BrokerAdapter(IBrokerAdapter):

    def send_order(self, symbol, order_type, lot, magic,
                   sl_price, tp_price, strategy_key="", strategy_label="", signal_reason=""):
        direction = 1 if order_type == 0 else -1

        comment = trading.build_trade_comment(
            strategy_key=strategy_key,
            signal_reason=signal_reason,
            action_kind="open",
        )

        raw = trading._send_order(
            symbol=symbol,
            direction=direction,
            lot=lot,
            sl_points=0,
            tp_points=0,
            magic_number=magic,
            order_comment=comment,
            sl_price=sl_price or 0.0,
            tp_price=tp_price or 0.0,
        )

        if raw is None:
            return OrderResult(success=False, retcode=-1, order_id="", deal_id="", comment="")

        success = raw.get("success", False)
        retcode = raw.get("retcode")
        if retcode is None:
            retcode = TRADE_RETCODE_DONE if success else -1
        return OrderResult(
            success=success,
            retcode=retcode,
            order_id=str(raw.get("ticket") or ""),
            deal_id="",
            comment=str(raw.get("comment") or ""),
            price=raw.get("price", 0.0),
            volume=raw.get("volume", 0.0),
        )

    def close_position(self, symbol, magic, strategy_key="", strategy_label="", close_reason=""):
        comment = trading.build_trade_comment(
            strategy_key=strategy_key,
            signal_reason=close_reason,
            action_kind="close",
        )
        results = trading._close_position(
            symbol=symbol,
            magic_number=magic,
            order_comment=comment,
        )
        if not results:
            return False
        return any(r.get("success", False) for r in results)

    def modify_sl(self, symbol, magic, new_sl_price):
        try:
            positions = mt5.positions_get(symbol=symbol) or []
            positions = [p for p in positions if p.magic == magic]
            success = False
            for pos in positions:
                request = {
                    "action": mt5.TRADE_ACTION_SLTP,
                    "position": pos.ticket,
                    "symbol": symbol,
                    "sl": new_sl_price,
                    "tp": pos.tp,
                    "magic": magic,
                }
                result = mt5.order_send(request)
                if result and result.retcode == TRADE_RETCODE_DONE:
                    success = True
            return success
        except Exception:
            return False

    def apply_signal(self, symbol, signal, lot, sl_points, tp_points,
                     magic_number, strategy_key="", strategy_label="", signal_reason=""):
        return trading.apply_signal(
            symbol=symbol,
            signal=signal,
            lot=lot,
            sl_points=sl_points,
            tp_points=tp_points,
            magic_number=magic_number,
            strategy_key=strategy_key,
            strategy_label=strategy_label,
            signal_reason=signal_reason,
        )

    def apply_pyramid_signal(self, symbol, magic_number, atr_value, lot,
                              strategy_key="", strategy_label="", signal_reason="", balance=None):
        return trading.apply_pyramid_signal(
            symbol=symbol,
            magic_number=magic_number,
            atr_value=atr_value,
            lot=lot,
            strategy_key=strategy_key,
            strategy_label=strategy_label,
            signal_reason=signal_reason,
            balance=balance,
        )

    def is_market_open(self, symbol):
        return trading.is_market_open(symbol)

    def get_open_positions(self, symbol, magic_number):
        return trading.get_all_positions(symbol, magic_number)

    def get_account_info(self):
        raw = mt5.account_info()
        if raw is None:
            return None
        return AccountInfo(
            balance=raw.balance,
            equity=raw.equity,
            margin=raw.margin,
            free_margin=raw.margin_free,
            margin_level=raw.margin_level,
            currency=raw.currency,
        )

    def get_instrument_info(self, symbol):
        info = mt5.symbol_info(symbol)
        if info is None:
            return None
        return InstrumentInfo(
            symbol=symbol,
            tick_size=getattr(info, "trade_tick_size", 0.0) or 0.0,
            tick_value=getattr(info, "trade_tick_value", 0.0) or 0.0,
            point=getattr(info, "point", 0.0) or 0.0,
            digits=getattr(info, "digits", 0) or 0,
            volume_min=getattr(info, "volume_min", 0.0) or 0.0,
            volume_max=getattr(info, "volume_max", 0.0) or 0.0,
            volume_step=getattr(info, "volume_step", 0.0) or 0.0,
            volume_digits=getattr(info, "volume_digits", 2) or 2,
            trade_stops_level=getattr(info, "trade_stops_level", 0) or 0,
            trade_freeze_level=getattr(info, "trade_freeze_level", 0) or 0,
            trade_fillings=getattr(info, "trade_fillings", 0) or 0,
            filling_mode=getattr(info, "filling_mode", 0) or 0,
            trade_exemode=getattr(info, "trade_exemode", 0) or 0,
        )
