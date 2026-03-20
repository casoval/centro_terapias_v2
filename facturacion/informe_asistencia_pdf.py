# facturacion/informe_asistencia_pdf.py
# =====================================================================
# GENERADOR DE INFORME DE ASISTENCIA PROFESIONAL — ReportLab canvas
# Refleja exactamente el contexto de la vista reporte_asistencia:
#   stats, tasas, por_servicio, por_profesional, por_sucursal,
#   ranking, peores_asistencia, retrasos_detalle, por_dia_semana,
#   reprogramaciones, sesiones_lista (tabla detallada paginada completa)
# =====================================================================

import os
import logging
from io import BytesIO
from datetime import date as _date_cls

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.pdfbase.pdfmetrics import stringWidth
from django.conf import settings

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────
# PALETA  (misma que informe_financiero_pdf para coherencia visual)
# ─────────────────────────────────────────────────────────────────────
C_OSC    = colors.HexColor('#0a0f1e')
C_PRI    = colors.HexColor('#1e3a8a')   # Azul índigo oscuro
C_MED    = colors.HexColor('#4338ca')   # Índigo
C_FONDO  = colors.HexColor('#f5f3ff')   # Índigo muy claro
C_L      = colors.HexColor('#e0e7ff')
C_VERDE  = colors.HexColor('#059669')
C_VERDE_L= colors.HexColor('#d1fae5')
C_AMBER  = colors.HexColor('#d97706')
C_AMBER_L= colors.HexColor('#fef3c7')
C_ROJO   = colors.HexColor('#be123c')
C_ROJO_L = colors.HexColor('#ffe4e6')
C_MORADO = colors.HexColor('#7c3aed')
C_MORADO_L=colors.HexColor('#ede9fe')
C_TEAL   = colors.HexColor('#0d9488')
C_TEAL_L = colors.HexColor('#ccfbf1')
C_SKY    = colors.HexColor('#0284c7')
C_SKY_L  = colors.HexColor('#e0f2fe')
C_GRIS_T = colors.HexColor('#f8fafc')
C_GRIS_H = colors.HexColor('#e2e8f0')
C_GRIS_B = colors.HexColor('#cbd5e1')
C_TEXTO  = colors.HexColor('#0f172a')
C_TSEC   = colors.HexColor('#334155')
C_MUTED  = colors.HexColor('#64748b')
C_BLANCO = colors.white
C_FONDO_PAG = colors.HexColor('#f8fafc')

# ─────────────────────────────────────────────────────────────────────
# LAYOUT
# ─────────────────────────────────────────────────────────────────────
PAGE_W, PAGE_H = letter
ML = 1.8 * cm
MR = 1.8 * cm
MT = 1.5 * cm
MB = 1.5 * cm
CW = PAGE_W - ML - MR
HEADER_H = 2.6 * cm
FOOTER_H = 0.9 * cm
Y_BOTTOM = MB + FOOTER_H + 0.3 * cm

NOMBRE_CENTRO = "Centro de Neurodesarrollo Infantil Misael"
DIRECCION     = "Calle Japon #28  -  Potosi, Bolivia"
TELEFONO      = "Tel.: 76175352"

MESES_FULL = ['', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
              'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']

DIAS_ES = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']

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


def _wrap(c, text, x, y, max_w, font, fsize, lh):
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


def _num(v, default=0):
    try:
        return int(float(v))
    except Exception:
        return default


def _pct(v):
    try:
        f = float(str(v).replace('%', ''))
        return f"{f:.1f}%"
    except Exception:
        return "0.0%"


def _attr(obj, key, default=''):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default) or default


# ─────────────────────────────────────────────────────────────────────
# ENCABEZADO, PIE, NUEVA PÁGINA
# ─────────────────────────────────────────────────────────────────────

def _encabezado(c, pg, total_pg, titulo_vista, periodo_txt, filtros_txt, fecha_emision):
    _grad(c, 0, PAGE_H - HEADER_H, PAGE_W, HEADER_H, C_OSC, C_PRI)

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

    # Banda informativa
    by = PAGE_H - HEADER_H - 0.8 * cm - 0.1 * cm
    c.setFillColor(C_FONDO)
    c.roundRect(ML, by, CW, 0.78 * cm, 4, fill=1, stroke=0)
    c.setStrokeColor(C_MED)
    c.setLineWidth(0.4)
    c.roundRect(ML, by, CW, 0.78 * cm, 4, fill=0, stroke=1)

    c.setFont("Helvetica-Bold", 7)
    c.setFillColor(C_PRI)
    c.drawString(ML + 0.35 * cm, by + 0.48 * cm, "PERIODO:")
    c.setFont("Helvetica", 8)
    c.setFillColor(C_TEXTO)
    c.drawString(ML + 1.8 * cm, by + 0.48 * cm, periodo_txt)

    if filtros_txt:
        c.setFont("Helvetica", 6.5)
        c.setFillColor(C_MUTED)
        c.drawString(ML + 7.5 * cm, by + 0.48 * cm, filtros_txt)

    c.setFont("Helvetica", 7)
    c.setFillColor(C_MUTED)
    c.drawRightString(PAGE_W - MR, by + 0.48 * cm, f"Emitido: {fecha_emision}")

    return by - 0.4 * cm


def _pie(c, pg, total_pg, fecha_emision):
    py = MB + 0.15 * cm
    c.setStrokeColor(C_GRIS_B)
    c.setLineWidth(0.4)
    c.line(ML, py + FOOTER_H - 0.15 * cm, PAGE_W - MR, py + FOOTER_H - 0.15 * cm)
    c.setFont("Helvetica", 6.5)
    c.setFillColor(C_MUTED)
    c.drawString(ML, py + 0.28 * cm,
                 f"{NOMBRE_CENTRO}  |  Informe de Asistencia generado el {fecha_emision}  |  CONFIDENCIAL — USO INTERNO")
    c.drawRightString(PAGE_W - MR, py + 0.28 * cm, f"Pagina {pg} / {total_pg}")


# ─────────────────────────────────────────────────────────────────────
# PRIMITIVOS DE DIBUJO  (mismos que informe_financiero_pdf)
# ─────────────────────────────────────────────────────────────────────

def _titulo_seccion(c, y, texto, color=None):
    col = color or C_PRI
    c.setFillColor(col)
    c.roundRect(ML, y - 0.55 * cm, CW, 0.55 * cm, 4, fill=1, stroke=0)
    c.setFillColor(C_BLANCO)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(ML + 0.4 * cm, y - 0.38 * cm, texto.upper())
    return y - 0.55 * cm - 0.3 * cm


def _explicacion(c, y, texto, max_w=None):
    mw = max_w or (CW - 0.4 * cm)
    c.setFont("Helvetica-Oblique", 7.8)
    c.setFillColor(C_MUTED)
    ny = _wrap(c, texto, ML + 0.2 * cm, y, mw, "Helvetica-Oblique", 7.8, 0.38 * cm)
    return ny - 0.25 * cm


