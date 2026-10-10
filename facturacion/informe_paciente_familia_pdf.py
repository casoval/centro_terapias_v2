# facturacion/informe_paciente_familia_pdf.py
# =====================================================================
# INFORME PARA LA FAMILIA (tutor del paciente)
# Resumen amable: asistencia, calendario, servicios, próximas sesiones, estado de
# cuenta y plan de trabajo. NO incluye datos internos: riesgo de abandono, semáforo,
# rentabilidad, descuentos/exenciones, mora ni antigüedad de deuda, notas clínicas,
# comparación con el centro ni informes pendientes.
# Entrada: context = {'paciente', 'a' (analizar_paciente), 'desde', 'hasta'}
# =====================================================================
import logging
from datetime import date as _date
from io import BytesIO

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas as pdf_canvas

from .informe_paciente_extra_pdf import (
    BS, _Pag, _calendarios, _grilla_p, _parrafo, _subtitulo, _tabla_p, _titulo, C_AMBER_,
)
from .informe_paciente_pdf import (
    CW, ML, PAGE_H, PAGE_W, C_BLANCO, C_FONDO, C_FONDO_PAG, C_MED, C_MORADO, C_MUTED, C_OSC, C_PRI, C_TEAL, C_TEXTO, C_TSEC,
    C_VERDE, MESES_FULL, NOMBRE_CENTRO, _encabezado, _grad, _logo, _pie,
)
from .informe_profesional_pdf import DIRECCION, TELEFONO, fd, fm, pc as _pc

logger = logging.getLogger(__name__)
TITULO = "INFORME PARA LA FAMILIA"


def _portada(c, pac, periodo_txt, fecha):
    c.setFillColor(C_FONDO_PAG)
    c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    _grad(c, 0, PAGE_H - 6.0 * cm, PAGE_W, 6.0 * cm, C_OSC, C_PRI)
    lp = _logo()
    if lp:
        try:
            c.drawImage(lp, ML, PAGE_H - 5.0 * cm, width=3 * cm, height=3 * cm, preserveAspectRatio=True, mask='auto')
        except Exception:
            pass
    c.setFillColor(C_BLANCO)
    c.setFont("Helvetica-Bold", 15)
    c.drawString(ML + 3.5 * cm, PAGE_H - 2.3 * cm, NOMBRE_CENTRO)
    c.setFont("Helvetica", 8.5)
    c.drawString(ML + 3.5 * cm, PAGE_H - 2.95 * cm, f"{DIRECCION}  |  {TELEFONO}")
    c.setFont("Helvetica-Bold", 11)
    c.drawString(ML + 3.5 * cm, PAGE_H - 4.0 * cm, "INFORME DE SEGUIMIENTO PARA LA FAMILIA")
    c.setFont("Helvetica", 8)
    c.drawString(ML + 3.5 * cm, PAGE_H - 4.6 * cm, "Asistencia, próximas sesiones, estado de cuenta y plan de trabajo")
    ty = PAGE_H - 7.4 * cm
    c.setFillColor(C_FONDO)
    c.roundRect(ML, ty - 3.2 * cm, CW, 3.2 * cm, 8, fill=1, stroke=0)
    c.setFillColor(C_PRI)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(ML + 0.6 * cm, ty - 0.8 * cm, "PACIENTE")
    c.setFillColor(C_TEXTO)
    c.setFont("Helvetica-Bold", 20)
    c.drawString(ML + 0.6 * cm, ty - 1.7 * cm, str(pac)[:40])
    c.setFillColor(C_PRI)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(ML + 0.6 * cm, ty - 2.3 * cm, "PERÍODO")
    c.setFillColor(C_TEXTO)
    c.setFont("Helvetica", 11)
    c.drawString(ML + 0.6 * cm + 1.8 * cm, ty - 2.3 * cm, periodo_txt)
    c.setFillColor(C_TSEC)
    c.setFont("Helvetica", 9)
    from reportlab.pdfbase.pdfmetrics import stringWidth
    y = ty - 4.4 * cm
    for ln in ("Estimada familia:",
               "Este documento resume cómo avanzó la asistencia a las terapias, cuáles son las próximas sesiones",
               "y el estado de cuenta, para que puedan acompañar el proceso con la información al día.",
               "Ante cualquier consulta, el equipo del centro está a su disposición."):
        c.drawString(ML + 0.3 * cm, y, ln)
        y -= 0.55 * cm
    c.setFont("Helvetica-Oblique", 7)
    c.setFillColor(C_MUTED)
    c.drawString(ML, 2.4 * cm, f"Emitido el {fecha}. Documento para uso de la familia del paciente.")


def _mensaje_asistencia(M):
    if M['base'] < 3:
        return "Todavía hay pocas sesiones en este período para valorar la asistencia."
    t = M['tasa_asistencia']
    if t >= 90:
        return "¡Excelente asistencia! Mantener la regularidad es lo que más ayuda al avance de las terapias."
    if t >= 75:
        return "Buena asistencia. La constancia es clave: si algún día no pueden venir, avísennos con anticipación para reprogramar."
    return ("Notamos que algunas sesiones no pudieron realizarse. Nos gustaría conversar para encontrar el horario que mejor "
            "se adapte a la familia y no perder la continuidad del tratamiento.")


