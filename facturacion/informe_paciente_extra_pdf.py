# facturacion/informe_paciente_extra_pdf.py
# =====================================================================
# SECCIONES NUEVAS DEL PDF INTERNO DEL PACIENTE (capa «decisión»)
#   A. Decisión y riesgo           (después de la portada)
#   B. Cuenta corriente y cobranza (después del financiero)
#   C. Comportamiento y plan       (después de la evolución)
#   D. Servicios y seguimiento     (antes del detalle de sesiones)
# Usan las mismas primitivas, colores y paginación en dos pasadas que el resto
# del informe (informe_paciente_pdf). Si ctx['a'] no existe, no dibujan nada.
# =====================================================================
import logging

from reportlab.lib.units import cm
from reportlab.pdfbase.pdfmetrics import stringWidth

from .informe_paciente_pdf import (
    CW, ML, PAGE_W, Y_BOTTOM, C_AMBER, C_BLANCO, C_FONDO_PAG, C_GRIS_B, C_GRIS_H, C_GRIS_T, C_MED, C_MORADO, C_MUTED,
    C_PRI, C_ROJO, C_TEAL, C_TEXTO, C_TSEC, C_VERDE, _grilla, _pie, _tabla, _tabla_header, _titulo_seccion,
)
from .informe_profesional_pdf import fd, fm, pc as _pc
from reportlab.lib import colors

logger = logging.getLogger(__name__)
BS = lambda v, d=2: f"Bs. {fm(v, d)}"                                            # noqa: E731


def _hex(h):
    return colors.HexColor(h)


class _Pag:
    """Cursor de página: lleva el canvas, la posición y los saltos con pie de página."""

    def __init__(self, pages_data, helpers):
        self.pd, self.h = pages_data, helpers
        self.c = self.y = self.pg = None

    def nueva(self):
        if self.c is not None:
            _pie(self.c, self.pg, self.h['total_pg'][0], self.h['fecha'])
            self.pd.append(self.pg)
        self.c, self.y, self.pg = self.h['new_page']()
        return self

    def asegurar(self, alto):
        if self.y - alto < Y_BOTTOM:
            self.nueva()

    def cerrar(self):
        if self.c is not None:
            _pie(self.c, self.pg, self.h['total_pg'][0], self.h['fecha'])
            self.pd.append(self.pg)


def _lineas(texto, font, size, ancho):
    out, linea = [], ''
    for w in str(texto).split():
        t = (linea + ' ' + w).strip()
        if stringWidth(t, font, size) <= ancho:
            linea = t
        else:
            if linea:
                out.append(linea)
            linea = w
    if linea:
        out.append(linea)
    return out or ['']


def _parrafo(P, texto, size=7.6, color=C_TEXTO, font='Helvetica', lh=None, x=None, ancho=None, espacio=0.15 * cm):
    lh = lh or size * 1.4          # interlineado en puntos
    x = ML + 0.2 * cm if x is None else x
    ancho = (CW - 0.4 * cm) if ancho is None else ancho
    for ln in _lineas(texto, font, size, ancho):
        P.asegurar(lh + 0.1 * cm)
        P.c.setFont(font, size)
        P.c.setFillColor(color)
        P.c.drawString(x, P.y - lh + 0.12 * cm, ln)
        P.y -= lh
    P.y -= espacio


def _subtitulo(P, texto, color=C_PRI, reserva=2.6 * cm):
    P.asegurar(reserva)          # el subtítulo nunca queda solo al pie: reserva espacio para encabezado y 2 filas
    P.c.setFont('Helvetica-Bold', 8.6)
    P.c.setFillColor(color)
    P.c.drawString(ML + 0.1 * cm, P.y - 0.4 * cm, texto)
    P.c.setStrokeColor(C_GRIS_B)
    P.c.setLineWidth(0.4)
    P.c.line(ML, P.y - 0.55 * cm, ML + CW, P.y - 0.55 * cm)
    P.y -= 0.8 * cm


def _titulo(P, texto, color=None):
    P.asegurar(2.0 * cm)
    P.y = _titulo_seccion(P.c, P.y, texto, color=color)


def _grilla_p(P, items, cols=4, alto=1.65 * cm):
    filas = (len(items) + cols - 1) // cols
    for i in range(filas):
        P.asegurar(alto + 0.4 * cm)
        P.y = _grilla(P.c, P.y, items[i * cols:(i + 1) * cols], cols=cols, box_h=alto)


def _tabla_p(P, headers, rows, col_ws, fsize=7.2, row_h=0.46 * cm):
    """Tabla con salto de página: repite el encabezado en cada hoja."""
    if not rows:
        return
    i = 0
    while i < len(rows):
        P.asegurar(row_h * 3 + 0.5 * cm)
        cabe = max(int((P.y - Y_BOTTOM - row_h - 0.35 * cm) / row_h), 1)
        if len(rows) - i > cabe and len(rows) - i - cabe == 1 and cabe > 2:
            cabe -= 1                # evita dejar una sola fila huérfana en la página siguiente
        trozo = rows[i:i + cabe]
        P.y = _tabla(P.c, P.y, headers, trozo, col_ws, fsize=fsize, row_h=row_h)
        i += len(trozo)
        if i < len(rows):
            P.nueva()


def _barras(P, items, color_fn=None, ancho_lbl=5.0 * cm):
    """items: [(etiqueta, valor_0_100, texto_derecha, color)]"""
    c = P.c
    for lbl, v, txt, col in items:
        P.asegurar(0.62 * cm)
        c = P.c
        c.setFont('Helvetica', 7.3)
        c.setFillColor(C_TEXTO)
        c.drawString(ML + 0.2 * cm, P.y - 0.42 * cm, str(lbl)[:48])
        bx, bw = ML + ancho_lbl, CW - ancho_lbl - 4.6 * cm
        c.setFillColor(C_GRIS_H)
        c.roundRect(bx, P.y - 0.46 * cm, bw, 0.3 * cm, 2, fill=1, stroke=0)
        c.setFillColor(col or C_MED)
        c.roundRect(bx, P.y - 0.46 * cm, max(bw * min(max(v, 0), 100) / 100.0, 0.04 * cm), 0.3 * cm, 2, fill=1, stroke=0)
        c.setFont('Helvetica-Bold', 7.2)
        c.setFillColor(C_TSEC)
        c.drawString(bx + bw + 0.25 * cm, P.y - 0.43 * cm, txt)
        P.y -= 0.62 * cm
    P.y -= 0.1 * cm


