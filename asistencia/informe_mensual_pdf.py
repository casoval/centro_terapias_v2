"""
PDF del informe mensual de asistencia: UNA HOJA por profesional (foto, nombre, sucursal, evaluación del mes
con estrellas de puntualidad y semáforo de asistencia —con el motivo de cada una—, y día por día: retraso,
faltas, permisos y descuento en días). Cuando incluye a varios profesionales (sucursal o global) se antepone
una hoja de resumen del centro. No contiene montos de pago.

Mismo estilo que los demás informes (ReportLab, encabezado azul con logo, tipografía Helvetica).
"""
import logging
import math
import os
from datetime import date, timedelta
from io import BytesIO

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import cm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.lib import colors

from facturacion.informe_paciente_pdf import (
    C_AMBER, C_BLANCO, C_FONDO, C_FONDO_PAG, C_GRIS_B, C_GRIS_H, C_GRIS_T, C_MED, C_MUTED, C_OSC,
    C_PRI, C_ROJO, C_ROJO_L, C_TEXTO, C_TSEC, C_VERDE, C_VERDE_L, DIRECCION, NOMBRE_CENTRO,
    TELEFONO, _grad, _logo,
)
from facturacion.informe_profesional_pdf import _foto_path, _recorta, _t

from .informe_mensual import fmt_dias, fmt_horas
from .services import fmt_min_seg

logger = logging.getLogger(__name__)

PW, PH = letter
ML = 1.4 * cm
CW = PW - 2 * ML
HEADER_H = 1.9 * cm
FOOT_Y = 1.1 * cm
C_FALTA_BG = colors.HexColor('#fecaca')       # rojo más fuerte que C_ROJO_L (falta vs. retraso)
C_TOLERANCIA_BG = colors.HexColor('#ecfccb')  # verde-amarillo suave: llegó tarde pero dentro de la tolerancia
C_PERMISO_BG = colors.HexColor('#fef9c3')     # amarillo suave: falta con permiso
GRIS_ESTRELLA = colors.HexColor('#d1d5db')

# Columnas de la tabla diaria (pt, se escalan al ancho útil)
COLS = [('Día', 40), ('Horario del día', 106), ('Marcaciones', 138), ('Estado', 92),
        ('Retraso', 34), ('Acum.', 36), ('Falta', 32), ('Desc. acum.', 44)]
_ESCALA = CW / sum(w for _, w in COLS)


def _plural_dias(valor):
    return 'día' if round(float(valor), 2) == 1 else 'días'


def _hex(valor):
    return colors.HexColor(valor)


def _envolver(texto, fuente, tam, ancho, max_lineas):
    """Parte `texto` en líneas que caben en `ancho`; si sobra, la última termina en «...»."""
    palabras, lineas, actual = _t(texto).split(), [], ''
    for p in palabras:
        prueba = (actual + ' ' + p).strip()
        if stringWidth(prueba, fuente, tam) <= ancho:
            actual = prueba
        else:
            lineas.append(actual)
            actual = p
    if actual:
        lineas.append(actual)
    if len(lineas) > max_lineas:
        lineas = lineas[:max_lineas]
        while lineas[-1] and stringWidth(lineas[-1] + '...', fuente, tam) > ancho:
            lineas[-1] = lineas[-1][:-1]
        lineas[-1] = lineas[-1].rstrip() + '...'
    return lineas


# ──────────────────────────────────────────────────────────────────────────────
# Dibujo de estrellas y semáforo
# ──────────────────────────────────────────────────────────────────────────────

def _estrella(c, cx, cy, r, color, fraccion):
    """Estrella de 5 puntas gris con `fraccion` (0, 0.5, 1) rellena del color."""
    pts = []
    for i in range(10):
        ang = math.pi / 2 + i * math.pi / 5
        rad = r if i % 2 == 0 else r * 0.42
        pts.append((cx + rad * math.cos(ang), cy + rad * math.sin(ang)))

    def trazo():
        p = c.beginPath()
        p.moveTo(*pts[0])
        for q in pts[1:]:
            p.lineTo(*q)
        p.close()
        return p

    c.setFillColor(GRIS_ESTRELLA)
    c.drawPath(trazo(), fill=1, stroke=0)
    if fraccion > 0:
        c.saveState()
        recorte = c.beginPath()
        recorte.rect(cx - r, cy - r, 2 * r * fraccion, 2 * r)
        c.clipPath(recorte, stroke=0, fill=0)
        c.setFillColor(color)
        c.drawPath(trazo(), fill=1, stroke=0)
        c.restoreState()


