# agenda/informe_evolucion_pdf.py
# =====================================================
# GENERADOR DE PDF - INFORME DE EVOLUCIÓN POR PACIENTE
# Hoja entera Letter portrait
# Agrupado por: Profesional → Servicio → Sesiones
# =====================================================

import os
import math
import logging
from io import BytesIO
from itertools import groupby
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.pdfbase.pdfmetrics import stringWidth
from django.conf import settings

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# PALETA
# ─────────────────────────────────────────────────────────────
C_AZUL_PRI   = colors.HexColor('#1E88E5')
C_AZUL_OSC   = colors.HexColor('#1565C0')
C_AZUL_FONDO = colors.HexColor('#E3F2FD')
C_CYAN       = colors.HexColor('#00ACC1')
C_CYAN_FONDO = colors.HexColor('#E0F7FA')
C_GRIS_CLARO = colors.HexColor('#F5F5F5')
C_GRIS_BORDE = colors.HexColor('#BBBBBB')
C_GRIS_MED   = colors.HexColor('#888888')
C_TEXTO      = colors.HexColor('#212121')
C_TEXTO_SEC  = colors.HexColor('#555555')
C_FONDO_PAG  = colors.HexColor('#F8F9FA')
C_ITALIC     = colors.HexColor('#9E9E9E')

ESTADO_COLORES = {
    'programada':        (colors.HexColor('#1565C0'), colors.HexColor('#E3F2FD')),
    'realizada':         (colors.HexColor('#2E7D32'), colors.HexColor('#E8F5E9')),
    'realizada_retraso': (colors.HexColor('#E65100'), colors.HexColor('#FFF3E0')),
    'falta':             (colors.HexColor('#B71C1C'), colors.HexColor('#FFEBEE')),
    'permiso':           (colors.HexColor('#6A1B9A'), colors.HexColor('#F3E5F5')),
    'cancelada':         (colors.HexColor('#424242'), colors.HexColor('#F5F5F5')),
    'reprogramada':      (colors.HexColor('#F57F17'), colors.HexColor('#FFFDE7')),
}
ESTADO_LABELS = {
    'programada':        'Programada',
    'realizada':         'Realizada',
    'realizada_retraso': 'Realizada con Retraso',
    'falta':             'Falta sin Aviso',
    'permiso':           'Permiso (con aviso)',
    'cancelada':         'Cancelada',
    'reprogramada':      'Reprogramada',
}
ESTADO_ICONOS = {
    'programada': '[ ]', 'realizada': '[OK]', 'realizada_retraso': '[~]',
    'falta': '[X]', 'permiso': '[P]', 'cancelada': '[-]', 'reprogramada': '[R]',
}

MESES = ['', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
         'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']

# ─────────────────────────────────────────────────────────────
# LAYOUT
# ─────────────────────────────────────────────────────────────
PAGE_W, PAGE_H = letter
MARGIN_L = 1.8 * cm
MARGIN_R = 1.8 * cm
MARGIN_T = 1.5 * cm
MARGIN_B = 1.5 * cm
CONTENT_W = PAGE_W - MARGIN_L - MARGIN_R

HEADER_H  = 2.8 * cm    # franja superior
INFO_H    = 1.4 * cm    # banda de datos del informe
GAP_POST_HEADER = 0.35 * cm
FOOTER_H  = 0.8 * cm

USABLE_Y_TOP    = PAGE_H - MARGIN_T - HEADER_H - INFO_H - GAP_POST_HEADER
USABLE_Y_BOTTOM = MARGIN_B + FOOTER_H + 0.2 * cm
USABLE_H        = USABLE_Y_TOP - USABLE_Y_BOTTOM

# Alturas fijas de elementos
H_SEP_PROF  = 0.9 * cm    # separador de profesional
H_SEP_SERV  = 0.65 * cm   # separador de servicio
H_GAP       = 0.30 * cm   # gap entre tarjetas
H_CARD_BASE = (0.72 + 0.75 + 0.22) * cm  # encabezado + datos + separador interno


# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────
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


def _grad(c, x, y, w, h, c1, c2, steps=28):
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


def _wrap_text(c, text, x, y, max_w, font, fsize, lh):
    """Dibuja texto con word-wrap. Retorna y final."""
    words = text.split()
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


def _notas_h(notas_text):
    """Altura que ocupa la sección de notas de una sesión."""
    label_h = 0.30 * cm
    gap     = 0.12 * cm
    if not notas_text:
        return label_h + gap + 0.40 * cm + 0.20 * cm
    chars_per_line = 97
    lines = math.ceil(max(1, len(notas_text) / chars_per_line))
    return label_h + gap + max(0.40 * cm, lines * 0.38 * cm) + 0.25 * cm


