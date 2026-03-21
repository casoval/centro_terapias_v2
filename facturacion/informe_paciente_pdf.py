# facturacion/informe_paciente_pdf.py
# =====================================================================
# GENERADOR DE INFORME INDIVIDUAL DE PACIENTE — ReportLab canvas
# Secciones:
#   Portada — datos del paciente + KPIs clave
#   1. Perfil clínico completo
#   2. Resumen financiero (cuenta corriente + período)
#   3. Estadísticas de asistencia
#   4. Evolución mensual (tabla)
#   5. Desglose por servicio
#   6. Desglose por profesional
#   7. Proyectos terapéuticos
#   8. Mensualidades
#   9. Desglose financiero por sucursal
#  10. Detalle completo de sesiones (landscape A4)
# =====================================================================

import os
import logging
from io import BytesIO
from decimal import Decimal
from datetime import date as _date_cls

from reportlab.lib.pagesizes import letter, A4, landscape as _landscape
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.pdfbase.pdfmetrics import stringWidth
from django.conf import settings

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────
# PALETA — tonos slate/azul oscuro con acentos ámbar/esmeralda
# ─────────────────────────────────────────────────────────────────────
C_OSC     = colors.HexColor('#0f172a')
C_PRI     = colors.HexColor('#1e3a5f')
C_MED     = colors.HexColor('#2563eb')
C_FONDO   = colors.HexColor('#dbeafe')
C_VERDE   = colors.HexColor('#16a34a')
C_VERDE_L = colors.HexColor('#dcfce7')
C_AMBER   = colors.HexColor('#d97706')
C_AMBER_L = colors.HexColor('#fef3c7')
C_ROJO    = colors.HexColor('#dc2626')
C_ROJO_L  = colors.HexColor('#fee2e2')
C_MORADO  = colors.HexColor('#7c3aed')
C_MORADO_L= colors.HexColor('#ede9fe')
C_TEAL    = colors.HexColor('#0d9488')
C_TEAL_L  = colors.HexColor('#ccfbf1')
C_GRIS_T  = colors.HexColor('#f8fafc')
C_GRIS_H  = colors.HexColor('#e2e8f0')
C_GRIS_B  = colors.HexColor('#cbd5e1')
C_TEXTO   = colors.HexColor('#0f172a')
C_TSEC    = colors.HexColor('#334155')
C_MUTED   = colors.HexColor('#64748b')
C_BLANCO  = colors.white
C_FONDO_PAG = colors.HexColor('#f8fafc')

# ─────────────────────────────────────────────────────────────────────
# LAYOUT
# ─────────────────────────────────────────────────────────────────────
PAGE_W, PAGE_H = letter
ML = 1.8 * cm
MR = 1.8 * cm
CW = PAGE_W - ML - MR
HEADER_H = 2.6 * cm
FOOTER_H = 0.9 * cm
Y_BOTTOM  = 1.5 * cm + FOOTER_H + 0.3 * cm

# Landscape A4
_LS_W, _LS_H = _landscape(A4)
_LS_ML = 1.5 * cm
_LS_MR = 1.5 * cm
_LS_CW = _LS_W - _LS_ML - _LS_MR
_LS_Y_BOTTOM = 1.2 * cm + 0.7 * cm + 0.2 * cm

NOMBRE_CENTRO = "Centro de Neurodesarrollo Infantil Misael"
DIRECCION     = "Calle Japon #28  -  Potosi, Bolivia"
TELEFONO      = "Tel.: 76175352"

MESES_FULL = ['', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
              'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']
MESES_CORTO = ['', 'Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun',
               'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']

ESTADO_LABEL = {
    'realizada': 'Realizada', 'realizada_retraso': 'Con Retraso',
    'falta': 'Falta', 'permiso': 'Permiso', 'cancelada': 'Cancelada',
    'reprogramada': 'Reprogramada', 'programada': 'Programada',
}
ESTADO_COLOR = {
    'realizada': C_VERDE, 'realizada_retraso': C_AMBER,
    'falta': C_ROJO, 'permiso': C_MORADO, 'cancelada': C_MUTED,
    'reprogramada': C_TEAL, 'programada': C_MED,
}

# ─────────────────────────────────────────────────────────────────────
# HELPERS
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
    try:
        return f"Bs. {float(v):,.0f}"
    except Exception:
        return "Bs. 0"


def _pct(v):
    try:
        return f"{float(str(v).replace('%','')):.1f}%"
    except Exception:
        return "0.0%"


def _num(v, default=0):
    try:
        return int(float(v))
    except Exception:
        return default


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


def _attr(obj, key, default=''):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default) or default

# ─────────────────────────────────────────────────────────────────────
# ENCABEZADO / PIE / NUEVA PÁGINA
# ─────────────────────────────────────────────────────────────────────

def _encabezado(c, pg, total_pg, titulo, nombre_pac, periodo_txt, fecha_emision):
    _grad(c, 0, PAGE_H - HEADER_H, PAGE_W, HEADER_H, C_OSC, C_PRI)
    lp = _logo()
    lh = HEADER_H - 0.5 * cm
    if lp:
        try:
            c.drawImage(lp, ML, PAGE_H - HEADER_H + 0.25 * cm,
                        width=lh, height=lh, preserveAspectRatio=True, mask='auto')
        except Exception:
            pass
    tx = ML + lh + 0.4 * cm
    c.setFillColor(C_BLANCO)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(tx, PAGE_H - 1.0 * cm, NOMBRE_CENTRO)
    c.setFont("Helvetica", 7)
    c.drawString(tx, PAGE_H - 1.55 * cm, f"{DIRECCION}  |  {TELEFONO}")
    c.setFont("Helvetica-Bold", 8.5)
    c.drawRightString(PAGE_W - MR, PAGE_H - 0.9 * cm, titulo)
    c.setFont("Helvetica", 7)
    c.drawRightString(PAGE_W - MR, PAGE_H - 1.45 * cm, f"Pag. {pg} de {total_pg}")

    by = PAGE_H - HEADER_H - 0.8 * cm - 0.1 * cm
    c.setFillColor(C_FONDO)
    c.roundRect(ML, by, CW, 0.78 * cm, 4, fill=1, stroke=0)
    c.setStrokeColor(C_MED)
    c.setLineWidth(0.4)
    c.roundRect(ML, by, CW, 0.78 * cm, 4, fill=0, stroke=1)
    c.setFont("Helvetica-Bold", 7)
    c.setFillColor(C_PRI)
    c.drawString(ML + 0.35 * cm, by + 0.48 * cm, "PACIENTE:")
    c.setFont("Helvetica-Bold", 8)
    c.setFillColor(C_TEXTO)
    c.drawString(ML + 2.0 * cm, by + 0.48 * cm, nombre_pac)
    c.setFont("Helvetica-Bold", 7)
    c.setFillColor(C_PRI)
    c.drawString(ML + 9.5 * cm, by + 0.48 * cm, "PERÍODO:")
    c.setFont("Helvetica", 7.5)
    c.setFillColor(C_TEXTO)
    c.drawString(ML + 11.1 * cm, by + 0.48 * cm, periodo_txt)
    c.setFont("Helvetica", 7)
    c.setFillColor(C_MUTED)
    c.drawRightString(PAGE_W - MR, by + 0.48 * cm, f"Emitido: {fecha_emision}")
    return by - 0.4 * cm


def _pie(c, pg, total_pg, fecha_emision):
    py = 1.5 * cm + 0.15 * cm
    c.setStrokeColor(C_GRIS_B)
    c.setLineWidth(0.4)
    c.line(ML, py + FOOTER_H - 0.15 * cm, PAGE_W - MR, py + FOOTER_H - 0.15 * cm)
    c.setFont("Helvetica", 6.5)
    c.setFillColor(C_MUTED)
    c.drawString(ML, py + 0.28 * cm,
                 f"{NOMBRE_CENTRO}  |  Informe de Paciente — {fecha_emision}  |  CONFIDENCIAL")
    c.drawRightString(PAGE_W - MR, py + 0.28 * cm, f"Pag. {pg} / {total_pg}")


# ─────────────────────────────────────────────────────────────────────
# PRIMITIVOS
# ─────────────────────────────────────────────────────────────────────

def _titulo_seccion(c, y, texto, color=None):
    col = color or C_PRI
    c.setFillColor(col)
    c.roundRect(ML, y - 0.55 * cm, CW, 0.55 * cm, 4, fill=1, stroke=0)
    c.setFillColor(C_BLANCO)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(ML + 0.4 * cm, y - 0.38 * cm, texto.upper())
    return y - 0.55 * cm - 0.3 * cm


def _explicacion(c, y, texto):
    c.setFont("Helvetica-Oblique", 7.5)
    c.setFillColor(C_MUTED)
    ny = _wrap(c, texto, ML + 0.2 * cm, y, CW - 0.4 * cm, "Helvetica-Oblique", 7.5, 0.37 * cm)
    return ny - 0.2 * cm


def _metrica_box(c, x, y, w, h, label, valor, sublabel='', color=C_MED):
    top, bot = y, y - h
    # Fondo tintado
    r_t = 1.0 - (1.0 - color.red)   * 0.09
    g_t = 1.0 - (1.0 - color.green) * 0.09
    b_t = 1.0 - (1.0 - color.blue)  * 0.09
    c.setFillColor(colors.Color(r_t, g_t, b_t))
    c.roundRect(x, bot, w, h, 6, fill=1, stroke=0)
    c.setStrokeColor(color)
    c.setLineWidth(0.5)
    c.roundRect(x, bot, w, h, 6, fill=0, stroke=1)
    # Barra lateral
    bw = 0.22 * cm
    c.setFillColor(color)
    c.roundRect(x, bot, bw * 2, h, 5, fill=1, stroke=0)
    c.rect(x + bw, bot, bw, h, fill=1, stroke=0)
    pad = bw + 0.25 * cm
    avail = w - pad - 0.18 * cm
    # Label
    c.setFont("Helvetica-Bold", 6.2)
    c.setFillColor(color)
    lbl = label.upper()
    while stringWidth(lbl, "Helvetica-Bold", 6.2) > avail and len(lbl) > 2:
        lbl = lbl[:-2] + '.'
    c.drawString(x + pad, top - 0.42 * cm, lbl)
    # Valor
    for fs in (14, 12, 10, 9, 8):
        if stringWidth(valor, "Helvetica-Bold", fs) <= avail:
            break
    c.setFont("Helvetica-Bold", fs)
    c.setFillColor(C_TEXTO)
    c.drawString(x + pad, bot + h * 0.52 - fs * 0.015 * cm, valor)
    # Sublabel
    if sublabel:
        c.setFont("Helvetica", 6)
        c.setFillColor(C_MUTED)
        sub = sublabel
        while stringWidth(sub, "Helvetica", 6) > avail and len(sub) > 4:
            sub = sub[:-2] + '…'
        c.drawString(x + pad, bot + 0.22 * cm, sub)