def _hallazgos_p(P, hall):
    col = {'alerta': C_ROJO, 'ok': C_VERDE, 'nota': C_AMBER_, 'info': C_TSEC}
    for h in hall:
        _parrafo(P, '• ' + h['txt'], 7.6, col.get(h['tipo'], C_TSEC), 'Helvetica-Bold' if h['tipo'] == 'alerta' else 'Helvetica',
                 espacio=0.02 * cm)
        if h.get('accion'):
            _parrafo(P, '   → ' + h['accion'], 7.0, C_MUTED, 'Helvetica-Oblique', x=ML + 0.6 * cm, ancho=CW - 1.0 * cm, espacio=0.14 * cm)


C_AMBER_ = _hex('#d97706')


def _fila_criterio(P, crit):
    c_regla = _lineas(crit['regla'], 'Helvetica', 6.2, 5.6 * cm)
    c_det = _lineas(crit['detalle'], 'Helvetica', 6.8, 6.6 * cm)
    c_val = _lineas(crit['valor'], 'Helvetica-Bold', 7.6, 4.2 * cm)
    alto = max(len(c_regla) * 0.27 + 0.45, len(c_det) * 0.3 + 0.2, len(c_val) * 0.32 + 0.2, 0.8) * cm
    P.asegurar(alto + 0.1 * cm)
    c, y = P.c, P.y
    c.setFillColor(_hex(crit['color']))
    c.circle(ML + 0.35 * cm, y - 0.38 * cm, 0.17 * cm, fill=1, stroke=0)
    c.setFont('Helvetica-Bold', 7.8)
    c.setFillColor(C_TEXTO)
    c.drawString(ML + 0.8 * cm, y - 0.4 * cm, crit['nombre'][:38])
    c.setFont('Helvetica', 6.2)
    c.setFillColor(C_MUTED)
    yy = y - 0.4 * cm - 0.3 * cm
    for ln in c_regla:
        c.drawString(ML + 0.8 * cm, yy, ln)
        yy -= 0.27 * cm
    c.setFont('Helvetica-Bold', 7.6)
    c.setFillColor(_hex(crit['color']))
    yy = y - 0.4 * cm
    for ln in c_val:
        c.drawString(ML + 6.8 * cm, yy, ln)
        yy -= 0.32 * cm
    c.setFont('Helvetica', 6.8)
    c.setFillColor(C_TSEC)
    yy = y - 0.4 * cm
    for ln in c_det:
        c.drawString(ML + 11.2 * cm, yy, ln)
        yy -= 0.3 * cm
    c.setStrokeColor(C_GRIS_B)
    c.setLineWidth(0.25)
    c.line(ML, y - alto, ML + CW, y - alto)
    P.y -= alto + 0.05 * cm


def _veredicto(P, sm):
    P.asegurar(2.6 * cm)
    c = P.c
    c.setFillColor(_hex(sm['color']))
    c.roundRect(ML, P.y - 2.0 * cm, CW, 2.0 * cm, 8, fill=1, stroke=0)
    c.setFillColor(C_BLANCO)
    c.setFont('Helvetica-Bold', 26)
    c.drawString(ML + 0.6 * cm, P.y - 1.35 * cm, f"{sm['score']}/100" if sm['score'] is not None else '—')
    c.setFont('Helvetica-Bold', 8.4)
    c.drawString(ML + 4.2 * cm, P.y - 0.7 * cm, 'SEMÁFORO DE DECISIÓN')
    c.setFont('Helvetica', 8)
    yy = P.y - 1.15 * cm
    for ln in _lineas(sm['msg'], 'Helvetica', 8, CW - 4.8 * cm)[:2]:
        c.drawString(ML + 4.2 * cm, yy, ln)
        yy -= 0.38 * cm
    c.setFont('Helvetica', 6.8)
    c.drawString(ML + 4.2 * cm, P.y - 1.82 * cm, f"{sm['n_verde']} en verde · {sm['n_ambar']} en ámbar · {sm['n_rojo']} en rojo")
    P.y -= 2.0 * cm + 0.3 * cm


