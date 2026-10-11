# facturacion/informe_asistencia_graficos.py
# =====================================================================
# GRÁFICAS PARA EL PDF DE ASISTENCIA (dibujadas con reportlab, sin imágenes)
# Cada función recibe el canvas y la esquina SUPERIOR izquierda (x, y_top) + ancho,
# y devuelve la altura usada. Misma paleta y umbrales que la pantalla.
# =====================================================================
import math

from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.pdfbase.pdfmetrics import stringWidth

OBJETIVO, MINIMO = 85.0, 70.0

HEX = {
    'verde': '#059669', 'ambar': '#d97706', 'rojo': '#be123c', 'gris': '#94a3b8', 'azul': '#2563eb',
    'violeta': '#7c3aed', 'teal': '#0d9488', 'slate': '#64748b', 'ink': '#0f172a', 'txt': '#334155',
    'muted': '#64748b', 'linea': '#e2e8f0', 'card': '#ffffff', 'fondo_t': '#f1f5f9',
}


def _c(k):
    return colors.HexColor(HEX.get(k, k))


def _col_asis(v, base=99):
    if base < 10:
        return _c('gris')
    return _c('verde') if v >= OBJETIVO else (_c('ambar') if v >= MINIMO else _c('rojo'))


def _recorta(c, txt, font, size, ancho):
    txt = str(txt)
    if stringWidth(txt, font, size) <= ancho:
        return txt
    while txt and stringWidth(txt + '…', font, size) > ancho:
        txt = txt[:-1]
    return txt + '…'


def _tarjeta(c, x, y, w, h, titulo, sub=None):
    """Fondo blanco con borde y título. Devuelve (x0, y_top_interior)."""
    c.setFillColor(_c('card'))
    c.setStrokeColor(_c('linea'))
    c.setLineWidth(0.7)
    c.roundRect(x, y - h, w, h, 7, fill=1, stroke=1)
    c.setFillColor(_c('ink'))
    c.setFont('Helvetica-Bold', 9)
    c.drawString(x + 0.45 * cm, y - 0.65 * cm, titulo)
    yy = y - 0.65 * cm
    if sub:
        c.setFont('Helvetica-Oblique', 6.6)
        c.setFillColor(_c('muted'))
        yy -= 0.38 * cm
        c.drawString(x + 0.45 * cm, yy, _recorta(c, sub, 'Helvetica-Oblique', 6.6, w - 0.9 * cm))
    return yy - 0.25 * cm


