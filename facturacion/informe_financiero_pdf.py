# facturacion/informe_financiero_pdf.py
# =====================================================================
# GENERADOR DE INFORME FINANCIERO PROFESIONAL — ReportLab canvas
# Adaptado a la vista activa: mensual, diaria, detalle_pagos,
# detalle_sesiones, detalle_proyectos, detalle_mensualidades,
# analisis_creditos
# =====================================================================

import os
import logging
from io import BytesIO
from decimal import Decimal
from datetime import date as _date_cls

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.pdfbase.pdfmetrics import stringWidth
from django.conf import settings

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────
# PALETA
# ─────────────────────────────────────────────────────────────────────
C_VERDE_OSC  = colors.HexColor('#1a3a1a')
C_VERDE_PRI  = colors.HexColor('#1e5c2e')
C_VERDE_MED  = colors.HexColor('#16a34a')
C_VERDE_FONDO= colors.HexColor('#f0fdf4')
C_VERDE_L    = colors.HexColor('#dcfce7')
C_AZUL       = colors.HexColor('#2563eb')
C_AZUL_L     = colors.HexColor('#dbeafe')
C_AMBER      = colors.HexColor('#d97706')
C_AMBER_L    = colors.HexColor('#fef3c7')
C_ROJO       = colors.HexColor('#dc2626')
C_ROJO_L     = colors.HexColor('#fee2e2')
C_MORADO     = colors.HexColor('#7c3aed')
C_MORADO_L   = colors.HexColor('#ede9fe')
C_TEAL       = colors.HexColor('#0d9488')
C_TEAL_L     = colors.HexColor('#ccfbf1')
C_GRIS_TABLA = colors.HexColor('#f8fafc')
C_GRIS_HDR   = colors.HexColor('#e2e8f0')
C_GRIS_BORDE = colors.HexColor('#cbd5e1')
C_TEXTO      = colors.HexColor('#0f172a')
C_TEXTO_SEC  = colors.HexColor('#334155')
C_MUTED      = colors.HexColor('#64748b')
C_BLANCO     = colors.white
C_FONDO_PAG  = colors.HexColor('#f8fafc')

# ─────────────────────────────────────────────────────────────────────
# CONSTANTES DE LAYOUT
# ─────────────────────────────────────────────────────────────────────
PAGE_W, PAGE_H = letter
ML = 1.8 * cm
MR = 1.8 * cm
MT = 1.5 * cm
MB = 1.5 * cm
CW = PAGE_W - ML - MR
HEADER_H  = 2.6 * cm
FOOTER_H  = 0.9 * cm
Y_TOP     = PAGE_H - MT - HEADER_H - 0.4 * cm
Y_BOTTOM  = MB + FOOTER_H + 0.3 * cm

NOMBRE_CENTRO = "Centro de Neurodesarrollo Infantil Misael"
DIRECCION     = "Calle Japon #28  -  Potosi, Bolivia"
TELEFONO      = "Tel.: 76175352"

MESES = ['', 'enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio',
         'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre']

MESES_FULL = ['', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
              'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']

VISTA_TITULOS = {
    'mensual':             'INFORME FINANCIERO MENSUAL',
    'diaria':              'INFORME DE CIERRE DIARIO',
    'detalle_pagos':       'DETALLE DE PAGOS RECIBIDOS',
    'detalle_sesiones':    'DETALLE DE SESIONES Y FACTURACION',
    'detalle_proyectos':   'DETALLE DE PROYECTOS Y FACTURACION',
    'detalle_mensualidades':'DETALLE DE MENSUALIDADES',
    'analisis_creditos':   'ANALISIS DE CREDITOS Y ADELANTOS',
}

# ─────────────────────────────────────────────────────────────────────
# HELPERS GENERALES
# ─────────────────────────────────────────────────────────────────────

def _logo():
    base = settings.BASE_DIR
    for ruta in [
        base / 'centro_terapias_v2' / 'staticfiles' / 'img' / 'logo_misael.png',
        base / 'staticfiles' / 'img' / 'logo_misael.png',
        base / 'static' / 'img' / 'logo_misael.png',
    ]:
        if os.path.exists(ruta):
            return str(ruta)
    return None


def _grad(c, x, y, w, h, c1, c2, steps=30):
    c.saveState()
    sw = w / steps
    for i in range(steps):
        t = i / steps
        r = c1.red   + (c2.red   - c1.red)   * t
        g = c1.green + (c2.green - c1.green) * t
        b = c1.blue  + (c2.blue  - c1.blue)  * t
        c.setFillColor(colors.Color(r, g, b))
        c.rect(x + i * sw, y, sw + 1, h, fill=1, stroke=0)
    c.restoreState()


def _bs(v):
    """Formatea un Decimal/float como 'Bs. 1.234'"""
    try:
        return f"Bs. {float(v):,.0f}"
    except Exception:
        return "Bs. 0"


def _pct(v):
    try:
        return f"{float(v):.1f}%"
    except Exception:
        return "0.0%"


def _attr(obj, key, default=''):
    """
    Lee un atributo de un objeto que puede ser:
    - dict / dict-like (QuerySet .values()) → obj[key]
    - Django model instance → getattr(obj, key)
    Nunca lanza excepción.
    """
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default) or default


def _nombre_paciente(p):
    """Retorna 'Nombre Apellido' para dict o instancia Paciente."""
    if p is None:
        return '—'
    if isinstance(p, dict):
        return f"{p.get('nombre', '')} {p.get('apellido', '')}".strip() or '—'
    nombre = getattr(p, 'nombre_completo', None)
    if nombre:
        return str(nombre)
    n = getattr(p, 'nombre', '') or ''
    a = getattr(p, 'apellido', '') or ''
    return f"{n} {a}".strip() or '—'


def _wrap(c, text, x, y, max_w, font, fsize, lh):
    """Dibuja texto con word-wrap. Retorna y final."""
    words = str(text).split()
    line = ""
    cy = y
    for word in words:
        test = (line + " " + word).strip()
        if stringWidth(test, font, fsize) <= max_w:
            line = test
        else:
            if line:
                c.drawString(x, cy, line)
                cy -= lh
            line = word
    if line:
        c.drawString(x, cy, line)
        cy -= lh
    return cy


def _new_page(c, pg, total_pg, titulo_vista, periodo_txt, sucursal_txt, fecha_emision):
    """Dibuja nueva página (fondo + encabezado). Retorna y inicial del contenido."""
    c.showPage()
    c.setFillColor(C_FONDO_PAG)
    c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    return _encabezado(c, pg, total_pg, titulo_vista, periodo_txt, sucursal_txt, fecha_emision)


# ─────────────────────────────────────────────────────────────────────
# ENCABEZADO Y PIE
# ─────────────────────────────────────────────────────────────────────

def _encabezado(c, pg, total_pg, titulo_vista, periodo_txt, sucursal_txt, fecha_emision):
    _grad(c, 0, PAGE_H - HEADER_H, PAGE_W, HEADER_H, C_VERDE_OSC, C_VERDE_PRI)

    lp = _logo()
    lh = HEADER_H - 0.5 * cm
    lx = ML
    ly = PAGE_H - HEADER_H + 0.25 * cm
    if lp:
        try:
            c.drawImage(lp, lx, ly, width=lh, height=lh,
                        preserveAspectRatio=True, mask='auto')
        except Exception:
            pass

    tx = lx + lh + 0.4 * cm
    c.setFillColor(C_BLANCO)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(tx, PAGE_H - 1.0 * cm, NOMBRE_CENTRO)
    c.setFont("Helvetica", 7)
    c.drawString(tx, PAGE_H - 1.55 * cm, f"{DIRECCION}  |  {TELEFONO}")

    c.setFont("Helvetica-Bold", 8.5)
    c.drawRightString(PAGE_W - MR, PAGE_H - 0.9 * cm, titulo_vista)
    c.setFont("Helvetica", 7)
    c.drawRightString(PAGE_W - MR, PAGE_H - 1.45 * cm, f"Pag. {pg} de {total_pg}")

    # Banda informativa bajo encabezado
    by = PAGE_H - HEADER_H - 0.8 * cm - 0.1 * cm
    c.setFillColor(C_VERDE_FONDO)
    c.roundRect(ML, by, CW, 0.78 * cm, 4, fill=1, stroke=0)
    c.setStrokeColor(C_VERDE_MED)
    c.setLineWidth(0.4)
    c.roundRect(ML, by, CW, 0.78 * cm, 4, fill=0, stroke=1)

    c.setFont("Helvetica-Bold", 7)
    c.setFillColor(C_VERDE_PRI)
    c.drawString(ML + 0.35 * cm, by + 0.48 * cm, "PERIODO:")
    c.setFont("Helvetica", 8)
    c.setFillColor(C_TEXTO)
    c.drawString(ML + 1.8 * cm, by + 0.48 * cm, periodo_txt)

    if sucursal_txt:
        c.setFont("Helvetica-Bold", 7)
        c.setFillColor(C_VERDE_PRI)
        c.drawString(ML + 9 * cm, by + 0.48 * cm, "SUCURSAL:")
        c.setFont("Helvetica", 8)
        c.setFillColor(C_TEXTO)
        c.drawString(ML + 10.7 * cm, by + 0.48 * cm, sucursal_txt)

    c.setFont("Helvetica", 7)
    c.setFillColor(C_MUTED)
    c.drawRightString(PAGE_W - MR, by + 0.48 * cm, f"Emitido: {fecha_emision}")

    return by - 0.4 * cm  # y inicial del contenido


