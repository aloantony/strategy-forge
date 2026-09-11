# Strategy Forge — https://github.com/aloantony/strategy-forge
# Required Notice: Copyright 2026 aloantony (https://github.com/aloantony)
# Licensed under the PolyForm Noncommercial License 1.0.0 — see LICENSE, or
# <https://polyformproject.org/licenses/noncommercial/1.0.0>. Noncommercial use
# is free; commercial use, including production use, requires a written
# agreement with the copyright holder.

from backend.brokers.mt5 import trading
from backend.brokers.mt5_import import mt5
from backend.brokers.interface import IBrokerAdapter, InstrumentInfo, OrderResult, AccountInfo
from backend.brokers.comment import build_trade_comment, _FALLBACK_OPEN_COMMENT, _FALLBACK_CLOSE_COMMENT

TRADE_RETCODE_DONE = 10009

_DEFAULT_OPEN_COMMENT  = "Bot trading"
_DEFAULT_CLOSE_COMMENT = "Cierre automatico"


class MT5BrokerAdapter(IBrokerAdapter):

    def send_order(self, symbol, order_type, lot, magic,
                   sl_price, tp_price, strategy_key="", strategy_label="", signal_reason=""):
        if mt5 is None:
            raise RuntimeError("MT5BrokerAdapter: MT5 no está conectado.")
        direction = 1 if order_type == 0 else -1

        symbol_info = mt5.symbol_info(symbol)
        if symbol_info is None:
            return OrderResult(success=False, retcode=-1, order_id="", deal_id="",
                               comment="symbol_info unavailable")

        if not symbol_info.visible:
            mt5.symbol_select(symbol, True)

        tick = mt5.symbol_info_tick(symbol)
        ask  = tick.ask if tick else 0.0
        bid  = tick.bid if tick else 0.0

        if direction == 1:   # BUY
            price     = ask
            order_mt5 = mt5.ORDER_TYPE_BUY
        else:                # SELL
            price     = bid
            order_mt5 = mt5.ORDER_TYPE_SELL

        sl = sl_price or 0.0
        tp = tp_price or 0.0

        lot, volume_note = trading.normalize_volume(lot, symbol_info)
        if lot <= 0:
            return OrderResult(success=False, retcode=-1, order_id="", deal_id="",
                               comment=f"volume invalid: {volume_note}")

        sl, tp, _ = trading.adjust_stops(direction, price, sl, tp, symbol_info, tick)

        filling_mode = trading.choose_filling_mode(symbol_info)
        comment_str  = build_trade_comment(
            strategy_key=strategy_key,
            signal_reason=signal_reason,
            action_kind="open",
        )
        request_comment = comment_str or _DEFAULT_OPEN_COMMENT

        request = {
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       symbol,
            "volume":       lot,
            "type":         order_mt5,
            "price":        price,
            "sl":           sl,
            "tp":           tp,
            "deviation":    20,
            "magic":        magic,
            "comment":      request_comment,
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": filling_mode,
        }

        result, used_mode, tried_modes, last_error = trading.order_send_with_filling_retry(
            request, symbol_info
        )
        success = result is not None and result.retcode == TRADE_RETCODE_DONE

        return OrderResult(
            success  = success,
            retcode  = result.retcode if result else -1,
            order_id = str(getattr(result, "order", "") or ""),
            deal_id  = "",
            comment  = str(getattr(result, "comment", "") or ""),
            price    = price,
            volume   = lot,
        )

    def close_position(self, symbol, magic, strategy_key="", strategy_label="", close_reason=""):
        comment_str = build_trade_comment(
            strategy_key=strategy_key,
            signal_reason=close_reason,
            action_kind="close",
        )
        request_comment = comment_str or _DEFAULT_CLOSE_COMMENT

        positions = mt5.positions_get(symbol=symbol) or []
        positions = [p for p in positions if p.magic == magic]

        if not positions:
            return False

        symbol_info = mt5.symbol_info(symbol)
        if symbol_info is None:
            return False

        filling_mode = trading.choose_filling_mode(symbol_info)

        any_success = False
        for pos in positions:
            request = {
                "action":       mt5.TRADE_ACTION_DEAL,
                "symbol":       symbol,
                "volume":       pos.volume,
                "type":         mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY
                                else mt5.ORDER_TYPE_BUY,
                "position":     pos.ticket,
                "deviation":    20,
                "magic":        magic,
                "comment":      request_comment,
                "type_time":    mt5.ORDER_TIME_GTC,
                "type_filling": filling_mode,
            }
            result, used_mode, tried, last_error = trading.order_send_with_filling_retry(
                request, symbol_info
            )
            if result and result.retcode == TRADE_RETCODE_DONE:
                any_success = True

        return any_success

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

    def modify_tp(self, symbol, magic, new_tp_price):
        try:
            positions = mt5.positions_get(symbol=symbol) or []
            positions = [p for p in positions if p.magic == magic]
            success = False
            for pos in positions:
                request = {
                    "action": mt5.TRADE_ACTION_SLTP,
                    "position": pos.ticket,
                    "symbol": symbol,
                    "sl": pos.sl,          # preserve current SL — do not zero it out
                    "tp": new_tp_price,    # new TP value
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
                              strategy_key="", strategy_label="", signal_reason="", balance=None,
                              sl_atr_mult=1.0, tp_atr_mult=2.0, pyramid_atr_mult=0.5,
                              max_entries=None, entry_index=None, direction=1):
        return trading.apply_pyramid_signal(
            symbol=symbol,
            magic_number=magic_number,
            atr_value=atr_value,
            lot=lot,
            strategy_key=strategy_key,
            strategy_label=strategy_label,
            signal_reason=signal_reason,
            balance=balance,
            sl_atr_mult=sl_atr_mult,
            tp_atr_mult=tp_atr_mult,
            pyramid_atr_mult=pyramid_atr_mult,
            max_entries=max_entries,
            entry_index=entry_index,
            direction=direction,
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