# ─────────────────────────────────────────────────────────────────────
def graf_barras(c, x, y, w, h, puntos, titulo, sub=None, prev=None, lineas_ref=True):
    """Barras verticales de % de asistencia 0-100 con cuadrícula, bandas objetivo/mínimo y valores.
    puntos: [{'label', 'asistencia', 'base'}]."""
    y_in = _tarjeta(c, x, y, w, h, titulo, sub)
    n = len(puntos)
    if not n:
        c.setFont('Helvetica', 8)
        c.setFillColor(_c('muted'))
        c.drawString(x + 0.5 * cm, y - h / 2, 'Sin datos en el período.')
        return h
    ml, mr, mb = 1.0 * cm, 0.5 * cm, 1.3 * cm
    px, pw = x + ml, w - ml - mr
    p_top, p_bot = y_in - 0.15 * cm, y - h + mb
    ph = p_top - p_bot
    Y = lambda v: p_bot + ph * max(0.0, min(v, 100.0)) / 100.0

    # bandas
    c.setFillColor(colors.Color(0.02, 0.59, 0.41, alpha=0.07))
    c.rect(px, Y(OBJETIVO), pw, Y(100) - Y(OBJETIVO), stroke=0, fill=1)
    c.setFillColor(colors.Color(0.75, 0.07, 0.24, alpha=0.06))
    c.rect(px, p_bot, pw, Y(MINIMO) - p_bot, stroke=0, fill=1)
    # cuadrícula + eje
    c.setLineWidth(0.4)
    for v in (0, 25, 50, 75, 100):
        c.setStrokeColor(_c('linea'))
        c.line(px, Y(v), px + pw, Y(v))
        c.setFillColor(_c('muted'))
        c.setFont('Helvetica', 6.3)
        c.drawRightString(px - 0.15 * cm, Y(v) - 2, f'{v}%')
    if lineas_ref:
        for v, k, lab in ((OBJETIVO, 'verde', f'Objetivo {OBJETIVO:.0f}%'), (MINIMO, 'rojo', f'Mínimo {MINIMO:.0f}%')):
            c.setStrokeColor(_c(k))
            c.setLineWidth(0.8)
            c.setDash(3, 2)
            c.line(px, Y(v), px + pw, Y(v))
            c.setDash()

    slot = pw / n
    bw = max(3.0, min(1.05 * cm, slot * 0.64))
    paso = 1 if n <= 14 else (2 if n <= 28 else 4)
    for i, pt in enumerate(puntos):
        cx = px + slot * (i + 0.5)
        if pt.get('base', 1) > 0:
            v = pt['asistencia']
            c.setFillColor(_col_asis(v))
            hh = max(Y(v) - p_bot, 1.2)
            r = min(2.4, bw / 2, hh)
            c.roundRect(cx - bw / 2, p_bot, bw, hh, r, stroke=0, fill=1)
            c.rect(cx - bw / 2, p_bot, bw, min(hh, r + 0.5), stroke=0, fill=1)  # base recta
            if n <= 26 or i % paso == 0:
                c.setFillColor(_c('ink'))
                c.setFont('Helvetica-Bold', 6.6 if n <= 16 else 5.8)
                c.drawCentredString(cx, Y(v) + 2.2, f'{v:.0f}')
        if i % paso == 0:
            c.setFillColor(_c('txt'))
            c.setFont('Helvetica', 6.4 if n <= 16 else 5.6)
            c.drawCentredString(cx, p_bot - 0.36 * cm, str(pt['label']))
    if prev:
        c.setStrokeColor(_c('azul'))
        c.setLineWidth(1.1)
        c.setDash(1.5, 2)
        c.line(px, Y(prev), px + pw, Y(prev))
        c.setDash()
    if lineas_ref:
        # leyenda de líneas, bajo el eje X
        items = [('verde', f'Objetivo {OBJETIVO:.0f}%', (3, 2)), ('rojo', f'Mínimo {MINIMO:.0f}%', (3, 2))]
        if prev:
            items.append(('azul', f'Período anterior {prev:.1f}%', (1.5, 2)))
        total_w = sum(22 + stringWidth(t, 'Helvetica', 6.2) + 14 for _k, t, _d in items) - 14
        lx = x + (w - total_w) / 2
        ly = y - h + 0.28 * cm
        for k, t, d in items:
            c.setStrokeColor(_c(k))
            c.setLineWidth(1.1)
            c.setDash(*d)
            c.line(lx, ly + 2, lx + 18, ly + 2)
            c.setDash()
            c.setFillColor(_c('txt'))
            c.setFont('Helvetica', 6.2)
            c.drawString(lx + 22, ly, t)
            lx += 22 + stringWidth(t, 'Helvetica', 6.2) + 14
    return h


# ─────────────────────────────────────────────────────────────────────
def graf_dona(c, x, y, w, h, partes, titulo, sub=None):
    """Dona de estados. partes: [(etiqueta, valor, '#hex')]."""
    y_in = _tarjeta(c, x, y, w, h, titulo, sub)
    partes = [p for p in partes if p[1] > 0]
    total = sum(p[1] for p in partes)
    if not total:
        c.setFont('Helvetica', 8)
        c.setFillColor(_c('muted'))
        c.drawString(x + 0.5 * cm, y - h / 2, 'Sin datos en el período.')
        return h
    r = min((y_in - (y - h)) / 2 - 0.15 * cm, w * 0.17)
    cx, cy = x + 0.5 * cm + r, (y_in + (y - h)) / 2 - 0.05 * cm
    ang = 90.0
    c.setLineWidth(0.8)
    for _lab, val, col in partes:
        ext = -360.0 * val / total
        c.setFillColor(colors.HexColor(col))
        c.setStrokeColor(colors.white)
        c.wedge(cx - r, cy - r, cx + r, cy + r, ang, ext, stroke=1, fill=1)
        ang += ext
    c.setFillColor(_c('card'))
    c.setStrokeColor(_c('card'))
    c.circle(cx, cy, r * 0.58, stroke=0, fill=1)
    c.setFillColor(_c('ink'))
    c.setFont('Helvetica-Bold', 12)
    c.drawCentredString(cx, cy - 1, f'{int(total):,}'.replace(',', '.'))
    c.setFont('Helvetica', 6)
    c.setFillColor(_c('muted'))
    c.drawCentredString(cx, cy - 9, 'sesiones')
    # leyenda
    lx = cx + r + 0.55 * cm
    ly = cy + (len(partes) * 0.46 * cm) / 2 - 0.1 * cm
    for lab, val, col in partes:
        c.setFillColor(colors.HexColor(col))
        c.roundRect(lx, ly - 2, 6, 6, 1.5, stroke=0, fill=1)
        c.setFillColor(_c('txt'))
        c.setFont('Helvetica', 7)
        vtxt = f'{int(val)} ({100 * val / total:.0f}%)'
        vw = stringWidth(vtxt, 'Helvetica-Bold', 7)
        c.drawString(lx + 10, ly, _recorta(c, lab, 'Helvetica', 7, (x + w - 0.45 * cm) - (lx + 10) - vw - 6))
        c.setFont('Helvetica-Bold', 7)
        c.setFillColor(_c('ink'))
        c.drawRightString(x + w - 0.45 * cm, ly, vtxt)
        ly -= 0.46 * cm
    return h


