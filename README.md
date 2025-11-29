# Bot de Trading MetaTrader 5

Bot de trading modular y escalable para MetaTrader 5 que implementa una estrategia basada en bandas dinámicas con ATR.

## Estructura del Proyecto

- `config.py` - Configuración del bot (símbolo, timeframe, parámetros de trading, etc.)
- `mt5_connection.py` - Gestión de conexión con MetaTrader 5
- `data_feed.py` - Obtención y procesamiento de datos de mercado
- `strategy_baseline.py` - Lógica de la estrategia de trading
- `trading.py` - Gestión de órdenes y posiciones
- `main.py` - Bucle principal del bot

## Estrategia

La estrategia utiliza:
- **Source**: OHLC4, HLC3, HL2 o CLOSE (configurable)
- **Average**: Media móvil simple sobre el source
- **Bandas**: Average ± (ATR × multiplicador)
- **Señales**:
  - **Compra**: Cuando `Dir_1` cambia a 1 (L_Set > Upper)
  - **Venta**: Cuando `Dir_1` cambia a -1 (H_Set < Lower)

## Requisitos

- MetaTrader 5 instalado y ejecutándose
- Cuenta de trading configurada en MT5
- Python 3.7+

## Instalación

```bash
pip install -r requirements.txt
```

## Configuración

Edita `config.py` para ajustar:
- `SYMBOL`: Símbolo a operar (ej: "DE40" para DAX)
- `TIMEFRAME`: Timeframe de las velas
- `SOURCE_MODE`: Fuente de precio ("OHLC4", "HLC3", "HL2", "CLOSE")
- `MA_LENGTH`: Longitud de la media móvil
- `ATR_LENGTH`: Longitud del ATR
- `ATR_MULT`: Multiplicador del ATR para las bandas
- `LOT`: Tamaño de la posición
- `SL_POINTS`: Stop Loss en puntos
- `TP_POINTS`: Take Profit en puntos
- `MAGIC_NUMBER`: Número mágico para identificar órdenes del bot

## Uso

```bash
python main.py
```

El bot se ejecutará en un bucle continuo, analizando el mercado y ejecutando operaciones según las señales generadas.

Para detener el bot, presiona `Ctrl+C`.

## Notas

- Asegúrate de que MetaTrader 5 esté abierto y conectado antes de ejecutar el bot
- El bot opera en modo demo o real según la cuenta configurada en MT5
- Revisa y ajusta los parámetros de riesgo antes de usar en cuenta real
