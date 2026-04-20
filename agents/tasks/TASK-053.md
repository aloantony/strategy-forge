### TASK-053: Spec — IBrokerAdapter contract audit for ExecutionEngine decoupling

- **ID**: TASK-053
- **Priority**: P1
- **Status**: todo
- **Assigned**: Daniel

**Description**
Audit `IBrokerAdapter` (and its `MT5BrokerAdapter` implementation) against every call that `ExecutionEngine` needs to make, then produce a written spec that Alex can implement verbatim. The goal is to confirm that the interface is complete and correct before any code is touched.

**Technical context**

- Relevant files:
  - `src/broker/interface.py` — `IBrokerAdapter`, `OrderResult`, `InstrumentInfo`
  - `src/broker/mt5_adapter.py` — `MT5BrokerAdapter`
  - `src/runtime/execution_engine.py` — current `ExecutionEngine`
  - `main.py` — instantiation site: `ExecutionEngine(broker=MT5BrokerAdapter(), uow=..., ...)`

- Current state of `ExecutionEngine`:
  - `__init__` already accepts `broker: IBrokerAdapter` (the migration was done in TASK-035).
  - There are **no remaining calls to `trading._send_order()` or `trading._close_position()` inside `execution_engine.py`** — those are delegated to `self._broker.send_order()` and `self._broker.close_position()`.
  - `MT5BrokerAdapter.send_order()` still calls `trading._send_order()` and `MT5BrokerAdapter.close_position()` still calls `trading._close_position()`. This is the remaining coupling: the adapter layer depends on private helpers in `trading.py`.

- Methods `ExecutionEngine` calls on the broker today:
  - `self._broker.send_order(symbol, order_type, lot, magic, sl_price, tp_price, strategy_key, strategy_label, signal_reason) -> OrderResult`
  - `self._broker.close_position(symbol, magic, strategy_key, strategy_label, close_reason) -> bool`
  - `self._broker.modify_sl(symbol, magic, new_sl_price) -> bool`
  - `self._broker.move_take_profit` — currently returns `not_supported`; spec must decide whether to add it to the interface now or defer.

- Key gotchas:
  - `trading._send_order()` is a private function (renamed in TASK-005). Its signature: `(symbol, direction, lot, sl_points, tp_points, magic_number, order_comment, sl_price, tp_price)`.
  - `trading._close_position()` signature: `(symbol, magic_number, order_comment)` — returns a list of result dicts.
  - `trading.build_trade_comment()` is already public and can stay as a shared helper.
  - `modify_sl` in `MT5BrokerAdapter` calls `mt5.order_send` directly — no `trading.py` coupling there.
  - **`modify_tp` — decisión del usuario: se implementa en este sprint.** Daniel debe:
    1. Verificar si `IBrokerAdapter` ya declara `modify_tp(symbol, magic, new_tp_price) -> bool` o si hay que añadirlo a la interfaz en `src/broker/interface.py`.
    2. Especificar qué MT5 API call implementa `modify_tp` (candidato: `mt5.order_send` con `TRADE_ACTION_SLTP`, informando tanto `sl` como `tp` — confirmar que el broker acepta modificar solo TP sin cambiar SL, o si hay que leer el SL actual primero).
    3. Documentar la firma completa del método en la spec.

  - **`build_trade_comment` — decisión del usuario: se mueve a `src/broker/comment.py` (Opción B).** Daniel debe especificar en la spec:
    - La función `build_trade_comment` (y sus helpers `_sanitize_comment_token`, las constantes `_TRADE_COMMENT_PREFIX`, `_MT5_COMMENT_MAX_LEN`, y cualquier otra que use internamente) se mueve de `trading.py` a un nuevo módulo `src/broker/comment.py`.
    - `trading.py` debe re-exportar `build_trade_comment` desde `src/broker/comment.py` para no romper ningún caller existente que ya hace `from trading import build_trade_comment` o `trading.build_trade_comment(...)`.
    - La spec debe indicar el import exacto que `trading.py` añade y confirmar que `MT5BrokerAdapter` importará desde `src.broker.comment` (no desde `trading`) una vez completado el sprint.

**Acceptance criteria**

- [ ] Daniel confirms whether `IBrokerAdapter` is complete for all actions `ExecutionEngine` calls today (send_order, close_position, modify_sl) or whether any gap exists.
- [ ] Daniel specifies whether `modify_tp` is already declared in `IBrokerAdapter` or must be added; if the latter, spec includes the exact method signature to add in `src/broker/interface.py`.
- [ ] Daniel specifies what MT5 API call implements `modify_tp` (confirming whether TRADE_ACTION_SLTP is the correct action and whether the current SL must be read first to avoid resetting it).
- [ ] Daniel documents the exact mapping from each `ExecutionEngine` call to its `IBrokerAdapter` method signature, noting any parameter name or type mismatches.
- [ ] Daniel documents what `MT5BrokerAdapter.send_order()` and `MT5BrokerAdapter.close_position()` should do instead of calling `trading._send_order()` / `trading._close_position()` — i.e., what MT5 API calls replace those private helpers.
- [ ] Daniel specifies the move of `build_trade_comment` (and its helpers/constants) from `trading.py` to `src/broker/comment.py`, including: the exact list of symbols to move, the re-export shim in `trading.py`, and which callers (starting with `MT5BrokerAdapter`) should update their import.
- [ ] Spec written to `agents/specs/TASK-053-execution-engine-broker-decoupling-spec.md`.
- [ ] TASK-054 is unblocked after this spec.