def _dibujar_estrellas(c, x, y, ev, r=7.5):
    """5 estrellas (con media estrella) que empiezan en x; devuelve el x donde terminan."""
    llenas = int(ev['estrellas'])
    media = (ev['estrellas'] - llenas) >= 0.5
    color = _hex(ev['color'])
    for i in range(5):
        fr = 1.0 if i < llenas else (0.5 if (i == llenas and media) else 0.0)
        _estrella(c, x + r + i * (2 * r + 2), y, r, color, fr)
    return x + 5 * (2 * r + 2)


def _dibujar_semaforo(c, x, y, ev, r=6):
    """Tres luces (rojo, amarillo, verde): solo la del nivel actual enciende."""
    luces = [('rojo', '#dc2626'), ('amarillo', '#eab308'), ('verde', '#16a34a')]
    for i, (nombre, col) in enumerate(luces):
        c.setFillColor(_hex(col) if nombre == ev['nivel'] else GRIS_ESTRELLA)
        c.circle(x + r + i * (2 * r + 3), y, r, fill=1, stroke=0)
    return x + 3 * (2 * r + 3)


# ──────────────────────────────────────────────────────────────────────────────
# Página: encabezado y pie
# ──────────────────────────────────────────────────────────────────────────────

def _fondo(c):
    c.setFillColor(C_FONDO_PAG)
    c.rect(0, 0, PW, PH, fill=1, stroke=0)


def _encabezado(c, pg, total, periodo, titulo='INFORME MENSUAL DE ASISTENCIA'):
    _grad(c, 0, PH - HEADER_H, PW, HEADER_H, C_OSC, C_PRI)
    lh = HEADER_H - 0.5 * cm
    lp = _logo()
    if lp:
        try:
            c.drawImage(lp, ML, PH - HEADER_H + 0.25 * cm, width=lh, height=lh,
                        preserveAspectRatio=True, mask='auto')
        except Exception:
            pass
    tx = ML + lh + 0.4 * cm
    c.setFillColor(C_BLANCO)
    c.setFont('Helvetica-Bold', 11)
    c.drawString(tx, PH - 0.85 * cm, _t(NOMBRE_CENTRO))
    c.setFont('Helvetica', 7)
    c.drawString(tx, PH - 1.3 * cm, _t(f"{DIRECCION}  |  {TELEFONO}"))
    c.setFont('Helvetica-Bold', 8.5)
    c.drawRightString(PW - ML, PH - 0.8 * cm, _t(titulo))
    c.setFont('Helvetica', 7.5)
    c.drawRightString(PW - ML, PH - 1.2 * cm, _t(periodo))
    c.setFont('Helvetica', 7)
    c.drawRightString(PW - ML, PH - 1.58 * cm, f"Pág. {pg} de {total}")


def _pie(c, pg, total, emitido):
    c.setStrokeColor(C_GRIS_B)
    c.setLineWidth(0.4)
    c.line(ML, FOOT_Y + 0.45 * cm, PW - ML, FOOT_Y + 0.45 * cm)
    c.setFont('Helvetica', 6.5)
    c.setFillColor(C_MUTED)
    c.drawString(ML, FOOT_Y + 0.12 * cm,
                 _t(f"{NOMBRE_CENTRO}  |  Informe mensual de asistencia - emitido {emitido}  |  "
                    "No incluye montos de pago  |  CONFIDENCIAL"))
    c.drawRightString(PW - ML, FOOT_Y + 0.12 * cm, f"Pág. {pg} / {total}")


# ──────────────────────────────────────────────────────────────────────────────
# Hoja de un profesional
# ──────────────────────────────────────────────────────────────────────────────

def _foto_o_iniciales(c, x, y, size, inf, foto_path):
    if foto_path:
        try:
            c.drawImage(foto_path, x, y, width=size, height=size, preserveAspectRatio=True, mask='auto')
            c.setStrokeColor(C_GRIS_B)
            c.setLineWidth(0.8)
            c.rect(x, y, size, size, fill=0, stroke=1)
            return
        except Exception:
            logger.warning('No se pudo dibujar la foto de %s', inf.nombre)
    c.setFillColor(C_FONDO)
    c.roundRect(x, y, size, size, 6, fill=1, stroke=0)
    c.setFillColor(C_PRI)
    c.setFont('Helvetica-Bold', size * 0.38)
    ini = (inf.profesional.nombre[:1] + inf.profesional.apellido[:1]).upper()
    c.drawCentredString(x + size / 2, y + size * 0.34, _t(ini))


