# facturacion/reporte_profesional_extra.py
# =====================================================================
# COMPLEMENTOS DEL REPORTE POR PROFESIONAL (decisión de continuidad)
#   2. Cobrado vs generado
#   3. Marcaje de asistencia vs horas con pacientes
#   4. Comparación con el resto del equipo
#   5. Semáforo de decisión (criterios visibles)
#   6. Tendencia de 6 meses
#   7. Retención de pacientes
#   8. Dependencia de pocos pacientes
#   9. Notas clínicas
# Se llama desde analizar(..., completo=True) y agrega claves al dict.
# =====================================================================

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from .reporte_profesional_data import (
    ATENDIDAS, CONSUMIDAS, MESES_CORTO, hm, _pct, _f, es_num,
)

VERDE, AMBAR, ROJO = 'verde', 'ambar', 'rojo'
COLOR = {VERDE: '#16a34a', AMBAR: '#d97706', ROJO: '#dc2626'}
PUNTOS = {VERDE: 1.0, AMBAR: 0.5, ROJO: 0.0}


# ─────────────────────────────────────────────────────────────────────
# 2. COBRADO vs GENERADO
# ─────────────────────────────────────────────────────────────────────
def cobranza(r):
    from facturacion.models import Pago, DetallePagoMasivo

    filas = r['filas']
    ids = [f['id'] for f in filas if f['tipo'] == 'individual' and f['estado'] in CONSUMIDAS]
    pagado = defaultdict(float)
    if ids:
        for row in (Pago.objects.filter(sesion_id__in=ids, anulado=False)
                    .values('sesion_id').annotate(t=Sum('monto'))):
            pagado[row['sesion_id']] += _f(row['t'])
        for row in (DetallePagoMasivo.objects
                    .filter(tipo='sesion', sesion_id__in=ids, pago__anulado=False)
                    .values('sesion_id').annotate(t=Sum('monto'))):
            pagado[row['sesion_id']] += _f(row['t'])

    gen_ind = cob_ind = 0.0
    for f in filas:
        if f['tipo'] == 'individual' and f['estado'] in CONSUMIDAS:
            cob = min(pagado.get(f['id'], 0.0), f['generado']) if f['generado'] else 0.0
            f['cobrado'] = round(cob, 2)
            gen_ind += f['generado']
            cob_ind += cob
        else:
            f['cobrado'] = None

    def _pm(lista, valor_key):
        gen = cob = 0.0
        for x in lista:
            ratio = min(x['cobrado'] / x[valor_key], 1.0) if x[valor_key] else 0.0
            x['ratio_cobro'] = round(ratio * 100, 1)
            x['cobrado_mio'] = round(x['gen_periodo'] * ratio, 2)
            gen += x['gen_periodo']
            cob += x['cobrado_mio']
        return gen, cob

    gen_p, cob_p = _pm(r['proyectos'], 'valor')
    gen_m, cob_m = _pm(r['mensualidades'], 'costo')
    gen = gen_ind + gen_p + gen_m
    cob = cob_ind + cob_p + cob_m
    pend = max(gen - cob, 0)
    r['cobranza'] = {
        'generado': round(gen, 2), 'cobrado': round(cob, 2), 'pendiente': round(pend, 2),
        'pct': _pct(cob, gen),
        'ind': {'gen': round(gen_ind, 2), 'cob': round(cob_ind, 2), 'pct': _pct(cob_ind, gen_ind)},
        'proy': {'gen': round(gen_p, 2), 'cob': round(cob_p, 2), 'pct': _pct(cob_p, gen_p)},
        'mens': {'gen': round(gen_m, 2), 'cob': round(cob_m, 2), 'pct': _pct(cob_m, gen_m)},
    }
    r['kpis']['cobrado'] = r['cobranza']['cobrado']
    r['kpis']['pendiente_cobro'] = r['cobranza']['pendiente']
    r['kpis']['pct_cobrado'] = r['cobranza']['pct']


