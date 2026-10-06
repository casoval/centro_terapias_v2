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
