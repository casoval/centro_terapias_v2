# agenda/informe_horario_pdf.py
# =====================================================
# GENERADOR DE PDF - HORARIO IMPRIMIBLE (Semanal / Mensual)
# Hoja Carta horizontal (landscape)
#
# 3 formatos según los filtros aplicados en la Agenda:
# 3 formatos según los filtros aplicados en la Agenda:
#   - 'profesional': filtrado solo por Profesional -> se repite Paciente
#     (+ Servicio/Sucursal si hay más de uno en el resultado). Color de
#     fondo del chip por Paciente.
#   - 'paciente':    filtrado solo por Paciente     -> se repite Servicio
#     (no el profesional, con el servicio alcanza) + Sucursal si hay más
#     de una en el resultado. Color de fondo del chip por Servicio.
#   - 'completo':    cualquier otra combinación de filtros -> se muestran
#     todos los datos (Profesional, Paciente, Servicio, Sucursal) en cada fila
#
# Pensado para entregarse en papel a pacientes/profesionales sin acceso
# al sistema, por eso se omiten datos que no aportan (estado interno,
# notas, pagos, etc.) y solo se ve lo esencial: hora, con quién y qué
# servicio.
# =====================================================

import os
from io import BytesIO
from collections import defaultdict
from datetime import timedelta

from django.conf import settings

from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
)
from reportlab.pdfgen import canvas as pdf_canvas


# ─────────────────────────────────────────────────────────────
# DATOS DEL CENTRO (mismo patrón que los demás informes del sistema)
# ─────────────────────────────────────────────────────────────
NOMBRE_CENTRO = "Centro de Neurodesarrollo Infantil Misael"

SUCURSALES_CENTRO = [
    {
        'nombre': 'Sede Principal',
        'direccion': 'Calle Japón #28 entre Daza y Calderón, a lado de la EPI-10 · Zona Baja',
        'telefono': '76175352',
    },
    {
        'nombre': 'Sucursal 1',
        'direccion': 'Calle Cochabamba a lado de ENTEL, casi esq. Bolívar · Zona Central',
        'telefono': '78633975',
    },
]

C_AZUL_OSC   = colors.HexColor('#1565C0')
C_AZUL_PRI   = colors.HexColor('#1E88E5')
C_AZUL_FONDO = colors.HexColor('#EEF4FF')
C_GRIS_BORDE = colors.HexColor('#CBD5E1')
C_TEXTO      = colors.HexColor('#212121')
C_TEXTO_SEC  = colors.HexColor('#555555')

DIAS_SEMANA = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
MESES = ['', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
         'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']

PAGE_W, PAGE_H = landscape(letter)
MARGIN_L = 1.3 * cm
MARGIN_R = 1.3 * cm
HEADER_H = 3.15 * cm  # alto del encabezado de marca (logo + nombre + 2 sucursales)
MARGIN_T = HEADER_H + 0.65 * cm   # deja espacio para el encabezado dibujado por página
MARGIN_B = 1.2 * cm
CONTENT_W = PAGE_W - MARGIN_L - MARGIN_R


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


def _grad(c, x, y, w, h, c1, c2, steps=24):
    """Franja con degradado horizontal simple (igual estilo que otros informes)."""
    c.saveState()
    for i in range(steps):
        t = i / float(steps - 1)
        r = c1.red   + (c2.red   - c1.red)   * t
        g = c1.green + (c2.green - c1.green) * t
        b = c1.blue  + (c2.blue  - c1.blue)  * t
        c.setFillColorRGB(r, g, b)
        c.rect(x + w * i / steps, y, w / steps + 1, h, stroke=0, fill=1)
    c.restoreState()


# ─────────────────────────────────────────────────────────────
# NUMERACIÓN "Página X de Y" (patrón estándar de reportlab)
# ─────────────────────────────────────────────────────────────
class _CanvasConTotalPaginas(pdf_canvas.Canvas):
    def __init__(self, *args, **kwargs):
        pdf_canvas.Canvas.__init__(self, *args, **kwargs)
        self._paginas_guardadas = []

    def showPage(self):
        self._paginas_guardadas.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._paginas_guardadas)
        for estado in self._paginas_guardadas:
            self.__dict__.update(estado)
            self._draw_numero_pagina(total)
            pdf_canvas.Canvas.showPage(self)
        pdf_canvas.Canvas.save(self)

    def _draw_numero_pagina(self, total):
        self.setFont('Helvetica', 7.5)
        self.setFillColor(C_TEXTO_SEC)
        self.drawRightString(
            PAGE_W - MARGIN_R, PAGE_H - MARGIN_T + 0.35 * cm,
            f"Página {self._pageNumber} de {total}"
        )