def _grilla(c, y, items, cols=4, box_h=1.7 * cm):
    gap = 0.25 * cm
    bw  = (CW - (cols - 1) * gap) / cols
    row = []
    for item in items:
        row.append(item)
        if len(row) == cols:
            for i, (lbl, val, sub, col) in enumerate(row):
                _metrica_box(c, ML + i * (bw + gap), y, bw, box_h, lbl, val, sub, col)
            y -= box_h + 0.35 * cm
            row = []
    if row:
        n = len(row)
        bw2 = (CW - (n - 1) * gap) / n
        for i, (lbl, val, sub, col) in enumerate(row):
            _metrica_box(c, ML + i * (bw2 + gap), y, bw2, box_h, lbl, val, sub, col)
        y -= box_h + 0.35 * cm
    return y


def _tabla(c, y, headers, rows, col_ws, stripe=True, fsize=7.5, row_h=0.52 * cm):
    total_w = sum(col_ws)
    c.setFillColor(C_GRIS_H)
    c.roundRect(ML, y - row_h, total_w, row_h, 3, fill=1, stroke=0)
    c.setStrokeColor(C_GRIS_B)
    c.setLineWidth(0.3)
    c.roundRect(ML, y - row_h, total_w, row_h, 3, fill=0, stroke=1)
    xc = ML
    for i, h in enumerate(headers):
        c.setFont("Helvetica-Bold", 7)
        c.setFillColor(C_TSEC)
        c.drawString(xc + 0.25 * cm, y - row_h + 0.15 * cm, str(h).upper())
        xc += col_ws[i]
    y -= row_h
    for ri, row in enumerate(rows):
        if stripe and ri % 2 == 0:
            c.setFillColor(C_GRIS_T)
            c.rect(ML, y - row_h, total_w, row_h, fill=1, stroke=0)
        c.setStrokeColor(C_GRIS_B)
        c.setLineWidth(0.2)
        c.line(ML, y - row_h, ML + total_w, y - row_h)
        xc = ML
        for ci, cell in enumerate(row):
            c.setFont("Helvetica", fsize)
            c.setFillColor(C_TEXTO)
            txt = str(cell) if cell is not None else ''
            mw  = col_ws[ci] - 0.5 * cm
            while stringWidth(txt, "Helvetica", fsize) > mw and len(txt) > 1:
                txt = txt[:-2] + '.'
            c.drawString(xc + 0.25 * cm, y - row_h + 0.13 * cm, txt)
            xc += col_ws[ci]
        y -= row_h
    c.setStrokeColor(C_GRIS_B)
    c.setLineWidth(0.4)
    c.line(ML, y, ML + total_w, y)
    return y - 0.2 * cm


def _tabla_header(c, y, headers, col_ws, row_h=0.5 * cm):
    total_w = sum(col_ws)
    c.setFillColor(C_GRIS_H)
    c.roundRect(ML, y - row_h, total_w, row_h, 3, fill=1, stroke=0)
    c.setStrokeColor(C_GRIS_B)
    c.setLineWidth(0.3)
    c.roundRect(ML, y - row_h, total_w, row_h, 3, fill=0, stroke=1)
    xc = ML
    for i, h in enumerate(headers):
        c.setFont("Helvetica-Bold", 7)
        c.setFillColor(C_TSEC)
        c.drawString(xc + 0.25 * cm, y - row_h + 0.15 * cm, str(h).upper())
        xc += col_ws[i]
    return y - row_h


def _kv_fila(c, y, label, valor, color_v=None):
    c.setFont("Helvetica-Bold", 7.5)
    c.setFillColor(C_TSEC)
    c.drawString(ML + 0.2 * cm, y, label)
    c.setFont("Helvetica", 8)
    c.setFillColor(color_v or C_TEXTO)
    c.drawRightString(ML + CW, y, str(valor))
    c.setStrokeColor(C_GRIS_B)
    c.setLineWidth(0.18)
    c.line(ML, y - 0.12 * cm, ML + CW, y - 0.12 * cm)
    return y - 0.44 * cm


# ─────────────────────────────────────────────────────────────────────
# PORTADA
# ─────────────────────────────────────────────────────────────────────

def _portada(c, pac, periodo_txt, fecha_emision, ctx):
    c.setFillColor(C_FONDO_PAG)
    c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    _grad(c, 0, PAGE_H - 6.0 * cm, PAGE_W, 6.0 * cm, C_OSC, C_PRI)

    # Logo del centro
    lp = _logo()
    if lp:
        try:
            c.drawImage(lp, ML, PAGE_H - 5.0 * cm, width=3 * cm, height=3 * cm,
                        preserveAspectRatio=True, mask='auto')
        except Exception:
            pass
    c.setFillColor(C_BLANCO)
    c.setFont("Helvetica-Bold", 15)
    c.drawString(ML + 3.5 * cm, PAGE_H - 2.3 * cm, NOMBRE_CENTRO)
    c.setFont("Helvetica", 8.5)
    c.drawString(ML + 3.5 * cm, PAGE_H - 2.95 * cm, f"{DIRECCION}  |  {TELEFONO}")

    c.setStrokeColor(colors.HexColor('#93c5fd'))
    c.setLineWidth(1.5)
    c.line(ML, PAGE_H - 6.0 * cm + 0.3 * cm, PAGE_W - MR, PAGE_H - 6.0 * cm + 0.3 * cm)

    # ── Foto del paciente (si existe) ────────────────────────────────
    foto_path = None
    if pac:
        foto_field = getattr(pac, 'foto', None)
        if foto_field:
            try:
                ruta = str(foto_field.path)
                if os.path.exists(ruta):
                    foto_path = ruta
            except Exception:
                pass

    # Zona central: foto a la izquierda + nombre/datos a la derecha
    ty = PAGE_H - 8.5 * cm
    foto_size = 3.8 * cm

    if foto_path:
        foto_x = PAGE_W / 2 - foto_size / 2 - 3.5 * cm
        foto_y = ty - 0.3 * cm
        # Marco de la foto
        c.setFillColor(C_GRIS_H)
        c.roundRect(foto_x - 0.12 * cm, foto_y - foto_size - 0.12 * cm,
                    foto_size + 0.24 * cm, foto_size + 0.24 * cm, 8, fill=1, stroke=0)
        c.setStrokeColor(C_MED)
        c.setLineWidth(1.5)
        c.roundRect(foto_x - 0.12 * cm, foto_y - foto_size - 0.12 * cm,
                    foto_size + 0.24 * cm, foto_size + 0.24 * cm, 8, fill=0, stroke=1)
        try:
            c.drawImage(foto_path, foto_x, foto_y - foto_size,
                        width=foto_size, height=foto_size,
                        preserveAspectRatio=False, mask='auto')
        except Exception:
            foto_path = None   # si falla el render, continuar sin foto

    # Título "INFORME INDIVIDUAL DE PACIENTE"
    c.setFont("Helvetica-Bold", 20)
    c.setFillColor(C_TEXTO)
    titulo = "INFORME INDIVIDUAL DE PACIENTE"
    c.drawCentredString(PAGE_W / 2, ty, titulo)
    c.setStrokeColor(C_MED)
    c.setLineWidth(2)
    tw = stringWidth(titulo, "Helvetica-Bold", 20)
    c.line(PAGE_W / 2 - tw / 2, ty - 0.3 * cm, PAGE_W / 2 + tw / 2, ty - 0.3 * cm)

    # Nombre del paciente
    nombre_pac = str(pac) if pac else '—'
    c.setFont("Helvetica-Bold", 14)
    c.setFillColor(C_PRI)
    c.drawCentredString(PAGE_W / 2, ty - 1.1 * cm, nombre_pac)

    # Datos breves del paciente bajo el nombre
    detalles = []
    if pac:
        edad = getattr(pac, 'edad', None)
        if edad: detalles.append(f"{edad} años")
        ci = getattr(pac, 'ci', None) or getattr(pac, 'carnet', None)
        if ci: detalles.append(f"CI: {ci}")
        genero_fn = getattr(pac, 'get_genero_display', None)
        if callable(genero_fn):
            try:
                g = genero_fn()
                if g: detalles.append(g)
            except Exception:
                pass
        gs = getattr(pac, 'grupo_sanguineo', None)
        if gs: detalles.append(f"Grupo: {gs}")

    if detalles:
        c.setFont("Helvetica", 9)
        c.setFillColor(C_TSEC)
        c.drawCentredString(PAGE_W / 2, ty - 1.85 * cm, "  ·  ".join(detalles))

    c.setFont("Helvetica", 10)
    c.setFillColor(C_TSEC)
    c.drawCentredString(PAGE_W / 2, ty - 2.55 * cm, f"Período: {periodo_txt}")
    c.setFont("Helvetica", 8.5)
    c.setFillColor(C_MUTED)
    c.drawCentredString(PAGE_W / 2, ty - 3.15 * cm, f"Documento generado el {fecha_emision}")

    # ── Caja KPIs portada ────────────────────────────────────────────
    stats = (ctx.get('datos') or {}).get('stats') or {}
    datos  = ctx.get('datos') or {}
    cc     = getattr(ctx.get('paciente'), 'cuenta_corriente', None)

    cy = ty - 4.2 * cm
    box_h_portada = 5.0 * cm
    c.setFillColor(C_GRIS_T)
    c.roundRect(ML, cy - box_h_portada, CW, box_h_portada, 8, fill=1, stroke=0)
    c.setStrokeColor(C_GRIS_B)
    c.setLineWidth(0.5)
    c.roundRect(ML, cy - box_h_portada, CW, box_h_portada, 8, fill=0, stroke=1)
    c.setFont("Helvetica-Bold", 9)
    c.setFillColor(C_PRI)
    c.drawString(ML + 0.5 * cm, cy - 0.45 * cm, "INDICADORES CLAVE DEL PERÍODO")

    # Saldo real como principal, saldo_actual como sublabel
    saldo_real   = cc.saldo_real   if cc else 0
    saldo_actual = cc.saldo_actual if cc else 0
    saldo_color  = C_VERDE if float(saldo_real) >= 0 else C_ROJO

    kpis_f1 = [
        ("Total Sesiones",  str(_num(stats.get('total_sesiones', 0))),              "En el período",      C_MED),
        ("Realizadas",      str(_num(stats.get('realizadas', 0)) +
                               _num(stats.get('retrasos', 0))),                     "Incl. retrasos",     C_VERDE),
        ("Faltas",          str(_num(stats.get('faltas', 0))),                      "Inasistencias",      C_ROJO),
        ("Tasa Asistencia", _pct(datos.get('tasa_asistencia', 0)),                  "Del período",        C_TEAL),
    ]
    kpis_f2 = [
        ("Total Cobrado",   _bs(stats.get('total_cobrado', 0)),                     "Monto generado",     C_MED),
        ("Total Pagado",    _bs(stats.get('total_pagado', 0)),                      "Pagado en período",  C_VERDE),
        ("Saldo Pendiente", _bs(stats.get('saldo_pendiente', 0)),                   "Por cobrar",         C_AMBER),
        ("Saldo Real Proy.", _bs(saldo_real),
         f"Cuenta: {_bs(saldo_actual)}",                                            saldo_color),
    ]

    gap_p = 0.2 * cm
    n_k   = 4
    bw_p  = (CW - 1.0 * cm - (n_k - 1) * gap_p) / n_k
    bh_p  = 1.8 * cm
    for i, (lbl, val, sub, col) in enumerate(kpis_f1):
        _metrica_box(c, ML + 0.5 * cm + i * (bw_p + gap_p),
                     cy - 0.55 * cm, bw_p, bh_p, lbl, val, sub, col)
    for i, (lbl, val, sub, col) in enumerate(kpis_f2):
        _metrica_box(c, ML + 0.5 * cm + i * (bw_p + gap_p),
                     cy - 0.55 * cm - bh_p - 0.3 * cm, bw_p, bh_p, lbl, val, sub, col)

    _pie(c, 1, 999, fecha_emision)