def _metrica_box(c, x, y, w, h, label, valor, sublabel='', color=C_MED, fondo=None):
    """
    Tarjeta de métrica rediseñada:
      ┌──────────────────────────────┐
      │▌ LABEL (pequeño, color)      │   ← barra lateral izquierda de color
      │                              │
      │   VALOR (grande, centrado)   │
      │                              │
      │   sublabel (gris, pequeño)   │
      └──────────────────────────────┘
    Fondo con tinte suave del color principal.
    """
    top = y
    bot = y - h

    # ── Fondo con tinte suave del color ──────────────────────────────
    r_tint = 1.0 - (1.0 - color.red)   * 0.10
    g_tint = 1.0 - (1.0 - color.green) * 0.10
    b_tint = 1.0 - (1.0 - color.blue)  * 0.10
    bg = colors.Color(r_tint, g_tint, b_tint)
    c.setFillColor(bg)
    c.roundRect(x, bot, w, h, 6, fill=1, stroke=0)

    # ── Borde sutil ───────────────────────────────────────────────────
    c.setStrokeColor(color)
    c.setLineWidth(0.5)
    c.roundRect(x, bot, w, h, 6, fill=0, stroke=1)

    # ── Barra lateral izquierda (accent bar) ──────────────────────────
    bar_w = 0.22 * cm
    c.setFillColor(color)
    # Rectángulo con esquinas izq redondeadas: dibujo manual
    c.roundRect(x, bot, bar_w * 2, h, 5, fill=1, stroke=0)   # redondeado
    c.rect(x + bar_w, bot, bar_w, h, fill=1, stroke=0)        # tapa esquinas derechas

    pad_l = bar_w + 0.25 * cm   # padding desde la barra
    avail_w = w - pad_l - 0.18 * cm

    # ── Label (arriba, pequeño, color) ────────────────────────────────
    c.setFont("Helvetica-Bold", 6.2)
    c.setFillColor(color)
    lbl_y = top - 0.42 * cm
    lbl_txt = label.upper()
    # Truncar si no cabe
    while stringWidth(lbl_txt, "Helvetica-Bold", 6.2) > avail_w and len(lbl_txt) > 2:
        lbl_txt = lbl_txt[:-2] + '.'
    c.drawString(x + pad_l, lbl_y, lbl_txt)

    # ── Valor (grande, oscuro, centrado verticalmente) ─────────────────
    # Centro vertical de la caja, ajustado hacia arriba por el sublabel
    mid_y = bot + h * 0.52
    for fsize in (15, 13, 11, 9, 8):
        sw = stringWidth(valor, "Helvetica-Bold", fsize)
        if sw <= avail_w:
            break
    c.setFont("Helvetica-Bold", fsize)
    c.setFillColor(C_TEXTO)
    c.drawString(x + pad_l, mid_y - fsize * 0.015 * cm, valor)

    # ── Sublabel (abajo, gris) ────────────────────────────────────────
    if sublabel:
        c.setFont("Helvetica", 6)
        c.setFillColor(C_MUTED)
        sub = sublabel
        while stringWidth(sub, "Helvetica", 6) > avail_w and len(sub) > 4:
            sub = sub[:-2] + '…'
        c.drawString(x + pad_l, bot + 0.22 * cm, sub)


def _grilla_metricas(c, y, items, cols=4, box_h=1.7 * cm):
    gap = 0.25 * cm   # espacio entre tarjetas
    box_w = (CW - (cols - 1) * gap) / cols
    row_items = []
    for item in items:
        row_items.append(item)
        if len(row_items) == cols:
            for i, (lbl, val, sub, col) in enumerate(row_items):
                bx = ML + i * (box_w + gap)
                _metrica_box(c, bx, y, box_w, box_h, lbl, val, sub, col)
            y -= box_h + 0.35 * cm
            row_items = []
    if row_items:
        n = len(row_items)
        box_w2 = (CW - (n - 1) * gap) / max(n, 1)
        for i, (lbl, val, sub, col) in enumerate(row_items):
            bx = ML + i * (box_w2 + gap)
            _metrica_box(c, bx, y, box_w2, box_h, lbl, val, sub, col)
        y -= box_h + 0.35 * cm
    return y


def _tabla(c, y, headers, rows, col_ws, stripe=True, font_size=7.5, row_h=0.52 * cm):
    total_w = sum(col_ws)
    # Encabezado
    c.setFillColor(C_GRIS_H)
    c.roundRect(ML, y - row_h, total_w, row_h, 3, fill=1, stroke=0)
    c.setStrokeColor(C_GRIS_B)
    c.setLineWidth(0.3)
    c.roundRect(ML, y - row_h, total_w, row_h, 3, fill=0, stroke=1)
    x_cur = ML
    for i, hdr in enumerate(headers):
        c.setFont("Helvetica-Bold", 7)
        c.setFillColor(C_TSEC)
        c.drawString(x_cur + 0.25 * cm, y - row_h + 0.15 * cm, str(hdr).upper())
        x_cur += col_ws[i]
    y -= row_h
    # Filas
    for r_idx, row in enumerate(rows):
        if stripe and r_idx % 2 == 0:
            c.setFillColor(C_GRIS_T)
            c.rect(ML, y - row_h, total_w, row_h, fill=1, stroke=0)
        c.setStrokeColor(C_GRIS_B)
        c.setLineWidth(0.2)
        c.line(ML, y - row_h, ML + total_w, y - row_h)
        x_cur = ML
        for c_idx, cell in enumerate(row):
            c.setFont("Helvetica", font_size)
            c.setFillColor(C_TEXTO)
            txt = str(cell) if cell is not None else ''
            max_w_cell = col_ws[c_idx] - 0.5 * cm
            while stringWidth(txt, "Helvetica", font_size) > max_w_cell and len(txt) > 1:
                txt = txt[:-2] + '.'
            c.drawString(x_cur + 0.25 * cm, y - row_h + 0.13 * cm, txt)
            x_cur += col_ws[c_idx]
        y -= row_h
    c.setStrokeColor(C_GRIS_B)
    c.setLineWidth(0.4)
    c.line(ML, y, ML + sum(col_ws), y)
    return y - 0.2 * cm


def _barra_horizontal(c, x, y, ancho_total, valor, maximo, color, h=0.28 * cm):
    """Dibuja una barra de progreso horizontal."""
    pct = min(float(valor) / float(maximo), 1.0) if maximo else 0
    # Fondo gris
    c.setFillColor(C_GRIS_H)
    c.roundRect(x, y - h, ancho_total, h, 2, fill=1, stroke=0)
    # Relleno
    if pct > 0:
        c.setFillColor(color)
        c.roundRect(x, y - h, ancho_total * pct, h, 2, fill=1, stroke=0)


