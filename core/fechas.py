"""
Utilidades centrales de formato de fechas.

CONVENCIÓN DEL SISTEMA: toda fecha que VE el usuario se muestra como
día-mes-año  →  dd/mm/aaaa   (ej. 11/10/2026).

El formato ISO (aaaa-mm-dd) se usa ÚNICAMENTE de forma interna:
  · value de <input type="date"> (el estándar HTML lo exige)
  · parámetros de URL / filtros GET / JSON entre servidor y JavaScript
  · nombres de archivo y claves de caché

Este módulo NO importa modelos de Django, por lo que puede usarse desde
cualquier parte (vistas, generadores de PDF, comandos, plantillas) sin
riesgo de imports circulares.
"""
import re
from datetime import date, datetime

# ── Nombres en español ───────────────────────────────────────────────
# (strftime('%B') / calendar.month_name dependen del locale del servidor
#  y devuelven "October" en inglés si no está configurado.)
MESES = ['', 'enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio',
         'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre']
MESES_ABREV = ['', 'ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago',
               'sep', 'oct', 'nov', 'dic']
DIAS = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo']
DIAS_ABREV = ['lun', 'mar', 'mié', 'jue', 'vie', 'sáb', 'dom']

FORMATO_FECHA = '%d/%m/%Y'
FORMATO_FECHA_HORA = '%d/%m/%Y %H:%M'

# Formatos de texto que se aceptan al interpretar un valor recibido como string.
_FORMATOS_ENTRADA = (
    '%Y-%m-%d',            # ISO  (inputs type="date", URLs, JSON)
    '%d/%m/%Y',            # formato del sistema
    '%d-%m-%Y',
    '%Y/%m/%d',
    '%Y-%m-%dT%H:%M:%S',
    '%Y-%m-%dT%H:%M:%S.%f',
    '%Y-%m-%d %H:%M:%S',
    '%Y-%m-%d %H:%M:%S.%f',
    '%Y-%m-%dT%H:%M',
    '%d/%m/%Y %H:%M',
    '%d/%m/%Y %H:%M:%S',
)


def parse_fecha(valor):
    """
    Convierte `valor` en un objeto `date`. Acepta date, datetime o string
    (ISO 'aaaa-mm-dd', 'dd/mm/aaaa', con o sin hora, con zona 'Z' / '+00:00').
    Devuelve None si no se puede interpretar.
    """
    if valor is None or valor == '':
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    texto = str(valor).strip()
    if not texto:
        return None
    # Quitar zona horaria al final ('Z', '+00:00', '-04:00') de timestamps ISO
    if 'T' in texto or (' ' in texto and ':' in texto):
        if texto.endswith('Z'):
            texto = texto[:-1]
        elif len(texto) > 6 and texto[-6] in '+-' and texto[-3] == ':':
            texto = texto[:-6]
    for fmt in _FORMATOS_ENTRADA:
        try:
            return datetime.strptime(texto, fmt).date()
        except ValueError:
            continue
    return None


def parse_fecha_hora(valor):
    """
    Igual que parse_fecha pero conserva la hora (devuelve datetime).
    Si el valor trae zona horaria (p. ej. '2026-10-11T19:30:00Z') se convierte
    a la hora local del proyecto (America/La_Paz) antes de formatear.
    """
    if isinstance(valor, datetime):
        dt = valor
    elif isinstance(valor, date):
        return datetime(valor.year, valor.month, valor.day)
    else:
        texto = str(valor).strip() if valor is not None else ''
        if not texto:
            return None
        dt = None
        try:
            dt = datetime.fromisoformat(texto)          # ISO, con o sin zona
        except ValueError:
            for fmt in _FORMATOS_ENTRADA:
                try:
                    dt = datetime.strptime(texto, fmt)
                    break
                except ValueError:
                    continue
        if dt is None:
            return None
    if dt.tzinfo is not None:
        try:
            from django.utils import timezone
            dt = timezone.localtime(dt)
        except Exception:
            dt = dt.replace(tzinfo=None)
    return dt


