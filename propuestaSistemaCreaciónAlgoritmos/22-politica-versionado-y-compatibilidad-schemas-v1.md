# Politica De Versionado Y Compatibilidad De Schemas v1

## Objetivo

Definir una politica unica y coherente para todos los schemas relevantes del
supersistema.

Incluye:
- schema fisico SQLite
- schema del modulo de estrategia
- schema del `plan`
- schema del `state`
- schema de `execution_report`
- schema de `event_log`

No basta con poner numeros de version.

Hay que decidir:
- que versiones puede leer el sistema
- que versiones puede ejecutar
- que versiones puede migrar
- cuando debe rechazar algo
- quien es responsable de cada migracion

## Problema de fondo

Sin politica de compatibilidad, cada cambio estructural deja preguntas peligrosas:
- una estrategia vieja sigue cargando o no
- un `state` viejo se puede leer o no
- una DB vieja se migra sola o no
- un `plan` con formato antiguo se ejecuta o no
- un `event_log` historico sigue siendo interpretable o no

En trading automatizado, no responder esto con claridad es mala arquitectura.

## Idea central

La politica correcta no es "ser compatible con todo para siempre".

La politica correcta es:
- ser estrictos en la ruta de ejecucion live
- ser tolerantes en la ruta de lectura historica
- ser explicitos en migraciones
- no reinterpretar silenciosamente semanticas antiguas

## Tipos de compatibilidad

Conviene separar cuatro cosas distintas.

## 1. Compatibilidad de lectura

El runtime puede parsear o leer una estructura vieja.

Ejemplo:
- leer un `execution_report` historico v1 aunque hoy el UI espere algun campo
  extra

## 2. Compatibilidad de ejecucion

El runtime puede usar esa estructura para tomar acciones reales.

Ejemplo:
- ejecutar un `plan` antiguo de forma segura

Esto es mucho mas delicado que la compatibilidad de lectura.

## 3. Compatibilidad de migracion

El sistema puede transformar una estructura antigua a la actual.

Ejemplo:
- migrar DB
- migrar `strategy_state`

## 4. Compatibilidad historica

El sistema puede conservar y consultar datos viejos sin reescribir todo el
historico.

Ejemplo:
- auditar eventos emitidos hace meses por una version anterior

## Regla maestra

`fail closed` en ejecucion.
`fail tolerant` en lectura historica.

Traducido:
- si algo es dudoso en live, se rechaza
- si algo es antiguo en auditoria, se intenta leer y marcar

## Principios rectores

1. Preferir cambios aditivos sobre cambios destructivos.
2. Nunca cambiar el significado de un campo o estado sin version bump o nueva
   semantica explicita.
3. Nunca reinterpretar silenciosamente un payload viejo con semantica nueva.
4. La ruta live debe ser conservadora.
5. La ruta historica debe ser resistente a datos viejos.
6. Cada schema debe tener un dueno claro.
7. Downgrade no es objetivo v1.

## Dueños de cada schema

## 1. SQLite schema

Dueno:
- core de persistencia

Responsable de migraciones:
- migraciones SQL + runner

## 2. Modulo de estrategia

Dueno:
- runtime de estrategias

Responsable de compatibilidad:
- loader de estrategias
- adaptador legacy

## 3. `plan` y `actions`

Dueno:
- runtime de decision/ejecucion

Responsable de compatibilidad:
- validator
- normalizer
- interprete

## 4. `strategy_state`

Dueno:
- la propia estrategia, dentro de los limites del runtime

Responsable de migracion:
- la estrategia, mediante hooks declarados

## 5. `execution_report` y `event_log`

Dueno:
- capa de observabilidad/auditoria del core

Responsable de compatibilidad:
- lectores y normalizadores historicos

## Matriz general de versionado

Cada artefacto versiona distinto porque no todos tienen la misma naturaleza.

## SQLite schema

Marcador:
- `schema_migrations.version`

Tipo de versionado:
- secuencia monotona entera

## Modulo de estrategia

Marcador:
- `STRATEGY_API_VERSION`

Tipo de versionado:
- major explicito por contrato

## Plan

Marcador:
- `plan.schema_version`

Tipo de versionado:
- major explicito por contrato ejecutable

## State de estrategia

Marcador:
- `STATE_SCHEMA_VERSION`

Tipo de versionado:
- version interna de la estrategia

## Reporte

Marcador:
- `report_schema_version`

Tipo de versionado:
- version de lectura historica

## Evento

Marcador:
- `event_schema_version`

Tipo de versionado:
- version de envelope y payload de evento

## Politica transversal por clase de cambio

