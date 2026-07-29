# Optimizaciones de rendimiento — Agenda (calendario, proyectos, mensualidades)

Fecha: 2026-07-27

## Resumen

La app de `agenda/` se sentía lenta al crecer los datos (calendario con muchas
sesiones, algunas páginas tardaban en cargar). Se identificaron y corrigieron
3 causas raíz, más 2 correcciones menores. Todo quedó verificado con scripts
de prueba en `tests/` (comparando antes/después con el mismo dataset).

## Resultados medidos (SQLite local, sin latencia de red)

Vista `/agenda/?vista=lista` (la más pesada, sin filtro de fecha), 25 filas
por página:

| Sesiones en BD | Código original | Código optimizado |
|---:|---|---|
| 300   | 63 queries / 441 ms | 14 queries / 375 ms |
| 1,000 | 63 queries / 483 ms | — |
| 4,886 | 63 queries / **847 ms** | 14 queries / **431 ms** |

Puntos clave:
- El código original **escala con el total histórico** de sesiones (441 → 483
  → 847 ms), aunque la página solo muestre 25 filas.
- El código optimizado se mantiene con **~14 queries fijas**, sin importar
  cuántas sesiones tenga el centro acumuladas.
- En producción (Postgres remoto, con latencia de red real por cada
  ida-y-vuelta), la diferencia sería considerablemente mayor a la medida
  aquí en SQLite local.

## Causas raíz encontradas

### 1. Paginación en memoria en la vista "lista" del calendario (CRÍTICO)

`agenda/views.py`, función `calendario()`. Para `vista == 'lista'` (sin
filtro de fecha por defecto), el código traía a memoria **todo el historial**
de sesiones que cumplían los filtros, con `select_related` a 6 tablas, y
recién después paginaba con `Paginator` sobre una **lista de Python** ya
materializada. Esto significa que cada carga de página ejecutaba una consulta
que traía y procesaba TODAS las sesiones históricas, aunque solo se
mostraran 25-50.

**Fix**: se pagina el **queryset** (LIMIT/OFFSET real a nivel de base de
datos) antes de procesar cualquier fila. Solo se instancian en Python los
registros que realmente se van a mostrar.

### 2. N+1 queries en `Sesion.pagado` / `Sesion.total_pagado`

Todos los templates del calendario (`sesion_row.html`,
`calendario_diario.html`, `calendario_semanal.html`,
`calendario_mensual*.html`, `calendario_lista.html`) hacen
`{% if sesion.pagado %}` por cada fila. Esa propiedad ejecutaba **2 consultas
SQL nuevas por cada sesión mostrada** (pagos directos + pagos masivos). En
una vista mensual con 300 sesiones visibles, esto son ~600 queries extra
solo para pintar la tabla.

**Fix**: se agregó `CalendarService.annotate_total_pagado()`, que anota
`total_pagado_sesion` sobre el queryset completo en **una sola consulta**
usando subqueries correlacionadas independientes (evita el "fan-out" de
JOIN). `Sesion.total_pagado` ahora revisa primero si ese valor ya viene
anotado (`hasattr(self, 'total_pagado_sesion')`) y lo reutiliza; si no está
anotado, sigue funcionando exactamente igual que antes (fallback
compatible, usado por ejemplo en la vista de detalle de una sola sesión).

### 3. Bug de datos: pagos masivos no se sumaban en las estadísticas (bonus)

La anotación original para el resumen "Total pagado / Total pendiente" del
calendario (`Coalesce(Sum('pagos__monto', ...))`) solo sumaba **pagos
directos** y omitía los **pagos masivos** (recibos que cubren varias
sesiones a la vez). El nuevo `annotate_total_pagado()` incluye ambos tipos
correctamente. Verificado con test dedicado (`tests/verificar_fix_rendimiento.py`,
sección 1).

### 4. Mismo patrón N+1 en `lista_proyectos` y `lista_mensualidades`