# ─────────────────────────────────────────────────────────────────────
# 3. MARCAJE DE ASISTENCIA
# ─────────────────────────────────────────────────────────────────────
def marcaje(prof, r):
    from asistencia.models import RegistroAsistencia

    user = prof.user
    out = {'disponible': False, 'motivo': 'El profesional no tiene usuario del sistema vinculado.'}
    if user is None:
        r['marcaje'] = out
        return
    desde, hasta = r['desde'], r['hasta']
    ini = timezone.make_aware(timezone.datetime.combine(desde, timezone.datetime.min.time()))
    fin = timezone.make_aware(timezone.datetime.combine(hasta + timedelta(days=1),
                                                         timezone.datetime.min.time()))
    regs = list(RegistroAsistencia.objects.filter(
        user=user, fecha_hora__gte=ini, fecha_hora__lt=fin,
        estado__in=('PUNTUAL', 'TARDANZA')).order_by('fecha_hora'))
    if not regs:
        r['marcaje'] = {'disponible': False,
                        'motivo': 'No hay marcajes de asistencia en este período.'}
        return

    por_dia = defaultdict(list)
    for g in regs:
        por_dia[timezone.localtime(g.fecha_hora).date()].append(g)

    min_presencia = 0
    entradas = tardanzas = min_tard = 0
    detalle = {}
    for d, lst in por_dia.items():
        abierta = None
        m_dia = 0
        for g in lst:
            t = timezone.localtime(g.fecha_hora)
            if g.tipo == 'ENTRADA':
                entradas += 1
                if g.estado == 'TARDANZA':
                    tardanzas += 1
                    min_tard += g.minutos_tardanza or 0
                abierta = t
            elif g.tipo == 'SALIDA' and abierta:
                m_dia += max(int((t - abierta).total_seconds() // 60), 0)
                abierta = None
        min_presencia += m_dia
        detalle[d] = m_dia

    dias_horario = [x for x in r['por_dia'] if x['cap'] and x['transcurrido']]
    sin_marcaje = [x for x in dias_horario if x['fecha'] not in por_dia]
    min_atendido = sum(x['att_tot'] for x in r['por_dia'] if x['fecha'] in detalle)
    r['marcaje'] = {
        'disponible': True,
        'dias_marcados': len(por_dia), 'dias_horario': len(dias_horario),
        'dias_sin_marcaje': len(sin_marcaje),
        'sin_marcaje_fechas': [x['fecha'] for x in sin_marcaje][:15],
        'entradas': entradas, 'tardanzas': tardanzas, 'min_tardanza': min_tard,
        'tardanza_prom': round(min_tard / tardanzas) if tardanzas else 0,
        'puntualidad': _pct(entradas - tardanzas, entradas),
        'presencia_txt': hm(min_presencia), 'presencia_min': min_presencia,
        'atendido_txt': hm(min_atendido),
        'uso_presencia': _pct(min_atendido, min_presencia),   # % de su presencia con pacientes
        'ocioso_txt': hm(max(min_presencia - min_atendido, 0)),
    }


# ─────────────────────────────────────────────────────────────────────
# 4. COMPARACIÓN CON EL EQUIPO
# ─────────────────────────────────────────────────────────────────────
def equipo(prof, r, args):
    from profesionales.models import Profesional
    from .reporte_profesional_data import analizar

    filas = []
    otros = (Profesional.objects.filter(activo=True).exclude(id=prof.id)
             .order_by('apellido', 'nombre')[:40])
    for p in list(otros) + [prof]:
        try:
            x = r if p.id == prof.id else analizar(
                p, r['desde'], r['hasta'], sucursal_id=args['sucursal_id'],
                manual_cfg=args['manual_cfg'], hoy=r['hoy'], comparar=False, completo=False)
        except Exception:
            continue
        k = x['kpis']
        if not (k['cap_el'] or k['atendidas']):
            continue
        filas.append({
            'id': p.id, 'nombre': p.nombre_completo, 'especialidad': p.especialidad,
            'yo': p.id == prof.id, 'gen': k['gen_total'], 'horas': k['horas_reloj'],
            'horas_txt': k['horas_reloj_txt'], 'ocup': k['ocup_efect'],
            'ingreso_hora': k['ingreso_hora'], 'faltas': k['tasa_faltas'],
            'atendidas': k['atendidas'], 'pacientes': k['pacientes'],
            'cap': k['cap_el'],
        })
    filas.sort(key=lambda x: -x['gen'])
    for i, f in enumerate(filas, 1):
        f['pos'] = i

    def prom(lst, key, cond=lambda f: True):
        v = [f[key] for f in lst if cond(f)]
        return round(sum(v) / len(v), 2) if v else 0.0

    otros_l = [f for f in filas if not f['yo']]
    mi_esp = prof.especialidad
    misma = [f for f in otros_l if f['especialidad'] == mi_esp]
    r['equipo'] = {
        'filas': filas,
        'n': len(filas),
        'prom_ocup': prom(otros_l, 'ocup', lambda f: f['cap'] > 0),
        'prom_ingreso_hora': prom(otros_l, 'ingreso_hora', lambda f: f['horas'] > 0),
        'prom_faltas': prom(otros_l, 'faltas'),
        'prom_gen': prom(otros_l, 'gen'),
        'misma_esp': len(misma), 'especialidad': mi_esp,
        'prom_ingreso_hora_esp': prom(misma, 'ingreso_hora', lambda f: f['horas'] > 0),
        'mi_pos': next((f['pos'] for f in filas if f['yo']), None),
    }


# ─────────────────────────────────────────────────────────────────────
# 6. TENDENCIA DE 6 MESES
# ─────────────────────────────────────────────────────────────────────
def tendencia(prof, r, args):
    from .reporte_profesional_data import analizar

    hoy = r['hoy']
    ref = min(r['hasta'], hoy) if r['hasta'] >= r['desde'] else hoy
    y, m = ref.year, ref.month - 5
    while m <= 0:
        m += 12
        y -= 1
    ini = date(y, m, 1)
    fin = (ref.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    try:
        x = analizar(prof, ini, fin, sucursal_id=args['sucursal_id'], manual_cfg=args['manual_cfg'],
                     hoy=hoy, comparar=False, completo=False)
    except Exception:
        r['tendencia'] = None
        return
    meses = []
    for g in x['por_mes']:
        completo = (g['key'][0], g['key'][1]) != (hoy.year, hoy.month) and \
            date(g['key'][0], g['key'][1], 1) < hoy.replace(day=1)
        meses.append({
            'label': g['label'], 'gen': g['gen'], 'ocup': g['ocup_efect'],
            'atend': g['n_atend'], 'faltas': g['n_falta'], 'horas': round(g['att_tot'] / 60, 1),
            'cap_el': g['cap_el'], 'completo': completo,
        })
    base = [m_ for m_ in meses if m_['completo'] and m_['cap_el'] > 0]
    # Meses previos a que el profesional tuviera actividad no son "producción baja": se descartan
    while base and not (base[0]['gen'] > 0 or base[0]['atend'] > 0):
        base.pop(0)
    direccion, pend_pct, txt = 'sin_datos', 0.0, 'Aún no hay meses completos suficientes para medir tendencia.'
    if len(base) >= 3:
        n = len(base)
        xs = list(range(n))
        ys = [b['gen'] for b in base]
        mx, my = sum(xs) / n, sum(ys) / n
        den = sum((a - mx) ** 2 for a in xs)
        slope = sum((a - mx) * (b - my) for a, b in zip(xs, ys)) / den if den else 0
        pend_pct = round(slope / my * 100, 1) if my else 0.0
        if pend_pct >= 5:
            direccion, txt = 'sube', f'Su producción viene SUBIENDO (~{pend_pct}% por mes).'
        elif pend_pct <= -5:
            direccion, txt = 'baja', f'Su producción viene BAJANDO (~{abs(pend_pct)}% por mes).'
        else:
            direccion, txt = 'estable', 'Su producción se mantiene ESTABLE.'
    r['tendencia'] = {'meses': meses, 'direccion': direccion, 'pendiente': pend_pct, 'txt': es_num(txt),
                      'n_base': len(base)}


# ─────────────────────────────────────────────────────────────────────
# 7. RETENCIÓN DE PACIENTES
# ─────────────────────────────────────────────────────────────────────
def retencion(prof, r, args):
    from agenda.models import Sesion
    from pacientes.models import Paciente

    desde, hasta, hoy = r['desde'], r['hasta'], r['hoy']
    corte = min(hasta, hoy)
    qs = Sesion.objects.filter(profesional=prof, fecha__lte=max(hasta, hoy)).values_list(
        'paciente_id', 'fecha', 'estado').order_by('fecha')
    if args['sucursal_id']:
        qs = qs.filter(sucursal_id=args['sucursal_id'])
    hist = defaultdict(list)
    for pid, f, est in qs:
        hist[pid].append((f, est))

    nuevos, activos, riesgo, previos, retenidos = [], [], [], set(), set()
    largo = (hasta - desde).days + 1
    prev_d, prev_h = desde - timedelta(days=largo), desde - timedelta(days=1)
    seguidas = []
    for pid, lst in hist.items():
        atend = [f for f, e in lst if e in ATENDIDAS]
        if atend and desde <= atend[0] <= hasta:
            nuevos.append(pid)
        if any(corte - timedelta(days=30) <= f <= corte for f in atend):
            activos.append(pid)
        elif any(corte - timedelta(days=120) <= f < corte - timedelta(days=30) for f in atend) \
                and not any(f > hoy and e == 'programada' for f, e in lst):
            riesgo.append(pid)
        if any(prev_d <= f <= prev_h for f in atend):
            previos.add(pid)
            if any(desde <= f <= hasta for f in atend):
                retenidos.add(pid)
        cons = [e for f, e in lst if e in CONSUMIDAS + ('permiso',) and f <= corte]
        n = 0
        for e in reversed(cons):
            if e == 'falta':
                n += 1
            else:
                break
        if n >= 2:
            seguidas.append((pid, n))

    ids = set(nuevos) | set(riesgo) | {p for p, _ in seguidas}
    nom = {p.id: f"{p.nombre} {p.apellido}" for p in Paciente.objects.filter(id__in=ids)}
    ult = {}
    for pid in riesgo:
        a = [f for f, e in hist[pid] if e in ATENDIDAS]
        ult[pid] = a[-1] if a else None
    r['retencion'] = {
        'nuevos': len(nuevos), 'activos': len(activos),
        'nuevos_lista': sorted(nom.get(p, '—') for p in nuevos)[:12],
        'riesgo': len(riesgo),
        'riesgo_lista': [{'nombre': nom.get(p, '—'), 'ultima': ult.get(p)} for p in riesgo][:12],
        'seguidas': [{'nombre': nom.get(p, '—'), 'n': n} for p, n in sorted(seguidas, key=lambda x: -x[1])][:12],
        'previos': len(previos), 'retenidos': len(retenidos),
        'tasa_retencion': _pct(len(retenidos), len(previos)) if previos else None,
        'prev_desde': prev_d, 'prev_hasta': prev_h,
        'dejaron': len(previos) - len(retenidos),
    }


# ─────────────────────────────────────────────────────────────────────
# 8. CONCENTRACIÓN DE INGRESOS
# ─────────────────────────────────────────────────────────────────────
def concentracion(r):
    total = r['kpis']['gen_total']
    pacs = sorted(r['pacientes'], key=lambda p: -p['gen'])
    top = [{'nombre': p['nombre'], 'gen': p['gen'], 'pct': _pct(p['gen'], total)} for p in pacs[:5]]
    t1 = top[0]['pct'] if top else 0.0
    t3 = round(sum(x['pct'] for x in top[:3]), 1)
    if not total:
        nivel = 'sin_datos'
    elif t1 >= 40 or t3 >= 75:
        nivel = 'alto'
    elif t1 >= 25 or t3 >= 55:
        nivel = 'medio'
    else:
        nivel = 'bajo'
    r['concentracion'] = {'top': top, 'top1': t1, 'top3': t3, 'nivel': nivel,
                          'n_pacientes': len([p for p in pacs if p['gen'] > 0])}


# ─────────────────────────────────────────────────────────────────────
# 9. NOTAS CLÍNICAS
# ─────────────────────────────────────────────────────────────────────
def notas(r):
    att = [f for f in r['filas'] if f['estado'] in ATENDIDAS]
    con = [f for f in att if f.get('tiene_nota')]
    sin = [f for f in att if not f.get('tiene_nota')]
    por_pac = defaultdict(int)
    for f in sin:
        por_pac[f['paciente']] += 1
    r['notas'] = {
        'atendidas': len(att), 'con_nota': len(con), 'sin_nota': len(sin),
        'pct': _pct(len(con), len(att)),
        'sin_por_paciente': sorted(({'nombre': k, 'n': v} for k, v in por_pac.items()),
                                   key=lambda x: -x['n'])[:10],
        'sin_recientes': [{'fecha': f['fecha'], 'paciente': f['paciente'], 'servicio': f['servicio']}
                          for f in sorted(sin, key=lambda x: x['fecha'], reverse=True)[:12]],
    }


# ─────────────────────────────────────────────────────────────────────
# 5. SEMÁFORO DE DECISIÓN
# ─────────────────────────────────────────────────────────────────────
INFO_CRITERIOS = {
    'Ocupación efectiva': "Horas realmente trabajadas con pacientes ÷ horas de su horario ya transcurrido. No cuenta faltas ni sesiones programadas sin registrar. Peso 1,5.",
    'Ingreso por hora vs equipo': "Total generado ÷ horas trabajadas del profesional, comparado con el promedio del resto del equipo en el mismo período. Se mide en % del promedio. Peso 1.",
    'Faltas sin aviso de sus pacientes': "Faltas sin aviso ÷ (atendidas + faltas + permisos). Solo se evalúa con 5 o más sesiones. Una tasa alta puede indicar problemas de adherencia de las familias. Peso 0,75.",
    'Cobertura de su costo': "Aporte al centro ÷ costo del profesional en el período. Aporte = total generado (menos comisión si es servicio externo). Costo = costo mensual ingresado × días ÷ 30,4. Solo aparece si ingresas el costo mensual. Peso 2.",
    'Producción efectivamente cobrada': "Dinero cobrado ÷ dinero generado. Mide si lo que produce se transforma en ingreso real para el centro. Peso 0,75.",
    'Tendencia de producción (6 meses)': "Pendiente de la recta que mejor ajusta el dinero generado por mes en meses completos, como % del promedio mensual. Requiere al menos 3 meses con actividad. Peso 1.",
    'Retención de pacientes': "De los niños atendidos en el período anterior (de igual duración), cuántos también fueron atendidos en este. Se evalúa con 3 o más niños previos. Peso 1.",
    'Puntualidad de ingreso': "Entradas marcadas como puntuales ÷ total de entradas marcadas en Asistencia. Peso 0,5.",
    'Dependencia de pocos pacientes': "Peso de los 1 y 3 niños que más generan sobre el total. Verde: reparto sano; ámbar: el mayor ≥ 25% o los 3 mayores ≥ 55%; rojo: el mayor ≥ 40% o los 3 mayores ≥ 75%. Peso 0,5.",
    'Notas de evolución registradas': "Sesiones atendidas con nota de evolución ÷ sesiones atendidas. Se evalúa con 5 o más sesiones. Peso 0,5.",
}


def semaforo(r):
    k = r['kpis']
    crit = []

    def add(nombre, valor_txt, estado, regla, peso=1.0, detalle=''):
        crit.append({'nombre': nombre, 'valor': es_num(valor_txt), 'estado': estado,
                     'color': COLOR[estado], 'regla': es_num(regla), 'peso': peso,
                     'detalle': es_num(detalle), 'info': INFO_CRITERIOS.get(nombre, '')})

    def nivel(v, verde, ambar, mayor_mejor=True):
        if mayor_mejor:
            return VERDE if v >= verde else (AMBAR if v >= ambar else ROJO)
        return VERDE if v <= verde else (AMBAR if v <= ambar else ROJO)

    if k['cap_el']:
        add('Ocupación efectiva', f"{k['ocup_efect']}%", nivel(k['ocup_efect'], 60, 35),
            'Verde ≥ 60% · Ámbar 35–60% · Rojo < 35%',
            1.5, 'Horas realmente trabajadas con pacientes ÷ horas de su horario transcurrido.')
    eq = r.get('equipo')
    if eq and eq['prom_ingreso_hora'] and k['horas_reloj']:
        rel = k['ingreso_hora'] / eq['prom_ingreso_hora'] * 100
        add('Ingreso por hora vs equipo', f"Bs. {k['ingreso_hora']:,.0f}/h ({rel:.0f}% del promedio)",
            nivel(rel, 90, 70), 'Verde ≥ 90% del promedio · Ámbar 70–90% · Rojo < 70%', 1.0,
            f"Promedio del resto del equipo: Bs. {eq['prom_ingreso_hora']:,.2f} por hora.")
    base = k['atendidas'] + k['faltas'] + k['permisos']
    if base >= 5:
        add('Faltas sin aviso de sus pacientes', f"{k['tasa_faltas']}%",
            nivel(k['tasa_faltas'], 10, 20, mayor_mejor=False),
            'Verde ≤ 10% · Ámbar 10–20% · Rojo > 20%', 0.75,
            'Una tasa alta puede indicar problema de adherencia o de manejo de familias.')
    if k.get('costo_periodo'):
        add('Cobertura de su costo', f"{k['cobertura']}× (margen Bs. {k['margen']:,.0f})",
            nivel(k['cobertura'], 1.3, 1.0), 'Verde ≥ 1,3× · Ámbar 1–1,3× · Rojo < 1×', 2.0,
            f"Aporta Bs. {k['neto_centro']:,.0f} al centro frente a un costo de Bs. {k['costo_periodo']:,.0f}.")
    cb = r.get('cobranza')
    if cb and cb['generado']:
        add('Producción efectivamente cobrada', f"{cb['pct']}%", nivel(cb['pct'], 80, 60),
            'Verde ≥ 80% · Ámbar 60–80% · Rojo < 60%', 0.75,
            f"Bs. {cb['pendiente']:,.0f} generados siguen sin cobrarse.")
    tn = r.get('tendencia')
    if tn and tn['direccion'] != 'sin_datos':
        est = {'sube': VERDE, 'estable': AMBAR, 'baja': ROJO}[tn['direccion']]
        add('Tendencia de producción (6 meses)', f"{tn['pendiente']:+}% por mes", est,
            'Verde: sube ≥ 5% · Ámbar: estable · Rojo: baja ≥ 5%', 1.0, tn['txt'])
    rt = r.get('retencion')
    if rt and rt['tasa_retencion'] is not None and rt['previos'] >= 3:
        add('Retención de pacientes', f"{rt['tasa_retencion']}%", nivel(rt['tasa_retencion'], 75, 55),
            'Verde ≥ 75% · Ámbar 55–75% · Rojo < 55%', 1.0,
            f"De {rt['previos']} pacientes del período anterior, {rt['retenidos']} siguen en este.")
    mk = r.get('marcaje')
    if mk and mk.get('disponible') and mk['entradas']:
        add('Puntualidad de ingreso', f"{mk['puntualidad']}%", nivel(mk['puntualidad'], 90, 75),
            'Verde ≥ 90% · Ámbar 75–90% · Rojo < 75%', 0.5,
            f"{mk['tardanzas']} tardanzas en {mk['entradas']} ingresos marcados.")
    cn = r.get('concentracion')
    if cn and cn['nivel'] != 'sin_datos':
        est = {'bajo': VERDE, 'medio': AMBAR, 'alto': ROJO}[cn['nivel']]
        add('Dependencia de pocos pacientes', f"Top 1: {cn['top1']}% · Top 3: {cn['top3']}%", est,
            'Verde: reparto sano · Ámbar: top1 ≥ 25% · Rojo: top1 ≥ 40%', 0.5,
            'Si dos o tres niños se van, ¿cuánto de su producción se cae?')
    nt = r.get('notas')
    if nt and nt['atendidas'] >= 5:
        add('Notas de evolución registradas', f"{nt['pct']}%", nivel(nt['pct'], 85, 60),
            'Verde ≥ 85% · Ámbar 60–85% · Rojo < 60%', 0.5,
            f"{nt['sin_nota']} sesiones atendidas sin nota clínica.")

    pesos = sum(c['peso'] for c in crit)
    score = sum(PUNTOS[c['estado']] * c['peso'] for c in crit) / pesos if pesos else None
    if score is None:
        veredicto, color, msg = 'sin_datos', '#64748b', 'No hay datos suficientes para un veredicto.'
    elif score >= 0.75:
        veredicto, color = 'solido', '#16a34a'
        msg = 'Rendimiento SÓLIDO: aporta valor al centro y cumple la mayoría de los criterios.'
    elif score >= 0.5:
        veredicto, color = 'aceptable', '#d97706'
        msg = 'Rendimiento ACEPTABLE con observaciones: conviene revisar los criterios en rojo/ámbar.'
    elif score >= 0.3:
        veredicto, color = 'bajo', '#ea580c'
        msg = 'Rendimiento BAJO: se recomienda un plan de mejora con metas y revisión a 30–60 días.'
    else:
        veredicto, color = 'critico', '#dc2626'
        msg = 'Rendimiento CRÍTICO: revisar la continuidad o reestructurar su agenda y pacientes.'
    r['semaforo'] = {
        'criterios': crit, 'score': round(score * 100) if score is not None else None,
        'veredicto': veredicto, 'color': color, 'msg': msg,
        'n_verde': sum(1 for c in crit if c['estado'] == VERDE),
        'n_ambar': sum(1 for c in crit if c['estado'] == AMBAR),
        'n_rojo': sum(1 for c in crit if c['estado'] == ROJO),
        'faltan_costo': not k.get('costo_periodo'),
        'nota': 'Veredicto orientativo, calculado con los criterios visibles; la decisión final es del dueño.',
    }


# ─────────────────────────────────────────────────────────────────────
def enriquecer(prof, r, args):
    """Orquesta todos los complementos sobre el dict ya calculado."""
    for fn in (lambda: cobranza(r), lambda: marcaje(prof, r), lambda: equipo(prof, r, args),
               lambda: tendencia(prof, r, args), lambda: retencion(prof, r, args),
               lambda: concentracion(r), lambda: notas(r)):
        try:
            fn()
        except Exception:
            import logging
            logging.getLogger(__name__).exception('Complemento de reporte profesional falló')
    try:
        semaforo(r)
    except Exception:
        r['semaforo'] = None
    return r
