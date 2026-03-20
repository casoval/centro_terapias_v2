# egresos/pdf_generator.py
# =====================================================
# GENERADOR DE PDF — COMPROBANTE DE EGRESO EGR-XXXX
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
#   - Caja total naranja "TOTAL EGRESO"
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
COLOR_ROJO_PRIMARIO    = colors.HexColor('#C0392B')
COLOR_ROJO_CLARO       = colors.HexColor('#E74C3C')
COLOR_ROJO_OSCURO      = colors.HexColor('#7B241C')
COLOR_CARMESI          = colors.HexColor('#922B21')
COLOR_NARANJA          = colors.HexColor('#E67E22')
COLOR_NARANJA_CLARO    = colors.HexColor('#FAD7A0')
COLOR_GRIS_MEDIO       = colors.HexColor('#888888')
COLOR_GRIS_CLARO       = colors.HexColor('#EEEEEE')
COLOR_GRIS_BORDE       = colors.HexColor('#BBBBBB')
COLOR_FONDO_PAGINA     = colors.HexColor('#F8F9FA')
COLOR_FONDO_TARJETA    = colors.white
COLOR_TEXTO_PRINCIPAL  = colors.HexColor('#212121')
COLOR_TEXTO_SECUNDARIO = colors.HexColor('#3D3D3D')
COLOR_FILA_PAR         = colors.HexColor('#FDF2F2')   # Rojo muy tenue — zebra
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

def generar_egreso_pdf(egreso):
    """
    Genera el comprobante PDF del egreso EGR-XXXX.
    Landscape letter con 2 copias: ORIGINAL (izquierda) + ADMINISTRACIÓN (derecha).

    Si el egreso tiene un PagoHonorario vinculado (egreso.pago_honorario) y ese
    pago incluye sesiones, se agrega automáticamente una segunda página portrait
    con el detalle completo de las sesiones liquidadas al profesional.

    Retorna bytes del PDF.
    """
    buf = BytesIO()
    c   = pdf_canvas.Canvas(buf, pagesize=landscape(letter))
    c.setTitle(f"Egreso_{egreso.numero_egreso}")

    # ── Página 1: comprobante doble landscape ────────────────────────────────
    c.setFillColor(COLOR_FONDO_PAGINA)
    c.rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT, fill=1, stroke=0)

    _dibujar_recibo(c, MARGIN, MARGIN, egreso, "ORIGINAL: PROVEEDOR")
    _linea_corte(c)
    _dibujar_recibo(c, MARGIN + ANCHO_RECIBO + GAP_CENTRAL, MARGIN, egreso, "COPIA: ADMINISTRACIÓN")

    if egreso.anulado:
        _sello_anulado_pagina(c, PAGE_WIDTH, PAGE_HEIGHT)

    # ── Página 2: detalle de sesiones (solo honorarios con PagoHonorario) ────
    pago_honorario = getattr(egreso, 'pago_honorario', None)
    sesiones = _extraer_sesiones_pago_honorario(pago_honorario)

    if sesiones:
        c.showPage()
        from reportlab.lib.pagesizes import letter as _portrait
        pw, ph = _portrait
        c.setPageSize((pw, ph))
        c.setFillColor(COLOR_FONDO_PAGINA)
        c.rect(0, 0, pw, ph, fill=1, stroke=0)
        _pagina_detalle_sesiones_honorario(c, egreso, pago_honorario, sesiones, pw, ph)
        if egreso.anulado:
            _sello_anulado_pagina(c, pw, ph)

    c.save()
    data = buf.getvalue()
    buf.close()
    return data


# =====================================================
# 6. DIBUJO DE UN RECIBO
# =====================================================

