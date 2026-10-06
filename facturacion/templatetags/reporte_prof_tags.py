# facturacion/templatetags/reporte_prof_tags.py
from django import template

register = template.Library()


@register.filter
def css(value, decimales=1):
    """Número → texto con punto decimal (seguro para CSS aunque el idioma sea es-bo)."""
    try:
        return f"{float(value):.{int(decimales)}f}"
    except (TypeError, ValueError):
        return "0"


@register.filter
def pw(value):
    """Ancho porcentual 0–100 para barras (con punto decimal)."""
    try:
        v = max(0.0, min(float(value), 100.0))
    except (TypeError, ValueError):
        v = 0.0
    return f"{v:.1f}"


@register.filter
def get_item(d, key):
    try:
        return d.get(key)
    except Exception:
        return None


@register.filter
def bs(value):
    """1234.5 → 1.234,50"""
    try:
        v = float(value or 0)
    except (TypeError, ValueError):
        return "0,00"
    s = f"{v:,.2f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


@register.filter
def signo(value):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return ""
    return f"+{v:g}" if v > 0 else f"{v:g}"


# ══════════════════════════════════════════════════════════════════════
# AYUDA CONTEXTUAL («i») — solo en pantalla, no en el PDF.
# Un único lugar para editar los textos. Uso en plantilla: {% ayuda "clave" %}
# ══════════════════════════════════════════════════════════════════════
from django.utils.html import format_html  # noqa: E402

