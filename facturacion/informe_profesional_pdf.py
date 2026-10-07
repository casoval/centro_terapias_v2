# facturacion/informe_profesional_pdf.py
# =====================================================================
# INFORME PDF POR PROFESIONAL — mismo estilo y primitivos que el
# informe de paciente (informe_paciente_pdf.py), con paginación
# automática (las tablas continúan en la página siguiente repitiendo
# su encabezado) y dos pasadas para el total de páginas correcto.
#
# Entrada: generar_informe_profesional_pdf({
#     'profesional': <Profesional>, 'r': <dict de analizar()+desglose>,
#     'desde': date, 'hasta': date, 'sucursal': <Sucursal|None> })
# =====================================================================

import os
import logging
import tempfile
from io import BytesIO
from datetime import date as _date

from reportlab.lib.pagesizes import letter, landscape as _landscape
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.pdfbase.pdfmetrics import stringWidth

from .informe_paciente_pdf import (
    C_OSC, C_PRI, C_MED, C_FONDO, C_VERDE, C_VERDE_L, C_AMBER, C_AMBER_L, C_ROJO,
    C_ROJO_L, C_MORADO, C_MORADO_L, C_TEAL, C_TEAL_L, C_GRIS_T, C_GRIS_H, C_GRIS_B,
    C_TEXTO, C_TSEC, C_MUTED, C_BLANCO, C_FONDO_PAG, NOMBRE_CENTRO, DIRECCION,
    TELEFONO, MESES_FULL, _logo, _grad, _wrap, _metrica_box,
)

logger = logging.getLogger(__name__)

PW, PH = letter
LW, LH = _landscape(letter)
ML = 1.6 * cm
HEADER_H = 2.3 * cm
FOOT_Y = 1.5 * cm
BOTTOM = 2.6 * cm

VERDICTO_COL = {'solido': C_VERDE, 'aceptable': C_AMBER, 'bajo': colors.HexColor('#ea580c'),
                'critico': C_ROJO, 'sin_datos': C_MUTED}


# ─────────────────────────────────────────────────────────────────────
# FORMATO
# ─────────────────────────────────────────────────────────────────────
_REEMPLAZOS = {'≥': '>=', '≤': '<=', '×': 'x', '→': '->', '✔': 'OK', '✖': 'X', '●': '*',
               '′': "'", '’': "'", '“': '"', '”': '"', '\u00a0': ' ', '…': '...',
               '⚠': '(!)', '≈': '~', '💡': '', '·': '-', '—': '-', '–': '-'}


def _t(s):
    """Limpia caracteres fuera de WinAnsi (Helvetica estándar de ReportLab)."""
    s = '' if s is None else str(s)
    for a, b in _REEMPLAZOS.items():
        s = s.replace(a, b)
    return s.encode('latin-1', 'replace').decode('latin-1')


def fm(v, d=2):
    """1234.5 -> 1.234,50"""
    try:
        s = f"{float(v or 0):,.{d}f}"
    except Exception:
        return "0"
    return s.replace(',', '\x00').replace('.', ',').replace('\x00', '.')


def bs(v, d=2):
    return f"Bs. {fm(v, d)}"


def pc(v):
    try:
        return f"{float(v):.1f}%".replace('.', ',')
    except Exception:
        return "0,0%"


def fd(d, fmt='%d/%m/%Y'):
    try:
        return d.strftime(fmt)
    except Exception:
        return '-'


def _recorta(txt, fsize, max_w, font='Helvetica'):
    txt = _t(txt)
    while stringWidth(txt, font, fsize) > max_w and len(txt) > 1:
        txt = txt[:-2] + '.'
    return txt


def _foto_path(prof):
    """Ruta local de la foto (filesystem o descarga desde Cloudinary). None si no hay."""
    f = getattr(prof, 'foto', None)
    if not f:
        return None, False
    try:
        ruta = str(f.path)
        if os.path.exists(ruta):
            return ruta, False
    except Exception:
        pass
    try:
        url = None
        if hasattr(f, 'build_url'):
            try:
                url = f.build_url(width=400, height=400, crop='fill', gravity='face',
                                  quality='auto', fetch_format='jpg')
            except Exception:
                url = None
        if not url and hasattr(f, 'url'):
            url = f.url
        if not url:
            return None, False
        if url.startswith('//'):
            url = 'https:' + url
        import urllib.request
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.jpg')
        tmp.close()
        with urllib.request.urlopen(url, timeout=8) as resp, open(tmp.name, 'wb') as out:
            out.write(resp.read())
        if os.path.getsize(tmp.name) > 0:
            return tmp.name, True
    except Exception as e:
        logger.warning(f"No se pudo cargar la foto del profesional: {e}")
    return None, False