def _dibujar_recibo(c, x, y, egreso, texto_copia):
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
            COLOR_ROJO_CLARO, COLOR_ROJO_OSCURO)
    c.saveState()
    c.setStrokeColor(colors.white)
    c.setLineWidth(1.5)
    c.roundRect(x + 0.2 * cm, by, ANCHO_RECIBO - 0.4 * cm, bh, 5, fill=0, stroke=1)
    c.restoreState()

    # ── C. Header ────────────────────────────────────────────────────────────
    y_header = by - 0.3 * cm
    _header(c, x, y_header, egreso)

    # ── D. Panel datos del egreso ─────────────────────────────────────────
    y_datos = y_header - 3.5 * cm
    h_datos = _panel_datos(c, x, y_datos, egreso)

    # ── E. Tabla detalle ──────────────────────────────────────────────────
    y_tabla = y_datos - h_datos - 0.15 * cm
    h_tabla = _tabla(c, x, y_tabla, egreso)

    # ── F. Sesiones cubiertas (honorarios) ───────────────────────────────
    y_ses = y_tabla - h_tabla - 0.25 * cm
    h_ses = _sesiones(c, x, y_ses, egreso)

    # ── G. Observaciones ─────────────────────────────────────────────────
    y_obs = y_ses - h_ses - 0.2 * cm
    h_obs = _observaciones(c, x, y_obs, egreso)

    # ── H. Totales ────────────────────────────────────────────────────────
    y_tot = y_obs - h_obs - 0.25 * cm
    _totales(c, x, y_tot, egreso)

    # ── I. QR ─────────────────────────────────────────────────────────────
    _qr_seccion(c, x, y, egreso)

    # ── J. Footer (badge copia) ───────────────────────────────────────────
    _footer(c, x, y, texto_copia)

    # ── K. Firmas ─────────────────────────────────────────────────────────
    _firmas(c, x, y)

    # ── L. Marca de agua ──────────────────────────────────────────────────
    _marca_agua(c, x, y)


# =====================================================
# 7. SECCIONES
# =====================================================

def _header(c, x, y_base, egreso):
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
    c.setFillColor(COLOR_ROJO_PRIMARIO)
    c.drawString(tx, y_base - 2.0 * cm, "COMPROBANTE DE PAGO")

    # Caja EGR-XXXX
    bw, bh = 4.0 * cm, 1.7 * cm
    bx = x + ANCHO_RECIBO - bw - 0.5 * cm
    by = y_base - 3.0 * cm
    _sombra(c, bx, by, bw, bh, r=8, off=2)
    _grad_r(c, bx, by, bw, bh, COLOR_ROJO_CLARO, COLOR_ROJO_OSCURO, r=8, steps=20)
    c.saveState()
    c.setStrokeColor(colors.white)
    c.setLineWidth(1.5)
    c.roundRect(bx, by, bw, bh, 8, fill=0, stroke=1)
    c.restoreState()
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 8)
    c.drawCentredString(bx + bw / 2, by + 1.2 * cm, "COMPROBANTE")
    c.setFont("Helvetica-Bold", 15)
    c.drawCentredString(bx + bw / 2, by + 0.35 * cm, egreso.numero_egreso)


def _panel_datos(c, x, y_base, egreso):
    """
    Panel de datos usando tabla ReportLab para que textos largos
    hagan wrap automático sin desbordarse sobre la columna vecina.
    """
    px = x + 0.4 * cm
    pw = ANCHO_RECIBO - 0.8 * cm

    # ── Valores ──────────────────────────────────────────────────────────────
    fecha     = egreso.fecha.strftime("%d/%m/%Y") if egreso.fecha else "---"
    periodo   = egreso.periodo_display if hasattr(egreso, 'periodo_display') else "---"
    cat_nom   = _s(egreso.categoria.nombre) if egreso.categoria else "---"
    cat_tipo  = egreso.categoria.get_tipo_display() if egreso.categoria else "---"
    proveedor = _s(egreso.proveedor.nombre) if egreso.proveedor else "Sin proveedor"
    sucursal  = _s(egreso.sucursal.nombre)  if egreso.sucursal  else "Global"
    metodo    = _s(egreso.metodo_pago.nombre) if egreso.metodo_pago else "---"

    # ── Estilos Paragraph para wrap ──────────────────────────────────────────
    sLbl = ParagraphStyle('lbl', fontName='Helvetica-Bold', fontSize=7.5,
                          textColor=COLOR_ROJO_OSCURO, leading=10)
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
        [P("CATEGORÍA:", sLbl), P(f"{cat_nom} ({cat_tipo})", sVal),
         P("PROVEEDOR:", sLbl), P(proveedor,                 sVal)],
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
    c.setStrokeColor(COLOR_ROJO_PRIMARIO)
    c.setLineWidth(0.8)
    c.roundRect(px, y_base - th, pw, th, 6, fill=0, stroke=1)
    c.restoreState()

    t.drawOn(c, px, y_base - th)
    return th   # altura real — para que el caller ajuste y_tabla