def _pie(c, pg, total_pg, fecha_emision):
    py = MB + 0.15 * cm
    c.setStrokeColor(C_GRIS_BORDE)
    c.setLineWidth(0.4)
    c.line(ML, py + FOOTER_H - 0.15 * cm, PAGE_W - MR, py + FOOTER_H - 0.15 * cm)
    c.setFont("Helvetica", 6.5)
    c.setFillColor(C_MUTED)
    c.drawString(ML, py + 0.28 * cm,
                 f"{NOMBRE_CENTRO}  |  Informe generado el {fecha_emision}  |  CONFIDENCIAL — USO INTERNO")
    c.drawRightString(PAGE_W - MR, py + 0.28 * cm, f"Pagina {pg} / {total_pg}")


# ─────────────────────────────────────────────────────────────────────
# PRIMITIVOS DE DIBUJO
# ─────────────────────────────────────────────────────────────────────

def _titulo_seccion(c, y, texto, color=None):
    """Dibuja un separador de sección con título. Retorna nueva y."""
    col = color or C_VERDE_PRI
    c.setFillColor(col)
    c.roundRect(ML, y - 0.55 * cm, CW, 0.55 * cm, 4, fill=1, stroke=0)
    c.setFillColor(C_BLANCO)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(ML + 0.4 * cm, y - 0.38 * cm, texto.upper())
    return y - 0.55 * cm - 0.3 * cm


def _explicacion(c, y, texto, max_w=None):
    """Párrafo explicativo en gris italic. Retorna nueva y."""
    mw = max_w or (CW - 0.4 * cm)
    c.setFont("Helvetica-Oblique", 7.8)
    c.setFillColor(C_MUTED)
    ny = _wrap(c, texto, ML + 0.2 * cm, y, mw, "Helvetica-Oblique", 7.8, 0.38 * cm)
    return ny - 0.25 * cm


def _metrica_box(c, x, y, w, h, label, valor, sublabel='', color=C_VERDE_MED, fondo=None):
    """
    Dibuja una caja de métrica con layout vertical fijo:
      ├─ barra de color (top 0.18 cm)
      ├─ label pequeño (top - 0.45 cm)
      ├─ valor grande   (top - 1.05 cm)  ← siempre aquí, ajusta font si no cabe
      └─ sublabel gris  (bottom + 0.22 cm)
    La altura mínima recomendada es 1.5 cm para que no se superponga nada.
    """
    top = y          # coordenada superior de la caja
    bot = y - h      # coordenada inferior

    # Fondo blanco
    c.setFillColor(C_BLANCO)
    c.roundRect(x, bot, w, h, 5, fill=1, stroke=0)
    # Borde de color
    c.setStrokeColor(color)
    c.setLineWidth(0.6)
    c.roundRect(x, bot, w, h, 5, fill=0, stroke=1)

    # Barra superior de color (solo los primeros 0.18 cm)
    c.setFillColor(color)
    c.roundRect(x, top - 0.18 * cm, w, 0.18 * cm, 3, fill=1, stroke=0)
    # rect sin radio para tapar la mitad inferior del roundRect
    c.rect(x, top - 0.36 * cm, w, 0.20 * cm, fill=1, stroke=0)

    pad = 0.28 * cm

    # Label (6.5 pt, mayúsculas, color de la caja)
    c.setFont("Helvetica-Bold", 6.5)
    c.setFillColor(color)
    c.drawString(x + pad, top - 0.50 * cm, label.upper())

    # Valor (tamaño adaptativo según ancho disponible)
    avail_w = w - 2 * pad
    for fsize in (13, 11, 9, 8):
        sw = stringWidth(valor, "Helvetica-Bold", fsize)
        if sw <= avail_w:
            break
    c.setFont("Helvetica-Bold", fsize)
    c.setFillColor(C_TEXTO)
    c.drawString(x + pad, top - 1.05 * cm, valor)

    # Sublabel (6 pt, gris, en la parte inferior de la caja)
    if sublabel:
        c.setFont("Helvetica", 6)
        c.setFillColor(C_MUTED)
        # Truncar si no cabe en una línea
        sub = sublabel
        while stringWidth(sub, "Helvetica", 6) > avail_w and len(sub) > 4:
            sub = sub[:-2] + '…'
        c.drawString(x + pad, bot + 0.20 * cm, sub)


def _tabla(c, y, headers, rows, col_ws, stripe=True, font_size=7.5, row_h=0.52 * cm):
    """
    Dibuja una tabla simple. headers = lista de str, rows = lista de listas.
    col_ws = lista de anchos en cm (suma debe ser <= CW).
    Retorna nueva y.
    """
    total_w = sum(col_ws)
    # Encabezado
    c.setFillColor(C_GRIS_HDR)
    c.roundRect(ML, y - row_h, total_w, row_h, 3, fill=1, stroke=0)
    c.setStrokeColor(C_GRIS_BORDE)
    c.setLineWidth(0.3)
    c.roundRect(ML, y - row_h, total_w, row_h, 3, fill=0, stroke=1)

    x_cur = ML
    for i, hdr in enumerate(headers):
        c.setFont("Helvetica-Bold", 7)
        c.setFillColor(C_TEXTO_SEC)
        pad = 0.25 * cm
        c.drawString(x_cur + pad, y - row_h + 0.15 * cm, str(hdr).upper())
        x_cur += col_ws[i]

    y -= row_h

    # Filas
    for r_idx, row in enumerate(rows):
        if stripe and r_idx % 2 == 0:
            c.setFillColor(C_GRIS_TABLA)
            c.rect(ML, y - row_h, total_w, row_h, fill=1, stroke=0)
        c.setStrokeColor(C_GRIS_BORDE)
        c.setLineWidth(0.2)
        c.line(ML, y - row_h, ML + total_w, y - row_h)

        x_cur = ML
        for c_idx, cell in enumerate(row):
            c.setFont("Helvetica", font_size)
            c.setFillColor(C_TEXTO)
            pad = 0.25 * cm
            txt = str(cell) if cell is not None else ''
            # Truncar si no cabe
            max_w_cell = col_ws[c_idx] - 0.5 * cm
            while stringWidth(txt, "Helvetica", font_size) > max_w_cell and len(txt) > 1:
                txt = txt[:-2] + '.'
            c.drawString(x_cur + pad, y - row_h + 0.13 * cm, txt)
            x_cur += col_ws[c_idx]

        y -= row_h

    # Línea de cierre
    c.setStrokeColor(C_GRIS_BORDE)
    c.setLineWidth(0.4)
    c.line(ML, y, ML + total_w, y)
    return y - 0.2 * cm


def _fila_kv(c, y, label, valor, color_val=None):
    """Fila de clave–valor simple. Retorna nueva y."""
    c.setFont("Helvetica-Bold", 8)
    c.setFillColor(C_TEXTO_SEC)
    c.drawString(ML, y, label)
    c.setFont("Helvetica", 8.5)
    c.setFillColor(color_val or C_TEXTO)
    c.drawRightString(ML + CW, y, valor)
    c.setStrokeColor(C_GRIS_BORDE)
    c.setLineWidth(0.2)
    c.line(ML, y - 0.1 * cm, ML + CW, y - 0.1 * cm)
    return y - 0.45 * cm


def _linea_divisora(c, y, grosor=0.4):
    c.setStrokeColor(C_GRIS_BORDE)
    c.setLineWidth(grosor)
    c.line(ML, y, ML + CW, y)
    return y - 0.25 * cm


def _alerta_box(c, y, texto, color=C_AMBER, fondo=None):
    h = 0.8 * cm
    bg = fondo or colors.Color(color.red, color.green, color.blue, alpha=0.08)
    c.setFillColor(bg)
    c.roundRect(ML, y - h, CW, h, 5, fill=1, stroke=0)
    c.setStrokeColor(color)
    c.setLineWidth(0.5)
    c.roundRect(ML, y - h, CW, h, 5, fill=0, stroke=1)
    c.setFont("Helvetica-Bold", 8)
    c.setFillColor(color)
    c.drawString(ML + 0.4 * cm, y - 0.55 * cm, texto)
    return y - h - 0.3 * cm


