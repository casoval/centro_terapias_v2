# facturacion/informe_financiero_graficos.py
# =====================================================================
# GRÁFICAS EN BOLIVIANOS PARA EL PDF FINANCIERO (reportlab, sin imágenes).
# Cada función recibe el canvas y la esquina SUPERIOR izquierda (x, y_top) + ancho,
# dibuja una «tarjeta» y devuelve la altura usada. Solo caracteres de Helvetica estándar.
# =====================================================================
import math

from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.pdfbase.pdfmetrics import stringWidth

HEX = {'ink': '#0f172a', 'txt': '#334155', 'muted': '#64748b', 'linea': '#e2e8f0', 'card': '#ffffff', 'fondo': '#f1f5f9',
       'gen': '#6366f1', 'cob': '#059669', 'egr': '#dc2626', 'res': '#0f172a'}


def _c(k):
    return colors.HexColor(HEX.get(k, k))


def abrev(v):
    a = abs(v)
    s = f"{a / 1000:.0f}k" if a >= 10000 else (f"{a / 1000:.1f}k".replace('.0k', 'k') if a >= 1000 else f"{a:.0f}")
    return ('-' if v < 0 else '') + s


def bs0(v):
    return 'Bs. ' + f"{v:,.0f}".replace(',', '.')


def _recorta(txt, font, size, ancho):
    txt = str(txt)
    if stringWidth(txt, font, size) <= ancho:
        return txt
    while txt and stringWidth(txt + '...', font, size) > ancho:
        txt = txt[:-1]
    return txt + '...'


def _tarjeta(c, x, y, w, h, titulo, sub=None):
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
        c.drawString(x + 0.45 * cm, yy, _recorta(sub, 'Helvetica-Oblique', 6.6, w - 0.9 * cm))
    return yy - 0.25 * cm


def _paso(rango, n=5):
    if rango <= 0:
        return 1
    crudo = rango / n
    mag = 10 ** math.floor(math.log10(crudo))
    for m in (1, 2, 2.5, 5, 10):
        if crudo <= m * mag:
            return m * mag
    return 10 * mag


# ─────────────────────────────────────────────────────────────────────
def graf_flujo(c, x, y, w, h, serie, titulo, sub=None):
    """Barras agrupadas por mes (generado, cobrado, egresos) + línea de resultado."""
    y_in = _tarjeta(c, x, y, w, h, titulo, sub)
    if not serie:
        return h
    ml, mr, mb = 1.15 * cm, 0.4 * cm, 1.5 * cm
    px, pw = x + ml, w - ml - mr
    p_top, p_bot = y_in - 0.1 * cm, y - h + mb
    vmax = max([max(p['generado'], p['cobrado'], p['egresos']) for p in serie] + [1])
    vmin = min([0] + [p['resultado'] for p in serie])
    paso = _paso(vmax - vmin)
    top = math.ceil(vmax / paso) * paso
    bot = math.floor(vmin / paso) * paso if vmin < 0 else 0
    Y = lambda v: p_bot + (p_top - p_bot) * (v - bot) / (top - bot)
    v = bot
    while v <= top + 1e-6:
        c.setStrokeColor(colors.HexColor('#94a3b8') if abs(v) < 1e-6 else _c('linea'))
        c.setLineWidth(0.7 if abs(v) < 1e-6 else 0.4)
        c.line(px, Y(v), px + pw, Y(v))
        c.setFillColor(_c('muted'))
        c.setFont('Helvetica', 6.2)
        c.drawRightString(px - 0.15 * cm, Y(v) - 2, abrev(v))
        v += paso
    n = len(serie)
    slot = pw / n
    bw = max(2.5, min(0.42 * cm, slot * 0.25))
    pts = []
    for i, p in enumerate(serie):
        cx = px + slot * (i + 0.5)
        for j, (k, col) in enumerate((('generado', 'gen'), ('cobrado', 'cob'), ('egresos', 'egr'))):
            bx = cx + (j - 1) * (bw + 1) - bw / 2
            y0, y1 = Y(0), Y(p[k])
            c.setFillColor(_c(col))
            c.roundRect(bx, min(y0, y1), bw, max(abs(y1 - y0), 0.8), 1.3, stroke=0, fill=1)
        pts.append((cx, Y(p['resultado']), p))
        c.setFillColor(_c('txt'))
        c.setFont('Helvetica', 5.8)
        c.drawCentredString(cx, p_bot - 0.36 * cm, p['label'])
    c.setStrokeColor(_c('res'))
    c.setLineWidth(1.3)
    pth = c.beginPath()
    for i, (cx, cy, _p) in enumerate(pts):
        (pth.moveTo if i == 0 else pth.lineTo)(cx, cy)
    c.drawPath(pth, stroke=1, fill=0)
    for cx, cy, p in pts:
        c.setFillColor(_c('cob') if p['resultado'] >= 0 else _c('egr'))
        c.setStrokeColor(colors.white)
        c.setLineWidth(0.8)
        c.circle(cx, cy, 1.9, stroke=1, fill=1)
    # leyenda
    items = [('Generado', 'gen', 0), ('Cobrado (neto)', 'cob', 0), ('Egresos', 'egr', 0), ('Resultado (cobrado - egresos)', 'res', 1)]
    tw = sum(14 + stringWidth(t, 'Helvetica', 6.4) + 14 for t, _k, _l in items) - 14
    lx = x + (w - tw) / 2
    ly = y - h + 0.3 * cm
    for t, k, ln in items:
        c.setFillColor(_c(k))
        c.setStrokeColor(_c(k))
        if ln:
            c.setLineWidth(1.3)
            c.line(lx, ly + 2, lx + 11, ly + 2)
            c.circle(lx + 5.5, ly + 2, 1.7, stroke=0, fill=1)
        else:
            c.roundRect(lx, ly - 0.5, 7, 6, 1.5, stroke=0, fill=1)
        c.setFillColor(_c('txt'))
        c.setFont('Helvetica', 6.4)
        c.drawString(lx + 13, ly, t)
        lx += 14 + stringWidth(t, 'Helvetica', 6.4) + 14
    return h