Los templates usan `proyecto.pagado_completo` / `mensualidad.pagado_completo`
(que internamente llaman a `total_pagado`/`total_devoluciones`, hasta 3
queries por fila), y `mensualidad.num_sesiones` / `num_sesiones_realizadas`
(2 queries más por fila vía `.count()`). Como estas vistas ya paginan
correctamente a 20 items, el impacto era acotado pero igual innecesario
(hasta 100 queries extra por página).

**Fix**: nuevo helper `ProyectoMensualidadService.cachear_pagos_en_lista()`
que precalcula pagos/devoluciones para toda una página en 3 queries fijas
(sin importar el tamaño de página), usando `.values(...).annotate(Sum(...))`
agrupado por id. Los conteos de sesiones/documentos de `lista_mensualidades`
ahora se anotan con `Count(..., distinct=True)` (evita fan-out al combinar
dos relaciones distintas en la misma anotación — verificado con test
dedicado que crea 4 sesiones × 3 documentos en la misma mensualidad y
confirma que los conteos NO se inflan a 12).

Además se quitó un `prefetch_related('sesiones')` que traía TODAS las
sesiones de cada mensualidad a memoria (objetos completos) solo para que el
template llamara `.count()` sobre ellas — lo cual ignora el prefetch de
todas formas y vuelve a golpear la base de datos. Ahora se anota el conteo
directamente.

También se consolidaron 4 `.count()` separados en un solo `.aggregate()`
con `Count(filter=...)` para las estadísticas de ambas listas.

### 5. Micro-optimización: `timezone.now()` fuera del loop

En `calendario()`, `ahora = timezone.localtime(timezone.now())` se recalculaba
en cada iteración del loop de sesiones (import + cálculo redundante). Ahora
se calcula una sola vez antes del loop.

## Índice de base de datos agregado

Nueva migración `agenda/migrations/0016_sesion_idx_sesion_ult_pac_serv_edo.py`:
índice compuesto `(paciente, servicio, estado, -fecha, -hora_inicio)` en
`Sesion`, que acelera la subquery correlacionada usada para determinar la
"última sesión por paciente+servicio" (usada para marcar si un servicio debe
renovarse). Antes solo existía `(paciente, fecha)`, que no cubre bien un
filtro por `servicio` + `estado`.

**Importante**: en producción, correr `python manage.py migrate` para
aplicar este índice.

## Archivos modificados

- `agenda/models.py` — propiedades `total_pagado`/`total_devoluciones` de
  `Sesion`, `Proyecto` y `Mensualidad` ahora reutilizan valores anotados si
  existen; `Mensualidad.num_sesiones`/`num_sesiones_realizadas` ídem; nuevo
  índice compuesto en `Sesion.Meta`.
- `agenda/services.py` — nuevo `CalendarService.annotate_total_pagado()` y
  `ProyectoMensualidadService.cachear_pagos_en_lista()`.
- `agenda/views.py` — `calendario()` reestructurada (paginación a nivel de
  queryset, anotación de pagos, timezone fuera del loop);
  `lista_proyectos()` y `lista_mensualidades()` usan el nuevo helper de
  cacheo de pagos y `.aggregate()` consolidado.
- `agenda/migrations/0016_...py` — nuevo índice.

## Scripts de verificación (carpeta `tests/`, no forman parte de la app)

- `verificar_fix_rendimiento.py [N]` — crea N sesiones de prueba, valida
  cálculos de pago (directo + masivo), confirma 0 queries extra cuando hay
  anotación, y ejercita la vista `/agenda/` completa (lista y mensual).
- `verificar_fix_listas.py` — valida que los conteos anotados de
  `lista_mensualidades` no sufren fan-out, y que `cachear_pagos_en_lista`
  da resultados correctos con 0 queries al reutilizar.
- `agregar_sesiones.py N` / `medir_vista_calendario.py` — usados para el
  benchmark antes/después de la tabla de resultados de arriba.

