SISTEMA DE TRADING - ARQUITECTURA

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

INDICADORES
  · ATR (14 períodos) → unidad de volatilidad
  · ADX + DI (14 períodos) → trigger
  · SMA Volumen (20 períodos) → sizing

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

TRIGGER LONG
  ADX > 25
  + +DI cruza por encima de -DI

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

GESTIÓN DE ENTRADA
  ¿Riesgo agregado ticker < 3%?
      ├── NO → Ignorar señal
      └── SÍ → ¿Hay posición abierta?
                  ├── NO → Entrada inicial
                  └── SÍ → ¿Precio avanzó 0.5×ATR
                            desde última entrada?
                                ├── NO → Esperar
                                └── SÍ → Nueva entrada piramiada

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

POR CADA ENTRADA (inicial o piramiada)
  · SL = precio entrada − 1×ATR
  · TP = precio entrada + 2×ATR
  · Tamaño = (volumen actual / SMA20) × 0.5%
             con techo en 1% de la cartera
  · Verificar que riesgo agregado < 3%

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

REGLAS
  · Solo largos
  · Cada posición es independiente
  · Máximo riesgo simultáneo por ticker: 3%
  · Máximo riesgo por operación: 1%