## Cambio aditivo no rompiente

Ejemplos:
- anadir campo opcional
- anadir metadata no obligatoria
- anadir informacion adicional en `report_json`

Politica:
- permitido sin romper consumers actuales si existe default claro o ignorabilidad
  segura
- documentar el cambio
- no hace falta bump mayor si la semantica antigua sigue intacta

## Cambio rompiente estructural

Ejemplos:
- renombrar campo requerido
- eliminar campo requerido
- cambiar shape de payload sin adapter
- introducir enum requerido que el runtime viejo no conoce

Politica:
- requiere nueva version del schema correspondiente o migracion explicita

## Cambio rompiente semantico

Ejemplos:
- mantener mismo campo pero cambiar su significado
- reutilizar un `status` existente para otra cosa
- hacer que una `action` signifique otra operativa

Politica:
- prohibido sin version bump claro
- mejor aun, usar nuevo nombre o nuevo `event_type`

## Cambio operativo pero no estructural

Ejemplos:
- nueva heuristica de normalizacion
- nuevo retry policy
- nuevo lock policy

Politica:
- no requiere schema bump por si mismo
- si afecta interpretacion historica, debe quedar trazado en metadata de runtime

## Politica concreta por artefacto

## 1. SQLite schema fisico

## Regla principal

La DB debe converger siempre al schema actual del runtime mediante migraciones
forward-only.

## Compatibilidad que garantizamos

### DB mas vieja que el runtime

Politica:
- se migra hacia delante automaticamente al arrancar
- si la migracion falla, el sistema no entra en operativa live

### DB exactamente en version actual

Politica:
- se usa normalmente

### DB mas nueva que el runtime

Politica:
- el runtime debe negarse a operar en modo escritura
- preferiblemente fallar al arranque con mensaje claro

Motivo:
- un binario viejo no debe escribir sobre una DB que no entiende

## Downgrade

Politica v1:
- no soportado

Si quieres volver a una version anterior del runtime:
- restauras DB desde backup
- o arrancas contra una DB compatible

## Backfill de datos

Si una migracion nueva requiere poblar datos derivados o recalcular algun
campo:
- debe hacerse en migracion dedicada o en repair step idempotente de bootstrap

No se debe esconder como efecto lateral opaco del negocio.

## Garantia realista

La garantia v1 para SQLite es:
- cualquier DB de una version anterior conocida puede migrarse hacia delante
- ninguna DB mas nueva se asume compatible hacia atras

## 2. Modulo de estrategia

## Versiones soportadas en v1

El runtime soporta:
- legacy por adaptador
- `STRATEGY_API_VERSION = 1`

## Versiones no soportadas

Si una estrategia declara:
- `STRATEGY_API_VERSION = 2`

y el runtime no soporta 2:
- la estrategia no debe cargarse
- no debe intentar caer silenciosamente al adaptador legacy

Motivo:
- si el autor declara una API nueva, el sistema no debe fingir otra

## Regla de compatibilidad

### Estrategia sin `STRATEGY_API_VERSION`, con `get_last_signal*`

Politica:
- entra como legacy

### Estrategia con `STRATEGY_API_VERSION = 1` y `decide`

Politica:
- entra como v1

### Estrategia con version desconocida

Politica:
- rechazo de carga

## Garantia realista

La garantia v1 aqui es estrecha a proposito:
- el runtime soporta exactamente las APIs que declara
- no intenta adivinar compatibilidad futura

## 3. `plan` schema

## Regla principal

La ruta live solo ejecuta versiones de `plan` explicitamente soportadas.

## Politica v1

En la v1 actual:
- el ejecutor soporta `schema_version = 1`
- las estrategias legacy se adaptan a un `plan` v1 sintetico antes de entrar al
  ejecutor

Eso significa algo importante:
- la compatibilidad legacy no vive dentro del ejecutor
- vive antes, en el adaptador

## Plan viejo conocido

Si en el futuro existiera `schema_version = 2` y el runtime aun soportara v1:
- podria normalizar v1 a un modelo interno comun
- pero solo si la semantica es segura

## Plan mas nuevo que el runtime

Politica:
- rechazo estructural inmediato
- nunca "mejor esfuerzo" en live

## Campos desconocidos

Hay que distinguir.

### Campos desconocidos en `meta` o `extensions`

Politica:
- pueden conservarse e ignorarse

### Campos desconocidos en zonas estructurales o que cambian semantica

Politica:
- si impiden validacion segura, rechazo

## Nuevos campos requeridos

Regla:
- si un campo nuevo puede auto-completarse con default inequívoco sin cambiar
  semantica, puede mantenerse la misma version mayor
