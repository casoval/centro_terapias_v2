"""
Template Tags Optimizados para Facturación
==========================================

Uso en template:
    {% load facturacion_tags %}
    
    {{ cuenta|get_balance_final }}
    {{ cuenta|get_deuda_total }}
    
Instalar:
    1. Crear directorio: facturacion/templatetags/
    2. Crear archivo: facturacion/templatetags/__init__.py (vacío)
    3. Guardar este archivo como: facturacion/templatetags/facturacion_tags.py
"""

from django import template
from decimal import Decimal

register = template.Library()


@register.filter(name='get_balance_final')
def get_balance_final(cuenta_corriente):
    """
    Obtiene el balance final usando cache
    
    Uso: {{ cuenta|get_balance_final }}
    """
    try:
        stats = cuenta_corriente.get_stats_cached()
        deuda_total = stats['deuda_sesiones'] + stats['deuda_proyectos']
        return cuenta_corriente.saldo - deuda_total
    except (AttributeError, KeyError):
        # Fallback al método lento si hay error
        return cuenta_corriente.balance_final


@register.filter(name='get_deuda_total')
def get_deuda_total(cuenta_corriente):
    """
    Obtiene la deuda total usando cache
    
    Uso: {{ cuenta|get_deuda_total }}
    """
    try:
        stats = cuenta_corriente.get_stats_cached()
        return stats['deuda_sesiones'] + stats['deuda_proyectos']
    except (AttributeError, KeyError):
        return cuenta_corriente.total_deuda_general


@register.filter(name='get_deuda_sesiones')
def get_deuda_sesiones(cuenta_corriente):
    """
    Obtiene la deuda de sesiones usando cache
    
    Uso: {{ cuenta|get_deuda_sesiones }}
    """
    try:
        stats = cuenta_corriente.get_stats_cached()
        return stats['deuda_sesiones']
    except (AttributeError, KeyError):
        return cuenta_corriente.deuda_sesiones


@register.filter(name='get_deuda_proyectos')
def get_deuda_proyectos(cuenta_corriente):
    """
    Obtiene la deuda de proyectos usando cache
    
    Uso: {{ cuenta|get_deuda_proyectos }}
    """
    try:
        stats = cuenta_corriente.get_stats_cached()
        return stats['deuda_proyectos']
    except (AttributeError, KeyError):
        return cuenta_corriente.deuda_proyectos


@register.simple_tag
def get_cuenta_stats(cuenta_corriente):
    """
    Obtiene todas las stats de una vez para usar en template
    
    Uso:
        {% get_cuenta_stats cuenta as stats %}
        {{ stats.deuda_sesiones }}
        {{ stats.deuda_proyectos }}
    """
    try:
        return cuenta_corriente.get_stats_cached()
    except AttributeError:
        # Fallback manual
        return {
            'consumo_sesiones': cuenta_corriente.consumo_sesiones,
            'pagado_sesiones': cuenta_corriente.pagado_sesiones,
            'deuda_sesiones': cuenta_corriente.deuda_sesiones,
            'consumo_proyectos': cuenta_corriente.consumo_proyectos,
            'pagado_proyectos': cuenta_corriente.pagado_proyectos,
            'deuda_proyectos': cuenta_corriente.deuda_proyectos,
        }


@register.filter
def subtract(value, arg):
    """
    Resta dos valores
    
    Uso: {{ saldo|subtract:deuda }}
    """
    try:
        return Decimal(str(value)) - Decimal(str(arg))
    except (ValueError, TypeError):
        return value


@register.filter  
def add_decimal(value, arg):
    """
    Suma dos valores decimales
    
    Uso: {{ valor1|add_decimal:valor2 }}
    """
    try:
        return Decimal(str(value)) + Decimal(str(arg))
    except (ValueError, TypeError):
        return value