# ─────────────────────────────────────────────────────────────────────
# PORTADA
# ─────────────────────────────────────────────────────────────────────

def _portada(c, titulo, periodo_txt, filtros_txt, fecha_emision, ctx):
    c.setFillColor(C_FONDO_PAG)
    c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)

    # Franja superior oscura
    _grad(c, 0, PAGE_H - 5.5 * cm, PAGE_W, 5.5 * cm, C_OSC, C_PRI)

    lp = _logo()
    if lp:
        try:
            c.drawImage(lp, ML, PAGE_H - 4.5 * cm, width=3 * cm, height=3 * cm,
                        preserveAspectRatio=True, mask='auto')
        except Exception:
            pass

    c.setFillColor(C_BLANCO)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(ML + 3.5 * cm, PAGE_H - 2.2 * cm, NOMBRE_CENTRO)
    c.setFont("Helvetica", 9)
    c.drawString(ML + 3.5 * cm, PAGE_H - 2.85 * cm, f"{DIRECCION}  |  {TELEFONO}")

    c.setStrokeColor(colors.HexColor('#a5b4fc'))
    c.setLineWidth(1.5)
    c.line(ML, PAGE_H - 5.5 * cm + 0.3 * cm, PAGE_W - MR, PAGE_H - 5.5 * cm + 0.3 * cm)

    ty = PAGE_H - 8.0 * cm
    c.setFont("Helvetica-Bold", 22)
    c.setFillColor(C_TEXTO)
    c.drawCentredString(PAGE_W / 2, ty, titulo)

    c.setStrokeColor(C_MED)
    c.setLineWidth(2)
    tw = stringWidth(titulo, "Helvetica-Bold", 22)
    c.line(PAGE_W / 2 - tw / 2, ty - 0.3 * cm, PAGE_W / 2 + tw / 2, ty - 0.3 * cm)

    c.setFont("Helvetica", 11)
    c.setFillColor(C_TSEC)
    c.drawCentredString(PAGE_W / 2, ty - 1.0 * cm, f"Periodo: {periodo_txt}")
    if filtros_txt:
        c.setFont("Helvetica", 9)
        c.drawCentredString(PAGE_W / 2, ty - 1.6 * cm, filtros_txt)

    c.setFont("Helvetica", 9)
    c.setFillColor(C_MUTED)
    c.drawCentredString(PAGE_W / 2, ty - 2.4 * cm, f"Documento generado el {fecha_emision}")

    # Caja de resumen ejecutivo
    stats = ctx.get('stats') or {}
    tasas = ctx.get('tasas') or {}

    total       = _num(stats.get('total', 0))
    realizadas  = _num(stats.get('realizadas', 0))
    retrasos    = _num(stats.get('retrasos', 0))
    faltas      = _num(stats.get('faltas', 0))
    permisos    = _num(stats.get('permisos', 0))
    canceladas  = _num(stats.get('canceladas', 0))
    programadas = _num(stats.get('programadas', 0))

    tasa_asis = _pct(tasas.get('tasa_asistencia', 0))
    tasa_punt = _pct(tasas.get('puntualidad', 0))
    tasa_falt = _pct(tasas.get('tasa_faltas', 0))

    cy = ty - 3.5 * cm
    c.setStrokeColor(C_GRIS_B)
    c.setLineWidth(0.5)
    c.roundRect(ML, cy - 5.0 * cm, CW, 5.0 * cm, 8, fill=0, stroke=1)
    c.setFillColor(C_GRIS_T)
    c.roundRect(ML, cy - 5.0 * cm, CW, 5.0 * cm, 8, fill=1, stroke=0)
    c.roundRect(ML, cy - 5.0 * cm, CW, 5.0 * cm, 8, fill=0, stroke=1)

    c.setFont("Helvetica-Bold", 9)
    c.setFillColor(C_PRI)
    c.drawString(ML + 0.5 * cm, cy - 0.45 * cm, "INDICADORES CLAVE DEL PERIODO")

    kpis_fila1 = [
        ("Total sesiones", str(total),       "En el periodo filtrado",       C_SKY),
        ("Realizadas",     str(realizadas + retrasos),
                                              f"Asistencia: {tasa_asis}",     C_VERDE),
        ("Faltas",         str(faltas),       f"Tasa faltas: {tasa_falt}",    C_ROJO),
        ("Permisos",       str(permisos),     "Con justificacion",            C_AMBER),
    ]
    kpis_fila2 = [
        ("Canceladas",     str(canceladas),   "Por el centro",                C_MUTED),
        ("Programadas",    str(programadas),  "Pendientes de realizarse",      C_MORADO),
        ("Puntualidad",    tasa_punt,         "% realizadas sin retraso",     C_TEAL),
        ("Retrasos",       str(retrasos),     "Con demora del paciente",      C_SKY),
    ]

    box_h_p = 1.95 * cm
    gap_p   = 0.25 * cm
    box_w_p = (CW - 1.0 * cm - 3 * gap_p) / 4   # 4 cajas por fila, 0.5cm padding a/c/lado

    for i, (lbl, val, sub, col) in enumerate(kpis_fila1):
        bx = ML + 0.5 * cm + i * (box_w_p + gap_p)
        _metrica_box(c, bx, cy - 0.55 * cm, box_w_p, box_h_p, lbl, val, sub, col)

    for i, (lbl, val, sub, col) in enumerate(kpis_fila2):
        bx = ML + 0.5 * cm + i * (box_w_p + gap_p)
        _metrica_box(c, bx, cy - 0.55 * cm - box_h_p - 0.35 * cm,
                     box_w_p, box_h_p, lbl, val, sub, col)

    _pie(c, 1, 999, fecha_emision)


# ─────────────────────────────────────────────────────────────────────
# SECCIÓN 1 — SEMÁFORO DE ESTADÍSTICAS GLOBALES
# ─────────────────────────────────────────────────────────────────────

