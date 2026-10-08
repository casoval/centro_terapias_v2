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
    'f_costo': "Opcional. Escribe cuánto le cuesta al centro este profesional por mes (sueldo y cargas). El sistema no guarda sueldos del personal interno, por eso se ingresa aquí. Con ese dato se calcula el margen y la cobertura, y se agrega el criterio de rentabilidad al semáforo. Se prorratea por los días de cada mes calendario: un mes completo equivale al costo mensual exacto; si el período abarca parte de un mes, se cuenta la fracción de días (ej. 08/09 al 07/10 = 23/30 de septiembre + 7/31 de octubre ≈ 0,99 mes).",
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
    'k_margen': "Lo que aporta al centro menos lo que cuesta. Aporte = total generado (si es servicio externo, se descuenta la comisión que se lleva el profesional). Costo = costo mensual ingresado × meses del período, prorrateado por días de cada mes calendario (un mes completo = el costo exacto). Cobertura = aporte ÷ costo (1× = cubre justo su costo).",
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

AYUDA.update({'sec_concil': 'Sirve para entender por qué las cifras de este informe pueden ser distintas a las del reporte financiero. Compara, para el mismo período, lo que el financiero cuenta como «generado» contra lo que este informe devenga sumando a TODOS los profesionales, y explica la diferencia partida por partida.', 'c_financiero': 'Total «generado real» del reporte financiero para el mismo período. Sesiones: por fecha de sesión (realizadas, con retraso y faltas sin aviso). Proyectos: costo COMPLETO de los iniciados en el período (en progreso, finalizados o cancelados). Mensualidades: costo completo de las del mes/año dentro del rango.', 'c_este': 'Lo que este informe devenga en el período sumando a todos los profesionales. Proyectos y mensualidades se reconocen conforme se realizan las sesiones (repartidas por el valor de cada sesión a precio individual), no de golpe.', 'c_dif': 'Este informe − Financiero. Negativo = el financiero ya contó dinero que este informe aún no devenga (sesiones pendientes o de otras fechas). Se explica en las líneas de ajuste.', 'c_prof': 'Cuánto de la columna «Este informe» corresponde a este profesional, sin considerar los filtros de servicio/niño/tipo/estado. Debe coincidir con «Cuánto genera» cuando no hay filtros.', 'c_ajustes': 'Cada línea explica una causa de la diferencia. Financiero + (ajustes) = Este informe. Si la verificación marca «cuadra», toda la diferencia está explicada.', 'c_check': 'Verificación automática: comprueba que Financiero + ajustes sea igual a Este informe, y que la cifra del profesional coincida con la sección «Cuánto genera». Si algo no cuadra se avisa para revisar los datos.'})
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


@register.filter
def bsd(value):
    """Variación con signo: 1234.5 → +1.234,50 · -80 → -80,00"""
    try:
        v = float(value or 0)
    except (TypeError, ValueError):
        return "0,00"
    s = f"{abs(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return ("+" if v > 0 else "-" if v < 0 else "") + s