def _secciones(P, a, paciente):
    M, cb, pl, pr, cu, sv = a['M'], a['cobranza'], a['plan'], a['proximas'], a.get('cuenta'), a['servicios']
    t = cb['tot']
    # 1. resumen
    _titulo(P, '1. Resumen del período', C_PRI)
    _grilla_p(P, [
        ('Sesiones a las que asistió', str(M['atendidas']), f"de {M['base']} programadas y vencidas", C_VERDE),
        ('Asistencia', _pc(M['tasa_asistencia']), 'asistió / sesiones que debía tener', C_MED),
        ('Puntualidad', _pc(M['puntualidad']), f"{M['retrasos']} llegadas con retraso", C_TEAL),
        ('Horas de terapia', M['horas_txt'], 'tiempo efectivo de atención', C_MORADO),
    ], cols=4)
    _parrafo(P, _mensaje_asistencia(M), 8.2, C_TEXTO, 'Helvetica-Bold', espacio=0.15 * cm)
    if M['faltas'] or M['permisos'] or M['canceladas'] or M['reprogramadas']:
        _parrafo(P, f"Sesiones que no se realizaron: {M['permisos']} con aviso (permiso), {M['faltas']} sin aviso, "
                    f"{M['canceladas']} canceladas por el centro y {M['reprogramadas']} reprogramadas.", 7.6, C_TSEC)
    if a['calendarios']:
        P.asegurar(6.5 * cm)
        _subtitulo(P, 'Calendario de sesiones')
        _calendarios(P, a['calendarios'])

    # 2. servicios
    _titulo(P, '2. Servicios y profesionales', C_TEAL)
    activos = [x for x in sv['items'] if x['activo'] is not False and (x['total_hist'] or x['n_periodo'])]
    _tabla_p(P, ['Servicio', 'Profesional(es)', 'Sesiones en el período', 'Última sesión'],
             [[x['nombre'], ', '.join(q['nombre'] for q in x['profs']) or '-', x['n_periodo'], fd(x['ultima']) if x['ultima'] else '-'] for x in activos]
             or [['Sin servicios con sesiones', '', '', '']],
             [4.6 * cm, 6.2 * cm, 3.6 * cm, 3.0 * cm])

    # 3. próximas sesiones
    _titulo(P, '3. Próximas sesiones', C_MED)
    if pr['items']:
        _tabla_p(P, ['Día y fecha', 'Hora', 'Servicio', 'Profesional', 'Sucursal'],
                 [[f"{x['dia']} {fd(x['fecha'])}", x['hora'], x['servicio'], x['prof'], x['suc']] for x in pr['items'][:15]],
                 [4.0 * cm, 1.6 * cm, 4.2 * cm, 4.6 * cm, 3.4 * cm])
        _parrafo(P, "Si no puede asistir, por favor avise con anticipación para reprogramar la sesión.", 7.4, C_MUTED, 'Helvetica-Oblique')
    else:
        _parrafo(P, "Por el momento no hay sesiones agendadas. Comuníquese con recepción para coordinar los próximos horarios.", 7.8, C_AMBER_)

    # 4. estado de cuenta
    _titulo(P, '4. Estado de cuenta', C_AMBER_)
    items = [
        ('Atenciones del período', BS(t['gen']), 'sesiones, mensualidades y proyectos', C_MED),
        ('Pagado', BS(t['cobrado']), 'aplicado a lo del período', C_VERDE),
        ('Saldo por pagar', BS(t['pend']), 'de lo realizado en el período', C_AMBER_ if t['pend'] > 0 else C_VERDE),
    ]
    if cu and cu['credito'] > 0:
        items.append(('Saldo a favor', BS(cu['credito']), 'crédito disponible', C_TEAL))
    _grilla_p(P, items, cols=len(items))
    if cb['pend_ses']:
        _subtitulo(P, 'Sesiones pendientes de pago')
        _tabla_p(P, ['Fecha', 'Servicio', 'Profesional', 'Pendiente Bs.'],
                 [[fd(x['fecha']), x['servicio'], x['prof'], fm(x['pend'])] for x in sorted(cb['pend_ses'], key=lambda z: z['fecha'])[:20]],
                 [2.6 * cm, 5.4 * cm, 6.0 * cm, 3.4 * cm])
    if a['paq_saldo']:
        _subtitulo(P, 'Mensualidades y proyectos con saldo')
        _tabla_p(P, ['Código', 'Detalle', 'Valor Bs.', 'Pagado Bs.', 'Saldo Bs.'],
                 [[x['codigo'], x['nombre'], fm(x['valor']), fm(x['pagado']), fm(x['saldo'])] for x in a['paq_saldo']],
                 [2.4 * cm, 6.0 * cm, 3.0 * cm, 3.0 * cm, 3.0 * cm])
    _parrafo(P, "Para regularizar un saldo o resolver dudas sobre un pago, puede acercarse a recepción.", 7.4, C_MUTED, 'Helvetica-Oblique')

    # 5. plan de trabajo
    vigentes = [x for x in pl['planes'] if x['vigente']]
    _titulo(P, '5. Plan de trabajo', C_MORADO)
    if vigentes:
        _tabla_p(P, ['Área de intervención', 'Frecuencia', 'Profesional', 'Vigencia', 'Próxima revisión'],
                 [[x['area'], x['frecuencia'], x['prof'] or '-', f"{fd(x['inicio']) if x['inicio'] else ''} - {fd(x['fin']) if x['fin'] else 'abierto'}",
                   fd(x['revision']) if x['revision'] else '-'] for x in vigentes],
                 [3.8 * cm, 3.4 * cm, 4.0 * cm, 3.8 * cm, 3.0 * cm], fsize=6.9)
    else:
        _parrafo(P, "Por el momento no hay un plan de trabajo vigente registrado. El equipo se pondrá en contacto para actualizarlo.", 7.6, C_TSEC)

    # 6. sugerencias
    _titulo(P, '6. Sugerencias para la familia', C_VERDE)
    sug = []
    if pr['items']:
        p0 = pr['items'][0]
        sug.append(f"Próxima sesión: {p0['dia']} {fd(p0['fecha'])} a las {p0['hora']} ({p0['servicio']}).")
    mejores = a['patron']['mejores']
    if mejores and M['base'] >= 4:
        m0 = mejores[0]
        sug.append(f"Los {m0['dia'].lower()} a las {m0['hora']} son los horarios en que más seguido asiste ({m0['tasa']:.0f}%). "
                   "Si algún horario resulta difícil, podemos conversarlo para cambiarlo.")
    if M['atendidas'] and M['puntualidad'] < 70:
        sug.append("Llegar unos minutos antes permite aprovechar completo el tiempo de la sesión.")
    if t['pend'] > 0:
        sug.append(f"Tiene un saldo por pagar de {BS(t['pend'])}. Puede regularizarlo en recepción.")
    if a['riesgo']['mens_sin_renovar'] and a['riesgo']['nivel'] != 'inactivo':
        sug.append("Recuerde renovar la mensualidad de este mes para mantener la continuidad de las terapias.")
    rev = [x for x in vigentes if x['revision'] and 0 <= (x['revision'] - a['hoy']).days <= 30]
    if rev:
        sug.append(f"La revisión del plan de trabajo ({rev[0]['area']}) está prevista para el {fd(rev[0]['revision'])}.")
    if a['clinico']['docs_familia']:
        sug.append(f"Hay {a['clinico']['docs_familia']} documento(s) disponible(s) para ustedes. Consulte en recepción o en la plataforma.")
    sug.append("Ante cualquier duda sobre el proceso terapéutico, converse con el profesional a cargo o con recepción.")
    for s_ in sug:
        _parrafo(P, '• ' + s_, 7.8, C_TEXTO, espacio=0.08 * cm)
    P.y -= 0.3 * cm
    _parrafo(P, f"{NOMBRE_CENTRO}  |  {DIRECCION}  |  Tel.: {TELEFONO}", 7.4, C_MUTED, 'Helvetica-Oblique')