def _seccion_stats(pages_data, ctx, helpers, total_pg_ref):
    make_page = helpers['new_page']
    fecha     = helpers['fecha']
    stats = ctx.get('stats') or {}
    tasas = ctx.get('tasas') or {}

    c, y, pg = make_page()

    y = _titulo_seccion(c, y, "1. Estadísticas Globales de Asistencia")
    y = _explicacion(c, y,
        "Resumen cuantitativo de todas las sesiones en el periodo seleccionado. "
        "Se contabilizan todos los estados registrados en el sistema y se calculan "
        "las tasas de asistencia, puntualidad y ausentismo sobre la base de sesiones "
        "que debían realizarse (realizadas + retrasos + faltas + permisos).")

    total       = _num(stats.get('total', 0))
    realizadas  = _num(stats.get('realizadas', 0))
    retrasos    = _num(stats.get('retrasos', 0))
    faltas      = _num(stats.get('faltas', 0))
    permisos    = _num(stats.get('permisos', 0))
    canceladas  = _num(stats.get('canceladas', 0))
    reprogramadas = _num(stats.get('reprogramadas', 0))
    programadas = _num(stats.get('programadas', 0))

    items_row1 = [
        ("Total sesiones",   str(total),              "Registradas en el periodo",   C_SKY),
        ("Realizadas",       str(realizadas),          "Sin retraso",                 C_VERDE),
        ("Con retraso",      str(retrasos),            "Llegaron tarde",              C_AMBER),
        ("Faltas",           str(faltas),              "No asistieron",               C_ROJO),
    ]
    items_row2 = [
        ("Permisos",         str(permisos),            "Justificados",                C_MORADO),
        ("Canceladas",       str(canceladas),          "Por el centro",               C_MUTED),
        ("Reprogramadas",    str(reprogramadas),       "Reagendadas",                 C_TEAL),
        ("Programadas",      str(programadas),         "Pendientes",                  C_PRI),
    ]

    y = _grilla_metricas(c, y, items_row1, cols=4, box_h=1.65 * cm)
    y = _grilla_metricas(c, y, items_row2, cols=4, box_h=1.65 * cm)

    # ── Tasas de rendimiento ──────────────────────────────────────────
    y -= 0.3 * cm
    y = _titulo_seccion(c, y, "1.2 Tasas de Rendimiento", color=C_VERDE)

    tasa_asis = _pct(tasas.get('tasa_asistencia', 0))
    tasa_punt = _pct(tasas.get('puntualidad', 0))
    tasa_falt = _pct(tasas.get('tasa_faltas', 0))
    tasa_perm = _pct(tasas.get('tasa_permisos', 0))

    items_tasas = [
        ("Tasa de asistencia",   tasa_asis, "Realizadas / (Real + Faltas + Permisos)", C_VERDE),
        ("Puntualidad",          tasa_punt, "Sin retraso / (Real + Retrasos)",          C_SKY),
        ("Tasa de faltas",       tasa_falt, "Faltas / base de asistencia",             C_ROJO),
        ("Tasa de permisos",     tasa_perm, "Permisos / base de asistencia",           C_AMBER),
    ]
    y = _grilla_metricas(c, y, items_tasas, cols=4, box_h=1.65 * cm)

    _pie(c, pg, helpers["total_pg"][0], fecha)
    pages_data.append(pg)


# ─────────────────────────────────────────────────────────────────────
# SECCIÓN 2 — POR DÍA DE LA SEMANA
# ─────────────────────────────────────────────────────────────────────

def _seccion_por_dia(pages_data, ctx, helpers):
    make_page = helpers['new_page']
    fecha     = helpers['fecha']
    por_dia   = ctx.get('por_dia_semana') or []

    if not por_dia:
        return

    c, y, pg = make_page()
    y = _titulo_seccion(c, y, "2. Distribución por Día de la Semana")
    y = _explicacion(c, y,
        "Muestra cuántas sesiones ocurren en cada día de la semana y el desglose "
        "de estados. Permite identificar qué días concentran mayor actividad y "
        "en qué días se producen más faltas o cancelaciones.")

    headers = ["Día", "Total", "Realizadas", "Retrasos", "Faltas", "Permisos", "Canceladas", "% Asistencia"]
    col_ws  = [2.8*cm, 1.4*cm, 2.2*cm,      2.0*cm,     1.6*cm,   2.0*cm,     2.2*cm,        2.3*cm]

    rows = []
    for d in por_dia:
        total_d = _num(d.get('total', 0))
        real_d  = _num(d.get('realizadas', 0)) + _num(d.get('retrasos', 0))
        base_d  = real_d + _num(d.get('faltas', 0)) + _num(d.get('permisos', 0))
        tasa_d  = f"{100 * real_d / base_d:.1f}%" if base_d else "—"
        rows.append([
            d.get('nombre', ''),
            str(total_d),
            str(_num(d.get('realizadas', 0))),
            str(_num(d.get('retrasos', 0))),
            str(_num(d.get('faltas', 0))),
            str(_num(d.get('permisos', 0))),
            str(_num(d.get('canceladas', 0))),
            tasa_d,
        ])

    y = _tabla(c, y, headers, rows, col_ws)

    _pie(c, pg, helpers["total_pg"][0], fecha)
    pages_data.append(pg)


# ─────────────────────────────────────────────────────────────────────
# SECCIÓN 3 — POR SERVICIO
# ─────────────────────────────────────────────────────────────────────

def _seccion_por_servicio(pages_data, ctx, helpers):
    make_page   = helpers['new_page']
    fecha       = helpers['fecha']
    por_servicio = ctx.get('por_servicio') or []

    if not por_servicio:
        return

    c, y, pg = make_page()
    y = _titulo_seccion(c, y, "3. Asistencia por Tipo de Servicio")
    y = _explicacion(c, y,
        "Desglose de sesiones clasificadas por el tipo de servicio terapéutico. "
        "Permite comparar la asistencia y las tasas de cumplimiento entre las "
        "distintas disciplinas ofrecidas en el centro.")

    headers = ["Servicio", "Total", "Realizadas", "Retrasos", "Faltas", "Permisos", "Cancel.", "Reproq.", "% Asist."]
    col_ws  = [4.5*cm, 1.2*cm, 1.8*cm,    1.7*cm,   1.5*cm,  1.8*cm,   1.5*cm,    1.5*cm,    1.6*cm]

    rows = []
    for s in por_servicio:
        rows.append([
            s.get('servicio__nombre') or '—',
            str(_num(s.get('total', 0))),
            str(_num(s.get('realizadas', 0))),
            str(_num(s.get('retrasos', 0))),
            str(_num(s.get('faltas', 0))),
            str(_num(s.get('permisos', 0))),
            str(_num(s.get('canceladas', 0))),
            str(_num(s.get('reprogramadas', 0))),
            _pct(s.get('tasa_asistencia', 0)),
        ])

    y = _tabla(c, y, headers, rows, col_ws)

    _pie(c, pg, helpers["total_pg"][0], fecha)
    pages_data.append(pg)


# ─────────────────────────────────────────────────────────────────────
# SECCIÓN 4 — POR PROFESIONAL
# ─────────────────────────────────────────────────────────────────────

