"""
Filtros de plantilla para mostrar fechas SIEMPRE como dd/mm/aaaa.

Se registran como "builtins" en settings.TEMPLATES, por lo que se pueden usar
en cualquier plantilla sin `{% load %}`.

A diferencia del filtro nativo |date, estos filtros también aceptan STRINGS
(p. ej. '2026-10-11' que llega desde request.GET o desde una vista), donde
|date devuelve vacío.

    {{ fecha_desde|fecha }}            → 01/10/2026
    {{ pago.concepto|texto_fechas }}   → 'Pago sesión 2026-10-08' se muestra 'Pago sesión 08/10/2026'
    {{ fecha|fecha_iso }}              → 2026-10-11  (solo para inputs/URLs)
    {{ fecha|fecha_hora }}             → 11/10/2026 15:30
    {{ fecha|fecha_corta }}            → 11/10
    {{ desde|periodo:hasta }}          → 01/10/2026 al 11/10/2026
    {{ fecha|fecha_larga_es }}         → 11 de octubre de 2026
    {{ fecha|mes_anio_es }}            → octubre 2026
"""
from django import template

from core import fechas as F

register = template.Library()


@register.filter(name='fecha')
def fecha(valor, vacio=''):
    return F.fmt_fecha(valor, vacio)


@register.filter(name='fecha_iso')
def fecha_iso(valor):
    """USO INTERNO: valor para <input type="date"> / URLs (aaaa-mm-dd). Acepta date o texto."""
    d = F.parse_fecha(valor)
    return d.strftime('%Y-%m-%d') if d else ''


@register.filter(name='fecha_hora')
def fecha_hora(valor, vacio=''):
    return F.fmt_fecha_hora(valor, vacio)


@register.filter(name='fecha_corta')
def fecha_corta(valor, vacio=''):
    return F.fmt_fecha_corta(valor, vacio)


@register.filter(name='fecha_larga_es')
def fecha_larga_es(valor, vacio=''):
    return F.fecha_larga(valor, vacio)


@register.filter(name='mes_anio_es')
def mes_anio_es(valor, vacio=''):
    return F.mes_anio(valor, vacio)


@register.filter(name='periodo')
def periodo(desde, hasta):
    """{{ desde|periodo:hasta }} → 'dd/mm/aaaa al dd/mm/aaaa'"""
    d1, d2 = F.parse_fecha(desde), F.parse_fecha(hasta)
    if not d1 or not d2:
        return ''
    return f"{F.fmt_fecha(d1)} al {F.fmt_fecha(d2)}"


@register.filter(name='texto_fechas')
def texto_fechas(valor):
    """Muestra un texto con las fechas aaaa-mm-dd que contenga convertidas a dd/mm/aaaa.
    Solo para MOSTRAR: nunca usarlo en value= de inputs ni en datos que se vuelven a guardar."""
    return F.fmt_texto_fechas(valor)