# ─────────────────────────────────────────────────────────────────────
def graf_dona(c, x, y, w, h, partes, titulo, sub=None, centro=None):
    """partes: [(etiqueta, valor, '#hex')]; muestra montos en Bs. y % en la leyenda."""
    y_in = _tarjeta(c, x, y, w, h, titulo, sub)
    partes = [p for p in partes if p[1] > 0]
    tot = sum(p[1] for p in partes)
    if not tot:
        c.setFont('Helvetica', 8)
        c.setFillColor(_c('muted'))
        c.drawString(x + 0.5 * cm, y - h / 2, 'Sin datos en el periodo.')
        return h
    r = min((y_in - (y - h)) / 2 - 0.15 * cm, w * 0.17)
    cx, cy = x + 0.5 * cm + r, (y_in + (y - h)) / 2 - 0.05 * cm
    ang = 90.0
    c.setLineWidth(0.8)
    for _l, v, col in partes:
        ext = -360.0 * v / tot
        c.setFillColor(colors.HexColor(col))
        c.setStrokeColor(colors.white)
        c.wedge(cx - r, cy - r, cx + r, cy + r, ang, ext, stroke=1, fill=1)
        ang += ext
    c.setFillColor(_c('card'))
    c.circle(cx, cy, r * 0.58, stroke=0, fill=1)
    c.setFillColor(_c('ink'))
    c.setFont('Helvetica-Bold', 10)
    c.drawCentredString(cx, cy - 1, centro or abrev(tot))
    lx = cx + r + 0.5 * cm
    ly = cy + (len(partes) * 0.5 * cm) / 2 - 0.1 * cm
    for lab, v, col in partes:
        c.setFillColor(colors.HexColor(col))
        c.roundRect(lx, ly - 2, 6, 6, 1.5, stroke=0, fill=1)
        vt = f"{bs0(v)} ({100 * v / tot:.0f}%)"
        vw = stringWidth(vt, 'Helvetica-Bold', 6.8)
        c.setFillColor(_c('txt'))
        c.setFont('Helvetica', 6.8)
        c.drawString(lx + 10, ly, _recorta(lab, 'Helvetica', 6.8, (x + w - 0.4 * cm) - (lx + 10) - vw - 5))
        c.setFillColor(_c('ink'))
        c.setFont('Helvetica-Bold', 6.8)
        c.drawRightString(x + w - 0.4 * cm, ly, vt)
        ly -= 0.5 * cm
    return h