def _seccion_por_profesional(pages_data, ctx, helpers):
    make_page      = helpers['new_page']
    fecha          = helpers['fecha']
    por_profesional = ctx.get('por_profesional') or []

    if not por_profesional:
        return

    c, y, pg = make_page()
    y = _titulo_seccion(c, y, "4. Asistencia por Profesional")
    y = _explicacion(c, y,
        "Comparativa del desempeño de cada profesional: total de sesiones a su "
        "cargo, cuántas se realizaron, cuántas tuvieron retraso y la tasa de "
        "puntualidad (sesiones sin retraso / sesiones realizadas).")

    headers = ["Profesional", "Sesiones", "Realizadas", "Retrasos", "Faltas", "Permisos", "Cancel.", "% Asist.", "Puntual."]
    col_ws  = [4.0*cm, 1.5*cm,  1.8*cm,    1.7*cm,   1.5*cm,  1.8*cm,   1.5*cm,    1.5*cm,   1.8*cm]

    rows = []
    for p in por_profesional:
        nombre = f"{p.get('profesional__nombre', '')} {p.get('profesional__apellido', '')}".strip() or '—'
        rows.append([
            nombre,
            str(_num(p.get('sesiones', 0))),
            str(_num(p.get('realizadas', 0))),
            str(_num(p.get('retrasos', 0))),
            str(_num(p.get('faltas', 0))),
            str(_num(p.get('permisos', 0))),
            str(_num(p.get('canceladas', 0))),
            _pct(p.get('tasa_asistencia', 0)),
            _pct(p.get('puntualidad', 0)),
        ])

    y = _tabla(c, y, headers, rows, col_ws)

    _pie(c, pg, helpers["total_pg"][0], fecha)
    pages_data.append(pg)


# ─────────────────────────────────────────────────────────────────────
# SECCIÓN 5 — POR SUCURSAL
# ─────────────────────────────────────────────────────────────────────

def _seccion_por_sucursal(pages_data, ctx, helpers):
    make_page   = helpers['new_page']
    fecha       = helpers['fecha']
    por_sucursal = ctx.get('por_sucursal') or []

    if not por_sucursal:
        return

    c, y, pg = make_page()
    y = _titulo_seccion(c, y, "5. Asistencia por Sucursal")
    y = _explicacion(c, y,
        "Distribucion de sesiones entre las diferentes sucursales del centro. "
        "Permite comparar el volumen y la calidad de la asistencia sede por sede.")

    headers = ["Sucursal", "Total", "Realizadas", "Retrasos", "Faltas", "Permisos", "Canceladas", "% Asistencia"]
    col_ws  = [4.0*cm, 1.4*cm, 2.1*cm,    1.8*cm,   1.5*cm,  1.8*cm,   2.2*cm,    2.3*cm]

    rows = []
    for s in por_sucursal:
        rows.append([
            s.get('nombre') or '—',
            str(_num(s.get('sesiones', 0))),
            str(_num(s.get('realizadas', 0))),
            str(_num(s.get('retrasos', 0))),
            str(_num(s.get('faltas', 0))),
            str(_num(s.get('permisos', 0))),
            str(_num(s.get('canceladas', 0))),
            _pct(s.get('tasa_asistencia', 0)),
        ])

    y = _tabla(c, y, headers, rows, col_ws)

    _pie(c, pg, helpers["total_pg"][0], fecha)
    pages_data.append(pg)


# ─────────────────────────────────────────────────────────────────────
# SECCIÓN 6 — RANKING DE PACIENTES
# ─────────────────────────────────────────────────────────────────────

def _seccion_ranking(pages_data, ctx, helpers):
    make_page        = helpers['new_page']
    fecha            = helpers['fecha']
    ranking          = ctx.get('ranking') or []
    peores           = ctx.get('peores_asistencia') or []

    if not ranking and not peores:
        return

    c, y, pg = make_page()
    y = _titulo_seccion(c, y, "6. Ranking de Asistencia por Paciente")
    y = _explicacion(c, y,
        "Solo se incluyen pacientes con al menos 3 sesiones en el periodo. "
        "La tasa de asistencia es: (realizadas + retrasos) / (realizadas + retrasos + faltas + permisos).")

    if ranking:
        y -= 0.2 * cm
        y = _titulo_seccion(c, y, "6.1 Mejores índices de asistencia (Top 15)", color=C_VERDE)
        headers = ["#", "Paciente", "Total", "Realizadas", "Retrasos", "Faltas", "Permisos", "% Asist.", "Desde"]
        col_ws  = [0.8*cm, 4.5*cm, 1.2*cm,   1.8*cm,      1.7*cm,    1.3*cm,  1.7*cm,     1.5*cm,    2.0*cm]
        rows = []
        for i, p in enumerate(ranking, 1):
            desde = p.get('desde')
            desde_str = desde.strftime('%d/%m/%Y') if desde else '—'
            rows.append([
                str(i),
                p.get('nombre_completo', '—'),
                str(_num(p.get('total', 0))),
                str(_num(p.get('realizadas', 0))),
                str(_num(p.get('retrasos', 0))),
                str(_num(p.get('faltas', 0))),
                str(_num(p.get('permisos', 0))),
                _pct(p.get('tasa', 0)),
                desde_str,
            ])
        y = _tabla(c, y, headers, rows, col_ws)

    if peores:
        if y < Y_BOTTOM + 4 * cm:
            _pie(c, pg, helpers["total_pg"][0], fecha)
            pages_data.append(pg)
            c, y, pg = make_page()

        y -= 0.3 * cm
        y = _titulo_seccion(c, y, "6.2 Pacientes con alta tasa de faltas (>20%)", color=C_ROJO)
        y = _explicacion(c, y,
            "Pacientes que requieren seguimiento por su alto ausentismo. "
            "Se muestran solo aquellos con al menos 3 sesiones y tasa de faltas superior al 20%.")
        headers2 = ["#", "Paciente", "Total", "Realizadas", "Faltas", "Permisos", "% Faltas"]
        col_ws2  = [0.8*cm, 5.5*cm, 1.4*cm,   2.0*cm,      1.5*cm,  1.8*cm,     2.1*cm]
        rows2 = []
        for i, p in enumerate(peores, 1):
            rows2.append([
                str(i),
                p.get('nombre_completo', '—'),
                str(_num(p.get('total', 0))),
                str(_num(p.get('realizadas', 0))),
                str(_num(p.get('faltas', 0))),
                str(_num(p.get('permisos', 0))),
                _pct(p.get('tasa_faltas', 0)),
            ])
        y = _tabla(c, y, headers2, rows2, col_ws2)

    _pie(c, pg, helpers["total_pg"][0], fecha)
    pages_data.append(pg)


# ─────────────────────────────────────────────────────────────────────
# SECCIÓN 7 — RETRASOS DETALLE
# ─────────────────────────────────────────────────────────────────────