# ─────────────────────────────────────────────────────────────────────
# SECCIÓN 1 — PERFIL CLÍNICO
# ─────────────────────────────────────────────────────────────────────

def _seccion_perfil(pages_data, ctx, helpers):
    """
    Sección 1: Perfil completo del paciente.
    Todos los campos se leen defensivamente con getattr(pac, campo, None).
    Incluye fotografía del paciente, datos bien espaciados y diagnóstico destacado.
    """
    make_page = helpers['new_page']
    pac       = ctx.get('paciente')
    if not pac:
        return

    c, y, pg = make_page()
    y = _titulo_seccion(c, y, "1. Perfil Completo del Paciente")

    # ── Helper: obtener campo defensivamente ─────────────────────────
    def _g(attr, default=''):
        val = getattr(pac, attr, None)
        if val is None:
            return default
        if callable(val):
            try:
                return val() or default
            except Exception:
                return default
        return val or default

    def _gf(attr):
        val = getattr(pac, attr, None)
        if not val:
            return '—'
        try:
            return val.strftime('%d/%m/%Y')
        except Exception:
            return str(val)

    # ── Intentar cargar foto (soporta Cloudinary y filesystem) ──────
    foto_path = None
    foto_field = getattr(pac, 'foto', None)
    if foto_field:
        # 1) Intentar path local (almacenamiento en disco)
        try:
            ruta = str(foto_field.path)
            if os.path.exists(ruta):
                foto_path = ruta
        except Exception:
            pass

        # 2) Si no hay path (Cloudinary u otro storage externo), descargar la URL
        if not foto_path:
            try:
                import urllib.request, tempfile
                foto_url = None
                # Cloudinary: build_url o .url
                if hasattr(foto_field, 'build_url'):
                    try:
                        foto_url = foto_field.build_url(
                            width=300, height=300, crop='fill',
                            gravity='face', quality='auto', fetch_format='auto'
                        )
                    except Exception:
                        pass
                if not foto_url and hasattr(foto_field, 'url'):
                    foto_url = foto_field.url

                if foto_url:
                    # Asegurar protocolo HTTPS
                    if foto_url.startswith('//'):
                        foto_url = 'https:' + foto_url
                    tmp = tempfile.NamedTemporaryFile(suffix='.jpg', delete=False)
                    urllib.request.urlretrieve(foto_url, tmp.name)
                    tmp.close()
                    if os.path.getsize(tmp.name) > 0:
                        foto_path = tmp.name
            except Exception:
                foto_path = None

    FOTO_W = 3.6 * cm
    FOTO_H = 3.6 * cm
    foto_x = ML
    foto_y = y - FOTO_H

    if foto_path:
        # Marco de la foto
        c.setFillColor(C_GRIS_H)
        c.roundRect(foto_x - 0.12*cm, foto_y - 0.12*cm,
                    FOTO_W + 0.24*cm, FOTO_H + 0.24*cm, 7, fill=1, stroke=0)
        c.setStrokeColor(C_MED)
        c.setLineWidth(1.5)
        c.roundRect(foto_x - 0.12*cm, foto_y - 0.12*cm,
                    FOTO_W + 0.24*cm, FOTO_H + 0.24*cm, 7, fill=0, stroke=1)
        try:
            c.drawImage(foto_path, foto_x, foto_y,
                        width=FOTO_W, height=FOTO_H,
                        preserveAspectRatio=False, mask='auto')
        except Exception:
            foto_path = None  # si falla el render mostrar avatar abajo

    if not foto_path:
        # Avatar placeholder con iniciales
        c.setFillColor(C_FONDO)
        c.roundRect(foto_x, foto_y, FOTO_W, FOTO_H, 7, fill=1, stroke=0)
        c.setStrokeColor(C_MED)
        c.setLineWidth(1.0)
        c.roundRect(foto_x, foto_y, FOTO_W, FOTO_H, 7, fill=0, stroke=1)
        nom_raw = _g('nombre_completo') or f"{_g('nombre')} {_g('apellido')}".strip()
        partes   = nom_raw.split()
        iniciales = ''.join(p[0].upper() for p in partes[:2]) if partes else '?'
        c.setFont("Helvetica-Bold", 22)
        c.setFillColor(C_MED)
        c.drawCentredString(foto_x + FOTO_W / 2, foto_y + FOTO_H / 2 - 0.4*cm, iniciales)

    # ── Columnas (siempre reservar espacio de foto) ───────────────────
    x_offset = FOTO_W + 0.55*cm
    col_izq  = ML + x_offset
    col_der  = ML + CW / 2 + 0.3*cm
    cw_izq   = CW / 2 - x_offset - 0.3*cm
    cw_der   = CW / 2 - 0.6*cm

    ROW_H  = 0.88 * cm   # altura total de cada fila (label + valor + espacio)
    GAP    = 0.10 * cm   # gap entre filas

    def _kv2(c, y_pos, label, valor, x, w):
        # Fondo de la tarjeta
        c.setFillColor(C_FONDO)
        c.roundRect(x, y_pos - ROW_H, w, ROW_H, 3, fill=1, stroke=0)
        # Label en azul pequeño arriba
        c.setFont("Helvetica-Bold", 6.2)
        c.setFillColor(C_MED)
        c.drawString(x + 0.25*cm, y_pos - 0.25*cm, label.upper())
        # Valor en negro más grande abajo
        c.setFont("Helvetica", 8.5)
        c.setFillColor(C_TEXTO)
        txt = str(valor) if valor else '—'
        mw = w - 0.5*cm
        while stringWidth(txt, "Helvetica", 8.5) > mw and len(txt) > 1:
            txt = txt[:-2] + '.'
        c.drawString(x + 0.25*cm, y_pos - 0.62*cm, txt)
        return y_pos - ROW_H - GAP

    # ── COLUMNA IZQUIERDA: Datos de identidad ─────────────────────────
    yi = y
    nom = (_g('nombre_completo') or f"{_g('nombre')} {_g('apellido')}".strip() or '—')
    yi = _kv2(c, yi, "Nombre completo", nom, col_izq, cw_izq)
    ci_val = _g('ci') or _g('carnet') or _g('documento') or '—'
    yi = _kv2(c, yi, "CI / Carnet", ci_val, col_izq, cw_izq)
    yi = _kv2(c, yi, "Fecha de nacimiento", _gf('fecha_nacimiento'), col_izq, cw_izq)
    edad_val = _g('edad')
    yi = _kv2(c, yi, "Edad", f"{edad_val} años" if edad_val else '—', col_izq, cw_izq)
    gen = _g('get_genero_display') or _g('genero') or '—'
    yi = _kv2(c, yi, "Género", gen, col_izq, cw_izq)
    est = _g('get_estado_display') or _g('estado') or '—'
    yi = _kv2(c, yi, "Estado", est, col_izq, cw_izq)
    peso  = _g('peso')
    talla = _g('talla') or _g('altura')
    if peso or talla:
        wt = []
        if peso:  wt.append(f"{peso} kg")
        if talla: wt.append(f"{talla} cm")
        yi = _kv2(c, yi, "Peso / Talla", ' · '.join(wt), col_izq, cw_izq)
    gs = _g('grupo_sanguineo') or _g('tipo_sangre')
    if gs:
        yi = _kv2(c, yi, "Grupo sanguíneo", gs, col_izq, cw_izq)
    nac = _g('nacionalidad')
    if nac: yi = _kv2(c, yi, "Nacionalidad", nac, col_izq, cw_izq)
    ciu = _g('ciudad') or _g('municipio')
    if ciu: yi = _kv2(c, yi, "Ciudad / Municipio", ciu, col_izq, cw_izq)
    dom = _g('domicilio') or _g('direccion')
    if dom: yi = _kv2(c, yi, "Domicilio", dom, col_izq, cw_izq)
    nivel   = _g('nivel_educativo') or _g('grado')
    escuela = _g('escuela') or _g('colegio')
    if nivel:   yi = _kv2(c, yi, "Nivel educativo", nivel, col_izq, cw_izq)
    if escuela: yi = _kv2(c, yi, "Escuela / Colegio", escuela, col_izq, cw_izq)
    fi = _gf('fecha_ingreso') or _gf('fecha_registro')
    if fi and fi != '—': yi = _kv2(c, yi, "Ingreso al centro", fi, col_izq, cw_izq)

    # ── COLUMNA DERECHA: Tutor y contacto ────────────────────────────
    yd = y
    tutor = _g('nombre_tutor') or _g('nombre_padre') or _g('nombre_madre')
    if tutor: yd = _kv2(c, yd, "Tutor / Responsable", tutor, col_der, cw_der)
    par = _g('get_parentesco_display') or _g('parentesco')
    if par: yd = _kv2(c, yd, "Parentesco", par, col_der, cw_der)
    ci_tutor = _g('ci_tutor') or _g('carnet_tutor')
    if ci_tutor: yd = _kv2(c, yd, "CI del tutor", ci_tutor, col_der, cw_der)
    ocu = _g('ocupacion_tutor') or _g('profesion_tutor')
    if ocu: yd = _kv2(c, yd, "Ocupación tutor", ocu, col_der, cw_der)
    tel1 = _g('telefono_tutor') or _g('telefono') or _g('celular_tutor')
    tel2 = _g('telefono_casa') or _g('telefono2')
    tel3 = _g('telefono_emergencia')
    if tel1: yd = _kv2(c, yd, "Teléfono tutor", tel1, col_der, cw_der)
    if tel2: yd = _kv2(c, yd, "Tel. alternativo", tel2, col_der, cw_der)
    if tel3: yd = _kv2(c, yd, "Tel. emergencia", tel3, col_der, cw_der)
    email = _g('email_tutor') or _g('email')
    if email: yd = _kv2(c, yd, "Email", email, col_der, cw_der)
    try:
        sucs = pac.sucursales.all()
        suc_txt = ', '.join(s.nombre for s in sucs) if sucs.exists() else '—'
    except Exception:
        suc_txt = '—'
    yd = _kv2(c, yd, "Sucursales", suc_txt, col_der, cw_der)
    der = _g('derivado_de') or _g('medico_derivante')
    if der: yd = _kv2(c, yd, "Derivado de", der, col_der, cw_der)
    seg = _g('seguro_medico') or _g('obra_social')
    if seg: yd = _kv2(c, yd, "Seguro médico", seg, col_der, cw_der)

    # Segundo tutor (si existe)
    tutor2 = _g('nombre_tutor_2')
    if tutor2:
        yd = _kv2(c, yd, "2° Tutor", tutor2, col_der, cw_der)
        par2 = _g('get_parentesco_2_display') or _g('parentesco_2')
        tel_2 = _g('telefono_tutor_2')
        if par2: yd = _kv2(c, yd, "Parentesco 2°", par2, col_der, cw_der)
        if tel_2: yd = _kv2(c, yd, "Teléfono 2°", tel_2, col_der, cw_der)

    y = min(yi, yd) - 0.35*cm

    # ── SECCIÓN 1.2: DIAGNÓSTICO DESTACADO ───────────────────────────
    diag_principal = _g('diagnostico')
    if diag_principal:
        if y < Y_BOTTOM + 2.5*cm:
            _pie(c, pg, helpers['total_pg'][0], helpers['fecha'])
            pages_data.append(pg)
            c, y, pg = make_page()

        y -= 0.1*cm
        y = _titulo_seccion(c, y, "1.2 Diagnóstico", color=C_TEAL)

        # Caja destacada de diagnóstico
        words_d = str(diag_principal).split()
        lines_d, line_d = [], ""
        mw_d = CW - 3.0*cm
        for w_ in words_d:
            test = (line_d + " " + w_).strip()
            if stringWidth(test, "Helvetica-Bold", 9) <= mw_d:
                line_d = test
            else:
                if line_d: lines_d.append(line_d)
                line_d = w_
        if line_d: lines_d.append(line_d)

        diag_h = max(1.1*cm, len(lines_d) * 0.44*cm + 0.5*cm)
        c.setFillColor(C_TEAL_L)
        c.roundRect(ML, y - diag_h, CW, diag_h, 5, fill=1, stroke=0)
        c.setStrokeColor(C_TEAL)
        c.setLineWidth(1.5)
        c.line(ML, y - diag_h, ML, y)  # barra izquierda
        c.setLineWidth(0.4)
        c.roundRect(ML, y - diag_h, CW, diag_h, 5, fill=0, stroke=1)
        c.setFont("Helvetica-Bold", 6.5)
        c.setFillColor(C_TEAL)
        c.drawString(ML + 0.4*cm, y - 0.24*cm, "DIAGNÓSTICO:")
        yt = y - 0.24*cm
        for ln in lines_d:
            c.setFont("Helvetica-Bold", 9)
            c.setFillColor(C_TEXTO)
            c.drawString(ML + 3.0*cm, yt, ln)
            yt -= 0.44*cm
        y -= diag_h + 0.15*cm

    # ── SECCIÓN 1.3: INFORMACIÓN CLÍNICA ─────────────────────────────
    campos_clinicos = [
        ("Diagnóstico secundario", _g('diagnostico_secundario') or _g('diagnostico2'), C_TEAL_L),
        ("CIE-10 / Código diag.", _g('cie10') or _g('codigo_diagnostico'), C_TEAL_L),
        ("Observaciones médicas",  _g('observaciones_medicas') or _g('observaciones'), C_GRIS_T),
        ("Antecedentes",           _g('antecedentes') or _g('antecedentes_medicos'), C_GRIS_T),
        ("Antecedentes familiares",_g('antecedentes_familiares'), C_GRIS_T),
        ("Tratamiento actual",     _g('tratamiento_actual') or _g('tratamiento'), C_GRIS_T),
        ("Medicamentos actuales",  _g('medicamentos') or _g('medicamentos_actuales'), C_AMBER_L),
        ("Notas adicionales",      _g('notas_adicionales') or _g('notas'), C_GRIS_T),
    ]
    aler = _g('alergias') or _g('alergias_medicamentos')
    campos_a_mostrar = [(lbl, val, bg) for lbl, val, bg in campos_clinicos if val]
    if aler:
        campos_a_mostrar.append(("⚠ ALERGIAS / CONTRAINDICACIONES", aler, C_ROJO_L))

    if campos_a_mostrar:
        if y < Y_BOTTOM + 3*cm:
            _pie(c, pg, helpers['total_pg'][0], helpers['fecha'])
            pages_data.append(pg)
            c, y, pg = make_page()

        y -= 0.1*cm
        y = _titulo_seccion(c, y, "1.3 Información Clínica Adicional", color=C_TEAL)

        def _kv_largo(c, y, label, valor, bg_color):
            if not valor:
                return y
            txt = str(valor)
            words_l = txt.split()
            lines_l, line_l = [], ""
            mw_l = CW - 2.8*cm
            for w_ in words_l:
                test = (line_l + " " + w_).strip()
                if stringWidth(test, "Helvetica", 7.8) <= mw_l:
                    line_l = test
                else:
                    if line_l: lines_l.append(line_l)
                    line_l = w_
            if line_l: lines_l.append(line_l)

            h_box = max(0.68*cm, len(lines_l) * 0.38*cm + 0.36*cm)
            if y - h_box < Y_BOTTOM:
                return None  # señal de página nueva

            c.setFillColor(bg_color)
            c.roundRect(ML, y - h_box, CW, h_box, 4, fill=1, stroke=0)
            c.setFont("Helvetica-Bold", 6.8)
            lbl_col = C_TEAL if bg_color == C_TEAL_L else (C_ROJO if bg_color == C_ROJO_L else C_TSEC)
            c.setFillColor(lbl_col)
            c.drawString(ML + 0.3*cm, y - 0.26*cm, label.upper() + ":")
            c.setFont("Helvetica", 7.8)
            c.setFillColor(C_TEXTO)
            yt = y - 0.26*cm
            for ln in lines_l:
                c.drawString(ML + 2.7*cm, yt, ln)
                yt -= 0.38*cm
            return y - h_box - 0.14*cm

        for lbl, val, bg in campos_a_mostrar:
            resultado = _kv_largo(c, y, lbl, val, bg)
            if resultado is None:
                _pie(c, pg, helpers['total_pg'][0], helpers['fecha'])
                pages_data.append(pg)
                c, y, pg = make_page()
                y = _titulo_seccion(c, y, "1.3 Información Clínica (cont.)", color=C_TEAL)
                resultado = _kv_largo(c, y, lbl, val, bg)
            y = resultado if resultado is not None else y

    _pie(c, pg, helpers['total_pg'][0], helpers['fecha'])
    pages_data.append(pg)

    # Limpiar archivo temporal si se descargó de Cloudinary
    try:
        import tempfile
        if foto_path and foto_path.startswith(tempfile.gettempdir()):
            os.unlink(foto_path)
    except Exception:
        pass