AYUDA = {
    # ── Filtros ──
    'f_profesional': "Profesional del que se arma el informe. Solo aparecen los activos.",
    'f_sucursal': "Limita el informe a las sesiones de una sucursal. Con «Todas» se suman todas. Si el profesional trabaja en varias sucursales, el horario base se toma de la zona de la sucursal elegida.",
    'f_mes': "Atajo para ver un mes completo. Úsalo junto con «Año». Reemplaza a las fechas Desde/Hasta.",
    'f_anio': "Año del mes elegido. Si eliges solo el año (sin mes), se muestra el año completo.",
    'f_desde': "Primer día del período analizado. Máximo 800 días de rango.",
    'f_hasta': "Último día del período analizado. Los días posteriores a hoy cuentan como «futuros»: no se evalúa su rendimiento, solo su disponibilidad.",
    'f_servicio': "Muestra solo las sesiones de ese servicio. Importante: filtra las tablas de sesiones, niños y generación de dinero, pero la ocupación del horario siempre considera TODAS las sesiones del profesional (si no, saldría un falso tiempo libre).",
    'f_nino': "Muestra solo las sesiones de ese niño. La ocupación del horario sigue considerando todas las sesiones del profesional.",
    'f_tipo': "Sesión individual: se cobra por sesión. Proyecto: evaluaciones o paquetes de precio fijo. Mensualidad: paquete mensual de precio fijo. Filtra las tablas, no la ocupación del horario.",
    'f_estado': "Filtra por estado de la sesión. Falta sin aviso = el niño no vino y no avisó (se cobra). Permiso = avisó (no se cobra). Con retraso = el niño llegó tarde pero se atendió.",
    'f_costo': "Opcional. Escribe cuánto le cuesta al centro este profesional por mes (sueldo y cargas). El sistema no guarda sueldos del personal interno, por eso se ingresa aquí. Con ese dato se calcula el margen y la cobertura, y se agrega el criterio de rentabilidad al semáforo. Se prorratea por los días del período (costo × días ÷ 30,4).",
    'f_rangos': "Atajos de fechas. Al pulsar uno se recalcula todo el informe con ese período.",
    'f_horario': "Define de qué horas es el horario de trabajo para medir ocupación y horas libres. Prioridad: 1) horario configurado en Asistencia (con sus fechas especiales y feriados), 2) horario predeterminado: L-V 9:00-12:00 y 14:30-19:00, sábado 9:00-12:00. Solo puedes editarlo aquí cuando Asistencia no tiene horario, o marcando «Forzar horario manual».",
    # ── Ficha / generales ──
    'gen_periodo': "Total que generó en el período: sesiones individuales + su parte de proyectos + su parte de mensualidades. Incluye las faltas sin aviso (se cobran), igual que el reporte financiero.",
    'semaforo': "Resume en un puntaje de 0 a 100 si el profesional aporta valor al centro. Cada criterio vale verde (1 punto), ámbar (0,5) o rojo (0) y se pondera según su importancia (la cobertura del costo pesa más). Es orientativo: la decisión final es del dueño.",
    'hallazgos': "Frases generadas automáticamente a partir de los números del informe. Rojo = requiere atención, azul = informativo, verde = positivo, amarillo = nota sobre los datos.",
    # ── Producción ──
    'sec_produccion': "Cuánto dinero atribuible al profesional produjo en el período, según el tipo de atención.",
    'k_gen_total': "Suma de lo generado por sesiones individuales, proyectos y mensualidades. Es lo que produjo, no necesariamente lo que ya se cobró (ver «Cobrado» y «Sin cobrar»).",
    'k_gen_ind': "Suma del monto cobrado de sus sesiones individuales realizadas, con retraso o falta sin aviso. Una sesión individual genera el precio de esa sesión.",
    'k_gen_proy': "Su parte del costo de proyectos/evaluaciones. El costo del proyecto es fijo: se reparte entre los profesionales según el valor de sus sesiones a precio individual y se devenga conforme se realizan las sesiones. «Solo» = proyectos que atendió únicamente él/ella; «Grupal» = compartidos con otros profesionales.",
    'k_gen_mens': "Su parte de las mensualidades. Mismo método que los proyectos: el costo mensual es fijo y se reparte según el valor de las sesiones de cada profesional a precio individual.",
    'k_por_generar': "Dinero que generarán las sesiones ya programadas (aún no realizadas). Para sesiones individuales es su precio; para proyectos/mensualidades es su parte de reparto de cada sesión pendiente.",
    'k_ing_hora': "Total generado ÷ horas de reloj trabajadas. Mide cuánto rinde cada hora efectiva del profesional. Sirve para compararlo con el equipo.",
    'k_ing_sesion': "Total generado ÷ sesiones atendidas (realizadas + con retraso).",
    'k_cobrado': "Parte de lo generado que el paciente ya pagó. En sesiones individuales se suman los pagos registrados de cada sesión. En proyectos/mensualidades se estima proporcional al avance de pago del paquete (si el paquete está pagado al 50%, se considera cobrado el 50% de su parte).",
    'k_sin_cobrar': "Generado − Cobrado. Producción que el profesional ya realizó pero que el centro aún no recibió.",
    'k_margen': "Lo que aporta al centro menos lo que cuesta. Aporte = total generado (si es servicio externo, se descuenta la comisión que se lleva el profesional). Costo = costo mensual ingresado × días del período ÷ 30,4. Cobertura = aporte ÷ costo (1× = cubre justo su costo).",
    'k_externos': "Servicios externos: el profesional cobra una comisión y el centro retiene el resto. Aquí se muestra lo que retiene el centro y lo que va al profesional (solo sesiones realizadas).",
    'comparacion': "Compara este período con el inmediatamente anterior de la misma duración. Verde = mejoró, rojo = empeoró. «pts» = puntos porcentuales.",
    'tipo_individual': "Sesiones que se cobran una por una. Genera el monto cobrado de cada sesión consumida (realizada, con retraso o falta sin aviso).",
    'tipo_proyecto': "Evaluaciones y proyectos de precio fijo. Aquí se muestra su parte del costo del proyecto, repartida por el valor de sus sesiones a precio individual.",
    'tipo_mensualidad': "Paquetes mensuales de precio fijo. Aquí se muestra su parte de la mensualidad, repartida por el valor de sus sesiones a precio individual.",
    # ── Horas ──
    'sec_horas': "Compara el tiempo que el profesional trabajó realmente con el tiempo que debía estar disponible según su horario. Solo se evalúan los días ya transcurridos.",
    'k_horas_trab': "Horas de reloj con pacientes (realizadas + con retraso). Si atiende a dos niños a la misma hora no se duplican. «Con pacientes» suma las horas de cada niño por separado (puede ser mayor si hay sesiones grupales).",
    'k_horario': "Horas que debía trabajar según su horario base en los días ya transcurridos del período. Descuenta feriados y días libres configurados en Asistencia.",
    'k_ocup_efect': "Horas realmente trabajadas ÷ horas de su horario transcurrido. Es la medida más exigente: no cuenta faltas ni sesiones sin registrar. Verde ≥ 60%, ámbar 35-60%, rojo < 35%. «Agendada» sí cuenta faltas y programadas.",
    'k_libres_inas': "Horas de su horario que quedaron libres porque el niño faltó, pidió permiso, se canceló o se reprogramó. La falta sin aviso sí se cobra, pero el profesional igual quedó libre esa hora.",
    'k_sin_agendar': "Horas de su horario en las que nunca hubo ningún niño agendado. Es capacidad disponible sin usar.",
    'k_potencial': "Estimación teórica de lo que habría generado si las horas libres que NO generaron dinero (permisos, cancelaciones, reprogramaciones y sin agendar) se hubieran ocupado, usando su ingreso por hora actual. No incluye faltas sin aviso porque esas sí se cobran. Con pocas sesiones puede salir inflado.",
    'k_prox': "Horas libres en los próximos 14 días contando desde hoy, restando las sesiones ya agendadas. No depende del rango elegido arriba. Indica cuánto cupo tiene para recibir nuevos niños.",
    'k_extra': "Minutos atendidos fuera de su horario base (antes, después o en días libres). Indica horas extra o agenda flexible.",
    'desglose': "Reparte las horas de su horario según lo ocurrido: trabajo efectivo, falta sin aviso (se cobra), permiso, cancelada, reprogramada, programada que no se registró (sesión pasada que sigue «programada») y sin paciente agendado. Pasa el mouse por cada tramo para ver sus horas.",
    # ── Evolución ──
    'sec_evolucion': "Evolución del rendimiento. Usa las pestañas para ver el detalle por día, semana o mes. El gráfico muestra sesiones atendidas (verde), faltas (rojo), dinero generado (línea azul) y ocupación agendada (línea naranja).",
    'e_horario': "Horas de su horario ese día/semana/mes.",
    'e_trabajo': "Horas de reloj con pacientes (realizadas + con retraso).",
    'e_libre': "Horario − horas ocupadas (agendadas, incluidas faltas). Es lo que quedó sin ningún niño.",
    'e_libres_inas': "Horas libres por falta, permiso, cancelación o reprogramación.",
    'e_sin_agendar': "Horas del horario en las que nunca hubo un niño agendado.",
    'e_ocup': "Horas ocupadas (atendidas + faltas + programadas) ÷ horas de su horario. Es la ocupación «agendada».",
    'e_ocup_efect': "Solo horas realmente trabajadas ÷ horas de su horario transcurrido.",
    'e_genero': "Dinero generado en esas sesiones (individuales + parte de proyectos y mensualidades).",
    # ── Huecos ──
    'sec_huecos': "Dónde tiene tiempo libre el profesional: por hora, por día de la semana y en huecos concretos.",
    'heat': "Cada celda es una hora del día en un día de la semana. El número es el % de esa hora que estuvo ocupada, considerando todos los días transcurridos del período. Verde intenso = casi siempre ocupada, tenue = casi siempre libre. «·» = fuera de su horario.",
    'por_dia_semana': "Ocupación por día de la semana (horas ocupadas ÷ horas de horario). Muestra qué días está más cargado y cuáles más libre.",
    'franjas': "Franjas de una hora con menor y mayor ocupación promedio. Útil para saber a qué hora agendar nuevos niños.",
    'huecos_prox': "Huecos libres de 30 minutos o más en los próximos 14 días, calculados desde hoy, restando sesiones ya agendadas. Este bloque NO depende del rango elegido: siempre mira hacia adelante. Si el rango termina hoy no habría días futuros dentro de él, por eso se calcula aparte.",
    'huecos_pasados': "Huecos de 30 minutos o más, ya transcurridos, en los que el profesional estaba en horario y no tuvo ningún niño (ni atendido ni con falta).",
    # ── Horario / marcaje ──
    'sec_horario': "Horario con el que se midió y comparación con las marcaciones reales del profesional en el módulo de Asistencia.",
    'horario_base': "Horario usado para el cálculo. Si viene de Asistencia respeta días libres y fechas especiales (feriados, etc.); si no, se usa el predeterminado o el que definiste.",
    'marcaje': "Compara lo que marcó el profesional en Asistencia (entrada/salida) con lo que realmente atendió niños. Requiere que el profesional tenga usuario vinculado y marcaciones.",
    'm_centro': "Tiempo entre sus marcaciones de entrada y salida (cada tramo mañana/tarde por separado).",
    'm_pacientes': "Horas con niños en los mismos días en que marcó. El porcentaje indica qué parte de su presencia en el centro dedicó a atender.",
    'm_puntual': "Entradas puntuales ÷ total de entradas marcadas. Las tardanzas se toman de Asistencia.",
    'm_sin_marcar': "Días con horario ya transcurridos en los que no hay ninguna marcación válida.",
    # ── Niños ──
    'sec_ninos': "Niños que tuvo en sesiones dentro del período y filtros elegidos.",
    'n_libre_falta': "Horas que el profesional quedó libre por las faltas sin aviso de ese niño (se cobraron igual).",
    'n_asist': "Atendidas ÷ (atendidas + faltas + permisos). Mide la constancia del niño.",
    'n_gen': "Dinero generado por ese niño para este profesional, separado por tipo de atención.",
    # ── Servicios ──
    'por_servicio': "Distribución de su trabajo y producción por servicio. % = parte del total generado.",
    'por_sucursal': "Distribución de su trabajo por sucursal.",
    # ── Proyectos ──
    'sec_proyectos': "Proyectos/evaluaciones con sesiones del profesional en el período, incluso si los comparte con otros profesionales.",
    'p_modalidad': "Solo = lo atiende únicamente este profesional. Grupal = participan otros profesionales (se listan).",
    'p_valor': "Costo total fijo del proyecto (lo que paga el paciente).",
    'p_total_indiv': "Lo que valdrían TODAS las sesiones del proyecto (de todos los profesionales, realizadas y programadas) si cada una se cobrara como sesión suelta. Se usa el precio personalizado del paciente o, si no tiene, el precio base del servicio. Es solo una referencia para calcular porcentajes: no es dinero cobrado.",
    'p_factor': "Costo del proyecto ÷ valor a precio individual. Menor a 1 = paquete con descuento; mayor a 1 = se cobró más que sesiones sueltas. Un factor muy bajo (ej. 0,3) puede indicar precios mal cargados.",
    'p_sesiones': "Sus sesiones planificadas (realizadas + programadas + faltas) sobre el total del proyecto.",
    'p_particip': "Valor a precio individual de SUS sesiones ÷ valor a precio individual de TODAS las sesiones. Pondera por precio para que una hora más cara pese más. Debajo se ve el valor en Bs. de sus sesiones.",
    'p_su_parte': "Costo del proyecto × su participación. Es lo que le corresponde del proyecto completo.",
    'p_generado': "Parte de «su parte» que ya se devengó en el período, porque las sesiones se realizaron (o hubo falta sin aviso).",
    'p_por_generar': "Parte de «su parte» que se devengará cuando se realicen sus sesiones programadas.",
    'p_cobrado': "% pagado del proyecto completo. Se usa para estimar cuánto de lo que generó ya fue cobrado.",
    # ── Mensualidades ──
    'sec_mens': "Mensualidades con sesiones del profesional en el período, incluso si las comparte con otros profesionales.",
    'm_costo': "Costo mensual fijo del paquete.",
    'm_indiv': "Valor a precio individual de todas las sesiones de la mensualidad (de todos los profesionales) y, debajo, el de las suyas. Referencia para calcular su participación.",
    'm_por_sesion': "Su parte de la mensualidad ÷ sus sesiones planificadas. Es lo que «vale» cada sesión suya dentro del paquete.",
    'm_serv': "Servicios de la mensualidad asignados a este profesional.",
    # ── Equipo / tendencia ──
    'sec_equipo': "Cómo se compara el profesional con el resto del equipo y cómo viene evolucionando.",
    'ranking': "Ordenado por dinero generado en el mismo período. Se compara ocupación efectiva, ingreso por hora y % de faltas. Cada profesional se mide con su propio horario.",
    'tendencia': "Producción y ocupación de los últimos 6 meses. La tendencia se calcula con los meses completos desde que el profesional tiene actividad (mínimo 3). Sube/baja si el cambio es de 5% o más por mes.",
    # ── Retención ──
    'sec_retencion': "Indicadores para saber si el profesional retiene niños, depende de pocos y si registra su trabajo.",
    'retencion': "Activos: niños atendidos en los últimos 30 días. Nuevos: primera sesión atendida dentro del período. Retención: de los niños atendidos en el período anterior, cuántos siguen en este. En riesgo: atendidos hace 30-120 días pero ya sin sesiones recientes ni programadas.",
    'concentracion': "Qué parte de lo que genera depende de pocos niños. Riesgo ALTO si el mayor niño aporta ≥ 40% o los 3 mayores ≥ 75%; MEDIO si ≥ 25% o ≥ 55%.",
    'notas': "Porcentaje de sesiones atendidas que tienen nota de evolución registrada. Una nota faltante significa trabajo sin documentar.",
    # ── Detalle de sesiones ──
    'sec_sesiones': "Todas las sesiones del profesional en el período y con los filtros elegidos. Puedes buscar y filtrar sin recargar.",
    's_cobro': "Monto cobrado en la sesión. En proyectos y mensualidades siempre es 0: el paciente paga un precio fijo por el paquete, no por sesión. Por eso se muestra «en paquete».",
    's_genero': "Dinero que esa sesión le atribuye al profesional. Individual: lo cobrado. Proyecto/mensualidad: su parte del costo fijo dividida entre sus sesiones según el valor a precio individual. Entre paréntesis = por generar (sesión programada). «—» = no genera (permiso, cancelada, reprogramada).",
    's_nota': "✅ la sesión atendida tiene nota de evolución; ✖ no la tiene.",
    's_tipo': "Individual, o el código del proyecto/mensualidad al que pertenece, indicando si se atiende Solo o en Grupal con otros profesionales.",
    's_min': "Duración de la sesión en minutos.",
}

