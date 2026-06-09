# Rollback Builder MTF v2

## Punto de control

- Rama de trabajo: `feature/builder-mtf-v2`.
- La implementación v2 usa `schema_version: 2` y `mode: "multi_timeframe"`.
- Las estrategias existentes `schema_version: 1` no se migran automáticamente.

## Apagado rápido

1. En `config.py`, mantener o volver a poner:
   ```python
   ENABLE_BUILDER_MTF = False
   ```
2. No crear ni editar estrategias `schema_version: 2` desde la UI.
3. Las estrategias v1 siguen usando el generador anterior y el contrato `prepare_dataframe` / `get_last_signal_payload`.

## Vuelta a versión anterior

Si se necesita retirar v2 por completo:

1. Cambiar a la rama estable previa, normalmente `main`.
2. No copiar archivos `strategy_*.json` con `schema_version: 2` al entorno estable.
3. Si existen estrategias v2 en `strategies/`, deshabilitarlas desde el registro o moverlas fuera del directorio antes de arrancar el bot estable.

## Identificación de artefactos v2

Una estrategia v2 contiene:

```json
{
  "schema_version": 2,
  "mode": "multi_timeframe"
}
```

El módulo Python generado expone:

- `SCHEMA_VERSION = 2`
- `MODE = "multi_timeframe"`
- `REQUIRED_TIMEFRAMES = [...]`
- `prepare_frames(frames)`
- `get_last_signal_payload_mtf(frames, ...)`

## Garantías de compatibilidad

- `schema_version: 1` conserva el generador v1.
- `schema_version: 2` se despacha a un generador separado.
- El runtime detecta MTF por presencia de `prepare_frames` o `get_last_signal_payload_mtf`; si no existen, usa el flujo v1.

