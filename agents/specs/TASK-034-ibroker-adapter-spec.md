# Pre-Implementation: IBrokerAdapter Protocol

**By**: Daniel
**Date**: 2026-04-11
**Task**: TASK-034
**Status**: ready

---

## Formal Problem Statement

**Input**: El sistema actual tiene tres capas que acoplan MT5 directamente:
1. `ExecutionEngine` (`src/runtime/execution_engine.py`) llama a `self._trading._send_order()` y `self._trading._close_position()` con firmas que **no coinciden** con las funciones privadas actuales de `trading.py`. También hace llamadas directas a `MetaTrader5` en `_execute_move_sl`.
2. `main.py` y `gui_charts.py` llaman a funciones de `trading.py` y directamente a `mt5.positions_get()` / `mt5.account_info()`.
3. `calculate_dynamic_lot()` y `check_aggregate_risk()` en `trading.py` llaman `mt5.symbol_info()` y `mt5.account_info()` internamente, impidiendo su uso en backtest sin MT5.

**Output**: Un protocolo `IBrokerAdapter` (`abc.ABC`) con firmas tipadas, un dataclass `InstrumentInfo`, un dataclass `OrderResult`, las firmas actualizadas de `calculate_dynamic_lot` / `check_aggregate_risk`, y la firma nueva de `ExecutionEngine.__init__`.

**Constraints**:
- `trading.py` no se rompe — sigue existiendo; `MT5BrokerAdapter` lo envuelve
- No se diseña `IDataProvider` / `IDataFeed` — eso es TASK-036
- La interfaz vive en `src/broker/interface.py`; el adaptador en `src/broker/mt5_adapter.py`
- Python 3.10+; usar `abc.ABC` + `@abstractmethod`; dataclasses con `from dataclasses import dataclass`

**Invariants**:
- `MT5BrokerAdapter` es el único punto de contacto con `trading.py` y con `mt5` directamente
- Las funciones puras `calculate_dynamic_lot` y `check_aggregate_risk` reciben `InstrumentInfo` en lugar de llamar MT5; el caller las obtiene vía `broker.get_instrument_info()`
- `ExecutionEngine` nunca importa `trading` ni `MetaTrader5` directamente

**Clarity**: ✅ clara

---

## Inventario de call sites — métodos privados de `trading.py` en `execution_engine.py`

### Call site 1 — `_execute_open` (línea 173)

```python
result = self._trading._send_order(
    symbol=symbol,
    order_type=order_type,      # 0=BUY, 1=SELL (constantes MT5)
    lot=volume,
    magic=self._magic,
    sl_price=sl_price,
    tp_price=tp_price,
    strategy_key=self._strategy_key,
    strategy_label=self._strategy_key,
    signal_reason=reason,
)
```

**Mismatch con `trading._send_order` actual**:

| Kwarg que usa EE | Param en `trading._send_order` | Diferencia |
|---|---|---|
| `order_type=0\|1` | `direction=1\|-1` | Semántica opuesta (MT5 vs dirección propia) |
| `magic=` | `magic_number=` | Solo nombre |
| `strategy_key`, `strategy_label`, `signal_reason` | `order_comment=` | EE espera que el adapter construya el comment |
| — | `sl_points`, `tp_points` | No existen en la llamada de EE (usa `sl_price`/`tp_price`) |

Consumo del resultado (líneas 185–187):
```python
success = result is not None and getattr(result, "retcode", -1) == 10009
broker_order_id = str(getattr(result, "order", "")) if result else None
broker_deal_id  = str(getattr(result, "deal", ""))  if result else None
```
→ EE espera un objeto con atributos `.retcode`, `.order`, `.deal`.

### Call site 2 — `_execute_close` (línea 267)

```python
success = self._trading._close_position(
    symbol=symbol,
    magic=self._magic,
    strategy_key=self._strategy_key,
    strategy_label=self._strategy_key,
    close_reason=reason,
)
```

**Mismatch con `trading._close_position` actual**:

| Kwarg que usa EE | Param en `trading._close_position` | Diferencia |
|---|---|---|
| `magic=` | `magic_number=` | Solo nombre |
| `strategy_key`, `strategy_label`, `close_reason` | `order_comment=` | EE espera que el adapter construya el comment |

