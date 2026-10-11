# facturacion/reporte_asistencia_data.py
# =====================================================================
# MOTOR DE ANÁLISIS DEL REPORTE DE ASISTENCIA (capa «decisión» para la dirección)
# Lo usan la pantalla y el PDF, para que ambos muestren exactamente los mismos números.
#
# CRITERIOS
#   · Base de asistencia = realizadas + con retraso + faltas sin aviso + permisos.
#     Canceladas por el centro, reprogramadas y programadas NO entran en la base.
#   · Asistencia = (realizadas + con retraso) / base.   Puntualidad = realizadas / atendidas.
#   · «Cancelada» se interpreta como cancelada por el centro (responsabilidad del centro).
#   · Cada tabla de ranking (profesional / sucursal / servicio) respeta todos los filtros
#     MENOS el de su propia dimensión, para no perder el contexto de comparación: si se
#     filtra un profesional, igual se ve cómo está frente a sus colegas.
#   · Comparación: período anterior de igual duración y mismos filtros; y el centro completo.
#   · Riesgo de abandono por paciente: usa los últimos 120 días (no depende del rango).
# =====================================================================
import logging
from collections import Counter, defaultdict
from datetime import date, timedelta

from .reporte_paciente_data import _metricas
from .reporte_profesional_data import ATENDIDAS, DIAS_CORTO, DIAS_ES, MESES_ES, _f, _pct, hm

logger = logging.getLogger(__name__)

OBJETIVO = 85.0        # asistencia objetivo (verde)
MINIMO = 70.0          # por debajo: rojo
OBJ_PUNT = 80.0        # puntualidad objetivo
MAX_CANCEL_CENTRO = 5.0  # % de sesiones canceladas por el centro tolerable
MIN_BASE = 10          # sesiones mínimas para juzgar a un profesional/servicio/sucursal
VENTANA_RIESGO = 120   # días de historial para riesgo de abandono
NO_REALIZADAS = ('falta', 'permiso', 'cancelada', 'reprogramada')
CAUSAS = (
    ('falta', 'Falta sin aviso', '#dc2626'),
    ('permiso', 'Permiso (con aviso)', '#8b5cf6'),
    ('cancelada', 'Cancelada por el centro', '#64748b'),
    ('reprogramada', 'Reprogramada', '#0d9488'),
)


# ─────────────────────────────────────────────────────────────────────
# FILTROS
# ─────────────────────────────────────────────────────────────────────
def normalizar_filtros(tipo, entidad_id, sucursal='', profesional='', servicio='', mensualidad='', proyecto=''):
    """Une el filtro de «vista» (entidad) con los filtros transversales, sin duplicar ni contradecir.
    La entidad elegida manda sobre el filtro transversal de su misma dimensión; si no hay entidad
    pero sí filtro transversal, ese filtro se toma como la entidad de la vista."""
    f = {'sucursal': sucursal or '', 'profesional': profesional or '', 'servicio': servicio or '',
         'paciente': '', 'mensualidad': mensualidad or '', 'proyecto': proyecto or ''}
    ent = str(entidad_id or '')
    if tipo in ('profesional', 'sucursal', 'servicio', 'paciente'):
        if ent:
            f[tipo] = ent
        elif tipo != 'paciente' and f[tipo]:
            ent = f[tipo]
    return f, ent


def _pasa(r, f):
    if f.get('sucursal') and str(r['suc_id']) != str(f['sucursal']):
        return False
    if f.get('profesional') and str(r['pid']) != str(f['profesional']):
        return False
    if f.get('servicio') and str(r['sid']) != str(f['servicio']):
        return False
    if f.get('paciente') and str(r['pac_id']) != str(f['paciente']):
        return False
    if f.get('mensualidad') and str(r['mensualidad_id'] or '') != str(f['mensualidad']):
        return False
    if f.get('proyecto') and str(r['proyecto_id'] or '') != str(f['proyecto']):
        return False
    return True


def _sin(f, dim):
    g = dict(f)
    g[dim] = ''
    return g