def _seccion_retrasos(pages_data, ctx, helpers):
    make_page       = helpers['new_page']
    fecha           = helpers['fecha']
    retrasos_detalle = ctx.get('retrasos_detalle') or []

    if not retrasos_detalle:
        return

    c, y, pg = make_page()
    y = _titulo_seccion(c, y, "7. Pacientes con Retrasos Frecuentes")
    y = _explicacion(c, y,
        "Pacientes que llegaron con retraso en 2 o más sesiones durante el periodo. "
        "Se muestra el promedio de minutos de demora y la fecha de la última sesión "
        "con retraso registrada.")

    headers = ["Paciente", "Sesiones con retraso", "Prom. minutos demora", "Última fecha"]
    col_ws  = [6.5*cm, 3.5*cm,              4.0*cm,               3.5*cm]

    rows = []
    for r in retrasos_detalle:
        ultima = r.get('ultima_fecha')
        ultima_str = ultima.strftime('%d/%m/%Y') if ultima else '—'
        rows.append([
            r.get('nombre_completo', '—'),
            str(_num(r.get('sesiones_con_retraso', 0))),
            f"{_num(r.get('promedio_minutos', 0))} min",
            ultima_str,
        ])

    y = _tabla(c, y, headers, rows, col_ws)

    _pie(c, pg, helpers["total_pg"][0], fecha)
    pages_data.append(pg)


# ─────────────────────────────────────────────────────────────────────
# SECCIÓN 8 — REPROGRAMACIONES
# ─────────────────────────────────────────────────────────────────────

def _seccion_reprogramaciones(pages_data, ctx, helpers):
    make_page       = helpers['new_page']
    fecha           = helpers['fecha']
    reprogramaciones = list(ctx.get('reprogramaciones') or [])

    if not reprogramaciones:
        return

    c, y, pg = make_page()
    y = _titulo_seccion(c, y, "8. Sesiones Reprogramadas")
    y = _explicacion(c, y,
        "Listado de las últimas 20 sesiones que fueron reprogramadas en el periodo. "
        "Una sesión reprogramada es aquella cuya fecha fue modificada "
        "por el paciente o el profesional antes de su realización.")

    headers = ["Fecha", "Paciente", "Servicio", "Profesional", "Mensualidad/Proyecto"]
    col_ws  = [2.2*cm, 4.5*cm,  4.0*cm,  4.0*cm,      2.8*cm]

    rows = []
    for s in reprogramaciones:
        pac = getattr(s, 'paciente', None)
        pac_nombre = f"{getattr(pac,'nombre','')} {getattr(pac,'apellido','')}".strip() if pac else '—'
        svc = getattr(s, 'servicio', None)
        svc_nombre = getattr(svc, 'nombre', '—') if svc else '—'
        prof = getattr(s, 'profesional', None)
        prof_nombre = f"{getattr(prof,'nombre','')} {getattr(prof,'apellido','')}".strip() if prof else '—'
        mens = getattr(s, 'mensualidad', None)
        proy = getattr(s, 'proyecto', None)
        ref = getattr(mens, 'codigo', None) or getattr(proy, 'codigo', None) or '—'
        fecha_s = getattr(s, 'fecha', None)
        fecha_str = fecha_s.strftime('%d/%m/%Y') if fecha_s else '—'
        rows.append([fecha_str, pac_nombre, svc_nombre, prof_nombre, ref])

    y = _tabla(c, y, headers, rows, col_ws)

    _pie(c, pg, helpers["total_pg"][0], fecha)
    pages_data.append(pg)


# ─────────────────────────────────────────────────────────────────────
# SECCIÓN 9 — DETALLE DE TODAS LAS SESIONES (tabla completa)
# ─────────────────────────────────────────────────────────────────────

ESTADO_LABEL = {
    'realizada'        : 'Realizada',
    'realizada_retraso': 'Con retraso',
    'falta'            : 'Falta',
    'permiso'          : 'Permiso',
    'cancelada'        : 'Cancelada',
    'reprogramada'     : 'Reprogramada',
    'programada'       : 'Programada',
}

ESTADO_COLOR = {
    'realizada'        : colors.HexColor('#059669'),  # verde
    'realizada_retraso': colors.HexColor('#d97706'),  # amber
    'falta'            : colors.HexColor('#be123c'),  # rojo
    'permiso'          : colors.HexColor('#7c3aed'),  # morado
    'cancelada'        : colors.HexColor('#64748b'),  # gris
    'reprogramada'     : colors.HexColor('#0d9488'),  # teal
    'programada'       : colors.HexColor('#0284c7'),  # sky
}

# ── Constantes de layout para páginas landscape ──────────────────────
# Usamos A4 landscape (842 × 595 pt) para la tabla de detalle
from reportlab.lib.pagesizes import A4, landscape as _landscape

_LS_W, _LS_H = _landscape(A4)   # 841.89 × 595.28 pt
_LS_ML = 1.5 * cm
_LS_MR = 1.5 * cm
_LS_MT = 1.2 * cm
_LS_MB = 1.2 * cm
_LS_CW = _LS_W - _LS_ML - _LS_MR          # ≈ 24.67 cm
_LS_HEADER_H = 1.8 * cm
_LS_FOOTER_H = 0.7 * cm
_LS_Y_BOTTOM = _LS_MB + _LS_FOOTER_H + 0.2 * cm

# Anchos de columna landscape — suman exactamente _LS_CW
# Fecha  Hora   Paciente  Servicio  Profesional  Sucursal   Estado     Referencia
_LS_COL_WS = [2.0*cm, 1.4*cm, 5.2*cm, 4.4*cm, 4.8*cm, 3.2*cm, 2.2*cm, 2.0*cm]
# Suma: 2.0+1.4+5.2+4.4+4.8+3.2+2.2+2.0 = 25.2 cm (< _LS_CW ≈ 26.7 cm)


def _encabezado_landscape(c, pg, total_pg, titulo, periodo_txt, filtros_txt, fecha_emision):
    """Encabezado minimalista para páginas landscape del detalle."""
    # Banda superior
    _grad(c, 0, _LS_H - _LS_HEADER_H, _LS_W, _LS_HEADER_H, C_OSC, C_PRI)

    c.setFillColor(C_BLANCO)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(_LS_ML, _LS_H - 0.95 * cm, NOMBRE_CENTRO)
    c.setFont("Helvetica", 7)
    c.drawString(_LS_ML, _LS_H - 1.45 * cm, f"Periodo: {periodo_txt}")

    c.setFont("Helvetica-Bold", 8)
    c.drawRightString(_LS_W - _LS_MR, _LS_H - 0.95 * cm, titulo)
    c.setFont("Helvetica", 7)
    c.drawRightString(_LS_W - _LS_MR, _LS_H - 1.45 * cm, f"Pag. {pg} de {total_pg}  |  {fecha_emision}")

    return _LS_H - _LS_HEADER_H - 0.3 * cm


def _pie_landscape(c, pg, total_pg, fecha_emision):
    py = _LS_MB + 0.1 * cm
    c.setStrokeColor(C_GRIS_B)
    c.setLineWidth(0.3)
    c.line(_LS_ML, py + _LS_FOOTER_H - 0.1 * cm,
           _LS_W - _LS_MR, py + _LS_FOOTER_H - 0.1 * cm)
    c.setFont("Helvetica", 6)
    c.setFillColor(C_MUTED)
    c.drawString(_LS_ML, py + 0.22 * cm,
                 f"{NOMBRE_CENTRO}  |  Detalle de sesiones  |  CONFIDENCIAL")
    c.drawRightString(_LS_W - _LS_MR, py + 0.22 * cm, f"Pag. {pg} / {total_pg}")