# ─────────────────────────────────────────────────────────────────────
# SECCIONES REUTILIZABLES
# ─────────────────────────────────────────────────────────────────────

def _grilla_metricas(c, y, items, cols=4, box_h=1.7 * cm):
    """
    Dibuja una grilla de cajas de métricas.
    items = lista de (label, valor, sublabel, color)
    Retorna nueva y.
    """
    box_w = (CW - (cols - 1) * 0.2 * cm) / cols
    row_items = []
    for item in items:
        row_items.append(item)
        if len(row_items) == cols:
            for i, (lbl, val, sub, col) in enumerate(row_items):
                bx = ML + i * (box_w + 0.2 * cm)
                _metrica_box(c, bx, y, box_w, box_h, lbl, val, sub, col)
            y -= box_h + 0.3 * cm
            row_items = []
    if row_items:
        box_w2 = (CW - (len(row_items) - 1) * 0.2 * cm) / max(len(row_items), 1)
        for i, (lbl, val, sub, col) in enumerate(row_items):
            bx = ML + i * (box_w2 + 0.2 * cm)
            _metrica_box(c, bx, y, box_w2, box_h, lbl, val, sub, col)
        y -= box_h + 0.3 * cm
    return y


# ─────────────────────────────────────────────────────────────────────
# PORTADA
# ─────────────────────────────────────────────────────────────────────

def _portada(c, titulo_vista, periodo_txt, sucursal_txt, fecha_emision, vista, ctx):
    # Fondo
    c.setFillColor(C_FONDO_PAG)
    c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)

    # Franja superior
    _grad(c, 0, PAGE_H - 5.5 * cm, PAGE_W, 5.5 * cm, C_VERDE_OSC, C_VERDE_PRI)

    # Logo
    lp = _logo()
    if lp:
        try:
            c.drawImage(lp, ML, PAGE_H - 4.5 * cm, width=3 * cm, height=3 * cm,
                        preserveAspectRatio=True, mask='auto')
        except Exception:
            pass

    # Nombre del centro (portada)
    c.setFillColor(C_BLANCO)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(ML + 3.5 * cm, PAGE_H - 2.2 * cm, NOMBRE_CENTRO)
    c.setFont("Helvetica", 9)
    c.drawString(ML + 3.5 * cm, PAGE_H - 2.85 * cm, f"{DIRECCION}  |  {TELEFONO}")

    # Línea decorativa
    c.setStrokeColor(colors.HexColor('#86efac'))
    c.setLineWidth(1.5)
    c.line(ML, PAGE_H - 5.5 * cm + 0.3 * cm, PAGE_W - MR, PAGE_H - 5.5 * cm + 0.3 * cm)

    # Título del informe
    ty = PAGE_H - 8.0 * cm
    c.setFont("Helvetica-Bold", 22)
    c.setFillColor(C_TEXTO)
    titulo_line1 = titulo_vista
    c.drawCentredString(PAGE_W / 2, ty, titulo_line1)

    # Línea verde bajo el título
    c.setStrokeColor(C_VERDE_MED)
    c.setLineWidth(2)
    tw = stringWidth(titulo_line1, "Helvetica-Bold", 22)
    c.line(PAGE_W / 2 - tw / 2, ty - 0.3 * cm, PAGE_W / 2 + tw / 2, ty - 0.3 * cm)

    # Período y sucursal
    c.setFont("Helvetica", 11)
    c.setFillColor(C_TEXTO_SEC)
    c.drawCentredString(PAGE_W / 2, ty - 1.0 * cm, f"Periodo: {periodo_txt}")
    if sucursal_txt:
        c.drawCentredString(PAGE_W / 2, ty - 1.6 * cm, f"Sucursal: {sucursal_txt}")

    c.setFont("Helvetica", 9)
    c.setFillColor(C_MUTED)
    c.drawCentredString(PAGE_W / 2, ty - 2.4 * cm, f"Documento generado el {fecha_emision}")

    # Caja de resumen ejecutivo (kpi principales)
    cy = ty - 3.5 * cm
    c.setStrokeColor(C_GRIS_BORDE)
    c.setLineWidth(0.5)
    c.roundRect(ML, cy - 4.5 * cm, CW, 4.5 * cm, 8, fill=0, stroke=1)
    c.setFillColor(C_GRIS_TABLA)
    c.roundRect(ML, cy - 4.5 * cm, CW, 4.5 * cm, 8, fill=1, stroke=0)
    c.roundRect(ML, cy - 4.5 * cm, CW, 4.5 * cm, 8, fill=0, stroke=1)

    c.setFont("Helvetica-Bold", 9)
    c.setFillColor(C_VERDE_PRI)
    c.drawString(ML + 0.5 * cm, cy - 0.45 * cm, "INDICADORES CLAVE DEL PERIODO")

    # Obtener métricas de portada según vista
    kpis = _kpis_portada(vista, ctx)
    box_w = (CW - 1.0 * cm) / min(len(kpis), 4)
    box_h_portada = 2.5 * cm

    # Primera fila de KPIs (máx 4)
    for i, (lbl, val, sub, col) in enumerate(kpis[:4]):
        bx = ML + 0.5 * cm + i * (box_w + 0.0 * cm)
        # _metrica_box usa coordenadas top-down (y es el tope de la caja)
        _metrica_box(c, bx, cy - 0.5 * cm, box_w - 0.15 * cm, box_h_portada,
                     lbl, val, sub, col)

    if len(kpis) > 4:
        for i, (lbl, val, sub, col) in enumerate(kpis[4:8]):
            bx = ML + 0.5 * cm + i * (box_w + 0.0 * cm)
            _metrica_box(c, bx, cy - 0.5 * cm - box_h_portada - 0.3 * cm,
                         box_w - 0.15 * cm, box_h_portada, lbl, val, sub, col)

    # Pie de portada
    _pie(c, 1, 999, fecha_emision)  # total_pg se actualiza al final


def _kpis_portada(vista, ctx):
    """Devuelve lista de (label, valor, sublabel, color) para la portada."""
    ingresos = ctx.get('ingresos') or {}
    cierre   = ctx.get('cierre_diario') or {}

    if vista in ('mensual', None, ''):
        return [
            ("Ingresos generados",
             _bs(ingresos.get('total_generado_real', 0)),
             "Sesiones + proyectos + mensualidades", C_VERDE_MED),
            ("Total cobrado neto",
             _bs(ingresos.get('total_cobrado_neto', 0)),
             "Pagos recibidos menos devoluciones", C_AZUL),
            ("Por cobrar",
             _bs(ingresos.get('total_pendiente', 0)),
             f"Tasa de cobranza: {_pct(ingresos.get('tasa_cobranza', 0))}", C_AMBER),
            ("Devoluciones",
             _bs(ingresos.get('total_devoluciones', 0)),
             f"{ingresos.get('devoluciones_info', {}).get('cantidad', 0)} devoluciones", C_ROJO),
        ]
    elif vista == 'diaria':
        return [
            ("Total cobrado hoy",
             _bs(cierre.get('monto_total_bruto', 0)),
             f"{cierre.get('pagos_total', 0)} recibos emitidos", C_VERDE_MED),
            ("En caja (efectivo)",
             _bs(cierre.get('efectivo_esperado', 0)),
             "Efectivo esperado fisicamente", C_AZUL),
            ("Sesiones realizadas",
             str(cierre.get('sesiones_realizadas', 0)),
             _bs(cierre.get('monto_generado_sesiones', 0)) + " generado", C_TEAL),
            ("Pacientes atendidos",
             str((cierre.get('estadisticas') or {}).get('pacientes_unicos', 0)),
             "Pacientes unicos del dia", C_MORADO),
        ]
    elif vista == 'detalle_pagos':
        dp = ctx.get('detalle_pagos')
        count = dp.count() if dp else 0
        total = ctx.get('total_detalle_pagos', 0)
        return [
            ("Total pagos", str(count), "Registros en el periodo", C_VERDE_MED),
            ("Monto total", _bs(total), "Suma de pagos validos", C_AZUL),
            ("Devoluciones", _bs(ctx.get('total_devoluciones', 0)), "A restar del total", C_ROJO),
            ("Neto del periodo", _bs(ctx.get('total_neto_periodo', 0) or (float(total or 0) - float(ctx.get('total_devoluciones', 0) or 0))), "Cobrado efectivo", C_TEAL),
        ]
    elif vista == 'detalle_sesiones':
        ds = ctx.get('detalle_sesiones')
        count = ds.count() if ds else 0
        tot = ctx.get('detalle_sesiones_totales') or {}
        return [
            ("Sesiones", str(count), "En el periodo seleccionado", C_VERDE_MED),
            ("Generado", _bs(tot.get('generado', 0)), "Costo total de sesiones", C_AZUL),
            ("Cobrado", _bs(tot.get('cobrado', 0)), "Total pagado", C_TEAL),
            ("Pendiente", _bs(tot.get('pendiente', 0)), "Por cobrar", C_AMBER),
        ]
    elif vista == 'detalle_proyectos':
        dp2 = ctx.get('detalle_proyectos')
        count = dp2.count() if dp2 else 0
        tot2 = ctx.get('detalle_proyectos_totales') or {}
        return [
            ("Proyectos", str(count), "En el periodo seleccionado", C_VERDE_MED),
            ("Costo total", _bs(tot2.get('costo_total', 0)), "Proyectos activos y finalizados", C_AZUL),
            ("Cobrado neto", _bs(tot2.get('cobrado', 0)), "Total pagado", C_TEAL),
            ("Pendiente", _bs(tot2.get('pendiente', 0)), "Por cobrar", C_AMBER),
        ]
    elif vista == 'detalle_mensualidades':
        dm = ctx.get('detalle_mensualidades')
        count = dm.count() if dm else 0
        tot3 = ctx.get('detalle_mensualidades_totales') or {}
        return [
            ("Mensualidades", str(count), "En el periodo seleccionado", C_VERDE_MED),
            ("Costo mensual", _bs(tot3.get('costo_total', 0)), "Suma de cuotas", C_AZUL),
            ("Cobrado", _bs(tot3.get('cobrado', 0)), "Total pagado", C_TEAL),
            ("Pendiente", _bs(tot3.get('pendiente', 0)), "Por cobrar", C_AMBER),
        ]
    elif vista == 'analisis_creditos':
        ac = ctx.get('analisis_creditos') or {}
        return [
            ("Creditos generados", _bs(ac.get('total_generado', 0)), "Adelantos recibidos", C_MORADO),
            ("Creditos usados", _bs(ac.get('total_utilizado', 0)), "Aplicados a servicios", C_AZUL),
            ("Saldo disponible", _bs(ac.get('saldo_disponible', 0) or ac.get('saldo_neto', 0)), "Credito aun sin usar", C_VERDE_MED),
            ("Pacientes con credito", str(len(ac.get('pacientes_con_credito', []))), "Con saldo a favor", C_TEAL),
        ]
    return []