def generar_informe_familia_pdf(context):
    pac, a = context['paciente'], context['a']
    desde, hasta = context.get('desde'), context.get('hasta')
    if desde and hasta:
        periodo = (f"{desde.day} de {MESES_FULL[desde.month]} de {desde.year}" if desde == hasta else f"{fd(desde)}  al  {fd(hasta)}")
    else:
        periodo = 'Todo el historial'
    fecha = _date.today().strftime('%d/%m/%Y')
    nombre = str(pac)

    def construir(total):
        buf = BytesIO()
        c = pdf_canvas.Canvas(buf, pagesize=letter)
        c.setTitle(f"{TITULO} - {nombre}")
        c.setAuthor(NOMBRE_CENTRO)
        pc = [1]

        def make_page():
            c.showPage()
            pc[0] += 1
            c.setFillColor(C_FONDO_PAG)
            c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
            return c, _encabezado(c, pc[0], total, TITULO, nombre, periodo, fecha), pc[0]
        helpers = {'new_page': make_page, 'fecha': fecha, 'canvas': c, 'page_counter': pc, 'periodo_txt': periodo, 'total_pg': [total]}
        _portada(c, pac, periodo, fecha)
        _pie(c, 1, total, fecha)
        P = _Pag([], helpers).nueva()
        _secciones(P, a, pac)
        P.cerrar()
        total_real = pc[0]
        c.save()
        buf.seek(0)
        return buf, total_real

    _b, n = construir(999)
    final, _n = construir(n)
    return final
