# egresos/ingreso_pdf_generator.py
# =====================================================
# GENERADOR DE PDF — COMPROBANTE DE INGRESO ADICIONAL ING-XXXX
# Misma arquitectura que facturacion/pdf_generator.py:
#   - Landscape letter, 2 copias lado a lado
#   - Línea de corte central
#   - Copia izquierda: ORIGINAL / Copia derecha: ADMINISTRACIÓN
# Diferencias visuales vs facturación:
#   - Paleta rojo/oscuro/naranja (salida de dinero)
#   - Barra superior degradado rojo-carmesí
#   - Caja EGR-XXXX en rojo oscuro
#   - Panel "Datos del Egreso" (categoría, proveedor, sucursal, método)
#   - Tabla: Concepto + detalles
#   - Sección sesiones cubiertas (honorarios) en morado
#   - Caja total verde "TOTAL INGRESO ADICIONAL"
#   - Badge ORIGINAL rojo oscuro / COPIA gris
#   - Firmas: Autorizado / Recibido por Proveedor
# =====================================================

import os
import logging
import hashlib
from io import BytesIO
from decimal import Decimal

from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.platypus import Table, TableStyle, Paragraph
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.graphics.shapes import Drawing
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics import renderPDF
from django.conf import settings

logger = logging.getLogger(__name__)

# =====================================================
# 1. PALETA — tonos rojo/oscuro (salida de dinero)
# =====================================================
COLOR_VERDE_PRIMARIO   = colors.HexColor('#1E8449')
COLOR_VERDE_CLARO      = colors.HexColor('#27AE60')
COLOR_VERDE_OSCURO     = colors.HexColor('#145A32')
COLOR_TEAL             = colors.HexColor('#0E6655')
COLOR_VERDE_TOTAL      = colors.HexColor('#1ABC9C')
COLOR_VERDE_TOTAL_CLARO= colors.HexColor('#A9DFBF')
COLOR_GRIS_MEDIO       = colors.HexColor('#888888')
COLOR_GRIS_CLARO       = colors.HexColor('#EEEEEE')
COLOR_GRIS_BORDE       = colors.HexColor('#BBBBBB')
COLOR_FONDO_PAGINA     = colors.HexColor('#F8F9FA')
COLOR_FONDO_TARJETA    = colors.white
COLOR_TEXTO_PRINCIPAL  = colors.HexColor('#212121')
COLOR_TEXTO_SECUNDARIO = colors.HexColor('#3D3D3D')
COLOR_FILA_PAR         = colors.HexColor('#F0FBF4')   # Verde muy tenue — zebra
COLOR_FILA_IMPAR       = colors.white

# Datos del Centro
NOMBRE_CENTRO = "Centro de Neurodesarrollo Infantil Misael"
DIRECCION     = "Calle Japón #28 • Potosí, Bolivia"
TELEFONO      = "Tel.: 76175352"

# Configuración de página — igual que facturación
PAGE_WIDTH, PAGE_HEIGHT = landscape(letter)
MARGIN       = 0.5 * cm
GAP_CENTRAL  = 1.0 * cm
ANCHO_RECIBO = (PAGE_WIDTH - (2 * MARGIN) - GAP_CENTRAL) / 2
ALTO_RECIBO  = PAGE_HEIGHT - (2 * MARGIN)


# =====================================================
# 2. UTILIDADES (mismo patrón que facturación)
# =====================================================

def _grad_h(c, x, y, w, h, c1, c2, steps=30):
    c.saveState()
    sw = w / steps
    for i in range(steps):
        t = i / steps
        c.setFillColor(colors.Color(
            c1.red   + (c2.red   - c1.red)   * t,
            c1.green + (c2.green - c1.green) * t,
            c1.blue  + (c2.blue  - c1.blue)  * t,
        ))
        c.rect(x + i * sw, y, sw + 1, h, fill=1, stroke=0)
    c.restoreState()


def _grad_r(c, x, y, w, h, c1, c2, r=8, steps=30):
    c.saveState()
    path = c.beginPath()
    path.roundRect(x, y, w, h, r)
    c.clipPath(path, stroke=0)
    sw = w / steps
    for i in range(steps):
        t = i / steps
        c.setFillColor(colors.Color(
            c1.red   + (c2.red   - c1.red)   * t,
            c1.green + (c2.green - c1.green) * t,
            c1.blue  + (c2.blue  - c1.blue)  * t,
        ))
        c.rect(x + i * sw, y, sw + 1, h, fill=1, stroke=0)
    c.restoreState()


