# facturacion/informe_sucursal_pdf.py
# =====================================================================
# INFORME PDF POR SUCURSAL
# Mismo estilo, paginación (2 pasadas) y primitivas que el informe por
# profesional: se reutiliza la clase Doc y sólo cambian títulos/secciones.
# Entrada: context = {'sucursal', 'r' (analizar_sucursal), 'desde', 'hasta'}
# =====================================================================
import logging
from datetime import date as _date

from reportlab.lib import colors
from reportlab.lib.units import cm

from .informe_profesional_pdf import (
    Doc, PW, PH, ML, VERDICTO_COL, fm, bs, pc, fd, _t, _recorta, _metrica_box, _grad, _logo,
    C_OSC, C_PRI, C_MED, C_FONDO, C_VERDE, C_AMBER, C_ROJO, C_MORADO, C_TEAL, C_TEXTO, C_TSEC,
    C_MUTED, C_BLANCO, C_GRIS_H, NOMBRE_CENTRO, DIRECCION, TELEFONO, MESES_FULL, FOOT_Y,
)

logger = logging.getLogger(__name__)


class DocSucursal(Doc):
    TITULO_DOC = "INFORME DE SUCURSAL"
    ETIQUETA = "SUCURSAL:"
    NOMBRE_DOC = "Informe de Sucursal"


def _sg(v, d=2):
    return f"+{fm(v, d)}" if v > 0 else fm(v, d)


def _col(v, inv=False):
    ok = v <= 0 if inv else v >= 0
    return C_VERDE if ok else C_ROJO


