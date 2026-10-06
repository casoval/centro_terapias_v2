# Asistencia

## Horarios
Cada **zona** tiene varias *plantillas de horario* (Admin → Asistencia → Horarios). Una plantilla = grupo de
días + 1..4 bloques (1 = continuo, 2 = partido). Ej.: "Lun–Vie 08–13 / 14–18" y "Sábado 08–12".
Prioridad: **fecha especial** > **horario propio del profesional** (si tiene "horario propio") > **horario de la zona**.

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
    5 * * * *   python manage.py generar_ausentes
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
`0007` elimina el esquema viejo. Hacer respaldo antes de migrar en producción.