- si no, requiere nueva version de `plan`

## Nuevos tipos de `action`

Regla:
- si el ejecutor no conoce el tipo, no lo ejecuta
- la presence de una `action` desconocida en live debe llevar a rechazo
  estructural o `not_supported`

No conviene:
- ignorar una `action` desconocida y seguir como si nada

## Garantia realista

La garantia v1 del `plan` es:
- strict execution compatibility
- tolerancia muy limitada y siempre explicitada

## 4. `strategy_state`

## Regla principal

El runtime es dueno del envelope.
La estrategia es duena del `strategy_state`.

## Envelope tecnico

Campos como:
- `schema_version`
- `instance`
- `meta`

pertenecen al core.

Si cambia el envelope:
- el core debe migrarlo o rechazarlo

## State interno de estrategia

Pertenece a la estrategia.

Versionado:
- `STATE_SCHEMA_VERSION`

## Compatibilidad en carga

### State con version igual a la estrategia actual

Politica:
- cargar normal

### State con version anterior y `migrate_state()` disponible

Politica:
- migrar en carga
- validar resultado
- persistir en nueva version

### State con version anterior sin migrador

Politica:
- la instancia no entra en live automaticamente
- error claro de incompatibilidad

### State mas nuevo que la estrategia cargada

Politica:
- rechazo de carga

Motivo:
- una estrategia vieja no debe tocar un state que pertenece a una version mas
  nueva de si misma

## Defaults

Si la estrategia no declara `STATE_SCHEMA_VERSION`:
- se asume `1`

Si no existe estado persistido:
- se usa `initial_state(context)` si existe
- si no, `{}` 

## Preservacion de campos desconocidos

Politica recomendada:
- el runtime no toca internamente claves del `strategy_state`
- serializa y deserializa como bloque opaco validable

Eso evita que el core rompa compatibilidad interna de la estrategia.

## Garantia realista

La garantia v1 del state es:
- el core preserva el bloque de estado
- la estrategia es responsable de migrar su propia semantica

## 5. `execution_report`

## Regla principal

Los reportes son historicos y append-only.
Por tanto, la prioridad no es ejecutarlos, sino poder leerlos.

## Politica

### Reporte viejo conocido

Politica:
- los lectores deben tolerar campos ausentes
- deben aplicar defaults de lectura cuando sea razonable

### Reporte con campos extra desconocidos

Politica:
- preservarlos e ignorarlos si no afectan la lectura base

### Reporte mas nuevo que el lector

Politica:
- lectura best-effort
- si no puede interpretarlo del todo, mostrar version y campos basicos

## Cambio de semantica

Si cambia el significado del reporte:
- bump de `report_schema_version`

No se debe:
- cambiar significado con la misma version y esperar que historico siga
  cuadrando

## Eager migration historica

Decision v1:
- no migrar todos los `report_json` historicos por defecto
- normalizar en lectura cuando sea necesario

## Garantia realista

La garantia v1 del reporte es:
- compatibilidad fuerte de lectura hacia atras dentro de la familia v1
- sin necesidad de reescribir el historico entero

## 6. `event_log`

## Regla principal

El log es append-only y debe ser lo mas estable posible en semantica.

## Regla de oro del evento

Un `event_type` ya publicado no debe cambiar de significado.

Si cambia de verdad:
- nuevo `event_type`
- o nueva version con adaptador muy claro

Preferencia v1:
- nuevo `event_type`

## Payloads de evento

### Campos nuevos en payload

Politica:
- permitidos si son aditivos
- lectores viejos deben ignorarlos

### Campos faltantes en eventos viejos

Politica:
- lectores nuevos deben tolerarlos

### Evento desconocido

Politica:
- no romper replay completo por ello
- mantenerlo como evento opaco con envelope visible

## `event_schema_version`

Debe versionar:
- envelope comun
- no necesariamente cada microdetalle del dominio

La semantica de dominio debe descansar sobre todo en:
- `event_type`
- payload bien definido

## Garantia realista

La garantia v1 del event log es:
- alta compatibilidad historica de lectura
- fuerte estabilidad semantica por `event_type`

## Politica de compatibilidad por ruta

## Ruta live de ejecucion

Politica:
- estricta
- fail closed

Aplica a:
- DB incompatible
- `plan` desconocido
- state no migrable
- modulo de estrategia no soportado

## Ruta paper/backtest

Politica:
- tambien estricta en contratos ejecutables
- algo mas tolerante en lectura historica

Motivo:
- aunque no haya dinero real, no conviene simular con semantica corrupta

## Ruta UI / auditoria / replay