def _caja_metrica(c, x, y, w, h, etiqueta, valor, sub='', color=C_TEXTO, fondo=C_BLANCO):
    c.setFillColor(fondo)
    c.roundRect(x, y, w, h, 4, fill=1, stroke=0)
    c.setStrokeColor(C_GRIS_B)
    c.setLineWidth(0.4)
    c.roundRect(x, y, w, h, 4, fill=0, stroke=1)
    c.setFont('Helvetica-Bold', 6)
    c.setFillColor(C_MUTED)
    c.drawCentredString(x + w / 2, y + h - 0.38 * cm, _t(etiqueta.upper()))
    c.setFont('Helvetica-Bold', 11)
    c.setFillColor(color)
    c.drawCentredString(x + w / 2, y + h / 2 - 0.12 * cm, _recorta(valor, 11, w - 6, 'Helvetica-Bold'))
    if sub:
        c.setFont('Helvetica', 6)
        c.setFillColor(C_MUTED)
        c.drawCentredString(x + w / 2, y + 0.2 * cm, _recorta(sub, 6, w - 6))


def _caja_evaluacion(c, x, y, w, h, titulo, ev, tipo):
    """Panel de evaluación: título, estrellas o semáforo con su etiqueta, y el motivo."""
    c.setFillColor(_hex(ev['fondo']) if ev else C_GRIS_T)
    c.roundRect(x, y, w, h, 5, fill=1, stroke=0)
    c.setStrokeColor(_hex(ev['color']) if ev else C_GRIS_B)
    c.setLineWidth(0.9)
    c.roundRect(x, y, w, h, 5, fill=0, stroke=1)
    c.setFillColor(C_MUTED)
    c.setFont('Helvetica-Bold', 6.3)
    c.drawString(x + 0.3 * cm, y + h - 0.42 * cm, _t(titulo.upper()))
    if not ev:
        c.setFont('Helvetica', 7.5)
        c.drawString(x + 0.3 * cm, y + h / 2 - 0.1 * cm, 'Sin datos para evaluar este mes.')
        return
    cy = y + h - 0.98 * cm
    fin = (_dibujar_estrellas(c, x + 0.3 * cm, cy, ev) if tipo == 'estrellas'
           else _dibujar_semaforo(c, x + 0.3 * cm, cy, ev))
    c.setFillColor(_hex(ev['color']))
    c.setFont('Helvetica-Bold', 10)
    c.drawString(fin + 0.3 * cm, cy - 3.5, _t(ev['etiqueta']))
    if tipo == 'estrellas':
        c.setFont('Helvetica', 7)
        c.setFillColor(C_TSEC)
        n = ev['estrellas']
        c.drawRightString(x + w - 0.3 * cm, cy - 3, f"{fmt_dias(n)} de 5")
    c.setFillColor(C_TEXTO)
    c.setFont('Helvetica', 6.6)
    for i, linea in enumerate(_envolver(ev['motivo'], 'Helvetica', 6.6, w - 0.6 * cm, 3)):
        c.drawString(x + 0.3 * cm, y + h - 1.55 * cm - i * 0.27 * cm, linea)


def _fila_estilo(dia):
    """(fondo, color_texto, negrita) según el estado del día."""
    e = dia.estado
    if e == 'falta':
        return C_FALTA_BG, C_ROJO, True
    if e == 'retraso':
        return C_ROJO_L, C_ROJO, False
    if e == 'permiso':
        return C_PERMISO_BG, colors.HexColor('#854d0e'), False
    if e == 'tolerancia':
        return C_TOLERANCIA_BG, colors.HexColor('#3f6212'), False
    if e == 'puntual':
        return C_BLANCO, C_TEXTO, False
    if e == 'pendiente':
        return C_FONDO, C_MED, False
    return C_GRIS_T, C_MUTED, False             # libre, sin horario, sin control, futuro