# ─────────────────────────────────────────────────────────────────────
def alto_barras_h(n):
    return 1.7 * cm + n * 0.52 * cm + 0.5 * cm


def graf_barras_h(c, x, y, w, items, titulo, sub=None):
    """Barras horizontales de asistencia con líneas de objetivo y mínimo.
    items: [{'nombre', 'valor', 'base', 'extra', 'sel'}]  (ordenadas como se quiere ver)."""
    h = alto_barras_h(len(items))
    y_in = _tarjeta(c, x, y, w, h, titulo, sub)
    lab_w = 3.9 * cm
    ext_w = 3.7 * cm
    bx, bw = x + 0.45 * cm + lab_w, w - 0.9 * cm - lab_w - ext_w
    X = lambda v: bx + bw * max(0.0, min(v, 100.0)) / 100.0
    top = y_in - 0.1 * cm
    bottom = y - h + 0.35 * cm
    yy = top - 0.35 * cm
    for it in items:
        if it.get('sel'):
            c.setFillColor(colors.HexColor('#e0e7ff'))
            c.roundRect(x + 0.25 * cm, yy - 0.2 * cm, w - 0.5 * cm, 0.46 * cm, 3, stroke=0, fill=1)
        c.setFillColor(_c('ink'))
        c.setFont('Helvetica-Bold' if it.get('sel') else 'Helvetica', 7)
        c.drawString(x + 0.45 * cm, yy - 0.02 * cm, _recorta(c, it['nombre'], 'Helvetica', 7, lab_w - 0.2 * cm))
        c.setFillColor(_c('fondo_t'))
        c.roundRect(bx, yy - 0.12 * cm, bw, 0.3 * cm, 2.5, stroke=0, fill=1)
        if it['base'] > 0:
            c.setFillColor(_col_asis(it['valor'], it['base']))
            c.roundRect(bx, yy - 0.12 * cm, max(X(it['valor']) - bx, 2), 0.3 * cm, 2.5, stroke=0, fill=1)
        c.setFillColor(_c('ink'))
        c.setFont('Helvetica-Bold', 7)
        c.drawString(bx + bw + 0.2 * cm, yy - 0.02 * cm, f"{it['valor']:.1f}%")
        c.setFont('Helvetica', 6)
        c.setFillColor(_c('muted'))
        c.drawString(bx + bw + 1.3 * cm, yy - 0.02 * cm, _recorta(c, it.get('extra', ''), 'Helvetica', 6, ext_w - 1.25 * cm))
        yy -= 0.52 * cm
    # guías
    for v, k, lab in ((MINIMO, 'rojo', f'{MINIMO:.0f}%'), (OBJETIVO, 'verde', f'{OBJETIVO:.0f}%')):
        c.setStrokeColor(_c(k))
        c.setLineWidth(0.7)
        c.setDash(3, 2)
        c.line(X(v), top, X(v), bottom + 0.1 * cm)
        c.setDash()
        c.setFillColor(_c(k))
        c.setFont('Helvetica-Bold', 5.8)
        c.drawCentredString(X(v), bottom - 0.12 * cm, lab)
    return h