def _card_h(sesion):
    return H_CARD_BASE + _notas_h((sesion.notas_sesion or "").strip())


# ─────────────────────────────────────────────────────────────
# ENCABEZADO DE PÁGINA
# ─────────────────────────────────────────────────────────────
NOMBRE_CENTRO = "Centro de Neurodesarrollo Infantil Misael"
DIRECCION     = "Calle Japón #28 • Potosí, Bolivia"
TELEFONO      = "Tel.: 76175352"


def _encabezado(c, paciente, profesional_nombre, servicio_nombre,
                fecha_desde, fecha_hasta, estados_filtro, pg, total_pg):
    # Franja gradiente
    _grad(c, 0, PAGE_H - HEADER_H, PAGE_W, HEADER_H, C_AZUL_OSC, C_AZUL_PRI)

    # Logo
    lp = _logo()
    lh = HEADER_H - 0.45 * cm
    lw = lh
    lx = MARGIN_L
    ly = PAGE_H - HEADER_H + 0.22 * cm
    if lp:
        try:
            c.drawImage(lp, lx, ly, width=lw, height=lh,
                        preserveAspectRatio=True, mask='auto')
        except Exception:
            pass

    # Nombre del centro
    tx = lx + lw + 0.4 * cm
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 12.5)
    c.drawString(tx, PAGE_H - 1.0 * cm, NOMBRE_CENTRO)
    c.setFont("Helvetica", 7.5)
    c.drawString(tx, PAGE_H - 1.55 * cm, f"{DIRECCION}  •  {TELEFONO}")

    # Derecha: título + página
    c.setFont("Helvetica-Bold", 9)
    c.drawRightString(PAGE_W - MARGIN_R, PAGE_H - 0.95 * cm, "INFORME DE EVOLUCIÓN CLÍNICA")
    c.setFont("Helvetica", 7)
    c.drawRightString(PAGE_W - MARGIN_R, PAGE_H - 1.5 * cm, f"Página {pg} de {total_pg}")

    # ── Banda informativa: SOLO en la primera página ──────────
    if pg == 1:
        INFO_H_P1 = INFO_H * 1.4
        by = PAGE_H - HEADER_H - INFO_H_P1 - 0.08 * cm
        c.setFillColor(C_AZUL_FONDO)
        c.roundRect(MARGIN_L, by, CONTENT_W, INFO_H_P1, 5, fill=1, stroke=0)
        c.setStrokeColor(C_AZUL_PRI)
        c.setLineWidth(0.4)
        c.roundRect(MARGIN_L, by, CONTENT_W, INFO_H_P1, 5, fill=0, stroke=1)

        nombre_pac = (str(paciente.nombre_completo)
                      if hasattr(paciente, 'nombre_completo')
                      else f"{paciente.nombre} {paciente.apellido}")
        periodo = (f"{fecha_desde.strftime('%d/%m/%Y') if fecha_desde else '—'}"
                   f"  →  "
                   f"{fecha_hasta.strftime('%d/%m/%Y') if fecha_hasta else '—'}")
        estados_txt = ", ".join(estados_filtro) if estados_filtro else "Todos"

        cols = [
            ("PACIENTE", nombre_pac),
            ("PERÍODO",  periodo),
            ("ESTADOS",  estados_txt),
        ]
        cw = CONTENT_W / len(cols)
        for i, (lbl, val) in enumerate(cols):
            cx = MARGIN_L + i * cw + 0.35 * cm
            c.setFont("Helvetica-Bold", 7.5)
            c.setFillColor(C_AZUL_OSC)
            c.drawString(cx, by + INFO_H_P1 - 0.45 * cm, lbl)
            c.setFont("Helvetica", 9)
            c.setFillColor(C_TEXTO)
            max_chars = 32
            v = val if len(val) <= max_chars else val[:max_chars - 1] + "…"
            c.drawString(cx, by + 0.30 * cm, v)

        return PAGE_H - HEADER_H - INFO_H_P1 - 0.08 * cm - GAP_POST_HEADER

    else:
        # Páginas 2+ sin banda informativa
        return PAGE_H - HEADER_H - GAP_POST_HEADER