# ─────────────────────────────────────────────────────────────────────
# CARGA (una sola consulta)
# ─────────────────────────────────────────────────────────────────────
def _cargar(ini, fin):
    from agenda.models import Sesion
    rows = []
    for x in Sesion.objects.filter(fecha__gte=ini, fecha__lte=fin).order_by('fecha', 'hora_inicio').values(
            'id', 'fecha', 'hora_inicio', 'estado', 'servicio_id', 'servicio__nombre', 'profesional_id',
            'profesional__nombre', 'profesional__apellido', 'profesional__activo', 'sucursal_id', 'sucursal__nombre',
            'paciente_id', 'paciente__nombre', 'paciente__apellido', 'paciente__estado', 'duracion_minutos',
            'minutos_retraso', 'proyecto_id', 'mensualidad_id'):
        rows.append({
            'id': x['id'], 'fecha': x['fecha'], 'hora': x['hora_inicio'].hour if x['hora_inicio'] else 0,
            'estado': x['estado'], 'sid': x['servicio_id'], 'servicio': x['servicio__nombre'] or '—',
            'pid': x['profesional_id'], 'prof': f"{x['profesional__nombre'] or ''} {x['profesional__apellido'] or ''}".strip(),
            'prof_activo': bool(x['profesional__activo']), 'suc_id': x['sucursal_id'], 'suc': x['sucursal__nombre'] or '—',
            'pac_id': x['paciente_id'], 'pac': f"{x['paciente__nombre'] or ''} {x['paciente__apellido'] or ''}".strip(),
            'pac_activo': x['paciente__estado'] == 'activo', 'dur': x['duracion_minutos'] or 0,
            'retraso': x['minutos_retraso'] or 0, 'proyecto_id': x['proyecto_id'], 'mensualidad_id': x['mensualidad_id'],
        })
    return rows


def _en(rows, d, h):
    return [r for r in rows if d <= r['fecha'] <= h]


# ─────────────────────────────────────────────────────────────────────
# PIEZAS
# ─────────────────────────────────────────────────────────────────────
def _nivel(asis, base, cancel_pct=0.0):
    """Semáforo de una fila: color según asistencia (y cancelaciones del centro)."""
    if base < MIN_BASE:
        return 'gris'
    if asis < MINIMO or cancel_pct >= MAX_CANCEL_CENTRO * 2:
        return 'rojo'
    if asis < OBJETIVO or cancel_pct >= MAX_CANCEL_CENTRO:
        return 'ambar'
    return 'verde'


def _tabla(rows, prev_rows, clave, nombre, centro_asis, sel_id=None):
    """Agrupa y calcula métricas por entidad. clave/nombre son funciones sobre la fila."""
    grupos, gprev = defaultdict(list), defaultdict(list)
    nom = {}
    for r in rows:
        k = clave(r)
        grupos[k].append(r)
        nom[k] = nombre(r)
    for r in prev_rows:
        gprev[clave(r)].append(r)
    out = []
    hoy = date.today()
    for k, lst in grupos.items():
        M = _metricas(lst)
        P = _metricas(gprev.get(k, []))
        tot_ses = M['total'] or 1
        cancel_pct = _pct(M['canceladas'], tot_ses)
        pacs = {r['pac_id'] for r in lst if r['estado'] in ATENDIDAS}
        vencidas = sum(1 for r in lst if r['estado'] == 'programada' and r['fecha'] < hoy)
        delta = round(M['tasa_asistencia'] - P['tasa_asistencia'], 1) if (M['base'] >= 5 and P['base'] >= 5) else None
        out.append({
            'id': k, 'nombre': nom[k], 'M': M, 'sesiones': M['total'], 'base': M['base'], 'atendidas': M['atendidas'],
            'asistencia': M['tasa_asistencia'], 'puntualidad': M['puntualidad'], 'faltas': M['faltas'],
            'tasa_faltas': M['tasa_faltas'], 'permisos': M['permisos'], 'canceladas': M['canceladas'],
            'cancel_pct': cancel_pct, 'reprogramadas': M['reprogramadas'], 'programadas': M['programadas'],
            'horas': hm(M['min']), 'pacientes': len(pacs), 'vencidas': vencidas, 'delta': delta,
            'vs_centro': round(M['tasa_asistencia'] - centro_asis, 1) if M['base'] >= MIN_BASE else None,
            'nivel': _nivel(M['tasa_asistencia'], M['base'], cancel_pct),
            'sel': sel_id is not None and str(k) == str(sel_id),
            'activo': all(r.get('prof_activo', True) for r in lst) if clave.__name__ == '_k_prof' else True,
        })
    elegibles = sorted([x for x in out if x['base'] >= MIN_BASE], key=lambda x: (-x['asistencia'], -x['base']))
    resto = sorted([x for x in out if x['base'] < MIN_BASE], key=lambda x: (-x['base'], x['nombre']))
    for i, x in enumerate(elegibles, 1):
        x['rank'] = i
    for x in resto:
        x['rank'] = None
    return {'filas': elegibles + resto, 'n_rank': len(elegibles)}