# ─────────────────────────────────────────────────────────────────────
# SECCIONES POR VISTA
# ─────────────────────────────────────────────────────────────────────

def _seccion_mensual(pages_data, ctx, helpers):
    """Genera todas las páginas de contenido para vista mensual."""
    make_page = helpers['new_page']
    ingresos  = ctx.get('ingresos') or {}
    por_metodo = ctx.get('por_metodo') or []
    por_servicio = ctx.get('por_servicio') or []
    top_pacientes = ctx.get('top_pacientes') or []

    # ── Página 2: Análisis de Ingresos ─────────────────────────────
    c, y, pg = make_page()

    y = _titulo_seccion(c, y, "1. Analisis de Ingresos del Periodo")
    y = _explicacion(c, y,
        "Esta seccion muestra cuanto genero el centro en el periodo seleccionado. "
        "El ingreso 'generado' es lo que los pacientes deben pagar por los servicios ya "
        "prestados o comprometidos. El ingreso 'cobrado' es el dinero que fisicamente "
        "ingreso a caja o fue transferido. La diferencia es lo que aun esta pendiente de cobro.")

    items = [
        ("Ingresos reales", _bs(ingresos.get('total_generado_real', 0)),
         "Servicios ya realizados o activos", C_VERDE_MED),
        ("Ingresos proyectados", _bs(ingresos.get('total_generado_proyectado', 0)),
         "Incluye sesiones programadas y proyectos planif.", colors.HexColor('#059669')),
        ("Cobrado bruto", _bs(ingresos.get('total_cobrado_bruto', 0)),
         "Pagos recibidos antes de devoluciones", C_AZUL),
        ("Cobrado neto", _bs(ingresos.get('total_cobrado_neto', 0)),
         "Despues de restar devoluciones", C_TEAL),
        ("Por cobrar real", _bs(ingresos.get('total_pendiente', 0)),
         f"Tasa de cobranza: {_pct(ingresos.get('tasa_cobranza', 0))}", C_AMBER),
        ("Por cobrar proyectado", _bs(ingresos.get('total_pendiente_proyectado', 0)),
         "Incluyendo compromisos futuros", colors.HexColor('#b45309')),
        ("Devoluciones", _bs(ingresos.get('total_devoluciones', 0)),
         f"{ingresos.get('devoluciones_info',{}).get('cantidad',0)} devoluciones realizadas", C_ROJO),
        ("Ticket promedio", _bs(ingresos.get('promedio_por_item', 0)),
         "Por servicio (sesion, proyecto o mensualidad)", C_MORADO),
    ]
    y = _grilla_metricas(c, y, items, cols=4, box_h=1.7 * cm)

    y = _linea_divisora(c, y)

    # Desglose por categoría
    y = _titulo_seccion(c, y, "2. Desglose por Categoria de Servicio")
    y = _explicacion(c, y,
        "Los servicios del centro se agrupan en tres categorias: sesiones individuales "
        "(consultas de una vez), proyectos (programas con varias sesiones acordadas de antemano) "
        "y mensualidades (planes de atencion continua con pago mensual). "
        "Cada categoria muestra cuanto genero, cuanto se cobro y cuanto queda pendiente.")

    ses   = ingresos.get('sesiones')   or {}
    proy  = ingresos.get('proyectos')  or {}
    mens  = ingresos.get('mensualidades') or {}

    headers = ["Categoria", "Cantidad", "Generado", "Cobrado", "Pendiente"]
    col_ws  = [4.5*cm, 2.5*cm, 3.5*cm, 3.5*cm, 3.5*cm]
    rows = [
        ["Sesiones individuales",
         str(ses.get('cantidad_sesiones', 0)),
         _bs(ses.get('total_generado_real', 0)),
         _bs(ses.get('total_cobrado', 0)),
         _bs(ses.get('total_pendiente', 0))],
        ["Proyectos terapeuticos",
         str(proy.get('cantidad_proyectos', 0)),
         _bs(proy.get('total_generado_real', 0)),
         _bs(proy.get('total_cobrado', 0)),
         _bs(proy.get('total_pendiente', 0))],
        ["Mensualidades",
         str(mens.get('cantidad_mensualidades', 0)),
         _bs(mens.get('total_generado_real', 0)),
         _bs(mens.get('total_cobrado', 0)),
         _bs(mens.get('total_pendiente', 0))],
    ]
    y = _tabla(c, y, headers, rows, col_ws)

    # Créditos
    creditos = ingresos.get('creditos') or {}
    if creditos:
        y -= 0.3 * cm
        y = _titulo_seccion(c, y, "3. Movimiento de Creditos (Pagos Adelantados)", color=C_MORADO)
        y = _explicacion(c, y,
            "Los creditos son pagos que los pacientes realizaron de forma adelantada, "
            "sin asignarlos todavia a una sesion o servicio especifico. "
            "Este dinero queda disponible como 'saldo a favor' y se descuenta automaticamente "
            "cuando se aplica a un servicio futuro. Son un ingreso recibido pero aun no 'devengado'.")
        items_c = [
            ("Creditos generados", _bs(creditos.get('generados', 0)),
             f"{creditos.get('generados_cantidad', 0)} adelantos recibidos", C_MORADO),
            ("Creditos utilizados", _bs(creditos.get('utilizados', 0)),
             f"{creditos.get('utilizados_cantidad', 0)} usos registrados", C_AZUL),
            ("Saldo neto disponible", _bs(creditos.get('saldo_neto', 0)),
             "Lo que los pacientes tienen a su favor", C_VERDE_MED),
        ]
        y = _grilla_metricas(c, y, items_c, cols=3, box_h=1.7 * cm)

    _pie(c, pg, 999, helpers['fecha'])
    pages_data.append((c, pg))

    # ── Página 3: Métodos de pago + Devoluciones ────────────────────
    c, y, pg = make_page()

    y = _titulo_seccion(c, y, "4. Desglose por Metodo de Pago")
    y = _explicacion(c, y,
        "Indica como pagaron los pacientes: en efectivo, mediante QR, transferencia bancaria u "
        "otros medios. Esta informacion es esencial para el control de caja y la conciliacion "
        "bancaria al final del periodo.")

    if por_metodo:
        total_mp = sum(float(m.get('monto', 0) or 0) for m in por_metodo)
        headers_mp = ["Metodo de Pago", "Cantidad transac.", "Monto Total", "% del Total"]
        col_ws_mp  = [6.5*cm, 3.5*cm, 4.0*cm, 3.5*cm]
        rows_mp = []
        for m in por_metodo:
            monto = float(m.get('monto', 0) or 0)
            pct = (monto / total_mp * 100) if total_mp > 0 else 0
            rows_mp.append([
                str(m.get('metodo_pago__nombre', '—')),
                str(m.get('cantidad', 0)),
                _bs(monto),
                f"{pct:.1f}%",
            ])
        y = _tabla(c, y, headers_mp, rows_mp, col_ws_mp)
    else:
        y = _alerta_box(c, y, "No hay datos de metodos de pago para el periodo seleccionado.", C_MUTED)

    # Devoluciones
    dev_info = ingresos.get('devoluciones_info') or {}
    anul_info = ingresos.get('anulaciones_info') or {}
    if float(ingresos.get('total_devoluciones', 0) or 0) > 0 or float(ingresos.get('total_anulaciones', 0) or 0) > 0:
        y -= 0.3 * cm
        y = _titulo_seccion(c, y, "5. Devoluciones y Anulaciones", color=C_ROJO)
        y = _explicacion(c, y,
            "Las devoluciones son montos que se reintegraron a los pacientes por servicios "
            "cancelados, pagos en exceso u otras razones. Las anulaciones son pagos registrados "
            "por error que fueron dados de baja sin efecto economico. Ambos reducen el ingreso neto real.")
        items_d = [
            ("Total devuelto", _bs(ingresos.get('total_devoluciones', 0)),
             f"{dev_info.get('cantidad', 0)} devoluciones en el periodo", C_ROJO),
            ("Total anulado", _bs(ingresos.get('total_anulaciones', 0)),
             f"{anul_info.get('cantidad', 0)} pagos anulados (sin efecto)", C_AMBER),
        ]
        y = _grilla_metricas(c, y, items_d, cols=2, box_h=1.7 * cm)

        por_met_dev = dev_info.get('por_metodo')
        if por_met_dev:
            headers_dev = ["Metodo de Devolucion", "Cantidad", "Monto"]
            col_ws_dev  = [8*cm, 3.5*cm, 6*cm]
            rows_dev = [
                [str(m.get('metodo_devolucion__nombre', '—')),
                 str(m.get('cantidad', 0)),
                 _bs(m.get('monto', 0))]
                for m in por_met_dev
            ]
            y = _tabla(c, y, headers_dev, rows_dev, col_ws_dev)

    _pie(c, pg, 999, helpers['fecha'])
    pages_data.append((c, pg))

    # ── Página 4: Servicios y Pacientes ─────────────────────────────
    c, y, pg = make_page()

    if por_servicio:
        y = _titulo_seccion(c, y, "6. Servicios Mas Rentables del Periodo")
        y = _explicacion(c, y,
            "Muestra cuales tipos de terapia o servicio aportaron mas ingresos al centro. "
            "Permite identificar los servicios de mayor demanda y planificar la oferta "
            "terapeutica de forma estrategica.")
        headers_s = ["Servicio", "Sesiones", "Proyectos", "Ingresos"]
        col_ws_s  = [8*cm, 2.5*cm, 2.5*cm, 4.5*cm]
        rows_s = [
            [str(_attr(s, 'nombre', '—')),
             str(_attr(s, 'sesiones', 0)),
             str(_attr(s, 'proyectos', 0)),
             _bs(_attr(s, 'ingresos', 0))]
            for s in list(por_servicio)[:15]
        ]
        y = _tabla(c, y, headers_s, rows_s, col_ws_s)

    if top_pacientes:
        y -= 0.3 * cm
        y = _titulo_seccion(c, y, "7. Pacientes con Mayor Consumo de Servicios")
        y = _explicacion(c, y,
            "Lista de los pacientes que mas sesiones y servicios recibieron en el periodo. "
            "Informacion util para entender la distribucion de la demanda y la continuidad "
            "del tratamiento.")
        headers_p = ["Paciente", "Sesiones"]
        col_ws_p  = [13*cm, 4.5*cm]
        rows_p = [
            [_nombre_paciente(p),
             str(_attr(p, 'sesiones_count', 0))]
            for p in list(top_pacientes)[:10]
        ]
        y = _tabla(c, y, headers_p, rows_p, col_ws_p)

    _pie(c, pg, 999, helpers['fecha'])
    pages_data.append((c, pg))