# ─────────────────────────────────────────────────────────────
# PIE DE PÁGINA
# ─────────────────────────────────────────────────────────────
def _pie(c, pg, total_pg, fecha_emision):
    fy = MARGIN_B
    c.setStrokeColor(C_GRIS_BORDE)
    c.setLineWidth(0.35)
    c.line(MARGIN_L, fy + 0.55 * cm, PAGE_W - MARGIN_R, fy + 0.55 * cm)
    c.setFont("Helvetica", 6.2)
    c.setFillColor(C_GRIS_MED)
    c.drawString(MARGIN_L, fy + 0.22 * cm,
                 f"{NOMBRE_CENTRO}  •  {DIRECCION}  •  {TELEFONO}")
    c.drawRightString(PAGE_W - MARGIN_R, fy + 0.22 * cm,
                      f"Emitido: {fecha_emision}   Pág. {pg}/{total_pg}")


# ─────────────────────────────────────────────────────────────
# SEPARADOR DE PROFESIONAL
# ─────────────────────────────────────────────────────────────
def _sep_profesional(c, y, nombre_prof, num_sesiones):
    """Dibuja la banda de separación de profesional. Retorna altura consumida."""
    h = H_SEP_PROF
    bx = MARGIN_L
    bw = CONTENT_W

    # Fondo con gradiente
    _grad(c, bx, y - h, bw, h, C_AZUL_OSC, C_AZUL_PRI)
    c.saveState()
    path = c.beginPath()
    path.roundRect(bx, y - h, bw, h, 6)
    c.clipPath(path, stroke=0)
    _grad(c, bx, y - h, bw, h, C_AZUL_OSC, C_AZUL_PRI)
    c.restoreState()

    # Borde
    c.setStrokeColor(C_AZUL_OSC)
    c.setLineWidth(0.5)
    c.roundRect(bx, y - h, bw, h, 6, fill=0, stroke=1)

    # Icono + nombre
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 9.5)
    c.drawString(bx + 0.5 * cm, y - h + 0.24 * cm,
                 f"PROFESIONAL:  {nombre_prof}")

    # Badge sesiones
    badge_txt = f"{num_sesiones} sesiones"
    bw_badge = stringWidth(badge_txt, "Helvetica-Bold", 7.5) + 0.4 * cm
    bx_badge = bx + bw - bw_badge - 0.4 * cm
    c.setFillColor(colors.white)
    c.roundRect(bx_badge, y - h + 0.12 * cm, bw_badge, 0.50 * cm, 4, fill=1, stroke=0)
    c.setFillColor(C_AZUL_OSC)
    c.setFont("Helvetica-Bold", 7.5)
    c.drawCentredString(bx_badge + bw_badge / 2, y - h + 0.23 * cm, badge_txt)

    return h


# ─────────────────────────────────────────────────────────────
# SEPARADOR DE SERVICIO
# ─────────────────────────────────────────────────────────────
def _sep_servicio(c, y, nombre_serv, num_sesiones):
    """Dibuja la banda de separación de servicio. Retorna altura consumida."""
    h = H_SEP_SERV
    bx = MARGIN_L + 0.4 * cm
    bw = CONTENT_W - 0.8 * cm

    c.setFillColor(C_CYAN_FONDO)
    c.roundRect(bx, y - h, bw, h, 4, fill=1, stroke=0)
    c.setStrokeColor(C_CYAN)
    c.setLineWidth(0.4)
    c.roundRect(bx, y - h, bw, h, 4, fill=0, stroke=1)

    # Línea acento izquierda
    c.setFillColor(C_CYAN)
    c.rect(bx, y - h, 0.22 * cm, h, fill=1, stroke=0)

    # Texto servicio
    c.setFillColor(C_TEXTO)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(bx + 0.38 * cm, y - h + 0.17 * cm,
                 f"Servicio:  {nombre_serv}")

    # Badge
    badge_txt = f"{num_sesiones} ses."
    bw_b = stringWidth(badge_txt, "Helvetica-Bold", 7) + 0.35 * cm
    bx_b = bx + bw - bw_b - 0.3 * cm
    c.setFillColor(C_CYAN)
    c.roundRect(bx_b, y - h + 0.10 * cm, bw_b, 0.40 * cm, 3, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 7)
    c.drawCentredString(bx_b + bw_b / 2, y - h + 0.16 * cm, badge_txt)

    return h