def _tabla(c, x, y_base, egreso):
    """Tabla concepto + detalles."""
    # Espacio extra antes del título
    titulo_y = y_base - 0.3 * cm

    c.setFont("Helvetica-Bold", 7.5)
    c.setFillColor(COLOR_ROJO_OSCURO)
    c.drawString(x + 0.5 * cm, titulo_y, "DETALLE DEL EGRESO")

    c.saveState()
    c.setStrokeColor(COLOR_ROJO_PRIMARIO)
    c.setLineWidth(0.8)
    c.line(x + 0.4 * cm, titulo_y - 0.18 * cm,
           x + ANCHO_RECIBO - 0.4 * cm, titulo_y - 0.18 * cm)
    c.restoreState()

    yt      = titulo_y - 0.35 * cm
    monto   = _d(egreso.monto)
    num_tr  = _s(egreso.numero_transaccion)          or "—"
    num_dp  = _s(egreso.numero_documento_proveedor)  or "—"

    headers = [["#", "DESCRIPCIÓN", "MONTO (Bs.)"]]
    filas   = [["1", _s(egreso.concepto)[:70], f"{monto:,.2f}"]]
    if num_tr != "—":
        filas.append(["", "N° Transacción: " + num_tr, ""])
    if num_dp != "—":
        filas.append(["", "N° Doc. Proveedor: " + num_dp, ""])

    td   = headers + filas
    aw   = ANCHO_RECIBO - 0.8 * cm
    cols = [aw * 0.06, aw * 0.75, aw * 0.19]

    t  = Table(td, colWidths=cols, repeatRows=1)
    st = [
        ('BACKGROUND',   (0, 0), (-1, 0), COLOR_ROJO_PRIMARIO),
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


def _sesiones(c, x, y_base, egreso):
    """Tabla morada de sesiones cubiertas (solo honorarios) — página 1."""
    try:
        sesiones = egreso.sesiones_cubiertas.select_related('paciente', 'servicio').all()
    except Exception:
        return 0
    if not sesiones.exists():
        return 0

    # Obtener montos de ComisionSesion en una sola query
    sesion_ids = list(sesiones.values_list('id', flat=True))
    monto_por_sesion = {}
    try:
        from servicios.models import ComisionSesion
        for row in ComisionSesion.objects.filter(
            sesion_id__in=sesion_ids
        ).values('sesion_id', 'monto_profesional'):
            monto_por_sesion[row['sesion_id']] = _d(row['monto_profesional'])
    except Exception as e:
        logger.warning(f"No se pudo leer ComisionSesion en _sesiones: {e}")

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
    headers = [["Fecha", "Paciente", "Servicio", "Honorario"]]
    filas = []
    for s in sesiones:
        fecha = s.fecha.strftime("%d/%m/%Y") if s.fecha else "---"
        monto = monto_por_sesion.get(s.id, Decimal(0))
        filas.append([
            fecha,
            _s(s.paciente)[:20],
            _s(s.servicio.nombre if s.servicio else "---")[:18],
            f"Bs.{monto:,.0f}",
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


def _observaciones(c, x, y_base, egreso):
    """Panel de observaciones si existen."""
    obs = _s(getattr(egreso, 'observaciones', ''))
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
    c.setFillColor(COLOR_ROJO_OSCURO)
    c.drawString(px + pad, y_base - 0.4 * cm, "OBSERVACIONES:")
    p.drawOn(c, px + pad, y_base - ah + pad)
    return ah + 0.2 * cm


def _totales(c, x, y_base, egreso):
    """Caja de total naranja + info de registro."""
    monto = _d(egreso.monto)

    bw, bh = 5.2 * cm, 1.5 * cm
    bx = x + ANCHO_RECIBO - bw - 0.5 * cm
    by = y_base - bh

    _sombra(c, bx, by, bw, bh, r=8, off=2)
    _grad_r(c, bx, by, bw, bh, COLOR_NARANJA_CLARO, COLOR_NARANJA, r=8, steps=20)
    c.saveState()
    c.setStrokeColor(COLOR_NARANJA)
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
    if hasattr(egreso, 'registrado_por') and egreso.registrado_por:
        reg = egreso.registrado_por.get_full_name() or egreso.registrado_por.username
    fecha_reg = egreso.fecha_registro.strftime("%d/%m/%Y %H:%M") if egreso.fecha_registro else "---"

    xi = x + 0.6 * cm
    c.setFont("Helvetica-Bold", 7)
    c.setFillColor(COLOR_ROJO_OSCURO)
    c.drawString(xi, y_base - 0.4 * cm, "REGISTRADO POR:")
    c.setFont("Helvetica", 8)
    c.setFillColor(COLOR_TEXTO_PRINCIPAL)
    c.drawString(xi, y_base - 0.8 * cm, reg)

    c.setFont("Helvetica-Bold", 7)
    c.setFillColor(COLOR_ROJO_OSCURO)
    c.drawString(xi, y_base - 1.15 * cm, "FECHA DE REGISTRO:")
    c.setFont("Helvetica", 8)
    c.setFillColor(COLOR_TEXTO_PRINCIPAL)
    c.drawString(xi, y_base - 1.55 * cm, fecha_reg)


def _qr_seccion(c, x, y, egreso):
    """QR de validación."""
    fs = egreso.fecha.strftime("%Y%m%d") if egreso.fecha else "00000000"
    m  = _d(egreso.monto)
    hv = _hash(egreso.numero_egreso, fs, str(m))
    url= f"https://centromisael.com/validar/{egreso.numero_egreso}/{hv}"

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
        bg = COLOR_ROJO_OSCURO       # Rojo oscuro para ORIGINAL (≠ azul de facturación)
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
    c.drawCentredString(x + 2.65 * cm, y_firmas - 0.3 * cm, "AUTORIZADO POR")

    c.line(x + ANCHO_RECIBO - 6.5 * cm, y_firmas,
           x + ANCHO_RECIBO - 2.8 * cm, y_firmas)
    c.drawCentredString(x + ANCHO_RECIBO - 4.65 * cm,
                        y_firmas - 0.3 * cm, "RECIBIDO POR / PROVEEDOR")

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

# =====================================================
# 8. DETALLE DE SESIONES — PÁGINA 2 (HONORARIOS)
# =====================================================

def _extraer_sesiones_pago_honorario(pago_honorario):
    """
    Retorna lista de tuplas (sesion, monto_profesional_decimal) ordenadas
    por fecha y hora.

    Estrategia:
      1. Obtiene todas las sesiones del PagoHonorario (M2M).
      2. Hace una sola query a ComisionSesion filtrando por esas sesiones,
         construyendo un dict {sesion_id: monto_profesional} para lookup O(1).
      3. Devuelve las tuplas ya ordenadas.

    ComisionSesion vive en servicios.models y tiene FK 'sesion'.
    No asumimos ningún related_name en Sesion → evitamos el AttributeError.
    """
    if pago_honorario is None:
        return []
    try:
        # 1. Sesiones del pago ordenadas por fecha/hora
        sesiones_qs = (
            pago_honorario.sesiones
            .select_related('servicio', 'paciente')
            .order_by('fecha', 'hora_inicio')
        )
        sesiones_list = list(sesiones_qs)
        if not sesiones_list:
            return []

        # 2. Montos profesional desde ComisionSesion — una sola query
        sesion_ids = [s.id for s in sesiones_list]
        try:
            from servicios.models import ComisionSesion
            comisiones_qs = ComisionSesion.objects.filter(
                sesion_id__in=sesion_ids
            ).values('sesion_id', 'monto_profesional')
            # dict {sesion_id: monto_profesional}
            monto_por_sesion = {
                row['sesion_id']: _d(row['monto_profesional'])
                for row in comisiones_qs
            }
        except Exception as e:
            logger.warning(f"No se pudo leer ComisionSesion: {e}")
            monto_por_sesion = {}

        # 3. Construir resultado
        resultado = [
            (sesion, monto_por_sesion.get(sesion.id, Decimal(0)))
            for sesion in sesiones_list
        ]
        return resultado

    except Exception as e:
        logger.error(f"Error extrayendo sesiones PagoHonorario: {e}")
        return []


def _pagina_detalle_sesiones_honorario(c, egreso, pago_honorario, sesiones, pw, ph):
    """
    Página portrait con el detalle completo de las sesiones liquidadas.

    Estructura:
      1. Barra título verde
      2. Panel de encabezado (EGR, fecha, profesional, CI, cantidad sesiones)
      3. Tabla: # | Fecha | Hora | Paciente | Servicio | Estado | Monto Prof. (Bs.)
      4. Caja de totales: deuda calculada / monto pagado / diferencia / saldado
      5. Nota al pie + marca de agua
    """
    COLOR_VERDE_P  = colors.HexColor('#2E7D32')   # Verde primario para esta página
    COLOR_VERDE_CL = colors.HexColor('#81C784')   # Verde claro
    COLOR_VERDE_TX = colors.HexColor('#1B5E20')   # Verde oscuro para texto

    margen   = 1.4 * cm
    y_cursor = ph - margen

    # ── 1. Barra de título ────────────────────────────────────────────────────
    barra_h = 1.1 * cm
    _grad_h(c, margen, y_cursor - barra_h, pw - 2 * margen, barra_h,
            COLOR_VERDE_CL, COLOR_VERDE_P)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(pw / 2, y_cursor - barra_h + 0.34 * cm,
                        "DETALLE DE SESIONES LIQUIDADAS  —  HONORARIOS PROFESIONAL")
    y_cursor -= barra_h + 0.3 * cm

    # ── 2. Panel de encabezado ────────────────────────────────────────────────
    num_egreso  = _s(getattr(egreso, 'numero_egreso', '---'))
    fecha_egr   = getattr(egreso, 'fecha', None)
    fecha_str   = fecha_egr.strftime("%d/%m/%Y") if fecha_egr else "---"

    prof_nombre = "---"
    ci_prof     = "---"
    if pago_honorario and pago_honorario.profesional:
        pr = pago_honorario.profesional
        prof_nombre = f"{_s(pr.nombre)} {_s(pr.apellido)}".strip().title()
        ci_prof = _s(getattr(pr, 'ci', '') or getattr(pr, 'carnet', '') or '---')

    total_ses = len(sesiones)

    panel_h = 1.85 * cm
    panel_x = margen
    panel_y = y_cursor - panel_h

    # Fondo + borde del panel
    c.saveState()
    c.setFillColor(COLOR_GRIS_CLARO)
    c.setFillAlpha(0.45)
    c.roundRect(panel_x, panel_y, pw - 2 * margen, panel_h, 6, fill=1, stroke=0)
    c.restoreState()
    c.saveState()
    c.setStrokeColor(COLOR_VERDE_P)
    c.setLineWidth(0.8)
    c.roundRect(panel_x, panel_y, pw - 2 * margen, panel_h, 6, fill=0, stroke=1)
    c.restoreState()

    # Fila 1: N° Egreso | Fecha de pago | Centro
    y1 = y_cursor - 0.55 * cm

    c.setFont("Helvetica-Bold", 8)
    c.setFillColor(COLOR_VERDE_TX)
    c.drawString(panel_x + 0.4 * cm, y1, "N° EGRESO:")
    c.setFont("Helvetica-Bold", 9)
    c.setFillColor(COLOR_TEXTO_PRINCIPAL)
    c.drawString(panel_x + 2.3 * cm, y1, num_egreso)

    c.setFont("Helvetica-Bold", 8)
    c.setFillColor(COLOR_VERDE_TX)
    c.drawString(panel_x + 5.2 * cm, y1, "FECHA DE PAGO:")
    c.setFont("Helvetica", 9)
    c.setFillColor(COLOR_TEXTO_PRINCIPAL)
    c.drawString(panel_x + 7.7 * cm, y1, fecha_str)

    c.setFont("Helvetica-Bold", 8)
    c.setFillColor(COLOR_VERDE_TX)
    c.drawString(panel_x + 10.5 * cm, y1, "CENTRO:")
    c.setFont("Helvetica", 8)
    c.setFillColor(COLOR_TEXTO_PRINCIPAL)
    c.drawString(panel_x + 12.0 * cm, y1, NOMBRE_CENTRO)

    # Fila 2: Profesional | C.I. | Sesiones
    y2 = y_cursor - 1.20 * cm

    c.setFont("Helvetica-Bold", 8)
    c.setFillColor(COLOR_VERDE_TX)
    c.drawString(panel_x + 0.4 * cm, y2, "PROFESIONAL:")
    c.setFont("Helvetica-Bold", 10)
    c.setFillColor(COLOR_TEXTO_PRINCIPAL)
    c.drawString(panel_x + 2.8 * cm, y2, prof_nombre)

    c.setFont("Helvetica-Bold", 8)
    c.setFillColor(COLOR_VERDE_TX)
    c.drawString(panel_x + 9.5 * cm, y2, "C.I.:")
    c.setFont("Helvetica", 9)
    c.setFillColor(COLOR_TEXTO_PRINCIPAL)
    c.drawString(panel_x + 10.5 * cm, y2, ci_prof)

    c.setFont("Helvetica-Bold", 8)
    c.setFillColor(COLOR_VERDE_TX)
    c.drawString(panel_x + 12.8 * cm, y2, "SESIONES:")
    c.setFont("Helvetica-Bold", 10)
    c.setFillColor(COLOR_VERDE_P)
    c.drawString(panel_x + 14.5 * cm, y2, str(total_ses))

    y_cursor = panel_y - 0.45 * cm

    # Línea separadora
    c.setStrokeColor(COLOR_GRIS_MEDIO)
    c.setLineWidth(0.4)
    c.line(margen, y_cursor, pw - margen, y_cursor)
    y_cursor -= 0.35 * cm

    # ── 3. Tabla de sesiones ──────────────────────────────────────────────────
    ESTADOS = {
        'realizada':    'Realizada',
        'completada':   'Completada',
        'pendiente':    'Pendiente',
        'cancelada':    'Cancelada',
        'reprogramada': 'Reprogramada',
        'ausente':      'Ausente',
    }

    headers = [["#", "FECHA", "HORA", "PACIENTE", "SERVICIO", "ESTADO", "MONTO PROF. (Bs.)"]]
    filas_tabla = []

    for i, (sesion, monto_prof) in enumerate(sesiones, start=1):
        fecha_ses = getattr(sesion, 'fecha', None)
        f_str = fecha_ses.strftime("%d/%m/%Y") if fecha_ses else "---"

        hora_inicio = getattr(sesion, 'hora_inicio', None)
        h_str = "---"
        if hora_inicio:
            h_str = (hora_inicio.strftime("%H:%M")
                     if hasattr(hora_inicio, 'strftime')
                     else str(hora_inicio)[:5])

        pac_str = "---"
        if hasattr(sesion, 'paciente') and sesion.paciente:
            p = sesion.paciente
            pac_str = f"{_s(p.nombre)} {_s(p.apellido)}".strip().title()

        srv_str = "---"
        if hasattr(sesion, 'servicio') and sesion.servicio:
            srv_str = _s(sesion.servicio.nombre)

        estado_raw = getattr(sesion, 'estado', None)
        est_str = ESTADOS.get(str(estado_raw).lower(), str(estado_raw).title()) if estado_raw else "---"

        m_str = f"{monto_prof:,.2f}" if monto_prof else "0.00"

        filas_tabla.append([str(i), f_str, h_str, pac_str, srv_str, est_str, m_str])

    tabla_data = headers + filas_tabla
    ancho_tabla = pw - 2 * margen

    col_widths = [
        ancho_tabla * 0.04,   # #
        ancho_tabla * 0.10,   # Fecha
        ancho_tabla * 0.07,   # Hora
        ancho_tabla * 0.24,   # Paciente
        ancho_tabla * 0.24,   # Servicio
        ancho_tabla * 0.13,   # Estado
        ancho_tabla * 0.18,   # Monto Prof.
    ]

    tabla = Table(tabla_data, colWidths=col_widths, repeatRows=1)

    estilos = [
        # Header
        ('BACKGROUND',    (0, 0), (-1, 0),  COLOR_VERDE_P),
        ('TEXTCOLOR',     (0, 0), (-1, 0),  colors.white),
        ('FONTNAME',      (0, 0), (-1, 0),  'Helvetica-Bold'),
        ('FONTSIZE',      (0, 0), (-1, 0),  8),
        ('TOPPADDING',    (0, 0), (-1, 0),  5),
        ('BOTTOMPADDING', (0, 0), (-1, 0),  5),
        ('LINEBELOW',     (0, 0), (-1, 0),  1.5, colors.white),
        # Datos
        ('FONTNAME',      (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE',      (0, 1), (-1, -1), 8),
        ('TOPPADDING',    (0, 1), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 4),
        ('LEFTPADDING',   (0, 0), (-1, -1), 5),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 5),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
        # Alineación por columna
        ('ALIGN', (0, 0), (0, -1), 'CENTER'),   # #
        ('ALIGN', (1, 0), (1, -1), 'CENTER'),   # Fecha
        ('ALIGN', (2, 0), (2, -1), 'CENTER'),   # Hora
        ('ALIGN', (3, 0), (3, -1), 'LEFT'),     # Paciente
        ('ALIGN', (4, 0), (4, -1), 'LEFT'),     # Servicio
        ('ALIGN', (5, 0), (5, -1), 'CENTER'),   # Estado
        ('ALIGN', (6, 0), (6, -1), 'RIGHT'),    # Monto
        # Bordes
        ('BOX',       (0, 0), (-1, -1), 1,   COLOR_GRIS_MEDIO),
        ('INNERGRID', (0, 1), (-1, -1), 0.5, COLOR_GRIS_CLARO),
    ]

    # Zebra striping — verde muy tenue
    VERDE_TENUE = colors.HexColor('#F1F8E9')
    for i in range(1, len(tabla_data)):
        if i % 2 == 0:
            estilos.append(('BACKGROUND', (0, i), (-1, i), VERDE_TENUE))

    # Columna monto en verde y negrita
    for i in range(1, len(tabla_data)):
        estilos.append(('TEXTCOLOR', (6, i), (6, i), COLOR_VERDE_P))
        estilos.append(('FONTNAME',  (6, i), (6, i), 'Helvetica-Bold'))

    tabla.setStyle(TableStyle(estilos))

    # ── 3b. Paginación automática de la tabla ─────────────────────────────────
    #
    # Si las sesiones no caben en la primera hoja se agregan hojas adicionales
    # automáticamente usando tabla.split().  Cada hoja de continuación repite
    # un encabezado compacto y la misma nota al pie/marca de agua.
    #
    # • Primera hoja  → espacio = desde y_cursor hasta 4.8 cm del borde inferior
    #                   (reserva para la caja de totales)
    # • Hojas extra   → espacio = página completa menos márgenes superior/inferior
    #                   (sin reserva de totales; éstos solo van en la última hoja)

    RESERVA_TOTALES = 4.8 * cm   # altura mínima para la caja de totales al pie

    def _pie_pagina(reg_str):
        """Nota al pie + marca de agua — se repite en todas las hojas."""
        c.setFont("Helvetica-Oblique", 7)
        c.setFillColor(COLOR_TEXTO_SECUNDARIO)
        c.drawString(margen, margen + 0.55 * cm,
                     "Este documento es el respaldo del pago de honorarios profesionales. "
                     "Conservar junto al comprobante EGR-XXXX.")
        c.drawString(margen, margen + 0.20 * cm,
                     f"Registrado por: {reg_str}   |   {NOMBRE_CENTRO}   |   {DIRECCION}")
        lp2 = _logo_path()
        if lp2:
            try:
                from PIL import Image as _PIL
                img2 = _PIL.open(lp2).convert('LA')
                buf3 = BytesIO(); img2.save(buf3, 'PNG'); buf3.seek(0)
                ir2 = ImageReader(buf3)
                iw2, ih2 = ir2.getSize()
                asp2 = ih2 / float(iw2)
                ls2, lh2 = 3.5 * cm, 3.5 * cm * asp2
                sx2, sy2  = 6.5 * cm, 5.0 * cm
                nc2 = int(pw / sx2) + 2
                nr2 = int(ph / sy2) + 2
                for _row in range(nr2):
                    for _col in range(nc2):
                        c.saveState()
                        ox2 = (sx2 / 2) if _row % 2 else 0
                        lx2 = _col * sx2 + ox2 - sx2 * 0.3
                        ly2 = _row * sy2 - sy2 * 0.3
                        c.setFillAlpha(0.10)
                        c.translate(lx2 + ls2 / 2, ly2 + lh2 / 2)
                        c.rotate(-25)
                        c.translate(-(lx2 + ls2 / 2), -(ly2 + lh2 / 2))
                        c.drawImage(ir2, lx2, ly2, width=ls2, height=lh2,
                                    mask='auto', preserveAspectRatio=True)
                        c.restoreState()
            except Exception as _e:
                logger.error(f"Marca agua detalle sesiones (cont.): {_e}")

    reg_str = "---"
    if hasattr(egreso, 'registrado_por') and egreso.registrado_por:
        reg_str = (egreso.registrado_por.get_full_name()
                   or egreso.registrado_por.username)

    tabla_pendiente = tabla          # porción de tabla aún sin dibujar
    es_primera_hoja = True
    num_hoja        = 1

    while tabla_pendiente is not None:
        if es_primera_hoja:
            espacio_disp = y_cursor - margen - RESERVA_TOTALES
        else:
            # Nueva hoja portrait — fondo + encabezado de continuación
            c.showPage()
            c.setPageSize((pw, ph))
            c.setFillColor(COLOR_FONDO_PAGINA)
            c.rect(0, 0, pw, ph, fill=1, stroke=0)

            # Barra de continuación
            cont_barra_h = 0.75 * cm
            cont_y       = ph - margen
            _grad_h(c, margen, cont_y - cont_barra_h,
                    pw - 2 * margen, cont_barra_h,
                    COLOR_VERDE_CL, COLOR_VERDE_P)
            c.setFillColor(colors.white)
            c.setFont("Helvetica-Bold", 9)
            c.drawCentredString(
                pw / 2,
                cont_y - cont_barra_h + 0.22 * cm,
                f"DETALLE DE SESIONES  —  Continuación (hoja {num_hoja})"
            )
            y_cursor    = cont_y - cont_barra_h - 0.3 * cm
            espacio_disp = y_cursor - margen - RESERVA_TOTALES

            if egreso.anulado:
                _sello_anulado_pagina(c, pw, ph)

        # Dividir lo que cabe en esta hoja
        partes = tabla_pendiente.split(ancho_tabla, espacio_disp)
        parte_actual = partes[0]

        w_t, h_t = parte_actual.wrapOn(c, ancho_tabla, espacio_disp)
        parte_actual.drawOn(c, margen, y_cursor - h_t)
        y_cursor -= h_t + 0.5 * cm

        # ¿Quedan más filas?
        if len(partes) > 1:
            _pie_pagina(reg_str)          # pie en hoja intermedia
            tabla_pendiente = partes[1]
            es_primera_hoja = False
            num_hoja       += 1
        else:
            tabla_pendiente = None        # salir del bucle → dibujar totales

    # ── 4. Caja de totales al pie ─────────────────────────────────────────────
    monto_deuda  = _d(getattr(pago_honorario, 'monto_deuda',  0))
    monto_pagado = _d(getattr(pago_honorario, 'monto_pagado', 0))
    diferencia   = _d(getattr(pago_honorario, 'diferencia',   0))
    saldado      = getattr(pago_honorario, 'saldado', False)

    monto_literal = _letras(monto_pagado)

    box_w = 8.5 * cm
    box_h = 3.0 * cm
    box_x = pw - margen - box_w
    box_y = margen + 0.9 * cm

    _sombra(c, box_x, box_y, box_w, box_h, r=8, off=2)
    _grad_r(c, box_x, box_y, box_w, box_h,
            COLOR_NARANJA_CLARO, COLOR_NARANJA, r=8, steps=25)
    c.saveState()
    c.setStrokeColor(COLOR_NARANJA)
    c.setLineWidth(1)
    c.roundRect(box_x, box_y, box_w, box_h, 8, fill=0, stroke=1)
    c.restoreState()

    def _fila_caja(label, valor, y_pos, bold_val=False, col_val=None):
        c.setFont("Helvetica-Bold", 8.5)
        c.setFillColor(COLOR_TEXTO_SECUNDARIO)
        c.drawString(box_x + 0.4 * cm, y_pos, label)
        c.setFont("Helvetica-Bold" if bold_val else "Helvetica",
                  11 if bold_val else 9)
        c.setFillColor(col_val if col_val else COLOR_TEXTO_PRINCIPAL)
        c.drawRightString(box_x + box_w - 0.4 * cm, y_pos, valor)

    y_box = box_y + box_h - 0.60 * cm
    _fila_caja("Deuda calculada (sesiones seleccionadas):",
               f"Bs. {monto_deuda:,.2f}", y_box)

    y_box -= 0.70 * cm
    _fila_caja("Monto pagado realmente:",
               f"Bs. {monto_pagado:,.2f}", y_box,
               bold_val=True, col_val=COLOR_VERDE_P)

    y_box -= 0.70 * cm
    col_dif = COLOR_VERDE_P if diferencia <= 0 else COLOR_ROJO_PRIMARIO
    signo   = "+" if diferencia < 0 else ""
    _fila_caja("Diferencia (deuda − pagado):",
               f"Bs. {signo}{diferencia:,.2f}", y_box,
               col_val=col_dif)

    if saldado:
        y_box -= 0.55 * cm
        c.setFont("Helvetica-BoldOblique", 8)
        c.setFillColor(COLOR_VERDE_P)
        c.drawRightString(box_x + box_w - 0.4 * cm, y_box, "✔  Marcado como SALDADO")

    # Monto en letras
    c.setFont("Helvetica-BoldOblique", 7)
    c.setFillColor(COLOR_TEXTO_SECUNDARIO)
    c.drawRightString(pw - margen, box_y - 0.35 * cm, f"SON: {monto_literal}")

    # ── 5. Nota al pie + marca de agua (última hoja) ─────────────────────────
    _pie_pagina(reg_str)