# ─────────────────────────────────────────────────────────────────────
def graf_antiguedad(c, x, y, w, h, aging, titulo, sub=None):
    cats = [('0-30', '0-30 d', '#059669'), ('31-60', '31-60 d', '#d97706'), ('61-90', '61-90 d', '#ea580c'), ('90+', '+90 d', '#be123c')]
    y_in = _tarjeta(c, x, y, w, h, titulo, sub)
    vmax = max([aging.get(k, 0) for k, _l, _c2 in cats] + [1])
    tot = sum(aging.get(k, 0) for k, _l, _c2 in cats) or 1
    base = y - h + 0.75 * cm
    ph = y_in - 0.7 * cm - base
    slot = (w - 0.9 * cm) / 4
    bw = min(1.7 * cm, slot * 0.62)
    c.setStrokeColor(_c('linea'))
    c.setLineWidth(0.6)
    c.line(x + 0.45 * cm, base, x + w - 0.45 * cm, base)
    for i, (k, lab, col) in enumerate(cats):
        v = aging.get(k, 0)
        cx = x + 0.45 * cm + slot * (i + 0.5)
        hh = max(ph * v / vmax, 1.5 if v else 0)
        c.setFillColor(colors.HexColor(col))
        c.roundRect(cx - bw / 2, base, bw, hh, 3, stroke=0, fill=1)
        c.setFillColor(_c('ink'))
        c.setFont('Helvetica-Bold', 7)
        c.drawCentredString(cx, base + hh + 0.28 * cm, bs0(v))
        c.setFont('Helvetica', 6)
        c.setFillColor(_c('muted'))
        c.drawCentredString(cx, base + hh + 0.06 * cm, f"{100 * v / tot:.0f}%")
        c.setFillColor(_c('txt'))
        c.setFont('Helvetica', 6.6)
        c.drawCentredString(cx, base - 0.38 * cm, lab)
    return h


# ─────────────────────────────────────────────────────────────────────
def alto_barras_h(n):
    return 1.7 * cm + n * 0.5 * cm + 0.3 * cm


def graf_barras_h(c, x, y, w, items, titulo, sub=None, color='#6366f1'):
    """Barras horizontales en Bs. items: [{'nombre','valor','extra','color'?}] (en el orden deseado)."""
    h = alto_barras_h(len(items))
    y_in = _tarjeta(c, x, y, w, h, titulo, sub)
    if not items:
        return h
    lab_w, val_w, ext_w = 4.6 * cm, 1.9 * cm, 3.6 * cm
    bx = x + 0.45 * cm + lab_w
    bw = w - 0.9 * cm - lab_w - val_w - ext_w
    vmax = max([it['valor'] for it in items] + [1])
    yy = y_in - 0.35 * cm
    for it in items:
        c.setFillColor(_c('ink'))
        c.setFont('Helvetica', 7)
        c.drawString(x + 0.45 * cm, yy - 0.02 * cm, _recorta(it['nombre'], 'Helvetica', 7, lab_w - 0.2 * cm))
        c.setFillColor(_c('fondo'))
        c.roundRect(bx, yy - 0.12 * cm, bw, 0.3 * cm, 2.5, stroke=0, fill=1)
        c.setFillColor(colors.HexColor(it.get('color', color)))
        c.roundRect(bx, yy - 0.12 * cm, max(bw * it['valor'] / vmax, 2), 0.3 * cm, 2.5, stroke=0, fill=1)
        c.setFillColor(_c('ink'))
        c.setFont('Helvetica-Bold', 7)
        c.drawString(bx + bw + 0.2 * cm, yy - 0.02 * cm, bs0(it['valor']))
        c.setFont('Helvetica', 6)
        c.setFillColor(_c('muted'))
        c.drawString(bx + bw + val_w + 0.3 * cm, yy - 0.02 * cm, _recorta(it.get('extra', ''), 'Helvetica', 6, ext_w - 0.4 * cm))
        yy -= 0.5 * cm
    return h