def _seccion_financiero(pages_data, ctx, helpers):
    make_page = helpers['new_page']
    pac    = ctx.get('paciente')
    datos  = ctx.get('datos') or {}
    stats  = datos.get('stats') or {}
    cc     = getattr(pac, 'cuenta_corriente', None) if pac else None

    c, y, pg = make_page()
    y = _titulo_seccion(c, y, "2. Resumen Financiero Global (Cuenta Corriente)")
    y = _explicacion(c, y,
        "La cuenta corriente refleja el estado financiero total del paciente con el centro, "
        "incluyendo todos los períodos. Los datos del período filtrado se muestran en la sección 2.2.")

    if cc:
        items_cc = [
            ("Saldo Actual",        _bs(cc.saldo_actual),          "A favor (+) / Deuda (-)",
             C_VERDE if cc.saldo_actual >= 0 else C_ROJO),
            ("Total Pagado",        _bs(cc.total_pagado),          "Pagos históricos",          C_MED),
            ("Consumido Actual",    _bs(cc.total_consumido_actual), "Sin programadas",           C_AMBER),
            ("Consumido Real",      _bs(cc.total_consumido_real),   "Con compromisos futuros",   C_TSEC),
        ]
        y = _grilla(c, y, items_cc, cols=4, box_h=1.65 * cm)

        items_cc2 = [
            ("Pag. Sesiones",       _bs(cc.pagos_sesiones),        "Aplicados a sesiones",      C_VERDE),
            ("Pag. Mensualidades",  _bs(cc.pagos_mensualidades),   "Aplicados a mensualidades", C_TEAL),
            ("Pag. Proyectos",      _bs(cc.pagos_proyectos),       "Aplicados a proyectos",     C_MED),
            ("Crédito Disponible",  _bs(cc.pagos_adelantados),     "Saldo adelantado",          C_MORADO),
        ]
        y = _grilla(c, y, items_cc2, cols=4, box_h=1.65 * cm)

        items_cc3 = [
            ("Total Mensualidades", _bs(cc.total_mensualidades),   "Activas/completadas",       C_TEAL),
            ("Total Proyectos",     _bs(cc.total_proyectos_real),  "En progreso/finalizados",   C_MED),
            ("Devoluciones",        _bs(cc.total_devoluciones),    "Reintegros realizados",     C_ROJO),
            ("Saldo Real",          _bs(cc.saldo_real),            "Incl. compromisos",         C_TSEC),
        ]
        y = _grilla(c, y, items_cc3, cols=4, box_h=1.65 * cm)
    else:
        y = _explicacion(c, y, "No se encontró cuenta corriente para este paciente.")

    # 2.2 — Financiero del período
    y -= 0.2 * cm
    y = _titulo_seccion(c, y, f"2.2 Financiero del Período Filtrado", color=C_TEAL)

    items_per = [
        ("Total Cobrado",   _bs(stats.get('total_cobrado', 0)),  "Monto generado en sesiones", C_MED),
        ("Total Pagado",    _bs(stats.get('total_pagado', 0)),   "Pagado por las sesiones",    C_VERDE),
        ("Saldo Pendiente", _bs(stats.get('saldo_pendiente', 0)),"Por cobrar del período",     C_AMBER),
        ("Tasa de Pago",    _pct(datos.get('tasa_pago', 0)),     f"{stats.get('sesiones_pagadas',0)} pagadas / {stats.get('sesiones_pendientes',0)} pend.", C_TEAL),
    ]
    y = _grilla(c, y, items_per, cols=4, box_h=1.65 * cm)

    # Desglose por sucursal
    fin_suc = datos.get('financiero_por_sucursal') or []
    if fin_suc:
        y -= 0.2 * cm
        y = _titulo_seccion(c, y, "2.3 Desglose por Sucursal", color=C_MORADO)
        headers_fs = ["Sucursal", "Consumido", "Pagado", "Saldo", "Sesiones", "Mensualidades", "Proyectos"]
        col_ws_fs  = [4.0*cm, 2.4*cm, 2.4*cm, 2.4*cm, 2.0*cm, 2.8*cm, 2.0*cm]
        rows_fs = []
        for sf in fin_suc:
            rows_fs.append([
                str(_attr(sf, 'sucursal_nombre', '—')),
                _bs(_attr(sf, 'consumido', 0)),
                _bs(_attr(sf, 'pagado', 0)),
                _bs(_attr(sf, 'saldo', 0)),
                str(_attr(sf, 'num_sesiones', 0)),
                str(_attr(sf, 'num_mensualidades', 0)),
                str(_attr(sf, 'num_proyectos', 0)),
            ])
        y = _tabla(c, y, headers_fs, rows_fs, col_ws_fs)

    _pie(c, pg, helpers['total_pg'][0], helpers['fecha'])
    pages_data.append(pg)