`trading._close_position` devuelve una `list` de dicts; EE espera un `bool`. El adapter debe convertir.

### Call site 3 — `_execute_move_sl` (líneas 322–338)

```python
import MetaTrader5 as mt5
positions = mt5.positions_get(symbol=symbol, group=f"*{self._magic}*") or \
            [p for p in (mt5.positions_get(symbol=symbol) or []) if p.magic == self._magic]
for pos in positions:
    request = { "action": mt5.TRADE_ACTION_SLTP, ... }
    result = mt5.order_send(request)
```

EE llama MT5 **directamente** — bypasa `trading_module` por completo. Este es el acoplamiento más crítico a resolver.

---

## Candidate Designs para el protocolo

### Opción A — Thin facade (solo lo que ExecutionEngine necesita)

Expone únicamente: `send_order`, `close_position`, `modify_sl`.

- **Time/Space**: n/a (interfaz)
- **Verdict**: eliminada
- **Reason**: `main.py` y `gui_charts.py` seguirían acoplados a `trading.py` directamente. No logra el objetivo de desacoplamiento total de MT5.

### Opción B — Full execution facade (todas las operaciones de ejecución, sin datos)

Expone: `send_order`, `close_position`, `modify_sl`, `apply_signal`, `apply_pyramid_signal`, `is_market_open`, `get_open_positions`, `get_account_info`, `get_instrument_info`.

- **Verdict**: seleccionada
- **Reason**: `main.py` y `gui_charts.py` migran a usar `broker.*` en lugar de `trading.*` + `mt5.*` directos. Un único punto de sustitución para backtest/otros brokers.

### Opción C — Command pattern (acciones como objetos enviados al broker)

Cada acción es un dataclass (`OpenOrder`, `ClosePosition`); el broker los procesa en batch.

- **Verdict**: eliminada
- **Reason**: Over-engineering para v1. EE ya normaliza acciones internamente. El adapter solo necesita ejecutar llamadas simples, no reimplementar el pipeline de normalización.

---

## Selected Design

**Winner**: Opción B — Full execution facade

**Justification**: El objetivo declarado (TASK-034 task file + context.md) es que el sistema pueda ejecutarse sin MT5 instalado. Eso requiere que `main.py`, `gui_charts.py` y `ExecutionEngine` no tengan ninguna referencia directa a `trading` ni a `mt5`. Opción B es el mínimo necesario para lograrlo. Opción A es insuficiente; Opción C añade complejidad sin beneficio en v1.

---

## Pseudocode Spec

### Archivo: `src/broker/interface.py`