def _k_prof(r):
    return r['pid']


def _k_suc(r):
    return r['suc_id']


def _k_serv(r):
    return r['sid']


def _serie(rows, desde, hasta):
    """Evolución: por día (≤31 días), por semana (≤180) o por mes."""
    dias = (hasta - desde).days + 1
    g = defaultdict(list)
    for r in rows:
        f = r['fecha']
        if dias <= 31:
            k, lab = f, f.strftime('%d/%m')
        elif dias <= 180:
            k = f - timedelta(days=f.weekday())
            lab = k.strftime('%d/%m')
        else:
            k, lab = date(f.year, f.month, 1), f"{MESES_ES[f.month][:3]} {str(f.year)[2:]}"
        g[k].append((lab, r))
    out = []
    for k in sorted(g):
        M = _metricas([r for _l, r in g[k]])
        out.append({'label': g[k][0][0], 'asistencia': M['tasa_asistencia'], 'base': M['base'], 'faltas': M['faltas'],
                    'permisos': M['permisos'], 'atendidas': M['atendidas'], 'canceladas': M['canceladas'],
                    'total': M['total']})
    return {'puntos': out, 'granularidad': 'día' if dias <= 31 else ('semana' if dias <= 180 else 'mes')}


def _bg_calor(inas, base):
    """Color de celda del mapa de calor según % de inasistencia (más opaco si hay pocos datos → más claro)."""
    if base < 3:
        return '#f1f5f9'
    if inas < 10:
        return '#bbf7d0'
    if inas < 20:
        return '#fef08a'
    if inas < 35:
        return '#fdba74'
    return '#fca5a5'


def _calor(rows):
    """Mapa día × hora: base y % de inasistencia (faltas + permisos) por celda."""
    cel = defaultdict(list)
    for r in rows:
        cel[(r['fecha'].weekday(), r['hora'])].append(r)
    horas = sorted({h for (_d, h) in cel})
    matriz = []
    criticas = []
    for d in range(7):
        fila = []
        for h in horas:
            lst = cel.get((d, h), [])
            M = _metricas(lst) if lst else None
            if M and M['base']:
                inas = _pct(M['faltas'] + M['permisos'], M['base'])
                fila.append({'base': M['base'], 'asis': M['tasa_asistencia'], 'inas': inas, 'bg': _bg_calor(inas, M['base'])})
                if M['base'] >= 5:
                    criticas.append({'dia': DIAS_ES[d], 'hora': f"{h:02d}:00", 'base': M['base'], 'asis': M['tasa_asistencia'],
                                     'inas': inas, 'faltas': M['faltas'], 'permisos': M['permisos']})
            else:
                fila.append(None)
        matriz.append({'dia': DIAS_CORTO[d], 'celdas': fila})
    criticas.sort(key=lambda x: (-x['inas'], -x['base']))
    return {'horas': [f"{h:02d}h" for h in horas], 'filas': matriz, 'criticas': criticas[:6],
            'mejores': sorted([c for c in criticas], key=lambda x: (-x['asis'], -x['base']))[:4]}


def _riesgo_pacientes(rows_hist, hoy):
    """Pacientes con rachas de inasistencia o que dejaron de venir (historial reciente)."""
    por_pac = defaultdict(list)
    for r in rows_hist:
        if r['fecha'] >= hoy - timedelta(days=VENTANA_RIESGO):
            por_pac[r['pac_id']].append(r)
    out = []
    for pid, lst in por_pac.items():
        if not lst[0]['pac_activo']:
            continue
        pas = sorted([r for r in lst if r['fecha'] < hoy and r['estado'] in ('realizada', 'realizada_retraso', 'falta', 'permiso')],
                     key=lambda r: (r['fecha'], r['hora']))
        if not pas:
            continue
        racha = 0
        for r in reversed(pas):
            if r['estado'] in ('falta', 'permiso'):
                racha += 1
            else:
                break
        asist = [r['fecha'] for r in pas if r['estado'] in ATENDIDAS]
        ult = max(asist) if asist else None
        dias_sin = (hoy - ult).days if ult else None
        fut = sum(1 for r in lst if r['estado'] == 'programada' and r['fecha'] >= hoy)
        fal30 = sum(1 for r in pas if r['estado'] == 'falta' and r['fecha'] >= hoy - timedelta(days=30))
        nivel = None
        if racha >= 3:
            nivel = 'alto'
        elif racha == 2 or (dias_sin is not None and dias_sin >= 21 and fut):
            nivel = 'medio'
        if nivel:
            profs = sorted({r['prof'] for r in lst if r['fecha'] >= hoy - timedelta(days=30)})
            out.append({'id': pid, 'nombre': lst[0]['pac'], 'racha': racha, 'ultima': ult, 'dias_sin': dias_sin,
                        'futuras': fut, 'faltas30': fal30, 'nivel': nivel, 'profs': ', '.join(profs[:2])})
    out.sort(key=lambda x: (0 if x['nivel'] == 'alto' else 1, -x['racha'], -(x['dias_sin'] or 0)))
    return out