def _seccion_diaria(pages_data, ctx, helpers):
    """Genera páginas de contenido para vista diaria."""
    make_page = helpers['new_page']
    cierre = ctx.get('cierre_diario') or {}
    stats  = cierre.get('estadisticas') or {}

    # ── Página 2: Cierre del día ────────────────────────────────────
    c, y, pg = make_page()

    y = _titulo_seccion(c, y, "1. Resumen del Cierre de Caja del Dia")
    y = _explicacion(c, y,
        f"Este documento resume todas las transacciones economicas del dia "
        f"{cierre.get('fecha_formato', '')}. "
        "Incluye el total cobrado, el desglose por forma de pago y los movimientos "
        "operativos del centro. El dato de 'en caja debe estar' indica el monto de "
        "efectivo fisico que deberia encontrarse en la caja al momento del cierre.")

    items = [
        ("Total cobrado", _bs(cierre.get('monto_total_bruto', 0)),
         f"{cierre.get('pagos_total', 0)} recibos emitidos hoy", C_VERDE_MED),
        ("Cobrado neto", _bs(cierre.get('monto_total_neto', 0)),
         "Despues de devoluciones del dia", C_TEAL),
        ("Efectivo en caja", _bs(cierre.get('efectivo_esperado', 0)),
         "Monto fisico que debe estar en caja", C_AZUL),
    ]
    if float(cierre.get('total_devoluciones', 0) or 0) > 0:
        items.append(("Devoluciones del dia",
                      _bs(cierre.get('total_devoluciones', 0)),
                      "Reintegros realizados hoy", C_ROJO))
    y = _grilla_metricas(c, y, items, cols=len(items), box_h=1.7 * cm)

    # Desglose por método
    y = _titulo_seccion(c, y, "2. Ingresos por Forma de Pago")
    y = _explicacion(c, y,
        "De todo el dinero cobrado hoy, esta tabla indica que parte llego en efectivo "
        "(que va fisicamente a caja), que parte fue mediante codigo QR y que parte fue "
        "transferencia bancaria o deposito. El efectivo es el unico que requiere control fisico.")

    metodos = list(cierre.get('por_metodo') or [])
    if metodos:
        headers_m = ["Metodo de Pago", "Transacciones", "Monto"]
        col_ws_m  = [9*cm, 4*cm, 4.5*cm]
        rows_m = [
            [str(m.get('metodo_pago__nombre', '—')),
             str(m.get('cantidad', 0)),
             _bs(m.get('monto', 0))]
            for m in metodos
        ]
        y = _tabla(c, y, headers_m, rows_m, col_ws_m)

    # Operaciones del día
    y -= 0.2 * cm
    y = _titulo_seccion(c, y, "3. Actividad Operativa del Dia")
    y = _explicacion(c, y,
        "Resumen de la actividad terapeutica: cuantos pacientes fueron atendidos, "
        "cuantas sesiones se realizaron y cuanto tiempo trabajo el equipo profesional.")

    items_op = [
        ("Sesiones realizadas", str(cierre.get('sesiones_realizadas', 0)),
         _bs(cierre.get('monto_generado_sesiones', 0)) + " generado", C_TEAL),
        ("Pacientes atendidos", str(stats.get('pacientes_unicos', 0)),
         "Pacientes unicos del dia", C_VERDE_MED),
        ("Horas trabajadas", f"{float(stats.get('horas_trabajadas', 0) or 0):.1f} h",
         "Total de duracion de sesiones", C_AZUL),
        ("Ticket promedio", _bs(stats.get('ticket_promedio', 0)),
         "Ingreso promedio por recibo", C_MORADO),
    ]
    y = _grilla_metricas(c, y, items_op, cols=4, box_h=1.7 * cm)

    # Asistencia
    y = _titulo_seccion(c, y, "4. Control de Asistencia")
    y = _explicacion(c, y,
        "Muestra el estado de todas las sesiones agendadas para hoy: cuantas se realizaron, "
        "cuantos pacientes llegaron con retraso, cuantos faltaron sin aviso y cuantas "
        "fueron canceladas. Las faltas sin aviso generan un costo al centro.")
    items_as = [
        ("Programadas", str(stats.get('programadas_dia', 0)), "Agendadas para hoy", C_AZUL),
        ("Realizadas + retrasos",
         str(int(cierre.get('sesiones_realizadas', 0))),
         "Sesiones completadas", C_VERDE_MED),
        ("Faltas", str(stats.get('faltas_dia', 0)), "Sin aviso previo", C_ROJO),
        ("Canceladas", str(stats.get('canceladas_dia', 0)), "Con aviso previo", C_MUTED),
    ]
    y = _grilla_metricas(c, y, items_as, cols=4, box_h=1.7 * cm)

    _pie(c, pg, 999, helpers['fecha'])
    pages_data.append((c, pg))

    # ── Página 3: Comparativa 7 días ────────────────────────────────
    comparativa = cierre.get('comparativa_dias') or []
    if comparativa:
        c, y, pg = make_page()
        y = _titulo_seccion(c, y, "5. Comparativa de los Ultimos 7 Dias")
        y = _explicacion(c, y,
            "Esta tabla permite ver la evolucion diaria de los ingresos en la ultima semana. "
            "Comparar el dia de hoy con dias anteriores ayuda a identificar tendencias, "
            "dias de mayor actividad y variaciones inusuales en la recaudacion.")

        headers_7 = ["Dia", "Fecha", "Generado", "Efect.(Caja)", "QR", "Transf.", "Total Cobrado"]
        col_ws_7  = [1.8*cm, 2.5*cm, 2.8*cm, 2.8*cm, 2.2*cm, 2.5*cm, 2.9*cm]
        rows_7 = [
            [str(d.get('dia_semana', '')),
             str(d.get('fecha', '')).split(' ')[0] if d.get('fecha') else '',
             _bs(d.get('ingresos', 0)),
             _bs(d.get('efectivo', 0)),
             _bs(d.get('qr', 0)),
             _bs(d.get('transferencia', 0)),
             _bs(d.get('cobrado_neto', 0))]
            for d in comparativa
        ]
        # Totales
        tot_ef = sum(float(d.get('efectivo', 0) or 0) for d in comparativa)
        tot_qr = sum(float(d.get('qr', 0) or 0) for d in comparativa)
        tot_tr = sum(float(d.get('transferencia', 0) or 0) for d in comparativa)
        tot_cn = sum(float(d.get('cobrado_neto', 0) or 0) for d in comparativa)
        rows_7.append(["TOTAL 7 DIAS", "", "", _bs(tot_ef), _bs(tot_qr), _bs(tot_tr), _bs(tot_cn)])
        y = _tabla(c, y, headers_7, rows_7, col_ws_7, font_size=7.5)

        _pie(c, pg, 999, helpers['fecha'])
        pages_data.append((c, pg))