# ─────────────────────────────────────────────────────────────
# COLOR POR VALOR (paleta pastel estable: mismo nombre -> mismo color
# siempre, sin necesidad de una pasada previa por todas las sesiones)
# ─────────────────────────────────────────────────────────────
PALETA_CHIPS = [
    colors.HexColor('#FFE1E1'), colors.HexColor('#E1EFFF'), colors.HexColor('#E1FFE4'),
    colors.HexColor('#FFF2D0'), colors.HexColor('#F0E1FF'), colors.HexColor('#D9FFF3'),
    colors.HexColor('#FFE1F0'), colors.HexColor('#EDE9DD'), colors.HexColor('#E3E1FF'),
    colors.HexColor('#FFFAD0'), colors.HexColor('#D9F5FF'), colors.HexColor('#EBFFD9'),
]


def _color_por_valor(nombre):
    if not nombre:
        return colors.whitesmoke
    h = sum(ord(c) for c in nombre)
    return PALETA_CHIPS[h % len(PALETA_CHIPS)]


# Cuántas sesiones caben en una "banda" antes de continuar en una fila física
# nueva (así, si un día tiene muchísimas sesiones, la fila sigue creciendo y
# puede pasar a la siguiente hoja igual que el resto de la tabla, en vez de
# intentar meter todo en una sola fila gigante que reportlab no puede partir).
SESIONES_POR_BANDA = 6


# ─────────────────────────────────────────────────────────────
# CHIP DE SESIÓN (pastilla de color dentro de cada celda del día)
# ─────────────────────────────────────────────────────────────
def _chip_sesion(sesion, formato, servicio_unico, sucursal_unica, fuente_base):
    hora = f"{sesion.hora_inicio.strftime('%H:%M')}-{sesion.hora_fin.strftime('%H:%M')}"
    color_fondo = colors.white

    if formato == 'paciente':
        # El profesional ya no se muestra: con el servicio alcanza para
        # identificar la sesión. Color de fondo por servicio.
        texto = f"<b>{hora}</b> {sesion.servicio.nombre}"
        if not sucursal_unica:
            texto += f"<br/><font size='6' color='#555555'>{sesion.sucursal.nombre}</font>"
        color_fondo = _color_por_valor(sesion.servicio.nombre)

    elif formato == 'profesional':
        # Color de fondo por paciente.
        texto = f"<b>{hora}</b> {sesion.paciente.nombre_completo}"
        extra = []
        if not servicio_unico:
            extra.append(sesion.servicio.nombre)
        if not sucursal_unica:
            extra.append(sesion.sucursal.nombre)
        if extra:
            texto += f"<br/><font size='6' color='#555555'>{' · '.join(extra)}</font>"
        color_fondo = _color_por_valor(sesion.paciente.nombre_completo)

    else:  # completo (sin color especial: hay demasiadas variables en juego)
        texto = (
            f"<b>{hora}</b> {sesion.profesional.nombre_completo} → {sesion.paciente.nombre_completo}"
            f"<br/><font size='6' color='#555555'>{sesion.servicio.nombre} · {sesion.sucursal.nombre}</font>"
        )

    style = ParagraphStyle(
        f'chip_{id(sesion)}', parent=fuente_base,
        backColor=color_fondo, borderColor=C_GRIS_BORDE, borderWidth=0.4,
        borderPadding=3, borderRadius=2,
    )
    return Paragraph(texto, style)