# ─────────────────────────────────────────────────────────────
# TARJETA DE SESIÓN
# ─────────────────────────────────────────────────────────────
def _tarjeta(c, sesion, y):
    """Dibuja la tarjeta de una sesión. Retorna altura consumida."""
    estado = sesion.estado
    c_txt, c_bg = ESTADO_COLORES.get(estado, (C_TEXTO, C_GRIS_CLARO))
    label = ESTADO_LABELS.get(estado, estado)
    notas = (sesion.notas_sesion or "").strip()

    ch = _card_h(sesion)
    bx = MARGIN_L + 0.8 * cm
    bw = CONTENT_W - 1.6 * cm

    # Fondo
    c.setFillColor(c_bg)
    c.roundRect(bx, y - ch, bw, ch, 5, fill=1, stroke=0)

    # Borde izquierdo de color
    c.setFillColor(c_txt)
    c.roundRect(bx, y - ch, 0.28 * cm, ch, 3, fill=1, stroke=0)

    # Borde exterior
    c.setStrokeColor(c_txt)
    c.setLineWidth(0.35)
    c.roundRect(bx, y - ch, bw, ch, 5, fill=0, stroke=1)

    # ── Encabezado de la tarjeta ──────────────────────────────
    hdr_h = 0.72 * cm
    c.setFillColor(c_txt)
    c.roundRect(bx, y - hdr_h, bw, hdr_h, 5, fill=1, stroke=0)
    c.rect(bx, y - hdr_h, bw, hdr_h / 2, fill=1, stroke=0)

    fecha_str = sesion.fecha.strftime("%d de %B de %Y").replace(
        sesion.fecha.strftime("%B"), MESES[sesion.fecha.month])
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(bx + 0.45 * cm, y - hdr_h + 0.22 * cm, fecha_str)
    c.setFont("Helvetica-Bold", 7.5)
    c.drawRightString(bx + bw - 0.35 * cm, y - hdr_h + 0.22 * cm, label)

    # ── Fila de datos ─────────────────────────────────────────
    datos_y = y - hdr_h - 0.75 * cm
    datos = [
        ("HORARIO",
         f"{sesion.hora_inicio.strftime('%H:%M')} – {sesion.hora_fin.strftime('%H:%M')}"),
        ("DURACIÓN", f"{sesion.duracion_minutos} min"),
        ("RETRASO",
         f"{sesion.minutos_retraso} min" if sesion.minutos_retraso else "—"),
    ]
    cw = (bw - 0.7 * cm) / len(datos)
    for i, (lbl, val) in enumerate(datos):
        dx = bx + 0.45 * cm + i * cw
        c.setFont("Helvetica-Bold", 6)
        c.setFillColor(C_AZUL_OSC)
        c.drawString(dx, datos_y + 0.40 * cm, lbl)
        c.setFont("Helvetica", 7.5)
        c.setFillColor(C_TEXTO)
        c.drawString(dx, datos_y + 0.08 * cm, val)

    # ── Separador punteado ────────────────────────────────────
    sep_y = y - hdr_h - 0.75 * cm - 0.22 * cm
    c.setStrokeColor(c_txt)
    c.setLineWidth(0.25)
    c.setDash([2, 3])
    c.line(bx + 0.45 * cm, sep_y + 0.11 * cm, bx + bw - 0.35 * cm, sep_y + 0.11 * cm)
    c.setDash([])

    # ── Notas ─────────────────────────────────────────────────
    ny = sep_y - 0.10 * cm

    c.setFont("Helvetica-Bold", 6.5)
    c.setFillColor(C_AZUL_OSC)
    c.drawString(bx + 0.45 * cm, ny, "EVOLUCIÓN / NOTAS DEL PROFESIONAL")

    ny -= 0.30 * cm

    if not notas:
        c.setFont("Helvetica-Oblique", 7.5)
        c.setFillColor(C_ITALIC)
        c.drawString(bx + 0.45 * cm, ny,
                     "El profesional no realizó ninguna anotación de esta sesión.")
    else:
        c.setFont("Helvetica", 7.8)
        c.setFillColor(C_TEXTO)
        _wrap_text(c, notas, bx + 0.45 * cm, ny,
                   bw - 0.85 * cm, "Helvetica", 7.8, 0.38 * cm)

    return ch