```
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class InstrumentInfo:
    symbol: str
    tick_size: float          # symbol_info.trade_tick_size
    tick_value: float         # symbol_info.trade_tick_value
    point: float              # symbol_info.point
    digits: int               # symbol_info.digits
    volume_min: float         # symbol_info.volume_min
    volume_max: float         # symbol_info.volume_max
    volume_step: float        # symbol_info.volume_step
    volume_digits: int        # symbol_info.volume_digits
    trade_stops_level: int    # symbol_info.trade_stops_level
    trade_freeze_level: int   # symbol_info.trade_freeze_level
    trade_fillings: int       # symbol_info.trade_fillings (bitmask)
    filling_mode: int         # symbol_info.filling_mode
    trade_exemode: int        # symbol_info.trade_exemode


@dataclass
class OrderResult:
    success: bool
    retcode: int              # 10009 = TRADE_RETCODE_DONE (MT5); adaptadores no-MT5 usan 10009 para éxito
    order_id: str             # broker order id
    deal_id: str              # broker deal id
    comment: str              # broker response comment
    price: float = 0.0
    volume: float = 0.0


@dataclass
class AccountInfo:
    balance: float
    equity: float
    margin: float
    free_margin: float
    margin_level: float       # porcentaje (e.g. 150.0 = 150%)
    currency: str


class IBrokerAdapter(ABC):

    # ------------------------------------------------------------------
    # Ejecución de órdenes (usadas por ExecutionEngine)
    # ------------------------------------------------------------------

    @abstractmethod
    def send_order(
        self,
        symbol: str,
        order_type: int,          # 0=BUY, 1=SELL (convención MT5)
        lot: float,
        magic: int,
        sl_price: float,
        tp_price: float,
        strategy_key: str = "",
        strategy_label: str = "",
        signal_reason: str = "",
    ) -> OrderResult:
        # Abre una posición nueva. El adaptador construye el comment de orden.
        ...

    @abstractmethod
    def close_position(
        self,
        symbol: str,
        magic: int,
        strategy_key: str = "",
        strategy_label: str = "",
        close_reason: str = "",
    ) -> bool:
        # Cierra todas las posiciones abiertas para symbol+magic.
        # Devuelve True si al menos una posición fue cerrada con éxito.
        ...

    @abstractmethod
    def modify_sl(
        self,
        symbol: str,
        magic: int,
        new_sl_price: float,
    ) -> bool:
        # Modifica el stop loss de todas las posiciones abiertas para symbol+magic.
        ...

    # ------------------------------------------------------------------
    # Señales de alto nivel (usadas por main.py y gui_charts.py)
    # ------------------------------------------------------------------

    @abstractmethod
    def apply_signal(
        self,
        symbol: str,
        signal: str,              # "buy" | "sell" | "none"
        lot: float,
        sl_points: float,
        tp_points: float,
        magic_number: int,
        strategy_key: str = "",
        strategy_label: str = "",
        signal_reason: str = "",
    ) -> Optional[dict]:
        # Traduce la señal en acciones: abre/cierra posiciones.
        # Devuelve dict con resultado o None si no se ejecutó nada.
        ...

    @abstractmethod
    def apply_pyramid_signal(
        self,
        symbol: str,
        magic_number: int,
        atr_value: float,
        lot: float,
        strategy_key: str = "",
        strategy_label: str = "",
        signal_reason: str = "",
        balance: Optional[float] = None,
    ) -> Optional[dict]:
        # Entrada inicial o piramidado solo-largo con SL/TP basados en ATR.
        ...

    # ------------------------------------------------------------------
    # Estado del mercado y cuenta (usadas por main.py, gui_charts.py)
    # ------------------------------------------------------------------

    @abstractmethod
    def is_market_open(self, symbol: str) -> tuple[bool, str]:
        # (True, "Tick reciente (3 s)") o (False, "Sin tick reciente")
        ...

    @abstractmethod
    def get_open_positions(self, symbol: str, magic_number: int) -> list[dict]:
        # Lista de posiciones abiertas para symbol+magic.
        # Cada dict: {"ticket", "type", "volume", "price_open",
        #             "price_current", "profit", "sl", "tp", "time_open"}
        # Equivale a trading.get_all_positions().
        ...

    @abstractmethod
    def get_account_info(self) -> Optional[AccountInfo]:
        # Información de la cuenta. None si no disponible.
        ...

    @abstractmethod
    def get_instrument_info(self, symbol: str) -> Optional[InstrumentInfo]:
        # Información del instrumento para cálculos de sizing.
        # None si el símbolo no existe o no está disponible.
        ...
```

---

### Archivo: `src/broker/mt5_adapter.py`

```
import trading  # el módulo trading.py del proyecto raíz
import MetaTrader5 as mt5
from src.broker.interface import (
    IBrokerAdapter, InstrumentInfo, OrderResult, AccountInfo
)

TRADE_RETCODE_DONE = 10009


class MT5BrokerAdapter(IBrokerAdapter):

    def send_order(self, symbol, order_type, lot, magic,
                   sl_price, tp_price, strategy_key, strategy_label, signal_reason):
        # Mapeo de convenciones:
        #   order_type=0 (BUY) → direction=1
        #   order_type=1 (SELL) → direction=-1
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
            sl_points=0,          # se usa sl_price/tp_price en su lugar
            tp_points=0,
            magic_number=magic,
            order_comment=comment,
            sl_price=sl_price or 0.0,
            tp_price=tp_price or 0.0,
        )

        # raw es un dict con "success", "ticket", "retcode", "comment", "price", "volume"
        if raw is None:
            return OrderResult(success=False, retcode=-1, order_id="", deal_id="", comment="")

        success = raw.get("success", False)
        retcode = raw.get("retcode") or (-1 if not success else TRADE_RETCODE_DONE)
        return OrderResult(
            success=success,
            retcode=retcode if retcode is not None else -1,
            order_id=str(raw.get("ticket") or ""),
            deal_id="",           # trading._send_order no devuelve deal_id; se obtiene de history
            comment=str(raw.get("comment") or ""),
            price=raw.get("price", 0.0),
            volume=raw.get("volume", 0.0),
        )

    def close_position(self, symbol, magic, strategy_key, strategy_label, close_reason):
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
        # results es una list de dicts con "success"
        if not results:
            return False
        return any(r.get("success", False) for r in results)

    def modify_sl(self, symbol, magic, new_sl_price):
        # Contiene la lógica actualmente inline en ExecutionEngine._execute_move_sl
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
                     magic_number, strategy_key, strategy_label, signal_reason):
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
                              strategy_key, strategy_label, signal_reason, balance=None):
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
```