def _pacientes(rows):
    por = defaultdict(list)
    for r in rows:
        por[r['pac_id']].append(r)
    mejores, criticos, retrasos = [], [], []
    for pid, lst in por.items():
        M = _metricas(lst)
        it = {'id': pid, 'nombre': lst[0]['pac'], 'total': M['total'], 'base': M['base'], 'atendidas': M['atendidas'],
              'faltas': M['faltas'], 'permisos': M['permisos'], 'asistencia': M['tasa_asistencia'],
              'tasa_faltas': M['tasa_faltas'], 'retrasos': M['retrasos'], 'retraso_prom': M['retraso_prom']}
        if M['base'] >= 5:
            mejores.append(it)
        if M['base'] >= 3 and M['tasa_faltas'] >= 20:
            criticos.append(it)
        if M['retrasos'] >= 2:
            retrasos.append(it)
    mejores.sort(key=lambda x: (-x['asistencia'], -x['base']))
    criticos.sort(key=lambda x: (-x['tasa_faltas'], -x['faltas']))
    retrasos.sort(key=lambda x: (-x['retraso_prom'], -x['retrasos']))
    return {'mejores': mejores[:10], 'criticos': criticos[:10], 'retrasos': retrasos[:10], 'n': len(por)}


# ─────────────────────────────────────────────────────────────────────
# DECISIONES
# ─────────────────────────────────────────────────────────────────────
def _decisiones(a):
    d = []
    M, P, C = a['M'], a['P'], a['C']
    add = lambda nivel, titulo, detalle, accion='': d.append({'nivel': nivel, 'titulo': titulo, 'detalle': detalle, 'accion': accion})

    if M['base'] < 5:
        add('info', 'Pocos datos para sacar conclusiones',
            f"Solo hay {M['base']} sesiones evaluables en el período y filtros elegidos.", 'Amplíe el rango de fechas para un análisis fiable.')
        return d

    t = M['tasa_asistencia']
    if t < MINIMO:
        add('alerta', f"Asistencia crítica: {t:.1f}%",
            f"Está por debajo del mínimo aceptable ({MINIMO:.0f}%). De {M['base']} sesiones evaluables, {M['faltas']} fueron faltas sin aviso y {M['permisos']} permisos.",
            'Reunión de dirección esta semana: confirmar todas las sesiones el día anterior y llamar a las familias con más faltas.')
    elif t < OBJETIVO:
        add('aviso', f"Asistencia por debajo del objetivo: {t:.1f}%",
            f"El objetivo es {OBJETIVO:.0f}%. Faltan {OBJETIVO - t:.1f} puntos; equivale a unas {max(int(M['base'] * (OBJETIVO - t) / 100), 1)} sesiones más asistidas en el período.",
            'Reforzar el recordatorio por WhatsApp (día anterior y 2 horas antes) y revisar las franjas con más inasistencia.')
    else:
        add('ok', f"Asistencia dentro del objetivo: {t:.1f}%", f"Cumple la meta de {OBJETIVO:.0f}%.", 'Mantener las prácticas actuales de confirmación.')

    if P['base'] >= 8:
        dl = round(t - P['tasa_asistencia'], 1)
        if dl <= -5:
            add('alerta' if dl <= -10 else 'aviso', f"La asistencia bajó {abs(dl):.1f} puntos",
                f"Pasó de {P['tasa_asistencia']:.1f}% en el período anterior a {t:.1f}% ahora.",
                'Identificar qué cambió (horarios, profesionales, época del año) antes de que se vuelva costumbre.')
        elif dl >= 5:
            add('ok', f"La asistencia mejoró {dl:.1f} puntos", f"Pasó de {P['tasa_asistencia']:.1f}% a {t:.1f}%.", 'Replicar lo que funcionó en estas semanas.')

    if M['tasa_faltas'] >= 10:
        add('aviso' if M['tasa_faltas'] < 15 else 'alerta', f"Faltas sin aviso: {M['tasa_faltas']:.1f}% de las sesiones evaluables",
            f"{M['faltas']} sesiones se perdieron sin aviso; el profesional estuvo disponible y no se pudo reasignar el horario.",
            'Política de confirmación obligatoria y aviso con 24 h; ofrecer el cupo a la lista de espera cuando haya un permiso.')

    if C and M['total'] >= 20 and _pct(M['canceladas'], M['total']) >= MAX_CANCEL_CENTRO:
        pc = _pct(M['canceladas'], M['total'])
        add('aviso' if pc < 10 else 'alerta', f"El centro canceló {pc:.1f}% de las sesiones ({M['canceladas']})",
            'Las cancelaciones del centro dañan la confianza de las familias y reducen ingresos.',
            'Revisar quién cancela y por qué (ausencias del profesional, falta de sala, feriados) y planificar con anticipación.')

    if M['atendidas'] >= 10 and M['puntualidad'] < OBJ_PUNT:
        add('aviso', f"Puntualidad baja: {M['puntualidad']:.1f}%",
            f"{M['retrasos']} llegadas con retraso (promedio {M['retraso_prom']:.0f} min); se pierde tiempo de terapia.",
            'Recordar el horario a las familias y evaluar si el tiempo entre sesiones consecutivas es realista.')

    if a['vencidas']['total']:
        v = a['vencidas']
        add('aviso', f"{v['total']} sesiones pasadas siguen como «Programada»",
            'Son sesiones cuya fecha ya pasó y nadie registró si el paciente asistió. Distorsionan este reporte y la facturación.',
            'Pedir a los profesionales con más pendientes que regularicen: ' + ', '.join(f"{n} ({c})" for n, c in v['top'][:3]) + '.')

    ctx = a['ranking']['prof']['filas']
    bajos = [x for x in ctx if x['base'] >= MIN_BASE and x['asistencia'] < MINIMO]
    if bajos:
        add('alerta', f"{len(bajos)} profesional(es) con asistencia crítica",
            '; '.join(f"{x['nombre']} {x['asistencia']:.0f}% ({x['base']} ses.)" for x in bajos[:5]),
            'Revisar con cada uno la composición de su agenda: pacientes con faltas reiteradas, horarios poco convenientes o servicios con baja adherencia.')
    canc = [x for x in ctx if x['sesiones'] >= MIN_BASE and x['cancel_pct'] >= MAX_CANCEL_CENTRO * 2]
    if canc:
        add('aviso', f"Profesionales con muchas cancelaciones del centro",
            '; '.join(f"{x['nombre']} {x['cancel_pct']:.0f}% ({x['canceladas']})" for x in canc[:4]),
            'Conversar sobre disponibilidad real y reasignar pacientes si es necesario.')

    suc = [x for x in a['ranking']['suc']['filas'] if x['base'] >= MIN_BASE]
    if len(suc) >= 2:
        mejor, peor = max(suc, key=lambda x: x['asistencia']), min(suc, key=lambda x: x['asistencia'])
        if mejor['asistencia'] - peor['asistencia'] >= 10:
            add('aviso', f"Diferencia de {mejor['asistencia'] - peor['asistencia']:.0f} puntos entre sucursales",
                f"{mejor['nombre']} {mejor['asistencia']:.0f}% frente a {peor['nombre']} {peor['asistencia']:.0f}%.",
                f"Llevar a {peor['nombre']} las prácticas de {mejor['nombre']} (recordatorios, trato con familias, horarios).")

    serv = [x for x in a['ranking']['serv']['filas'] if x['base'] >= MIN_BASE and x['asistencia'] < MINIMO]
    if serv:
        add('aviso', f"Servicios con baja adherencia ({len(serv)})",
            '; '.join(f"{x['nombre']} {x['asistencia']:.0f}%" for x in serv[:4]),
            'Revisar frecuencia indicada, horario ofrecido y comunicación del valor del servicio a las familias.')

    cr = a['calor']['criticas']
    if cr and cr[0]['inas'] >= 25:
        add('aviso', 'Franjas horarias con más inasistencia',
            '; '.join(f"{c['dia']} {c['hora']} ({c['inas']:.0f}% no asiste, {c['base']} ses.)" for c in cr[:3]),
            'Evitar agendar pacientes con historial de faltas en esas franjas, o confirmarlas de forma reforzada.')

    dias = [x for x in a['por_dia'] if x['base'] >= MIN_BASE]
    if len(dias) >= 3:
        peor = min(dias, key=lambda x: x['asistencia'])
        mejor = max(dias, key=lambda x: x['asistencia'])
        if mejor['asistencia'] - peor['asistencia'] >= 10:
            add('info', f"Día más débil: {peor['nombre']} ({peor['asistencia']:.0f}%)",
                f"El mejor día es {mejor['nombre']} con {mejor['asistencia']:.0f}%.", 'Considerar menos cupos o más confirmación ese día.')

    r = a['riesgo']
    altos = [x for x in r if x['nivel'] == 'alto']
    if r:
        add('alerta' if altos else 'aviso', f"{len(r)} paciente(s) con riesgo de abandono ({len(altos)} alto)",
            'Rachas de 3 o más inasistencias seguidas, o sin asistir hace 21+ días con sesiones agendadas.',
            'Llamar esta semana a las familias de la lista; ofrecer reprogramar o conversar sobre el obstáculo.')
    return d