# ══════════════════════════════════════════════════════════════════════
# AYUDA DEL REPORTE POR SUCURSAL (claves con prefijo su_)
# ══════════════════════════════════════════════════════════════════════
AYUDA.update({
    # ── Filtros y cuadros de gastos ──
    'su_f_sucursal': "Sucursal de la que se arma el informe. Se consolidan TODOS sus profesionales y sus sesiones; los números de cada profesional cuadran con su propio informe.",
    'su_f_gastos': "Aquí decides qué gastos cuentan. Se suman tres fuentes: 1) egresos ya registrados en el sistema, 2) los cuadros que completes (alquiler, servicios, limpieza…) y 3) el costo mensual de cada profesional. Con eso se calcula el resultado, el margen, el punto de equilibrio y la rentabilidad de cada profesional y niño.",
    'su_f_egr': "Incluye los egresos registrados en el módulo de Egresos (no anulados) de esta sucursal. Se ubican por su período contable (mes/año del gasto, no la fecha de pago). Si el período abarca solo parte de un mes, se cuenta la fracción de días de ese mes.",
    'su_f_glob': "Los egresos registrados SIN sucursal son globales (publicidad general, contador, etc.). Aquí eliges cómo cargarlos a esta sucursal: proporcional a las horas atendidas de cada sucursal (recomendado), en partes iguales, o no incluirlos.",
    'su_f_pers': "Qué hacer con los egresos registrados de tipo Personal o Honorarios. Automático: se incluyen, salvo que ingreses costos por profesional (así no se cuenta dos veces el mismo sueldo). Incluir / Excluir fuerzan la decisión. Ojo: la comisión de profesionales externos ya se descuenta del ingreso neto, no la dupliques aquí.",
    'su_f_manual': "Escribe los gastos que tú ves: concepto y monto en Bs. Usa «Mensual» para gastos que se repiten cada mes (se prorratean por días de cada mes calendario) o «Total del período» para un gasto único que ocurrió en el rango. Se guardan en la dirección (URL) del informe: puedes marcarla como favorita para repetirlo.",
    'su_f_freq': "Mensual: el monto se cobra cada mes y se prorratea por los días del período (un mes completo = el monto exacto). Total del período: se cuenta una sola vez, repartido por días entre los meses del rango.",
    'su_f_cp': "Opcional. Cuánto le cuesta al centro cada profesional por mes (sueldo y cargas). El sistema no guarda sueldos internos, por eso se ingresa aquí. Con ese dato se calcula el margen y la cobertura de cada profesional, y se reparte entre los niños que atiende.",
    'su_f_comp': "Compara esta sucursal con las demás activas (ingreso neto, ocupación, gastos). Hace el cálculo completo de cada sucursal, por eso puede tardar unos segundos más.",
    # ── Indicadores ──
    'su_gen': "Devengado: lo que la sucursal PRODUJO en el período, se haya pagado o no. Total generado por todos los profesionales de la sucursal: sesiones individuales (incluye faltas sin aviso, que se cobran) + parte ponderada de proyectos y mensualidades devengada en el período.",
    'su_neto': "Generado (devengado, no es dinero cobrado) que queda al centro: generado menos la comisión que corresponde a profesionales externos (servicios con comisión). Es la base para medir la rentabilidad.",
    'su_gastos': "Total de gastos considerados en el período: operativos (alquiler, servicios…) más costo de personal/profesionales. Revisa el detalle en «Gastos».",
    'su_resultado': "Ingreso neto − gastos. Positivo = la sucursal gana dinero en el período; negativo = pierde. Depende de los gastos que hayas incluido.",
    'su_margen': "Resultado ÷ ingreso neto. Indica cuántos centavos de cada boliviano neto quedan después de pagar los gastos.",
    'su_cobertura': "Ingreso neto ÷ gastos. 1,0× = punto de equilibrio. Por encima de 1 cubre sus gastos; por debajo, no.",
    'su_equilibrio': "Cuánto falta para cubrir los gastos, expresado en horas y sesiones adicionales al ritmo actual de ingreso neto. Compáralo con las horas sin paciente agendado: si hay más horas libres que las necesarias, el problema es llenar la agenda.",
    'su_gasto_hora': "Gastos totales ÷ horas efectivamente trabajadas. Es lo que cuesta cada hora de atención: si el ingreso neto por hora es menor, cada hora trabajada pierde dinero.",
    'su_ing_hora': "Ingreso neto ÷ horas de reloj trabajadas por los profesionales. Compárelo con el costo por hora de los gastos.",
    'su_ocup_efect': "Horas realmente trabajadas con pacientes ÷ horas de horario transcurrido de todos los profesionales de la sucursal (suma de capacidades).",
    'su_ocup_agend': "Horas con sesión agendada u ocupada (incluye faltas sin aviso, que el profesional esperó) ÷ horas de horario transcurrido.",
    'su_horas': "Horas de reloj trabajadas por los profesionales (suma). Una sesión grupal simultánea no duplica horas. El horario sale de Asistencia o, si no está configurado, del predeterminado.",
    'su_potencial': "Estimación teórica: horas libres que no generaron dinero × ingreso neto por hora actual, con la agenda llena. Con pocas sesiones en el período puede salir inflado: tómalo como orden de magnitud, no como dinero seguro.",
    'su_semaforo': "Resume en un puntaje de 0 a 100 si la sucursal es sana. Cada criterio vale verde (1), ámbar (0,5) o rojo (0) y se pondera según su importancia (la cobertura de gastos pesa más). Los criterios y sus umbrales están a la vista. Es orientativo: la decisión es del dueño.",
    'su_hallazgos': "Frases generadas automáticamente con los números del informe. Rojo = requiere atención, azul = informativo, verde = positivo, amarillo = nota sobre los datos.",
    # ── Secciones ──
    'su_sec_resultado': "Cómo se llega al resultado: del ingreso generado al neto del centro y de ahí, restando gastos, al resultado final. Incluye el punto de equilibrio.",
    'su_sec_gastos': "Gastos considerados, por concepto y origen: registrados en el sistema, globales prorrateados, cuadros ingresados por ti y costo de profesionales.",
    'su_g_origen': "Registrado = egreso de la sucursal en el módulo de Egresos. Global = egreso sin sucursal, cargado según el reparto elegido. Ingresado = cuadro que completaste. Profesional = costo mensual por profesional.",
    'su_sec_tipos': "De dónde viene el dinero: sesiones individuales, proyectos/evaluaciones y mensualidades, con su ingreso por hora para comparar qué tipo de atención rinde más.",
    'su_sec_servicio': "Rendimiento por servicio: sesiones, horas, ingreso e ingreso por hora. El ingreso por hora usa horas-paciente (cada niño cuenta por separado).",
    'su_t_bs_hora': "Ingreso ÷ horas atendidas de ese tipo o servicio. Sirve para ver qué se paga mejor por hora de trabajo.",
    'su_sec_horas': "Cómo se usó el tiempo de la sucursal: horas trabajadas, perdidas por inasistencia, canceladas y sin paciente agendado, más su evolución y mapa de calor.",
    'su_desglose': "Cada hora del horario transcurrido de los profesionales se clasifica en una sola causa. Falta sin aviso se cobra; permiso, cancelada, reprogramada y sin paciente agendado no.",
    'su_evol': "Evolución por mes, semana o día. En meses se muestra ingreso neto, gastos y resultado; en semanas y días, atenciones, faltas e ingreso.",
    'su_heat': "Ocupación de la sucursal por día y hora: suma de todos los profesionales. Verde intenso = franja llena; claro = vacía. Muestra cuándo hay capacidad sin usar.",
    'su_franjas': "Horas del día con menor y mayor ocupación consolidada. Son las franjas donde conviene captar pacientes (libres) o donde falta capacidad (llenas).",
    'su_sec_profes': "Aporte y rentabilidad de cada profesional dentro de la sucursal, con su ocupación, horas libres y, si ingresaste su costo, margen y cobertura.",
    'su_p_neto': "Lo que el profesional aporta al centro: su generado menos comisión externa. Entre paréntesis, su peso en el ingreso neto de la sucursal.",
    'su_p_costo': "Costo mensual que ingresaste, prorrateado por días del período. Vacío = no ingresaste costo para ese profesional.",
    'su_p_margen': "Aporte neto − costo del profesional. Verde = cubre su costo; rojo = no lo cubre.",
    'su_p_cobertura': "Aporte neto ÷ costo. 1,0× = cubre justo su costo.",
    'su_p_ocup': "Ocupación efectiva (horas con pacientes ÷ horas de su horario transcurrido). Entre paréntesis, la agendada.",
    'su_p_libre': "Horas de su horario sin sesión (tiempo libre) y horas perdidas por inasistencia/cancelación.",
    'su_sec_ninos': "Rentabilidad de cada niño: lo que aporta (neto) menos el costo que se le asigna según los minutos que se atiende.",
    'su_n_neto': "Generado del niño en la sucursal (sesiones individuales + su parte de paquetes), ajustado por la comisión externa proporcional.",
    'su_n_costo': "Costo asignado = costo directo del profesional (repartido por minutos atendidos de cada niño) + resto de gastos repartido por minutos atendidos. Es una asignación, no un gasto real por niño.",
    'su_n_margen': "Neto − costo asignado. Rojo = el niño no cubre el costo que se le asigna. La suma de márgenes de todos los niños es igual al resultado de la sucursal.",
    'su_conc_prof': "Qué parte del ingreso neto de la sucursal depende de uno o pocos profesionales. Si es muy alto, la sucursal es frágil ante una salida.",
    'su_conc_pac': "Qué parte del ingreso depende de uno o pocos niños. Si es muy alto, perder unos pocos pacientes golpea la sucursal.",
    'su_sec_paquetes': "Proyectos y mensualidades de la sucursal con el reparto entre profesionales. El % de participación se pondera por lo que costaría cada sesión como individual (precio del paciente o precio base del servicio).",
    'su_pq_gen': "Parte del costo fijo ya devengada en el período por sesiones realizadas o faltas sin aviso, sumando a todos los profesionales.",
    'su_pq_factor': "Costo del paquete ÷ valor de sus sesiones a precio individual. Menor a 1 = se vendió con descuento; mayor a 1 = se cobró más que las sesiones sueltas.",
    'su_pq_partes': "Reparto del paquete entre profesionales: nombre, % de participación y lo que generó cada uno en el período.",
    'su_sec_comp': "Cómo va esta sucursal frente al período anterior (misma duración) y frente a las demás sucursales activas.",
    'su_comp_ant': "Compara con el período inmediatamente anterior de igual duración. Verde = mejora, rojo = empeora (en gastos, subir es negativo).",
    'su_comp_suc': "Ingreso neto, ocupación y resultado de cada sucursal activa. Para las otras sucursales solo se consideran sus egresos registrados (los cuadros manuales y costos por profesional aplican solo a la sucursal elegida).",
    'su_sec_concil': "Compara el generado de este informe con el consumido del reporte financiero para entender las diferencias. Los pagos y la cobranza se ven con fechas en la sección «Cobranza y flujo de caja».",
    'su_c_consumido': "Total consumido de la sucursal según el reporte financiero: sesiones por fecha, proyectos iniciados y mensualidades del mes, completos.",
    # ── Cobranza y flujo de caja ──
    'su_sec_cobranza': "Separa lo que la sucursal PRODUJO (generado/devengado, se haya pagado o no) de lo que realmente se COBRÓ. Permite ver cuánto falta cobrar, qué tan atrasado está, qué entró a caja y de qué período era, para proyectar y evaluar retrasos de pago.",
    'su_cb_gen': "Generado dentro del período (sesiones realizadas, mensualidades y proyectos devengados), antes de descontar la comisión de profesionales externos. No depende de si el paciente pagó.",
    'su_cb_cobrado': "De lo generado en el período, la parte que ya fue pagada hasta hoy (en cualquier fecha: antes, durante o después del período). El uso de crédito cuenta como pagado.",
    'su_cb_pend': "Lo generado en el período que todavía no se ha pagado. Es el dinero por cobrar de este período.",
    'su_cb_mora': "Parte del pendiente con más de 30 días de antigüedad. En sesiones se cuenta desde la fecha de la sesión; en paquetes desde su inicio o desde el inicio del período.",
    'su_cb_caja': "Dinero recibido con fecha de pago dentro del período (efectivo, QR, transferencia…), menos devoluciones. Incluye cobros de deudas atrasadas y adelantos, por eso NO es lo mismo que lo generado. No incluye el uso de crédito (no es dinero nuevo).",
    'su_cb_prog': "Lo que aún no se ha producido pero está en agenda: sesiones programadas a su precio y la parte de proyectos/mensualidades por consumir.",
    'su_cb_tabla1': "Toma lo generado en el período y muestra cuándo se pagó: antes del período (adelantado), durante o después (cobro tardío). Lo que falta es lo pendiente de cobro.",
    'su_cb_antes': "Pagos hechos antes del inicio del período por consumos que se generaron dentro de él (el paciente pagó por adelantado).",
    'su_cb_despues': "Pagos hechos después del fin del período (hasta hoy) por consumos del período: cobro tardío.",
    'su_cb_tabla2': "Clasifica el dinero que entró en el período según lo que pagó: consumos de este período, deudas de períodos anteriores, adelantos de consumos futuros o crédito sin asignar.",
    'su_cb_anterior': "Pagos recibidos en este período por sesiones, mensualidades o proyectos de períodos anteriores: recuperación de deuda atrasada.",
    'su_cb_adelanto': "Pagos recibidos por sesiones programadas, mensualidades o proyectos que corresponden a consumos posteriores o que aún no se realizaron.",
    'su_cb_credito': "Pagos de adelanto sin sesión, mensualidad ni proyecto asignado (crédito a favor del paciente). Solo se cuentan pacientes cuya sucursal principal es esta.",
    'su_cb_uso_credito': "Consumos pagados con crédito que el paciente ya había adelantado. Salda la deuda pero no genera ingreso de caja nuevo.",
    'su_cb_aging': "Cuánto falta cobrar según los días transcurridos desde que se generó. Mientras más antiguo, más difícil de recuperar.",
    'su_cb_deudores': "Pacientes con más saldo pendiente de lo generado en el período, con su antigüedad máxima. Sirve para priorizar el cobro.",
    'su_cb_proy': "Suma lo ya generado y lo programado para estimar el cierre del período, y estima cuánto de lo programado se cobraría si se mantiene la tasa de cobro actual. Es una estimación orientativa.",
    'su_cb_periodo': "Dinero (efectivo, QR, transferencia…) recibido DENTRO del período por sesiones realizadas, mensualidades o proyectos de este período. En paquetes se cuenta el pago completo recibido. No incluye lo pagado antes del período ni el uso de crédito, por eso puede diferir de «Cobrado de lo generado».",
    'su_cb_puente': "Explica la diferencia entre las dos cifras: se parte de «Cobrado de lo generado», se restan lo pagado antes, lo pagado después y el uso de crédito (no entran a la caja de este período) y la última línea ajusta los paquetes, donde la caja cuenta el pago completo y el generado solo la parte devengada. Siempre cierra exacto.",
})