# ─────────────────────────────────────────────────────────────────────
# DEUDA TOTAL PROYECTADA (sin importar el período)
# ─────────────────────────────────────────────────────────────────────
def _caja_deuda(P, a, familia=False):
    dd = a['deuda']
    P.asegurar(3.4 * cm)
    c, y = P.c, P.y
    hay = dd['tiene_deuda']
    c.setFillColor(_hex('#b91c1c') if hay else _hex('#15803d'))
    c.roundRect(ML, y - 2.7 * cm, CW, 2.7 * cm, 9, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont('Helvetica-Bold', 8)
    c.drawString(ML + 0.6 * cm, y - 0.65 * cm, 'DEUDA TOTAL PROYECTADA' if hay else ('SALDO A FAVOR' if dd['a_favor'] else 'SIN DEUDA'))
    c.setFont('Helvetica-Bold', 24)
    c.drawString(ML + 0.6 * cm, y - 1.55 * cm, BS(dd['total'] if hay else dd['a_favor']))
    c.setFont('Helvetica', 6.8)
    ln = _lineas('Incluye lo realizado hasta hoy y lo agendado (sesiones programadas, mensualidades y proyectos), menos lo pagado. '
                 'No depende del período seleccionado.', 'Helvetica', 6.8, 8.0 * cm)
    for i, t in enumerate(ln[:3]):
        c.drawString(ML + 0.6 * cm, y - 2.0 * cm - i * 0.3 * cm, t)
    items = [('Realizado hasta hoy (pendiente)', dd['actual']), ('Agendado por consumir (pendiente)', dd['prog'])]
    if dd['credito_aplicado']:
        items.append(('(-) Crédito a favor aplicado', dd['credito_aplicado']))
    if not familia:
        items.append(('Deuda vencida (> 30 días)', dd['mora30']))
    x0 = ML + 9.0 * cm
    for i, (lbl, v) in enumerate(items[:4]):
        yy = y - 0.75 * cm - i * 0.58 * cm
        c.setFont('Helvetica', 7)
        c.drawString(x0, yy, lbl)
        c.setFont('Helvetica-Bold', 8.5)
        c.drawRightString(ML + CW - 0.5 * cm, yy, BS(v))
    P.y -= 2.7 * cm + 0.35 * cm


def _detalle_deuda(P, a, familia=False):
    """Composición, antigüedad, deuda por mes y detalle de lo pendiente. familia=True: sin antigüedad ni términos internos."""
    dd = a['deuda']
    if not (dd['tiene_deuda'] or dd['items_total']):
        _parrafo(P, 'No hay montos pendientes de pago.', 7.8, C_VERDE)
        return
    _subtitulo(P, 'De qué se compone la deuda')
    filas = [[f['nombre'] + (' (agendado)' if f['programado'] else ''), fm(f['valor']), fm(f['pagado']), fm(f['pend'])] for f in dd['filas'] if f['valor'] or f['pend']]
    filas.append(['TOTAL PENDIENTE POR ÍTEM', '', '', fm(dd['items_total'])])
    if dd['credito_aplicado']:
        filas.append(['(-) Crédito a favor aplicado', '', '', fm(dd['credito_aplicado'])])
    if dd['ajuste']:
        filas.append(['(+/-) Ajustes por sobrepagos, devoluciones u otros', '', '', fm(dd['ajuste'])])
    filas.append(['= DEUDA TOTAL PROYECTADA', '', '', fm(dd['total'])])
    _tabla_p(P, ['Concepto', 'Valor', 'Pagado', 'Pendiente'], filas, [8.2 * cm, 3.2 * cm, 3.2 * cm, 3.4 * cm])
    if not familia:
        _subtitulo(P, 'Antigüedad de lo ya realizado y no pagado')
        _barras(P, [(x['label'] + f" ({x['n']})", x['pct'], f"{fm(x['monto'], 0)} · {x['pct']:.0f}%",
                     C_ROJO if x['ini'] >= 31 else (C_AMBER_ if x['ini'] >= 8 else C_VERDE)) for x in dd['aging']])
    if dd['por_mes']:
        _subtitulo(P, 'Deuda por mes')
        filas = [[m['label'], fm(m['actual']), fm(m['prog']), fm(m['total'])] for m in dd['por_mes']]
        filas.append(['TOTAL', fm(sum(m['actual'] for m in dd['por_mes'])), fm(sum(m['prog'] for m in dd['por_mes'])), fm(sum(m['total'] for m in dd['por_mes']))])
        _tabla_p(P, ['Mes', 'Realizado', 'Agendado', 'Total'], filas, [5.4 * cm, 4.0 * cm, 4.0 * cm, 4.6 * cm])
    if dd['paquetes']:
        _subtitulo(P, 'Mensualidades y proyectos con saldo')
        _tabla_p(P, ['Código', 'Detalle', 'Tipo', 'Valor', 'Pagado', 'Saldo', 'Desde'],
                 [[x['codigo'], x['nombre'] + (' (agendado)' if x['futuro'] else ''), 'Proyecto' if x['clave'] == 'proyecto' else 'Mensualidad',
                   fm(x['valor']), fm(x['pagado']), fm(x['saldo']), fd(x['ref'])] for x in dd['paquetes']],
                 [2.0 * cm, 5.0 * cm, 2.3 * cm, 2.1 * cm, 2.1 * cm, 2.1 * cm, 2.3 * cm], fsize=6.8)
    if dd['sesiones']:
        _subtitulo(P, f"Sesiones realizadas sin pagar ({dd['n_sesiones']})")
        hdr = ['Fecha', 'Servicio', 'Profesional', 'Monto', 'Pagado', 'Pendiente'] + ([] if familia else ['Antigüedad'])
        ws = [2.4 * cm, 4.0 * cm, 4.4 * cm, 2.2 * cm, 2.2 * cm, 2.4 * cm] if familia else [2.2 * cm, 3.4 * cm, 3.9 * cm, 2.0 * cm, 2.0 * cm, 2.1 * cm, 1.9 * cm]
        _tabla_p(P, hdr, [[fd(x['fecha']), x['servicio'], x['prof'], fm(x['monto']), fm(x['pagado']), fm(x['pend'])] + ([] if familia else [f"{x['dias']} d"])
                          for x in dd['sesiones']], ws, fsize=6.8)
        if dd['n_sesiones'] > len(dd['sesiones']):
            _parrafo(P, f"Se muestran las {len(dd['sesiones'])} más antiguas de {dd['n_sesiones']}.", 6.8, C_MUTED, 'Helvetica-Oblique')
    if dd['programadas']:
        _subtitulo(P, f"Sesiones programadas aún sin pagar ({dd['n_programadas']})")
        _tabla_p(P, ['Fecha', 'Hora', 'Servicio', 'Profesional', 'Valor', 'Pagado', 'Pendiente'],
                 [[fd(x['fecha']), x['hora'], x['servicio'], x['prof'], fm(x['monto']), fm(x['pagado']), fm(x['pend'])] for x in dd['programadas']],
                 [2.4 * cm, 1.5 * cm, 3.6 * cm, 4.0 * cm, 2.2 * cm, 2.2 * cm, 2.1 * cm], fsize=6.8)


# ─────────────────────────────────────────────────────────────────────
# A · DECISIÓN, RIESGO Y VALOR
# ─────────────────────────────────────────────────────────────────────
def seccion_A(pages_data, ctx, helpers):
    a = ctx.get('a')
    if not a:
        return
    P = _Pag(pages_data, helpers).nueva()
    _titulo(P, 'A. Decisión: ¿cómo está este paciente?', C_PRI)
    sm, rg, vl, M = a['semaforo'], a['riesgo'], a['valor'], a['M']
    _veredicto(P, sm)
    for crit in sm['criterios']:
        _fila_criterio(P, crit)
    _parrafo(P, sm['nota'], 6.8, C_MUTED, 'Helvetica-Oblique', espacio=0.25 * cm)

    _subtitulo(P, ('Estado del paciente: INACTIVO' if rg['nivel'] == 'inactivo' else f"Riesgo de abandono: {rg['nivel'].upper()}"),
               {'bajo': C_VERDE, 'medio': C_AMBER_, 'alto': C_ROJO}.get(rg['nivel'], C_MUTED))
    _grilla_p(P, [
        ('Última sesión asistida', fd(rg['ultima']) if rg['ultima'] else '—', f"hace {rg['dias_sin']} días" if rg['dias_sin'] is not None else '', C_MED),
        ('Próxima sesión', fd(rg['proxima']) if rg['proxima'] else 'Sin agendar', f"en {rg['dias_a_proxima']} días" if rg['dias_a_proxima'] is not None else 'agendar', C_VERDE if rg['proxima'] else C_ROJO),
        ('Sesiones por semana', f"{fm(rg['sem30'], 1)}", f"30 días previos: {fm(rg['sem30p'], 1)}" + (f" ({rg['variacion']:+.0f}%)" if rg['variacion'] is not None else ''), C_TEAL),
        ('Inasistencias seguidas', str(rg['seg_faltas']), 'falta o permiso', C_ROJO if rg['seg_faltas'] >= 2 else C_MUTED),
        ('Cancelaciones seguidas', str(rg['seg_cancel']), 'por parte del centro', C_MUTED),
        ('Mensualidad del mes', 'Sin renovar' if rg['mens_sin_renovar'] else 'Al día', '', C_ROJO if rg['mens_sin_renovar'] else C_VERDE),
        ('Tiempo de tratamiento', f"{rg['meses_trat']} meses", f"desde {fd(rg['primera'])}" if rg['primera'] else '', C_PRI),
        ('Umbrales', f"{rg['umbral_obs']} / {rg['umbral_riesgo']} d", 'observación / riesgo', C_MUTED),
    ], cols=4)
    for m in rg['motivos']:
        _parrafo(P, '• ' + m, 7.6, C_TEXTO, espacio=0.02 * cm)
    P.y -= 0.2 * cm

    _subtitulo(P, 'Hallazgos y acciones sugeridas')
    _hallazgos_p(P, a['hallazgos'])

    _subtitulo(P, 'Valor del paciente y rentabilidad')
    items = [
        ('Valor histórico', BS(vl['total_hist'], 0), f"ses. {fm(vl['ind_hist'], 0)} · mens. {fm(vl['mens_hist'], 0)} · proy. {fm(vl['proy_hist'], 0)}", C_MED),
        ('Promedio mensual', BS(vl['prom_mensual'], 0), f"en {vl['meses']} meses", C_TEAL),
        ('Ingreso por hora', BS(vl['ing_hora'], 0), (f"centro (ind.) {fm(a['comparacion']['centro']['ing_hora'], 0)}" if a.get('comparacion') else f"{vl['horas']} h"), C_MORADO),
        ('Posición entre pacientes', f"{vl['ranking']['pos']}° de {vl['ranking']['de']}" if vl.get('ranking') else '—', 'por ingreso en sesiones ind.', C_PRI),
        ('Generado en el período', BS(a['gen']['total'], 0), f"ind. {fm(a['gen']['ind'], 0)} · proy. {fm(a['gen']['gen_proy'], 0)} · mens. {fm(a['gen']['gen_mens'], 0)}", C_VERDE),
        ('Dejado de cobrar', BS(vl['dejado'], 0), f"{_pc(vl['pct_dejado'])} de lo que correspondía", C_ROJO),
        ('Exenciones', BS(vl['exen_v'], 0), f"{vl['exen_n']} sesiones sin cobro", C_AMBER_),
    ]
    if vl['margen'] is not None:
        items.append(('Margen estimado', BS(vl['margen'], 0), f"{_pc(vl['margen_pct'])} · costo {fm(vl['costo'], 0)}", C_VERDE if vl['margen'] >= 0 else C_ROJO))
    _grilla_p(P, items, cols=4)
    if vl['dejado'] or vl['exen_v']:
        _tabla_p(P, ['Concepto', 'Sesiones', 'Monto Bs.'], [
            ['Descuentos en sesiones cobradas', '-', fm(vl['desc_ses'])],
            ['Sesiones realizadas sin cobro (gratuitas)', vl['grat_n'], fm(vl['grat_v'])],
            ['Paquetes con descuento', '-', fm(vl['desc_paq'])],
            ['TOTAL DEJADO DE COBRAR', '', fm(vl['dejado'])],
            ['Exenciones (permiso, cancelación, reprogramación)', vl['exen_n'], fm(vl['exen_v'])],
        ], [10.5 * cm, 2.6 * cm, 4.4 * cm])
    P.cerrar()


# ─────────────────────────────────────────────────────────────────────
# B · CUENTA CORRIENTE Y COBRANZA
# ─────────────────────────────────────────────────────────────────────
def seccion_B(pages_data, ctx, helpers):
    a = ctx.get('a')
    if not a:
        return
    P = _Pag(pages_data, helpers).nueva()
    cb, cu, pr = a['cobranza'], a.get('cuenta'), a['proximas']
    t = cb['tot']
    _titulo(P, 'B. Deuda total y cobranza del período', C_AMBER_)
    _subtitulo(P, 'Deuda total del paciente (sin importar el período)')
    _caja_deuda(P, a)
    _detalle_deuda(P, a)
    _subtitulo(P, 'Cobranza del período seleccionado: lo generado vs. lo cobrado')
    _parrafo(P, 'Generado (devengado) es lo que el paciente consumió en el período, se haya pagado o no. Cobrado es el dinero recibido, '
                'ubicado por su fecha: antes del período (adelantado), durante o después (cobro tardío).', 7.4, C_MUTED, 'Helvetica-Oblique')
    items = [
        ('Generado', BS(t['gen'], 0), 'devengado en el período', C_MED),
        ('Cobrado de eso', BS(t['cobrado'], 0), f"{_pc(t['pct'])} de lo generado", C_VERDE),
        ('Falta cobrar', BS(t['pend'], 0), f"{cb['n_pend_ses']} sesiones sin pagar", C_AMBER_),
        ('Mora > 30 días', BS(cb['mora30'], 0), f"{_pc(cb['pct_mora30'])} de lo generado", C_ROJO),
        ('Rapidez de pago', f"{fm(cb['dias_pago_prom'], 1)} d" if cb['dias_pago_prom'] is not None else '—',
         f"{cb['pct_pago_7d']:.0f}% en ≤ 7 días" if cb['pct_pago_7d'] is not None else 'sin sesiones pagadas', C_MORADO),
    ]
    _grilla_p(P, items, cols=3)
    _subtitulo(P, '1. De lo generado, ¿se cobró?')
    rows = [[f['nombre'], fm(f['gen']), fm(f['antes']), fm(f['durante']), fm(f['despues']), fm(f['pend']), _pc(f['pct'])] for f in cb['filas']]
    rows.append(['TOTAL', fm(t['gen']), fm(t['antes']), fm(t['durante']), fm(t['despues']), fm(t['pend']), _pc(t['pct'])])
    _tabla_p(P, ['Tipo', 'Generado', 'Antes', 'En período', 'Después', 'Falta', '% cobr.'], rows,
             [4.0 * cm, 2.5 * cm, 2.3 * cm, 2.5 * cm, 2.3 * cm, 2.3 * cm, 1.6 * cm])
    _parrafo(P, 'El uso de crédito cuenta como pagado. En proyectos y mensualidades el cobro se estima proporcional al avance de pago.',
             6.8, C_MUTED, 'Helvetica-Oblique')
    _subtitulo(P, '2. Antigüedad de lo que falta cobrar')
    _barras(P, [(x['label'] + f" ({x['n']})", x['pct'], f"{fm(x['monto'], 0)} · {x['pct']:.0f}%",
                 C_ROJO if x['ini'] >= 31 else (C_AMBER_ if x['ini'] >= 8 else C_VERDE)) for x in cb['aging']])
    if cb['pend_ses']:
        _subtitulo(P, '3. Sesiones pendientes de pago')
        _tabla_p(P, ['Fecha', 'Servicio', 'Profesional', 'Monto', 'Pendiente', 'Antigüedad'],
                 [[fd(x['fecha']), x['servicio'], x['prof'], fm(x['monto']), fm(x['pend']), f"{x['dias']} días"] for x in cb['pend_ses']],
                 [2.3 * cm, 3.8 * cm, 4.2 * cm, 2.4 * cm, 2.6 * cm, 2.2 * cm])
        if cb['n_pend_ses'] > len(cb['pend_ses']):
            _parrafo(P, f"Se muestran las {len(cb['pend_ses'])} más antiguas de {cb['n_pend_ses']}.", 6.8, C_MUTED, 'Helvetica-Oblique')
    _subtitulo(P, 'Próximo cobro esperado')
    _parrafo(P, f"{pr['total']} sesiones agendadas ({pr['n7']} en 7 días, {pr['n30']} en 30). Valor de las individuales: {BS(pr['esperado'])}; ya pagado por "
                f"adelantado {BS(pr['adelantado'])}; por cobrar {BS(pr['por_cobrar'])}." + (f" Mensualidad del mes: {BS(pr['mens_prox'])}." if pr['mens_prox'] else '')
                + f" Saldo pendiente de lo ya generado: {BS(t['pend'])}. Las sesiones de proyectos y mensualidades no se suman: están cubiertas por el costo fijo del paquete.", 7.6)
    P.cerrar()


# ─────────────────────────────────────────────────────────────────────
# C · COMPORTAMIENTO, COMPARACIÓN Y PLAN
# ─────────────────────────────────────────────────────────────────────
def _heat(P, pt):
    if not pt['heat']:
        return
    ncol = len(pt['horas'])
    cw = min(1.15 * cm, (CW - 1.6 * cm) / max(ncol, 1))
    ch = 0.62 * cm
    P.asegurar(ch * (len(pt['heat']) + 2) + 0.6 * cm)
    c, y = P.c, P.y
    c.setFont('Helvetica-Bold', 6.2)
    c.setFillColor(C_MUTED)
    for j, h in enumerate(pt['horas']):
        c.drawCentredString(ML + 1.6 * cm + j * cw + cw / 2, y - 0.35 * cm, h)
    y -= 0.5 * cm
    for f in pt['heat']:
        c.setFont('Helvetica-Bold', 7)
        c.setFillColor(C_TSEC)
        c.drawString(ML + 0.2 * cm, y - 0.42 * cm, f['dia_c'])
        for j, ce in enumerate(f['celdas']):
            x = ML + 1.6 * cm + j * cw
            if ce['n'] == 0:
                c.setFillColor(C_GRIS_H)
                c.roundRect(x + 1, y - ch + 1, cw - 2, ch - 2, 3, fill=1, stroke=0)
                continue
            col = _hex('#86efac') if ce['tasa'] >= 80 else (_hex('#fcd34d') if ce['tasa'] >= 50 else _hex('#fca5a5'))
            c.setFillColor(col)
            c.roundRect(x + 1, y - ch + 1, cw - 2, ch - 2, 3, fill=1, stroke=0)
            c.setFillColor(C_TEXTO)
            c.setFont('Helvetica-Bold', 6.4)
            c.drawCentredString(x + cw / 2, y - ch / 2 - 0.08 * cm, f"{ce['att']}/{ce['n']}")
        y -= ch
    P.y = y - 0.15 * cm
    _parrafo(P, 'Cada celda: asistidas / citas que debía tener. Verde ≥ 80%, amarillo 50–80%, rojo < 50%.', 6.8, C_MUTED, 'Helvetica-Oblique')


def _calendarios(P, cals):
    if not cals:
        return
    cw, ch = 1.05 * cm, 0.58 * cm
    ancho = cw * 7
    for k in range(0, len(cals), 2):
        par = cals[k:k + 2]
        alto = ch * (max(len(x['semanas']) for x in par) + 2) + 0.6 * cm
        P.asegurar(alto)
        c, y0 = P.c, P.y
        for i, cal in enumerate(par):
            x0 = ML + 0.3 * cm + i * (ancho + 1.4 * cm)
            c.setFont('Helvetica-Bold', 8)
            c.setFillColor(C_PRI)
            c.drawString(x0, y0 - 0.38 * cm, cal['label'])
            y = y0 - 0.55 * cm
            c.setFont('Helvetica-Bold', 6)
            c.setFillColor(C_MUTED)
            for j, d in enumerate(('Lu', 'Ma', 'Mi', 'Ju', 'Vi', 'Sá', 'Do')):
                c.drawCentredString(x0 + j * cw + cw / 2, y - 0.3 * cm, d)
            y -= 0.4 * cm
            for sem in cal['semanas']:
                for j, d in enumerate(sem):
                    if not d:
                        continue
                    x = x0 + j * cw
                    c.setFillColor(_hex(d['color']) if d['estado'] else C_GRIS_T)
                    c.roundRect(x + 1, y - ch + 1, cw - 2, ch - 2, 3, fill=1, stroke=0)
                    c.setFillColor(C_BLANCO if d['estado'] else C_TSEC)
                    c.setFont('Helvetica-Bold' if d['estado'] else 'Helvetica', 6.8)
                    c.drawCentredString(x + cw / 2, y - ch / 2 - 0.08 * cm, str(d['dia']))
                y -= ch
        P.y = y0 - alto + 0.3 * cm
    leyenda = [('Realizada', '#16a34a'), ('Con retraso', '#f59e0b'), ('Falta sin aviso', '#dc2626'), ('Permiso', '#8b5cf6'),
               ('Cancelada', '#94a3b8'), ('Reprogramada', '#0d9488'), ('Programada', '#2563eb')]
    P.asegurar(0.8 * cm)
    c, x = P.c, ML + 0.3 * cm
    for lbl, col in leyenda:
        c.setFillColor(_hex(col))
        c.roundRect(x, P.y - 0.4 * cm, 0.26 * cm, 0.26 * cm, 2, fill=1, stroke=0)
        c.setFillColor(C_TSEC)
        c.setFont('Helvetica', 6.6)
        c.drawString(x + 0.38 * cm, P.y - 0.36 * cm, lbl)
        x += stringWidth(lbl, 'Helvetica', 6.6) + 1.0 * cm
    P.y -= 0.8 * cm


def seccion_C(pages_data, ctx, helpers):
    a = ctx.get('a')
    if not a:
        return
    P = _Pag(pages_data, helpers).nueva()
    cp, pt, pl, mt = a.get('comparacion'), a['patron'], a['plan'], a['motivos']
    _titulo(P, 'C. Comportamiento, comparación y plan de trabajo', C_TEAL)
    if cp:
        _subtitulo(P, f"Comparación con {cp['etiqueta']} y con el centro")

        def f_(x, k):
            return (BS(x, 0) if k == 'bs' else (f"{x:.1f}%" if k == 'pct' else (f"{x} h" if k == 'h' else str(x))))
        rows = []
        for r in cp['filas']:
            d = r['delta']
            ds = (f"{d:+,.0f}" if r['fmt'] in ('bs', 'n') else f"{d:+.1f}") + (' pts' if r['fmt'] == 'pct' else (' h' if r['fmt'] == 'h' else ''))
            rows.append([r['k'], f_(r['ant'], r['fmt']), f_(r['act'], r['fmt']), ds, f"{r['centro']:.1f}%" if r.get('centro') is not None else '-'])
        _tabla_p(P, ['Indicador', 'Anterior', 'Actual', 'Variación', 'Centro'], rows, [5.6 * cm, 3.0 * cm, 3.0 * cm, 3.2 * cm, 2.7 * cm])
    s = a['series']['tabla_meses']
    if s:
        _subtitulo(P, 'Evolución mensual')
        _tabla_p(P, ['Mes', 'Asistidas', 'Faltas', 'Permisos', '% asistencia', 'Horas', 'Generado ind. Bs.'],
                 [[x['label'], x['atend'], x['faltas'], x['permisos'], _pc(x['asistencia']) if x['asistencia'] is not None else '-', x['horas'], fm(x['gen'])] for x in s],
                 [2.6 * cm, 2.2 * cm, 2.0 * cm, 2.2 * cm, 2.6 * cm, 2.0 * cm, 3.9 * cm])
    P.asegurar(5.5 * cm)
    _subtitulo(P, 'Cuándo asiste: día × hora')
    _heat(P, pt)
    if pt['mejores']:
        _parrafo(P, 'Asiste más: ' + '; '.join(f"{x['dia']} {x['hora']} ({x['tasa']:.0f}% en {x['n']})" for x in pt['mejores']) + '.', 7.4, C_VERDE)
    if pt['peores']:
        _parrafo(P, 'Asiste menos: ' + '; '.join(f"{x['dia']} {x['hora']} ({x['tasa']:.0f}% en {x['n']})" for x in pt['peores']) +
                 '. Conviene proponer a la familia un cambio de horario.', 7.4, C_ROJO)
    if pt['por_dia']:
        _tabla_p(P, ['Día', 'Citas', 'Asistió', '% asistencia'], [[x['dia'], x['n'], x['att'], _pc(x['tasa'])] for x in pt['por_dia']],
                 [4.0 * cm, 2.8 * cm, 2.8 * cm, 3.4 * cm])
    if a['calendarios']:
        P.asegurar(6.5 * cm)
        _subtitulo(P, 'Calendario de sesiones')
        _calendarios(P, a['calendarios'])
    _subtitulo(P, 'Plan de trabajo y cumplimiento')
    _parrafo(P, f"Frecuencia planificada: {fm(pl['plan_sem'], 1)} sesiones/semana · real (últimas 4 semanas): {fm(pl['real_sem'], 1)} · cumplimiento: "
                + (f"{pl['cumplimiento']:.0f}%" if pl['cumplimiento'] is not None else 'sin dato (plan sin frecuencia interpretable)') + '.', 7.6)
    if pl['planes']:
        _tabla_p(P, ['Área', 'Frecuencia', 'Vigencia', 'Revisión', 'Estado'],
                 [[x['area'], x['frecuencia'], f"{fd(x['inicio']) if x['inicio'] else ''} - {fd(x['fin']) if x['fin'] else 'abierto'}",
                   f"{fd(x['revision'])} ({x['estado_rev']})" if x['revision'] else '-', x['estado']] for x in pl['planes']],
                 [3.6 * cm, 3.4 * cm, 4.2 * cm, 3.9 * cm, 2.4 * cm])
    else:
        _parrafo(P, 'No tiene planes de trabajo registrados.', 7.4, C_MUTED, 'Helvetica-Oblique')
    _subtitulo(P, 'Inasistencias, permisos y reprogramaciones')
    _tabla_p(P, ['Origen', 'Cantidad'], [[x['k'], x['n']] for x in mt['por_origen']], [8.0 * cm, 3.0 * cm])
    if mt['top']:
        _parrafo(P, 'Motivos más repetidos: ' + ' · '.join(f"{x['texto']} ({x['n']})" for x in mt['top']) + '.', 7.4)
    if mt['lista']:
        _tabla_p(P, ['Fecha', 'Estado', 'Servicio', 'Motivo registrado'],
                 [[fd(x['fecha']), x['estado_txt'], x['servicio'], x['motivo'] or 'sin motivo'] for x in mt['lista']],
                 [2.3 * cm, 3.0 * cm, 3.6 * cm, 8.6 * cm])
        _parrafo(P, f"{mt['sin_motivo']} de {mt['total']} sin motivo registrado: conviene anotarlo para entender el patrón.", 6.8, C_MUTED, 'Helvetica-Oblique')
    P.cerrar()


# ─────────────────────────────────────────────────────────────────────
# D · SERVICIOS, PRÓXIMAS SESIONES Y SEGUIMIENTO CLÍNICO
# ─────────────────────────────────────────────────────────────────────
def seccion_D(pages_data, ctx, helpers):
    a = ctx.get('a')
    if not a:
        return
    P = _Pag(pages_data, helpers).nueva()
    sv, pr, cl = a['servicios'], a['proximas'], a['clinico']
    _titulo(P, 'D. Servicios, próximas sesiones y seguimiento clínico', C_MORADO)
    _subtitulo(P, 'Servicios y profesionales')
    _tabla_p(P, ['Servicio', 'Estado', 'Ses. período', 'Última asistida', 'Profesionales (% de sus sesiones)', 'Cambios'],
             [[x['nombre'], 'Inactivo' if x['activo'] is False else ('Activo sin uso' if x['alerta'] else 'Activo'), x['n_periodo'],
               f"{fd(x['ultima'])} ({x['dias_sin']} d)" if x['ultima'] else '-',
               ', '.join(f"{q['nombre']} {q['pct']:.0f}%" for q in x['profs']) or '-', x['cambios']] for x in sv['items']],
             [3.3 * cm, 2.3 * cm, 1.9 * cm, 3.0 * cm, 5.9 * cm, 1.4 * cm], fsize=6.9)
    _subtitulo(P, 'Próximas sesiones agendadas')
    if pr['items']:
        _tabla_p(P, ['Fecha', 'Hora', 'Servicio', 'Profesional', 'Sucursal', 'Tipo', 'Valor', 'Pagado'],
                 [[f"{x['dia'][:3]} {fd(x['fecha'])}", x['hora'], x['servicio'], x['prof'], x['suc'], x['tipo'],
                   fm(x['valor']) if x['tipo'] == 'individual' else '-', fm(x['pagado']) if x['tipo'] == 'individual' else '-'] for x in pr['items']],
                 [2.9 * cm, 1.3 * cm, 2.9 * cm, 3.2 * cm, 2.5 * cm, 1.9 * cm, 1.5 * cm, 1.4 * cm], fsize=6.8)
        _parrafo(P, f"{pr['total']} sesiones agendadas; valor de las individuales {BS(pr['esperado'])}, pagado por adelantado {BS(pr['adelantado'])}.", 7, C_MUTED, 'Helvetica-Oblique')
    else:
        _parrafo(P, 'No tiene sesiones agendadas a futuro.', 7.6, C_ROJO)
    _subtitulo(P, 'Seguimiento clínico y calidad del registro')
    _grilla_p(P, [
        ('Notas de evolución', _pc(cl['pct_nota']), f"{cl['con_nota']} de {cl['sesiones']} sesiones realizadas",
         C_VERDE if cl['pct_nota'] >= 80 else (C_AMBER_ if cl['pct_nota'] >= 60 else C_ROJO)),
        ('Última evaluación', fd(cl['ult_eval']) if cl['ult_eval'] else '—', f"hace {cl['dias_ult_eval']} días" if cl['dias_ult_eval'] is not None else '', C_PRI),
        ('Informes sin finalizar', str(cl['informes_pend']), 'de evaluación', C_AMBER_ if cl['informes_pend'] else C_VERDE),
        ('Documentos', str(cl['n_docs']), f"{cl['docs_familia']} compartidos con la familia", C_TEAL),
    ], cols=4)
    if cl['por_prof']:
        _tabla_p(P, ['Profesional', 'Sesiones realizadas', 'Con nota', '% con nota'],
                 [[x['prof'], x['n'], x['con'], _pc(x['pct'])] for x in cl['por_prof']], [7.0 * cm, 3.6 * cm, 3.0 * cm, 3.4 * cm])
    if cl['sin_nota']:
        _parrafo(P, 'Recientes sin nota: ' + ' · '.join(f"{fd(x['fecha'])} {x['servicio']} ({x['prof']})" for x in cl['sin_nota']) + '.', 7.2, C_AMBER_)
    if cl['proy_sin_informe']:
        _parrafo(P, 'Proyectos finalizados sin informe entregado: ' + ', '.join(f"{x['codigo']} ({x['nombre']})" for x in cl['proy_sin_informe']) + '.', 7.4, C_ROJO)
    ev = [f"ADOS-2 módulo {x['modulo']} ({fd(x['fecha_evaluacion'])})" for x in cl['ados']] + [f"ADI-R ({fd(x['fecha_evaluacion'])})" for x in cl['adir']]
    if ev:
        _parrafo(P, 'Evaluaciones: ' + '; '.join(ev) + '.', 7.4)
    if cl['informes']:
        _parrafo(P, 'Informes: ' + '; '.join(f"{fd(x['fecha_informe'])} ({x['estado']})" for x in cl['informes']) + '.', 7.4)
    _subtitulo(P, 'Línea de tiempo del paciente')
    for e in a['timeline'][:30]:
        P.asegurar(0.75 * cm)
        c = P.c
        c.setFillColor(C_MED if not e['futuro'] else C_BLANCO)
        c.setStrokeColor(C_MED)
        c.setLineWidth(1)
        c.circle(ML + 0.5 * cm, P.y - 0.3 * cm, 0.11 * cm, fill=1, stroke=1)
        c.setStrokeColor(C_GRIS_B)
        c.setLineWidth(0.6)
        c.line(ML + 0.5 * cm, P.y - 0.42 * cm, ML + 0.5 * cm, P.y - 0.9 * cm)
        c.setFont('Helvetica', 6.8)
        c.setFillColor(C_MUTED)
        c.drawString(ML + 1.0 * cm, P.y - 0.34 * cm, fd(e['fecha']) + (' (pendiente)' if e['futuro'] else ''))
        c.setFont('Helvetica-Bold', 7.4)
        c.setFillColor(C_TEXTO)
        c.drawString(ML + 3.6 * cm, P.y - 0.34 * cm, e['titulo'][:60])
        if e['detalle']:
            c.setFont('Helvetica', 7)
            c.setFillColor(C_TSEC)
            c.drawString(ML + 3.6 * cm + stringWidth(e['titulo'][:60], 'Helvetica-Bold', 7.4) + 0.2 * cm, P.y - 0.34 * cm, ('- ' + str(e['detalle']))[:70])
        P.y -= 0.6 * cm
    P.cerrar()


# ─────────────────────────────────────────────────────────────────────
# E · EVOLUCIÓN CLÍNICA POR ÁREA (notas de los profesionales)
# ─────────────────────────────────────────────────────────────────────
_COL_TONO = {'favorable': '#16a34a', 'mixta': '#d97706', 'dificultades': '#dc2626', 'neutra': '#94a3b8'}
_COL_TEND = {'mejorando': C_VERDE, 'con más dificultades': C_ROJO, 'estable': C_MED, 'sin datos suficientes': C_MUTED}


def seccion_E(pages_data, ctx, helpers):
    a = ctx.get('a')
    if not a or not a.get('evolucion'):
        return
    ev = a['evolucion']
    P = _Pag(pages_data, helpers).nueva()
    _titulo(P, 'E. Evolución clínica por área: notas de los profesionales', C_PRI)
    _parrafo(P, ev['aviso'], 6.8, C_ROJO, 'Helvetica-Oblique', espacio=0.2 * cm)
    if not ev['areas']:
        _parrafo(P, 'Sin sesiones atendidas en el período: no hay notas para analizar.', 7.6, C_MUTED)
        P.cerrar()
        return
    _grilla_p(P, [
        ('Notas en el período', str(ev['total_notas']), f"de {ev['total_sesiones']} sesiones atendidas ({_pc(ev['pct'])})", C_MED),
        ('Áreas con atención', str(ev['n_areas']), '', C_TEAL),
        ('Profesionales', str(len(ev['profs'])), 'que atendieron al paciente', C_MORADO),
        ('Áreas sin notas', str(len(ev['areas_sin_notas'])), ', '.join(ev['areas_sin_notas'])[:40], C_ROJO if ev['areas_sin_notas'] else C_VERDE),
    ], cols=4)
    _subtitulo(P, 'Notas que escribe cada profesional')
    _tabla_p(P, ['Profesional', 'Áreas', 'Sesiones', 'Con nota', '% con nota', 'Palabras', '% breves', 'Última nota'],
             [[x['prof'], ', '.join(x['areas']), x['ses'], x['notas'], _pc(x['pct']), fm(x['palabras_prom'], 1),
               _pc(x['pct_breves']) if x['notas'] else '-', fd(x['ultima']) if x['ultima'] else '-'] for x in ev['profs']],
             [3.3 * cm, 3.3 * cm, 1.6 * cm, 1.6 * cm, 1.9 * cm, 2.2 * cm, 2.2 * cm, 1.9 * cm], fsize=6.8)
    _parrafo(P, 'Muy breve = menos de 8 palabras. El tono es un análisis automático por palabras clave (orientativo).', 6.8, C_MUTED, 'Helvetica-Oblique')
    for ar in ev['areas']:
        P.asegurar(7.0 * cm)
        _subtitulo(P, f"{ar['nombre']}  ·  tendencia: {ar['tendencia']}", _COL_TEND.get(ar['tendencia'], C_PRI))
        _parrafo(P, f"{ar['sesiones']} sesiones atendidas · {ar['n_notas']} con nota ({_pc(ar['pct_nota'])}) · {fm(ar['palabras_prom'], 1)} palabras por nota "
                    f"({_pc(ar['pct_breves'])} muy breves)" + (f" · última nota {fd(ar['ultima'])} (hace {ar['dias_ultima']} días)" if ar['ultima'] else '')
                    + (f" · balance {ar['neto_ini']:+.0f}% → {ar['neto_fin']:+.0f}%" if ar['neto_ini'] is not None else '') + '.', 7.4)
        if not ar['n_notas']:
            _parrafo(P, 'Ninguna sesión atendida de esta área tiene nota de evolución.', 7.6, C_ROJO, 'Helvetica-Bold')
            continue
        _barras(P, [(lbl, ar['pct_tonos'][k], f"{ar['tonos'][k]} · {ar['pct_tonos'][k]:.0f}%", _hex(_COL_TONO[k]))
                    for k, lbl in (('favorable', 'Favorables'), ('mixta', 'Mixtas'), ('dificultades', 'Con dificultades'), ('neutra', 'Neutras'))],
                ancho_lbl=3.4 * cm)
        if ar['temas']:
            _parrafo(P, 'Temas más repetidos: ' + ', '.join(f"{t['texto']} ({t['n']})" for t in ar['temas']) + '.', 7.2, C_TSEC)
        _tabla_p(P, ['Mes', 'Notas', '% favorables', '% con dificultades'],
                 [[m['label'], m['n'], _pc(m['fav']), _pc(m['dif'])] for m in ar['meses']], [3.0 * cm, 2.4 * cm, 3.6 * cm, 4.2 * cm])
        _subtitulo(P, f"Notas de evolución de {ar['nombre']} ({ar['notas_total']}), en orden cronológico", _COL_TEND.get(ar['tendencia'], C_PRI))
        for n in reversed(ar['notas']):
            P.asegurar(1.5 * cm)
            _parrafo(P, f"{fd(n['fecha'])} {n['hora']}  ·  {n['prof']}  ·  tono: {n['tono']}  ·  {n['palabras']} palabras", 6.9,
                     _hex(_COL_TONO[n['tono']]), 'Helvetica-Bold', espacio=0.0)
            parrafos = [x for x in n['texto'].splitlines() if x.strip()] or [n['texto']]
            for k, par in enumerate(parrafos):
                _parrafo(P, ' '.join(par.split()), 7.1, C_TEXTO, x=ML + 0.6 * cm, ancho=CW - 1.0 * cm,
                         espacio=(0.28 * cm if k == len(parrafos) - 1 else 0.05 * cm))
    P.cerrar()