Estos scripts requieren un usuario `test_perf`, una `Sucursal Test`, un
`TipoServicio Test`, un `Profesional Test` y un `Paciente Test`; se pueden
borrar sin afectar la app en producción.

## Corrección adicional: contador de sesiones pendientes (facturación)

Fuera del alcance original ("agenda"), pero encontrada al auditar si el mismo
patrón de bug (pagos masivos no reconocidos) existía en otras partes de la
app. Se confirmó en `facturacion/services.py` → `AccountService.update_balance()`:

- El **saldo en dinero** de la cuenta corriente (`pagos_sesiones`,
  `pagos_mensualidades`, `pagos_proyectos`, etc.) **ya estaba bien calculado**
  — sumaba correctamente pagos directos + masivos desde antes. No se tocó.
- El campo `num_sesiones_realizadas_pendientes` (un **contador**, no un
  monto) sí tenía el bug: no reconocía como "pagada" una sesión cubierta por
  un pago masivo, así que la seguía contando como pendiente. Se muestra como
  el texto "(N sesiones pendientes de pago completo)" en
  `facturacion/templates/facturacion/detalle_cuenta.html`.

**Verificado con un caso concreto** (`tests/verificar_fix_contador_cuenta.py`):
2 sesiones de Bs. 100 cada una, una pagada con pago directo y otra con pago
masivo.

| | Antes | Después |
|---|---|---|
| `num_sesiones_realizadas_pendientes` | **1** (bug: no veía el pago masivo) | **0** (correcto) |
| `pagos_sesiones` (saldo en dinero) | 200 | 200 (sin cambios) |

El fix usa el mismo patrón de subqueries correlacionadas independientes ya
usado en `agenda/services.py`, para sumar pagos directos + masivos sin
provocar "fan-out" de JOIN.

## Archivos modificados (actualizado)

- `agenda/models.py`, `agenda/services.py`, `agenda/views.py`,
  `agenda/migrations/0016_...py` — ver secciones anteriores.
- `facturacion/services.py` — corrección de `num_sesiones_realizadas_pendientes`
  en `AccountService.update_balance()` (no afecta ningún cálculo de dinero).


## Revisión a fondo (segunda pasada): seguridad + más bugs de pagos masivos

### 🔴 Seguridad — corregido

1. **Credencial real de Cloudinary hardcodeada en `config/settings.py`**, expuesta en el
   repositorio público de GitHub (api_key y api_secret reales). Se quitó del código;
   ahora se lee desde variables de entorno también en desarrollo (antes solo se exigía
   en producción). **Acción obligatoria del equipo: rotar esa credencial desde el
   dashboard de Cloudinary** — el fix de código no invalida la que ya estuvo expuesta.
2. **`SECRET_KEY` con valor por defecto inseguro utilizable en producción** si faltaba
   la variable de entorno. Ahora producción falla al arrancar (`ValueError`) si no está
   configurada, en vez de arrancar en silencio con un valor conocido/público.
3. **Webhook del bot de WhatsApp con "fail open"** (`agente/views.py`): si
   `WEBHOOK_SECRET_TOKEN` no estaba configurado, se aceptaba CUALQUIER request sin
   autenticar. Ahora bloquea por defecto si falta el token ("fail closed").
4. Se creó `.env.example` (no existía, aunque `.gitignore` ya lo esperaba) documentando
   todas las variables de entorno usadas por el proyecto.

Los 3 fixes de seguridad están verificados con pruebas automatizadas (`manage.py check`,
simulación de producción sin `SECRET_KEY`, llamada directa a `_verificar_token`).

### 🟡 Vista de "desglose de cuenta" completamente rota — corregido

Al verificar el fix de excedentes (punto 5 de la sección anterior), se descubrió que
`facturacion/views.py` → `detalle_cuenta_ajax` (el endpoint detrás del botón
**"Ver desglose"** en la ficha de cuenta del paciente) tenía **3 bugs independientes
que la rompían por completo (error 500 en cada llamada)**, sin relación con pagos
masivos:

- Llamaba a `cuenta.get_stats_cached()`, un método que **nunca existió** en el modelo
  `CuentaCorriente` (se llamaba desde 6 lugares del código, incluyendo
  `facturacion/templatetags/facturacion_tags.py`, pero solo ahí había manejo de errores
  con fallback — por eso no se notaba en esas pantallas). Se implementó el método,
  devolviendo exactamente el diccionario que ya esperaban todos los lugares que lo
  llamaban.
- **3 `KeyError`** en la misma función: `.aggregate(total=Sum('monto'))['monto__sum']`
  — el resultado de `aggregate()` queda bajo la clave `'total'` (el nombre que se le
  dio), no `'monto__sum'`. Esto garantizaba que la vista fallara siempre, incluso
  después de arreglar `get_stats_cached`.

Verificado end-to-end con un test que llama al endpoint real vía `Client()` y confirma
`status_code == 200` con los montos correctos.

### 🟠 Más cálculos de pagos que no reconocían pagos masivos

5. **Cálculo de "excedentes"** en `detalle_cuenta_ajax` — corregido (solo lectura/display).
6. **`PaymentService.process_payment`, ajuste automático de precio al marcar
   "pago completo"** (`facturacion/services.py`) — **este sí escribe en la base de
   datos**: si una sesión/proyecto/mensualidad ya tenía parte pagada por pago masivo, y
   luego llegaba un pago directo adicional marcado como "pago completo", el sistema
   sobrescribía `monto_cobrado`/`costo_total`/`costo_mensual` usando solo el total
   directo, **perdiendo silenciosamente el registro del pago masivo previo**.
   Corregido para sumar ambos. Verificado con un caso real: proyecto de Bs.100 pagado
   100% por masivo + pago directo adicional de Bs.20 marcado "completo" → antes
   `costo_total` quedaba en 20, ahora queda correctamente en 120.
7. **`AccountService.process_refund`, validación de devoluciones para proyecto y
   mensualidad** — la misma función calculaba "cuánto hay disponible para devolver"
   contando solo pagos directos, por lo que podía **bloquear devoluciones legítimas**
   de dinero pagado vía masivo (falla "segura" — bloquea de más, no permite de más —
   pero sigue siendo un bug). Corregido y verificado: una devolución de Bs.80 sobre un
   proyecto pagado 100% por masivo, que antes se rechazaba con
   "Disponible: Bs.-80", ahora se procesa correctamente.
8. **Encontrado, NO corregido — bajo impacto, marcado como informativo en el propio
   código**: cálculo de comisión de servicio externo en `process_payment` (línea ~803
   de `facturacion/services.py`) tampoco incluye pagos masivos. El comentario original
   dice explícitamente "guarda el desglose centro/profesional para reportes internos" y
   "NO afecta pagos, créditos ni cuenta corriente" — se dejó sin tocar por quedar fuera
   del alcance de esta revisión y merecer su propia validación con el equipo que genera
   esos reportes de comisiones.

### Scripts de verificación agregados

- `tests/verificar_fix_contador_cuenta.py` — verifica el contador de sesiones pendientes.
- `tests/verificar_fix_excedentes.py` — verifica excedentes + el fix de `get_stats_cached`
  y los 3 `KeyError`.
- `tests/verificar_fix_escritura_pagos.py` — verifica el ajuste de costo al pago completo
  y la validación de devoluciones.

## Validación con una copia real de la base de datos (post-parche)

Se restauró un backup real de producción (294 pacientes, 10.550 sesiones, 199
proyectos, 366 mensualidades, 1.876 pagos directos, **1.033 pagos masivos**) en un
Postgres local, y se corrió el código parcheado contra esos datos reales. Esto sacó a
la luz un problema que los datos sintéticos no alcanzaban a mostrar:

### Bug de rendimiento adicional encontrado (y corregido) gracias a datos reales