def _sombra(c, x, y, w, h, r=10, off=2):
    c.saveState()
    c.setFillColor(colors.HexColor('#00000015'))
    c.roundRect(x + off, y - off, w, h, r, fill=1, stroke=0)
    c.restoreState()


def _qr(c, x, y, data, size=1.8 * cm):
    try:
        qw = QrCodeWidget(data)
        b  = qw.getBounds()
        dw, dh = b[2] - b[0], b[3] - b[1]
        d = Drawing(size, size, transform=[size / dw, 0, 0, size / dh, 0, 0])
        d.add(qw)
        renderPDF.draw(d, c, x, y)
    except Exception as e:
        logger.error(f"QR egreso error: {e}")


def _logo_path():
    bd = settings.BASE_DIR
    for p in [
        bd / 'centro_terapias_v2' / 'staticfiles' / 'img' / 'logo_misael.png',
        bd / 'staticfiles' / 'img' / 'logo_misael.png',
        bd / 'static' / 'img' / 'logo_misael.png',
    ]:
        if os.path.exists(p):
            return str(p)
    return None


def _s(v):
    return "" if v is None else str(v)


def _d(v):
    try:    return Decimal(str(v)) if v is not None else Decimal(0)
    except: return Decimal(0)


def _hash(num, fecha, monto):
    return hashlib.md5(f"{num}{fecha}{monto}".encode()).hexdigest()[:8].upper()


def _letras(monto):
    try:
        monto = Decimal(monto).quantize(Decimal('0.01'))
        ent = int(monto)
        dec = int(round((monto - ent) * 100))
        return f"{_nl(ent)} {dec:02d}/100 BOLIVIANOS".upper()
    except:
        return "MONTO NO VÁLIDO"