def _seccion_detalle_sesiones(pages_data, ctx, helpers):
    """
    Genera la tabla completa de sesiones en páginas LANDSCAPE (A4 apaisado).
    Ajusta automáticamente columnas al ancho disponible.
    Incluye colores en la columna Estado para lectura rápida.
    """
    make_page   = helpers['new_page']
    fecha       = helpers['fecha']
    sesiones    = list(ctx.get('sesiones_qs') or [])
    periodo_txt = helpers.get('periodo_txt', '')
    filtros_txt = helpers.get('filtros_txt', '')

    if not sesiones:
        return

    total_ses = len(sesiones)
    titulo_ls = f"9. DETALLE COMPLETO DE SESIONES ({total_ses} registros)"

    # Verificar que columnas no superen CW landscape
    col_ws = list(_LS_COL_WS)
    total_col = sum(col_ws)
    if total_col > _LS_CW:
        # Reducir proporcionalmente la columna más ancha (paciente/profesional)
        exceso = total_col - _LS_CW
        col_ws[2] -= exceso * 0.5   # Paciente
        col_ws[4] -= exceso * 0.5   # Profesional
    total_w = sum(col_ws)

    headers = ["FECHA", "HORA", "PACIENTE", "SERVICIO", "PROFESIONAL",
               "SUCURSAL", "ESTADO", "REFERENCIA"]

    row_h    = 0.46 * cm
    fsize_h  = 6.5
    fsize_r  = 6.5

    def _dibujar_encabezado_tabla(c, y):
        """Dibuja la fila de encabezados de la tabla."""
        c.setFillColor(C_PRI)
        c.roundRect(_LS_ML, y - row_h, total_w, row_h, 3, fill=1, stroke=0)
        c.setStrokeColor(colors.HexColor('#3730a3'))
        c.setLineWidth(0.3)
        c.roundRect(_LS_ML, y - row_h, total_w, row_h, 3, fill=0, stroke=1)
        x_cur = _LS_ML
        for i, hdr in enumerate(headers):
            c.setFont("Helvetica-Bold", fsize_h)
            c.setFillColor(C_BLANCO)
            c.drawString(x_cur + 0.18 * cm, y - row_h + 0.14 * cm, hdr)
            x_cur += col_ws[i]
        return y - row_h

    # ── Primera página landscape ──────────────────────────────────────
    # Nota: la canvas principal es letter portrait. Para las páginas
    # landscape llamamos showPage + setPageSize en la misma canvas.
    # Esto es compatible con ReportLab canvas multi-page.
    make_page_fn = helpers['new_page']

    # Forzamos una nueva página y cambiamos tamaño
    # Obtenemos la canvas desde el closure de make_page_fn
    # helpers['canvas'] es la referencia guardada en generar_informe_asistencia_pdf
    cv = helpers['canvas']

    total_pg = helpers['total_pg']   # lista [N] — en pasada 1 = [999], en pasada 2 = [total_real]

    def _nueva_pagina_ls(pg_ref):
        pg_ref[0] += 1
        pg = pg_ref[0]
        cv.showPage()
        cv.setPageSize(_landscape(A4))
        cv.setFillColor(C_FONDO_PAG)
        cv.rect(0, 0, _LS_W, _LS_H, fill=1, stroke=0)
        y = _encabezado_landscape(cv, pg, total_pg[0], titulo_ls, periodo_txt, filtros_txt, fecha)
        return cv, y, pg

    pg_ls = [helpers['page_counter'][0]]
    cv, y, pg = _nueva_pagina_ls(pg_ls)
    helpers['page_counter'][0] = pg_ls[0]

    y = _dibujar_encabezado_tabla(cv, y)

    for r_idx, s in enumerate(sesiones):
        # ── Salto de página ───────────────────────────────────────────
        if y < _LS_Y_BOTTOM + row_h:
            _pie_landscape(cv, pg, total_pg[0], fecha)
            pages_data.append(pg)
            pg_ls[0] = pg
            cv, y, pg = _nueva_pagina_ls(pg_ls)
            helpers['page_counter'][0] = pg_ls[0]
            y = _dibujar_encabezado_tabla(cv, y)

        # ── Franja alternada ──────────────────────────────────────────
        if r_idx % 2 == 0:
            cv.setFillColor(C_GRIS_T)
            cv.rect(_LS_ML, y - row_h, total_w, row_h, fill=1, stroke=0)

        cv.setStrokeColor(C_GRIS_B)
        cv.setLineWidth(0.12)
        cv.line(_LS_ML, y - row_h, _LS_ML + total_w, y - row_h)

        # ── Datos ─────────────────────────────────────────────────────
        pac    = getattr(s, 'paciente', None)
        svc    = getattr(s, 'servicio', None)
        prof   = getattr(s, 'profesional', None)
        suc    = getattr(s, 'sucursal', None)
        mens   = getattr(s, 'mensualidad', None)
        proy   = getattr(s, 'proyecto', None)
        estado = getattr(s, 'estado', '')
        fecha_s = getattr(s, 'fecha', None)
        hora_s  = getattr(s, 'hora_inicio', None)

        fecha_str = fecha_s.strftime('%d/%m/%Y') if fecha_s else '—'
        hora_str  = hora_s.strftime('%H:%M')     if hora_s  else '—'
        pac_str   = (f"{getattr(pac,'nombre','')} {getattr(pac,'apellido','')}").strip() or '—'
        svc_str   = getattr(svc,  'nombre', '—') or '—'
        prof_str  = (f"{getattr(prof,'nombre','')} {getattr(prof,'apellido','')}").strip() or '—'
        suc_str   = getattr(suc,  'nombre', '—') or '—'
        est_str   = ESTADO_LABEL.get(estado, estado)
        ref_str   = getattr(mens, 'codigo', None) or getattr(proy, 'codigo', None) or '—'

        celdas    = [fecha_str, hora_str, pac_str, svc_str, prof_str, suc_str, est_str, ref_str]
        est_color = ESTADO_COLOR.get(estado, C_TEXTO)

        x_cur = _LS_ML
        for c_idx, celda in enumerate(celdas):
            is_estado = (c_idx == 6)
            fcolor    = est_color if is_estado else C_TEXTO
            font      = "Helvetica-Bold" if is_estado else "Helvetica"
            cv.setFont(font, fsize_r)
            cv.setFillColor(fcolor)
            txt = str(celda)
            max_w_c = col_ws[c_idx] - 0.35 * cm
            while stringWidth(txt, font, fsize_r) > max_w_c and len(txt) > 1:
                txt = txt[:-2] + '.'
            cv.drawString(x_cur + 0.18 * cm, y - row_h + 0.12 * cm, txt)
            x_cur += col_ws[c_idx]

        y -= row_h

    # ── Cierre de tabla ───────────────────────────────────────────────
    cv.setStrokeColor(C_GRIS_B)
    cv.setLineWidth(0.4)
    cv.line(_LS_ML, y, _LS_ML + total_w, y)

    _pie_landscape(cv, pg, total_pg[0], fecha)
    pages_data.append(pg)

    helpers['page_counter'][0] = pg


