# src/broker/comment.py
# Comment-building helpers for MT5 order comments.
# Moved from trading.py per TASK-053/054.

import re

_TRADE_COMMENT_PREFIX    = "TA"
_MT5_COMMENT_MAX_LEN     = 31
_STRATEGY_TOKEN_MAX_LEN  = 10
_REASON_TOKEN_MAX_LEN    = 24
_FALLBACK_OPEN_COMMENT   = "TAOPEN"
_FALLBACK_CLOSE_COMMENT  = "TACLOSE"


def _sanitize_comment_token(value: str, max_len: int) -> str:
    # compacta un texto libre en un token seguro para el comentario de MT5.
    token = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower())
    token = re.sub(r"_+", "_", token).strip("_")
    if not token:
        return ""
    return token[:max_len].strip("_")


def build_trade_comment(
    strategy_key: str = "",
    signal_reason: str = "",
    action_kind: str = "open"
) -> str:
    # arma comentario compacto para recuperar motivo desde history_deals_get.
    action_code = "o" if str(action_kind or "").strip().lower() == "open" else "c"
    strategy_token = _sanitize_comment_token(strategy_key, _STRATEGY_TOKEN_MAX_LEN)
    reason_token = _sanitize_comment_token(signal_reason, _REASON_TOKEN_MAX_LEN)
    parts = [_TRADE_COMMENT_PREFIX, action_code]
    if strategy_token:
        parts.append(f"s={strategy_token}")
    if reason_token:
        parts.append(f"r={reason_token}")
    comment = "|".join(parts)
    if len(comment) <= _MT5_COMMENT_MAX_LEN:
        return comment

    # Prioriza conservar un motivo legible antes que el token de estrategia.
    if strategy_token and reason_token:
        no_strategy = "|".join([_TRADE_COMMENT_PREFIX, action_code, f"r={reason_token}"])
        if len(no_strategy) <= _MT5_COMMENT_MAX_LEN:
            return no_strategy

    # Ajuste progresivo por si el broker limita el tamaño del comentario.
    if reason_token:
        allowed_reason_len = max(4, _MT5_COMMENT_MAX_LEN - len("|".join(parts[:-1])) - 3)
        reason_token = reason_token[:allowed_reason_len].strip("_")
        parts[-1] = f"r={reason_token}" if reason_token else ""
        parts = [p for p in parts if p]
    comment = "|".join(parts)
    if len(comment) <= _MT5_COMMENT_MAX_LEN:
        return comment

    if strategy_token:
        # Si aún excede, prioriza conservar acción + motivo.
        parts = [_TRADE_COMMENT_PREFIX, action_code]
        if reason_token:
            parts.append(f"r={reason_token}")
    comment = "|".join(parts)
    return comment[:_MT5_COMMENT_MAX_LEN]
