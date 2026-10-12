# facturacion/templatetags/reporte_fin_ayudas.py
# Ayudas «i» y filtros del Panel del Dueño del reporte financiero.
# Se carga con {% load reporte_prof_tags reporte_fin_ayudas %}: al importarse, agrega sus textos
# al diccionario AYUDA del sistema de ayudas existente (no modifica reporte_prof_tags.py).
from django import template

from .reporte_prof_tags import AYUDA

register = template.Library()


@register.filter
def bs0(value):
    """1234.5 → 1.235 (sin decimales, para cifras grandes)."""
    try:
        v = float(value or 0)
    except (TypeError, ValueError):
        return "0"
    return f"{v:,.0f}".replace(",", ".")


@register.filter
def bsd0(value):
    """Con signo y sin decimales: 1234 → +1.234 · -80 → -80"""
    try:
        v = float(value or 0)
    except (TypeError, ValueError):
        return "0"
    s = f"{abs(v):,.0f}".replace(",", ".")
    return ("+" if v > 0 else "-" if v < 0 else "") + s


AYUDA.update({
    'fi_panel': "Panel de decisión del dueño. Resume la salud económica del período elegido: cuánto se generó, cuánto se cobró, cuánto se debe, cuánto se gastó y qué conviene hacer. No reemplaza las demás pestañas: usa las mismas definiciones de ingresos y cobros para que las cifras cuadren con ellas. No usa el filtro «Registrado por».",
    'fi_generado': "Generado = lo que el centro ganó por servicios del período: sesiones sueltas realizadas (con retraso o falta), proyectos iniciados y mensualidades del mes. Es lo que se debería cobrar, haya o no entrado el dinero.",
    'fi_cobrado': "Cobrado neto = pagos recibidos en el período (sin «Uso de Crédito», que no es dinero nuevo) menos devoluciones. Es el dinero que realmente entró.",
    'fi_cobranza': "Cobranza = cobrado neto ÷ generado del período. Meta 80 %. Puede pasar de 100 % si se cobran deudas de períodos anteriores, o ser baja si se generó mucho y aún no se pagó.",
    'fi_cartera': "Deuda total de pacientes hoy: lo ya realizado más lo agendado, menos lo pagado (misma cifra que el «Saldo real» de la cuenta corriente). No depende del período elegido.",
    'fi_real': "Parte de la deuda que ya se consumió (sesiones, mensualidades y proyectos realizados). Es la deuda «firme»; el resto aún no se prestó.",
    'fi_egresos': "Gastos registrados en el módulo Egresos, ubicados por período contable (o por fecha de pago si no tiene período). Los marcados como honorario profesional no se suman aquí porque ya se descuentan como comisiones, para no duplicar.",
    'fi_resultado': "Resultado = cobrado neto − comisiones a profesionales externos − egresos. Es una vista de caja (lo que entró menos lo que salió), no un balance contable. Si no hay egresos registrados no es confiable.",
    'fi_margen': "Margen = resultado ÷ cobrado neto. Indica cuántos bolivianos quedan por cada 100 cobrados.",
    'fi_agendado': "Sesiones sueltas programadas en los próximos 30 días que ya tienen monto. Es ingreso comprometido, aún no generado.",
    'fi_creditos': "Saldos a favor de pacientes: dinero cobrado por adelantado por servicios que aún no se prestaron. Es una obligación del centro, no utilidad.",
    'fi_decisiones': "Lista automática de lo importante del período, ordenada por urgencia, con una acción sugerida. Se basa en umbrales: cobranza 80 % / 60 %, margen 10 %, deuda concentrada 50 %, dependencia de pacientes 35 %, devoluciones 3 %.",
    'fi_flujo': "Los últimos 12 meses terminando en el mes de «Hasta»: lo generado, lo cobrado y los egresos (barras) y el resultado cobrado − egresos (línea). Si la línea cae bajo cero, ese mes se gastó más de lo que entró.",
    'fi_composicion': "De dónde viene lo generado del período: sesiones sueltas, proyectos y mensualidades. Las mensualidades dan ingreso más estable y predecible.",
    'fi_metodos': "Cómo pagan las familias en el período (efectivo, QR, transferencia…), sin «Uso de Crédito». Sirve para controlar el manejo de efectivo.",
    'fi_cobrar': "Pacientes con mayor deuda, para cobrar. Ordenados por deuda total. La antigüedad es una estimación por orden de llegada (FIFO): se asume que cada pago cancela lo más antiguo primero. Riesgo alto: paciente inactivo con deuda, deuda de más de 60 días o más de 60 días sin pagar; medio: más de 30 días.",
    'fi_antig': "Reparte la deuda ya realizada según qué tan viejo es el consumo que la origina (estimación FIFO). Mientras más antigua, menos probable es recuperarla.",
    'fi_riesgo': "Alto: paciente inactivo con deuda, deuda con más de 60 días o más de 60 días sin pagar. Medio: más de 30 días. Bajo: reciente.",
    'fi_mas': "Pacientes que más generaron en el período (sesiones sueltas + proyectos + mensualidades). La barra muestra su peso sobre el total. «Cobrado» es lo que pagaron en el período; si es mucho menor que lo generado, hay saldo pendiente.",
    'fi_menos': "Pacientes con menor generación en el período (mayores a 0). Pueden ser pacientes con pocas sesiones, recién iniciados o en riesgo de dejar el servicio. Útil para decidir seguimiento o ampliar su plan.",
    'fi_concentracion': "Qué tan repartido está el ingreso. Si 5 pacientes generan más del 35 % hay dependencia: perder a uno golpea los ingresos.",
    'fi_cumplidos': "Pacientes con 3 o más pagos directos en el último año, al menos 80 % pagados dentro de 10 días del consumo y sin deuda actual. Ideales para reconocer y modelo de comportamiento.",
    'fi_lentos': "Pacientes con 3 o más pagos directos en el último año y menos de 50 % pagados dentro de 10 días. Candidatos a recordatorios tempranos, cobro por adelantado o plan de pago.",
    'fi_demora': "Demora promedio (ponderada por monto) entre el consumo y el pago, solo para pagos aplicados directamente a una sesión, proyecto o mensualidad.",
    'fi_egr_cat': "Egresos del período por categoría, de mayor a menor, sin honorarios profesionales (esos se ven como comisiones).",
    'fi_equilibrio': "Gastos del período llevados a un mes. Es lo mínimo que el centro debe cobrar al mes para no perder dinero (punto de equilibrio aproximado).",
    'fi_sucursales': "Comparación entre sucursales con las mismas definiciones. Los egresos globales (sin sucursal) no se reparten aquí, por eso el resultado por sucursal es antes de gastos compartidos.",
    'fi_servicios': "Servicios que más generan en el período (sesiones sueltas y proyectos por servicio base; las mensualidades se agrupan aparte).",
    'fi_cuadre': "Generado − cobrado mide lo ocurrido en el período. La deuda de pacientes es el saldo de hoy: lo consumido y agendado menos lo pagado, sumando solo a quienes deben. Si el período cubre todo el historial se cumple: generado − cobrado = deuda ya consumida − saldos a favor. La deuda total además incluye lo agendado, que aún no se generó.",
    'fi_antes': "Variación frente al período anterior de igual duración y mismos filtros.",
})