def _textos_fila(dia):
    marc = ' | '.join(f"{e}-{s or '?'}" for e, s, _r in dia.pares) if dia.pares else ''
    est = {
        'puntual': 'Puntual', 'tolerancia': 'En tolerancia', 'retraso': 'Retraso', 'falta': dia.falta_texto,
        'permiso': 'Permiso', 'libre': 'Libre', 'sin_horario': '-', 'pendiente': 'Por llegar',
        'sin_control': 'Sin control', 'futuro': '',
    }[dia.estado]
    horario = dia.horario or '-'
    if dia.horario == 'Libre' and dia.nota:
        horario = f"Libre ({dia.nota})"
    if dia.estado == 'sin_horario' and not dia.pares:
        marc = ''
    if dia.permiso_texto:                                    # «Permiso: Certificado médico»
        marc = f"{marc} | {dia.permiso_texto}" if marc else dia.permiso_texto
    elif dia.estado in ('puntual', 'tolerancia', 'retraso', 'falta') and not marc:
        marc = '-'
    ev = dia.evaluado
    return [
        f"{dia.fecha.day:02d} {dia.dia_abrev}",
        horario,
        marc,
        est,
        fmt_min_seg(dia.retraso_seg) if dia.retraso_seg else '',
        fmt_min_seg(dia.acum_seg) if ev and dia.acum_seg else '',
        fmt_dias(dia.falta_dias) if dia.falta_dias else '',
        fmt_dias(dia.descuento_acum) if ev and dia.descuento_acum else '',
    ]


def _tabla_dias(c, inf, y_top, y_bottom):
    n_filas = len(inf.dias) + 2                           # encabezado + días + total
    rh = max(10.5, min(15.5, (y_top - y_bottom) / n_filas))
    fs = 7 if rh >= 12 else 6.2
    xs, x = [], ML
    for _n, w in COLS:
        xs.append(x)
        x += w * _ESCALA
    anchos = [w * _ESCALA for _n, w in COLS]

    # encabezado
    y = y_top - rh
    c.setFillColor(C_PRI)
    c.roundRect(ML, y, CW, rh, 3, fill=1, stroke=0)
    c.setFillColor(C_BLANCO)
    c.setFont('Helvetica-Bold', fs)
    for (nombre, _w), x0, w in zip(COLS, xs, anchos):
        if nombre in ('Retraso', 'Acum.', 'Falta', 'Desc. acum.'):
            c.drawCentredString(x0 + w / 2, y + rh / 2 - fs * 0.33, _t(nombre))
        else:
            c.drawString(x0 + 3, y + rh / 2 - fs * 0.33, _t(nombre))

    for dia in inf.dias:
        y -= rh
        fondo, color, negrita = _fila_estilo(dia)
        c.setFillColor(fondo)
        c.rect(ML, y, CW, rh, fill=1, stroke=0)
        c.setStrokeColor(C_GRIS_H)
        c.setLineWidth(0.3)
        c.line(ML, y, ML + CW, y)
        textos = _textos_fila(dia)
        for i, (txt, x0, w) in enumerate(zip(textos, xs, anchos)):
            if not txt:
                continue
            fuente = 'Helvetica-Bold' if (negrita and i in (0, 3, 4, 6)) or i == 0 else 'Helvetica'
            col = color
            if i == 2 and dia.sin_salida:
                col = C_AMBER                              # entrada sin salida
            if i == 3 and dia.estado == 'puntual':
                col = C_VERDE
            if i in (4, 6):
                col, fuente = C_ROJO, 'Helvetica-Bold'
            c.setFillColor(col)
            c.setFont(fuente, fs)
            ty = y + rh / 2 - fs * 0.33
            if i in (4, 5, 6, 7):
                c.drawCentredString(x0 + w / 2, ty, _t(txt))
            else:
                c.drawString(x0 + 3, ty, _recorta(txt, fs, w - 5, fuente))

    # total
    y -= rh
    r = inf.resumen
    c.setFillColor(C_OSC)
    c.roundRect(ML, y, CW, rh, 3, fill=1, stroke=0)
    c.setFillColor(C_BLANCO)
    c.setFont('Helvetica-Bold', fs)
    ty = y + rh / 2 - fs * 0.33
    c.drawString(xs[0] + 3, ty, 'TOTAL DEL MES')
    c.drawCentredString(xs[4] + anchos[4] / 2, ty, fmt_min_seg(r['retraso_seg']))
    c.drawCentredString(xs[6] + anchos[6] / 2, ty, fmt_dias(r['desc_faltas']))
    c.drawCentredString(xs[7] + anchos[7] / 2, ty, fmt_dias(r['desc_total']))
    return y


def _leyenda(c, y):
    items = [(C_ROJO_L, 'Retraso'), (C_FALTA_BG, 'Falta'), (C_PERMISO_BG, 'Permiso'),
             (C_TOLERANCIA_BG, 'En tolerancia'), (C_GRIS_T, 'Libre / sin horario / sin control'),
             (C_FONDO, 'Por llegar')]
    x = ML
    c.setFont('Helvetica', 6.3)
    for color, texto in items:
        c.setFillColor(color)
        c.setStrokeColor(C_GRIS_B)
        c.setLineWidth(0.4)
        c.rect(x, y, 8, 8, fill=1, stroke=1)
        c.setFillColor(C_TSEC)
        c.drawString(x + 11, y + 1.6, _t(texto))
        x += 11 + stringWidth(_t(texto), 'Helvetica', 6.3) + 12
    c.setFillColor(C_AMBER)
    c.drawString(x, y + 1.6, _t('Amarillo oscuro: entrada sin salida (?)'))


