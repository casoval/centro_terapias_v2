# facturacion/templatetags/cuenta_tags.py

from django import template
from decimal import Decimal

register = template.Library()


@register.filter
def abs_value(value):
    """Retorna el valor absoluto de un número"""
    try:
        return abs(Decimal(str(value)))
    except (ValueError, TypeError):
        return 0


@register.filter
def es_consistente(cuenta, tolerancia=0.01):
    """
    Verifica si el saldo actual coincide con el crédito disponible
    
    Usage: {% if cuenta|es_consistente %}
    """
    try:
        diferencia = abs(Decimal(str(cuenta.saldo_actual)) - Decimal(str(cuenta.pagos_adelantados)))
        return diferencia <= Decimal(str(tolerancia))
    except (ValueError, TypeError, AttributeError):
        return False


@register.simple_tag
def diferencia_saldo_credito(cuenta):
    """
    Calcula la diferencia entre saldo actual y crédito disponible
    
    Usage: {% diferencia_saldo_credito cuenta as diff %}
    """
    try:
        return abs(Decimal(str(cuenta.saldo_actual)) - Decimal(str(cuenta.pagos_adelantados)))
    except (ValueError, TypeError, AttributeError):
        return Decimal('0')


@register.inclusion_tag('facturacion/partials/validacion_credito.html')
def validacion_credito(cuenta):
    """
    Renderiza un componente de validación de crédito
    
    Usage: {% validacion_credito cuenta %}
    """
    try:
        saldo = Decimal(str(cuenta.saldo_actual))
        credito = Decimal(str(cuenta.pagos_adelantados))
        diferencia = abs(saldo - credito)
        es_consistente = diferencia <= Decimal('0.01')
        
        return {
            'cuenta': cuenta,
            'saldo': saldo,
            'credito': credito,
            'diferencia': diferencia,
            'es_consistente': es_consistente
        }
    except (ValueError, TypeError, AttributeError):
        return {
            'cuenta': cuenta,
            'error': True
        }