# ─────────────────────────────────────────────────────────────────────
# ENTRADA PRINCIPAL
# ─────────────────────────────────────────────────────────────────────
def analizar_asistencia(desde, hasta, filtros, hoy=None):
    hoy = hoy or date.today()
    span = (hasta - desde).days + 1
    p_hasta = desde - timedelta(days=1)
    p_desde = p_hasta - timedelta(days=span - 1)
    ini = min(p_desde, hoy - timedelta(days=VENTANA_RIESGO))
    fin = max(hasta, hoy + timedelta(days=30))
    todas = _cargar(ini, fin)

    centro = _en(todas, desde, hasta)
    sel = [r for r in centro if _pasa(r, filtros)]
    prev = [r for r in _en(todas, p_desde, p_hasta) if _pasa(r, filtros)]
    prev_centro = _en(todas, p_desde, p_hasta)
    M, P, C = _metricas(sel), _metricas(prev), _metricas(centro)
    hay_filtro = any(filtros.get(k) for k in ('sucursal', 'profesional', 'servicio', 'paciente', 'mensualidad', 'proyecto'))

    a = {'desde': desde, 'hasta': hasta, 'p_desde': p_desde, 'p_hasta': p_hasta, 'hoy': hoy, 'filtros': filtros,
         'M': M, 'P': P, 'C': C if hay_filtro else None, 'hay_filtro': hay_filtro,
         'delta_asis': round(M['tasa_asistencia'] - P['tasa_asistencia'], 1) if (M['base'] >= 5 and P['base'] >= 5) else None,
         'vs_centro': round(M['tasa_asistencia'] - C['tasa_asistencia'], 1) if (hay_filtro and M['base'] >= 5 and C['base'] >= 5) else None,
         'nivel': _nivel(M['tasa_asistencia'], MIN_BASE if M['base'] >= 5 else 0)}

    # horas perdidas por causa
    tot_ses = M['total'] or 1
    perd, tot_min = [], 0
    for est, lab, col in CAUSAS:
        lst = [r for r in sel if r['estado'] == est]
        mi = sum(r['dur'] for r in lst)
        tot_min += mi
        perd.append({'estado': est, 'label': lab, 'color': col, 'n': len(lst), 'min': mi, 'horas': hm(mi), 'pct': _pct(len(lst), tot_ses)})
    a['perdidas'] = {'filas': perd, 'total_n': sum(x['n'] for x in perd), 'total_min': tot_min, 'total_horas': hm(tot_min),
                     'pct': _pct(sum(x['n'] for x in perd), tot_ses),
                     'aprovechado': hm(M['min']), 'pct_aprov': _pct(M['min'], M['min'] + tot_min)}

    # sesiones pasadas sin registrar
    venc = [r for r in sel if r['estado'] == 'programada' and r['fecha'] < hoy]
    cnt = Counter(r['prof'] for r in venc)
    a['vencidas'] = {'total': len(venc), 'top': cnt.most_common(8)}

    # puntualidad: tramos de retraso
    ret = [r['retraso'] for r in sel if r['estado'] == 'realizada_retraso']
    tr = (('Hasta 5 min', 0, 5), ('6 a 10 min', 6, 10), ('11 a 15 min', 11, 15), ('Más de 15 min', 16, 10 ** 6))
    a['tramos_retraso'] = [{'label': l, 'n': sum(1 for m in ret if lo <= m <= hi), 'pct': _pct(sum(1 for m in ret if lo <= m <= hi), len(ret))}
                           for l, lo, hi in tr]
    a['retraso_total_min'] = sum(ret)

    a['serie'] = _serie(sel, desde, hasta)
    a['serie_prev'] = {'asistencia': P['tasa_asistencia']}
    a['svg_evolucion'] = svg_evolucion(a['serie']['puntos'], P['tasa_asistencia'] if P['base'] >= 5 else None)
    a['por_dia'] = []
    for i in range(7):
        m = _metricas([r for r in sel if r['fecha'].weekday() == i])
        a['por_dia'].append({'nombre': DIAS_ES[i], 'corto': DIAS_CORTO[i], 'total': m['total'], 'base': m['base'],
                             'asistencia': m['tasa_asistencia'], 'faltas': m['faltas'], 'permisos': m['permisos'],
                             'canceladas': m['canceladas']})
    horas = defaultdict(list)
    for r in sel:
        horas[r['hora']].append(r)
    a['por_hora'] = []
    for h in sorted(horas):
        m = _metricas(horas[h])
        a['por_hora'].append({'hora': f"{h:02d}:00", 'total': m['total'], 'base': m['base'], 'asistencia': m['tasa_asistencia'],
                              'faltas': m['faltas'], 'permisos': m['permisos']})
    a['calor'] = _calor(sel)

    # rankings (contexto: respetan filtros menos su dimensión) y desgloses (dentro de la selección)
    a['ranking'], a['desglose'] = {}, {}
    for dim, kf, nf, campo in (('prof', _k_prof, lambda r: r['prof'], 'profesional'),
                               ('suc', _k_suc, lambda r: r['suc'], 'sucursal'),
                               ('serv', _k_serv, lambda r: r['servicio'], 'servicio')):
        f2 = _sin(filtros, campo)
        ctx = [r for r in centro if _pasa(r, f2)]
        ctx_prev = [r for r in prev_centro if _pasa(r, f2)]
        Mc = _metricas(ctx)
        a['ranking'][dim] = _tabla(ctx, ctx_prev, kf, nf, Mc['tasa_asistencia'], filtros.get(campo) or None)
        a['ranking'][dim]['promedio'] = Mc['tasa_asistencia']
        a['desglose'][dim] = _tabla(sel, prev, kf, nf, M['tasa_asistencia'])
        a['desglose'][dim]['promedio'] = M['tasa_asistencia']

    a['pacientes'] = _pacientes(sel)
    hist = [r for r in todas if _pasa(r, filtros)]
    a['riesgo'] = _riesgo_pacientes(hist, hoy)
    a['decisiones'] = _decisiones(a)
    orden = {'alerta': 0, 'aviso': 1, 'info': 2, 'ok': 3}
    a['decisiones'].sort(key=lambda x: orden[x['nivel']])
    a['n_alertas'] = sum(1 for x in a['decisiones'] if x['nivel'] == 'alerta')
    a['n_avisos'] = sum(1 for x in a['decisiones'] if x['nivel'] == 'aviso')
    return a