def _nl(n):
    if n == 0: return "CERO"
    U   = ["","UN","DOS","TRES","CUATRO","CINCO","SEIS","SIETE","OCHO","NUEVE"]
    D   = ["","DIEZ","VEINTE","TREINTA","CUARENTA","CINCUENTA","SESENTA","SETENTA","OCHENTA","NOVENTA"]
    D10 = ["DIEZ","ONCE","DOCE","TRECE","CATORCE","QUINCE","DIECISEIS","DIECISIETE","DIECIOCHO","DIECINUEVE"]
    D20 = ["VEINTE","VEINTIUNO","VEINTIDOS","VEINTITRES","VEINTICUATRO","VEINTICINCO",
           "VEINTISEIS","VEINTISIETE","VEINTIOCHO","VEINTINUEVE"]
    C   = ["","CIENTO","DOSCIENTOS","TRESCIENTOS","CUATROCIENTOS","QUINIENTOS",
           "SEISCIENTOS","SETECIENTOS","OCHOCIENTOS","NOVECIENTOS"]
    if n < 10:   return U[n]
    if n < 20:   return D10[n - 10]
    if n < 30:   return D20[n - 20]
    if n < 100:  return D[n // 10] + (" Y " + U[n % 10] if n % 10 else "")
    if n == 100: return "CIEN"
    if n < 1000: return C[n // 100] + (" " + _nl(n % 100) if n % 100 else "")
    if n < 1_000_000:
        m = n // 1000; r = n % 1000
        return ("MIL" if m == 1 else _nl(m) + " MIL") + (" " + _nl(r) if r else "")
    m = n // 1_000_000; r = n % 1_000_000
    return ("UN MILLON" if m == 1 else _nl(m) + " MILLONES") + (" " + _nl(r) if r else "")


# =====================================================
# 3. MARCA DE AGUA (mismo patrón que facturación)
# =====================================================

def _marca_agua(c, x, y):
    """Marca de agua en patrón repetido dentro del recibo."""
    lp = _logo_path()
    if not lp:
        return
    try:
        from PIL import Image
        img = Image.open(lp).convert('LA')
        buf = BytesIO(); img.save(buf, 'PNG'); buf.seek(0)
        ir = ImageReader(buf)
        iw, ih = ir.getSize()
        aspect = ih / float(iw)
        ls, lh  = 3.5 * cm, 3.5 * cm * aspect
        sx, sy  = 6.5 * cm, 5.0 * cm
        nc = int(ANCHO_RECIBO / sx) + 2
        nr = int(ALTO_RECIBO  / sy) + 2
        top = y + ALTO_RECIBO
        for row in range(nr):
            for col in range(nc):
                c.saveState()
                ox  = (sx / 2) if row % 2 else 0
                lx  = x + col * sx + ox - sx * 0.3
                ly  = y + row * sy - sy * 0.3
                lcy = ly + lh / 2
                if   lcy >= top - 4.0 * cm: opacity = 0.08
                elif lcy >= top - 6.0 * cm: opacity = 0.11
                else:                        opacity = 0.13
                c.setFillAlpha(opacity)
                c.translate(lx + ls / 2, ly + lh / 2)
                c.rotate(-25)
                c.translate(-(lx + ls / 2), -(ly + lh / 2))
                c.drawImage(ir, lx, ly, width=ls, height=lh,
                            mask='auto', preserveAspectRatio=True)
                c.restoreState()
    except Exception as e:
        logger.error(f"Marca agua egreso: {e}")


# =====================================================
# 4. SELLO ANULADO (mismo patrón que facturación)
# =====================================================

def _sello_anulado_pagina(c, pw, ph):
    c.saveState()
    c.translate(pw / 2, ph / 2)
    c.rotate(45)
    c.setFont("Helvetica-Bold", 130)
    c.setFillColor(colors.Color(0.5, 0, 0, alpha=0.20))
    c.drawCentredString(4, -4, "ANULADO")
    c.setFillColor(colors.Color(0.75, 0, 0, alpha=0.55))
    c.drawCentredString(0, 0, "ANULADO")
    c.restoreState()


# =====================================================
# 5. FUNCIÓN PÚBLICA
# =====================================================

def generar_ingreso_adicional_pdf(ingreso):
    """
    Genera el comprobante PDF del ingreso adicional ING-XXXX.
    Landscape letter con 2 copias: ORIGINAL (izquierda) + ADMINISTRACIÓN (derecha).
    Retorna bytes del PDF.
    """
    buf = BytesIO()
    c   = pdf_canvas.Canvas(buf, pagesize=landscape(letter))
    c.setTitle(f"IngresoAdicional_{ingreso.numero_ingreso}")

    # Fondo de página
    c.setFillColor(COLOR_FONDO_PAGINA)
    c.rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT, fill=1, stroke=0)

    # Copia izquierda — ORIGINAL
    _dibujar_recibo(c, MARGIN, MARGIN, ingreso, "ORIGINAL: ADMINISTRACIÓN")

    # Línea de corte
    _linea_corte(c)

    # Copia derecha — ARCHIVO
    _dibujar_recibo(c, MARGIN + ANCHO_RECIBO + GAP_CENTRAL, MARGIN, ingreso, "COPIA: ARCHIVO")

    # Sello ANULADO encima de todo (si aplica)
    if ingreso.anulado:
        _sello_anulado_pagina(c, PAGE_WIDTH, PAGE_HEIGHT)

    c.save()
    data = buf.getvalue()
    buf.close()
    return data


# =====================================================
# 6. DIBUJO DE UN RECIBO
# =====================================================

def _dibujar_recibo(c, x, y, ingreso, texto_copia):
    """Dibuja un recibo completo en las coordenadas (x, y)."""
    top = y + ALTO_RECIBO

    # ── A. Tarjeta base con sombra ──────────────────────────────────────────
    _sombra(c, x, y, ANCHO_RECIBO, ALTO_RECIBO, r=10, off=3)
    c.saveState()
    c.setFillColor(COLOR_FONDO_TARJETA)
    c.setStrokeColor(COLOR_GRIS_BORDE)
    c.setLineWidth(0.5)
    c.roundRect(x, y, ANCHO_RECIBO, ALTO_RECIBO, 10, fill=1, stroke=1)
    c.restoreState()

    # ── B. Barra superior degradado rojo ────────────────────────────────────
    bh = 0.45 * cm
    by = top - 0.6 * cm
    _grad_h(c, x + 0.2 * cm, by, ANCHO_RECIBO - 0.4 * cm, bh,
            COLOR_VERDE_CLARO, COLOR_VERDE_OSCURO)
    c.saveState()
    c.setStrokeColor(colors.white)
    c.setLineWidth(1.5)
    c.roundRect(x + 0.2 * cm, by, ANCHO_RECIBO - 0.4 * cm, bh, 5, fill=0, stroke=1)
    c.restoreState()

    # ── C. Header ────────────────────────────────────────────────────────────
    y_header = by - 0.3 * cm
    _header(c, x, y_header, ingreso)

    # ── D. Panel datos del egreso ─────────────────────────────────────────
    y_datos = y_header - 3.5 * cm
    h_datos = _panel_datos(c, x, y_datos, ingreso)

    # ── E. Tabla detalle ──────────────────────────────────────────────────
    y_tabla = y_datos - h_datos - 0.15 * cm
    h_tabla = _tabla(c, x, y_tabla, ingreso)

    # ── F. Sesiones cubiertas (honorarios) ───────────────────────────────
    y_ses = y_tabla - h_tabla - 0.25 * cm
    h_ses = _sesiones(c, x, y_ses, ingreso)

    # ── G. Observaciones ─────────────────────────────────────────────────
    y_obs = y_ses - h_ses - 0.2 * cm
    h_obs = _observaciones(c, x, y_obs, ingreso)

    # ── H. Totales ────────────────────────────────────────────────────────
    y_tot = y_obs - h_obs - 0.25 * cm
    _totales(c, x, y_tot, ingreso)

    # ── I. QR ─────────────────────────────────────────────────────────────
    _qr_seccion(c, x, y, ingreso)

    # ── J. Footer (badge copia) ───────────────────────────────────────────
    _footer(c, x, y, texto_copia)

    # ── K. Firmas ─────────────────────────────────────────────────────────
    _firmas(c, x, y)

    # ── L. Marca de agua ──────────────────────────────────────────────────
    _marca_agua(c, x, y)


# =====================================================
# 7. SECCIONES
# =====================================================

def _header(c, x, y_base, ingreso):
    """Logo + nombre centro + caja EGR-XXXX."""
    lp = _logo_path()
    if lp:
        try:
            ir = ImageReader(lp)
            iw, ih = ir.getSize()
            lw = 2.0 * cm
            lh = lw * (ih / float(iw))
            c.drawImage(lp, x + 0.5 * cm, y_base - lh,
                        width=lw, height=lh, mask='auto')
        except Exception:
            pass
    egreso = ingreso  # alias para reutilizar el resto de _header sin cambios

    tx = x + 2.8 * cm
    c.setFillColor(COLOR_TEXTO_PRINCIPAL)
    c.setFont("Helvetica-Bold", 11)
    w1 = c.stringWidth("Centro de Neurodesarrollo Infantil ", "Helvetica-Bold", 11)
    c.drawString(tx, y_base - 0.45 * cm, "Centro de Neurodesarrollo Infantil ")
    c.setFillColor(colors.HexColor('#4A0080'))
    c.setFont("Helvetica-Bold", 14)
    c.drawString(tx + w1, y_base - 0.47 * cm, "Misael")

    c.setFont("Helvetica", 8)
    c.setFillColor(COLOR_TEXTO_SECUNDARIO)
    c.drawString(tx, y_base - 1.0 * cm, DIRECCION)
    c.drawString(tx, y_base - 1.45 * cm, TELEFONO)

    c.setFont("Helvetica-Bold", 7)
    c.setFillColor(COLOR_VERDE_PRIMARIO)
    c.drawString(tx, y_base - 2.0 * cm, "COMPROBANTE DE INGRESO ADICIONAL")

    # Caja EGR-XXXX
    bw, bh = 4.0 * cm, 1.7 * cm
    bx = x + ANCHO_RECIBO - bw - 0.5 * cm
    by = y_base - 3.0 * cm
    _sombra(c, bx, by, bw, bh, r=8, off=2)
    _grad_r(c, bx, by, bw, bh, COLOR_VERDE_CLARO, COLOR_VERDE_OSCURO, r=8, steps=20)
    c.saveState()
    c.setStrokeColor(colors.white)
    c.setLineWidth(1.5)
    c.roundRect(bx, by, bw, bh, 8, fill=0, stroke=1)
    c.restoreState()
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 8)
    c.drawCentredString(bx + bw / 2, by + 1.2 * cm, "COMPROBANTE")
    c.setFont("Helvetica-Bold", 15)
    c.drawCentredString(bx + bw / 2, by + 0.35 * cm, ingreso.numero_ingreso)