# ─────────────────────────────────────────────────────────────────────
# SECCIÓN 3 — ESTADÍSTICAS DE ASISTENCIA
# ─────────────────────────────────────────────────────────────────────

def _seccion_asistencia(pages_data, ctx, helpers):
    make_page = helpers['new_page']
    datos  = ctx.get('datos') or {}
    stats  = datos.get('stats') or {}

    c, y, pg = make_page()
    y = _titulo_seccion(c, y, "3. Estadísticas de Asistencia del Período")
    y = _explicacion(c, y,
        "Conteo y porcentajes de todos los estados registrados en el período filtrado. "
        "La tasa de asistencia se calcula sobre las sesiones que debían realizarse "
        "(realizadas + retrasos + faltas + permisos).")

    total = _num(stats.get('total_sesiones', 0))
    real  = _num(stats.get('realizadas', 0))
    ret   = _num(stats.get('retrasos', 0))
    falt  = _num(stats.get('faltas', 0))
    perm  = _num(stats.get('permisos', 0))
    canc  = _num(stats.get('canceladas', 0))
    repro = _num(stats.get('reprogramadas', 0))
    progr = _num(stats.get('programadas', 0))

    items1 = [
        ("Total Sesiones",  str(total),       "En el período",              C_MED),
        ("Realizadas",      str(real),         "Sin retraso",                C_VERDE),
        ("Con Retraso",     str(ret),          "Llegaron tarde",             C_AMBER),
        ("Faltas",          str(falt),         "Sin asistir",                C_ROJO),
    ]
    items2 = [
        ("Permisos",        str(perm),         "Justificados",               C_MORADO),
        ("Canceladas",      str(canc),         "Por el centro",              C_MUTED),
        ("Reprogramadas",   str(repro),        "Reagendadas",                C_TEAL),
        ("Programadas",     str(progr),        "Pendientes",                 C_PRI),
    ]
    y = _grilla(c, y, items1, cols=4, box_h=1.65 * cm)
    y = _grilla(c, y, items2, cols=4, box_h=1.65 * cm)

    # Tasas
    y -= 0.2 * cm
    y = _titulo_seccion(c, y, "3.2 Tasas de Rendimiento", color=C_VERDE)

    base_asis = real + ret + falt + perm
    base_punt = real + ret
    tasa_asis = round(100 * (real + ret) / base_asis, 1) if base_asis else 0
    tasa_punt = round(100 * real / base_punt, 1)          if base_punt else 0
    tasa_falt = round(100 * falt / base_asis, 1)          if base_asis else 0
    tasa_perm = round(100 * perm / base_asis, 1)          if base_asis else 0
    tasa_pago = float(datos.get('tasa_pago', 0))

    items_t = [
        ("Tasa Asistencia",  f"{tasa_asis}%",  "Realizadas / base",           C_VERDE),
        ("Puntualidad",      f"{tasa_punt}%",  "Sin retraso / realizadas",    C_MED),
        ("Tasa Faltas",      f"{tasa_falt}%",  "Faltas / base",               C_ROJO),
        ("Tasa Permisos",    f"{tasa_perm}%",  "Permisos / base",             C_AMBER),
        ("Tasa de Pago",     f"{tasa_pago:.1f}%", "Sesiones cobradas",        C_TEAL),
    ]
    y = _grilla(c, y, items_t, cols=5, box_h=1.65 * cm)

    # Por servicio
    por_svc = list(datos.get('por_servicio') or [])
    if por_svc:
        y -= 0.2 * cm
        y = _titulo_seccion(c, y, "3.3 Desglose por Tipo de Servicio")
        headers_s = ["Servicio", "Total", "Realizadas", "Faltas", "Monto Bs."]
        col_ws_s  = [6.5*cm, 1.8*cm, 2.5*cm, 1.8*cm, 5.4*cm]
        rows_s = [
            [str(s.get('servicio__nombre', '—')),
             str(_num(s.get('cantidad', 0))),
             str(_num(s.get('sesiones_realizadas', 0))),
             str(_num(s.get('sesiones_falta', 0))),
             _bs(s.get('monto_total', 0))]
            for s in por_svc
        ]
        y = _tabla(c, y, headers_s, rows_s, col_ws_s)

    # Por profesional
    por_pro = list(datos.get('por_profesional') or [])
    if por_pro and y > Y_BOTTOM + 4 * cm:
        y -= 0.2 * cm
        y = _titulo_seccion(c, y, "3.4 Sesiones Realizadas por Profesional")
        headers_p = ["Profesional", "Sesiones", "Monto Total Bs."]
        col_ws_p  = [9.0*cm, 3.5*cm, 5.5*cm]
        rows_p = [
            [f"{p.get('profesional__nombre','')} {p.get('profesional__apellido','')}".strip(),
             str(_num(p.get('cantidad', 0))),
             _bs(p.get('monto_total', 0))]
            for p in por_pro
        ]
        y = _tabla(c, y, headers_p, rows_p, col_ws_p)

    _pie(c, pg, helpers['total_pg'][0], helpers['fecha'])
    pages_data.append(pg)


# ─────────────────────────────────────────────────────────────────────
# SECCIÓN 4 — EVOLUCIÓN MENSUAL
# ─────────────────────────────────────────────────────────────────────

def _seccion_evolucion(pages_data, ctx, helpers):
    make_page  = helpers['new_page']
    grafico    = ctx.get('grafico_data') or {}
    labels     = grafico.get('labels', [])
    realizadas = grafico.get('realizadas', [])
    faltas     = grafico.get('faltas', [])
    retrasos   = grafico.get('retrasos', [])
    monto      = grafico.get('monto', [])

    if not labels:
        return

    c, y, pg = make_page()
    y = _titulo_seccion(c, y, "4. Evolución Mensual de Sesiones y Facturación")
    y = _explicacion(c, y,
        "Desglose mes a mes de las sesiones y el monto facturado en el período seleccionado. "
        "Permite identificar tendencias de asistencia y estacionalidades.")

    headers = ["Mes", "Realizadas", "Con Retraso", "Faltas", "Total Ses.", "Monto Bs."]
    col_ws  = [3.2*cm, 2.5*cm, 2.5*cm, 2.0*cm, 2.5*cm, 5.3*cm]
    rows = []
    for i, lbl in enumerate(labels):
        r  = realizadas[i] if i < len(realizadas) else 0
        f  = faltas[i]     if i < len(faltas)     else 0
        rt = retrasos[i]   if i < len(retrasos)   else 0
        m  = monto[i]      if i < len(monto)       else 0
        rows.append([lbl, str(r), str(rt), str(f), str(r + rt + f), _bs(m)])
    # Totales
    rows.append([
        "TOTAL",
        str(sum(realizadas)),
        str(sum(retrasos)),
        str(sum(faltas)),
        str(sum(realizadas) + sum(retrasos) + sum(faltas)),
        _bs(sum(monto)),
    ])
    y = _tabla(c, y, headers, rows, col_ws)

    _pie(c, pg, helpers['total_pg'][0], helpers['fecha'])
    pages_data.append(pg)