@register.filter
def format_currency(value):
    """
    Formatea un valor como moneda boliviana
    
    Uso: {{ monto|format_currency }}
    Resultado: Bs. 100.00
    """
    try:
        value = Decimal(str(value))
        return f"Bs. {value:,.2f}"
    except (ValueError, TypeError):
        return value


@register.filter
def balance_class(balance):
    """
    Retorna clase CSS según el balance
    
    Uso: <span class="{{ balance|balance_class }}">{{ balance }}</span>
    """
    try:
        balance = Decimal(str(balance))
        if balance < 0:
            return 'text-danger'  # Rojo (debe)
        elif balance > 0:
            return 'text-success'  # Verde (a favor)
        else:
            return 'text-muted'  # Gris (al día)
    except (ValueError, TypeError):
        return ''


@register.filter
def balance_icon(balance):
    """
    Retorna ícono según el balance
    
    Uso: <i class="{{ balance|balance_icon }}"></i>
    """
    try:
        balance = Decimal(str(balance))
        if balance < 0:
            return 'bi bi-arrow-down-circle text-danger'
        elif balance > 0:
            return 'bi bi-arrow-up-circle text-success'
        else:
            return 'bi bi-check-circle text-muted'
    except (ValueError, TypeError):
        return ''


@register.inclusion_tag('facturacion/widgets/balance_badge.html')
def balance_badge(cuenta_corriente):
    """
    Widget de badge para mostrar balance
    
    Uso: {% balance_badge cuenta %}
    """
    try:
        stats = cuenta_corriente.get_stats_cached()
        deuda_total = stats['deuda_sesiones'] + stats['deuda_proyectos']
        balance = cuenta_corriente.saldo - deuda_total
    except (AttributeError, KeyError):
        balance = cuenta_corriente.balance_final
    
    return {
        'balance': balance,
        'saldo': cuenta_corriente.saldo,
    }


@register.simple_tag
def calculate_sesion_totals(sesion):
    """
    Calcula totales de una sesión usando valores pre-calculados
    
    Uso: {% calculate_sesion_totals sesion as totales %}
    """
    # Si ya tiene valores calculados por annotate, usarlos
    if hasattr(sesion, 'total_pagado_calc'):
        return {
            'total_pagado': sesion.total_pagado_calc,
            'total_contado': sesion.total_pagado_contado_calc,
            'total_credito': sesion.total_pagado_credito_calc,
            'saldo_pendiente': sesion.saldo_pendiente_calc,
        }
    
    # Fallback a properties (más lento)
    return {
        'total_pagado': sesion.total_pagado,
        'total_contado': sesion.total_pagado_contado,
        'total_credito': sesion.total_pagado_credito,
        'saldo_pendiente': sesion.saldo_pendiente,
    }


# ================== EJEMPLO DE USO EN TEMPLATE ==================
"""
{% load facturacion_tags %}

{# Método 1: Usando filtros #}
<div class="balance {{ cuenta|get_balance_final|balance_class }}">
    Balance: {{ cuenta|get_balance_final|format_currency }}
</div>

{# Método 2: Usando tag para obtener todas las stats #}
{% get_cuenta_stats cuenta as stats %}
<ul>
    <li>Deuda Sesiones: {{ stats.deuda_sesiones|format_currency }}</li>
    <li>Deuda Proyectos: {{ stats.deuda_proyectos|format_currency }}</li>
    <li>Total Deuda: {{ stats.deuda_sesiones|add_decimal:stats.deuda_proyectos|format_currency }}</li>
</ul>

{# Método 3: Widget de badge #}
{% balance_badge cuenta %}

{# Método 4: Para sesiones con valores pre-calculados #}
{% for sesion in sesiones %}
    {% calculate_sesion_totals sesion as totales %}
    <tr>
        <td>{{ sesion.fecha }}</td>
        <td>{{ totales.total_pagado|format_currency }}</td>
        <td>{{ totales.saldo_pendiente|format_currency }}</td>
    </tr>
{% endfor %}
"""