---

### Firma actualizada de `ExecutionEngine.__init__`

```
# ANTES (actual)
def __init__(
    self,
    trading_module,          # módulo concreto trading.py
    uow,
    symbol: str,
    magic_number: int,
    strategy_key: str,
    instance_id: str,
    mode: str = "live",
):
    self._trading = trading_module   # acoplamiento directo

# DESPUÉS (TASK-035)
def __init__(
    self,
    broker: IBrokerAdapter,          # reemplaza trading_module
    uow,
    symbol: str,
    magic_number: int,
    strategy_key: str,
    instance_id: str,
    mode: str = "live",
):
    self._broker = broker            # el engine nunca importa trading ni mt5
```

Los métodos de `ExecutionEngine` se actualizan de forma correspondiente:
- `self._trading._send_order(...)` → `self._broker.send_order(...)`
- `self._trading._close_position(...)` → `self._broker.close_position(...)`
- Inline MT5 en `_execute_move_sl` → `self._broker.modify_sl(...)`

---

### Firmas actualizadas de `calculate_dynamic_lot` y `check_aggregate_risk`

Estas funciones permanecen en `trading.py` pero dejan de llamar a MT5 internamente. El parámetro `symbol: str` se reemplaza por `instrument_info: InstrumentInfo`.

```
# calculate_dynamic_lot — ANTES
def calculate_dynamic_lot(
    symbol: str,
    atr_value: float,
    volume_ratio: float,
    balance: float = None,        # si None, llama mt5.account_info() internamente
) -> float

# calculate_dynamic_lot — DESPUÉS
def calculate_dynamic_lot(
    atr_value: float,
    volume_ratio: float,
    instrument_info: InstrumentInfo,
    balance: float,               # siempre requerido; caller lo obtiene de broker.get_account_info()
) -> float

# Pseudocode:
function calculate_dynamic_lot(atr_value, volume_ratio, instrument_info, balance):
    if atr_value <= 0 or volume_ratio <= 0 or balance <= 0:
        return 0.0
    tick_size  = instrument_info.tick_size
    tick_value = instrument_info.tick_value
    if tick_size <= 0 or tick_value <= 0:
        return 0.0
    target_risk_pct = min(volume_ratio * 0.005, 0.01)
    risk_money      = target_risk_pct * balance
    risk_per_lot    = atr_value * (tick_value / tick_size)
    if risk_per_lot <= 0:
        return 0.0
    return risk_money / risk_per_lot
    # nota: resultado sin normalizar; caller pasa por normalize_volume()


# check_aggregate_risk — ANTES
def check_aggregate_risk(
    symbol: str,
    new_lot: float,
    atr_value: float,
    balance: float,
    open_positions: list,
) -> tuple[bool, float]

# check_aggregate_risk — DESPUÉS
def check_aggregate_risk(
    new_lot: float,
    atr_value: float,
    balance: float,
    open_positions: list,
    instrument_info: InstrumentInfo,
) -> tuple[bool, float]

# Pseudocode:
function check_aggregate_risk(new_lot, atr_value, balance, open_positions, instrument_info):
    AGGREGATE_RISK_LIMIT = 0.03
    if balance <= 0:
        return (False, 0.0)
    tick_size  = instrument_info.tick_size
    tick_value = instrument_info.tick_value
    if tick_size <= 0 or tick_value <= 0:
        return (False, 0.0)
    value_per_price_unit_per_lot = tick_value / tick_size
    existing_risk_money = 0.0
    for pos in open_positions where pos["type"] == "BUY" and pos["sl"] > 0:
        distance = pos["price_open"] - pos["sl"]
        if distance > 0:
            existing_risk_money += pos["volume"] * distance * value_per_price_unit_per_lot
    new_entry_risk    = new_lot * atr_value * value_per_price_unit_per_lot
    total_risk_money  = existing_risk_money + new_entry_risk
    aggregate_risk_pct = total_risk_money / balance
    return (aggregate_risk_pct <= AGGREGATE_RISK_LIMIT, aggregate_risk_pct)
```