# ─────────────────────────────────────────────────────────────────────
# DOCUMENTO CON PAGINACIÓN AUTOMÁTICA
# ─────────────────────────────────────────────────────────────────────
class Doc:
    # Textos del encabezado/pie: las subclases (p. ej. informe de sucursal) los reemplazan
    TITULO_DOC = "INFORME DE PROFESIONAL"
    ETIQUETA = "PROFESIONAL:"
    NOMBRE_DOC = "Informe de Profesional"

    def __init__(self, total, nombre, periodo, fecha):
        self.buf = BytesIO()
        self.c = pdf_canvas.Canvas(self.buf, pagesize=letter)
        self.c.setAuthor(NOMBRE_CENTRO)
        self.c.setTitle(f"{self.NOMBRE_DOC} - {_t(nombre)}")
        self.total, self.nombre, self.periodo, self.fecha = total, nombre, periodo, fecha
        self.pg = 0
        self.land = False
        self.y = 0
        self.w, self.h = PW, PH

    # ── geometría ──
    @property
    def cw(self):
        return self.w - 2 * ML

    def _fondo(self):
        self.c.setFillColor(C_FONDO_PAG)
        self.c.rect(0, 0, self.w, self.h, fill=1, stroke=0)

    # ── páginas ──
    def portada_inicio(self):
        self.pg = 1
        self.w, self.h, self.land = PW, PH, False
        self._fondo()

    def page(self, land=None):
        land = self.land if land is None else land
        self.c.showPage()
        self.pg += 1
        self.land = land
        self.w, self.h = (LW, LH) if land else (PW, PH)
        self.c.setPageSize((self.w, self.h))
        self._fondo()
        self._encabezado()
        self._pie()

    def _encabezado(self):
        c = self.c
        hh = 1.9 * cm if self.land else HEADER_H
        _grad(c, 0, self.h - hh, self.w, hh, C_OSC, C_PRI)
        lp = _logo()
        lh = hh - 0.5 * cm
        if lp:
            try:
                c.drawImage(lp, ML, self.h - hh + 0.25 * cm, width=lh, height=lh,
                            preserveAspectRatio=True, mask='auto')
            except Exception:
                pass
        tx = ML + lh + 0.4 * cm
        c.setFillColor(C_BLANCO)
        c.setFont("Helvetica-Bold", 11)
        c.drawString(tx, self.h - 0.95 * cm, NOMBRE_CENTRO)
        c.setFont("Helvetica", 7)
        c.drawString(tx, self.h - 1.45 * cm, f"{DIRECCION}  |  {TELEFONO}")
        c.setFont("Helvetica-Bold", 8.5)
        c.drawRightString(self.w - ML, self.h - 0.9 * cm, self.TITULO_DOC)
        c.setFont("Helvetica", 7)
        c.drawRightString(self.w - ML, self.h - 1.4 * cm, f"Pág. {self.pg} de {self.total}")
        by = self.h - hh - 0.85 * cm
        c.setFillColor(C_FONDO)
        c.roundRect(ML, by, self.cw, 0.72 * cm, 4, fill=1, stroke=0)
        c.setStrokeColor(C_MED)
        c.setLineWidth(0.4)
        c.roundRect(ML, by, self.cw, 0.72 * cm, 4, fill=0, stroke=1)
        c.setFont("Helvetica-Bold", 7)
        c.setFillColor(C_PRI)
        c.drawString(ML + 0.3 * cm, by + 0.26 * cm, self.ETIQUETA)
        c.setFont("Helvetica-Bold", 8)
        c.setFillColor(C_TEXTO)
        c.drawString(ML + 2.4 * cm, by + 0.26 * cm, _recorta(self.nombre, 8, 7.2 * cm, 'Helvetica-Bold'))
        c.setFont("Helvetica-Bold", 7)
        c.setFillColor(C_PRI)
        px = ML + 10.2 * cm if not self.land else ML + 12 * cm
        c.drawString(px, by + 0.26 * cm, "PERIODO:")
        c.setFont("Helvetica", 7.5)
        c.setFillColor(C_TEXTO)
        c.drawString(px + 1.5 * cm, by + 0.26 * cm, _t(self.periodo))
        c.setFont("Helvetica", 7)
        c.setFillColor(C_MUTED)
        c.drawRightString(self.w - ML - 0.3 * cm, by + 0.26 * cm, f"Emitido: {self.fecha}")
        self.y = by - 0.45 * cm

    def _pie(self):
        c = self.c
        c.setStrokeColor(C_GRIS_B)
        c.setLineWidth(0.4)
        c.line(ML, FOOT_Y + 0.55 * cm, self.w - ML, FOOT_Y + 0.55 * cm)
        c.setFont("Helvetica", 6.5)
        c.setFillColor(C_MUTED)
        c.drawString(ML, FOOT_Y + 0.2 * cm,
                     f"{NOMBRE_CENTRO}  |  {self.NOMBRE_DOC} - {self.fecha}  |  CONFIDENCIAL")
        c.drawRightString(self.w - ML, FOOT_Y + 0.2 * cm, f"Pág. {self.pg} / {self.total}")

    def ensure(self, h):
        if self.y - h < BOTTOM:
            self.page()

    # ── bloques ──
    def titulo(self, texto, color=None):
        self.ensure(4.6 * cm)
        c = self.c
        c.setFillColor(color or C_PRI)
        c.roundRect(ML, self.y - 0.55 * cm, self.cw, 0.55 * cm, 4, fill=1, stroke=0)
        c.setFillColor(C_BLANCO)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(ML + 0.4 * cm, self.y - 0.38 * cm, _t(texto).upper())
        self.y -= 0.55 * cm + 0.3 * cm

    def subtitulo(self, texto):
        self.ensure(1.2 * cm)
        self.c.setFont("Helvetica-Bold", 8.5)
        self.c.setFillColor(C_PRI)
        self.c.drawString(ML + 0.1 * cm, self.y - 0.3 * cm, _t(texto))
        self.y -= 0.6 * cm

    def parrafo(self, texto, fsize=7.5, color=None, font="Helvetica", indent=0.2 * cm, lh=None):
        lh = lh or (fsize * 0.047 * cm * 1.0 + 0.0)
        lh = fsize * 0.0445 * cm
        palabras = _t(texto).split()
        # estimar líneas para controlar salto de página
        n = 1
        linea = ''
        for p in palabras:
            test = (linea + ' ' + p).strip()
            if stringWidth(test, font, fsize) <= self.cw - 2 * indent:
                linea = test
            else:
                n += 1
                linea = p
        self.ensure(n * lh + 0.3 * cm)
        self.c.setFont(font, fsize)
        self.c.setFillColor(color or C_MUTED)
        self.y = _wrap(self.c, _t(texto), ML + indent, self.y - 0.25 * cm, self.cw - 2 * indent,
                       font, fsize, lh) - 0.05 * cm

    def espacio(self, h=0.3 * cm):
        self.y -= h

    def grilla(self, items, cols=4, box_h=1.6 * cm):
        gap = 0.25 * cm
        bw = (self.cw - (cols - 1) * gap) / cols
        for i in range(0, len(items), cols):
            fila = items[i:i + cols]
            self.ensure(box_h + 0.4 * cm)
            n = len(fila)
            bw2 = bw
            for j, (lbl, val, sub, col) in enumerate(fila):
                _metrica_box(self.c, ML + j * (bw2 + gap), self.y, bw2, box_h,
                             _t(lbl), _t(val), _t(sub), col)
            self.y -= box_h + 0.3 * cm


    def tabla(self, headers, rows, widths, aligns=None, fsize=7, row_h=0.46 * cm, x0=None):
        """rows: lista de listas; una celda puede ser str o (str, color)."""
        c = self.c
        x0 = ML if x0 is None else x0
        total_w = sum(widths)
        if self.land and abs(total_w - self.cw) > 0.2 * cm:
            esc = self.cw / total_w
            widths = [w_ * esc for w_ in widths]
            total_w = self.cw
        aligns = aligns or ['l'] * len(widths)

        def head():
            c.setFillColor(C_GRIS_H)
            c.roundRect(x0, self.y - row_h, total_w, row_h, 3, fill=1, stroke=0)
            c.setStrokeColor(C_GRIS_B)
            c.setLineWidth(0.3)
            c.roundRect(x0, self.y - row_h, total_w, row_h, 3, fill=0, stroke=1)
            xc = x0
            for i, h in enumerate(headers):
                c.setFont("Helvetica-Bold", 6.5)
                c.setFillColor(C_TSEC)
                txt = _recorta(str(h).upper(), 6.5, widths[i] - 0.3 * cm, 'Helvetica-Bold')
                if aligns[i] == 'r':
                    c.drawRightString(xc + widths[i] - 0.15 * cm, self.y - row_h + 0.15 * cm, txt)
                elif aligns[i] == 'c':
                    c.drawCentredString(xc + widths[i] / 2, self.y - row_h + 0.15 * cm, txt)
                else:
                    c.drawString(xc + 0.15 * cm, self.y - row_h + 0.15 * cm, txt)
                xc += widths[i]
            self.y -= row_h

        self.ensure(row_h * 3)
        head()
        if not rows:
            c.setFont("Helvetica-Oblique", 7)
            c.setFillColor(C_MUTED)
            c.drawString(x0 + 0.2 * cm, self.y - row_h + 0.15 * cm, "Sin datos en el período.")
            self.y -= row_h
        for ri, row in enumerate(rows):
            if self.y - row_h < BOTTOM:
                self.page()
                head()
            if ri % 2 == 0:
                c.setFillColor(C_GRIS_T)
                c.rect(x0, self.y - row_h, total_w, row_h, fill=1, stroke=0)
            c.setStrokeColor(C_GRIS_B)
            c.setLineWidth(0.2)
            c.line(x0, self.y - row_h, x0 + total_w, self.y - row_h)
            xc = x0
            for ci, cell in enumerate(row):
                col = C_TEXTO
                if isinstance(cell, tuple):
                    cell, col = cell
                c.setFont("Helvetica", fsize)
                c.setFillColor(col)
                txt = _recorta('' if cell is None else cell, fsize, widths[ci] - 0.3 * cm)
                if aligns[ci] == 'r':
                    c.drawRightString(xc + widths[ci] - 0.15 * cm, self.y - row_h + 0.13 * cm, txt)
                elif aligns[ci] == 'c':
                    c.drawCentredString(xc + widths[ci] / 2, self.y - row_h + 0.13 * cm, txt)
                else:
                    c.drawString(xc + 0.15 * cm, self.y - row_h + 0.13 * cm, txt)
                xc += widths[ci]
            self.y -= row_h
        c.setStrokeColor(C_GRIS_B)
        c.setLineWidth(0.4)
        c.line(x0, self.y, x0 + total_w, self.y)
        self.y -= 0.35 * cm

    def barra_apilada(self, partes, alto=0.6 * cm):
        """partes: [(label, pct, color, txt)]"""
        self.ensure(alto + 2.2 * cm)
        c = self.c
        x = ML
        total_w = self.cw
        c.setFillColor(C_GRIS_H)
        c.roundRect(ML, self.y - alto, total_w, alto, 3, fill=1, stroke=0)
        for lbl, pct, col, txt in partes:
            w = total_w * max(pct, 0) / 100.0
            if w <= 0:
                continue
            c.setFillColor(colors.HexColor(col))
            c.rect(x, self.y - alto, w, alto, fill=1, stroke=0)
            x += w
        self.y -= alto + 0.35 * cm
        xl, yl = ML, self.y
        c.setFont("Helvetica", 6.8)
        for lbl, pct, col, txt in partes:
            t = _t(f"{lbl}: {txt} ({pc(pct)})")
            w = stringWidth(t, "Helvetica", 6.8) + 0.7 * cm
            if xl + w > ML + self.cw:
                xl = ML
                yl -= 0.42 * cm
            c.setFillColor(colors.HexColor(col))
            c.rect(xl, yl - 0.05 * cm, 0.25 * cm, 0.25 * cm, fill=1, stroke=0)
            c.setFillColor(C_TSEC)
            c.drawString(xl + 0.35 * cm, yl, t)
            xl += w
        self.y = yl - 0.55 * cm

    def barras_h(self, items, color=C_VERDE, max_val=None, ancho_label=2.4 * cm, ancho_txt=5.2 * cm):
        """items: [(label, valor_numerico, texto_derecha, color|None)]"""
        c = self.c
        mx = max_val or max([i[1] for i in items] + [1])
        bar_w = self.cw - ancho_label - ancho_txt
        for lbl, val, txt, col in items:
            self.ensure(0.6 * cm)
            c.setFont("Helvetica-Bold", 7)
            c.setFillColor(C_TEXTO)
            c.drawString(ML + 0.1 * cm, self.y - 0.38 * cm, _recorta(lbl, 7, ancho_label - 0.2 * cm, 'Helvetica-Bold'))
            c.setFillColor(C_GRIS_H)
            c.roundRect(ML + ancho_label, self.y - 0.45 * cm, bar_w, 0.34 * cm, 2, fill=1, stroke=0)
            w = bar_w * min(max(val, 0) / mx, 1.0)
            if w > 0:
                c.setFillColor(col or color)
                c.roundRect(ML + ancho_label, self.y - 0.45 * cm, w, 0.34 * cm, 2, fill=1, stroke=0)
            c.setFont("Helvetica", 7)
            c.setFillColor(C_TSEC)
            c.drawString(ML + ancho_label + bar_w + 0.2 * cm, self.y - 0.38 * cm, _recorta(txt, 7, ancho_txt - 0.3 * cm))
            self.y -= 0.55 * cm
        self.y -= 0.15 * cm

    def columnas(self, labels, valores, color=C_VERDE, alto=3.2 * cm, fmt=lambda v: fm(v, 0), color2=None, valores2=None):
        """Gráfico de columnas simple (hasta ~24 barras)."""
        n = len(labels)
        if not n:
            return
        self.ensure(alto + 1.6 * cm)
        c = self.c
        mx = max(list(valores) + list(valores2 or []) + [1])
        base = self.y - alto - 0.3 * cm
        slot = self.cw / n
        bw = min(slot * 0.62, 1.1 * cm)
        c.setStrokeColor(C_GRIS_B)
        c.setLineWidth(0.4)
        c.line(ML, base, ML + self.cw, base)
        for i, (lb, v) in enumerate(zip(labels, valores)):
            x = ML + slot * i + (slot - bw) / 2
            h = alto * (v / mx) if mx else 0
            c.setFillColor(color)
            c.rect(x, base, bw, h, fill=1, stroke=0)
            if valores2 is not None:
                h2 = alto * (valores2[i] / mx) if mx else 0
                c.setFillColor(color2 or C_ROJO)
                c.rect(x + bw * 0.55, base, bw * 0.45, h2, fill=1, stroke=0)
            c.setFont("Helvetica", 6)
            c.setFillColor(C_TSEC)
            c.drawCentredString(x + bw / 2, base + h + 0.1 * cm, fmt(v))
            c.setFont("Helvetica", 5.8 if n > 10 else 6.5)
            c.setFillColor(C_MUTED)
            c.drawCentredString(x + bw / 2, base - 0.3 * cm, _recorta(lb, 5.8, slot))
        self.y = base - 0.7 * cm

    def heat(self, filas, horas):
        """filas: [{'dia_c','celdas':[{'h','ocup','a'}]}]"""
        if not filas:
            return
        self.ensure(0.5 * cm * (len(filas) + 2))
        c = self.c
        lw = 1.2 * cm
        n = len(horas)
        cw_ = (self.cw - lw) / n
        ch = 0.5 * cm
        c.setFont("Helvetica", 6)
        c.setFillColor(C_MUTED)
        for i, h in enumerate(horas):
            c.drawCentredString(ML + lw + cw_ * i + cw_ / 2, self.y - 0.3 * cm, h)
        self.y -= 0.4 * cm
        for f in filas:
            c.setFont("Helvetica-Bold", 7)
            c.setFillColor(C_TSEC)
            c.drawString(ML + 0.1 * cm, self.y - ch + 0.17 * cm, _t(f['dia_c']))
            for i, cel in enumerate(f['celdas']):
                x = ML + lw + cw_ * i
                if cel['ocup'] is None:
                    c.setFillColor(colors.HexColor('#f1f5f9'))
                    c.rect(x + 0.5, self.y - ch + 0.5, cw_ - 1, ch - 1, fill=1, stroke=0)
                else:
                    a = max(0.08, min(float(cel.get('a') or 0), 1.0))
                    c.setFillColor(colors.Color(1 - (1 - 0.086) * a, 1 - (1 - 0.64) * a, 1 - (1 - 0.29) * a))
                    c.rect(x + 0.5, self.y - ch + 0.5, cw_ - 1, ch - 1, fill=1, stroke=0)
                    c.setFillColor(C_OSC if a > 0.45 else C_TSEC)
                    c.setFont("Helvetica", 5.8)
                    c.drawCentredString(x + cw_ / 2, self.y - ch + 0.17 * cm, f"{cel['ocup']:.0f}")
            self.y -= ch
        self.y -= 0.3 * cm

    def semaforo_filas(self, criterios):
        c = self.c
        for cr in criterios:
            det = _t(cr.get('detalle', ''))
            n_det = max(1, len(det) // 70 + 1)
            h = max(0.9 * cm, 0.45 * cm + n_det * 0.34 * cm)
            self.ensure(h + 0.1 * cm)
            col = colors.HexColor(cr['color'])
            c.setFillColor(col)
            c.circle(ML + 0.3 * cm, self.y - 0.4 * cm, 0.17 * cm, fill=1, stroke=0)
            c.setFont("Helvetica-Bold", 7.8)
            c.setFillColor(C_TEXTO)
            c.drawString(ML + 0.75 * cm, self.y - 0.33 * cm, _recorta(cr['nombre'], 7.8, 6.3 * cm, 'Helvetica-Bold'))
            c.setFont("Helvetica", 6.3)
            c.setFillColor(C_MUTED)
            c.drawString(ML + 0.75 * cm, self.y - 0.68 * cm, _recorta(cr['regla'], 6.3, 6.6 * cm))
            c.setFont("Helvetica-Bold", 8)
            c.setFillColor(col)
            c.drawString(ML + 7.6 * cm, self.y - 0.33 * cm, _recorta(cr['valor'], 8, 4.6 * cm, 'Helvetica-Bold'))
            c.setFont("Helvetica", 6.8)
            c.setFillColor(C_TSEC)
            _wrap(c, det, ML + 12.3 * cm, self.y - 0.3 * cm, self.cw - 12.4 * cm, "Helvetica", 6.8, 0.33 * cm)
            c.setStrokeColor(C_GRIS_H)
            c.setLineWidth(0.3)
            c.line(ML, self.y - h, ML + self.cw, self.y - h)
            self.y -= h + 0.05 * cm


# ─────────────────────────────────────────────────────────────────────
# PORTADA
# ─────────────────────────────────────────────────────────────────────
def _portada(d, prof, r, periodo, sucursal, foto_path):
    c = d.c
    k = r['kpis']
    d._fondo()
    _grad(c, 0, PH - 6.0 * cm, PW, 6.0 * cm, C_OSC, C_PRI)
    lp = _logo()
    if lp:
        try:
            c.drawImage(lp, ML, PH - 5.0 * cm, width=3 * cm, height=3 * cm, preserveAspectRatio=True, mask='auto')
        except Exception:
            pass
    c.setFillColor(C_BLANCO)
    c.setFont("Helvetica-Bold", 15)
    c.drawString(ML + 3.5 * cm, PH - 2.3 * cm, NOMBRE_CENTRO)
    c.setFont("Helvetica", 8.5)
    c.drawString(ML + 3.5 * cm, PH - 2.95 * cm, f"{DIRECCION}  |  {TELEFONO}")
    c.setStrokeColor(colors.HexColor('#93c5fd'))
    c.setLineWidth(1.5)
    c.line(ML, PH - 5.7 * cm, PW - ML, PH - 5.7 * cm)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(ML + 3.5 * cm, PH - 4.0 * cm, "INFORME INDIVIDUAL DE PROFESIONAL")
    c.setFont("Helvetica", 8)
    c.drawString(ML + 3.5 * cm, PH - 4.6 * cm, "Rendimiento, horas, ingresos y decisión de continuidad")

    ty = PH - 7.2 * cm
    FS = 4.2 * cm
    fx, fy = ML, ty - FS
    c.setFillColor(C_GRIS_H)
    c.roundRect(fx - 0.12 * cm, fy - 0.12 * cm, FS + 0.24 * cm, FS + 0.24 * cm, 8, fill=1, stroke=0)
    c.setStrokeColor(C_MED)
    c.setLineWidth(1.5)
    c.roundRect(fx - 0.12 * cm, fy - 0.12 * cm, FS + 0.24 * cm, FS + 0.24 * cm, 8, fill=0, stroke=1)
    dibujada = False
    if foto_path:
        try:
            c.drawImage(foto_path, fx, fy, width=FS, height=FS, preserveAspectRatio=True, mask='auto')
            dibujada = True
        except Exception:
            dibujada = False
    if not dibujada:
        c.setFillColor(C_FONDO)
        c.roundRect(fx, fy, FS, FS, 7, fill=1, stroke=0)
        c.setFillColor(C_PRI)
        c.setFont("Helvetica-Bold", 34)
        ini = f"{prof.nombre[:1]}{prof.apellido[:1]}".upper()
        c.drawCentredString(fx + FS / 2, fy + FS / 2 - 0.5 * cm, _t(ini))

    tx = ML + FS + 0.8 * cm
    c.setFillColor(C_TEXTO)
    c.setFont("Helvetica-Bold", 17)
    c.drawString(tx, ty - 0.7 * cm, _recorta(prof.nombre_completo, 17, PW - tx - ML, 'Helvetica-Bold'))
    c.setFont("Helvetica-Bold", 9.5)
    c.setFillColor(C_MED)
    c.drawString(tx, ty - 1.4 * cm, _t(prof.especialidad))
    c.setFont("Helvetica", 8)
    c.setFillColor(C_TSEC)
    yy = ty - 2.1 * cm
    lineas = [f"Estado: {'Activo' if prof.activo else 'Inactivo'}   |   Ingreso: {fd(prof.fecha_ingreso)}"]
    if prof.telefono:
        lineas.append(f"Teléfono: {prof.telefono}")
    if prof.email:
        lineas.append(f"Email: {prof.email}")
    suc = ', '.join(s.nombre for s in prof.sucursales.all())
    if suc:
        lineas.append(f"Sucursales: {suc}")
    svs = ', '.join(s.nombre for s in prof.servicios.all())
    if svs:
        lineas.append(f"Servicios: {svs}")
    for ln in lineas:
        yy = _wrap(c, _t(ln), tx, yy, PW - tx - ML, "Helvetica", 8, 0.42 * cm)

    # Caja período
    by = fy - 1.2 * cm
    c.setFillColor(C_FONDO)
    c.roundRect(ML, by - 1.6 * cm, PW - 2 * ML, 1.6 * cm, 6, fill=1, stroke=0)
    c.setFont("Helvetica-Bold", 7.5)
    c.setFillColor(C_PRI)
    c.drawString(ML + 0.5 * cm, by - 0.55 * cm, "PERIODO ANALIZADO")
    c.setFont("Helvetica-Bold", 12)
    c.setFillColor(C_TEXTO)
    c.drawString(ML + 0.5 * cm, by - 1.2 * cm, _t(periodo))
    if sucursal:
        c.setFont("Helvetica", 8)
        c.setFillColor(C_TSEC)
        c.drawRightString(PW - ML - 0.5 * cm, by - 0.55 * cm, f"Sucursal: {_t(sucursal.nombre)}")
    c.setFont("Helvetica", 8)
    c.setFillColor(C_TSEC)
    c.drawRightString(PW - ML - 0.5 * cm, by - 1.2 * cm, f"{r['n_dias']} días  |  {k['total']} sesiones  |  {k['pacientes']} niño(s) atendido(s)")

    # Veredicto + cifras
    d.y = by - 2.3 * cm
    sm = r.get('semaforo')
    if sm and sm.get('score') is not None:
        col = VERDICTO_COL.get(sm['veredicto'], C_MUTED)
        c.setFillColor(col)
        c.roundRect(ML, d.y - 2.2 * cm, PW - 2 * ML, 2.2 * cm, 8, fill=1, stroke=0)
        c.setFillColor(C_BLANCO)
        c.setFont("Helvetica-Bold", 28)
        c.drawString(ML + 0.6 * cm, d.y - 1.45 * cm, f"{sm['score']}/100")
        c.setFont("Helvetica-Bold", 8.5)
        c.drawString(ML + 4.6 * cm, d.y - 0.8 * cm, "SEMÁFORO DE DECISION")
        c.setFont("Helvetica", 8)
        _wrap(c, _t(sm['msg']), ML + 4.6 * cm, d.y - 1.25 * cm, PW - 2 * ML - 5.2 * cm, "Helvetica", 8, 0.4 * cm)
        d.y -= 2.2 * cm + 0.5 * cm
    items = [
        ("Generado", bs(k['gen_total'], 0), "sesiones + proyectos + mens.", C_VERDE),
        ("Horas trabajadas", k['horas_reloj_txt'], f"Bs. {fm(k['ingreso_hora'], 0)} por hora", C_MED),
        ("Ocupación efectiva", pc(k['ocup_efect']), f"agendada {pc(k['ocup_el'])}", colors.HexColor(k['carga_color'])),
        ("Libres por inasistencia", k['h_perdidas_txt'], f"{pc(k['pct_perdidas'])} de su horario", C_ROJO),
    ]
    for j, (lbl, val, sub, col) in enumerate(items):
        gap = 0.25 * cm
        bw = (PW - 2 * ML - 3 * gap) / 4
        _metrica_box(c, ML + j * (bw + gap), d.y, bw, 1.7 * cm, _t(lbl), _t(val), _t(sub), col)
    d.y -= 1.7 * cm + 0.6 * cm
    c.setFont("Helvetica-Oblique", 7)
    c.setFillColor(C_MUTED)
    c.drawString(ML, FOOT_Y + 0.9 * cm, f"Emitido el {d.fecha}. Documento confidencial de uso interno de la dirección.")
    d._pie()


# ─────────────────────────────────────────────────────────────────────
# SECCIONES
# ─────────────────────────────────────────────────────────────────────
def _sec_ejecutivo(d, r, prof):
    k = r['kpis']
    d.page(land=False)
    d.titulo("1. Resumen ejecutivo y decisión de continuidad", C_PRI)
    sm = r.get('semaforo')
    if sm:
        d.parrafo(f"{sm['msg']}  Criterios: {sm['n_verde']} en verde, {sm['n_ambar']} en ámbar, "
                  f"{sm['n_rojo']} en rojo. {sm['nota']}", 8, C_TEXTO, "Helvetica-Bold")
        d.semaforo_filas(sm['criterios'])
        if sm.get('faltan_costo'):
            d.parrafo("Nota: no se ingreso el costo mensual del profesional, por lo que no se evalua su rentabilidad "
                      "(el sistema no registra sueldos del personal interno).", 7, C_MUTED, "Helvetica-Oblique")
    d.espacio(0.2 * cm)
    d.subtitulo("Lo más importante")
    for h in r['hallazgos']:
        col = {'alerta': C_ROJO, 'ok': C_VERDE, 'nota': C_AMBER}.get(h['tipo'], C_TSEC)
        d.parrafo("- " + h['txt'], 7.6, col)
    cmp_ = r.get('comparacion')
    if cmp_:
        d.espacio(0.2 * cm)
        d.subtitulo(f"Comparación con el período anterior ({fd(cmp_['desde'], '%d/%m')} - {fd(cmp_['hasta'])})")
        sg = lambda v: (f"+{fm(v, 1)}" if v > 0 else fm(v, 1))
        d.tabla(["Indicador", "Anterior", "Actual", "Variacion"], [
            ["Sesiones atendidas", str(cmp_['atendidas'][0]), str(k['atendidas']), (sg(cmp_['atendidas'][1]), C_VERDE if cmp_['atendidas'][1] >= 0 else C_ROJO)],
            ["Generado (Bs.)", fm(cmp_['gen'][0]), fm(k['gen_total']), (sg(cmp_['gen'][1]), C_VERDE if cmp_['gen'][1] >= 0 else C_ROJO)],
            ["Ocupación agendada", pc(cmp_['ocup'][0]), pc(k['ocup_el']), (sg(cmp_['ocup'][1]) + " pts", C_VERDE if cmp_['ocup'][1] >= 0 else C_ROJO)],
            ["Niños atendidos", str(cmp_['pacientes'][0]), str(k['pacientes']), (sg(cmp_['pacientes'][1]), C_VERDE if cmp_['pacientes'][1] >= 0 else C_ROJO)],
        ], [6.0 * cm, 3.6 * cm, 3.6 * cm, 4.4 * cm], ['l', 'r', 'r', 'r'], 7.5)


def _sec_produccion(d, r):
    k = r['kpis']
    d.titulo("2. Cuánto genera", C_VERDE)
    d.parrafo("Las faltas sin aviso se cobran y cuentan como ingreso (igual que el reporte financiero). En proyectos y "
              "mensualidades el costo es fijo: se reparte entre los profesionales segun el valor de sus sesiones a precio "
              "individual y se devenga conforme se realizan las sesiones.")
    items = [
        ("Total generado", bs(k['gen_total']), f"{bs(k['ingreso_hora'], 0)} por hora", C_VERDE),
        ("Sesiones individuales", bs(k['gen_ind']), f"{pc(k['pct_ind'])} del total", C_MED),
        ("Proyectos", bs(k['gen_proy']), f"Solo {fm(k['gen_proy_solo'], 0)} | Grupal {fm(k['gen_proy_grupal'], 0)}", C_MORADO),
        ("Mensualidades", bs(k['gen_mens']), f"Solo {fm(k['gen_mens_solo'], 0)} | Grupal {fm(k['gen_mens_grupal'], 0)}", C_TEAL),
        ("Por generar (agenda)", bs(k['por_generar']), "sesiones programadas", C_AMBER),
        ("Ingreso por sesión", bs(k['ingreso_sesion']), f"{k['atendidas']} sesiones atendidas", C_MED),
    ]
    if 'cobrado' in k:
        items += [("Cobrado", bs(k['cobrado']), f"{pc(k['pct_cobrado'])} de lo generado", C_VERDE),
                  ("Generado sin cobrar", bs(k['pendiente_cobro']), "pendiente de pago", C_ROJO)]
    if k.get('costo_periodo'):
        items.append(("Margen vs. su costo", bs(k['margen']), f"aporta {fm(k['neto_centro'], 0)} / costo {fm(k['costo_periodo'], 0)} ({fm(k['costo_meses'])} mes)",
                      C_VERDE if k['rentable'] else C_ROJO))
    if k['tiene_externos']:
        items.append(("Servicios externos", bs(k['ext_centro']), f"retiene el centro | prof. {fm(k['ext_prof'], 0)}", C_AMBER))
    d.grilla(items, cols=4)
    d.subtitulo("Producción por tipo de atención")
    d.tabla(["Tipo", "Sesiones", "Atend.", "Faltas", "Prog.", "Horas", "Niños", "Generado Bs.", "% total"],
            [[t['nombre'], t['n'], t['atend'], t['faltas'], t['prog'], t['horas_txt'], t['pacs'], fm(t['gen']), pc(t['pct_gen'])]
             for t in r['por_tipo']],
            [4.4 * cm, 1.6 * cm, 1.4 * cm, 1.4 * cm, 1.4 * cm, 1.8 * cm, 1.4 * cm, 2.6 * cm, 1.9 * cm],
            ['l', 'r', 'r', 'r', 'r', 'r', 'r', 'r', 'r'])
    cb = r.get('cobranza')
    if cb:
        d.subtitulo("Generado vs. cobrado")
        d.tabla(["Concepto", "Generado Bs.", "Cobrado Bs.", "Pendiente Bs.", "% cobrado"],
                [[n, fm(x['gen']), fm(x['cob']), fm(max(x['gen'] - x['cob'], 0)), pc(x['pct'])]
                 for n, x in (("Sesiones individuales", cb['ind']), ("Proyectos", cb['proy']), ("Mensualidades", cb['mens']))]
                + [[("TOTAL", C_PRI), (fm(cb['generado']), C_PRI), (fm(cb['cobrado']), C_PRI), (fm(cb['pendiente']), C_ROJO), (pc(cb['pct']), C_PRI)]],
                [5.6 * cm, 3.2 * cm, 3.2 * cm, 3.2 * cm, 2.6 * cm], ['l', 'r', 'r', 'r', 'r'])
        d.parrafo("En proyectos y mensualidades el cobro se estima proporcional al avance de pago de cada paquete.", 7, C_MUTED, "Helvetica-Oblique")


def _sec_conciliacion(d, r):
    cn = r.get('conciliacion')
    if not cn:
        return
    d.titulo("3. Conciliación con el reporte financiero", C_MORADO)
    d.parrafo(f"Período {cn['periodo_txt']}. Compara lo que el reporte financiero cuenta como generado con lo que este informe "
              "devenga sumando a todos los profesionales, y explica cada diferencia.")
    filas = []
    for f in cn['filas']:
        filas.append([(f['concepto'], C_TEXTO), fm(f['financiero']), fm(f['este_reporte']),
                      (fm(f['diferencia']), C_ROJO if f['diferencia'] < 0 else C_VERDE if f['diferencia'] > 0 else C_TEXTO),
                      (fm(f['prof']), C_PRI), pc(f['pct_prof'])])
        for a in f['ajustes']:
            if a['monto']:
                filas.append([(f"   ({a['signo']}) {a['corto']}", C_MUTED), '', '',
                              (f"{a['signo']}{fm(a['monto'])}", C_VERDE if a['signo'] == '+' else C_ROJO), '', ''])
    t = cn['total']
    filas.append([("TOTAL", C_PRI), (fm(t['financiero']), C_PRI), (fm(t['este_reporte']), C_PRI),
                  (fm(t['diferencia']), C_PRI), (fm(t['prof']), C_PRI), (pc(t['pct_prof']), C_PRI)])
    d.tabla(["Concepto", "Financiero", "Este informe", "Diferencia", "Del profesional", "% centro"], filas,
            [8.4 * cm, 2.0 * cm, 2.2 * cm, 2.0 * cm, 2.2 * cm, 1.5 * cm], ['l', 'r', 'r', 'r', 'r', 'r'], 6.8)
    d.parrafo(("La conciliación cuadra: Financiero + ajustes = Este informe." if cn['todo_cuadra']
               else "ATENCIÓN: la conciliación no cuadra del todo; revisar los datos de proyectos y mensualidades.")
              + (" La cifra del profesional coincide con «Cuánto genera»." if cn['cuadra_kpis'] else
                 (" Hay filtros activos: no se compara con «Cuánto genera»." if cn['cuadra_kpis'] is None else
                  f" La cifra del profesional difiere de «Cuánto genera» por {fm(cn['dif_kpis'])}.")),
              7.2, C_VERDE if cn['todo_cuadra'] else C_ROJO, "Helvetica-Bold")
    d.parrafo("El financiero cuenta el costo completo de un proyecto en el período en que inicia y el de una mensualidad en su mes; "
              "este informe lo reconoce conforme se realizan las sesiones. Las sesiones individuales deben coincidir exactamente.",
              7, C_MUTED, "Helvetica-Oblique")


def _sec_horas(d, r):
    k = r['kpis']
    d.page(land=False)
    d.titulo("4. Horas trabajadas y tiempo libre", C_TEAL)
    d.parrafo("Las horas son de reloj: sesiones simultaneas con varios niños no se duplican. La falta sin aviso se cobra, "
              "pero el profesional queda libre esa hora; permisos, cancelaciones y reprogramaciones liberan la hora sin "
              "generar ingreso. Solo se consideran los días ya transcurridos.")
    items_h = [
        ("Horas trabajadas", k['horas_reloj_txt'], f"con pacientes: {k['horas_pac_txt']}", C_VERDE),
        ("Horario transcurrido", k['cap_el_txt'], f"{k['dias_con_horario']} días con horario", C_MED),
        ("Ocupación efectiva", pc(k['ocup_efect']), k['carga_txt'][:34], colors.HexColor(k['carga_color'])),
        ("Ocupación agendada", pc(k['ocup_el']), "incluye faltas y programadas", C_TEAL),
        ("Libres por inasistencia", k['h_perdidas_txt'], f"{pc(k['pct_perdidas'])} de su horario", C_ROJO),
        ("Sin paciente agendado", k['h_sinag_txt'], f"{pc(k['pct_sinag'])} de su horario", C_MUTED),
        ("Potencial no aprovechado", bs(k['potencial_no_aprovechado'], 0), f"estimado a 100% ({k['h_no_pagadas_txt']})", C_MORADO),
    ]
    if r.get('proximos'):   # inactivos: sin disponibilidad futura
        px_ = r['proximos']
        items_h.append(("Libre próximos 14 días", px_['libre_txt'], f"de {px_['cap_txt']} de horario ({pc(px_['ocup'])} agendado)", C_AMBER))
    d.grilla(items_h, cols=4)
    d.subtitulo("Que paso con cada hora de su horario")
    d.barra_apilada([(x['label'], x['pct'], x['color'], x['txt']) for x in r['desglose'] if x['pct'] > 0])
    d.tabla(["Causa", "Horas", "% del horario", "Se cobra"],
            [[x['label'], x['txt'], pc(x['pct']),
              "Sí" if 'Falta' in x['label'] or 'efectivo' in x['label'] else ("Pendiente" if 'Programada' in x['label'] else "No")]
             for x in r['desglose']],
            [7.2 * cm, 3.2 * cm, 3.6 * cm, 3.6 * cm], ['l', 'r', 'r', 'c'])

    d.subtitulo("Ocupación por día de la semana")
    d.barras_h([(w['dia'], w['ocup'], f"{pc(w['ocup'])} | {w['n_atend']} ses. | {w['att_txt']}",
                 C_ROJO if w['ocup'] >= 85 else C_VERDE if w['ocup'] >= 60 else C_AMBER if w['ocup'] >= 35 else C_MORADO)
                for w in r['por_dia_semana'] if w['cap'] or w['n']], max_val=100)
    if r['heat']:
        d.subtitulo("Mapa de calor (hora x día): % de ocupación de su horario")
        d.heat(r['heat'], r['heat_horas'])
    if r['franjas_libres']:
        d.parrafo("Franjas con más tiempo libre: " + " | ".join(f"{f['h']} ({pc(f['ocup'])})" for f in r['franjas_libres']), 7.5, C_TSEC)
        d.parrafo("Franjas más llenas: " + " | ".join(f"{f['h']} ({pc(f['ocup'])})" for f in r['franjas_llenas']), 7.5, C_TSEC)

    d.subtitulo("Horario base considerado")
    d.parrafo(r['horario']['fuente_txt'], 7.5, C_TSEC)
    d.tabla(["Día", "Bloques", "Horas"], [[x['dia'], ' / '.join(x['bloques']) or 'Libre', x['horas_txt']] for x in r['horario']['semana']],
            [3.4 * cm, 10.0 * cm, 3.4 * cm], ['l', 'l', 'r'])
    if r['horario']['especiales']:
        d.parrafo("Fechas especiales: " + "; ".join(f"{fd(e['fecha'], '%d/%m')} ({e['tipo']}{': ' + e['motivo'] if e['motivo'] else ''})"
                                                      for e in r['horario']['especiales']), 7, C_MUTED)

    d.subtitulo("Marcaje de asistencia vs. horas con pacientes")
    mk = r['marcaje']
    if mk.get('disponible'):
        d.tabla(["Indicador", "Valor"], [
            ["Horas en el centro (marcaje)", mk['presencia_txt']],
            ["Horas con pacientes (mismos días)", f"{mk['atendido_txt']}  ({pc(mk['uso_presencia'])} de su presencia)"],
            ["En el centro sin paciente", mk['ocioso_txt']],
            ["Puntualidad de ingreso", f"{pc(mk['puntualidad'])}  ({mk['tardanzas']} tardanzas de {mk['entradas']} ingresos)"],
            ["Días con horario sin marcaje", f"{mk['dias_sin_marcaje']} de {mk['dias_horario']}"],
        ], [7.2 * cm, 10.4 * cm], ['l', 'l'])
    else:
        d.parrafo(mk.get('motivo', ''), 7.5, C_MUTED)

    if r.get('proximos'):
        px = r['proximos']
        d.subtitulo(f"Huecos disponibles - próximos {px['dias']} días (desde {fd(px['desde'], '%d/%m')} hasta {fd(px['hasta'])})")
        d.parrafo(f"Libres {px['libre_txt']} de {px['cap_txt']} de horario ({pc(px['ocup'])} ya agendado). "
                  "Se calcula siempre desde hoy, sin importar el período del informe.", 7.2, C_MUTED)
        d.tabla(["Fecha", "Franja libre", "Duración"],
                [[f"{h['dia']} {fd(h['fecha'])}", f"{h['ini']} - {h['fin']}", h['txt']] for h in px['huecos'][:30]],
                [5.2 * cm, 6.4 * cm, 3.4 * cm], ['l', 'l', 'r'])


def _sec_evolucion(d, r):
    d.page(land=False)
    d.titulo("5. Rendimiento por mes, semana y día", C_MED)
    if r['por_mes']:
        d.subtitulo("Generado por mes (Bs.)  |  columna verde = atendidas, roja = faltas")
        d.columnas([g['label'] for g in r['por_mes']], [g['gen'] for g in r['por_mes']], C_VERDE)
    cab = ["Período", "Atend.", "Faltas", "Horario", "Trabajo", "Libre", "Libres x inasist.", "Sin agendar", "Ocup. efect.", "Generado"]
    w = [2.6 * cm, 1.2 * cm, 1.2 * cm, 1.7 * cm, 1.7 * cm, 1.7 * cm, 2.1 * cm, 1.9 * cm, 1.7 * cm, 2.1 * cm]
    al = ['l'] + ['r'] * 9
    fila = lambda g: [g['label'], g['n_atend'], g['n_falta'], g['cap_txt'], g['att_txt'], g['libre_txt'], g['perd_txt'],
                      g['sinag_txt'], pc(g['ocup_efect']), fm(g['gen'], 0)]
    d.subtitulo("Por mes")
    d.tabla(cab, [fila(g) for g in r['por_mes']], w, al, 6.8)
    d.subtitulo("Por semana")
    d.tabla(cab, [fila(g) for g in r['por_semana']], w, al, 6.8)
    d.subtitulo("Por día")
    d.tabla(["Fecha", "Horario", "Ses.", "Atend.", "Falta", "Prog.", "Trabajo", "Libre", "Ocup.", "Generado"],
            [[f"{x['dia_c']} {fd(x['fecha'])}", ' / '.join(x['bloques']) or 'libre', x['n'], x['n_atend'], x['n_falta'], x['n_prog'],
              x['att_txt'], x['libre_txt'], pc(x['ocup']) if x['cap'] else '-', fm(x['gen'], 0)]
             for x in r['por_dia'] if x['cap'] or x['n']],
            [2.8 * cm, 3.6 * cm, 1.0 * cm, 1.2 * cm, 1.1 * cm, 1.1 * cm, 1.7 * cm, 1.7 * cm, 1.5 * cm, 1.9 * cm],
            ['l', 'l'] + ['r'] * 8, 6.6, row_h=0.42 * cm)


def _sec_ninos(d, r):
    d.page(land=False)
    d.titulo(f"6. Niños que atendió ({len(r['pacientes'])}" + (f", {r['n_ninos_inactivos']} inactivo(s)" if r.get('n_ninos_inactivos') else '') + ")", C_MORADO)
    d.tabla(["Niño", "Servicios", "Ses.", "Atend.", "Faltas", "Horas", "Asist.", "Individual", "Proy.", "Mens.", "Total"],
            [[p['nombre'] + (' (inactivo)' if p.get('inactivo') else ''), ', '.join(p['servicios']), p['n'], p['atend'], p['faltas'], p['horas_txt'], pc(p['tasa']),
              fm(p['gen_ind'], 0), fm(p['gen_proy'], 0), fm(p['gen_mens'], 0), (fm(p['gen'], 0), C_PRI)]
             for p in r['pacientes']],
            [3.4 * cm, 3.0 * cm, 0.9 * cm, 1.1 * cm, 1.1 * cm, 1.4 * cm, 1.3 * cm, 1.5 * cm, 1.2 * cm, 1.2 * cm, 1.4 * cm],
            ['l', 'l'] + ['r'] * 9, 6.6)
    d.subtitulo("Por servicio")
    d.tabla(["Servicio", "Ses.", "Atend.", "Niños", "Horas", "Generado Bs.", "% total"],
            [[s['nombre'], s['n'], s['atend'], s['pacs'], s['horas_txt'], fm(s['gen']), pc(s['pct_gen'])] for s in r['por_servicio']],
            [5.6 * cm, 1.5 * cm, 1.6 * cm, 1.5 * cm, 2.2 * cm, 3.0 * cm, 2.2 * cm], ['l'] + ['r'] * 6)
    if len(r['por_sucursal']) > 0:
        d.subtitulo("Por sucursal")
        d.tabla(["Sucursal", "Ses.", "Atend.", "Faltas", "Horas", "Generado Bs."],
                [[s['nombre'], s['n'], s['atend'], s['faltas'], s['horas_txt'], fm(s['gen'])] for s in r['por_sucursal']],
                [6.0 * cm, 1.8 * cm, 1.8 * cm, 1.8 * cm, 2.6 * cm, 3.6 * cm], ['l'] + ['r'] * 5)


def _sec_equipo(d, r):
    d.page(land=False)
    d.titulo("7. Equipo, tendencia, retención y calidad de registro", C_AMBER)
    eq = r.get('equipo')
    if eq:
        d.subtitulo("Ranking del equipo en el mismo período")
        d.tabla(["#", "Profesional", "Generado", "Horas", "Ocup. efect.", "Bs/hora", "Faltas"],
                [[(f['pos'], C_PRI if f['yo'] else C_TEXTO), (f['nombre'] + (' (este informe)' if f['yo'] else ''), C_PRI if f['yo'] else C_TEXTO),
                  fm(f['gen'], 0), f['horas_txt'], pc(f['ocup']), fm(f['ingreso_hora'], 0), pc(f['faltas'])] for f in eq['filas']],
                [0.9 * cm, 6.0 * cm, 2.4 * cm, 2.0 * cm, 2.2 * cm, 2.0 * cm, 2.1 * cm], ['c', 'l', 'r', 'r', 'r', 'r', 'r'])
        d.parrafo(f"Promedio del resto del equipo: ocupación {pc(eq['prom_ocup'])}, Bs. {fm(eq['prom_ingreso_hora'], 0)} por hora, "
                  f"faltas {pc(eq['prom_faltas'])}.", 7.5, C_TSEC)
    tn = r.get('tendencia')
    if tn:
        d.subtitulo("Tendencia de 6 meses")
        d.columnas([m['label'] for m in tn['meses']], [m['gen'] for m in tn['meses']], C_VERDE, alto=2.6 * cm)
        d.parrafo(tn['txt'] + " (los meses en curso o previos a su actividad no entran en el calculo)", 7.5, C_TSEC)
    rt = r.get('retencion')
    if rt:
        d.subtitulo("Retención de niños")
        d.parrafo(f"Activos (últimos 30 días): {rt['activos']}  |  Nuevos en el período: {rt['nuevos']}"
                  + (f"  |  Retención: {pc(rt['tasa_retencion'])} ({rt['retenidos']} de {rt['previos']} del período anterior)"
                     if rt['tasa_retencion'] is not None else ''), 7.8, C_TEXTO)
        if rt['riesgo_lista']:
            d.parrafo("En riesgo de abandono: " + ", ".join(x['nombre'] + (f" (últ. {fd(x['ultima'], '%d/%m')})" if x['ultima'] else '')
                                                            for x in rt['riesgo_lista']), 7.5, C_ROJO)
        if rt['seguidas']:
            d.parrafo("Faltas seguidas: " + ", ".join(f"{x['nombre']} ({x['n']})" for x in rt['seguidas']), 7.5, C_ROJO)
    cn = r.get('concentracion')
    if cn and cn['top']:
        d.subtitulo(f"Dependencia de pocos niños (riesgo {cn['nivel'].upper()})")
        d.barras_h([(t['nombre'], t['pct'], f"{pc(t['pct'])} | Bs. {fm(t['gen'], 0)}", C_AMBER) for t in cn['top']], max_val=100)
    nt = r.get('notas')
    if nt:
        d.subtitulo("Notas de evolución")
        d.parrafo(f"{nt['con_nota']} de {nt['atendidas']} sesiones atendidas tienen nota clínica ({pc(nt['pct'])}). "
                  f"Sin nota: {nt['sin_nota']}."
                  + (" Por niño: " + ", ".join(f"{x['nombre']} ({x['n']})" for x in nt['sin_por_paciente']) if nt['sin_por_paciente'] else ''),
                  7.6, C_TSEC)


def _sec_proyectos(d, r):
    d.page(land=True)
    d.titulo(f"8. Proyectos y evaluaciones ({len(r['proyectos'])})", C_MORADO)
    d.parrafo("Total indiv. = lo que valdrían TODAS las sesiones del proyecto (de todos los profesionales) a precio individual; Suyo indiv. = solo sus sesiones. Participación = Suyo / Total. "
              "Factor = costo del proyecto / valor a precio individual (menor a 1: descuento). Su parte se devenga conforme "
              "se realizan las sesiones.")
    d.tabla(["Código", "Niño", "Estado", "Modalidad", "Valor", "Total indiv.", "Suyo indiv.", "Factor", "Sus ses.", "Particip.", "Su parte", "Generado", "Por generar", "Cobrado"],
            [[p['codigo'], p['paciente'], p['estado'], p['modalidad'] + (' c/' + ', '.join(p['companeros'])[:22] if p['companeros'] else ''),
              fm(p['valor'], 0), fm(p['ref_total'], 0), fm(p['ref_mio'], 0), fm(p['factor']), f"{p['sesiones_mias']}/{p['sesiones_total']}", pc(p['share']),
              fm(p['atribuido'], 0), (fm(p['gen_periodo'], 0), C_PRI), fm(p['por_generar'], 0), pc(p.get('ratio_cobro', 0))]
             for p in r['proyectos']],
            [1.8 * cm, 3.4 * cm, 1.9 * cm, 3.4 * cm, 1.5 * cm, 1.6 * cm, 1.6 * cm, 1.2 * cm, 1.3 * cm, 1.5 * cm, 1.6 * cm, 1.6 * cm, 1.7 * cm, 1.5 * cm],
            ['l', 'l', 'l', 'l'] + ['r'] * 10, 6.5, x0=ML)
    d.titulo(f"9. Mensualidades ({len(r['mensualidades'])})", C_TEAL)
    d.tabla(["Código", "Niño", "Período", "Servicios que atiende", "Modalidad", "Costo", "Total indiv.", "Suyo indiv.", "Factor", "Sus ses.", "Particip.", "Su parte", "Por sesión", "Generado", "Cobrado"],
            [[m['codigo'], m['paciente'], m['periodo'], ', '.join(m['servicios']), m['modalidad'] + (' c/' + ', '.join(m['companeros'])[:18] if m['companeros'] else ''),
              fm(m['costo'], 0), fm(m['ref_total'], 0), fm(m['ref_mio'], 0), fm(m['factor']), f"{m['sesiones_mias']}/{m['sesiones_total']}", pc(m['share']),
              fm(m['atribuido'], 0), fm(m['por_sesion'], 0), (fm(m['gen_periodo'], 0), C_PRI), pc(m.get('ratio_cobro', 0))]
             for m in r['mensualidades']],
            [1.7 * cm, 3.0 * cm, 2.0 * cm, 2.8 * cm, 2.8 * cm, 1.3 * cm, 1.5 * cm, 1.5 * cm, 1.1 * cm, 1.3 * cm, 1.5 * cm, 1.5 * cm, 1.5 * cm, 1.6 * cm, 1.5 * cm],
            ['l', 'l', 'l', 'l', 'l'] + ['r'] * 10, 6.4)


def _sec_sesiones(d, r):
    d.page(land=True)
    d.titulo(f"10. Detalle de sesiones ({len(r['filas'])})", C_PRI)
    est_col = {'realizada': C_VERDE, 'realizada_retraso': C_AMBER, 'falta': C_ROJO, 'permiso': C_MORADO,
               'programada': C_MED}
    d.tabla(["Fecha", "Hora", "Niño", "Servicio", "Sucursal", "Tipo", "Estado", "Min", "Cobro", "Generó", "Nota"],
            [[f"{f['dia']} {fd(f['fecha'])}", f"{f['ini']}-{f['fin']}", f['paciente'], f['servicio'], f['sucursal'],
              'Individual' if f['tipo'] == 'individual' else f"{f['tipo'][:4].title()} {f['origen']}",
              (f['estado_txt'], est_col.get(f['estado'], C_TSEC)), f['dur'], (fm(f['monto'], 0) if f['tipo'] == 'individual' else 'paquete'),
              fm(f['generado'], 0) if f['generado'] else (f"({fm(f['por_generar'], 0)})" if f['por_generar'] else '-'),
              ('Sí' if f.get('tiene_nota') else 'No') if f['estado'] in ('realizada', 'realizada_retraso') else '']
             for f in r['filas']],
            [2.7 * cm, 2.1 * cm, 4.2 * cm, 3.6 * cm, 2.6 * cm, 2.6 * cm, 2.4 * cm, 1.0 * cm, 1.5 * cm, 1.8 * cm, 1.0 * cm],
            ['l', 'l', 'l', 'l', 'l', 'l', 'l', 'r', 'r', 'r', 'c'], 6.4, row_h=0.4 * cm)
    d.parrafo("Generó entre parentesis = por generar (sesión programada). En proyectos y mensualidades, 'Generó' es su parte ponderada del costo fijo.",
              6.8, C_MUTED, "Helvetica-Oblique")


# ─────────────────────────────────────────────────────────────────────
# ORQUESTADOR (2 pasadas para el total de páginas)
# ─────────────────────────────────────────────────────────────────────
def generar_informe_profesional_pdf(context):
    prof = context['profesional']
    r = context['r']
    desde, hasta = context['desde'], context['hasta']
    sucursal = context.get('sucursal')
    if desde == hasta:
        periodo = f"{desde.day} de {MESES_FULL[desde.month]} de {desde.year}"
    else:
        periodo = f"{fd(desde)}  al  {fd(hasta)}"
    fecha = _date.today().strftime('%d/%m/%Y')
    foto_path, es_tmp = _foto_path(prof)

    def construir(total):
        d = Doc(total, prof.nombre_completo, periodo, fecha)
        d.portada_inicio()
        _portada(d, prof, r, periodo, sucursal, foto_path)
        _sec_ejecutivo(d, r, prof)
        _sec_produccion(d, r)
        _sec_conciliacion(d, r)
        _sec_horas(d, r)
        _sec_evolucion(d, r)
        _sec_ninos(d, r)
        _sec_equipo(d, r)
        _sec_proyectos(d, r)
        _sec_sesiones(d, r)
        d.c.save()
        d.buf.seek(0)
        return d

    try:
        primera = construir(999)
        total = primera.pg
        final = construir(total)
        return final.buf
    finally:
        if es_tmp and foto_path and os.path.exists(foto_path):
            try:
                os.unlink(foto_path)
            except Exception:
                pass