# ─────────────────────────────────────────────────────────────
# PLANIFICADOR DE PÁGINAS
# ─────────────────────────────────────────────────────────────
def _planificar(sesiones_list):
    """
    Divide las sesiones (ya ordenadas prof→serv→fecha) en páginas,
    insertando separadores de profesional y servicio donde corresponde.

    Retorna lista de páginas; cada página es lista de items:
      {'tipo': 'sep_prof',  'prof': ..., 'total': ...}
      {'tipo': 'sep_serv',  'serv': ..., 'total': ...}
      {'tipo': 'sesion',    'sesion': ...}
    """
    pages = []
    current_page = []
    used = 0.0

    last_prof_id = None
    last_serv_id = None

    def _new_page():
        nonlocal current_page, used
        if current_page:
            pages.append(current_page)
        current_page = []
        used = 0.0

    # La primera página tiene la banda informativa, ocupa más espacio del encabezado
    INFO_H_P1 = INFO_H * 1.4
    USABLE_H_P1 = USABLE_H - (INFO_H_P1 - INFO_H)  # menos espacio en pág 1

    def _fits(h):
        usable = USABLE_H_P1 if len(pages) == 0 else USABLE_H
        return used + h <= usable

    def _add(item, h):
        nonlocal used
        current_page.append(item)
        used += h

    # Pre-calcular totales por prof y por (prof, serv)
    from collections import defaultdict
    totales_prof = defaultdict(int)
    totales_serv = defaultdict(int)
    for s in sesiones_list:
        totales_prof[s.profesional_id] += 1
        totales_serv[(s.profesional_id, s.servicio_id)] += 1

    for sesion in sesiones_list:
        pid = sesion.profesional_id
        sid = sesion.servicio_id
        ch  = _card_h(sesion) + H_GAP

        need_prof = (pid != last_prof_id)
        need_serv = need_prof or (sid != last_serv_id)

        # Calcular cuánto necesitamos insertar antes de la tarjeta
        extra = 0.0
        if need_prof:
            extra += H_SEP_PROF + H_GAP
        if need_serv:
            extra += H_SEP_SERV + H_GAP

        # ¿Cabe todo junto en la página actual?
        if not _fits(extra + ch):
            _new_page()
            # Al saltar de página NO repetimos separadores si el prof/serv no cambió

        if need_prof:
            _add({'tipo': 'sep_prof',
                  'prof': sesion.profesional,
                  'total': totales_prof[pid]},
                 H_SEP_PROF + H_GAP)
            last_prof_id = pid
            last_serv_id = None   # forzar sep_serv tras nuevo prof

        need_serv = need_serv or (sid != last_serv_id)
        if need_serv:
            _add({'tipo': 'sep_serv',
                  'serv': sesion.servicio,
                  'total': totales_serv[(pid, sid)]},
                 H_SEP_SERV + H_GAP)
            last_serv_id = sid

        _add({'tipo': 'sesion', 'sesion': sesion}, ch)

    if current_page:
        pages.append(current_page)

    return pages if pages else [[]]


# ─────────────────────────────────────────────────────────────
# FUNCIÓN PRINCIPAL
# ─────────────────────────────────────────────────────────────
def generar_informe_evolucion_pdf(paciente, sesiones,
                                   profesional_nombre, servicio_nombre,
                                   fecha_desde, fecha_hasta, estados_filtro):
    from datetime import date as _date

    buffer = BytesIO()
    sesiones_list = list(sesiones)

    pages = _planificar(sesiones_list)
    total_pages = max(len(pages), 1)

    c = pdf_canvas.Canvas(buffer, pagesize=letter)
    c.setTitle(f"Informe Evolución - {paciente}")

    fecha_emision = _date.today().strftime("%d/%m/%Y")

    for pg_idx, page_items in enumerate(pages, start=1):
        # Fondo de página
        c.setFillColor(C_FONDO_PAG)
        c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)

        # Encabezado
        y = _encabezado(c, paciente, profesional_nombre, servicio_nombre,
                        fecha_desde, fecha_hasta, estados_filtro,
                        pg_idx, total_pages)

        # Dibujar items
        for item in page_items:
            if item['tipo'] == 'sep_prof':
                prof = item['prof']
                nombre = f"{prof.nombre} {prof.apellido}"
                h = _sep_profesional(c, y, nombre, item['total'])
                y -= h + H_GAP

            elif item['tipo'] == 'sep_serv':
                serv = item['serv']
                h = _sep_servicio(c, y, serv.nombre, item['total'])
                y -= h + H_GAP

            elif item['tipo'] == 'sesion':
                h = _tarjeta(c, item['sesion'], y)
                y -= h + H_GAP

        # Si página vacía (sin sesiones)
        if not page_items:
            c.setFont("Helvetica-Oblique", 11)
            c.setFillColor(C_GRIS_MED)
            c.drawCentredString(PAGE_W / 2, PAGE_H / 2,
                                "No se encontraron sesiones con los filtros seleccionados.")

        _pie(c, pg_idx, total_pages, fecha_emision)

        if pg_idx < total_pages:
            c.showPage()

    c.save()
    buffer.seek(0)
    return buffer