Politica:
- best-effort
- tolerante a campos faltantes o extras
- siempre mostrando version y limites si hace falta

## Politica de deprecacion

Toda deprecacion debe seguir este ciclo.

## Fase 1: introduccion

- aparece schema nuevo o contrato nuevo
- coexistencia con el anterior si tiene sentido

## Fase 2: dual-read / single-write

- el sistema ya escribe en la version nueva
- sigue leyendo la vieja

## Fase 3: advertencia

- warning claro en logs o UI técnica
- documentacion de salida

## Fase 4: retirada de escritura antigua

- la ruta vieja ya no se produce
- solo se sigue leyendo o adaptando

## Fase 5: retirada total

- solo cuando ya no es necesaria para live o historico activo

## Importante

No hace falta aplicar este ciclo igual a todo.

Ejemplo:
- legacy strategy API si requiere deprecacion cuidada
- DB downgrade no

## Soporte minimo recomendado por artefacto

## SQLite

- write: solo schema actual
- read: solo schema actual tras migracion

## Modulo de estrategia

- load: `legacy` + `v1`
- reject: versiones futuras desconocidas

## Plan

- execute: solo versiones soportadas explicitamente
- normalize: solo si hay adapter seguro

## State

- read: version igual o migrable
- reject: version futura o no migrable

## Reportes

- read: fuerte compatibilidad hacia atras
- write: solo version actual

## Eventos

- read: fuerte compatibilidad hacia atras
- write: solo envelope actual

## Politica de defaults

Los defaults son utiles, pero peligrosos si cambian semantica.

Regla:
- un default solo es valido si reproduce de forma inequívoca el comportamiento
  previo

Ejemplo bueno:
- nuevo campo informativo con default `null`

Ejemplo malo:
- nuevo campo de ejecucion cuyo default cambia el targeting o el riesgo

## Politica de enums y estados

Hay que ser muy estrictos aqui.

## Enums ejecutables

Ejemplos:
- `action.type`
- `status` de plan ejecutable

Politica:
- nuevos valores deben tratarse como incompatibles hasta soporte explicito

## Enums historicos/observacionales

Ejemplos:
- metadata analitica
- clasificaciones UI

Politica:
- pueden ser mas tolerantes si el lector soporta "unknown"

## Politica de nombres

Renombrar rompe mas de lo que parece.

Regla:
- evitar renombrar campos si basta con anadir otro nuevo
- si se renombra uno importante, usar migracion/version bump

## Politica de pruebas

La politica de compatibilidad no vale nada sin tests.

Minimos recomendados:

1. DB vieja -> runtime nuevo -> migra y arranca.
2. DB mas nueva -> runtime viejo -> falla limpio.
3. Estrategia `legacy` -> adaptador -> plan v1.
4. Estrategia `v1` -> carga normal.
5. `strategy_state` viejo migrable -> upgrade correcto.
6. `strategy_state` viejo no migrable -> bloqueo limpio.
7. `plan` con `schema_version` desconocida -> rechazo.
8. `execution_report` viejo -> lectura best-effort.
9. `event_type` desconocido -> replay no rompe entero.

## Reglas simples de bolsillo

Si quieres cambiar algo, usa estas preguntas:

1. Cambia solo la forma o tambien el significado?
2. El runtime viejo podria ejecutar esto sin peligro?
3. El historico viejo debe seguir leyendose?
4. Hay un default inequívoco?
5. Quien es dueño de migrarlo?

Si no puedes responderlas con claridad:
- el cambio aun no esta bien diseñado

## Decisiones finales v1

La politica concreta para este proyecto queda asi:

- SQLite: forward-only, converge al schema actual, sin downgrade soportado.
- Modulo de estrategia: soporte explicito a `legacy` y `STRATEGY_API_VERSION=1`;
  versiones futuras desconocidas se rechazan.
- `plan`: ejecucion estricta solo para versiones soportadas; nada de
  best-effort en live.
- `strategy_state`: el core preserva y la estrategia migra su propio estado.
- `execution_report` y `event_log`: alta compatibilidad de lectura hacia atras;
  no hace falta reescribir todo el historico.
- Cambios semanticos nunca se hacen silenciosamente.
- La ruta live falla cerrada; la ruta historica intenta leer y marcar.

## Resumen ejecutivo

La politica de compatibilidad correcta no es "soportarlo todo".

Es esta:
- ejecutar solo lo que entiendes con seguridad
- migrar lo que eres dueño de migrar
- conservar el historico sin reescribirlo compulsivamente
- y rechazar con claridad lo que no puedes interpretar sin riesgo