def _seccion_tabla_pagos(pages_data, ctx, helpers):
    make_page = helpers['new_page']
    detalle = ctx.get('detalle_pagos')
    metodos = ctx.get('detalle_pagos_metodos') or []

    c, y, pg = make_page()
    y = _titulo_seccion(c, y, "1. Resumen de Pagos del Periodo")
    y = _explicacion(c, y,
        "Esta seccion lista todos los pagos registrados en el periodo seleccionado. "
        "Cada registro corresponde a un recibo emitido al paciente por el pago de una sesion, "
        "proyecto, mensualidad o adelanto de credito. Los pagos anulados no se incluyen.")

    total = ctx.get('total_detalle_pagos', 0)
    count = detalle.count() if detalle else 0
    items = [
        ("Total recibos", str(count), "Pagos validos registrados", C_VERDE_MED),
        ("Monto total cobrado", _bs(total), "Suma de todos los recibos", C_AZUL),
        ("Devoluciones", _bs(ctx.get('total_devoluciones', 0)), "A descontar del total", C_ROJO),
    ]
    y = _grilla_metricas(c, y, items, cols=3, box_h=1.7 * cm)

    if metodos:
        y = _titulo_seccion(c, y, "Distribucion por Metodo de Pago")
        headers_m = ["Metodo", "Transacciones", "Total"]
        col_ws_m  = [8*cm, 4*cm, 5.5*cm]
        rows_m = [[str(m.get('metodo_pago__nombre', '—')), str(m.get('cantidad', 0)), _bs(m.get('total', 0))]
                  for m in metodos]
        y = _tabla(c, y, headers_m, rows_m, col_ws_m)

    if not detalle:
        _pie(c, pg, 999, helpers['fecha'])
        pages_data.append((c, pg))
        return

    # Tabla de pagos paginada
    y -= 0.3 * cm
    y = _titulo_seccion(c, y, "2. Listado Completo de Pagos")
    headers_p = ["Recibo", "Fecha", "Paciente", "Concepto", "Metodo", "Monto"]
    col_ws_p  = [2.5*cm, 2.2*cm, 4.5*cm, 4.0*cm, 2.8*cm, 2.5*cm]
    row_h_p   = 0.5 * cm

    for pago in detalle:
        if pago.sesion:
            concepto = f"Sesion: {pago.sesion.servicio.nombre if pago.sesion.servicio else '—'}"
        elif pago.proyecto:
            concepto = f"Proyecto: {pago.proyecto.servicio_base.nombre if pago.proyecto.servicio_base else '—'}"
        elif pago.mensualidad:
            concepto = "Mensualidad"
        else:
            concepto = "Adelanto/Credito"

        row = [
            str(pago.numero_recibo),
            str(pago.fecha_pago.strftime('%d/%m/%Y') if pago.fecha_pago else ''),
            (f"{pago.paciente.nombre} {pago.paciente.apellido}"[:28] if pago.paciente else '—'),
            concepto[:28],
            str(pago.metodo_pago.nombre if pago.metodo_pago else '—')[:14],
            _bs(pago.monto),
        ]

        needed = row_h_p + 0.1 * cm
        if y - needed < Y_BOTTOM:
            _pie(c, pg, 999, helpers['fecha'])
            pages_data.append((c, pg))
            c, y, pg = make_page()
            y = _titulo_seccion(c, y, "2. Listado Completo de Pagos (cont.)")

        # Fila individual
        r_idx = len([r for r in pages_data]) % 2
        if r_idx == 0:
            c.setFillColor(C_GRIS_TABLA)
            c.rect(ML, y - row_h_p, sum(col_ws_p), row_h_p, fill=1, stroke=0)
        c.setStrokeColor(C_GRIS_BORDE)
        c.setLineWidth(0.2)
        c.line(ML, y - row_h_p, ML + sum(col_ws_p), y - row_h_p)
        x_cur = ML
        for c_idx, cell in enumerate(row):
            c.setFont("Helvetica", 7.5)
            c.setFillColor(C_TEXTO)
            c.drawString(x_cur + 0.2 * cm, y - row_h_p + 0.12 * cm, str(cell))
            x_cur += col_ws_p[c_idx]
        y -= row_h_p

    _pie(c, pg, 999, helpers['fecha'])
    pages_data.append((c, pg))


def _seccion_tabla_sesiones(pages_data, ctx, helpers):
    make_page = helpers['new_page']
    detalle = ctx.get('detalle_sesiones')
    totales = ctx.get('detalle_sesiones_totales') or {}

    c, y, pg = make_page()
    y = _titulo_seccion(c, y, "1. Resumen de Sesiones del Periodo")
    y = _explicacion(c, y,
        "Las sesiones individuales son atenciones de un solo encuentro entre el profesional "
        "y el paciente. Cada fila muestra el costo de la sesion, cuanto se pago y cuanto queda "
        "pendiente de cobro. El estado indica si la sesion fue realizada, si el paciente falto o "
        "si fue cancelada.")

    items = [
        ("Total sesiones", str(detalle.count() if detalle else 0),
         "En el periodo seleccionado", C_VERDE_MED),
        ("Generado", _bs(totales.get('generado', 0)), "Costo total a cobrar", C_AZUL),
        ("Cobrado", _bs(totales.get('cobrado', 0)), "Total pagado", C_TEAL),
        ("Pendiente", _bs(totales.get('pendiente', 0)), "Por cobrar", C_AMBER),
    ]
    y = _grilla_metricas(c, y, items, cols=4, box_h=1.7 * cm)

    if not detalle:
        _pie(c, pg, 999, helpers['fecha'])
        pages_data.append((c, pg))
        return

    y = _titulo_seccion(c, y, "2. Listado de Sesiones")
    headers_s = ["Fecha", "Paciente", "Profesional", "Servicio", "Estado", "Costo", "Pagado", "Pend."]
    col_ws_s  = [2.1*cm, 3.5*cm, 3.5*cm, 3.0*cm, 2.1*cm, 1.9*cm, 1.9*cm, 1.5*cm]
    row_h_s   = 0.5 * cm

    ESTADOS = {
        'realizada': 'Real.', 'realizada_retraso': 'Real.R',
        'falta': 'Falta', 'cancelada': 'Cancel.',
        'programada': 'Prog.', 'permiso': 'Permiso',
    }

    for sesion in detalle:
        from decimal import Decimal as D
        costo   = float(sesion.monto_cobrado or 0)
        pagado  = float(getattr(sesion, '_total_pagado', 0) or 0)
        pend    = max(0, costo - pagado)
        estado  = ESTADOS.get(sesion.estado, sesion.estado[:6])
        prof    = sesion.profesional
        prof_n  = f"{prof.nombre} {prof.apellido}"[:18] if prof else '—'
        pac     = sesion.paciente
        pac_n   = f"{pac.nombre} {pac.apellido}"[:18] if pac else '—'
        serv_n  = sesion.servicio.nombre[:14] if sesion.servicio else '—'

        row = [
            sesion.fecha.strftime('%d/%m/%Y') if sesion.fecha else '',
            pac_n, prof_n, serv_n, estado,
            _bs(costo), _bs(pagado), _bs(pend),
        ]

        needed = row_h_s + 0.1 * cm
        if y - needed < Y_BOTTOM:
            _pie(c, pg, 999, helpers['fecha'])
            pages_data.append((c, pg))
            c, y, pg = make_page()
            y = _titulo_seccion(c, y, "2. Listado de Sesiones (cont.)")

        c.setStrokeColor(C_GRIS_BORDE)
        c.setLineWidth(0.2)
        c.line(ML, y - row_h_s, ML + sum(col_ws_s), y - row_h_s)
        x_cur = ML
        for c_idx, cell in enumerate(row):
            c.setFont("Helvetica", 7)
            c.setFillColor(C_TEXTO)
            c.drawString(x_cur + 0.15 * cm, y - row_h_s + 0.12 * cm, str(cell))
            x_cur += col_ws_s[c_idx]
        y -= row_h_s

    _pie(c, pg, 999, helpers['fecha'])
    pages_data.append((c, pg))


