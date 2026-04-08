# Principios Base

## Diagnostico del sistema actual

El sistema actual del repo esta orientado a estrategias que emiten una senal:
- `buy`
- `sell`
- `none`

Eso sirve para plugins de senal, pero no para algoritmos completos.

Hoy la estrategia puede:
- preparar columnas
- calcular indicadores
- detectar contexto de entrada o salida

Hoy la estrategia no gobierna de forma natural:
- sizing dinamico
- riesgo por ticker o cartera
- pyramiding
- parciales
- trailing stop
- break even
- pending orders complejas
- reglas avanzadas de gestion de posicion

## Vision objetivo

Queremos un supersistema donde la estrategia pueda decidir todo lo posible a
nivel de negocio de trading.

Eso incluye, segun la estrategia:
- trigger de entrada
- trigger de salida
- sesgo long o short
- sizing
- stop loss
- take profit
- trailing
- parciales
- pyramiding
- cooldowns
- filtros horarios
- riesgo definido por la propia estrategia

## Limite correcto de soberania

La estrategia debe tener soberania sobre la logica de trading.

El core NO debe imponer limites financieros hardcodeados del tipo:
- riesgo maximo por trade
- riesgo maximo por ticker
- perdida diaria maxima

Si esos limites existen, deben venir de la estrategia o de opciones activadas
explicitamente por el usuario.

## Lo que sigue perteneciendo al motor

Aunque la estrategia decida la logica, el motor debe seguir siendo el dueno de
la fontaneria tecnica:
- conexion con broker
- envio de ordenes
- reintentos
- normalizacion de volumen
- validacion de lot step, min lot, max lot
- validacion tecnica de precios y stops
- consistencia del estado interno
- logging, replay, backtest y paper trading

Resumen:
- la estrategia decide QUE quiere hacer
- el motor decide COMO se ejecuta tecnicamente

## Modelo mental acordado

La unidad de decision de una estrategia debe ser:

`contexto + estado_anterior -> plan + estado_nuevo`

Definiciones:
- `contexto`: foto completa y de solo lectura del sistema en ese instante
- `estado_anterior`: memoria privada y serializable de la estrategia
- `plan`: conjunto de acciones que la estrategia quiere ejecutar
- `estado_nuevo`: memoria actualizada tras la decision

## Principios de diseno

1. La estrategia no debe tocar directamente MT5 ni el broker.
2. La estrategia no debe depender de hacks con variables globales.
3. El estado de estrategia debe ser explicito, serializable y restaurable.
4. La realidad del broker y la memoria estrategica no deben mezclarse.
5. El mismo modelo debe servir para live, demo, paper y backtest.
6. El core debe ser agnostico respecto a la logica financiera concreta.

## Estado actual de la propuesta

Ya definidos:
- principios base
- modelo `plan + actions`
- modelo de `contexto` v1
- modelo de `state` v1
- contrato del interprete de `actions`
- convivencia multi-estrategia v1
- modelo canonico de recursos operativos v1
- targeting y lifecycle de actions v1
- catalogo de actions v1
- modelo de `execution_report` y `event_log` v1
- backend de persistencia v1 recomendado
- esquema fisico SQLite v1 propuesto
- plan de migraciones SQL v1
- modulo de persistencia y DAL v1
- estrategia de adopcion incremental sobre el codebase actual
- contrato del adaptador legacy -> v1
- contrato del modulo de estrategia v1
- politica de concurrencia y reintentos de ejecucion v1
- politica de snapshots y reconciliacion con broker v1
- impacto en latencia operativa v1
- politica de versionado y compatibilidad de schemas v1

Siguen abiertos:
- politica futura para cuentas `netting` con libro sintetico compartido
  Nota: queda explicitamente postergada fuera del alcance actual; mientras
  tanto rige enfoque `hedging-first` y `single_owner_per_symbol` en `netting`.
- politicas exactas de retencion, compactacion y export
- politica de deprecacion final del contrato `get_last_signal()`