def fmt_fecha(valor, vacio=''):
    """date | datetime | str  →  'dd/mm/aaaa'.  Si no es interpretable devuelve `vacio`."""
    d = parse_fecha(valor)
    return d.strftime(FORMATO_FECHA) if d else vacio


def fmt_fecha_corta(valor, vacio=''):
    """→ 'dd/mm' (sin año)."""
    d = parse_fecha(valor)
    return d.strftime('%d/%m') if d else vacio


def fmt_fecha_hora(valor, vacio=''):
    """→ 'dd/mm/aaaa HH:MM'."""
    dt = parse_fecha_hora(valor)
    return dt.strftime(FORMATO_FECHA_HORA) if dt else vacio


def fmt_fecha_archivo(valor=None):
    """
    dd-mm-aaaa apto para NOMBRES DE ARCHIVO (la barra '/' no es válida en
    nombres de archivo). Sin argumento usa la fecha de hoy.
    """
    d = parse_fecha(valor) if valor is not None else date.today()
    return d.strftime('%d-%m-%Y') if d else ''


def fmt_periodo(desde, hasta, separador='  al  ', vacio='Periodo no especificado'):
    """
    Período 'dd/mm/aaaa al dd/mm/aaaa'.
    Si desde == hasta devuelve la fecha larga ('11 de octubre de 2026').
    Si falta alguna de las dos fechas devuelve `vacio`.
    """
    d1, d2 = parse_fecha(desde), parse_fecha(hasta)
    if not d1 or not d2:
        return vacio
    if d1 == d2:
        return fecha_larga(d1)
    return f"{fmt_fecha(d1)}{separador}{fmt_fecha(d2)}"


def fecha_larga(valor, vacio=''):
    """→ '11 de octubre de 2026' (siempre en español)."""
    d = parse_fecha(valor)
    return f"{d.day} de {MESES[d.month]} de {d.year}" if d else vacio


def fecha_larga_con_dia(valor, vacio=''):
    """→ 'domingo 11 de octubre de 2026'."""
    d = parse_fecha(valor)
    return f"{DIAS[d.weekday()]} {fecha_larga(d)}" if d else vacio


def mes_anio(valor, vacio=''):
    """→ 'octubre 2026' (siempre en español)."""
    d = parse_fecha(valor)
    return f"{MESES[d.month]} {d.year}" if d else vacio


def mes_abrev_anio(valor, vacio=''):
    """→ 'oct 2026' (siempre en español)."""
    d = parse_fecha(valor)
    return f"{MESES_ABREV[d.month]} {d.year}" if d else vacio


def nombre_dia(valor, vacio=''):
    """→ 'Domingo' (siempre en español, con mayúscula inicial)."""
    d = parse_fecha(valor)
    return DIAS[d.weekday()].capitalize() if d else vacio


def nombre_mes(valor, vacio=''):
    """→ 'Octubre' (siempre en español, con mayúscula inicial)."""
    d = parse_fecha(valor)
    return MESES[d.month].capitalize() if d else vacio


# ── Fechas ISO incrustadas dentro de un TEXTO ────────────────────────
# Algunos conceptos guardados en la base de datos (p. ej. "Uso de crédito - sesión
# 2026-10-08") contienen la fecha en formato aaaa-mm-dd. Esta función solo cambia
# cómo se MUESTRA el texto; no modifica el dato guardado.
_RE_ISO_EN_TEXTO = re.compile(r'(?<![\d-])(\d{4})-(\d{2})-(\d{2})(?![\d-])')


def fmt_texto_fechas(texto):
    """Convierte cada 'aaaa-mm-dd' VÁLIDA dentro de `texto` a 'dd/mm/aaaa'.
    Si `texto` no es str, lo devuelve sin cambios. Fechas imposibles (2026-13-45) se dejan igual."""
    if not isinstance(texto, str) or '-' not in texto:
        return texto

    def _cambiar(m):
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).strftime(FORMATO_FECHA)
        except ValueError:
            return m.group(0)

    return _RE_ISO_EN_TEXTO.sub(_cambiar, texto)