def _seccion_tabla_proyectos(pages_data, ctx, helpers):
    make_page = helpers['new_page']
    detalle = ctx.get('detalle_proyectos')
    totales = ctx.get('detalle_proyectos_totales') or {}

    c, y, pg = make_page()
    y = _titulo_seccion(c, y, "1. Resumen de Proyectos Terapeuticos")
    y = _explicacion(c, y,
        "Los proyectos son programas terapeuticos acordados entre el centro y el paciente "
        "por un numero definido de sesiones y un costo total. El paciente puede pagar en cuotas. "
        "Esta tabla muestra el avance de cobro de cada proyecto activo o finalizado en el periodo.")

    items = [
        ("Total proyectos", str(detalle.count() if detalle else 0),
         "En el periodo seleccionado", C_VERDE_MED),
        ("Costo total", _bs(totales.get('costo_total', 0)), "Valor acordado de todos los proyectos", C_AZUL),
        ("Cobrado neto", _bs(totales.get('cobrado', 0)), "Total pagado (menos devoluciones)", C_TEAL),
        ("Pendiente", _bs(totales.get('pendiente', 0)), "Por cobrar de los proyectos", C_AMBER),
    ]
    y = _grilla_metricas(c, y, items, cols=4, box_h=1.7 * cm)

    if not detalle:
        _pie(c, pg, 999, helpers['fecha'])
        pages_data.append((c, pg))
        return

    y = _titulo_seccion(c, y, "2. Listado de Proyectos")
    headers_p = ["Inicio", "Paciente", "Profesional", "Servicio", "Estado", "Costo", "Cobrado", "Pend."]
    col_ws_p  = [2.1*cm, 3.5*cm, 3.5*cm, 3.0*cm, 2.1*cm, 1.9*cm, 1.9*cm, 1.5*cm]
    row_h_p   = 0.5 * cm

    for proy in detalle:
        costo  = float(proy.costo_total or 0)
        cobrado= float(getattr(proy, 'total_pagado_calc', 0) or 0)
        pend   = max(0, costo - cobrado)
        prof   = proy.profesional_responsable
        prof_n = f"{prof.nombre} {prof.apellido}"[:18] if prof else '—'
        pac    = proy.paciente
        pac_n  = f"{pac.nombre} {pac.apellido}"[:18] if pac else '—'
        serv_n = proy.servicio_base.nombre[:14] if proy.servicio_base else '—'
        estado = proy.estado[:8] if proy.estado else '—'

        row = [
            proy.fecha_inicio.strftime('%d/%m/%Y') if proy.fecha_inicio else '',
            pac_n, prof_n, serv_n, estado,
            _bs(costo), _bs(cobrado), _bs(pend),
        ]

        needed = row_h_p + 0.1 * cm
        if y - needed < Y_BOTTOM:
            _pie(c, pg, 999, helpers['fecha'])
            pages_data.append((c, pg))
            c, y, pg = make_page()
            y = _titulo_seccion(c, y, "2. Listado de Proyectos (cont.)")

        c.setStrokeColor(C_GRIS_BORDE)
        c.setLineWidth(0.2)
        c.line(ML, y - row_h_p, ML + sum(col_ws_p), y - row_h_p)
        x_cur = ML
        for c_idx, cell in enumerate(row):
            c.setFont("Helvetica", 7)
            c.setFillColor(C_TEXTO)
            c.drawString(x_cur + 0.15 * cm, y - row_h_p + 0.12 * cm, str(cell))
            x_cur += col_ws_p[c_idx]
        y -= row_h_p

    _pie(c, pg, 999, helpers['fecha'])
    pages_data.append((c, pg))


def _seccion_tabla_mensualidades(pages_data, ctx, helpers):
    make_page = helpers['new_page']
    detalle = ctx.get('detalle_mensualidades')
    totales = ctx.get('detalle_mensualidades_totales') or {}

    c, y, pg = make_page()
    y = _titulo_seccion(c, y, "1. Resumen de Mensualidades")
    y = _explicacion(c, y,
        "Las mensualidades son planes de atencion continua donde el paciente paga una "
        "cuota mensual fija. Incluyen un numero determinado de sesiones por mes con uno "
        "o varios profesionales. Esta seccion muestra el estado de cobro de cada mensualidad "
        "activa, pausada o completada en el periodo.")

    items = [
        ("Mensualidades", str(detalle.count() if detalle else 0),
         "En el periodo seleccionado", C_VERDE_MED),
        ("Costo mensual total", _bs(totales.get('costo_total', 0)), "Suma de todas las cuotas", C_AZUL),
        ("Cobrado", _bs(totales.get('cobrado', 0)), "Total pagado", C_TEAL),
        ("Pendiente", _bs(totales.get('pendiente', 0)), "Por cobrar", C_AMBER),
    ]
    y = _grilla_metricas(c, y, items, cols=4, box_h=1.7 * cm)

    if not detalle:
        _pie(c, pg, 999, helpers['fecha'])
        pages_data.append((c, pg))
        return

    y = _titulo_seccion(c, y, "2. Listado de Mensualidades")
    headers_m = ["Periodo", "Paciente", "Sucursal", "Estado", "Costo Mensual", "Cobrado", "Pendiente"]
    col_ws_m  = [2.2*cm, 4.0*cm, 3.0*cm, 2.0*cm, 3.0*cm, 2.5*cm, 2.8*cm]
    row_h_m   = 0.5 * cm

    for mens in detalle:
        costo   = float(mens.costo_mensual or 0)
        cobrado = float(getattr(mens, '_total_pagado', 0) or 0)
        pend    = max(0, costo - cobrado)
        pac     = mens.paciente
        pac_n   = f"{pac.nombre} {pac.apellido}"[:22] if pac else '—'
        suc_n   = mens.sucursal.nombre[:14] if mens.sucursal else 'Global'
        periodo = f"{MESES_FULL[mens.mes][:3]}/{mens.anio}" if mens.mes and mens.anio else '—'
        estado  = mens.estado[:8] if mens.estado else '—'

        row = [periodo, pac_n, suc_n, estado, _bs(costo), _bs(cobrado), _bs(pend)]

        needed = row_h_m + 0.1 * cm
        if y - needed < Y_BOTTOM:
            _pie(c, pg, 999, helpers['fecha'])
            pages_data.append((c, pg))
            c, y, pg = make_page()
            y = _titulo_seccion(c, y, "2. Listado de Mensualidades (cont.)")

        c.setStrokeColor(C_GRIS_BORDE)
        c.setLineWidth(0.2)
        c.line(ML, y - row_h_m, ML + sum(col_ws_m), y - row_h_m)
        x_cur = ML
        for c_idx, cell in enumerate(row):
            c.setFont("Helvetica", 7.5)
            c.setFillColor(C_TEXTO)
            c.drawString(x_cur + 0.15 * cm, y - row_h_m + 0.12 * cm, str(cell))
            x_cur += col_ws_m[c_idx]
        y -= row_h_m

    _pie(c, pg, 999, helpers['fecha'])
    pages_data.append((c, pg))