def _panel_datos(c, x, y_base, ingreso):
    """
    Panel de datos usando tabla ReportLab para que textos largos
    hagan wrap automático sin desbordarse sobre la columna vecina.
    """
    px = x + 0.4 * cm
    pw = ANCHO_RECIBO - 0.8 * cm

    # ── Valores ──────────────────────────────────────────────────────────────
    fecha     = ingreso.fecha.strftime("%d/%m/%Y") if ingreso.fecha else "---"
    periodo   = ingreso.periodo_display if hasattr(ingreso, 'periodo_display') else "---"
    cat_nom   = ingreso.get_tipo_display() if ingreso.tipo else "---"
    cat_tipo  = ""  # IngresoAdicional no tiene subtipo
    proveedor = _s(ingreso.origen) if ingreso.origen else "Sin origen"
    sucursal  = _s(ingreso.sucursal.nombre)  if ingreso.sucursal  else "Global"
    metodo    = _s(ingreso.metodo_pago.nombre) if ingreso.metodo_pago else "---"

    # ── Estilos Paragraph para wrap ──────────────────────────────────────────
    sLbl = ParagraphStyle('lbl', fontName='Helvetica-Bold', fontSize=7.5,
                          textColor=COLOR_VERDE_OSCURO, leading=10)
    sVal = ParagraphStyle('val', fontName='Helvetica', fontSize=8,
                          textColor=COLOR_TEXTO_PRINCIPAL, leading=10)

    def P(txt, st): return Paragraph(txt, st)

    # 4 columnas: etiqueta | valor | etiqueta | valor
    lw = pw * 0.14   # etiqueta estrecha
    vw = pw * 0.36   # valor ancho
    col_widths = [lw, vw, lw, vw]

    tabla_data = [
        [P("FECHA:",     sLbl), P(fecha,                     sVal),
         P("PERÍODO:",   sLbl), P(periodo,                   sVal)],
        [P("TIPO:",       sLbl), P(cat_nom,                   sVal),
         P("ORIGEN:",    sLbl), P(proveedor,                 sVal)],
        [P("SUCURSAL:",  sLbl), P(sucursal,                  sVal),
         P("MÉTODO:",    sLbl), P(metodo,                    sVal)],
    ]

    t = Table(tabla_data, colWidths=col_widths)
    t.setStyle(TableStyle([
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING',    (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING',   (0, 0), (-1, -1), 4),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 4),
        ('LINEBELOW',     (0, 0), (-1, -2), 0.3, COLOR_GRIS_BORDE),
    ]))

    _, th = t.wrapOn(c, pw, ALTO_RECIBO)

    # Fondo + borde del panel (se adapta a la altura real calculada)
    c.saveState()
    c.setFillColor(COLOR_GRIS_CLARO)
    c.setFillAlpha(0.45)
    c.roundRect(px, y_base - th, pw, th, 6, fill=1, stroke=0)
    c.restoreState()

    c.saveState()
    c.setStrokeColor(COLOR_VERDE_PRIMARIO)
    c.setLineWidth(0.8)
    c.roundRect(px, y_base - th, pw, th, 6, fill=0, stroke=1)
    c.restoreState()

    t.drawOn(c, px, y_base - th)
    return th   # altura real — para que el caller ajuste y_tabla