La corrección del cálculo de "Total pagado / Total pendiente" del calendario (que
agrega pagos masivos) generaba una consulta SQL donde la subquery de pagos se
evaluaba **3 a 4 veces por fila** (una vez por cada lugar donde se usa el valor:
`Sum()`, y 3 expresiones `CASE`), en vez de una sola vez. Con datos sintéticos
pequeños esto era invisible; con las 10.550 sesiones reales, esa sola consulta
tardaba **1.15 segundos — el 97% del tiempo total de la página** (confirmado con
`EXPLAIN ANALYZE`).

**Corrección**: en vez de dejar que la base de datos repita la subquery, se trae una
sola vez por fila el valor ya calculado (`monto_cobrado`, `total_pagado_sesion`) y se
suma en Python. La misma subquery ahora se ejecuta una sola vez por fila.

### Resultado final, con datos reales y caché tibia (3 corridas)

| | Código original | Código optimizado (con índice aplicado) |
|---|---|---|
| Vista lista, sin filtro de fecha, 10.550 sesiones | ~1.3 – 1.6 s | ~150 – 175 ms |
| Queries SQL | 65 | 54 |

**~9x más rápido** en datos reales de producción (con caché tibia; la primera carga
"fría" también mejora, de ~2.4s a ~0.5s).

### Otras validaciones con datos reales

- `AccountService.update_balance()` corrido sin errores sobre los **94 pacientes
  activos** de la base real — los montos (Consumido, Pagado, Saldo, Crédito
  Disponible) se ven consistentes entre sí para todos.
- `detalle_cuenta_ajax` (antes roto, ver sección de "Vista de desglose de cuenta")
  probado contra pacientes reales con pagos masivos — responde 200 OK con montos
  coherentes en todos los casos.

### Nota técnica sobre cómo se restauró el dump

El archivo subido (`.dump`, formato "custom" de `pg_dump`) fue generado con
PostgreSQL 18, cuyo formato de archivo (v1.16) todavía no soporta `pg_restore` de
PostgreSQL 16 (el disponible en este entorno). Se usó la librería `pgdumplib` (Python
puro) para leer el dump y reconstruir manualmente el esquema + datos + índices/FKs en
un Postgres 16 local, reproduciendo el mismo comportamiento que `pg_restore` haría con
la versión correcta. Este backup real **no se incluye** en los archivos entregados —
solo se usó localmente para la validación y no queda en ningún archivo del paquete.

## Recomendaciones adicionales (no aplicadas en este cambio)

1. **Signal síncrono de "cuenta corriente"**: cada `Sesion.save()` dispara
   un recálculo síncrono de la cuenta corriente del paciente (consultas de
   agregación). Es correcto para uso normal, pero puede ser lento en
   creaciones masivas (agendar recurrente, mensualidades con muchas
   sesiones). Considerar diferir ese recálculo (señal `post_save` con
   `transaction.on_commit`, o un job asíncrono) si se notan lentitud al
   crear sesiones en lote.
2. **Cache en producción**: `CACHES` usa `LocMemCache` (memoria del proceso).
   Con más de un worker de gunicorn, cada uno cachea por separado. Si el
   centro escala a varios workers/instancias, conviene mover a Redis.
3. **Cálculo de comisión de servicio externo** (`facturacion/services.py` línea ~803):
   único punto restante con el patrón "pagos masivos no reconocidos", dejado sin tocar
   por ser explícitamente informativo (no afecta pagos/créditos/cuenta corriente) y
   merecer revisión con quien genera esos reportes de comisiones.
4. **Apps aún no auditadas a fondo**: `documentos/`, `pacientes/`, `profesionales/`,
   `evaluaciones/`, `inventario/`, `recordatorios/`, `agente/` (más allá de la revisión
   de seguridad del webhook). No se encontró nada al pasar por encima, pero no se hizo
   una revisión exhaustiva como la de `agenda/` y `facturacion/`.