def _seccion_creditos(pages_data, ctx, helpers):
    make_page = helpers['new_page']
    ac = ctx.get('analisis_creditos') or {}

    c, y, pg = make_page()
    y = _titulo_seccion(c, y, "1. Analisis de Creditos y Adelantos")
    y = _explicacion(c, y,
        "Los creditos son pagos que los pacientes realizaron de forma adelantada, antes de que "
        "se les asigne a un servicio especifico. Funcionan como un 'saldo a favor': cuando el "
        "paciente recibe una sesion o servicio, el sistema descuenta automaticamente del credito. "
        "Esta seccion muestra el movimiento de creditos en el periodo: cuanto se adelanto, cuanto "
        "se uso y que saldo queda disponible para cada paciente.")

    items = [
        ("Creditos generados", _bs(ac.get('total_generado', 0)),
         f"{len(list(ac.get('generados', []) or []))} adelantos registrados", C_MORADO),
        ("Creditos utilizados", _bs(ac.get('total_utilizado', 0)),
         f"{len(list(ac.get('utilizados', []) or []))} aplicaciones a servicios", C_AZUL),
        ("Saldo disponible", _bs(ac.get('saldo_disponible', 0) or ac.get('saldo_neto', 0)),
         "Total aun sin aplicar a servicios", C_VERDE_MED),
        ("Pacientes con credito", str(len(list(ac.get('pacientes_con_credito', []) or []))),
         "Con saldo a favor activo", C_TEAL),
    ]
    y = _grilla_metricas(c, y, items, cols=4, box_h=1.7 * cm)

    # Pacientes con crédito disponible
    pacientes_cc = list(ac.get('pacientes_con_credito', []) or [])
    if pacientes_cc:
        y = _titulo_seccion(c, y, "2. Pacientes con Credito Disponible")
        y = _explicacion(c, y,
            "Estos pacientes tienen saldo a favor en su cuenta corriente con el centro. "
            "Ese saldo fue pagado con anticipacion y aun no ha sido aplicado a ningun servicio.")
        headers_pc = ["Paciente", "Credito Generado", "Credito Usado", "Saldo Disponible"]
        col_ws_pc  = [7*cm, 3.5*cm, 3.5*cm, 3.5*cm]
        rows_pc = [
            [_nombre_paciente(p),
             _bs(_attr(p, 'credito_generado', 0)),
             _bs(_attr(p, 'credito_usado', 0)),
             _bs(_attr(p, 'credito_disponible', 0))]
            for p in pacientes_cc[:20]
        ]
        y = _tabla(c, y, headers_pc, rows_pc, col_ws_pc)

    _pie(c, pg, 999, helpers['fecha'])
    pages_data.append((c, pg))


# ─────────────────────────────────────────────────────────────────────
# FUNCIÓN PRINCIPAL
# ─────────────────────────────────────────────────────────────────────

def generar_informe_financiero_pdf(context):
    """
    Genera el informe financiero en PDF a partir del contexto del template.
    Retorna un BytesIO listo para servir como HttpResponse.
    """
    vista        = context.get('vista') or 'mensual'
    fecha_desde  = context.get('fecha_desde', '')
    fecha_hasta  = context.get('fecha_hasta', '')
    sucursal_id  = context.get('sucursal_id', '')
    sucursal_obj = None

    # Intentar resolver nombre de sucursal
    if sucursal_id:
        try:
            from servicios.models import Sucursal
            sucursal_obj = Sucursal.objects.filter(id=sucursal_id).first()
        except Exception:
            pass

    sucursal_txt = sucursal_obj.nombre if sucursal_obj else ''
    titulo_vista = VISTA_TITULOS.get(vista, 'INFORME FINANCIERO')

    # Período legible
    if fecha_desde and fecha_hasta:
        if fecha_desde == fecha_hasta:
            try:
                from datetime import datetime
                fd = datetime.strptime(fecha_desde, '%Y-%m-%d').date()
                periodo_txt = fd.strftime('%d de ') + MESES_FULL[fd.month] + fd.strftime(' de %Y')
            except Exception:
                periodo_txt = fecha_desde
        else:
            periodo_txt = f"{fecha_desde}  al  {fecha_hasta}"
    else:
        periodo_txt = 'Periodo no especificado'

    fecha_emision = _date_cls.today().strftime('%d/%m/%Y')

    # ── Estructura de páginas ────────────────────────────────────────
    # Usamos una lista de buffers (una canvas por "sección").
    # Al final concatenamos con pypdf para actualizar total de páginas.
    # Estrategia simple: canvas único multi-página.

    buffer = BytesIO()
    c = pdf_canvas.Canvas(buffer, pagesize=letter)
    c.setTitle(f"{titulo_vista} - {periodo_txt}")
    c.setAuthor(NOMBRE_CENTRO)
    c.setSubject("Informe Financiero Confidencial")

    # Estado de paginación
    page_counter = [1]  # mutable para closure

    def make_page():
        """Crea una nueva página y retorna (canvas, y_inicial, num_página)."""
        page_counter[0] += 1
        pg = page_counter[0]
        # showPage ya fue llamado por _new_page — NO llamar aquí
        c.setFillColor(C_FONDO_PAG)
        c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
        y = _encabezado(c, pg, 999, titulo_vista, periodo_txt, sucursal_txt, fecha_emision)
        return c, y, pg

    helpers = {
        'new_page': make_page,
        'fecha': fecha_emision,
    }

    # Necesitamos wrap de showPage para el make_page
    original_new_page = make_page

    def make_page_wrapped():
        c.showPage()
        return original_new_page()

    helpers['new_page'] = make_page_wrapped
    pages_data = []  # para contar páginas al final

    # ── PORTADA (página 1) ───────────────────────────────────────────
    c.setFillColor(C_FONDO_PAG)
    c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    _portada(c, titulo_vista, periodo_txt, sucursal_txt, fecha_emision, vista, context)
    pages_data.append(('portada', 1))

    # ── CONTENIDO según vista ────────────────────────────────────────
    if vista in ('mensual', '', None):
        _seccion_mensual(pages_data, context, helpers)
    elif vista == 'diaria':
        _seccion_diaria(pages_data, context, helpers)
    elif vista == 'detalle_pagos':
        _seccion_tabla_pagos(pages_data, context, helpers)
    elif vista == 'detalle_sesiones':
        _seccion_tabla_sesiones(pages_data, context, helpers)
    elif vista == 'detalle_proyectos':
        _seccion_tabla_proyectos(pages_data, context, helpers)
    elif vista == 'detalle_mensualidades':
        _seccion_tabla_mensualidades(pages_data, context, helpers)
    elif vista == 'analisis_creditos':
        _seccion_creditos(pages_data, context, helpers)

    total_pages = page_counter[0]
    c.save()

    # ── Segunda pasada: actualizar "Pag. X de TOTAL" ────────────────
    # Regenerar con total_pages correcto usando el mismo flujo pero
    # reemplazando 999 por total_pages en el encabezado y pie.
    # Como ReportLab no permite edición post-save, re-generamos el buffer.
    buffer2 = BytesIO()
    c2 = pdf_canvas.Canvas(buffer2, pagesize=letter)
    c2.setTitle(f"{titulo_vista} - {periodo_txt}")
    c2.setAuthor(NOMBRE_CENTRO)

    pg2 = [1]

    def make_page2():
        pg2[0] += 1
        pg = pg2[0]
        c2.setFillColor(C_FONDO_PAG)
        c2.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
        y = _encabezado(c2, pg, total_pages, titulo_vista, periodo_txt, sucursal_txt, fecha_emision)
        return c2, y, pg

    def make_page2_wrapped():
        c2.showPage()
        return make_page2()

    helpers2 = {'new_page': make_page2_wrapped, 'fecha': fecha_emision}
    pages_data2 = []

    c2.setFillColor(C_FONDO_PAG)
    c2.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    _portada(c2, titulo_vista, periodo_txt, sucursal_txt, fecha_emision, vista, context)
    # Actualizar número total en pie de portada
    _pie(c2, 1, total_pages, fecha_emision)
    pages_data2.append(('portada', 1))

    if vista in ('mensual', '', None):
        _seccion_mensual(pages_data2, context, helpers2)
    elif vista == 'diaria':
        _seccion_diaria(pages_data2, context, helpers2)
    elif vista == 'detalle_pagos':
        _seccion_tabla_pagos(pages_data2, context, helpers2)
    elif vista == 'detalle_sesiones':
        _seccion_tabla_sesiones(pages_data2, context, helpers2)
    elif vista == 'detalle_proyectos':
        _seccion_tabla_proyectos(pages_data2, context, helpers2)
    elif vista == 'detalle_mensualidades':
        _seccion_tabla_mensualidades(pages_data2, context, helpers2)
    elif vista == 'analisis_creditos':
        _seccion_creditos(pages_data2, context, helpers2)

    c2.save()
    buffer2.seek(0)
    return buffer2