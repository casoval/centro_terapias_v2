from django import template
from datetime import date, datetime

register = template.Library()

DIAS_SEMANA = {
    0: 'Lunes',
    1: 'Martes', 
    2: 'Miércoles',
    3: 'Jueves',
    4: 'Viernes',
    5: 'Sábado',
    6: 'Domingo'
}

MESES = {
    1: 'Enero',
    2: 'Febrero',
    3: 'Marzo',
    4: 'Abril',
    5: 'Mayo',
    6: 'Junio',
    7: 'Julio',
    8: 'Agosto',
    9: 'Septiembre',
    10: 'Octubre',
    11: 'Noviembre',
    12: 'Diciembre'
}

@register.filter
def dia_semana(fecha):
    """Retorna el nombre del día de la semana en español"""
    if isinstance(fecha, (date, datetime)):
        return DIAS_SEMANA[fecha.weekday()]
    return ''

@register.filter
def mes_nombre(fecha):
    """Retorna el nombre del mes en español"""
    if isinstance(fecha, (date, datetime)):
        return MESES[fecha.month]
    return ''

@register.filter
def fecha_larga(fecha):
    """Formato: Lunes, 14 de Diciembre de 2025"""
    if isinstance(fecha, (date, datetime)):
        dia = DIAS_SEMANA[fecha.weekday()]
        mes = MESES[fecha.month]
        return f"{dia}, {fecha.day} de {mes} de {fecha.year}"
    return ''

@register.filter
def mes_anio(fecha):
    """Formato: Diciembre 2025"""
    if isinstance(fecha, (date, datetime)):
        mes = MESES[fecha.month]
        return f"{mes} {fecha.year}"
    return ''