def _hoja_profesional(c, inf, foto_path, pg, total, emitido, sucursal_filtro=None):
    _fondo(c)
    _encabezado(c, pg, total, inf.periodo)
    _pie(c, pg, total, emitido)
    r = inf.resumen

    # ── tarjeta del profesional ─────────────────────────────────────────────
    card_h = 2.7 * cm
    card_y = PH - HEADER_H - 0.4 * cm - card_h
    c.setFillColor(C_BLANCO)
    c.roundRect(ML, card_y, CW, card_h, 6, fill=1, stroke=0)
    c.setStrokeColor(C_GRIS_B)
    c.setLineWidth(0.5)
    c.roundRect(ML, card_y, CW, card_h, 6, fill=0, stroke=1)
    fs = 2.2 * cm
    _foto_o_iniciales(c, ML + 0.25 * cm, card_y + (card_h - fs) / 2, fs, inf, foto_path)

    tx = ML + fs + 0.6 * cm
    box_w = 4.4 * cm
    max_w = CW - (tx - ML) - box_w - 0.8 * cm
    c.setFillColor(C_TEXTO)
    c.setFont('Helvetica-Bold', 13)
    c.drawString(tx, card_y + card_h - 0.8 * cm, _recorta(inf.nombre, 13, max_w, 'Helvetica-Bold'))
    c.setFont('Helvetica', 8.5)
    c.setFillColor(C_TSEC)
    c.drawString(tx, card_y + card_h - 1.25 * cm, _recorta(inf.profesional.especialidad or '', 8.5, max_w))
    suc = sucursal_filtro or (', '.join(inf.sucursales) if inf.sucursales else 'Sin sucursal asignada')
    c.setFont('Helvetica-Bold', 8)
    c.drawString(tx, card_y + card_h - 1.7 * cm, 'Sucursal:')
    c.setFont('Helvetica', 8)
    c.drawString(tx + 1.45 * cm, card_y + card_h - 1.7 * cm, _recorta(suc, 8, max_w - 1.45 * cm))
    ultimo = date(inf.anio, inf.mes, 28)
    while (ultimo + timedelta(days=1)).month == inf.mes:
        ultimo += timedelta(days=1)
    c.setFont('Helvetica-Bold', 8)
    c.drawString(tx, card_y + card_h - 2.1 * cm, 'Período:')
    c.setFont('Helvetica', 8)
    c.drawString(tx + 1.45 * cm, card_y + card_h - 2.1 * cm,
                 f"01/{inf.mes:02d}/{inf.anio} al {ultimo:%d/%m/%Y}")

    # caja de descuento total (el dato principal)
    bx = ML + CW - box_w - 0.3 * cm
    by = card_y + 0.3 * cm
    bh = card_h - 0.6 * cm
    hay = r['desc_total'] > 0
    c.setFillColor(C_ROJO_L if hay else C_VERDE_L)
    c.roundRect(bx, by, box_w, bh, 5, fill=1, stroke=0)
    c.setStrokeColor(C_ROJO if hay else C_VERDE)
    c.setLineWidth(0.8)
    c.roundRect(bx, by, box_w, bh, 5, fill=0, stroke=1)
    c.setFillColor(C_ROJO if hay else C_VERDE)
    c.setFont('Helvetica-Bold', 6.5)
    c.drawCentredString(bx + box_w / 2, by + bh - 0.45 * cm, 'DESCUENTO TOTAL DEL MES')
    c.setFont('Helvetica-Bold', 19 if hay else 14)
    valor = f"{fmt_dias(r['desc_total'])} {_plural_dias(r['desc_total'])}" if hay else 'Sin descuento'
    c.drawCentredString(bx + box_w / 2, by + bh / 2 - 0.25 * cm, _t(valor))
    c.setFont('Helvetica', 6.3)
    c.setFillColor(C_TSEC)
    c.drawCentredString(bx + box_w / 2, by + 0.3 * cm,
                        _t(f"retraso {fmt_dias(r['desc_retraso'])} + faltas {fmt_dias(r['desc_faltas'])}"))

    # ── métricas ────────────────────────────────────────────────────────────
    y = card_y - 0.3 * cm
    mh = 1.35 * cm
    gap = 0.18 * cm
    n = 6
    mw = (CW - gap * (n - 1)) / n
    y -= mh
    metricas = [
        ('Días con horario', str(r['dias_con_horario']), f"{r['dias_completos']} con asistencia completa", C_TEXTO),
        ('Tardanzas', str(r['tardanzas']), f"{r['usos_tolerancia']} en tolerancia", C_ROJO if r['tardanzas'] else C_TEXTO),
        ('Retraso acumulado', r['retraso_txt'], f"descuento: {fmt_dias(r['desc_retraso'])} {_plural_dias(r['desc_retraso'])}",
         C_ROJO if r['retraso_seg'] else C_TEXTO),
        ('Faltas', f"{fmt_dias(r['desc_faltas'])} {_plural_dias(r['desc_faltas'])}",
         f"{r['faltas_completas']} compl. · {r['faltas_medias']} medio(s) · {fmt_dias(r['faltas_justificadas'])} c/permiso",
         C_ROJO if r['desc_faltas'] else C_TEXTO),
        ('Horas trabajadas', fmt_horas(r['trabajado_min']), f"de {fmt_horas(r['esperado_min'])} esperadas", C_TEXTO),
        ('Entrada sin salida', str(r['sin_salida']), 'días a revisar', C_AMBER if r['sin_salida'] else C_TEXTO),
    ]
    for i, (et, val, sub, col) in enumerate(metricas):
        _caja_metrica(c, ML + i * (mw + gap), y, mw, mh, et, val, sub, col)

    # ── evaluación del mes: estrellas + semáforo, cada una con su motivo ─────
    y -= 0.3 * cm
    eh = 2.0 * cm
    y -= eh
    ew = (CW - 0.25 * cm) / 2
    _caja_evaluacion(c, ML, y, ew, eh, 'Evaluación de puntualidad', r['puntualidad'], 'estrellas')
    _caja_evaluacion(c, ML + ew + 0.25 * cm, y, ew, eh, 'Evaluación de asistencia', r['asistencia'], 'semaforo')

    # ── detalle del descuento ───────────────────────────────────────────────
    y -= 0.2 * cm
    notas = [
        f"Retraso: {r['retraso_txt']} min acumulados (solo lo que pasa de la tolerancia) = "
        f"{fmt_dias(r['desc_retraso'])} {_plural_dias(r['desc_retraso'])} de descuento.",
        f"Regla del mes: {inf.texto_regla}.",
        f"Faltas sin justificar: {r['faltas_completas']} día(s) completo(s) y {r['faltas_medias']} medio(s) = "
        f"{fmt_dias(r['desc_faltas'])} {_plural_dias(r['desc_faltas'])} de descuento. "
        f"Con permiso (sin descuento): {fmt_dias(r['faltas_justificadas'])} {_plural_dias(r['faltas_justificadas'])}.",
    ]
    if inf.control_desde is None:
        notas.append('Este profesional aún no tiene control de asistencia (sin enrolar ni marcaciones): no se calcularon faltas.')
    elif inf.control_desde > date(inf.anio, inf.mes, 1):
        notas.append(f"Control de asistencia desde el {inf.control_desde:%d/%m/%Y}: los días anteriores no generan faltas.")
    notas.append('Este informe no incluye montos de pago; el descuento se expresa en días y lo aplica el administrador.')
    c.setFont('Helvetica', 6.6)
    for i, t in enumerate(notas):
        c.setFillColor(C_TEXTO if i < 3 else C_MUTED)
        c.drawString(ML + 0.1 * cm, y - 0.25 * cm - i * 0.33 * cm, _recorta(t, 6.6, CW - 0.2 * cm))
    y -= 0.25 * cm + len(notas) * 0.33 * cm + 0.05 * cm

    # ── tabla y leyenda ─────────────────────────────────────────────────────
    y_leyenda = FOOT_Y + 0.75 * cm
    _tabla_dias(c, inf, y, y_leyenda + 0.5 * cm)
    _leyenda(c, y_leyenda)