# ─────────────────────────────────────────────────────────────────────
# SECCIÓN 5 — PROYECTOS
# ─────────────────────────────────────────────────────────────────────

def _seccion_proyectos(pages_data, ctx, helpers):
    make_page = helpers['new_page']
    datos     = ctx.get('datos') or {}
    proyectos = list(datos.get('proyectos_todos') or datos.get('proyectos') or [])
    p_stats   = datos.get('proyectos_stats') or {}

    if not proyectos and not p_stats.get('total'):
        return

    c, y, pg = make_page()
    y = _titulo_seccion(c, y, "5. Proyectos Terapéuticos")

    # Resumen
    items = [
        ("Total Proyectos", str(_num(p_stats.get('total', 0))),      "Registrados",              C_TEAL),
        ("Activos",         str(_num(p_stats.get('activos', 0))),     "En curso / planificados",  C_MED),
        ("Finalizados",     str(_num(p_stats.get('finalizados', 0))), "Completados",              C_VERDE),
        ("Monto Total",     _bs(p_stats.get('monto_total', 0)),       "Valor de todos",           C_AMBER),
    ]
    y = _grilla(c, y, items, cols=4, box_h=1.55 * cm)

    if proyectos:
        y -= 0.1 * cm
        headers = ["Código", "Nombre / Servicio", "Profesional", "Estado", "Inicio", "Costo Bs.", "Sesiones"]
        col_ws  = [2.2*cm, 4.2*cm, 3.5*cm, 2.2*cm, 1.9*cm, 2.3*cm, 1.7*cm]
        rows = []
        for p in proyectos:
            prof = getattr(p, 'profesional_responsable', None)
            prof_n = f"{getattr(prof,'nombre','')} {getattr(prof,'apellido','')}".strip() if prof else '—'
            svc_b  = getattr(p, 'servicio_base', None)
            svc_n  = getattr(svc_b, 'nombre', '—') or '—'
            nombre = getattr(p, 'nombre', '') or svc_n
            fi     = getattr(p, 'fecha_inicio', None)
            rows.append([
                getattr(p, 'codigo', str(p.pk))[:10],
                nombre[:30],
                prof_n[:22],
                getattr(p, 'estado', '—')[:10],
                fi.strftime('%d/%m/%Y') if fi else '—',
                _bs(getattr(p, 'costo_total', 0)),
                str(getattr(p, 'num_sesiones', 0) or '—'),
            ])
        y = _tabla(c, y, headers, rows, col_ws)

    _pie(c, pg, helpers['total_pg'][0], helpers['fecha'])
    pages_data.append(pg)


# ─────────────────────────────────────────────────────────────────────
# SECCIÓN 6 — MENSUALIDADES
# ─────────────────────────────────────────────────────────────────────

def _seccion_mensualidades(pages_data, ctx, helpers):
    make_page    = helpers['new_page']
    datos        = ctx.get('datos') or {}
    mensualidades = list(datos.get('mensualidades_todas') or datos.get('mensualidades') or [])
    m_stats      = datos.get('mensualidades_stats') or {}

    if not mensualidades and not m_stats.get('total'):
        return

    c, y, pg = make_page()
    y = _titulo_seccion(c, y, "6. Mensualidades")

    items = [
        ("Total",    str(_num(m_stats.get('total', 0))),   "Registradas",  C_TEAL),
        ("Activas",  str(_num(m_stats.get('activas', 0))), "En curso",     C_VERDE),
        ("Monto",    _bs(m_stats.get('monto_total', 0)),   "Total cuotas", C_AMBER),
    ]
    y = _grilla(c, y, items, cols=3, box_h=1.55 * cm)

    if mensualidades:
        headers = ["Período", "Sucursal", "Estado", "Costo Bs.", "Pagado Bs.", "Pend. Bs.", "Sesiones"]
        col_ws  = [2.4*cm, 3.5*cm, 2.0*cm, 2.5*cm, 2.5*cm, 2.5*cm, 2.6*cm]
        rows = []
        for m in mensualidades:
            mes  = getattr(m, 'mes', None)
            anio = getattr(m, 'anio', None)
            per  = f"{MESES_CORTO[mes] if mes else '?'}/{anio or '?'}"
            suc  = getattr(m, 'sucursal', None)
            suc_n = getattr(suc, 'nombre', '—') if suc else '—'
            try:
                pagado_n = float(m.pagado_neto)
            except Exception:
                pagado_n = 0
            costo = float(getattr(m, 'costo_mensual', 0) or 0)
            pend  = max(0, costo - pagado_n)
            rows.append([
                per,
                suc_n[:20],
                getattr(m, 'estado', '—')[:10],
                _bs(costo),
                _bs(pagado_n),
                _bs(pend),
                str(getattr(m, 'num_sesiones', '—') or '—'),
            ])
        y = _tabla(c, y, headers, rows, col_ws)

    _pie(c, pg, helpers['total_pg'][0], helpers['fecha'])
    pages_data.append(pg)


# ─────────────────────────────────────────────────────────────────────
# SECCIÓN 7 — PAGOS RECIBIDOS (contado + crédito separados)
# ─────────────────────────────────────────────────────────────────────

def _seccion_pagos(pages_data, ctx, helpers):
    make_page  = helpers['new_page']
    datos      = ctx.get('datos') or {}
    p_stats    = datos.get('pagos_stats') or {}

    # Listas separadas — primero intentar desde contexto directo, luego desde datos
    pagos_contado = list(ctx.get('pagos_contado') or [])
    pagos_credito = list(ctx.get('pagos_credito') or [])

    # Si no vienen separados, reconstruir desde pagos_recientes
    if not pagos_contado and not pagos_credito:
        todos = list(ctx.get('pagos_recientes') or [])
        NOMBRE_CREDITO = "Uso de Crédito"
        pagos_contado = [p for p in todos if p.metodo_pago and p.metodo_pago.nombre != NOMBRE_CREDITO]
        pagos_credito = [p for p in todos if p.metodo_pago and p.metodo_pago.nombre == NOMBRE_CREDITO]

    if not pagos_contado and not pagos_credito:
        return

    c, y, pg = make_page()
    y = _titulo_seccion(c, y, "7. Pagos Recibidos en el Período")
    y = _explicacion(c, y,
        "Se distinguen los pagos reales al contado (efectivo, QR, transferencia) "
        "de los descuentos de crédito acumulado previamente por el paciente.")

    # ── Resumen en grilla ──────────────────────────────────────────────
    total_contado = sum(Decimal(str(p.monto or 0)) for p in pagos_contado)
    total_credito = sum(Decimal(str(p.monto or 0)) for p in pagos_credito)
    total_global  = total_contado + total_credito

    # Agrupar contado por método
    from collections import defaultdict as _ddict
    _por_met = _ddict(lambda: Decimal('0'))
    for p in pagos_contado:
        _por_met[p.metodo_pago.nombre] += Decimal(str(p.monto or 0))
    met_txt = '  ·  '.join(f"{k}: {_bs(v)}" for k, v in sorted(_por_met.items(), key=lambda x: -x[1]))

    kpis = [
        ("Total Recibido",   _bs(total_global),  f"{len(pagos_contado)+len(pagos_credito)} recibos", C_MED),
        ("Pagos al Contado", _bs(total_contado), f"{len(pagos_contado)} recibos",                    C_VERDE),
        ("Uso de Crédito",   _bs(total_credito), f"{len(pagos_credito)} aplicaciones",               C_MORADO),
    ]
    y = _grilla(c, y, kpis, cols=3, box_h=1.55*cm)

    # Desglose por método de pago (contado)
    if _por_met:
        y -= 0.1*cm
        c.setFont("Helvetica-Bold", 7)
        c.setFillColor(C_TSEC)
        c.drawString(ML, y, "Desglose por método de pago (contado):")
        y -= 0.35*cm
        gap_m = 0.3*cm
        n_met = len(_por_met)
        bw_m  = (CW - (n_met - 1) * gap_m) / max(n_met, 1)
        bw_m  = min(bw_m, 5.0*cm)
        for i, (met_n, met_v) in enumerate(sorted(_por_met.items(), key=lambda x: -x[1])):
            _metrica_box(c, ML + i*(bw_m + gap_m), y, bw_m, 1.45*cm,
                         met_n, _bs(met_v), f"{sum(1 for p in pagos_contado if p.metodo_pago and p.metodo_pago.nombre == met_n)} recibos",
                         C_VERDE)
        y -= 1.45*cm + 0.3*cm

    # ── Tabla pagos al contado ─────────────────────────────────────────
    def _tabla_pagos(c, y, pg, pagos, titulo_sec, color_titulo, color_monto):
        if not pagos:
            return y, pg

        # ¿Cabe el título + encabezado?
        if y < Y_BOTTOM + 2.5*cm:
            _pie(c, pg, helpers['total_pg'][0], helpers['fecha'])
            pages_data.append(pg)
            c, y, pg = make_page()

        y = _titulo_seccion(c, y, titulo_sec, color=color_titulo)

        headers = ["Recibo", "Fecha", "Concepto", "Método", "Monto Bs."]
        col_ws  = [2.5*cm, 2.2*cm, 6.5*cm, 3.5*cm, 3.3*cm]
        row_h   = 0.50*cm
        y = _tabla_header(c, y, headers, col_ws)

        total_sec = Decimal('0')
        for ri, pago in enumerate(pagos):
            if y < Y_BOTTOM + row_h:
                _pie(c, pg, helpers['total_pg'][0], helpers['fecha'])
                pages_data.append(pg)
                c, y, pg = make_page()
                y = _titulo_seccion(c, y, titulo_sec + " (cont.)", color=color_titulo)
                y = _tabla_header(c, y, headers, col_ws)

            if pago.sesion:
                concepto = f"Sesión: {pago.sesion.servicio.nombre if pago.sesion.servicio else '—'}"
            elif pago.proyecto:
                concepto = f"Proyecto: {pago.proyecto.servicio_base.nombre if pago.proyecto.servicio_base else '—'}"
            elif pago.mensualidad:
                concepto = f"Mensualidad {getattr(pago.mensualidad, 'periodo_display', '') or ''}"
            else:
                concepto = "Adelanto / Crédito"

            metodo_n = str(pago.metodo_pago.nombre if pago.metodo_pago else '—')
            monto_v  = Decimal(str(pago.monto or 0))
            total_sec += monto_v

            row = [
                str(pago.numero_recibo),
                pago.fecha_pago.strftime('%d/%m/%Y') if pago.fecha_pago else '—',
                concepto[:42],
                metodo_n[:20],
                _bs(monto_v),
            ]

            if ri % 2 == 0:
                c.setFillColor(C_GRIS_T)
                c.rect(ML, y - row_h, sum(col_ws), row_h, fill=1, stroke=0)
            c.setStrokeColor(C_GRIS_B)
            c.setLineWidth(0.15)
            c.line(ML, y - row_h, ML + sum(col_ws), y - row_h)
            xc = ML
            for ci, cell in enumerate(row):
                c.setFont("Helvetica", 7.5)
                c.setFillColor(C_TEXTO if ci != 4 else color_monto)
                if ci == 4:
                    c.setFont("Helvetica-Bold", 7.5)
                c.drawString(xc + 0.2*cm, y - row_h + 0.13*cm, str(cell))
                xc += col_ws[ci]
            y -= row_h

        # Fila total
        c.setFillColor(C_GRIS_H)
        c.rect(ML, y - row_h, sum(col_ws), row_h, fill=1, stroke=0)
        c.setFont("Helvetica-Bold", 8)
        c.setFillColor(C_TEXTO)
        c.drawString(ML + 0.25*cm, y - row_h + 0.15*cm, f"TOTAL ({len(pagos)} recibos)")
        c.setFillColor(color_monto)
        c.drawRightString(ML + sum(col_ws) - 0.25*cm, y - row_h + 0.15*cm, _bs(total_sec))
        y -= row_h + 0.25*cm

        return y, pg

    y, pg = _tabla_pagos(c, y, pg, pagos_contado,
                         "7.1 Pagos al Contado (Efectivo / QR / Transferencia)",
                         C_VERDE, C_VERDE)
    y, pg = _tabla_pagos(c, y, pg, pagos_credito,
                         "7.2 Uso de Crédito Acumulado",
                         C_MORADO, C_MORADO)

    _pie(c, pg, helpers['total_pg'][0], helpers['fecha'])
    pages_data.append(pg)


