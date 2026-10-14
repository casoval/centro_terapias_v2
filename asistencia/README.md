# Asistencia

## Horarios
Cada **zona** tiene varias *plantillas de horario* (Admin → Asistencia → Horarios). Una plantilla = grupo de
días + 1..4 bloques (1 = continuo, 2 = partido). Ej.: "Lun–Vie 08–13 / 14–18" y "Sábado 08–12".
Prioridad: **fecha especial** > **horario propio del profesional** (si tiene "horario propio") > **horario de la zona**.

## Vigencias: los cambios NO son retroactivos
Todo lo configurable tiene una fecha de inicio elegida por el administrador; los meses anteriores se
calculan siempre con lo que regía en su momento (el informe mensual, el panel y «Mi asistencia»).
- **Horarios** (días, bloques, tolerancia y límite para marcar): al editar se elige «Aplicar desde».
  Con una fecha posterior al inicio del horario se crea una **versión nueva** y la anterior queda vigente hasta el
  día previo; con una fecha igual o anterior se corrige el mismo horario. «Finalizar» (antes «Eliminar») deja de
  aplicar el horario desde una fecha; solo se borra si nunca llegó a regir. Los finalizados quedan en un historial.
- **Horario propio de un profesional:** activarlo o desactivarlo también es «desde una fecha» (`PeriodoHorarioPropio`);
  fuera de esos periodos rige el horario de la zona. Se pueden tener varios periodos.
- **Reglas de descuento por retraso:** versiones que rigen desde el día 1 de un mes (`ReglasAsistencia.para_mes`):
  un mes se evalúa completo con una sola versión. Solo se pueden borrar las versiones programadas (futuras).
- **Fechas especiales** ya eran por fecha.
- Pendiente (no incluido): terminar una asignación de zona conserva el historial; hoy eliminar la asignación borra
  también su horario propio y el pasado de ese profesional en esa zona dejaría de calcularse.

## Reglas de retraso y descuento
Por **bloque de horario** (Horarios, horarios propios y fechas especiales):
- **Tolerancia** (min): el retraso se acumula **después** de ella, con precisión de segundos. Con 10 min y entrada a las
  08:00: hasta 08:10:00 es puntual y no acumula nada; a las 08:11:00 acumula **1 minuto** (no 11); a las 08:10:30, 30 s.
  Cada ingreso guarda `segundos_tarde` (después de la hora, también dentro de la tolerancia) y `segundos_acumulables`
  (solo el excedente). `minutos_tardanza` sigue siendo informativo (minutos desde la hora de entrada).
- **Límite para marcar** (min, opcional): hasta N min con 0 s se puede marcar; un segundo después ya no y el bloque se
  toma como falta (`generar_ausentes` crea el AUSENTE justo al vencer el límite). El admin puede registrarlo a mano.

Para todo el centro (Asistencia → Reglas, `ReglasAsistencia` + `TramoDescuento`), por **tramos** y por versiones desde un mes:
- los segundos acumulables se suman en el mes y el total cae en un tramo. Los topes son inclusivos. Sugerido:
  hasta 30 min → 0 días · hasta 45 → ½ día · hasta 60 → 1 día · hasta 90 → 2 días · más de 90 → 3 días
  (30:00 no descuenta; 30:01 a 45:00 = medio día; 45:01 a 60:00 = 1 día; 60:01 a 90:00 = 2 días; desde 90:01 = 3 días).
  Ver `services.dias_descuento()`. Cada fila es «hasta N minutos (admite decimales) → X días»; «más allá del último tope» es obligatorio.
- el acumulado se ve en la columna «Retraso acum. mes» del Panel (min:seg) y en «Mi asistencia».

## Faltas, permisos y evaluación del mes
- **Falta:** bloque sin ingreso. Horario partido: faltar a un bloque = medio día, a los dos = día completo. Horario continuo
  (p. ej. el sábado) = día completo.
- **Permiso / justificación** (Asistencia → Justificaciones, `PermisoAsistencia`): solo el administrador, después de revisar
  el comprobante o justificativo escrito (certificado médico, permiso por escrito, otro) con su detalle y archivo opcional.
  Mientras no exista, la falta descuenta. **Plazo: hasta el último día del mes de la falta** (a cualquier hora);
  pasado el mes no se puede justificar ni quitar.
- **Puntualidad (estrellas, solo retraso):** 5★ siempre a la hora o antes (verde) · 4★ usó la tolerancia sin acumular ni un
  segundo (verde-amarillo) · 3★ acumula retraso sin descuento (amarillo) · 2½★ medio día de descuento (amarillo-naranja) ·
  2★ un día (naranja) · 1★ dos días (rojo) · 0★ tres días o más, pésima (morado).