# ──────────────────────────────────────────────────────────────────────────────
# Hoja(s) de resumen del centro (sucursal / global)
# ──────────────────────────────────────────────────────────────────────────────

RES_COLS = [('Profesional', 138), ('Sucursal', 70), ('Días', 32), ('Retraso', 44),
            ('Faltas', 36), ('Puntualidad', 90), ('Asistencia', 66), ('DESC. TOTAL', 52)]
RES_FILA_H = 0.62 * cm
RES_LINEA_H = 0.27 * cm
RES_MOTIVO_W = None


def _motivos_resumen(inf):
    """Líneas de motivo (puntualidad y asistencia) de un profesional para la hoja de resumen."""
    r = inf.resumen
    ancho = CW - 0.5 * cm
    lineas = []
    if r['puntualidad']:
        lineas += [('P', t) for t in _envolver('Puntualidad: ' + r['puntualidad']['motivo'], 'Helvetica', 6, ancho, 2)]
    if r['asistencia']:
        lineas += [('A', t) for t in _envolver('Asistencia: ' + r['asistencia']['motivo'], 'Helvetica', 6, ancho, 2)]
    return lineas


def _paginar_resumen(informes):
    """Agrupa profesionales por hoja según la altura que ocupa cada fila (datos + motivos)."""
    disponible = PH - HEADER_H - 0.8 * cm - 0.95 * cm - RES_FILA_H - FOOT_Y - 1.4 * cm - 0.9 * cm
    grupos, actual, usado = [], [], 0
    for inf in informes:
        alto = RES_FILA_H + len(_motivos_resumen(inf)) * RES_LINEA_H + 0.12 * cm
        if actual and usado + alto > disponible:
            grupos.append(actual)
            actual, usado = [], 0
        actual.append(inf)
        usado += alto
    if actual:
        grupos.append(actual)
    return grupos