def _tabla(c, x, y_base, ingreso):
    """Tabla concepto + detalles."""
    # Espacio extra antes del título
    titulo_y = y_base - 0.3 * cm

    c.setFont("Helvetica-Bold", 7.5)
    c.setFillColor(COLOR_VERDE_OSCURO)
    c.drawString(x + 0.5 * cm, titulo_y, "DETALLE DEL INGRESO ADICIONAL")

    c.saveState()
    c.setStrokeColor(COLOR_VERDE_PRIMARIO)
    c.setLineWidth(0.8)
    c.line(x + 0.4 * cm, titulo_y - 0.18 * cm,
           x + ANCHO_RECIBO - 0.4 * cm, titulo_y - 0.18 * cm)
    c.restoreState()

    yt      = titulo_y - 0.35 * cm
    monto   = _d(ingreso.monto)
    num_doc = _s(ingreso.numero_documento) or "—"

    headers = [["#", "DESCRIPCIÓN", "MONTO (Bs.)"]]
    filas   = [["1", _s(ingreso.concepto)[:70], f"{monto:,.2f}"]]
    if num_doc != "—":
        filas.append(["", "N° Documento: " + num_doc, ""])

    td   = headers + filas
    aw   = ANCHO_RECIBO - 0.8 * cm
    cols = [aw * 0.06, aw * 0.75, aw * 0.19]

    t  = Table(td, colWidths=cols, repeatRows=1)
    st = [
        ('BACKGROUND',   (0, 0), (-1, 0), COLOR_VERDE_PRIMARIO),
        ('TEXTCOLOR',    (0, 0), (-1, 0), colors.white),
        ('FONTNAME',     (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE',     (0, 0), (-1, 0), 8),
        ('ALIGN',        (0, 0), (0, -1), 'CENTER'),
        ('ALIGN',        (2, 0), (2, -1), 'RIGHT'),
        ('FONTNAME',     (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE',     (0, 1), (-1, -1), 8),
        ('TOPPADDING',   (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING',(0, 0), (-1, -1), 4),
        ('LEFTPADDING',  (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ('VALIGN',       (0, 0), (-1, -1), 'MIDDLE'),
        ('BOX',          (0, 0), (-1, -1), 1, COLOR_GRIS_MEDIO),
        ('LINEBELOW',    (0, 0), (-1, 0),  1.5, colors.white),
        ('INNERGRID',    (0, 1), (-1, -1), 0.5, COLOR_GRIS_CLARO),
    ]
    for i in range(1, len(td)):
        if i % 2 == 0:
            st.append(('BACKGROUND', (0, i), (-1, i), COLOR_FILA_PAR))

    t.setStyle(TableStyle(st))
    _, ht = t.wrapOn(c, aw, ALTO_RECIBO)
    t.drawOn(c, x + 0.4 * cm, yt - ht)
    return ht + 0.35 * cm


def _sesiones(c, x, y_base, ingreso):
    """Ingresos adicionales no tienen sesiones cubiertas."""
    return 0

def _sesiones_unused(c, x, y_base, ingreso):  # kept for reference
    try:
        sesiones = []
    except Exception:
        return 0
    if not sesiones:
        return 0

    c.setFont("Helvetica-Bold", 7.5)
    c.setFillColor(colors.HexColor('#4A235A'))
    c.drawString(x + 0.5 * cm, y_base, "SESIONES CUBIERTAS")

    c.saveState()
    c.setStrokeColor(colors.HexColor('#7D3C98'))
    c.setLineWidth(0.8)
    c.line(x + 0.4 * cm, y_base - 0.18 * cm,
           x + ANCHO_RECIBO - 0.4 * cm, y_base - 0.18 * cm)
    c.restoreState()

    yt = y_base - 0.35 * cm
    headers = [["Fecha", "Paciente", "Servicio", "Cobrado"]]
    filas = []
    for s in sesiones:
        fecha = s.fecha.strftime("%d/%m/%Y") if s.fecha else "---"
        filas.append([
            fecha,
            _s(s.paciente)[:20],
            _s(s.servicio.nombre if s.servicio else "---")[:18],
            f"Bs.{_d(s.monto_cobrado):,.0f}",
        ])

    MORADO = colors.HexColor('#7D3C98')
    LILA   = colors.HexColor('#F4ECF7')
    td   = headers + filas
    aw   = ANCHO_RECIBO - 0.8 * cm
    cols = [aw * 0.18, aw * 0.34, aw * 0.30, aw * 0.18]

    t  = Table(td, colWidths=cols, repeatRows=1)
    st = [
        ('BACKGROUND',   (0, 0), (-1, 0), MORADO),
        ('TEXTCOLOR',    (0, 0), (-1, 0), colors.white),
        ('FONTNAME',     (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE',     (0, 0), (-1, 0), 7.5),
        ('FONTNAME',     (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE',     (0, 1), (-1, -1), 7.5),
        ('ALIGN',        (3, 0), (3, -1), 'RIGHT'),
        ('TOPPADDING',   (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING',(0, 0), (-1, -1), 3),
        ('LEFTPADDING',  (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ('VALIGN',       (0, 0), (-1, -1), 'MIDDLE'),
        ('BOX',          (0, 0), (-1, -1), 1, COLOR_GRIS_MEDIO),
        ('LINEBELOW',    (0, 0), (-1, 0),  1.5, colors.white),
        ('INNERGRID',    (0, 1), (-1, -1), 0.5, COLOR_GRIS_CLARO),
    ]
    for i in range(1, len(td)):
        if i % 2 == 0:
            st.append(('BACKGROUND', (0, i), (-1, i), LILA))

    t.setStyle(TableStyle(st))
    _, ht = t.wrapOn(c, aw, ALTO_RECIBO)
    t.drawOn(c, x + 0.4 * cm, yt - ht)
    return ht + 0.35 * cm


def _observaciones(c, x, y_base, ingreso):
    """Panel de observaciones si existen."""
    obs = _s(getattr(ingreso, 'observaciones', ''))
    if not obs.strip():
        return 0

    pad = 0.25 * cm
    px  = x + 0.4 * cm
    pw  = ANCHO_RECIBO - 0.8 * cm

    est = ParagraphStyle('obs', fontName='Helvetica', fontSize=7.5,
                         textColor=COLOR_TEXTO_PRINCIPAL, leading=10)
    p   = Paragraph(obs, est)
    _, h = p.wrap(pw - 2 * pad, ALTO_RECIBO)
    ah = h + 2 * pad + 0.35 * cm

    c.saveState()
    c.setFillColor(COLOR_GRIS_CLARO)
    c.setFillAlpha(0.3)
    c.roundRect(px, y_base - ah, pw, ah, 5, fill=1, stroke=0)
    c.restoreState()

    c.saveState()
    c.setStrokeColor(COLOR_GRIS_BORDE)
    c.setLineWidth(0.5)
    c.roundRect(px, y_base - ah, pw, ah, 5, fill=0, stroke=1)
    c.restoreState()

    c.setFont("Helvetica-Bold", 7.5)
    c.setFillColor(COLOR_VERDE_OSCURO)
    c.drawString(px + pad, y_base - 0.4 * cm, "OBSERVACIONES:")
    p.drawOn(c, px + pad, y_base - ah + pad)
    return ah + 0.2 * cm


def _totales(c, x, y_base, ingreso):
    """Caja de total naranja + info de registro."""
    monto = _d(ingreso.monto)

    bw, bh = 5.2 * cm, 1.5 * cm
    bx = x + ANCHO_RECIBO - bw - 0.5 * cm
    by = y_base - bh

    _sombra(c, bx, by, bw, bh, r=8, off=2)
    _grad_r(c, bx, by, bw, bh, COLOR_VERDE_TOTAL_CLARO, COLOR_VERDE_TOTAL, r=8, steps=20)
    c.saveState()
    c.setStrokeColor(COLOR_VERDE_TOTAL)
    c.setLineWidth(1.5)
    c.roundRect(bx, by, bw, bh, 8, fill=0, stroke=1)
    c.restoreState()

    c.setFillColor(COLOR_TEXTO_PRINCIPAL)
    c.setFont("Helvetica-Bold", 9)
    c.drawRightString(bx + bw - 0.4 * cm, by + 1.0 * cm, "TOTAL PAGADO")
    c.setFont("Helvetica-Bold", 17)
    c.drawRightString(bx + bw - 0.4 * cm, by + 0.2 * cm, f"Bs. {monto:,.2f}")

    # Monto en letras
    c.setFillColor(COLOR_TEXTO_SECUNDARIO)
    c.setFont("Helvetica-BoldOblique", 6.5)
    c.drawRightString(x + ANCHO_RECIBO - 0.5 * cm,
                      by - 0.38 * cm, f"SON: {_letras(monto)}")

    # Registrado por (izquierda)
    reg = "---"
    if hasattr(ingreso, 'registrado_por') and ingreso.registrado_por:
        reg = ingreso.registrado_por.get_full_name() or ingreso.registrado_por.username
    fecha_reg = ingreso.fecha_registro.strftime("%d/%m/%Y %H:%M") if ingreso.fecha_registro else "---"

    xi = x + 0.6 * cm
    c.setFont("Helvetica-Bold", 7)
    c.setFillColor(COLOR_VERDE_OSCURO)
    c.drawString(xi, y_base - 0.4 * cm, "REGISTRADO POR:")
    c.setFont("Helvetica", 8)
    c.setFillColor(COLOR_TEXTO_PRINCIPAL)
    c.drawString(xi, y_base - 0.8 * cm, reg)

    c.setFont("Helvetica-Bold", 7)
    c.setFillColor(COLOR_VERDE_OSCURO)
    c.drawString(xi, y_base - 1.15 * cm, "FECHA DE REGISTRO:")
    c.setFont("Helvetica", 8)
    c.setFillColor(COLOR_TEXTO_PRINCIPAL)
    c.drawString(xi, y_base - 1.55 * cm, fecha_reg)


def _qr_seccion(c, x, y, ingreso):
    """QR de validación."""
    fs = ingreso.fecha.strftime("%Y%m%d") if ingreso.fecha else "00000000"
    m  = _d(ingreso.monto)
    hv = _hash(ingreso.numero_ingreso, fs, str(m))
    url= f"https://centromisael.com/validar/{ingreso.numero_ingreso}/{hv}"

    qs = 1.8 * cm
    qx = x + ANCHO_RECIBO - qs - 0.5 * cm
    qy = y + 2.4 * cm

    c.saveState()
    c.setFillColor(colors.white)
    c.setStrokeColor(COLOR_GRIS_MEDIO)
    c.setLineWidth(0.5)
    c.roundRect(qx - 0.1 * cm, qy - 0.1 * cm,
                qs + 0.2 * cm, qs + 0.2 * cm, 4, fill=1, stroke=1)
    c.restoreState()

    _qr(c, qx, qy, url, qs)

    c.setFont("Helvetica", 6)
    c.setFillColor(COLOR_TEXTO_SECUNDARIO)
    c.drawCentredString(qx + qs / 2, qy - 0.35 * cm, "Escanea para validar")
    c.setFont("Helvetica-Bold", 6)
    c.setFillColor(COLOR_TEXTO_PRINCIPAL)
    c.drawCentredString(qx + qs / 2, qy - 0.65 * cm, f"#{hv}")


def _footer(c, x, y, texto_copia):
    """Badge de copia — ORIGINAL rojo / COPIA gris (mismo patrón que facturación)."""
    y_footer = y + 0.35 * cm

    if "ORIGINAL" in texto_copia:
        bg = COLOR_VERDE_OSCURO       # Verde oscuro para ORIGINAL
        fg = colors.white
    else:
        bg = COLOR_GRIS_CLARO
        fg = COLOR_TEXTO_PRINCIPAL

    bw, bh = 6.5 * cm, 0.6 * cm
    bx = x + ANCHO_RECIBO / 2 - bw / 2

    _sombra(c, bx, y_footer, bw, bh, r=6, off=1)
    c.setFillColor(bg)
    c.roundRect(bx, y_footer, bw, bh, 6, fill=1, stroke=0)
    c.setFillColor(fg)
    c.setFont("Helvetica-Bold", 8)
    c.drawCentredString(x + ANCHO_RECIBO / 2, y_footer + 0.18 * cm, texto_copia)


def _firmas(c, x, y):
    """Líneas de firma — Autorizado por / Recibido por Proveedor."""
    y_firmas = y + 1.6 * cm

    c.saveState()
    c.setStrokeColor(COLOR_GRIS_MEDIO)
    c.setLineWidth(0.5)
    c.setDash([2, 2])

    c.line(x + 0.8 * cm, y_firmas, x + 4.5 * cm, y_firmas)
    c.setFont("Helvetica", 7)
    c.setFillColor(COLOR_TEXTO_SECUNDARIO)
    c.drawCentredString(x + 2.65 * cm, y_firmas - 0.3 * cm, "RECIBIDO POR")

    c.line(x + ANCHO_RECIBO - 6.5 * cm, y_firmas,
           x + ANCHO_RECIBO - 2.8 * cm, y_firmas)
    c.drawCentredString(x + ANCHO_RECIBO - 4.65 * cm,
                        y_firmas - 0.3 * cm, "ENTREGADO POR / ORIGEN")

    c.setDash([])
    c.restoreState()


def _linea_corte(c):
    """Línea de corte punteada central — igual que facturación."""
    x = PAGE_WIDTH / 2
    c.saveState()
    c.setStrokeColor(COLOR_GRIS_MEDIO)
    c.setLineWidth(0.5)
    c.setDash([4, 4])
    c.line(x, MARGIN + 0.5 * cm, x, PAGE_HEIGHT - MARGIN - 0.5 * cm)
    c.setDash([])
    c.restoreState()