# ─────────────────────────────────────────────────────────────
# GENERADOR PRINCIPAL
# ─────────────────────────────────────────────────────────────
def generar_horario_pdf(
    vista, fecha_inicio, fecha_fin, sesiones, formato,
    nombre_profesional=None, nombre_paciente=None,
    sucursal_unica=None, servicio_unico=None,
    mostrar_domingo=True,
):
    """
    vista: 'semanal' o 'mensual'
    fecha_inicio / fecha_fin: date, rango a mostrar
    sesiones: queryset/lista de Sesion ya filtradas (select_related recomendado)
    formato: 'profesional' | 'paciente' | 'completo'
    nombre_profesional / nombre_paciente: nombre a mostrar UNA sola vez en el
        encabezado cuando el formato es 'profesional' / 'paciente'
    sucursal_unica / servicio_unico: nombre (str) si el resultado filtrado
        solo contiene una sucursal/servicio (se muestra una vez arriba y se
        omite por celda); None si hay varias (se muestra por celda)
    mostrar_domingo: respeta el toggle de la vista semanal/mensual

    Diseño: grilla de calendario real (columnas = días desde Lunes, filas =
    semanas), igual que la vista en pantalla — no una lista apilada por día.
    """
    buffer = BytesIO()

    doc = SimpleDocTemplate(
        buffer, pagesize=landscape(letter),
        leftMargin=MARGIN_L, rightMargin=MARGIN_R,
        topMargin=MARGIN_T, bottomMargin=MARGIN_B,
        title=f"Horario {vista} - {NOMBRE_CENTRO}",
    )

    style_header_dia = ParagraphStyle(
        'header_dia', fontName='Helvetica-Bold', fontSize=9.5, leading=11,
        textColor=colors.white, alignment=1,
    )
    style_numero_dia = ParagraphStyle(
        'numero_dia', fontName='Helvetica-Bold', fontSize=9, leading=11,
        textColor=C_AZUL_OSC, spaceAfter=2,
    )
    style_chip_base = ParagraphStyle(
        'chip_base', fontName='Helvetica', fontSize=6.8, leading=9,
        textColor=C_TEXTO,
    )
    styles = getSampleStyleSheet()

    # ── Agrupar sesiones por fecha ──────────────────────────────────────
    por_fecha = defaultdict(list)
    for s in sesiones:
        por_fecha[s.fecha].append(s)
    for fecha in por_fecha:
        por_fecha[fecha].sort(key=lambda s: s.hora_inicio)

    # ── Columnas a mostrar (Lunes=0 ... Domingo=6) ───────────────────────
    indices_dias = list(range(6)) + ([6] if mostrar_domingo else [])
    n_cols = len(indices_dias)
    ancho_col = CONTENT_W / n_cols
    anchos = [ancho_col] * n_cols
    headers_dias = [DIAS_SEMANA[i] for i in indices_dias]

    # ── Armar semanas (listas de 7 fechas, Lunes a Domingo) ──────────────
    semanas = []
    if vista == 'mensual':
        cursor = fecha_inicio - timedelta(days=fecha_inicio.weekday())
        while cursor <= fecha_fin:
            semanas.append([cursor + timedelta(days=i) for i in range(7)])
            cursor += timedelta(days=7)
    else:
        semanas.append([fecha_inicio + timedelta(days=i) for i in range(7)])

    # ── Tabla única: header de días + N "bandas" físicas por semana ──────
    # Cada día se reparte en bandas de SESIONES_POR_BANDA sesiones. Si un
    # día tiene muchas sesiones, la semana simplemente ocupa más bandas
    # (más filas físicas), y como cada banda es una fila normal de la
    # tabla, reportlab puede partirla entre hojas sin problema — el día
    # "sigue creciendo" tal como se ve en pantalla, aunque entre en varias
    # hojas impresas.
    #
    # IMPORTANTE: no se fija `rowHeights` — reportlab NO lo trata como un
    # mínimo sino como un alto fijo, y si el contenido real es más alto
    # (varios chips apilados) el texto se recorta/superpone. Dejando que
    # reportlab calcule el alto de cada fila a partir del contenido, cada
    # fila crece exactamente lo necesario.
    data = [[Paragraph(h, style_header_dia) for h in headers_dias]]
    fondos_relleno = []   # (fila, col) de celdas fuera de mes -> gris

    for semana in semanas:
        # Para cada columna de esta semana: ¿es relleno? y sus bandas de sesiones
        columnas_info = []
        max_bandas = 1
        for i in indices_dias:
            fecha = semana[i]
            es_relleno = (vista == 'mensual' and (fecha < fecha_inicio or fecha > fecha_fin))
            sesiones_dia = [] if es_relleno else por_fecha.get(fecha, [])
            bandas = [sesiones_dia[j:j + SESIONES_POR_BANDA]
                      for j in range(0, len(sesiones_dia), SESIONES_POR_BANDA)] or [[]]
            columnas_info.append((fecha, es_relleno, bandas))
            max_bandas = max(max_bandas, len(bandas))

        for banda_idx in range(max_bandas):
            fila_idx = len(data)
            fila = []
            for col_idx, (fecha, es_relleno, bandas) in enumerate(columnas_info):
                if es_relleno:
                    fila.append('')
                    fondos_relleno.append((fila_idx, col_idx))
                    continue

                contenido = []
                if banda_idx == 0:
                    contenido.append(Paragraph(str(fecha.day), style_numero_dia))
                if banda_idx < len(bandas):
                    for s in bandas[banda_idx]:
                        if contenido:
                            contenido.append(Spacer(1, 2))
                        contenido.append(_chip_sesion(
                            s, formato, servicio_unico, sucursal_unica, style_chip_base
                        ))
                fila.append(contenido if contenido else '')
            data.append(fila)

    tabla = Table(data, colWidths=anchos, repeatRows=1)

    estilo = [
        ('BACKGROUND', (0, 0), (-1, 0), C_AZUL_OSC),
        ('GRID', (0, 0), (-1, -1), 0.6, C_GRIS_BORDE),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 3),
        ('TOPPADDING', (0, 0), (-1, 0), 5),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 5),
    ]
    # Pintar celdas de relleno (fuera de mes) de gris claro
    for fila_idx, col_idx in fondos_relleno:
        estilo.append(('BACKGROUND', (col_idx, fila_idx), (col_idx, fila_idx),
                        colors.HexColor('#F2F2F2')))
    tabla.setStyle(TableStyle(estilo))

    story = [tabla]

    # ── Encabezado de marca (se repite en cada página) ──────────────────
    titulo_vista = "HORARIO SEMANAL" if vista == 'semanal' else "HORARIO MENSUAL"
    if vista == 'mensual':
        subtitulo = f"{MESES[fecha_inicio.month]} {fecha_inicio.year}"
    else:
        subtitulo = (
            f"{fecha_inicio.day:02d}/{fecha_inicio.month:02d}/{fecha_inicio.year} — "
            f"{fecha_fin.day:02d}/{fecha_fin.month:02d}/{fecha_fin.year}"
        )

    # Línea de contexto (nombre fijo / sucursal-servicio únicos) según formato
    linea_contexto = None
    if formato == 'profesional' and nombre_profesional:
        partes = [f"Profesional: {nombre_profesional}"]
        if servicio_unico:
            partes.append(f"Servicio: {servicio_unico}")
        if sucursal_unica:
            partes.append(f"Sucursal: {sucursal_unica}")
        linea_contexto = "   •   ".join(partes)
    elif formato == 'paciente' and nombre_paciente:
        partes = [f"Paciente: {nombre_paciente}"]
        if servicio_unico:
            partes.append(f"Servicio: {servicio_unico}")
        if sucursal_unica:
            partes.append(f"Sucursal: {sucursal_unica}")
        linea_contexto = "   •   ".join(partes)

    def _draw_encabezado(c, _doc):
        _grad(c, 0, PAGE_H - HEADER_H, PAGE_W, HEADER_H, C_AZUL_OSC, C_AZUL_PRI)

        lp = _logo()
        lh = (HEADER_H - 0.5 * cm) / 2   # logo a la mitad del tamaño anterior
        lw = lh
        lx = MARGIN_L
        ly = PAGE_H - HEADER_H / 2 - lh / 2   # centrado verticalmente en la franja
        if lp:
            try:
                c.drawImage(lp, lx, ly, width=lw, height=lh,
                            preserveAspectRatio=True, mask='auto')
            except Exception:
                pass

        tx = lx + lw + 0.35 * cm
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 11.5)
        c.drawString(tx, PAGE_H - 0.75 * cm, NOMBRE_CENTRO)

        # Ambas sucursales, una línea cada una (nombre · dirección · teléfono)
        c.setFont("Helvetica", 6.9)
        y_suc = PAGE_H - 1.35 * cm
        for suc in SUCURSALES_CENTRO:
            c.drawString(
                tx, y_suc,
                f"{suc['nombre']} · {suc['direccion']}  ·  Tel. {suc['telefono']}"
            )
            y_suc -= 0.42 * cm

        c.setFont("Helvetica-Bold", 12)
        c.drawRightString(PAGE_W - MARGIN_R, PAGE_H - 0.75 * cm, titulo_vista)
        c.setFont("Helvetica", 8.5)
        c.drawRightString(PAGE_W - MARGIN_R, PAGE_H - 1.25 * cm, subtitulo)

        if linea_contexto:
            c.setFillColor(C_TEXTO)
            c.setFont("Helvetica-Bold", 9)
            c.drawString(MARGIN_L, PAGE_H - HEADER_H - 0.55 * cm, linea_contexto)

        c.setStrokeColor(C_GRIS_BORDE)
        c.setLineWidth(0.7)
        y_linea = PAGE_H - HEADER_H - (0.85 * cm if linea_contexto else 0.35 * cm)
        c.line(MARGIN_L, y_linea, PAGE_W - MARGIN_R, y_linea)

    doc.build(
        story,
        onFirstPage=_draw_encabezado,
        onLaterPages=_draw_encabezado,
        canvasmaker=_CanvasConTotalPaginas,
    )
    buffer.seek(0)
    return buffer