def _hojas_resumen(c, grupos, alcance, periodo, pg0, total, emitido, total_informes, total_desc):
    escala = CW / sum(w for _n, w in RES_COLS)
    anchos = [w * escala for _n, w in RES_COLS]
    xs = [ML + sum(anchos[:i]) for i in range(len(anchos))]
    pg = pg0
    for k, grupo in enumerate(grupos):
        if k:
            c.showPage()
        _fondo(c)
        _encabezado(c, pg, total, periodo, 'RESUMEN DE ASISTENCIA')
        _pie(c, pg, total, emitido)
        y = PH - HEADER_H - 0.8 * cm
        c.setFont('Helvetica-Bold', 11)
        c.setFillColor(C_PRI)
        c.drawString(ML, y, _recorta(f"Resumen mensual - {alcance}", 11, CW, 'Helvetica-Bold'))
        c.setFont('Helvetica', 7)
        c.setFillColor(C_MUTED)
        c.drawString(ML, y - 0.42 * cm,
                     _t('Días = días con horario · Retraso = acumulado del mes (min:seg) · Faltas = días de descuento por faltas · '
                        'DESC. TOTAL = retraso + faltas, en días. Sin montos de pago.'))
        y -= 0.95 * cm
        rh = RES_FILA_H
        c.setFillColor(C_PRI)
        c.roundRect(ML, y - rh, CW, rh, 3, fill=1, stroke=0)
        c.setFillColor(C_BLANCO)
        c.setFont('Helvetica-Bold', 6.4)
        for i, ((nombre, _w), x0, w) in enumerate(zip(RES_COLS, xs, anchos)):
            if i < 2 or i in (5, 6):
                c.drawString(x0 + 3, y - rh + 0.2 * cm, _t(nombre))
            else:
                c.drawCentredString(x0 + w / 2, y - rh + 0.2 * cm, _t(nombre))
        y -= rh
        for inf in grupo:
            r = inf.resumen
            motivos = _motivos_resumen(inf)
            alto = rh + len(motivos) * RES_LINEA_H + 0.12 * cm
            y -= alto
            hay = r['desc_total'] > 0
            c.setFillColor(C_ROJO_L if hay else C_BLANCO)
            c.rect(ML, y, CW, alto, fill=1, stroke=0)
            c.setStrokeColor(C_GRIS_H)
            c.setLineWidth(0.3)
            c.line(ML, y, ML + CW, y)
            ty = y + alto - rh + 0.2 * cm                       # línea de datos (arriba de la fila)
            suc = ', '.join(inf.sucursales) or '-'
            celdas = [inf.nombre, suc, str(r['dias_con_horario']), r['retraso_txt'],
                      fmt_dias(r['desc_faltas']), None, None, fmt_dias(r['desc_total'])]
            for i, (txt, x0, w) in enumerate(zip(celdas, xs, anchos)):
                if i == 5:
                    if r['puntualidad']:
                        fin = _dibujar_estrellas(c, x0 + 2, ty + 2.2, r['puntualidad'], r=4.2)
                        c.setFont('Helvetica-Bold', 5.8)
                        c.setFillColor(_hex(r['puntualidad']['color']))
                        c.drawString(fin + 3, ty, _t(r['puntualidad']['etiqueta'].split(' (')[0]))
                    else:
                        c.setFont('Helvetica', 6.5); c.setFillColor(C_MUTED); c.drawString(x0 + 3, ty, 'Sin datos')
                    continue
                if i == 6:
                    if r['asistencia']:
                        fin = _dibujar_semaforo(c, x0 + 2, ty + 2.2, r['asistencia'], r=3.6)
                        c.setFont('Helvetica-Bold', 6.5)
                        c.setFillColor(_hex(r['asistencia']['color']))
                        c.drawString(fin + 3, ty, _t(r['asistencia']['etiqueta']))
                    else:
                        c.setFont('Helvetica', 6.5); c.setFillColor(C_MUTED); c.drawString(x0 + 3, ty, 'Sin datos')
                    continue
                c.setFont('Helvetica-Bold' if i in (0, 7) else 'Helvetica', 7)
                c.setFillColor(C_ROJO if (i == 7 and hay) else C_TEXTO)
                if i < 2:
                    c.drawString(x0 + 3, ty, _recorta(txt, 7, w - 5, 'Helvetica-Bold' if i == 0 else 'Helvetica'))
                else:
                    c.drawCentredString(x0 + w / 2, ty, _t(txt))
            # motivos (por qué tiene esas estrellas y ese semáforo)
            for j, (tipo, texto) in enumerate(motivos):
                ev = r['puntualidad'] if tipo == 'P' else r['asistencia']
                c.setFont('Helvetica', 6)
                c.setFillColor(_hex(ev['color']) if ev else C_TSEC)
                c.drawString(ML + 0.25 * cm, ty - 0.33 * cm - j * RES_LINEA_H, texto)
        if k == len(grupos) - 1:
            y -= 0.5 * cm
            c.setFont('Helvetica-Bold', 8)
            c.setFillColor(C_TEXTO)
            c.drawString(ML, y, _t(f"{total_informes} profesional(es)  -  descuento total del grupo: "
                                   f"{fmt_dias(total_desc)} {_plural_dias(total_desc)}"))
        pg += 1
    return pg