# ─────────────────────────────────────────────────────────────────────
# SECCIÓN 7.3 — DEVOLUCIONES
# ─────────────────────────────────────────────────────────────────────

def _seccion_devoluciones(pages_data, ctx, helpers):
    make_page    = helpers['new_page']
    devoluciones = list(ctx.get('devoluciones') or [])

    if not devoluciones:
        return

    c, y, pg = make_page()
    y = _titulo_seccion(c, y, "7.3 Devoluciones Realizadas en el Período", color=C_ROJO)
    y = _explicacion(c, y,
        "Reintegros efectuados al paciente durante el período. "
        "El monto neto recibido = pagos al contado − devoluciones.")

    # ── Resumen ────────────────────────────────────────────────────────
    total_dev = sum(Decimal(str(getattr(d, 'monto', 0) or 0)) for d in devoluciones)
    datos     = ctx.get('datos') or {}
    p_stats   = datos.get('pagos_stats') or {}
    contado   = Decimal(str(p_stats.get('contado_monto', 0) or 0))
    neto      = contado - total_dev

    kpis = [
        ("Devoluciones",    _bs(total_dev), f"{len(devoluciones)} registro(s)",   C_ROJO),
        ("Pagado Contado",  _bs(contado),   "Efectivo / QR / Transf.",            C_VERDE),
        ("Neto Recibido",   _bs(neto),      "Contado − Devoluciones",             C_MED if neto >= 0 else C_ROJO),
    ]
    y = _grilla(c, y, kpis, cols=3, box_h=1.45*cm)

    # ── Tabla ──────────────────────────────────────────────────────────
    headers = ["N° Dev.", "Fecha", "Concepto", "Método", "Motivo", "Monto Bs."]
    col_ws  = [2.3*cm, 2.0*cm, 4.5*cm, 2.8*cm, 4.9*cm, 2.5*cm]
    row_h   = 0.50*cm
    y = _tabla_header(c, y, headers, col_ws)

    for ri, dev in enumerate(devoluciones):
        if y < _LS_Y_BOTTOM + row_h if False else y < Y_BOTTOM + row_h:
            _pie(c, pg, helpers['total_pg'][0], helpers['fecha'])
            pages_data.append(pg)
            c, y, pg = make_page()
            y = _titulo_seccion(c, y, "7.3 Devoluciones (cont.)", color=C_ROJO)
            y = _tabla_header(c, y, headers, col_ws)

        # Concepto
        proy  = getattr(dev, 'proyecto',    None)
        mens  = getattr(dev, 'mensualidad', None)
        if proy:
            sb = getattr(proy, 'servicio_base', None)
            concepto = f"Proy: {getattr(sb,'nombre','—') if sb else getattr(proy,'codigo','—')}"
        elif mens:
            concepto = f"Mens: {getattr(mens,'periodo_display',None) or getattr(mens,'codigo','—')}"
        else:
            concepto = "Crédito / Adelanto"

        metodo_dev = getattr(dev, 'metodo_devolucion', None)
        metodo_n   = getattr(metodo_dev, 'nombre', '—') if metodo_dev else '—'
        motivo_txt = str(getattr(dev, 'motivo', '') or '—')
        fecha_d    = getattr(dev, 'fecha_devolucion', None)
        monto_d    = Decimal(str(getattr(dev, 'monto', 0) or 0))
        num_dev    = str(getattr(dev, 'numero_devolucion', '—') or '—')

        row = [
            num_dev[:12],
            fecha_d.strftime('%d/%m/%Y') if fecha_d else '—',
            concepto[:30],
            metodo_n[:18],
            motivo_txt[:35],
            _bs(monto_d),
        ]

        # Fondo rojo suave
        c.setFillColor(C_ROJO_L)
        c.rect(ML, y - row_h, sum(col_ws), row_h, fill=1, stroke=0)
        c.setStrokeColor(C_GRIS_B)
        c.setLineWidth(0.15)
        c.line(ML, y - row_h, ML + sum(col_ws), y - row_h)

        xc = ML
        for ci, cell in enumerate(row):
            is_monto = (ci == 5)
            c.setFont("Helvetica-Bold" if is_monto else "Helvetica", 7.5)
            c.setFillColor(C_ROJO if is_monto else C_TEXTO)
            txt = str(cell)
            mw  = col_ws[ci] - 0.4*cm
            while stringWidth(txt, "Helvetica-Bold" if is_monto else "Helvetica", 7.5) > mw and len(txt) > 1:
                txt = txt[:-2] + '.'
            c.drawString(xc + 0.2*cm, y - row_h + 0.13*cm, txt)
            xc += col_ws[ci]
        y -= row_h

    # Fila total
    c.setFillColor(C_ROJO_L)
    c.rect(ML, y - row_h, sum(col_ws), row_h, fill=1, stroke=0)
    c.setFont("Helvetica-Bold", 8)
    c.setFillColor(C_ROJO)
    c.drawString(ML + 0.25*cm, y - row_h + 0.15*cm, f"TOTAL DEVOLUCIONES ({len(devoluciones)})")
    c.drawRightString(ML + sum(col_ws) - 0.25*cm, y - row_h + 0.15*cm, f"− {_bs(total_dev)}")
    y -= row_h + 0.2*cm

    _pie(c, pg, helpers['total_pg'][0], helpers['fecha'])
    pages_data.append(pg)


# ─────────────────────────────────────────────────────────────────────
# SECCIÓN 8 — DETALLE COMPLETO DE SESIONES (landscape)
# ─────────────────────────────────────────────────────────────────────

def _encabezado_ls(c, pg, total_pg, titulo, nombre_pac, periodo_txt, fecha):
    _grad(c, 0, _LS_H - 1.8 * cm, _LS_W, 1.8 * cm, C_OSC, C_PRI)
    c.setFillColor(C_BLANCO)
    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(_LS_ML, _LS_H - 0.95 * cm, NOMBRE_CENTRO)
    c.setFont("Helvetica", 7)
    c.drawString(_LS_ML, _LS_H - 1.45 * cm, f"Paciente: {nombre_pac}  |  Período: {periodo_txt}")
    c.setFont("Helvetica-Bold", 8)
    c.drawRightString(_LS_W - _LS_MR, _LS_H - 0.95 * cm, titulo)
    c.setFont("Helvetica", 7)
    c.drawRightString(_LS_W - _LS_MR, _LS_H - 1.45 * cm, f"Pag. {pg} de {total_pg}  |  {fecha}")
    return _LS_H - 1.8 * cm - 0.3 * cm


def _pie_ls(c, pg, total_pg, fecha):
    py = 1.2 * cm + 0.1 * cm
    c.setStrokeColor(C_GRIS_B)
    c.setLineWidth(0.3)
    c.line(_LS_ML, py + 0.6 * cm, _LS_W - _LS_MR, py + 0.6 * cm)
    c.setFont("Helvetica", 6)
    c.setFillColor(C_MUTED)
    c.drawString(_LS_ML, py + 0.22 * cm,
                 f"{NOMBRE_CENTRO}  |  Detalle de sesiones  |  CONFIDENCIAL")
    c.drawRightString(_LS_W - _LS_MR, py + 0.22 * cm, f"Pag. {pg} / {total_pg}")