# ─────────────────────────────────────────────────────────────────────
# PORTADA
# ─────────────────────────────────────────────────────────────────────
def _portada(d, suc, r, periodo):
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
    c.drawString(ML + 3.5 * cm, PH - 4.0 * cm, "INFORME DE SUCURSAL")
    c.setFont("Helvetica", 8)
    c.drawString(ML + 3.5 * cm, PH - 4.6 * cm, "Rentabilidad, gastos, ocupación, profesionales y niños")

    ty = PH - 7.2 * cm
    FS = 3.4 * cm
    fx, fy = ML, ty - FS
    c.setFillColor(C_FONDO)
    c.roundRect(fx, fy, FS, FS, 7, fill=1, stroke=0)
    c.setFillColor(C_PRI)
    c.setFont("Helvetica-Bold", 30)
    c.drawCentredString(fx + FS / 2, fy + FS / 2 - 0.4 * cm, _t(''.join(w[0] for w in suc.nombre.split()[:2]).upper()))
    tx = ML + FS + 0.8 * cm
    c.setFillColor(C_TEXTO)
    c.setFont("Helvetica-Bold", 17)
    c.drawString(tx, ty - 0.7 * cm, _recorta(suc.nombre, 17, PW - tx - ML, 'Helvetica-Bold'))
    c.setFont("Helvetica", 8)
    c.setFillColor(C_TSEC)
    yy = ty - 1.5 * cm
    for ln in [f"Estado: {'Activa' if suc.activa else 'Inactiva'}",
               f"Dirección: {suc.direccion}" if suc.direccion else '',
               f"Teléfono: {suc.telefono}" if suc.telefono else '',
               f"Equipo: {k['profesionales']} profesional(es)  |  {k['pacientes']} niño(s) atendido(s)"]:
        if ln:
            c.drawString(tx, yy, _recorta(ln, 8, PW - tx - ML))
            yy -= 0.45 * cm

    by = fy - 1.0 * cm
    c.setFillColor(C_FONDO)
    c.roundRect(ML, by - 1.6 * cm, PW - 2 * ML, 1.6 * cm, 6, fill=1, stroke=0)
    c.setFont("Helvetica-Bold", 7.5)
    c.setFillColor(C_PRI)
    c.drawString(ML + 0.5 * cm, by - 0.55 * cm, "PERIODO ANALIZADO")
    c.setFont("Helvetica-Bold", 12)
    c.setFillColor(C_TEXTO)
    c.drawString(ML + 0.5 * cm, by - 1.2 * cm, _t(periodo))
    c.setFont("Helvetica", 8)
    c.setFillColor(C_TSEC)
    c.drawRightString(PW - ML - 0.5 * cm, by - 1.2 * cm, f"{r['n_dias']} días  |  {k['total']} sesiones")

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
        from .informe_paciente_pdf import _wrap
        c.setFont("Helvetica", 8)
        _wrap(c, _t(sm['msg']), ML + 4.6 * cm, d.y - 1.25 * cm, PW - 2 * ML - 5.2 * cm, "Helvetica", 8, 0.4 * cm)
        d.y -= 2.2 * cm + 0.5 * cm
    items = [
        ("Ingreso neto", bs(k['neto_centro'], 0), f"generado {fm(k['gen_total'], 0)}", C_VERDE),
        ("Gastos", bs(k['gastos'], 0) if k['tiene_gastos'] else "sin gastos", "operativos + personal", C_ROJO),
        ("Resultado", bs(k['resultado'], 0) if k['tiene_gastos'] else "-",
         f"margen {pc(k['margen_pct'])}" if k['tiene_gastos'] else "ingresa gastos",
         C_VERDE if k['resultado'] >= 0 else C_ROJO),
        ("Ocupación efectiva", pc(k['ocup_efect']), f"{k['min_reloj_txt']} trabajadas", C_MED),
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
def _sec_ejecutivo(d, r):
    k = r['kpis']
    d.page(land=False)
    d.titulo("1. Resumen ejecutivo y decisión", C_PRI)
    sm = r.get('semaforo')
    if sm:
        d.parrafo(f"{sm['msg']}  Criterios: {sm['n_verde']} en verde, {sm['n_ambar']} en ámbar, "
                  f"{sm['n_rojo']} en rojo. {sm['nota']}", 8, C_TEXTO, "Helvetica-Bold")
        d.semaforo_filas(sm['criterios'])
        if sm.get('faltan_gastos'):
            d.parrafo("Nota: no se ingresaron gastos, por lo que no se evalúa la rentabilidad (cobertura y margen).",
                      7, C_MUTED, "Helvetica-Oblique")
    d.espacio(0.2 * cm)
    d.subtitulo("Lo más importante")
    for h in r['hallazgos']:
        col = {'alerta': C_ROJO, 'ok': C_VERDE, 'nota': C_AMBER}.get(h['tipo'], C_TSEC)
        d.parrafo("- " + h['txt'], 7.6, col)
    cmp_ = r.get('comparacion')
    if cmp_:
        d.espacio(0.2 * cm)
        d.subtitulo(f"Comparación con el período anterior ({fd(cmp_['desde'], '%d/%m')} - {fd(cmp_['hasta'])})")
        d.tabla(["Indicador", "Anterior", "Actual", "Variación"], [
            ["Ingreso neto (Bs.)", fm(cmp_['neto'][0]), fm(k['neto_centro']), (_sg(cmp_['neto'][1]), _col(cmp_['neto'][1]))],
            ["Gastos (Bs.)", fm(cmp_['gastos'][0]), fm(k['gastos']), (_sg(cmp_['gastos'][1]), _col(cmp_['gastos'][1], True))],
            ["Resultado (Bs.)", fm(cmp_['resultado'][0]), fm(k['resultado']), (_sg(cmp_['resultado'][1]), _col(cmp_['resultado'][1]))],
            ["Sesiones atendidas", str(cmp_['atendidas'][0]), str(k['atendidas']), (_sg(cmp_['atendidas'][1], 0), _col(cmp_['atendidas'][1]))],
            ["Ocupación efectiva", pc(cmp_['ocup'][0]), pc(k['ocup_efect']), (_sg(cmp_['ocup'][1], 1) + " pts", _col(cmp_['ocup'][1]))],
            ["Niños atendidos", str(cmp_['pacientes'][0]), str(k['pacientes']), (_sg(cmp_['pacientes'][1], 0), _col(cmp_['pacientes'][1]))],
        ], [6.0 * cm, 3.6 * cm, 3.6 * cm, 4.4 * cm], ['l', 'r', 'r', 'r'], 7.5)


def _sec_resultado(d, r):
    k, g = r['kpis'], r['gastos']
    d.page(land=False)
    d.titulo("2. Resultado, gastos y punto de equilibrio", C_VERDE)
    d.parrafo("Ingreso neto = generado por los profesionales menos la comisión de profesionales externos. "
              "Los gastos combinan egresos registrados en el sistema, los conceptos ingresados por la dirección y el "
              "costo mensual por profesional, prorrateados por días en meses parciales.")
    d.grilla([
        ("Generado", bs(k['gen_total']), f"{bs(k['ingreso_hora'], 0)} por hora", C_MED),
        ("Ingreso neto", bs(k['neto_centro']), f"{bs(k['neto_hora'], 0)} netos por hora", C_VERDE),
        ("Gastos", bs(k['gastos']), f"operativos {fm(k['gastos_oper'], 0)} | personal {fm(k['gastos_pers'], 0)}", C_ROJO),
        ("Resultado", bs(k['resultado']), f"margen {pc(k['margen_pct'])}" if k['tiene_gastos'] else "sin gastos",
         C_VERDE if k['resultado'] >= 0 else C_ROJO),
        ("Cobertura de gastos", f"{fm(k['cobertura'])}x" if k['tiene_gastos'] else "-", "neto / gastos (1,00x = equilibrio)", C_AMBER),
        ("Gasto por hora trabajada", bs(k['gasto_hora']) if k['tiene_gastos'] else "-", f"por hora ofrecida {fm(k['gasto_hora_cap'], 0)}", C_MORADO),
        ("Por generar (agenda)", bs(k['por_generar']), "sesiones programadas", C_TEAL),
        ("Potencial no aprovechado", bs(k['potencial_no_aprovechado'], 0), "estimado, horas libres sin cobro", C_MUTED),
    ], cols=4)
    d.subtitulo("Del ingreso al resultado")
    d.tabla(["Concepto", "Bs."], [
        ["Generado por los profesionales", fm(k['gen_total'])],
        ["   Sesiones individuales", f"{fm(k['gen_ind'])}  ({pc(k['pct_ind'])})"],
        ["   Proyectos", f"{fm(k['gen_proy'])}  ({pc(k['pct_proy'])})"],
        ["   Mensualidades", f"{fm(k['gen_mens'])}  ({pc(k['pct_mens'])})"],
        ["(-) Comisión de profesionales externos", fm(k['ext_prof'])],
        [("= Ingreso neto del centro", C_PRI), (fm(k['neto_centro']), C_PRI)],
        ["(-) Gastos operativos", fm(k['gastos_oper'])],
        ["(-) Costo de personal / profesionales", fm(k['gastos_pers'])],
        [("= RESULTADO", C_VERDE if k['resultado'] >= 0 else C_ROJO), (fm(k['resultado']), C_VERDE if k['resultado'] >= 0 else C_ROJO)],
    ], [11.0 * cm, 6.6 * cm], ['l', 'r'], 7.6)
    d.subtitulo("Punto de equilibrio")
    if not k['tiene_gastos']:
        d.parrafo("No hay gastos considerados; ingrese gastos para calcular el punto de equilibrio.", 7.6, C_MUTED, "Helvetica-Oblique")
    elif k['faltante']:
        d.parrafo(f"Faltan Bs. {fm(k['faltante'])} para cubrir los gastos del período: equivale a ~{fm(k['h_equilibrio'], 1)} horas "
                  f"más de atención" + (f" (~{k['ses_equilibrio']} sesiones)" if k['ses_equilibrio'] else "") +
                  f" al ritmo actual de Bs. {fm(k['neto_hora'])} netos por hora. La sucursal tiene {k['h_sinag_txt']} de horario "
                  f"sin paciente agendado y {k['h_no_pagadas_txt']} de horas sin cobro; llenarlas aportaría ~Bs. {fm(k['cobrable_libre'], 0)}.",
                  7.8, C_ROJO)
    else:
        d.parrafo(f"La sucursal cubre sus gastos: el ingreso neto los supera en Bs. {fm(k['resultado'])} ({fm(k['cobertura'])}x). "
                  f"Cada hora trabajada deja Bs. {fm(k['neto_hora'])} netos frente a Bs. {fm(k['gasto_hora'])} de gasto.", 7.8, C_VERDE)
    d.subtitulo("Gastos considerados")
    org = {'registrado': 'Registrado', 'global': 'Global', 'manual': 'Ingresado', 'profesional': 'Profesional'}
    d.tabla(["Concepto", "Categoría", "Origen", "Detalle", "Monto Bs.", "%"],
            [[f['concepto'], f['categoria'], org.get(f['origen'], f['origen']), f['detalle'], fm(f['monto']), pc(f['pct'])]
             for f in g['filas']] + ([[("TOTAL GASTOS", C_PRI), '', '', '', (fm(g['total']), C_PRI), '']] if g['filas'] else []),
            [4.6 * cm, 3.4 * cm, 2.0 * cm, 3.6 * cm, 2.4 * cm, 1.6 * cm], ['l', 'l', 'l', 'l', 'r', 'r'], 7)
    if g['filas']:
        d.espacio(0.2 * cm)
        top = g['filas'][:8]
        mx = max(f['monto'] for f in top) or 1
        d.ensure(0.55 * cm * len(top) + 0.4 * cm)      # el gráfico completo en una sola página
        d.barras_h([(f['concepto'], f['monto'], f"Bs. {fm(f['monto'], 0)} ({pc(f['pct'])})", None) for f in top],
                   color=C_ROJO, max_val=mx)
    if g['excl_pers']:
        d.parrafo(f"Se excluyeron Bs. {fm(g['excl_pers'])} de egresos de personal/honorarios registrados para no duplicar los costos "
                  f"por profesional ingresados.", 7, C_MUTED, "Helvetica-Oblique")
    if g['inc_egr'] and g['share_glob']:
        d.parrafo(f"Gastos globales (sin sucursal): se cargó a esta sucursal el {pc(g['share_glob'] * 100)} de su total.",
                  7, C_MUTED, "Helvetica-Oblique")


def _sec_ingresos(d, r):
    k = r['kpis']
    d.titulo("3. De dónde viene el dinero", C_MORADO)
    d.subtitulo("Por tipo de atención")
    d.tabla(["Tipo", "Sesiones", "Atend.", "Faltas", "Horas", "Niños", "Generó Bs.", "% total", "Bs/hora"],
            [[t['nombre'], t['n'], t['atend'], t['faltas'], t['horas_txt'], t['pacs'], fm(t['gen']), pc(t['pct_gen']), fm(t['ingreso_hora'], 0)]
             for t in r['por_tipo']],
            [4.4 * cm, 1.6 * cm, 1.4 * cm, 1.4 * cm, 1.8 * cm, 1.4 * cm, 2.6 * cm, 1.7 * cm, 1.7 * cm],
            ['l', 'r', 'r', 'r', 'r', 'r', 'r', 'r', 'r'])
    d.parrafo(f"Proyectos solo / grupal: Bs. {fm(k['gen_proy_solo'], 0)} / {fm(k['gen_proy_grupal'], 0)}  |  "
              f"Mensualidades solo / grupal: Bs. {fm(k['gen_mens_solo'], 0)} / {fm(k['gen_mens_grupal'], 0)}. "
              f"En paquetes el costo es fijo y se reparte entre profesionales según el valor de sus sesiones a precio individual.",
              7, C_MUTED, "Helvetica-Oblique")
    d.subtitulo("Por servicio")
    d.tabla(["Servicio", "Atend.", "Faltas", "% faltas", "Horas", "Niños", "Generó Bs.", "% total", "Bs/hora"],
            [[s['nombre'], s['atend'], s['faltas'], pc(s['tasa_faltas']), s['horas_txt'], s['pacs'], fm(s['gen']),
              pc(s['pct_gen']), fm(s['ingreso_hora'], 0)] for s in r['por_servicio']],
            [4.4 * cm, 1.4 * cm, 1.4 * cm, 1.6 * cm, 1.8 * cm, 1.4 * cm, 2.6 * cm, 1.7 * cm, 1.7 * cm],
            ['l', 'r', 'r', 'r', 'r', 'r', 'r', 'r', 'r'])


def _sec_horas(d, r):
    k = r['kpis']
    d.page(land=False)
    d.titulo("4. Horas, ocupación y horarios vacíos", C_TEAL)
    d.parrafo("Horas de reloj de todos los profesionales (suma). La falta sin aviso se cobra pero el profesional queda libre esa hora; "
              "permisos, cancelaciones y reprogramaciones liberan la hora sin ingreso. Se consideran solo los días ya transcurridos.")
    d.grilla([
        ("Horas trabajadas", k['min_reloj_txt'], f"con pacientes: {k['min_pacientes_txt']}", C_VERDE),
        ("Horario transcurrido", k['cap_el_txt'], f"{r['horario_fuentes']['asistencia']} prof. con horario de Asistencia", C_MED),
        ("Ocupación efectiva", pc(k['ocup_efect']), "trabajado / horario", C_TEAL),
        ("Ocupación agendada", pc(k['ocup_el']), "incluye faltas y programadas", C_MORADO),
        ("Perdidas por inasistencia", k['h_perdidas_txt'], f"{pc(k['pct_perdidas'])} del horario", C_ROJO),
        ("Sin paciente agendado", k['h_sinag_txt'], f"{pc(k['pct_sinag'])} del horario", C_MUTED),
        ("Faltas sin aviso", f"{k['faltas']} ({pc(k['tasa_faltas'])})", f"{k['h_falta_txt']} esperadas (se cobran)", C_ROJO),
        ("Horas sin cobro", k['h_no_pagadas_txt'], "permiso, cancelada, sin agendar", C_AMBER),
    ], cols=4)
    d.subtitulo("Qué pasó con cada hora del horario")
    d.barra_apilada([(x['label'], x['pct'], x['color'], x['txt']) for x in r['desglose'] if x['pct'] > 0])
    d.subtitulo("Evolución mensual")
    pm = r['por_mes']
    if pm:
        d.tabla(["Mes", "Atend.", "Faltas", "Horas", "Ocup.", "Neto Bs.", "Gastos Bs.", "Resultado Bs."],
                [[a['label'], a['n_atend'], a['n_falta'], a['att_txt'], pc(a['ocup_efect']), fm(a['neto']), fm(a['gastos']),
                  (fm(a['resultado']), C_VERDE if a['resultado'] >= 0 else C_ROJO)] for a in pm],
                [2.6 * cm, 1.4 * cm, 1.4 * cm, 2.0 * cm, 1.6 * cm, 2.8 * cm, 2.8 * cm, 3.0 * cm],
                ['l', 'r', 'r', 'r', 'r', 'r', 'r', 'r'])
        if len(pm) >= 2:
            d.espacio(0.1 * cm)
            d.columnas([a['label'][:3] for a in pm], [max(a['neto'], 0) for a in pm], color=C_VERDE,
                       color2=C_ROJO, valores2=[a['gastos'] for a in pm])
            d.parrafo("Verde = ingreso neto | Rojo = gastos del mes. El último mes puede estar incompleto.", 6.8, C_MUTED, "Helvetica-Oblique")
    d.subtitulo("Ocupación por día de la semana")
    d.tabla(["Día", "Atend.", "Horas", "Ocupación", "Libres", "Generó Bs."],
            [[w['dia'], w['n_atend'], w['att_txt'], pc(w['ocup']), w['libre_txt'], fm(w['gen'])] for w in r['por_dia_semana']],
            [3.4 * cm, 2.0 * cm, 2.6 * cm, 2.6 * cm, 2.6 * cm, 3.2 * cm], ['l', 'r', 'r', 'r', 'r', 'r'])
    if r['heat']:
        d.ensure(0.5 * cm * (len(r['heat']) + 3) + 1.2 * cm)     # título + mapa juntos
        d.subtitulo("Mapa de calor de ocupación (día x hora, % de ocupación de la sucursal)")
        d.heat(r['heat'], r['heat_horas'])
    if r['franjas_libres']:
        d.parrafo("Franjas más vacías: " + "; ".join(f"{f['h']} ({pc(f['ocup'])}, {f['libre_txt']} libres)" for f in r['franjas_libres']) +
                  ".  Más llenas: " + "; ".join(f"{f['h']} ({pc(f['ocup'])})" for f in r['franjas_llenas']) + ".", 7.4, C_TSEC)


def _sec_profesionales(d, r):
    d.page(land=True)
    d.titulo(f"5. Profesionales: aporte y rentabilidad ({len(r['profesionales'])})", C_PRI)
    k = r['kpis']
    rows = []
    for p in r['profesionales']:
        rows.append([
            p['pos'], p['nombre'] + ('' if p['activo'] else ' (inactivo)'), fm(p['gen']), fm(p['neto']), pc(p['pct_neto']),
            fm(p['costo_periodo']) if p['costo_periodo'] else '-',
            (fm(p['margen']), C_VERDE if p['rentable'] else C_ROJO) if p['margen'] is not None else '-',
            f"{fm(p['cobertura'])}x" if p['cobertura'] is not None else '-',
            p['horas_txt'], 'sin horario' if p['sin_horario'] else f"{p['ocup_efect']:.0f}% ({p['ocup']:.0f}%)",
            p['libre_txt'], p['perdidas_txt'], fm(p['neto_hora'], 0), pc(p['tasa_faltas']), p['pacientes'],
        ])
    rows.append([('', C_PRI), ("TOTAL SUCURSAL", C_PRI), (fm(k['gen_total']), C_PRI), (fm(k['neto_centro']), C_PRI), '',
                 (fm(k['costo_periodo']) if k['costo_periodo'] else '', C_PRI), '', '', (k['min_reloj_txt'], C_PRI),
                 (pc(k['ocup_efect']), C_PRI), k['libre_el_txt'], k['h_perdidas_txt'], fm(k['neto_hora'], 0), pc(k['tasa_faltas']), k['pacientes']])
    d.tabla(["#", "Profesional", "Generó", "Aporte neto", "% suc.", "Costo", "Margen", "Cobert.", "Horas", "Ocup. ef. (ag.)",
             "Libre", "Perdidas", "Neto/h", "Faltas", "Niños"],
            rows,
            [0.6 * cm, 3.8 * cm, 1.9 * cm, 1.9 * cm, 1.2 * cm, 1.6 * cm, 1.7 * cm, 1.2 * cm, 1.4 * cm, 2.4 * cm, 1.4 * cm, 1.4 * cm, 1.2 * cm, 1.1 * cm, 1.0 * cm],
            ['c', 'l', 'r', 'r', 'r', 'r', 'r', 'r', 'r', 'r', 'r', 'r', 'r', 'r', 'r'], 6.6, row_h=0.46 * cm)
    d.parrafo("Costo = costo mensual ingresado por la dirección, prorrateado por días. Margen = aporte neto - costo. Cobertura = aporte neto / costo. "
              "Para el detalle de cada profesional consulte su informe individual con el mismo período.", 6.8, C_MUTED, "Helvetica-Oblique")
    cp = r['concentracion'].get('prof')
    if cp:
        d.parrafo(f"Dependencia: {cp['top1_nombre']} aporta el {pc(cp['top1'])} del ingreso neto de la sucursal.", 7.4, C_TSEC)


def _sec_ninos(d, r):
    d.page(land=True)
    k = r['kpis']
    d.titulo(f"6. Niños atendidos: rentabilidad ({len(r['pacientes'])})", C_MORADO)
    pr = r.get('pac_resumen')
    if pr:
        d.parrafo(f"{pr['rentables']} de {pr['n']} niños cubren el costo que se les asigna; {pr['deficit']} están en déficit por "
                  f"Bs. {fm(pr['perdida'])}. Los rentables aportan Bs. {fm(pr['ganancia'])} de margen. "
                  f"Costo asignado por hora-niño: Bs. {fm(k['costo_hora_pac'])}.", 7.6, C_TEXTO)
    else:
        d.parrafo("Ingrese gastos para calcular cuánto aporta o cuesta cada niño.", 7.6, C_MUTED, "Helvetica-Oblique")
    cn = r['concentracion'].get('pac')
    if cn:
        d.parrafo(f"Dependencia de pocos niños: el principal aporta {pc(cn['top1'])} del generado y los 5 principales {pc(cn['top5'])} "
                  f"(riesgo {cn['nivel'].upper()}).", 7.4, C_TSEC)
    d.tabla(["Niño", "Servicios", "Profesionales", "Ses.", "Atend.", "Faltas", "Horas", "Neto Bs.", "% suc.", "Costo asign.", "Margen Bs.", "Marg. %"],
            [[p['nombre'] + (' (inactivo)' if p['inactivo'] else ''), ', '.join(p['servicios']), ', '.join(p['profesionales']),
              p['n'], p['atend'], p['faltas'], p['horas_txt'], fm(p['neto']), pc(p['pct_neto']),
              fm(p['costo']) if p['margen'] is not None else '-',
              (fm(p['margen']), C_VERDE if p['rentable'] else C_ROJO) if p['margen'] is not None else '-',
              pc(p['margen_pct']) if p['margen_pct'] is not None else '-'] for p in r['pacientes']],
            [3.8 * cm, 3.4 * cm, 3.6 * cm, 0.9 * cm, 1.1 * cm, 1.1 * cm, 1.5 * cm, 1.9 * cm, 1.2 * cm, 1.9 * cm, 1.9 * cm, 1.3 * cm],
            ['l', 'l', 'l', 'r', 'r', 'r', 'r', 'r', 'r', 'r', 'r', 'r'], 6.5, row_h=0.42 * cm)
    d.parrafo("El costo asignado es una distribución, no un gasto real por niño: costo directo del profesional repartido por minutos atendidos "
              "+ resto de gastos repartido por minutos atendidos. La suma de márgenes equivale al resultado de la sucursal.",
              6.8, C_MUTED, "Helvetica-Oblique")


def _sec_paquetes(d, r):
    d.page(land=True)
    pq = r['paq_resumen']
    d.titulo("7. Proyectos y mensualidades", C_TEAL)
    d.parrafo(f"Proyectos: {pq['proy']['n']} (valor Bs. {fm(pq['proy']['valor'], 0)}, generó {fm(pq['proy']['gen'], 0)}, por generar "
              f"{fm(pq['proy']['por_generar'], 0)}, {pq['proy']['grupales']} grupales).  Mensualidades: {pq['mens']['n']} (valor "
              f"Bs. {fm(pq['mens']['valor'], 0)}, generó {fm(pq['mens']['gen'], 0)}, por generar {fm(pq['mens']['por_generar'], 0)}, "
              f"{pq['mens']['grupales']} grupales). La participación de cada profesional se pondera por lo que costaría cada sesión como individual.",
              7.4, C_TEXTO)
    for titulo, lst, lbl in (("Proyectos", r['proyectos'], 'Proyecto'), ("Mensualidades", r['mensualidades'], 'Período')):
        d.subtitulo(titulo)
        d.tabla(["Código", f"{lbl} / niño", "Estado", "Modal.", "Valor", "Factor", "Profesionales y participación", "Generó", "Por generar", "Cobrado"],
                [[x['codigo'], f"{x['nombre']} - {x['paciente']}", x['estado'], x['modalidad'], fm(x['valor'], 0), fm(x['factor']),
                  '; '.join(f"{q['nombre']} {q['share']:.1f}% ({fm(q['gen'], 0)})" for q in x['partes']),
                  fm(x['gen_periodo']), fm(x['por_generar']), pc(x['ratio_cobro'])] for x in lst],
                [1.9 * cm, 4.2 * cm, 1.8 * cm, 1.3 * cm, 1.5 * cm, 1.1 * cm, 6.6 * cm, 1.8 * cm, 1.8 * cm, 1.4 * cm],
                ['l', 'l', 'l', 'l', 'r', 'r', 'l', 'r', 'r', 'r'], 6.4, row_h=0.42 * cm)
    d.parrafo("Factor = costo del paquete / valor de sus sesiones a precio individual (menor a 1 = vendido con descuento).",
              6.8, C_MUTED, "Helvetica-Oblique")


def _sec_comparaciones(d, r):
    k = r['kpis']
    d.page(land=False)
    d.titulo("8. Comparación entre sucursales y conciliación", C_AMBER)
    if r['comparativa']:
        d.subtitulo("Contra las demás sucursales activas")
        d.tabla(["Sucursal", "Neto Bs.", "Gastos Bs.", "Resultado", "Ocup.", "Neto/h", "Niños", "Prof."],
                [[(c['nombre'] + (' (esta)' if c['actual'] else ''), C_PRI if c['actual'] else C_TEXTO), fm(c['neto'], 0), fm(c['gastos'], 0),
                  (fm(c['resultado'], 0), C_VERDE if c['resultado'] >= 0 else C_ROJO), pc(c['ocup_efect']), fm(c['neto_hora'], 0),
                  c['pacientes'], c['profesionales']] for c in r['comparativa']],
                [4.6 * cm, 2.4 * cm, 2.4 * cm, 2.4 * cm, 1.6 * cm, 1.6 * cm, 1.3 * cm, 1.3 * cm],
                ['l', 'r', 'r', 'r', 'r', 'r', 'r', 'r'])
        d.parrafo("Para las otras sucursales solo se consideran egresos registrados; los cuadros manuales y costos por profesional "
                  "aplican únicamente a esta sucursal.", 6.8, C_MUTED, "Helvetica-Oblique")
    cc = r.get('conciliacion')
    if cc:
        d.subtitulo("Conciliación con el reporte financiero")
        d.tabla(["Concepto", "Bs."], [
            ["Generado (este informe, devengado por sesión)", fm(cc['generado'])],
            ["Consumido (reporte financiero)", fm(cc['consumido'])],
            ["   Sesiones / Mensualidades / Proyectos", f"{fm(cc['consumido_ses'], 0)} / {fm(cc['consumido_mens'], 0)} / {fm(cc['consumido_proy'], 0)}"],
            [("Diferencia", C_VERDE if cc['cuadra'] else C_AMBER), (fm(cc['diferencia']), C_VERDE if cc['cuadra'] else C_AMBER)],
            ["Cobrado en el período (pagos directos)", fm(cc['pagado'])],
            ["Devoluciones", fm(cc['devoluciones'])],
            ["Saldo del período (pagado - consumido)", (fm(cc['saldo']), C_VERDE if cc['saldo'] >= 0 else C_ROJO)],
        ], [11.0 * cm, 6.6 * cm], ['l', 'r'], 7.6)
        d.parrafo(cc['explicacion'], 7, C_MUTED, "Helvetica-Oblique")


def _sec_anexo(d, r):
    egr = r['gastos'].get('detalle_egresos') or []
    if not egr:
        return
    d.page(land=True)
    d.titulo(f"Anexo. Egresos registrados incluidos ({len(egr)})", C_MUTED)
    d.tabla(["N°", "Fecha", "Concepto", "Categoría", "Proveedor", "Origen", "Total Bs.", "Cargado Bs."],
            [[e['numero'], fd(e['fecha']), e['concepto'], e['categoria'], e['proveedor'], e['origen'], fm(e['monto_total']), fm(e['monto'])]
             for e in egr],
            [2.6 * cm, 2.2 * cm, 6.0 * cm, 3.6 * cm, 3.6 * cm, 3.4 * cm, 2.2 * cm, 2.2 * cm],
            ['l', 'l', 'l', 'l', 'l', 'l', 'r', 'r'], 6.6, row_h=0.4 * cm)
    d.parrafo("Cargado = monto del egreso prorrateado por los días del período (y por el reparto elegido en gastos globales).",
              6.8, C_MUTED, "Helvetica-Oblique")


# ─────────────────────────────────────────────────────────────────────
# ORQUESTADOR (2 pasadas para el total de páginas)
# ─────────────────────────────────────────────────────────────────────
def generar_informe_sucursal_pdf(context):
    suc = context['sucursal']
    r = context['r']
    desde, hasta = context['desde'], context['hasta']
    if desde == hasta:
        periodo = f"{desde.day} de {MESES_FULL[desde.month]} de {desde.year}"
    else:
        periodo = f"{fd(desde)}  al  {fd(hasta)}"
    fecha = _date.today().strftime('%d/%m/%Y')

    def construir(total):
        d = DocSucursal(total, suc.nombre, periodo, fecha)
        d.portada_inicio()
        _portada(d, suc, r, periodo)
        _sec_ejecutivo(d, r)
        _sec_resultado(d, r)
        _sec_ingresos(d, r)
        _sec_horas(d, r)
        _sec_profesionales(d, r)
        _sec_ninos(d, r)
        _sec_paquetes(d, r)
        _sec_comparaciones(d, r)
        _sec_anexo(d, r)
        d.c.save()
        d.buf.seek(0)
        return d

    primera = construir(999)
    final = construir(primera.pg)
    return final.buf