**Impacto en callers actuales de estas funciones:**

`main.py` y `gui_charts.py` llaman así actualmente:
```python
raw_lot = trading.calculate_dynamic_lot(symbol, atr_val, vol_ratio, balance)
allowed, pct = check_aggregate_risk(symbol, new_lot, atr, balance, positions)
```

Después de TASK-035, el patrón de llamada será:
```python
instrument_info = broker.get_instrument_info(symbol)
raw_lot = trading.calculate_dynamic_lot(atr_val, vol_ratio, instrument_info, balance)
allowed, pct = trading.check_aggregate_risk(new_lot, atr, balance, positions, instrument_info)
```

Felix debe actualizar todos los call sites en `main.py`, `gui_charts.py` y cualquier estrategia que llame estas funciones directamente.

---

## Scope de TASK-035

Felix implementa en TASK-035:

1. Crear `src/broker/` con `__init__.py` vacío
2. Crear `src/broker/interface.py` con los dataclasses y la clase abstracta según el pseudocode de arriba
3. Crear `src/broker/mt5_adapter.py` con `MT5BrokerAdapter` según el pseudocode de arriba
4. Actualizar `src/runtime/execution_engine.py`: reemplazar `trading_module` por `broker: IBrokerAdapter` en `__init__`; actualizar `_execute_open`, `_execute_close`, `_execute_move_sl` para usar `self._broker.*`
5. Actualizar firma de `calculate_dynamic_lot` y `check_aggregate_risk` en `trading.py` (quitar `symbol`, añadir `instrument_info: InstrumentInfo`)
6. Actualizar todos los call sites en `main.py` y `gui_charts.py`

**Lo que NO hace TASK-035**: no crea `IDataFeed` ni `IHistoricalDataSource` — eso es TASK-036.

---

## Notas críticas para Felix

### Mismatch de `OrderResult.deal_id`

`trading._send_order` devuelve un dict con `"ticket"` (order ID) pero **no incluye deal_id**. En MT5, el deal_id se obtiene de `history_deals_get()` después del fill. Para v1, `deal_id=""` es aceptable — `ExecutionEngine._execute_open` usa `deal_id` solo para persistencia (`_persist_fill`), y el campo puede quedarse vacío sin romper nada.

### Retcode en `OrderResult`

`trading._send_order` devuelve `result["retcode"]` que viene de `mt5_result.retcode` (puede ser None si MT5 retorna None). El adaptador debe garantizar que `OrderResult.retcode` nunca sea None — usar `-1` como sentinel para "sin resultado".

`ExecutionEngine._execute_open` evalúa: `getattr(result, "retcode", -1) == 10009`. Después de TASK-035 esto cambia a `result.success` (más directo). Felix puede simplificar este check al migrar.

### `apply_pyramid_signal` en la interfaz

`apply_pyramid_signal` internamente llama `mt5.account_info()` para obtener balance si no se pasa. Con el adaptador, `balance` siempre debe ser pasado por el caller (obtenido de `broker.get_account_info().balance`). `MT5BrokerAdapter.apply_pyramid_signal` delega directamente a `trading.apply_pyramid_signal`, que mantiene la llamada interna a `mt5.account_info()` por ahora — esto es aceptable para v1 dado que `MT5BrokerAdapter` ya está acoplado a MT5 por definición.