- **Asistencia (semáforo, solo faltas):** verde sin faltas · amarillo faltó pero con permiso · rojo faltó sin justificar.
- Cada evaluación trae su **motivo** en texto. Se muestra en el Panel (con aviso de a quién conviene llamar), en «Mi asistencia»,
  en el Informe mensual y en el PDF (por profesional y en el resumen del centro). Código: `evaluacion.py`.

## Marcado
GPS (zona + precisión) → secuencia entrada/salida validada en servidor → rostro → registro.
Cada entrada se asigna al bloque que corresponde a la hora; la tardanza se mide contra ese bloque.

## Reconocimiento facial
`face-api.js` corre en el navegador (archivos en `static/asistencia/face/`, sin CDN). El servidor recibe un
descriptor de 128 números y lo compara por distancia euclidiana con los guardados al enrolar.
Limitación: la comparación se calcula en el cliente y no hay detección de "prueba de vida"; la foto de cada
marcado se guarda como evidencia para revisión.

## Tareas programadas (cron)
    # cada hora: crea AUSENTE por cada bloque ya terminado sin entrada (idempotente)
    5 * * * *   python manage.py generar_ausentes     # con límites de marcado cortos, mejor cada 15 min
    # al cierre de la jornada: reporte CSV a RRHH
    30 19 * * 1-6  python manage.py enviar_reporte_asistencia
No se generan ausencias en días sin horario, días libres ni para profesionales sin enrolar
(`--incluir-sin-enrolar` para forzarlo; `--fecha YYYY-MM-DD` para reprocesar un día pasado).

## Ajustes opcionales (`settings.py`)
| Ajuste | Defecto | Qué hace |
|---|---|---|
| `ASISTENCIA_UMBRAL_FACIAL` | 0.5 | distancia máxima aceptada (menor = más estricto) |
| `ASISTENCIA_PRECISION_GPS_MAX` | 150 | metros de error GPS máximos aceptados |
| `ASISTENCIA_REENTRADAS_EXTRA` | 3 | salidas/re-entradas extra permitidas por día |
| `ASISTENCIA_ENROLAMIENTO_MIN_CAPTURAS` | 3 | capturas válidas mínimas al enrolar |

## Migración
`0005` crea las tablas nuevas, `0006` convierte los datos (horarios de zona, personalizados, fechas
especiales, etiquetas de bloque; los enrolamientos con el vector simulado antiguo pasan a *pendiente*),
`0007` elimina el esquema viejo, `0008` agrega el límite para marcar y las reglas mensuales, `0009` quita un campo sobrante de las reglas, `0010` agrega las vigencias por fecha y `0011` conserva lo ya configurado como «desde siempre», `0012`-`0014` pasan a segundos de retraso, reglas por tramos y permisos. Hacer respaldo antes de migrar en producción.

## Migración de datos (0012 a 0014)
- Las reglas guardadas con «medio día / día completo» pasan a los tramos sugeridos (30/45/60/90 min → 0/½/1/2 días, más de 90 → 3).
  Una regla sin valores queda sin descuento.
- Los retrasos ya registrados se **recalculan con el criterio nuevo** (solo el excedente de la tolerancia), tomando la tolerancia
  del bloque del horario que regía ese día (10 min si no se encuentra). Haz un respaldo antes de migrar.

## Asuetos (tiempo libre concedido)
Día de la Mujer, cumpleaños, vacaciones... **no son falta, ni permiso, ni asistencia: son neutros.**
- **Tipos** (Admin → Asistencia → Asuetos): nombre, días por defecto (0,5 = medio día), plazo para usarlo y si se otorga solo en el cumpleaños.
- **Otorgar**: crea un saldo (`DerechoAsueto`) para todo el personal, sucursales, zonas o profesionales elegidos, con filtro por sexo.
  El sexo y la fecha de nacimiento se cargan en la ficha del profesional.
- **Usar**: el admin registra la fecha (y el bloque) en que la persona lo toma (`UsoAsueto`), sin pasarse del saldo ni del vencimiento.
  Cada bloque pesa 1/N del día (partido: medio día = un bloque; continuo: día completo). Varios días = una fecha por vez.
- **Efecto**: el bloque en asueto no genera AUSENTE, no es falta ni descuento, no cuenta como día con horario ni horas esperadas;
  aparece como «Asueto» en el panel, el informe mensual (PDF) y «Mi asistencia». El reporte del profesional lo descuenta de su capacidad.
- **Cumpleaños automáticos**: `python manage.py otorgar_asuetos_cumpleanos` (cron diario, idempotente).

## Reglas por alcance
Regla **general** + excepciones por **sucursal** o **profesional** (Admin → Reglas). Gana la más específica
(profesional > sucursal > general). Cada alcance tiene sus propias versiones por mes (no retroactivas);
«Terminar excepción» devuelve a esa persona/sucursal a la regla más general desde el mes elegido.

## Migración
`0015` agrega asuetos y el alcance de las reglas; `profesionales 0003` agrega sexo y fecha de nacimiento (opcionales).
