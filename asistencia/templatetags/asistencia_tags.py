"""Filtros para mostrar la evaluación de asistencia (estrellas, semáforo, minutos:segundos, días)."""
from django import template
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe

from ..informe_mensual import fmt_dias
from ..services import fmt_min_seg

register = template.Library()


@register.simple_tag
def estrellas(ev, tam='1.05rem'):
    """5 estrellas (con media estrella) en el color de la evaluación de puntualidad, más su etiqueta."""
    if not ev:
        return mark_safe('<span class="text-xs text-gray-300">Sin datos</span>')
    llenas = int(ev['estrellas'])
    media = (ev['estrellas'] - llenas) >= 0.5
    gris = '#d1d5db'
    partes = []
    for i in range(5):
        if i < llenas:
            estilo = f"color:{ev['color']}"
        elif i == llenas and media:
            estilo = (f"background:linear-gradient(90deg,{ev['color']} 50%,{gris} 50%);"
                      "-webkit-background-clip:text;background-clip:text;color:transparent")
        else:
            estilo = f"color:{gris}"
        partes.append((estilo, tam))
    html = format_html_join('', '<span style="{};font-size:{};line-height:1">★</span>', partes)
    return format_html(
        '<span class="inline-flex items-center gap-1.5" title="{}">'
        '<span class="inline-flex">{}</span>'
        '<span class="text-xs font-semibold" style="color:{}">{}</span></span>',
        ev['motivo'], html, ev['color'], ev['etiqueta'])


@register.simple_tag
def semaforo(ev):
    """Círculo verde / amarillo / rojo con su etiqueta."""
    if not ev:
        return mark_safe('<span class="text-xs text-gray-300">Sin datos</span>')
    return format_html(
        '<span class="inline-flex items-center gap-1.5" title="{}">'
        '<span style="display:inline-block;width:.8rem;height:.8rem;border-radius:9999px;background:{}"></span>'
        '<span class="text-xs font-semibold" style="color:{}">{}</span></span>',
        ev['motivo'], ev['color'], ev['color'], ev['etiqueta'])


@register.filter
def min_seg(segundos):
    """90 -> '1:30' (minutos:segundos)."""
    try:
        return fmt_min_seg(segundos)
    except (TypeError, ValueError):
        return '0:00'


@register.filter
def dias(valor):
    """1.5 -> '1,5'."""
    try:
        return fmt_dias(valor)
    except (TypeError, ValueError):
        return '0'