# ──────────────────────────────────────────────────────────────────────────────
# Entrada pública
# ──────────────────────────────────────────────────────────────────────────────

def generar_informe_mensual_pdf(informes, alcance, sucursal_filtro=None, compress=True) -> bytes:
    """
    informes: lista de InformeMensual (informe_mensual.construir_informes_mensuales).
    alcance: texto para el resumen ("Global", "Sucursal: Central", ...).
    Con 2 o más profesionales se antepone la hoja de resumen. Devuelve los bytes del PDF.
    """
    from django.utils import timezone

    emitido = timezone.localtime().strftime('%d/%m/%Y %H:%M')
    buf = BytesIO()
    c = pdf_canvas.Canvas(buf, pagesize=letter, pageCompression=1 if compress else 0)
    c.setTitle(_t(f"Informe mensual de asistencia - {alcance}"))
    c.setAuthor(_t(NOMBRE_CENTRO))

    if not informes:
        _fondo(c)
        _encabezado(c, 1, 1, '')
        _pie(c, 1, 1, emitido)
        c.setFont('Helvetica', 11)
        c.setFillColor(C_MUTED)
        c.drawCentredString(PW / 2, PH / 2, 'No hay profesionales para el filtro seleccionado.')
        c.save()
        return buf.getvalue()

    periodo = informes[0].periodo
    con_resumen = len(informes) > 1
    grupos = _paginar_resumen(informes) if con_resumen else []
    total = len(grupos) + len(informes)

    pg = 1
    if con_resumen:
        total_desc = sum(i.resumen['desc_total'] for i in informes)
        pg = _hojas_resumen(c, grupos, alcance, periodo, 1, total, emitido, len(informes), total_desc)
        c.showPage()
    fotos = []
    try:
        for inf in informes:
            try:
                ruta, es_tmp = _foto_path(inf.profesional)
            except Exception:
                ruta, es_tmp = None, False
            if ruta and es_tmp:
                fotos.append(ruta)
            _hoja_profesional(c, inf, ruta, pg, total, emitido, sucursal_filtro)
            pg += 1
            if pg <= total:
                c.showPage()
        c.save()
    finally:
        for ruta in fotos:
            try:
                os.unlink(ruta)
            except OSError:
                pass
    return buf.getvalue()