# ─────────────────────────────────────────────────────────────────────
# FUNCIÓN PRINCIPAL
# ─────────────────────────────────────────────────────────────────────

def generar_informe_asistencia_pdf(context):
    """
    Genera el informe de asistencia en PDF a partir del contexto
    que devuelve la vista reporte_asistencia.
    Retorna un BytesIO listo para servir como HttpResponse.
    """
    fecha_desde_str = str(context.get('fecha_desde', ''))
    fecha_hasta_str = str(context.get('fecha_hasta', ''))
    tipo            = context.get('tipo', 'general')
    entidad         = context.get('entidad')
    sucursal_filtro = context.get('sucursal_filtro', '')

    # Período legible
    if fecha_desde_str and fecha_hasta_str:
        if fecha_desde_str == fecha_hasta_str:
            try:
                from datetime import datetime
                fd = datetime.strptime(fecha_desde_str, '%Y-%m-%d').date()
                periodo_txt = (fd.strftime('%d de ') +
                               MESES_FULL[fd.month] +
                               fd.strftime(' de %Y'))
            except Exception:
                periodo_txt = fecha_desde_str
        else:
            periodo_txt = f"{fecha_desde_str}  al  {fecha_hasta_str}"
    else:
        periodo_txt = 'Periodo no especificado'

    # Texto de filtros activos para el encabezado
    filtros_partes = []
    if tipo and tipo != 'general':
        tipo_label = {'paciente': 'Paciente', 'profesional': 'Profesional',
                      'servicio': 'Servicio', 'sucursal': 'Sucursal'}.get(tipo, tipo)
        if entidad:
            nombre_ent = str(entidad)
            filtros_partes.append(f"{tipo_label}: {nombre_ent}")
        else:
            filtros_partes.append(f"Tipo: {tipo_label}")

    if sucursal_filtro:
        try:
            from servicios.models import Sucursal
            suc = Sucursal.objects.filter(id=sucursal_filtro).first()
            if suc:
                filtros_partes.append(f"Sucursal: {suc.nombre}")
        except Exception:
            pass

    mens_id = context.get('mensualidad_id', '')
    proy_id = context.get('proyecto_id', '')
    if mens_id:
        filtros_partes.append(f"Mensualidad ID: {mens_id}")
    if proy_id:
        filtros_partes.append(f"Proyecto ID: {proy_id}")

    filtros_txt = "  |  ".join(filtros_partes) if filtros_partes else ""

    titulo = "INFORME DE ASISTENCIA"
    fecha_emision = _date_cls.today().strftime('%d/%m/%Y')

    # ── Primera pasada (para contar páginas) ────────────────────────
    buffer = BytesIO()
    c = pdf_canvas.Canvas(buffer, pagesize=letter)
    c.setTitle(f"{titulo} - {periodo_txt}")
    c.setAuthor(NOMBRE_CENTRO)
    c.setSubject("Informe de Asistencia Confidencial")

    page_counter = [1]

    def make_page():
        page_counter[0] += 1
        pg = page_counter[0]
        c.setFillColor(C_FONDO_PAG)
        c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
        y = _encabezado(c, pg, 999, titulo, periodo_txt, filtros_txt, fecha_emision)
        return c, y, pg

    def make_page_w():
        c.showPage()
        return make_page()

    _total_pg_placeholder = [999]   # placeholder — pasada 1

    helpers = {
        'new_page'    : make_page_w,
        'fecha'       : fecha_emision,
        'canvas'      : c,
        'page_counter': page_counter,
        'periodo_txt' : periodo_txt,
        'filtros_txt' : filtros_txt,
        'total_pg'    : _total_pg_placeholder,
    }
    pages_data = []

    # Portada (página 1)
    c.setFillColor(C_FONDO_PAG)
    c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    _portada(c, titulo, periodo_txt, filtros_txt, fecha_emision, context)
    pages_data.append(1)

    # Secciones de contenido
    _seccion_stats(pages_data, context, helpers, page_counter)
    _seccion_por_dia(pages_data, context, helpers)
    _seccion_por_servicio(pages_data, context, helpers)
    _seccion_por_profesional(pages_data, context, helpers)
    _seccion_por_sucursal(pages_data, context, helpers)
    _seccion_ranking(pages_data, context, helpers)
    _seccion_retrasos(pages_data, context, helpers)
    _seccion_reprogramaciones(pages_data, context, helpers)
    _seccion_detalle_sesiones(pages_data, context, helpers)

    total_pages = page_counter[0]
    c.save()

    # ── Segunda pasada: imprimir con total_pages correcto ────────────
    buffer2 = BytesIO()
    c2 = pdf_canvas.Canvas(buffer2, pagesize=letter)
    c2.setTitle(f"{titulo} - {periodo_txt}")
    c2.setAuthor(NOMBRE_CENTRO)

    pg2 = [1]

    def make_page2():
        pg2[0] += 1
        pg = pg2[0]
        c2.setFillColor(C_FONDO_PAG)
        c2.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
        y = _encabezado(c2, pg, total_pages, titulo, periodo_txt, filtros_txt, fecha_emision)
        return c2, y, pg

    def make_page2_w():
        c2.showPage()
        return make_page2()

    helpers2 = {
        'new_page'    : make_page2_w,
        'fecha'       : fecha_emision,
        'canvas'      : c2,
        'page_counter': pg2,
        'periodo_txt' : periodo_txt,
        'filtros_txt' : filtros_txt,
        'total_pg'    : [total_pages],   # ← valor real para pie de página
    }
    pages_data2 = []

    c2.setFillColor(C_FONDO_PAG)
    c2.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    _portada(c2, titulo, periodo_txt, filtros_txt, fecha_emision, context)
    _pie(c2, 1, total_pages, fecha_emision)
    pages_data2.append(1)

    _seccion_stats(pages_data2, context, helpers2, pg2)
    _seccion_por_dia(pages_data2, context, helpers2)
    _seccion_por_servicio(pages_data2, context, helpers2)
    _seccion_por_profesional(pages_data2, context, helpers2)
    _seccion_por_sucursal(pages_data2, context, helpers2)
    _seccion_ranking(pages_data2, context, helpers2)
    _seccion_retrasos(pages_data2, context, helpers2)
    _seccion_reprogramaciones(pages_data2, context, helpers2)
    _seccion_detalle_sesiones(pages_data2, context, helpers2)

    c2.save()
    buffer2.seek(0)
    return buffer2