# ─────────────────────────────────────────────────────────────────────
# GRÁFICO SVG (pantalla): evolución de la asistencia con escala 0-100 %
# ─────────────────────────────────────────────────────────────────────
def svg_evolucion(puntos, prev_asis=None):
    """Barras de % de asistencia por tramo, con eje, cuadrícula, líneas de objetivo/mínimo y promedio previo.
    Se genera en el servidor: no depende de JavaScript ni del formato numérico regional (coma decimal)."""
    n = len(puntos)
    if not n:
        return ''
    W, H = 720, 292
    ml, mr, mt, mb = 42, 16, 22, 62
    pw_, ph = W - ml - mr, H - mt - mb
    slot = pw_ / n
    bw = max(6, min(38, slot * 0.64))
    Y = lambda v: mt + ph * (1 - max(0.0, min(v, 100.0)) / 100.0)
    o = [f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="Evolución de la asistencia" '
         f'style="display:block;max-width:100%;height:auto;font-family:\'Sora\',\'DM Sans\',sans-serif">']
    # cuadrícula y eje Y
    for v in (0, 25, 50, 75, 100):
        y = Y(v)
        o.append(f'<line x1="{ml}" y1="{y:.1f}" x2="{W - mr}" y2="{y:.1f}" stroke="#e2e8f0" stroke-width="1"/>')
        o.append(f'<text x="{ml - 7}" y="{y + 3.5:.1f}" text-anchor="end" font-size="10" fill="#64748b">{v}%</text>')
    # franjas de referencia
    o.append(f'<rect x="{ml}" y="{Y(100):.1f}" width="{pw_}" height="{Y(OBJETIVO) - Y(100):.1f}" fill="#059669" opacity="0.05"/>')
    o.append(f'<rect x="{ml}" y="{Y(MINIMO):.1f}" width="{pw_}" height="{Y(0) - Y(MINIMO):.1f}" fill="#be123c" opacity="0.05"/>')
    for v, col, lab in ((OBJETIVO, '#059669', f'Objetivo {OBJETIVO:.0f}%'), (MINIMO, '#be123c', f'Mínimo {MINIMO:.0f}%')):
        y = Y(v)
        o.append(f'<line x1="{ml}" y1="{y:.1f}" x2="{W - mr}" y2="{y:.1f}" stroke="{col}" stroke-width="1.2" stroke-dasharray="5 4"/>')
    # barras
    paso = 1 if n <= 14 else (2 if n <= 28 else 4)
    for i, pt in enumerate(puntos):
        cx = ml + slot * (i + 0.5)
        x = cx - bw / 2
        if pt['base'] <= 0:
            o.append(f'<text x="{cx:.1f}" y="{Y(0) - 6:.1f}" text-anchor="middle" font-size="9" fill="#94a3b8">–</text>')
        else:
            v = pt['asistencia']
            col = '#059669' if v >= OBJETIVO else ('#d97706' if v >= MINIMO else '#be123c')
            y = Y(v)
            h = max(Y(0) - y, 2)
            r = min(5, bw / 2, h)
            o.append(f'<path d="M{x:.1f},{Y(0):.1f} L{x:.1f},{y + r:.1f} Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f} L{x + bw - r:.1f},{y:.1f} '
                     f'Q{x + bw:.1f},{y:.1f} {x + bw:.1f},{y + r:.1f} L{x + bw:.1f},{Y(0):.1f} Z" fill="{col}">'
                     f'<title>{pt["label"]}: {v:.1f}% · {pt["base"]} evaluables · {pt["faltas"]} faltas · {pt["permisos"]} permisos</title></path>')
            if n <= 26 or i % paso == 0:
                o.append(f'<text x="{cx:.1f}" y="{y - 5:.1f}" text-anchor="middle" font-size="{10 if n <= 16 else 9}" font-weight="700" fill="#1e293b">{v:.0f}</text>')
        if i % paso == 0:
            o.append(f'<text x="{cx:.1f}" y="{H - mb + 15}" text-anchor="middle" font-size="{10 if n <= 16 else 9}" fill="#475569">{pt["label"]}</text>')
    # promedio del período anterior
    if prev_asis:
        y = Y(prev_asis)
        o.append(f'<line x1="{ml}" y1="{y:.1f}" x2="{W - mr}" y2="{y:.1f}" stroke="#2563eb" stroke-width="1.6" stroke-dasharray="2 3"/>')
    # leyenda
    leyenda = [('#059669', f'Objetivo {OBJETIVO:.0f}%', '5 4'), ('#be123c', f'Mínimo {MINIMO:.0f}%', '5 4')]
    if prev_asis:
        leyenda.append(('#2563eb', f'Período anterior {prev_asis:.1f}%', '2 3'))
    lx = ml + 6
    for col, txt, dash in leyenda:
        o.append(f'<line x1="{lx}" y1="{H - 12}" x2="{lx + 22}" y2="{H - 12}" stroke="{col}" stroke-width="1.8" stroke-dasharray="{dash}"/>')
        o.append(f'<text x="{lx + 28}" y="{H - 8.5}" font-size="10" fill="#475569">{txt}</text>')
        lx += 28 + len(txt) * 5.6 + 22
    o.append('</svg>')
    return ''.join(o)