def _seccion_detalle_sesiones(pages_data, ctx, helpers):
    sesiones = list(ctx.get('sesiones_completas') or [])
    if not sesiones:
        return

    fecha      = helpers['fecha']
    total_pg   = helpers['total_pg']
    cv         = helpers['canvas']
    pc_ref     = helpers['page_counter']
    pac        = ctx.get('paciente')
    nombre_pac = str(pac) if pac else '—'
    periodo_txt = helpers.get('periodo_txt', '')

    titulo_ls = f"8. DETALLE COMPLETO DE SESIONES ({len(sesiones)} registros)"

    # Columnas landscape: suma = _LS_CW ≈ 26.7 cm
    # Fecha  Hora   Servicio   Profesional  Sucursal  Estado   Costo   Pagado   Pend.  Ref.
    col_ws = [1.9*cm, 1.3*cm, 4.2*cm, 4.0*cm, 3.0*cm, 2.2*cm, 2.2*cm, 2.2*cm, 2.2*cm, 2.4*cm]
    headers = ["FECHA", "HORA", "SERVICIO", "PROFESIONAL", "SUCURSAL",
               "ESTADO", "COSTO", "PAGADO", "PEND.", "REFERENCIA"]

    row_h = 0.46 * cm

    def _nueva_pg_ls():
        pc_ref[0] += 1
        pg = pc_ref[0]
        cv.showPage()
        cv.setPageSize(_landscape(A4))
        cv.setFillColor(C_FONDO_PAG)
        cv.rect(0, 0, _LS_W, _LS_H, fill=1, stroke=0)
        y = _encabezado_ls(cv, pg, total_pg[0], titulo_ls, nombre_pac, periodo_txt, fecha)
        return cv, y, pg

    def _hdr_tabla(cv, y):
        cv.setFillColor(C_PRI)
        cv.roundRect(_LS_ML, y - row_h, sum(col_ws), row_h, 3, fill=1, stroke=0)
        xc = _LS_ML
        for i, h in enumerate(headers):
            cv.setFont("Helvetica-Bold", 6.2)
            cv.setFillColor(C_BLANCO)
            cv.drawString(xc + 0.15 * cm, y - row_h + 0.14 * cm, h)
            xc += col_ws[i]
        return y - row_h

    cv, y, pg = _nueva_pg_ls()
    y = _hdr_tabla(cv, y)

    for ri, s in enumerate(sesiones):
        if y < _LS_Y_BOTTOM + row_h:
            _pie_ls(cv, pg, total_pg[0], fecha)
            pages_data.append(pg)
            cv, y, pg = _nueva_pg_ls()
            y = _hdr_tabla(cv, y)

        if ri % 2 == 0:
            cv.setFillColor(C_GRIS_T)
            cv.rect(_LS_ML, y - row_h, sum(col_ws), row_h, fill=1, stroke=0)
        cv.setStrokeColor(C_GRIS_B)
        cv.setLineWidth(0.12)
        cv.line(_LS_ML, y - row_h, _LS_ML + sum(col_ws), y - row_h)

        pac_s  = getattr(s, 'paciente',    None)
        svc    = getattr(s, 'servicio',    None)
        prof   = getattr(s, 'profesional', None)
        suc    = getattr(s, 'sucursal',    None)
        mens   = getattr(s, 'mensualidad', None)
        proy   = getattr(s, 'proyecto',    None)
        estado = getattr(s, 'estado', '')
        fecha_s = getattr(s, 'fecha', None)
        hora_s  = getattr(s, 'hora_inicio', None)
        costo   = float(getattr(s, 'monto_cobrado', 0) or 0)
        pagado  = float(getattr(s, 'total_pagado_sesion', 0) or 0)
        pend    = max(0.0, costo - pagado)

        ref = getattr(mens, 'codigo', None) or getattr(proy, 'codigo', None) or '—'

        celdas = [
            fecha_s.strftime('%d/%m/%Y') if fecha_s else '—',
            hora_s.strftime('%H:%M')     if hora_s  else '—',
            getattr(svc,  'nombre', '—') or '—',
            f"{getattr(prof,'nombre','')} {getattr(prof,'apellido','')}".strip() or '—',
            getattr(suc,  'nombre', '—') or '—',
            ESTADO_LABEL.get(estado, estado),
            _bs(costo),
            _bs(pagado),
            _bs(pend),
            ref[:12],
        ]
        est_col = ESTADO_COLOR.get(estado, C_TEXTO)

        xc = _LS_ML
        for ci, celda in enumerate(celdas):
            is_est = (ci == 5)
            font   = "Helvetica-Bold" if is_est else "Helvetica"
            fc     = est_col if is_est else C_TEXTO
            cv.setFont(font, 6.5)
            cv.setFillColor(fc)
            txt = str(celda)
            mw  = col_ws[ci] - 0.35 * cm
            while stringWidth(txt, font, 6.5) > mw and len(txt) > 1:
                txt = txt[:-2] + '.'
            cv.drawString(xc + 0.15 * cm, y - row_h + 0.12 * cm, txt)
            xc += col_ws[ci]
        y -= row_h

    cv.setStrokeColor(C_GRIS_B)
    cv.setLineWidth(0.4)
    cv.line(_LS_ML, y, _LS_ML + sum(col_ws), y)
    _pie_ls(cv, pg, total_pg[0], fecha)
    pages_data.append(pg)
    helpers['page_counter'][0] = pg


# ─────────────────────────────────────────────────────────────────────
# FUNCIÓN PRINCIPAL
# ─────────────────────────────────────────────────────────────────────

def generar_informe_paciente_pdf(context):
    """
    Genera el informe completo individual de paciente en PDF.
    context debe incluir las claves que popula reporte_paciente() en views.py,
    más las keys extra:
      - sesiones_completas: queryset completo de sesiones (sin paginación)
      - pagos_recientes: queryset de pagos del período
      - proyectos_todos: queryset completo de proyectos
      - mensualidades_todas: queryset completo de mensualidades
    """
    pac         = context.get('paciente')
    fecha_desde = str(context.get('fecha_desde', ''))
    fecha_hasta = str(context.get('fecha_hasta', ''))

    nombre_pac  = str(pac) if pac else '—'
    titulo      = "INFORME DE PACIENTE"

    # Período legible
    if fecha_desde and fecha_hasta:
        if fecha_desde == fecha_hasta:
            try:
                from datetime import datetime as _dt
                fd = _dt.strptime(fecha_desde, '%Y-%m-%d').date()
                periodo_txt = f"{fd.day} de {MESES_FULL[fd.month]} de {fd.year}"
            except Exception:
                periodo_txt = fecha_desde
        else:
            periodo_txt = f"{fecha_desde}  al  {fecha_hasta}"
    else:
        periodo_txt = 'Todo el historial del paciente'

    fecha_emision = _date_cls.today().strftime('%d/%m/%Y')

    # ── PASADA 1 ─────────────────────────────────────────────────────
    buf1 = BytesIO()
    c = pdf_canvas.Canvas(buf1, pagesize=letter)
    c.setTitle(f"{titulo} — {nombre_pac}")
    c.setAuthor(NOMBRE_CENTRO)

    pc = [1]

    def make_page():
        pc[0] += 1
        pg = pc[0]
        c.setFillColor(C_FONDO_PAG)
        c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
        y = _encabezado(c, pg, 999, titulo, nombre_pac, periodo_txt, fecha_emision)
        return c, y, pg

    def make_page_w():
        c.showPage()
        return make_page()

    helpers = {
        'new_page'    : make_page_w,
        'fecha'       : fecha_emision,
        'canvas'      : c,
        'page_counter': pc,
        'periodo_txt' : periodo_txt,
        'total_pg'    : [999],
    }
    pages_data = []

    # Portada
    c.setFillColor(C_FONDO_PAG)
    c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    _portada(c, pac, periodo_txt, fecha_emision, context)
    pages_data.append(1)

    _seccion_perfil(pages_data, context, helpers)
    _seccion_financiero(pages_data, context, helpers)
    _seccion_asistencia(pages_data, context, helpers)
    _seccion_evolucion(pages_data, context, helpers)
    _seccion_proyectos(pages_data, context, helpers)
    _seccion_mensualidades(pages_data, context, helpers)
    _seccion_pagos(pages_data, context, helpers)
    _seccion_devoluciones(pages_data, context, helpers)
    _seccion_detalle_sesiones(pages_data, context, helpers)

    total_pages = pc[0]
    c.save()

    # ── PASADA 2 — total correcto ─────────────────────────────────────
    buf2 = BytesIO()
    c2 = pdf_canvas.Canvas(buf2, pagesize=letter)
    c2.setTitle(f"{titulo} — {nombre_pac}")
    c2.setAuthor(NOMBRE_CENTRO)

    pc2 = [1]

    def make_page2():
        pc2[0] += 1
        pg = pc2[0]
        c2.setFillColor(C_FONDO_PAG)
        c2.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
        y = _encabezado(c2, pg, total_pages, titulo, nombre_pac, periodo_txt, fecha_emision)
        return c2, y, pg

    def make_page2_w():
        c2.showPage()
        return make_page2()

    helpers2 = {
        'new_page'    : make_page2_w,
        'fecha'       : fecha_emision,
        'canvas'      : c2,
        'page_counter': pc2,
        'periodo_txt' : periodo_txt,
        'total_pg'    : [total_pages],
    }
    pages_data2 = []

    c2.setFillColor(C_FONDO_PAG)
    c2.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    _portada(c2, pac, periodo_txt, fecha_emision, context)
    _pie(c2, 1, total_pages, fecha_emision)
    pages_data2.append(1)

    _seccion_perfil(pages_data2, context, helpers2)
    _seccion_financiero(pages_data2, context, helpers2)
    _seccion_asistencia(pages_data2, context, helpers2)
    _seccion_evolucion(pages_data2, context, helpers2)
    _seccion_proyectos(pages_data2, context, helpers2)
    _seccion_mensualidades(pages_data2, context, helpers2)
    _seccion_pagos(pages_data2, context, helpers2)
    _seccion_devoluciones(pages_data2, context, helpers2)
    _seccion_detalle_sesiones(pages_data2, context, helpers2)

    c2.save()
    buf2.seek(0)
    return buf2