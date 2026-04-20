### TASK-054: Implementation — remove trading.py private-method coupling from MT5BrokerAdapter

- **ID**: TASK-054
- **Priority**: P1
- **Status**: done
- **Assigned**: Alex

**Description**
Replace the calls to `trading._send_order()` and `trading._close_position()` inside `MT5BrokerAdapter` with direct MT5 API calls, following the spec produced by Daniel in TASK-053. After this task, no code outside `trading.py` itself will call its private helpers.

**Technical context**

- Relevant files:
  - `src/broker/mt5_adapter.py` — primary target; `send_order` and `close_position` methods
  - `src/broker/interface.py` — `IBrokerAdapter`, `OrderResult` (reference only; do not modify unless the spec adds `modify_tp`)
  - `trading.py` — private helpers to stop calling: `_send_order`, `_close_position`; public helper that may stay: `build_trade_comment`
  - `main.py` — wiring; verify no new instantiation changes are needed after the adapter fix
  - `agents/specs/TASK-053-execution-engine-broker-decoupling-spec.md` — Daniel's spec; implement verbatim

- Current coupling in `MT5BrokerAdapter`:
  - `send_order()` calls `trading.build_trade_comment(...)` then `trading._send_order(...)` (private — to eliminate)
  - `close_position()` calls `trading.build_trade_comment(...)` then `trading._close_position(...)` (private — to eliminate)
  - `modify_sl()` calls `mt5.order_send` directly — already clean, do not touch

- **`modify_tp` — implementar en este sprint** (decisión del usuario). Siguiendo la spec de Daniel:
  - Si `IBrokerAdapter` no declara aún `modify_tp`, Alex añade el método a `src/broker/interface.py` exactamente como Daniel especifique.
  - Alex implementa `MT5BrokerAdapter.modify_tp(symbol, magic, new_tp_price) -> bool` usando el MT5 API call que Daniel documente en la spec.
  - `ExecutionEngine._execute_move_tp` dejará de devolver `not_supported` y pasará a llamar `self._broker.modify_tp(...)` — este cambio en `execution_engine.py` está dentro del scope de TASK-054 si la spec de Daniel lo autoriza.

- **`build_trade_comment` — mover a `src/broker/comment.py`** (decisión del usuario). Alex implementa el movimiento según la spec de Daniel:
  - Crear `src/broker/comment.py` con la función `build_trade_comment` y todos sus helpers (`_sanitize_comment_token`, constantes `_TRADE_COMMENT_PREFIX`, `_MT5_COMMENT_MAX_LEN`, etc.) copiados desde `trading.py`.
  - En `trading.py`: eliminar las definiciones originales y añadir un shim de re-export (`from src.broker.comment import build_trade_comment`) para no romper callers existentes.
  - En `MT5BrokerAdapter` (`src/broker/mt5_adapter.py`): cambiar el import de `build_trade_comment` para que apunte a `src.broker.comment` en lugar de `trading`.
  - Verificar que ningún otro caller externo (fuera de `trading.py` y `MT5BrokerAdapter`) importa `build_trade_comment` directamente de `trading` — si los hay, actualizar esos imports también (o documentarlos; el shim los cubre de todas formas).

- What `_send_order` does (reference for MT5 replacement):
  - Calls `mt5.order_check()` to validate, then `mt5.order_send()` with `TRADE_ACTION_DEAL`
  - Returns a dict with `{success, retcode, ticket, price, volume, comment}`
  - The `MT5BrokerAdapter.send_order()` already converts this dict to an `OrderResult`

- What `_close_position` does (reference for MT5 replacement):
  - Calls `mt5.positions_get(symbol=symbol)`, filters by `magic_number`
  - For each position, calls `mt5.order_send()` with `TRADE_ACTION_DEAL` in the opposite direction (close)
  - Returns a list of result dicts `[{success, retcode, ...}]`

- Key constraints:
  - Do NOT modify `trading.py` internals; the goal is to make the adapter self-sufficient.
  - Do NOT modify `execution_engine.py` — it already calls `self._broker.*` correctly.
  - `trading.build_trade_comment()` is public and may continue to be used by the adapter.
  - Do NOT change `IBrokerAdapter` unless Daniel's spec explicitly requires it.
  - Do NOT touch `gui_charts.py`.
  - The wiring in `main.py` at line ~791 instantiates `ExecutionEngine(broker=MT5BrokerAdapter(), ...)` — this should remain unchanged; Alex must verify it still works after the adapter change.
  - Do NOT use `TRADE_ACTION_SLTP` for closing — that is for SL/TP modification; use `TRADE_ACTION_DEAL` with the opposite direction.

- Blocked by: TASK-053 spec

**Acceptance criteria**

- [ ] `MT5BrokerAdapter.send_order()` no longer imports or calls `trading._send_order()`.
- [ ] `MT5BrokerAdapter.close_position()` no longer imports or calls `trading._close_position()`.
- [ ] Both methods call the MT5 API directly (via `import MetaTrader5 as mt5`) following the pattern described in Daniel's spec.
- [ ] `MT5BrokerAdapter.modify_tp(symbol, magic, new_tp_price) -> bool` implemented using the MT5 API call Daniel specifies.
- [ ] If `IBrokerAdapter` did not already declare `modify_tp`, it is now added to `src/broker/interface.py` per Daniel's spec.
- [ ] `src/broker/comment.py` created with `build_trade_comment` and all its helpers/constants moved from `trading.py`.
- [ ] `trading.py` re-exports `build_trade_comment` from `src.broker.comment` (shim in place; no external caller is broken).
- [ ] `MT5BrokerAdapter` imports `build_trade_comment` from `src.broker.comment`, not from `trading`.
- [ ] No other file has been modified to call `trading._send_order()` or `trading._close_position()`.
- [ ] `main.py` wiring at the `ExecutionEngine` instantiation site is unchanged and correct.
- [ ] A manual smoke-test (or code review) confirms `send_order` and `close_position` would produce equivalent MT5 requests as the private helpers they replace.
- [ ] TASK-055 review can proceed after this is marked done.