# ─────────────────────────────────────────────────────────────────────
def graf_calor(c, x, y, w, calor, titulo, sub=None):
    """Mapa de calor día × hora con % de inasistencia por celda."""
    horas, filas = calor['horas'], calor['filas']
    nh = max(len(horas), 1)
    cell_h = 0.5 * cm
    h = 1.55 * cm + 7 * cell_h + 0.75 * cm
    y_in = _tarjeta(c, x, y, w, h, titulo, sub)
    lab_w = 1.1 * cm
    gx = x + 0.45 * cm + lab_w
    cw = (w - 0.9 * cm - lab_w) / nh
    cw = min(cw, 2.4 * cm)
    yy = y_in - 0.15 * cm
    c.setFont('Helvetica-Bold', 6.2)
    c.setFillColor(_c('muted'))
    for j, hh in enumerate(horas):
        c.drawCentredString(gx + cw * (j + 0.5), yy - 0.1 * cm, hh)
    yy -= 0.28 * cm
    for f in filas:
        c.setFont('Helvetica-Bold', 6.6)
        c.setFillColor(_c('txt'))
        c.drawRightString(gx - 0.2 * cm, yy - cell_h + 0.17 * cm, f['dia'])
        for j, cel in enumerate(f['celdas']):
            bg = cel['bg'] if cel else '#f8fafc'
            c.setFillColor(colors.HexColor(bg))
            c.roundRect(gx + cw * j + 1, yy - cell_h + 1, cw - 2, cell_h - 2, 2.5, stroke=0, fill=1)
            if cel:
                c.setFillColor(_c('ink'))
                c.setFont('Helvetica-Bold', 6.2)
                c.drawCentredString(gx + cw * (j + 0.5), yy - cell_h + 0.17 * cm, f"{cel['inas']:.0f}%")
        yy -= cell_h
    # leyenda
    lx = gx
    ly = y - h + 0.35 * cm
    for lab, col in (('<10%', '#bbf7d0'), ('10-20%', '#fef08a'), ('20-35%', '#fdba74'), ('≥35%', '#fca5a5'), ('<3 sesiones', '#f1f5f9')):
        c.setFillColor(colors.HexColor(col))
        c.roundRect(lx, ly - 1, 8, 6, 1.5, stroke=0, fill=1)
        c.setFillColor(_c('txt'))
        c.setFont('Helvetica', 6)
        t = lab.replace('≥', '>=')
        c.drawString(lx + 11, ly, t)
        lx += 11 + stringWidth(t, 'Helvetica', 6) + 14
    return h


# ─────────────────────────────────────────────────────────────────────
def graf_apilada(c, x, y, w, partes, titulo, sub=None, nota=None):
    """Barra horizontal apilada. partes: [(etiqueta, valor, '#hex', texto_valor)]."""
    h = 3.15 * cm + (0.4 * cm if nota else 0)
    y_in = _tarjeta(c, x, y, w, h, titulo, sub)
    total = sum(p[1] for p in partes if p[1] > 0)
    bx, bw = x + 0.45 * cm, w - 0.9 * cm
    by = y_in - 0.5 * cm
    if not total:
        c.setFont('Helvetica', 8)
        c.setFillColor(_c('muted'))
        c.drawString(bx, by, 'Sin datos en el período.')
        return h
    cx = bx
    for lab, val, col, _t in partes:
        if val <= 0:
            continue
        sw = bw * val / total
        c.setFillColor(colors.HexColor(col))
        c.rect(cx, by - 0.2 * cm, sw, 0.55 * cm, stroke=0, fill=1)
        if sw > 1.0 * cm:
            c.setFillColor(colors.white)
            c.setFont('Helvetica-Bold', 6.4)
            c.drawCentredString(cx + sw / 2, by - 0.03 * cm, f'{100 * val / total:.0f}%')
        cx += sw
    ly = by - 0.85 * cm
    colw = bw / 2
    for i, (lab, val, col, tv) in enumerate(partes):
        lx = bx + (i % 2) * colw
        if i and i % 2 == 0:
            ly -= 0.42 * cm
        c.setFillColor(colors.HexColor(col))
        c.roundRect(lx, ly - 2, 6, 6, 1.5, stroke=0, fill=1)
        c.setFillColor(_c('txt'))
        c.setFont('Helvetica', 6.8)
        c.drawString(lx + 10, ly, lab)
        c.setFont('Helvetica-Bold', 6.8)
        c.setFillColor(_c('ink'))
        c.drawRightString(lx + colw - 0.4 * cm, ly, tv)
    if nota:
        c.setFont('Helvetica-Oblique', 6.2)
        c.setFillColor(_c('muted'))
        c.drawString(bx, y - h + 0.3 * cm, _recorta(c, nota, 'Helvetica-Oblique', 6.2, bw))
    return h