AYUDA.update({'e_ses': 'Sesiones del profesional en ese período (todas las del filtro, cualquier estado).', 'e_atend': 'Sesiones atendidas: realizadas + realizadas con retraso.', 'e_falta': 'Faltas sin aviso: el niño no vino y no avisó. Se cobran, pero el profesional quedó libre esa hora.', 'e_prog': 'Sesiones todavía en estado «programada» (futuras, o pasadas que no se registraron).', 'n_horas': 'Horas de sesiones atendidas (realizadas + con retraso), sumando cada niño por separado.', 's_ninos': 'Niños distintos atendidos en ese servicio.', 's_pct': 'Parte del total generado que corresponde a ese servicio/sucursal.', 'm_su_parte': 'Costo mensual × su participación. Es lo que le corresponde de la mensualidad completa.', 'm_generado': 'Parte de «su parte» ya devengada en el período por sesiones realizadas o faltas sin aviso.', 'm_cobrado': '% pagado de la mensualidad completa. Se usa para estimar cuánto de lo que generó ya fue cobrado.', 'm_atfp': 'Sus sesiones en el período: atendidas / faltas sin aviso / programadas.', 'r_faltas': '% de faltas sin aviso de sus niños: faltas ÷ (atendidas + faltas + permisos).'})


@register.simple_tag
def ayuda(clave):
    """Ícono «i» con globo explicativo. Solo para pantalla."""
    txt = AYUDA.get(clave)
    if not txt:
        return ''
    return format_html('<i class="inf no-print" tabindex="0" role="button" aria-label="Ayuda" data-t="{}">i</i>', txt)


@register.simple_tag
def ayuda_txt(texto):
    """Ícono «i» con un texto dinámico (p. ej. el de cada criterio del semáforo)."""
    if not texto:
        return ''
    return format_html('<i class="inf no-print" tabindex="0" role="button" aria-label="Ayuda" data-t="{}">i</i>', texto)
