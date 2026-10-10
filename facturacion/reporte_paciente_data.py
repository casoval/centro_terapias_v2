# facturacion/reporte_paciente_data.py
# =====================================================================
# MOTOR DE ANÁLISIS DEL REPORTE POR PACIENTE (capa «decisión»)
# Se suma a lo que ya calcula la vista reporte_paciente (financiero, asistencia,
# proyectos, mensualidades, pagos…). Lo usan la pantalla y los PDF (interno y
# para la familia), para que ambos muestren exactamente los mismos números.
#
# CRITERIOS (iguales a los reportes por profesional y por sucursal):
#   · Generado (devengado) = sesiones individuales consumidas por su monto cobrado
#     (incluye la falta sin aviso) + parte ponderada de proyectos y mensualidades,
#     repartida por lo que costaría cada sesión como individual.
#   · «Cobrado» es otra cosa: dinero pagado, con su fecha (antes/durante/después).
#   · Riesgo y tendencia usan el HISTORIAL completo del paciente (no dependen del
#     rango ni de los filtros); el resto respeta rango y filtros.
#   · Umbrales de abandono: «en observación» a los 21 días sin sesión, «riesgo» a los 30
#     (configurables).
# =====================================================================
import calendar
import logging
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import date, timedelta

from django.db.models import Count, Sum

from .reporte_profesional_data import (
    ATENDIDAS, CONSUMIDAS, DIAS_CORTO, DIAS_ES, MESES_ES, es_num, hm, _f, _pct,
)
from .reporte_profesional_extra import AMBAR, COLOR, PUNTOS, ROJO, VERDE

logger = logging.getLogger(__name__)

UMBRAL_OBS = 21
UMBRAL_RIESGO = 30
BASE_ASIS = ('realizada', 'realizada_retraso', 'falta', 'permiso')
ESTADOS_TXT = {'programada': 'Programada', 'realizada': 'Realizada', 'realizada_retraso': 'Con retraso',
               'falta': 'Falta sin aviso', 'permiso': 'Permiso', 'cancelada': 'Cancelada',
               'reprogramada': 'Reprogramada'}
COLOR_EST = {'realizada': '#16a34a', 'realizada_retraso': '#f59e0b', 'falta': '#dc2626', 'permiso': '#8b5cf6',
             'cancelada': '#94a3b8', 'reprogramada': '#0d9488', 'programada': '#2563eb'}
PRIORIDAD_CAL = ('falta', 'permiso', 'realizada_retraso', 'realizada', 'cancelada', 'reprogramada', 'programada')
AGING = ((0, 7, '0 a 7 días'), (8, 30, '8 a 30 días'), (31, 60, '31 a 60 días'), (61, 10 ** 6, 'Más de 60 días'))


# ─────────────────────────────────────────────────────────────────────
# CARGA DE DATOS (una consulta por tabla)
# ─────────────────────────────────────────────────────────────────────
def _cargar_sesiones(paciente):
    from agenda.models import Sesion
    rows = []
    for x in Sesion.objects.filter(paciente=paciente).order_by('fecha', 'hora_inicio').values(
            'id', 'fecha', 'hora_inicio', 'estado', 'servicio_id', 'servicio__nombre', 'servicio__color',
            'servicio__costo_base', 'profesional_id', 'profesional__nombre', 'profesional__apellido',
            'sucursal_id', 'sucursal__nombre', 'proyecto_id', 'mensualidad_id', 'monto_cobrado',
            'monto_original', 'monto_previo_exencion', 'duracion_minutos', 'minutos_retraso',
            'observaciones', 'notas_sesion', 'motivo_reprogramacion'):
        rows.append({
            'id': x['id'], 'fecha': x['fecha'], 'hora': x['hora_inicio'].hour if x['hora_inicio'] else 0,
            'hora_txt': x['hora_inicio'].strftime('%H:%M') if x['hora_inicio'] else '',
            'estado': x['estado'], 'sid': x['servicio_id'], 'servicio': x['servicio__nombre'] or '—',
            'color': x['servicio__color'] or '#64748b', 'base': _f(x['servicio__costo_base']),
            'pid': x['profesional_id'], 'prof': f"{x['profesional__nombre'] or ''} {x['profesional__apellido'] or ''}".strip(),
            'suc_id': x['sucursal_id'], 'suc': x['sucursal__nombre'] or '',
            'proyecto_id': x['proyecto_id'], 'mensualidad_id': x['mensualidad_id'],
            'tipo': 'proyecto' if x['proyecto_id'] else ('mensualidad' if x['mensualidad_id'] else 'individual'),
            'monto': _f(x['monto_cobrado']), 'monto_orig': _f(x['monto_original']),
            'monto_exen': _f(x['monto_previo_exencion']), 'dur': x['duracion_minutos'] or 0,
            'retraso': x['minutos_retraso'] or 0, 'obs': (x['observaciones'] or '').strip(),
            'nota': (x['notas_sesion'] or '').strip(), 'motivo': (x['motivo_reprogramacion'] or '').strip(),
        })
    return rows


def _cargar_pagos(paciente):
    """Pagos por sesión / proyecto / mensualidad (directos y de pagos masivos), con su fecha."""
    from facturacion.models import DetallePagoMasivo, Pago
    out = {'sesion': defaultdict(list), 'proyecto': defaultdict(list), 'mensualidad': defaultdict(list)}
    for campo in ('sesion', 'proyecto', 'mensualidad'):
        for x in Pago.objects.filter(paciente=paciente, anulado=False, **{f'{campo}__isnull': False}).values(
                f'{campo}_id', 'fecha_pago', 'monto', 'metodo_pago__nombre'):
            out[campo][x[f'{campo}_id']].append((x['fecha_pago'], _f(x['monto']), x['metodo_pago__nombre']))
        for x in DetallePagoMasivo.objects.filter(pago__paciente=paciente, pago__anulado=False, tipo=campo,
                                                  **{f'{campo}__isnull': False}).values(
                f'{campo}_id', 'pago__fecha_pago', 'monto', 'pago__metodo_pago__nombre'):
            out[campo][x[f'{campo}_id']].append((x['pago__fecha_pago'], _f(x['monto']), x['pago__metodo_pago__nombre']))
    return out


def _cargar_paquetes(paciente):
    from agenda.models import Mensualidad, Proyecto
    proy = [{'id': p['id'], 'clave': 'proyecto', 'codigo': p['codigo'], 'nombre': p['nombre'], 'estado': p['estado'],
             'valor': _f(p['costo_total']), 'valor_orig': _f(p['costo_original']), 'ref': p['fecha_inicio'],
             'fin': p['fecha_fin_real'] or p['fecha_fin_estimada'], 'tipo': p['tipo'],
             'informe_entregado': p['informe_entregado'], 'fecha_entrega': p['fecha_entrega_informe']}
            for p in Proyecto.objects.filter(paciente=paciente).values(
                'id', 'codigo', 'nombre', 'estado', 'costo_total', 'costo_original', 'fecha_inicio',
                'fecha_fin_real', 'fecha_fin_estimada', 'tipo', 'informe_entregado', 'fecha_entrega_informe')]
    mens = [{'id': m['id'], 'clave': 'mensualidad', 'codigo': m['codigo'],
             'nombre': f"{MESES_ES[m['mes']]} {m['anio']}", 'estado': m['estado'], 'valor': _f(m['costo_mensual']),
             'valor_orig': _f(m['costo_original']), 'ref': date(m['anio'], m['mes'], 1), 'anio': m['anio'], 'mes': m['mes']}
            for m in Mensualidad.objects.filter(paciente=paciente).values(
                'id', 'codigo', 'mes', 'anio', 'costo_mensual', 'costo_original', 'estado')]
    return proy, mens


# ─────────────────────────────────────────────────────────────────────
# UTILIDADES
# ─────────────────────────────────────────────────────────────────────
def _asignar(pagos, monto):
    """Reparte cronológicamente hasta `monto` entre los pagos [(fecha, importe, método)]."""
    resto, out = monto, []
    for f, m, _mp in sorted(pagos, key=lambda x: x[0]):
        if resto <= 0.004:
            break
        t = min(m, resto)
        out.append((f, t))
        resto -= t
    return out


def _bucket(f, desde, hasta):
    if desde is None or hasta is None:
        return 'durante'
    return 'antes' if f < desde else ('durante' if f <= hasta else 'despues')


def _metricas(lista):
    """Conteos y tasas de una lista de sesiones (mismas fórmulas que el reporte actual)."""
    c = Counter(s['estado'] for s in lista)
    real, ret, fal, per = c['realizada'], c['realizada_retraso'], c['falta'], c['permiso']
    base = real + ret + fal + per
    atend = real + ret
    min_at = sum(s['dur'] for s in lista if s['estado'] in ATENDIDAS)
    return {
        'total': len(lista), 'realizadas': real, 'retrasos': ret, 'faltas': fal, 'permisos': per,
        'canceladas': c['cancelada'], 'reprogramadas': c['reprogramada'], 'programadas': c['programada'],
        'atendidas': atend, 'base': base, 'tasa_asistencia': _pct(atend, base), 'tasa_faltas': _pct(fal, base),
        'puntualidad': _pct(real, atend), 'min': min_at, 'horas_txt': hm(min_at),
        'retraso_prom': round(sum(s['retraso'] for s in lista if s['estado'] == 'realizada_retraso') / ret, 1) if ret else 0.0,
    }


def _pasa(s, f):
    if f.get('servicio') and str(s['sid']) != str(f['servicio']):
        return False
    if f.get('profesional') and str(s['pid']) != str(f['profesional']):
        return False
    if f.get('sucursal') and str(s['suc_id']) != str(f['sucursal']):
        return False
    if f.get('tipo') and s['tipo'] != f['tipo']:
        return False
    return True


def _en_rango(fecha, desde, hasta):
    return (desde is None or fecha >= desde) and (hasta is None or fecha <= hasta)


def _frecuencia_semana(txt):
    """Interpreta texto libre del plan («2 veces por semana», «semanal», «quincenal»…) → sesiones/semana."""
    t = (txt or '').lower().strip()
    if not t:
        return None
    m = re.search(r'(\d+(?:[.,]\d+)?)\s*(?:veces|vez|x|sesion|ses)', t) or re.match(r'^(\d+(?:[.,]\d+)?)\b', t)
    if m:
        n = float(m.group(1).replace(',', '.'))
        if 'quincen' in t:
            return n / 2.0
        if ('mes' in t or 'mensual' in t) and 'semana' not in t:
            return n / 4.3
        return n
    if 'diari' in t:
        return 5.0
    if 'quincen' in t:
        return 0.5
    if 'mensual' in t:
        return 0.25
    if 'semanal' in t or 'una vez' in t:
        return 1.0
    return None


# ─────────────────────────────────────────────────────────────────────
# GENERADO (devengado) DEL PERÍODO
# ─────────────────────────────────────────────────────────────────────
def _generado(S, rows, proy, mens, precio):
    """Devengado de la selección S: individuales + parte ponderada de proyectos y mensualidades."""
    gen_ind = round(sum(s['monto'] for s in S if s['tipo'] == 'individual' and s['estado'] in CONSUMIDAS), 2)
    out = {'ind': gen_ind, 'proyectos': [], 'mensualidades': []}
    for campo, tipo_s, lista in (('proyecto_id', 'proyecto', proy), ('mensualidad_id', 'mensualidad', mens)):
        den = defaultdict(float)
        for s in rows:
            if s[campo] and (s['estado'] in CONSUMIDAS or s['estado'] == 'programada'):
                den[s[campo]] += precio(s)
        num, prog = defaultdict(float), defaultdict(float)
        resumen = defaultdict(lambda: {'n': 0, 'atend': 0, 'faltas': 0, 'prog': 0, 'servicios': set(), 'profs': set()})
        for s in S:
            pid = s[campo]
            if not pid:
                continue
            r = resumen[pid]
            r['n'] += 1
            r['servicios'].add(s['servicio'])
            r['profs'].add(s['prof'])
            if s['estado'] in CONSUMIDAS:
                num[pid] += precio(s)
            if s['estado'] in ATENDIDAS:
                r['atend'] += 1
            elif s['estado'] == 'falta':
                r['faltas'] += 1
            elif s['estado'] == 'programada':
                prog[pid] += precio(s)
                r['prog'] += 1
        for p in lista:
            if p['id'] not in resumen or den.get(p['id'], 0) <= 0:
                continue
            r = resumen[p['id']]
            d = den[p['id']]
            out['proyectos' if tipo_s == 'proyecto' else 'mensualidades'].append({
                **p, 'gen': round(p['valor'] * num[p['id']] / d, 2), 'por_generar': round(p['valor'] * prog[p['id']] / d, 2),
                'share': round(num[p['id']] / d * 100, 1), 'n': r['n'], 'atend': r['atend'], 'faltas': r['faltas'],
                'prog': r['prog'], 'servicios': sorted(r['servicios']), 'profs': sorted(r['profs']),
            })
    out['gen_proy'] = round(sum(x['gen'] for x in out['proyectos']), 2)
    out['gen_mens'] = round(sum(x['gen'] for x in out['mensualidades']), 2)
    out['total'] = round(out['ind'] + out['gen_proy'] + out['gen_mens'], 2)
    out['por_generar'] = round(sum(s['monto_prog'] for s in S)
                               + sum(x['por_generar'] for x in out['proyectos'] + out['mensualidades']), 2)
    return out


# ─────────────────────────────────────────────────────────────────────
# COBRANZA DEL PACIENTE (generado → cobrado → pendiente, con antigüedad)
# ─────────────────────────────────────────────────────────────────────
def _cobranza(S, gen, pagos, desde, hasta, hoy):
    t = {'individual': {'gen': 0.0, 'antes': 0.0, 'durante': 0.0, 'despues': 0.0},
         'proyecto': {'gen': 0.0, 'antes': 0.0, 'durante': 0.0, 'despues': 0.0},
         'mensualidad': {'gen': 0.0, 'antes': 0.0, 'durante': 0.0, 'despues': 0.0}}
    aging = [{'label': l, 'ini': a, 'fin': b, 'monto': 0.0, 'n': 0} for a, b, l in AGING]
    pend_ses, dias_pago = [], []

    def _aging(dias, monto):
        for a in aging:
            if a['ini'] <= dias <= a['fin']:
                a['monto'] += monto
                a['n'] += 1
                return

    for s in S:
        if s['tipo'] != 'individual' or s['estado'] not in CONSUMIDAS or s['monto'] <= 0:
            continue
        x = t['individual']
        x['gen'] += s['monto']
        asig = _asignar(pagos['sesion'].get(s['id'], []), s['monto'])
        cob = 0.0
        for f, m in asig:
            x[_bucket(f, desde, hasta)] += m
            cob += m
        if s['monto'] - cob <= 0.005 and asig:
            dias_pago.append((asig[-1][0] - s['fecha']).days)
        pend = s['monto'] - cob
        if pend > 0.005:
            dias = max((hoy - s['fecha']).days, 0)
            _aging(dias, pend)
            pend_ses.append({'fecha': s['fecha'], 'servicio': s['servicio'], 'prof': s['prof'], 'monto': round(s['monto'], 2),
                             'pend': round(pend, 2), 'dias': dias})
    for clave, lista, key in (('proyecto', gen['proyectos'], 'proyecto'), ('mensualidad', gen['mensualidades'], 'mensualidad')):
        x = t[clave]
        for p in lista:
            if p['gen'] <= 0 or p['valor'] <= 0:
                continue
            pays = pagos[key].get(p['id'], [])
            tot = sum(m for _f_, m, _mp in pays)
            esc = min(1.0, p['valor'] / tot) if tot else 1.0
            b = {'antes': 0.0, 'durante': 0.0, 'despues': 0.0}
            for f, m, _mp in pays:
                b[_bucket(f, desde, hasta)] += m * esc
            cob = 0.0
            for kk, v in b.items():
                part = p['gen'] * v / p['valor']
                x[kk] += part
                cob += part
            x['gen'] += p['gen']
            p['cobrado'] = round(min(tot, p['valor']), 2)
            p['saldo'] = round(max(p['valor'] - tot, 0.0), 2)
            p['ratio_cobro'] = _pct(min(tot, p['valor']), p['valor'])
            pend = max(p['gen'] - cob, 0.0)
            if pend > 0.005:
                _aging(max((hoy - max(p['ref'], desde or p['ref'])).days, 0), pend)
    filas, tot = [], {'gen': 0.0, 'antes': 0.0, 'durante': 0.0, 'despues': 0.0}
    nombres = {'individual': 'Sesiones individuales', 'proyecto': 'Proyectos', 'mensualidad': 'Mensualidades'}
    for c, x in t.items():
        x['nombre'] = nombres[c]
        x['cobrado'] = x['antes'] + x['durante'] + x['despues']
        x['pend'] = max(x['gen'] - x['cobrado'], 0.0)
        x['pct'] = _pct(x['cobrado'], x['gen'])
        for kk in ('gen', 'antes', 'durante', 'despues'):
            tot[kk] += x[kk]
        for kk in ('gen', 'antes', 'durante', 'despues', 'cobrado', 'pend'):
            x[kk] = round(x[kk], 2)
        filas.append(x)
    tot['cobrado'] = tot['antes'] + tot['durante'] + tot['despues']
    tot['pend'] = max(tot['gen'] - tot['cobrado'], 0.0)
    tot['pct'] = _pct(tot['cobrado'], tot['gen'])
    tot = {k: (round(v, 2) if k != 'pct' else v) for k, v in tot.items()}
    pend_tot = sum(a['monto'] for a in aging)
    for a in aging:
        a['monto'] = round(a['monto'], 2)
        a['pct'] = _pct(a['monto'], pend_tot)
    mora30 = round(sum(a['monto'] for a in aging if a['ini'] >= 31), 2)
    dp = [max(d, 0) for d in dias_pago]
    pend_ses.sort(key=lambda x: -x['dias'])
    return {
        'filas': filas, 'tot': tot, 'aging': aging, 'mora30': mora30, 'pct_mora30': _pct(mora30, tot['gen']),
        'pend_ses': pend_ses[:25], 'n_pend_ses': len(pend_ses),
        'dias_pago_prom': round(sum(dp) / len(dp), 1) if dp else None,
        'pct_pago_7d': _pct(sum(1 for d in dp if d <= 7), len(dp)) if dp else None,
        'pct_adelantado': _pct(sum(1 for d in dias_pago if d <= 0), len(dias_pago)) if dias_pago else None,
        'n_pagadas': len(dp),
    }


# ─────────────────────────────────────────────────────────────────────
# RIESGO DE ABANDONO (historial completo)
# ─────────────────────────────────────────────────────────────────────
def _riesgo(paciente, rows, mens, hoy, umbral_obs, umbral_riesgo):
    pas = [s for s in rows if s['fecha'] <= hoy]
    att = [s for s in pas if s['estado'] in ATENDIDAS]
    ultima = max((s['fecha'] for s in att), default=None)
    dias_sin = (hoy - ultima).days if ultima else None
    fut = sorted([s for s in rows if s['estado'] == 'programada' and s['fecha'] >= hoy], key=lambda s: (s['fecha'], s['hora']))
    prox = fut[0] if fut else None

    def n_ventana(a, b):
        return sum(1 for s in att if a <= s['fecha'] <= b)
    n30 = n_ventana(hoy - timedelta(days=29), hoy)
    n30p = n_ventana(hoy - timedelta(days=59), hoy - timedelta(days=30))
    variacion = round((n30 - n30p) / n30p * 100, 1) if n30p else None
    # inasistencias seguidas (de la familia) y cancelaciones seguidas (del centro)
    orden = sorted([s for s in pas if s['estado'] in BASE_ASIS], key=lambda s: (s['fecha'], s['hora']), reverse=True)
    seg_fal = 0
    for s in orden:
        if s['estado'] in ('falta', 'permiso'):
            seg_fal += 1
        else:
            break
    seg_can = 0
    for s in sorted([s for s in pas if s['estado'] in BASE_ASIS + ('cancelada',)], key=lambda s: (s['fecha'], s['hora']), reverse=True):
        if s['estado'] == 'cancelada':
            seg_can += 1
        else:
            break
    meses_set = {(m['anio'], m['mes']) for m in mens if m['estado'] != 'cancelada'}
    ant = (hoy.year, hoy.month - 1) if hoy.month > 1 else (hoy.year - 1, 12)
    mens_sin_renovar = bool(meses_set) and ant in meses_set and (hoy.year, hoy.month) not in meses_set and hoy.day >= 5
    primera = min((s['fecha'] for s in rows), default=None) or getattr(paciente, 'fecha_registro', None)
    meses_trat = ((hoy.year - primera.year) * 12 + hoy.month - primera.month + 1) if primera else 0
    motivos, nivel = [], 'bajo'
    inactivo = getattr(paciente, 'estado', 'activo') != 'activo'

    def sube(n):
        nonlocal nivel
        orden_n = {'bajo': 0, 'medio': 1, 'alto': 2}
        if orden_n[n] > orden_n[nivel]:
            nivel = n
    if dias_sin is not None and not prox:
        if dias_sin >= umbral_riesgo:
            sube('alto'); motivos.append(f"{dias_sin} días sin asistir y sin sesiones agendadas (umbral de riesgo: {umbral_riesgo}).")
        elif dias_sin >= umbral_obs:
            sube('medio'); motivos.append(f"{dias_sin} días sin asistir y sin sesiones agendadas (en observación desde {umbral_obs}).")
    elif dias_sin is not None and dias_sin >= umbral_riesgo and prox:
        sube('medio'); motivos.append(f"{dias_sin} días sin asistir, aunque tiene sesiones agendadas.")
    if ultima is None and rows:
        sube('medio'); motivos.append('Tiene sesiones registradas pero ninguna asistida todavía.')
    if seg_fal >= 3:
        sube('alto'); motivos.append(f"{seg_fal} inasistencias seguidas (falta o permiso).")
    elif seg_fal == 2:
        sube('medio'); motivos.append('2 inasistencias seguidas (falta o permiso).')
    if variacion is not None and n30p >= 3:
        if variacion <= -60:
            sube('alto'); motivos.append(f"Su asistencia cayó {abs(variacion):.0f}% frente a los 30 días anteriores ({n30p} → {n30} sesiones).")
        elif variacion <= -35:
            sube('medio'); motivos.append(f"Su asistencia bajó {abs(variacion):.0f}% frente a los 30 días anteriores ({n30p} → {n30} sesiones).")
    if mens_sin_renovar:
        sube('medio'); motivos.append('Tenía mensualidad el mes pasado y todavía no tiene la de este mes.')
    if seg_can >= 3:
        motivos.append(f"{seg_can} cancelaciones seguidas por parte del centro: revisar la agenda del profesional.")
    if inactivo:
        motivos.append('El paciente figura como inactivo.')
    if not motivos:
        motivos.append('Asiste con regularidad y tiene sesiones agendadas.' if prox else 'Sin señales de abandono.')
    if inactivo:
        # un paciente inactivo no está «en riesgo de abandonar»: ya no asiste. Se informa su situación.
        nivel = 'inactivo'
        motivos = ['Paciente INACTIVO' + (f": última sesión asistida el {ultima:%d/%m/%Y} (hace {dias_sin} días)." if ultima else ': sin sesiones asistidas registradas.')]
        if prox:
            motivos.append(f"Aun así tiene una sesión agendada el {prox['fecha']:%d/%m/%Y}: conviene revisar si debe reactivarse.")
    return {
        'nivel': nivel, 'motivos': motivos, 'ultima': ultima, 'dias_sin': dias_sin, 'proxima': prox['fecha'] if prox else None,
        'dias_a_proxima': (prox['fecha'] - hoy).days if prox else None, 'n30': n30, 'n30p': n30p, 'variacion': variacion,
        'sem30': round(n30 * 7 / 30.0, 2), 'sem30p': round(n30p * 7 / 30.0, 2),
        'seg_faltas': seg_fal, 'seg_cancel': seg_can, 'mens_sin_renovar': mens_sin_renovar,
        'meses_trat': meses_trat, 'primera': primera, 'inactivo': inactivo,
        'umbral_obs': umbral_obs, 'umbral_riesgo': umbral_riesgo,
    }


# ─────────────────────────────────────────────────────────────────────
# VALOR, DESCUENTOS Y RENTABILIDAD
# ─────────────────────────────────────────────────────────────────────
def _valor(S, rows, gen, proy, mens, M, riesgo, costo_hora, desde, hasta, hoy):
    from agenda.models import Sesion
    ind_total = sum(s['monto'] for s in rows if s['tipo'] == 'individual' and s['estado'] in CONSUMIDAS)
    mens_total = sum(m['valor'] for m in mens if m['estado'] != 'cancelada' and m['ref'] <= hoy)
    proy_total = sum(p['valor'] for p in proy if p['estado'] != 'cancelado' and p['ref'] <= hoy)
    total = round(ind_total + mens_total + proy_total, 2)
    meses = max(riesgo['meses_trat'], 1)
    horas = M['min'] / 60.0
    ing_hora = round(gen['total'] / horas, 2) if horas else 0.0
    # descuentos / gratuidades / exenciones del período
    desc_ses = grat_n = grat_v = exen_n = exen_v = 0.0
    for s in S:
        if s['tipo'] == 'individual' and s['estado'] in CONSUMIDAS:
            if s['monto'] > 0 and s['monto_orig'] > s['monto'] + 0.005:
                desc_ses += s['monto_orig'] - s['monto']
            elif s['monto'] <= 0 and (s['monto_orig'] > 0 or s['monto_exen'] > 0):
                grat_n += 1
                grat_v += s['monto_orig'] or s['monto_exen']
        elif s['estado'] in ('permiso', 'cancelada', 'reprogramada') and s['monto_exen'] > 0:
            exen_n += 1
            exen_v += s['monto_exen']
    desc_paq = sum(max(p['valor_orig'] - p['valor'], 0.0) for p in gen['proyectos'] + gen['mensualidades'] if p['valor_orig'] > 0)
    dejado = desc_ses + grat_v + desc_paq
    # posición entre pacientes (ingreso por sesiones individuales del período)
    hasta_r, desde_r = hasta or hoy, desde or (hoy - timedelta(days=89))
    rk = (Sesion.objects.filter(fecha__gte=desde_r, fecha__lte=hasta_r, estado__in=CONSUMIDAS, proyecto__isnull=True,
                                mensualidad__isnull=True).values('paciente_id').annotate(t=Sum('monto_cobrado')).order_by('-t'))
    lista = [(x['paciente_id'], _f(x['t'])) for x in rk if _f(x['t']) > 0]
    costo = round(horas * costo_hora, 2) if costo_hora else None
    return {
        'total_hist': total, 'ind_hist': round(ind_total, 2), 'mens_hist': round(mens_total, 2), 'proy_hist': round(proy_total, 2),
        'meses': meses, 'prom_mensual': round(total / meses, 2), 'ing_hora': ing_hora,
        'desc_ses': round(desc_ses, 2), 'grat_n': int(grat_n), 'grat_v': round(grat_v, 2),
        'exen_n': int(exen_n), 'exen_v': round(exen_v, 2), 'desc_paq': round(desc_paq, 2), 'dejado': round(dejado, 2),
        'pct_dejado': _pct(dejado, gen['total'] + dejado), 'ranking_lista': lista,
        'costo_hora': costo_hora or 0.0, 'costo': costo,
        'margen': round(gen['total'] - costo, 2) if costo is not None else None,
        'margen_pct': round((gen['total'] - costo) / gen['total'] * 100, 1) if (costo is not None and gen['total']) else None,
        'horas': round(horas, 1),
    }


# ─────────────────────────────────────────────────────────────────────
# PLAN DE TRABAJO
# ─────────────────────────────────────────────────────────────────────
def _plan(paciente, rows, hoy):
    from documentos.models import PlanTrabajo
    planes, plan_sem = [], 0.0
    for p in PlanTrabajo.objects.filter(paciente=paciente).select_related('profesional').order_by('-activo', '-fecha_inicio'):
        freq = _frecuencia_semana(p.frecuencia_sesiones)
        vigente = p.activo and (p.fecha_fin is None or p.fecha_fin >= hoy) and (p.fecha_inicio is None or p.fecha_inicio <= hoy)
        if p.activo and p.fecha_fin and p.fecha_fin < hoy:
            estado = 'vencido'
        elif not p.activo:
            estado = 'inactivo'
        else:
            estado = 'vigente'
        rev = None
        if p.proxima_revision:
            d = (p.proxima_revision - hoy).days
            rev = 'vencida' if d < 0 else ('próxima' if d <= 15 else 'al día')
        if vigente and freq:
            plan_sem += freq
        planes.append({
            'area': p.area_intervencion, 'frecuencia': p.frecuencia_sesiones, 'freq_sem': freq, 'inicio': p.fecha_inicio,
            'fin': p.fecha_fin, 'revision': p.proxima_revision, 'estado_rev': rev, 'estado': estado, 'vigente': vigente,
            'prof': ((p.profesional.get_full_name() if p.profesional_id else '') or p.nombre_profesional_manual
                     or (p.profesional.username if p.profesional_id else '') or ''),
        })
    att = [s for s in rows if s['estado'] in ATENDIDAS]
    n28 = sum(1 for s in att if hoy - timedelta(days=27) <= s['fecha'] <= hoy)
    real_sem = round(n28 / 4.0, 2)
    cumpl = round(real_sem / plan_sem * 100, 1) if plan_sem else None
    return {'planes': planes, 'plan_sem': round(plan_sem, 2), 'real_sem': real_sem, 'cumplimiento': cumpl,
            'n_vigentes': sum(1 for p in planes if p['vigente']), 'sin_plan': not any(p['vigente'] for p in planes),
            'revisiones_vencidas': sum(1 for p in planes if p['vigente'] and p['estado_rev'] == 'vencida')}


# ─────────────────────────────────────────────────────────────────────
# COMPARACIONES (período anterior y promedio del centro)
# ─────────────────────────────────────────────────────────────────────
def _comparar(rows, precio, proy, mens, filtros, desde, hasta, hoy, gen_actual, M):
    from agenda.models import Sesion
    if desde and hasta:
        largo = (hasta - desde).days + 1
        ph = desde - timedelta(days=1)
        pd = ph - timedelta(days=largo - 1)
        etiqueta = f"período anterior ({pd:%d/%m/%Y} – {ph:%d/%m/%Y})"
        a_d, a_h = desde, hasta
    else:
        a_d, a_h = hoy - timedelta(days=29), hoy
        ph, pd = a_d - timedelta(days=1), a_d - timedelta(days=30)
        etiqueta = 'los 30 días anteriores a los últimos 30 días'
    S_prev = [s for s in rows if _en_rango(s['fecha'], pd, ph) and _pasa(s, filtros)]
    S_act = [s for s in rows if _en_rango(s['fecha'], a_d, a_h) and _pasa(s, filtros)] if not (desde and hasta) else None
    Mp = _metricas(S_prev)
    Ma = M if S_act is None else _metricas(S_act)
    gp = _generado(S_prev, rows, proy, mens, precio)['total']
    ga = gen_actual['total'] if S_act is None else _generado(S_act, rows, proy, mens, precio)['total']
    # promedio del centro en la ventana actual
    cnt = {x['estado']: x['n'] for x in Sesion.objects.filter(fecha__gte=a_d, fecha__lte=a_h).values('estado').annotate(n=Count('id'))}
    r, rt, f_, p_ = cnt.get('realizada', 0), cnt.get('realizada_retraso', 0), cnt.get('falta', 0), cnt.get('permiso', 0)
    base_c = r + rt + f_ + p_
    ind = Sesion.objects.filter(fecha__gte=a_d, fecha__lte=a_h, estado__in=ATENDIDAS, proyecto__isnull=True,
                                mensualidad__isnull=True).aggregate(m=Sum('monto_cobrado'), d=Sum('duracion_minutos'))
    ih = round(_f(ind['m']) / (_f(ind['d']) / 60.0), 2) if _f(ind['d']) else 0.0
    return {
        'etiqueta': etiqueta, 'ventana': (a_d, a_h), 'previo': (pd, ph),
        'filas': [
            {'k': 'Sesiones atendidas', 'act': Ma['atendidas'], 'ant': Mp['atendidas'], 'delta': Ma['atendidas'] - Mp['atendidas'], 'fmt': 'n', 'sube_bien': True},
            {'k': 'Asistencia (%)', 'act': Ma['tasa_asistencia'], 'ant': Mp['tasa_asistencia'], 'delta': round(Ma['tasa_asistencia'] - Mp['tasa_asistencia'], 1), 'fmt': 'pct', 'sube_bien': True,
             'centro': _pct(r + rt, base_c)},
            {'k': 'Puntualidad (%)', 'act': Ma['puntualidad'], 'ant': Mp['puntualidad'], 'delta': round(Ma['puntualidad'] - Mp['puntualidad'], 1), 'fmt': 'pct', 'sube_bien': True,
             'centro': _pct(r, r + rt)},
            {'k': 'Faltas sin aviso (%)', 'act': Ma['tasa_faltas'], 'ant': Mp['tasa_faltas'], 'delta': round(Ma['tasa_faltas'] - Mp['tasa_faltas'], 1), 'fmt': 'pct', 'sube_bien': False,
             'centro': _pct(f_, base_c)},
            {'k': 'Horas atendidas', 'act': round(Ma['min'] / 60.0, 1), 'ant': round(Mp['min'] / 60.0, 1), 'delta': round((Ma['min'] - Mp['min']) / 60.0, 1), 'fmt': 'h', 'sube_bien': True},
            {'k': 'Generado (Bs.)', 'act': ga, 'ant': gp, 'delta': round(ga - gp, 2), 'fmt': 'bs', 'sube_bien': True},
        ],
        'centro': {'asistencia': _pct(r + rt, base_c), 'puntualidad': _pct(r, r + rt), 'faltas': _pct(f_, base_c), 'ing_hora': ih,
                   'sesiones': sum(cnt.values())},
    }


# ─────────────────────────────────────────────────────────────────────
# PATRÓN DE ASISTENCIA, CALENDARIO, SERVICIOS, MOTIVOS, PRÓXIMAS, LÍNEA DE TIEMPO, CALIDAD
# ─────────────────────────────────────────────────────────────────────
def _patron(S):
    cel = defaultdict(lambda: [0, 0])
    por_dia = defaultdict(lambda: [0, 0])
    por_hora = defaultdict(lambda: [0, 0])
    for s in S:
        if s['estado'] not in BASE_ASIS:
            continue
        a = 1 if s['estado'] in ATENDIDAS else 0
        wd = s['fecha'].weekday()
        cel[(wd, s['hora'])][0] += 1
        cel[(wd, s['hora'])][1] += a
        por_dia[wd][0] += 1
        por_dia[wd][1] += a
        por_hora[s['hora']][0] += 1
        por_hora[s['hora']][1] += a
    if not cel:
        return {'heat': [], 'horas': [], 'por_dia': [], 'mejores': [], 'peores': [], 'por_hora': []}
    h0, h1 = min(h for _w, h in cel), max(h for _w, h in cel)
    heat = []
    for wd in range(7):
        if wd not in por_dia:
            continue
        celdas = []
        for h in range(h0, h1 + 1):
            n, a = cel.get((wd, h), [0, 0])
            tasa = _pct(a, n) if n else None
            celdas.append({'h': h, 'n': n, 'att': a, 'tasa': tasa, 'a': round((tasa or 0) / 100.0, 2)})
        heat.append({'dia': DIAS_ES[wd], 'dia_c': DIAS_CORTO[wd], 'celdas': celdas})
    slots = [{'dia': DIAS_ES[w], 'hora': f"{h:02d}:00", 'n': n, 'att': a, 'tasa': _pct(a, n)}
             for (w, h), (n, a) in cel.items() if n >= 3]
    return {
        'heat': heat, 'horas': [f"{h:02d}h" for h in range(h0, h1 + 1)],
        'por_dia': [{'dia': DIAS_ES[w], 'n': n, 'att': a, 'tasa': _pct(a, n)} for w, (n, a) in sorted(por_dia.items())],
        'por_hora': [{'hora': f"{h:02d}:00", 'n': n, 'att': a, 'tasa': _pct(a, n)} for h, (n, a) in sorted(por_hora.items())],
        'mejores': sorted(slots, key=lambda x: (-x['tasa'], -x['n']))[:3],
        'peores': [x for x in sorted(slots, key=lambda x: (x['tasa'], -x['n'])) if x['tasa'] < 80][:3],
    }


def _calendarios(S, desde, hasta, hoy, max_meses=3):
    if not S:
        return []
    ref = min(hasta or hoy, max(s['fecha'] for s in S)) if (hasta or hoy) else max(s['fecha'] for s in S)
    ref = max(ref, min(s['fecha'] for s in S))
    meses = []
    y, m = ref.year, ref.month
    primero = min(s['fecha'] for s in S)
    while len(meses) < max_meses and (y, m) >= (primero.year, primero.month):
        meses.append((y, m))
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    meses.reverse()
    por_dia = defaultdict(list)
    for s in S:
        por_dia[s['fecha']].append(s['estado'])
    out = []
    for y, m in meses:
        semanas = []
        for sem in calendar.Calendar(0).monthdayscalendar(y, m):
            fila = []
            for d in sem:
                if d == 0:
                    fila.append(None)
                    continue
                f = date(y, m, d)
                est = por_dia.get(f, [])
                dom = next((e for e in PRIORIDAD_CAL if e in est), None)
                fila.append({'dia': d, 'n': len(est), 'estado': dom, 'color': COLOR_EST.get(dom, ''), 'estados': est,
                             'tip': ', '.join(f"{ESTADOS_TXT[e]}" for e in est)})
            semanas.append(fila)
        out.append({'label': f"{MESES_ES[m]} {y}", 'semanas': semanas, 'y': y, 'm': m})
    return out


def _servicios(paciente, rows, hoy, S):
    from pacientes.models import PacienteServicio
    ps = list(PacienteServicio.objects.filter(paciente=paciente).select_related('servicio'))
    por_s = defaultdict(list)
    for s in rows:
        por_s[s['sid']].append(s)
    out, cambios_total = [], 0
    ids_vistos = set()
    for x in ps:
        sid = x.servicio_id
        ids_vistos.add(sid)
        out.append(_info_servicio(sid, x.servicio.nombre, getattr(x, 'activo', True), _f(getattr(x, 'costo_sesion', 0)),
                                  por_s.get(sid, []), S, hoy))
    for sid, lst in por_s.items():
        if sid not in ids_vistos:
            out.append(_info_servicio(sid, lst[0]['servicio'], None, 0.0, lst, S, hoy))
    for o in out:
        cambios_total += o['cambios']
    out.sort(key=lambda o: (not (o['activo'] is not False), -o['n_periodo']))
    return {'items': out, 'cambios_total': cambios_total,
            'inactivos_sin_uso': [o['nombre'] for o in out if o['alerta']]}


def _info_servicio(sid, nombre, activo, costo, lst, S, hoy):
    att = sorted([s for s in lst if s['estado'] in ATENDIDAS], key=lambda s: (s['fecha'], s['hora']))
    ultima = att[-1]['fecha'] if att else None
    dias = (hoy - ultima).days if ultima else None
    seq = [s['pid'] for s in att if s['pid']]
    cambios = sum(1 for a, b in zip(seq, seq[1:]) if a != b)
    cnt = Counter(s['prof'] for s in att if s['prof'])
    principal = cnt.most_common(1)[0] if cnt else None
    n30 = sum(1 for s in att if hoy - timedelta(days=29) <= s['fecha'] <= hoy)
    return {
        'sid': sid, 'nombre': nombre, 'activo': activo, 'costo': costo, 'ultima': ultima, 'dias_sin': dias, 'n30': n30,
        'n_periodo': sum(1 for s in S if s['sid'] == sid and s['estado'] in ATENDIDAS), 'total_hist': len(att),
        'cambios': cambios, 'profs': [{'nombre': k, 'n': v, 'pct': _pct(v, len(att))} for k, v in cnt.most_common()],
        'principal': principal[0] if principal else '', 'continuidad': _pct(principal[1], len(att)) if principal else 0.0,
        'alerta': bool(activo is True and (dias is None or dias > 30)),
    }


def _motivos(S):
    c = Counter(s['estado'] for s in S)
    lista, textos = [], Counter()
    for s in sorted(S, key=lambda s: s['fecha'], reverse=True):
        if s['estado'] not in ('permiso', 'cancelada', 'reprogramada', 'falta'):
            continue
        txt = s['motivo'] if s['estado'] == 'reprogramada' and s['motivo'] else (s['obs'] or s['nota'] or s['motivo'])
        if txt:
            textos[re.sub(r'\s+', ' ', txt.lower())[:70]] += 1
        lista.append({'fecha': s['fecha'], 'estado': s['estado'], 'estado_txt': ESTADOS_TXT[s['estado']], 'servicio': s['servicio'],
                      'prof': s['prof'], 'motivo': (txt or '')[:140]})
    return {
        'por_origen': [
            {'k': 'Falta sin aviso (familia)', 'n': c['falta'], 'color': COLOR_EST['falta']},
            {'k': 'Permiso con aviso (familia)', 'n': c['permiso'], 'color': COLOR_EST['permiso']},
            {'k': 'Cancelada (centro)', 'n': c['cancelada'], 'color': COLOR_EST['cancelada']},
            {'k': 'Reprogramada', 'n': c['reprogramada'], 'color': COLOR_EST['reprogramada']},
        ],
        'top': [{'texto': k, 'n': v} for k, v in textos.most_common(8)],
        'lista': lista[:14], 'total': len(lista), 'sin_motivo': sum(1 for x in lista if not x['motivo']),
    }


def _proximas(rows, pagos, precio, hoy):
    fut = sorted([s for s in rows if s['estado'] == 'programada' and s['fecha'] >= hoy], key=lambda s: (s['fecha'], s['hora']))
    items, esp, adel = [], 0.0, 0.0
    for s in fut:
        if s['tipo'] == 'individual':
            valor = s['monto'] if s['monto'] > 0 else (s['monto_orig'] if s['monto_orig'] > 0 else precio(s))
            pag = sum(a for _f_, a in _asignar(pagos['sesion'].get(s['id'], []), valor))
            esp += valor
            adel += pag
        else:
            valor, pag = 0.0, 0.0
        items.append({'fecha': s['fecha'], 'hora': s['hora_txt'], 'dia': DIAS_ES[s['fecha'].weekday()], 'servicio': s['servicio'],
                      'prof': s['prof'], 'suc': s['suc'], 'tipo': s['tipo'], 'valor': round(valor, 2), 'pagado': round(pag, 2),
                      'pend': round(max(valor - pag, 0), 2), 'dias': (s['fecha'] - hoy).days})
    return {'items': items[:25], 'total': len(fut), 'n7': sum(1 for x in items if x['dias'] <= 7),
            'n30': sum(1 for x in items if x['dias'] <= 30), 'esperado': round(esp, 2), 'adelantado': round(adel, 2),
            'por_cobrar': round(max(esp - adel, 0), 2)}


def _clinico(paciente, S, proy, hoy):
    from documentos.models import DocumentoPaciente
    from evaluaciones.models import EvaluacionADIR, EvaluacionADOS2, InformeEvaluacion
    at = [s for s in S if s['estado'] in ATENDIDAS]
    con_nota = [s for s in at if s['nota']]
    sin_nota = [s for s in at if not s['nota']]
    por_prof = defaultdict(lambda: [0, 0])
    for s in at:
        por_prof[s['prof']][0] += 1
        por_prof[s['prof']][1] += 1 if s['nota'] else 0
    ados = list(EvaluacionADOS2.objects.filter(paciente=paciente).order_by('-fecha_evaluacion').values('fecha_evaluacion', 'modulo'))
    adir = list(EvaluacionADIR.objects.filter(paciente=paciente).order_by('-fecha_evaluacion').values('fecha_evaluacion'))
    inf = list(InformeEvaluacion.objects.filter(paciente=paciente).order_by('-fecha_informe').values('fecha_informe', 'estado'))
    docs = list(DocumentoPaciente.objects.filter(paciente=paciente).order_by('-fecha_subida').values('titulo', 'tipo', 'fecha_subida', 'compartir_misael_kids'))
    ev_fechas = [x['fecha_evaluacion'] for x in ados + adir if x['fecha_evaluacion']]
    ult_ev = max(ev_fechas) if ev_fechas else None
    sin_informe = [p for p in proy if p['estado'] == 'finalizado' and not p.get('informe_entregado')]
    return {
        'sesiones': len(at), 'con_nota': len(con_nota), 'pct_nota': _pct(len(con_nota), len(at)),
        'sin_nota': [{'fecha': s['fecha'], 'servicio': s['servicio'], 'prof': s['prof']} for s in sorted(sin_nota, key=lambda s: s['fecha'], reverse=True)[:10]],
        'por_prof': [{'prof': k, 'n': v[0], 'con': v[1], 'pct': _pct(v[1], v[0])} for k, v in sorted(por_prof.items(), key=lambda kv: kv[1][1] / max(kv[1][0], 1))],
        'ados': ados, 'adir': adir, 'informes': inf, 'ult_eval': ult_ev, 'dias_ult_eval': (hoy - ult_ev).days if ult_ev else None,
        'informes_pend': sum(1 for x in inf if x['estado'] != 'finalizado'),
        'proy_sin_informe': [{'codigo': p['codigo'], 'nombre': p['nombre']} for p in sin_informe],
        'docs': docs, 'n_docs': len(docs), 'docs_familia': sum(1 for d in docs if d['compartir_misael_kids']),
    }


def _linea_tiempo(paciente, rows, proy, mens, clin, planes, pagos_dev, hoy):
    ev = []
    if getattr(paciente, 'fecha_registro', None):
        ev.append((paciente.fecha_registro, 'ingreso', 'Ingreso al centro', ''))
    att = [s for s in rows if s['estado'] in ATENDIDAS]
    if att:
        p = min(att, key=lambda s: s['fecha'])
        ev.append((p['fecha'], 'sesion', 'Primera sesión atendida', f"{p['servicio']} · {p['prof']}"))
    for x in clin['ados']:
        ev.append((x['fecha_evaluacion'], 'eval', 'Evaluación ADOS-2', f"Módulo {x['modulo']}"))
    for x in clin['adir']:
        ev.append((x['fecha_evaluacion'], 'eval', 'Evaluación ADI-R', ''))
    for x in clin['informes']:
        ev.append((x['fecha_informe'], 'informe', 'Informe de evaluación', x['estado'].capitalize()))
    for p in proy:
        ev.append((p['ref'], 'proyecto', f"Proyecto {p['codigo']}", p['nombre']))
        if p['fin'] and p['estado'] == 'finalizado':
            ev.append((p['fin'], 'proyecto', f"Proyecto {p['codigo']} finalizado", 'Informe entregado' if p.get('informe_entregado') else 'Informe pendiente'))
    for m in mens:
        ev.append((m['ref'], 'mensualidad', f"Mensualidad {m['nombre']}", m['estado'].capitalize()))
    for p in planes:
        if p['inicio']:
            ev.append((p['inicio'], 'plan', f"Plan de trabajo: {p['area']}", p['frecuencia']))
        if p['revision']:
            ev.append((p['revision'], 'plan', f"Revisión de plan: {p['area']}", 'pendiente' if p['revision'] >= hoy else 'fecha de revisión'))
    for d in clin['docs'][:10]:
        ev.append((d['fecha_subida'], 'doc', 'Documento', d['titulo']))
    for d in pagos_dev:
        ev.append((d['fecha'], 'devolucion', 'Devolución', f"Bs. {d['monto']:,.2f}"))
    ev = [((e[0].date() if hasattr(e[0], 'date') and callable(e[0].date) else e[0]),) + e[1:] for e in ev if e[0]]
    ev.sort(key=lambda e: e[0], reverse=True)
    iconos = {'ingreso': '🏁', 'sesion': '▶️', 'eval': '🧪', 'informe': '📄', 'proyecto': '📦', 'mensualidad': '🗓️',
              'plan': '🎯', 'doc': '📎', 'devolucion': '↩️'}
    return [{'fecha': f, 'tipo': t, 'icono': iconos.get(t, '•'), 'titulo': ti, 'detalle': d, 'futuro': f > hoy} for f, t, ti, d in ev[:40]]


def _devoluciones(paciente):
    from facturacion.models import Devolucion
    return [{'fecha': d['fecha_devolucion'], 'monto': _f(d['monto'])} for d in
            Devolucion.objects.filter(paciente=paciente).values('fecha_devolucion', 'monto')]


# ─────────────────────────────────────────────────────────────────────
# EVOLUCIÓN CLÍNICA: análisis de las notas de evolución por área y profesional
# (Sesion.notas_sesion). El «tono» es un análisis automático por palabras clave:
# ORIENTATIVO, no reemplaza la lectura clínica de las notas.
# ─────────────────────────────────────────────────────────────────────
_STOP = set("""
de la que el en y a los del se las por un para con no una su al lo como mas pero sus le ya o este si porque esta entre
cuando muy sin sobre tambien me hasta hay donde quien desde todo nos durante todos uno les ni contra otros ese eso ante
ellos e esto antes algunos unos yo otro otras otra tanto esa estos mucho quienes nada muchos cual poco ella estar
estas algunas algo nosotros mi mis tu te ti tus ellas ser fue era sido son es soy eres estaba estuvo estan
cada tras segun aun asi luego despues mientras solo solamente demas tiene tuvo tenia tienen hizo hace hacen
hacia dentro fuera cuyo cuya sera seran puede pudo podia pueden debe debio quiso quiere quieren ademas
sesion sesiones paciente nino nina hoy trabajo trabajamos trabajaron realizo realizaron realiza
realizar actividad actividades terapia terapias presenta presento muestra mostro continua continuo continuar
inicio inicia finalizo final termino parte vez veces menos misma mismo
""".split())
_POS_STEMS = [r'logr(?:o|a|an|ando|ado|aron|ar|os)', r'mejor(?:o|a|an|ando|ia|ias)', r'avanc\w*', r'avanz\w*', r'progres\w*', r'adquir\w*',
              r'aprendi\w*', r'consolid\w*', r'domin(?:a|o|an|ando)', r'correctamente', r'adecuad\w*',
              r'buena? (?:disposicion|actitud|respuesta|participacion|atencion|conducta)', r'buen (?:desempeno|trabajo|nivel|ritmo|comportamiento)',
              r'particip\w*', r'colabor\w*', r'atent[oa]s?', r'motivad\w*', r'interes\w*', r'espontane\w*', r'autonom\w*',
              r'independien\w*', r'responde\w*', r'comprend\w*', r'fluid\w*', r'tranquil\w*', r'alegre\w*', r'content[oa]s?',
              r'entusias\w*', r'cooperad\w*', r'imit(?:o|a|ando|aron)', r'nombr(?:o|a|ando)', r'articul(?:o|a|ando)',
              r'pronunci(?:o|a|ando)', r'mantien\w*', r'mantuvo', r'concentr\w*', r'exito\w*', r'satisfactori\w*',
              r'favorable\w*', r'cumpl(?:io|e|ieron)', r'sigue instrucciones', r'siguio instrucciones']
_NEG_STEMS = [r'dificultad\w*', r'le costo', r'cuesta', r'costo mucho', r'rechaz\w*', r'berrinche\w*', r'rabieta\w*', r'llant\w*',
              r'llor\w*', r'irritab\w*', r'inquiet\w*', r'distra\w*', r'dispers\w*', r'desatent\w*', r'agitad\w*', r'se nego',
              r'negativ\w*', r'resistencia', r'frustr\w*', r'disruptiv\w*', r'agresiv\w*', r'agresion', r'impulsiv\w*', r'cansad\w*',
              r'somnolien\w*', r'enferm\w*', r'desmotivad\w*', r'ansios\w*', r'ansiedad', r'regres\w*', r'retroces\w*', r'estanc\w*',
              r'intolerancia', r'crisis', r'intranquil\w*', r'desorganiz\w*', r'no quiso', r'no pudo']
_POS_RX = [re.compile(r'\b' + x + r'\b') for x in _POS_STEMS]
_NEG_RX = [re.compile(r'\b' + x + r'\b') for x in _NEG_STEMS]
_SIN_RX = re.compile(r'\bsin (?:mayor(?:es)? |ninguna |mucha |mucho )?(?:' + '|'.join(_NEG_STEMS) + r')\b')
_NO_POS_RX = re.compile(r'\bno (?:logr\w*|mejor\w*|avanz\w*|particip\w*|colabor\w*|respond\w*|comprend\w*|sigui\w*)')
BREVE = 8      # notas con menos palabras se consideran muy breves


def _norm(t):
    return ''.join(c for c in unicodedata.normalize('NFD', (t or '').lower()) if unicodedata.category(c) != 'Mn')


def _tono(texto):
    """(positivos, negativos) por palabras clave, con negaciones simples («sin dificultad», «no logró»)."""
    t = _norm(texto)
    pos = neg = 0
    pos += len(_SIN_RX.findall(t))
    t = _SIN_RX.sub(' ', t)
    neg += len(_NO_POS_RX.findall(t))
    t = _NO_POS_RX.sub(' ', t)
    pos += sum(len(r.findall(t)) for r in _POS_RX)
    neg += sum(len(r.findall(t)) for r in _NEG_RX)
    return pos, neg


def _etiqueta_tono(pos, neg):
    if pos > neg:
        return 'favorable'
    if neg > pos:
        return 'dificultades'
    return 'mixta' if pos else 'neutra'


def _temas(textos, n=12):
    cnt, orig = Counter(), {}
    for t in textos:
        vistos = set()
        for w in re.findall(r"[A-Za-záéíóúüñÁÉÍÓÚÜÑ]{4,}", t):
            k = _norm(w)
            if k in _STOP or k in vistos:
                continue
            vistos.add(k)
            cnt[k] += 1
            orig.setdefault(k, w.lower())
    return [{'texto': orig[k], 'n': v} for k, v in cnt.most_common(n) if v >= 2]


def _neto_tono(lst):
    return round(sum(1 if x['tono'] == 'favorable' else (-1 if x['tono'] == 'dificultades' else 0) for x in lst) / len(lst) * 100, 1)


def _evolucion(S, hoy):
    """Notas de evolución de las sesiones atendidas de S, agrupadas por área (servicio) y por profesional."""
    at = [s for s in S if s['estado'] in ATENDIDAS]
    areas_d = defaultdict(list)
    for s in at:
        areas_d[(s['sid'], s['servicio'], s['color'])].append(s)
    areas = []
    for (sid, nombre, color), ses in areas_d.items():
        notas = []
        for s in sorted([x for x in ses if x['nota']], key=lambda x: (x['fecha'], x['hora']), reverse=True):
            pos, neg = _tono(s['nota'])
            palabras = len(s['nota'].split())
            notas.append({
                'fecha': s['fecha'], 'hora': s['hora_txt'], 'prof': s['prof'] or '—', 'servicio': nombre, 'texto': s['nota'],
                'palabras': palabras, 'breve': palabras < BREVE, 'pos': pos, 'neg': neg, 'tono': _etiqueta_tono(pos, neg),
                'tipo': s['tipo'], 'busqueda': _norm(f"{nombre} {s['prof']} {s['nota']}"),
            })
        n, tot = len(notas), len(ses)
        tonos = Counter(x['tono'] for x in notas)
        cron = list(reversed(notas))
        tendencia, neto_ini, neto_fin = 'sin datos suficientes', None, None
        if n >= 6:
            h = n // 2
            neto_ini, neto_fin = _neto_tono(cron[:h]), _neto_tono(cron[h:])
            d = neto_fin - neto_ini
            tendencia = 'mejorando' if d >= 15 else ('con más dificultades' if d <= -15 else 'estable')
        por_mes = defaultdict(list)
        for x in notas:
            por_mes[(x['fecha'].year, x['fecha'].month)].append(x)
        meses = []
        for k in sorted(por_mes):
            lst = por_mes[k]
            meses.append({'label': f"{MESES_ES[k[1]][:3]} {str(k[0])[2:]}", 'n': len(lst),
                          'fav': _pct(sum(1 for x in lst if x['tono'] == 'favorable'), len(lst)),
                          'dif': _pct(sum(1 for x in lst if x['tono'] == 'dificultades'), len(lst))})
        pp = defaultdict(lambda: {'ses': 0, 'notas': []})
        for s in ses:
            pp[s['prof'] or '—']['ses'] += 1
        for x in notas:
            pp[x['prof']]['notas'].append(x)
        profs = []
        for pr, d in pp.items():
            ln = d['notas']
            profs.append({'prof': pr, 'ses': d['ses'], 'notas': len(ln), 'pct': _pct(len(ln), d['ses']),
                          'palabras_prom': round(sum(x['palabras'] for x in ln) / len(ln), 1) if ln else 0.0,
                          'breves': sum(1 for x in ln if x['breve']), 'pct_breves': _pct(sum(1 for x in ln if x['breve']), len(ln)),
                          'ultima': max((x['fecha'] for x in ln), default=None)})
        profs.sort(key=lambda x: -x['ses'])
        ultima = notas[0]['fecha'] if notas else None
        areas.append({
            'sid': sid, 'nombre': nombre, 'color': color, 'sesiones': tot, 'n_notas': n, 'pct_nota': _pct(n, tot),
            'palabras_prom': round(sum(x['palabras'] for x in notas) / n, 1) if n else 0.0,
            'breves': sum(1 for x in notas if x['breve']), 'pct_breves': _pct(sum(1 for x in notas if x['breve']), n),
            'ultima': ultima, 'dias_ultima': (hoy - ultima).days if ultima else None,
            'tonos': {k: tonos.get(k, 0) for k in ('favorable', 'mixta', 'dificultades', 'neutra')},
            'pct_tonos': {k: _pct(tonos.get(k, 0), n) for k in ('favorable', 'mixta', 'dificultades', 'neutra')},
            'tendencia': tendencia, 'neto_ini': neto_ini, 'neto_fin': neto_fin,
            'temas': _temas([x['texto'] for x in notas]), 'meses': meses, 'profs': profs,
            'notas': notas[:150], 'notas_total': n, 'recortadas': n > 150,
        })
    areas.sort(key=lambda a_: (-a_['n_notas'], -a_['sesiones']))
    gp = defaultdict(lambda: {'ses': 0, 'n': 0, 'pal': 0, 'breves': 0, 'areas': set(), 'ult': None})
    for ar in areas:
        for pr in ar['profs']:
            g = gp[pr['prof']]
            g['ses'] += pr['ses']
            g['n'] += pr['notas']
            g['breves'] += pr['breves']
            g['pal'] += pr['palabras_prom'] * pr['notas']
            g['areas'].add(ar['nombre'])
            if pr['ultima'] and (g['ult'] is None or pr['ultima'] > g['ult']):
                g['ult'] = pr['ultima']
    profs = [{'prof': k, 'ses': g['ses'], 'notas': g['n'], 'pct': _pct(g['n'], g['ses']),
              'palabras_prom': round(g['pal'] / g['n'], 1) if g['n'] else 0.0, 'pct_breves': _pct(g['breves'], g['n']),
              'areas': sorted(g['areas']), 'ultima': g['ult']} for k, g in gp.items()]
    profs.sort(key=lambda x: -x['ses'])
    tot_n = sum(a_['n_notas'] for a_ in areas)
    tot_s = sum(a_['sesiones'] for a_ in areas)
    return {
        'areas': areas, 'profs': profs, 'total_notas': tot_n, 'total_sesiones': tot_s, 'pct': _pct(tot_n, tot_s),
        'areas_sin_notas': [a_['nombre'] for a_ in areas if a_['sesiones'] >= 3 and a_['n_notas'] == 0],
        'n_areas': len(areas),
        'aviso': ('Contenido clínico confidencial: son las notas que escriben los profesionales. No se incluye en el PDF para la familia. '
                  'El «tono» es un análisis automático por palabras clave (orientativo): no reemplaza la lectura clínica.'),
    }


# ─────────────────────────────────────────────────────────────────────
# SEMÁFORO Y HALLAZGOS
# ─────────────────────────────────────────────────────────────────────
def _semaforo(a):
    M, cb, rg, pl = a['M'], a['cobranza'], a['riesgo'], a['plan']
    crit = []

    def add(nombre, valor, estado, regla, peso, detalle):
        crit.append({'nombre': nombre, 'valor': es_num(valor), 'estado': estado, 'color': COLOR[estado],
                     'regla': es_num(regla), 'peso': peso, 'detalle': es_num(detalle)})

    def nivel(v, verde, ambar, mayor=True):
        if mayor:
            return VERDE if v >= verde else (AMBAR if v >= ambar else ROJO)
        return VERDE if v <= verde else (AMBAR if v <= ambar else ROJO)

    inactivo = rg['nivel'] == 'inactivo'
    if not inactivo:
        add('Riesgo de abandono', f"{rg['nivel'].upper()}" + (f" · {rg['dias_sin']} días sin asistir" if rg['dias_sin'] is not None else ''),
            {'bajo': VERDE, 'medio': AMBAR, 'alto': ROJO}[rg['nivel']],
            f"Verde: sin señales · Ámbar: {rg['umbral_obs']}+ días sin asistir o señales de caída · Rojo: {rg['umbral_riesgo']}+ días sin sesiones agendadas o 3 inasistencias seguidas",
            2.0, '; '.join(rg['motivos'][:2]))
    if M['base'] >= 4:
        add('Asistencia en el período', f"{M['tasa_asistencia']}%", nivel(M['tasa_asistencia'], 85, 70),
            'Verde ≥ 85% · Ámbar 70–85% · Rojo < 70%', 1.5,
            f"{M['atendidas']} asistidas de {M['base']} sesiones que debía tener (faltas {M['faltas']}, permisos {M['permisos']}).")
    if M['atendidas'] >= 4:
        add('Puntualidad', f"{M['puntualidad']}%", nivel(M['puntualidad'], 80, 60),
            'Verde ≥ 80% · Ámbar 60–80% · Rojo < 60% de las sesiones sin retraso', 0.75,
            f"{M['retrasos']} sesiones con retraso" + (f", promedio {M['retraso_prom']:.0f} min." if M['retrasos'] else '.'))
    if cb['tot']['gen'] > 0:
        add('Mora de pago (más de 30 días)', f"{cb['pct_mora30']}% · Bs. {cb['mora30']:,.0f}",
            nivel(cb['pct_mora30'], 8, 18, mayor=False), 'Verde ≤ 8% · Ámbar 8–18% · Rojo > 18% de lo generado', 1.5,
            f"Cobrado {cb['tot']['pct']}% de lo generado; pendiente Bs. {cb['tot']['pend']:,.0f}.")
    if cb['dias_pago_prom'] is not None and cb['n_pagadas'] >= 3:
        add('Rapidez de pago', f"{cb['dias_pago_prom']} días en promedio", nivel(cb['dias_pago_prom'], 7, 15, mayor=False),
            'Verde ≤ 7 días · Ámbar 8–15 · Rojo > 15 días desde la sesión hasta que se paga', 0.75,
            f"{cb['pct_pago_7d']}% de las sesiones pagadas se pagó dentro de la semana.")
    if pl['cumplimiento'] is not None and not inactivo:
        add('Cumplimiento del plan', f"{pl['cumplimiento']}% ({pl['real_sem']}/{pl['plan_sem']} ses./semana)",
            nivel(pl['cumplimiento'], 85, 60), 'Verde ≥ 85% · Ámbar 60–85% · Rojo < 60% de la frecuencia planificada', 1.0,
            'Sesiones reales por semana (últimas 4 semanas) frente a la frecuencia del plan de trabajo vigente.')
    if rg['variacion'] is not None and rg['n30p'] >= 3 and not inactivo:
        add('Tendencia de asistencia', f"{rg['variacion']:+.0f}% ({rg['n30p']} → {rg['n30']} sesiones)",
            nivel(rg['variacion'], -15, -40), 'Verde ≥ −15% · Ámbar −15 a −40% · Rojo < −40% frente a los 30 días anteriores', 1.0,
            'Compara las sesiones asistidas de los últimos 30 días con las de los 30 anteriores.')
    pesos = sum(c['peso'] for c in crit)
    score = sum(PUNTOS[c['estado']] * c['peso'] for c in crit) / pesos if pesos else None
    if score is None:
        ver, msg, color = 'sin_datos', 'No hay datos suficientes para un veredicto.', '#64748b'
    elif score >= 0.75:
        ver, msg, color = 'solido', 'Paciente ESTABLE: asiste, paga y cumple su plan.', '#16a34a'
    elif score >= 0.5:
        ver, msg, color = 'aceptable', 'Paciente EN OBSERVACIÓN: hay señales que conviene atender.', '#d97706'
    elif score >= 0.3:
        ver, msg, color = 'bajo', 'Paciente con RIESGO MEDIO: conviene contactar a la familia.', '#ea580c'
    else:
        ver, msg, color = 'critico', 'Paciente con RIESGO DE ABANDONO: contactar a la familia cuanto antes.', '#dc2626'
    if inactivo:
        pend = cb['tot']['pend']
        ver, color, score = 'inactivo', '#475569', None
        msg = es_num('Paciente INACTIVO. ' + (f"Tiene Bs. {pend:,.2f} pendientes de cobro de lo generado en el período: gestionar el cobro."
                                              if pend > 0 else 'No tiene saldos pendientes de lo generado en el período.'))
    if rg['nivel'] == 'alto' and ver in ('solido', 'aceptable'):
        ver, msg, color = 'bajo', 'Paciente con RIESGO MEDIO: el riesgo de abandono es alto aunque otros criterios estén bien.', '#ea580c'
    return {'criterios': crit, 'score': round(score * 100) if score is not None else None, 'veredicto': ver, 'msg': msg,
            'color': color, 'n_verde': sum(1 for c in crit if c['estado'] == VERDE),
            'n_ambar': sum(1 for c in crit if c['estado'] == AMBAR), 'n_rojo': sum(1 for c in crit if c['estado'] == ROJO),
            'nota': 'Veredicto orientativo con criterios visibles; la decisión final es del equipo.'}


def _hallazgos(a):
    M, cb, rg, pl, vl, px, sv = a['M'], a['cobranza'], a['riesgo'], a['plan'], a['valor'], a['proximas'], a['servicios']
    cl, cp, mt = a['clinico'], a['comparacion'], a['motivos']
    h = []

    def add(tipo, txt, accion=''):
        h.append({'tipo': tipo, 'txt': es_num(txt), 'accion': accion})
    if rg['nivel'] == 'inactivo':
        add('nota', rg['motivos'][0], 'Si la familia desea retomar las terapias, reactivar al paciente y agendar sesiones.')
        if cb['tot']['pend'] > 0:
            add('alerta', f"Aunque está inactivo, tiene Bs. {cb['tot']['pend']:,.2f} pendientes de cobro de lo generado en el período.",
                'Gestionar el cobro del saldo pendiente.')
    if rg['nivel'] == 'alto':
        add('alerta', 'Riesgo ALTO de abandono: ' + ' '.join(rg['motivos'][:2]), 'Contactar hoy al tutor, entender el motivo y ofrecer un horario alternativo.')
    elif rg['nivel'] == 'medio':
        add('nota', 'Riesgo MEDIO de abandono: ' + ' '.join(rg['motivos'][:2]), 'Llamar o escribir al tutor esta semana para confirmar asistencia.')
    if rg['mens_sin_renovar']:
        add('alerta', 'No renovó la mensualidad de este mes.', 'Consultar si continuará y ofrecer renovar o ajustar el plan.')
    if cb['tot']['gen'] > 0:
        add('info', f"Cobranza del período: de Bs. {cb['tot']['gen']:,.2f} generados se cobró Bs. {cb['tot']['cobrado']:,.2f} ({cb['tot']['pct']}%); "
                    f"falta Bs. {cb['tot']['pend']:,.2f}.")
        if cb['mora30'] > 0:
            add('alerta', f"Mora: Bs. {cb['mora30']:,.2f} llevan más de 30 días sin pagarse ({cb['pct_mora30']}% de lo generado).",
                'Coordinar un plan de pago con el tutor y priorizar el cobro de lo más antiguo.')
        if cb['dias_pago_prom'] is not None and cb['dias_pago_prom'] > 15 and cb['n_pagadas'] >= 3:
            add('nota', f"Tarda en promedio {cb['dias_pago_prom']} días en pagar cada sesión.", 'Recordarle la fecha de pago o proponer pago por adelantado / mensualidad.')
    cc = a.get('cuenta')
    if cc and cc['saldo_actual'] < 0:
        add('alerta', f"Saldo en contra de la cuenta corriente: Bs. {abs(cc['saldo_actual']):,.2f}.", 'Revisar el estado de cuenta con el tutor.')
    elif cc and cc['credito'] > 0:
        add('ok', f"Tiene crédito a favor de Bs. {cc['credito']:,.2f} para próximas sesiones.")
    if M['base'] >= 4 and M['tasa_asistencia'] < 70:
        add('alerta', f"Asistencia baja en el período: {M['tasa_asistencia']}%.", 'Revisar motivos y reforzar la confirmación de citas (recordatorio un día antes).')
    elif M['base'] >= 4 and M['tasa_asistencia'] >= 90:
        add('ok', f"Asistencia excelente en el período: {M['tasa_asistencia']}%.")
    if M['atendidas'] >= 4 and M['puntualidad'] < 60:
        add('nota', f"Llega tarde con frecuencia: solo {M['puntualidad']}% de sus sesiones son puntuales.", 'Conversar con la familia sobre el horario de llegada o mover la sesión.')
    pt = a['patron']
    if pt['peores']:
        w = pt['peores'][0]
        add('info', f"Asiste menos los {w['dia'].lower()} a las {w['hora']} ({w['tasa']}% en {w['n']} citas).", 'Ofrecer cambiar esa sesión a su franja de mejor asistencia.' + (f" Mejor franja: {pt['mejores'][0]['dia'].lower()} a las {pt['mejores'][0]['hora']} ({pt['mejores'][0]['tasa']}%)." if pt['mejores'] else ''))
    if pl['sin_plan']:
        add('nota', 'No tiene un plan de trabajo vigente.', 'Registrar el plan con área de intervención, frecuencia y fecha de revisión.')
    else:
        if pl['revisiones_vencidas']:
            add('alerta', f"{pl['revisiones_vencidas']} plan(es) con revisión vencida.", 'Programar la revisión del plan con el profesional responsable.')
        if pl['cumplimiento'] is not None and pl['cumplimiento'] < 60:
            add('alerta', f"Cumple solo el {pl['cumplimiento']}% de la frecuencia planificada ({pl['real_sem']} de {pl['plan_sem']} sesiones por semana).",
                'Revisar la agenda: faltan sesiones para cumplir el plan.')
    for s in sv['items']:
        if s['alerta'] and s['activo'] is not False:
            hace = 'sin ninguna sesión asistida' if s['dias_sin'] is None else 'hace ' + str(s['dias_sin']) + ' días'
            add('nota', "Servicio «" + s['nombre'] + "» activo sin uso (" + hace + ").", 'Agendar sesiones o dar de baja el servicio si ya no se necesita.')
    if vl['dejado'] > 0 and vl['pct_dejado'] >= 10:
        add('info', f"Se dejó de cobrar Bs. {vl['dejado']:,.2f} ({vl['pct_dejado']}% de lo que correspondía) por descuentos, gratuidades o paquetes con descuento.")
    if vl['exen_v'] > 0:
        add('info', f"Exenciones: {vl['exen_n']} sesión(es) no cobradas por Bs. {vl['exen_v']:,.2f} (permisos, cancelaciones o reprogramaciones).")
    if vl['margen'] is not None and vl['margen_pct'] is not None:
        add('ok' if vl['margen'] >= 0 else 'alerta', f"Con el costo por hora ingresado, su margen en el período es Bs. {vl['margen']:,.2f} ({vl['margen_pct']}%).")
    if cp and cp['filas']:
        asis = next(x for x in cp['filas'] if x['k'].startswith('Asistencia'))
        if asis.get('centro') is not None and M['base'] >= 4:
            dif = round(asis['act'] - asis['centro'], 1)
            if abs(dif) >= 8:
                add('ok' if dif > 0 else 'nota', f"Su asistencia ({asis['act']}%) está {abs(dif)} puntos {'por encima' if dif > 0 else 'por debajo'} del promedio del centro ({asis['centro']}%).")
    if cl['sesiones'] and cl['pct_nota'] < 70:
        add('nota', f"Solo {cl['pct_nota']}% de las sesiones realizadas tiene nota de evolución ({len(cl['sin_nota'])} recientes sin nota).",
            'Pedir a los profesionales completar las notas de evolución.')
    if cl['informes_pend']:
        add('nota', f"{cl['informes_pend']} informe(s) de evaluación sin finalizar.", 'Finalizar y entregar los informes pendientes.')
    if cl['proy_sin_informe']:
        add('nota', f"{len(cl['proy_sin_informe'])} proyecto(s) finalizado(s) sin informe entregado: " + ', '.join(p['codigo'] for p in cl['proy_sin_informe'][:3]) + '.',
            'Entregar el informe a la familia y registrar la entrega.')
    if cl['dias_ult_eval'] is not None and cl['dias_ult_eval'] > 365:
        add('info', f"La última evaluación fue hace {cl['dias_ult_eval']} días.", 'Considerar una reevaluación para medir el avance.')
    if px['n7'] == 0 and rg['proxima'] is None and rg['nivel'] != 'inactivo':
        add('alerta', 'No tiene sesiones agendadas.', 'Agendar las próximas sesiones antes de que se pierda la continuidad.')
    if px['por_cobrar'] > 0:
        add('info', f"Sesiones agendadas por Bs. {px['esperado']:,.2f}; ya pagó por adelantado Bs. {px['adelantado']:,.2f} (por cobrar Bs. {px['por_cobrar']:,.2f}).")
    ev = a.get('evolucion')
    if ev:
        for ar in ev['areas']:
            if ar['tendencia'] == 'con más dificultades':
                add('alerta', f"Área {ar['nombre']}: las notas recientes reflejan más dificultades que las del inicio (balance {ar['neto_ini']:+.0f}% → {ar['neto_fin']:+.0f}%).",
                    'Revisar objetivos y estrategia con el profesional del área.')
            elif ar['tendencia'] == 'mejorando':
                add('ok', f"Área {ar['nombre']}: las notas muestran una evolución favorable (balance {ar['neto_ini']:+.0f}% → {ar['neto_fin']:+.0f}%).")
            if ar['sesiones'] >= 4 and ar['pct_nota'] < 50:
                add('nota', f"Área {ar['nombre']}: solo {ar['pct_nota']}% de las sesiones tiene nota de evolución.", 'Pedir al profesional registrar la evolución en cada sesión.')
            if ar['n_notas'] >= 5 and ar['pct_breves'] >= 50:
                add('nota', f"Área {ar['nombre']}: {ar['pct_breves']}% de las notas tiene menos de {BREVE} palabras; es difícil analizar la evolución.", 'Pedir notas con más detalle (objetivo trabajado, respuesta y observaciones).')
        if ev['areas_sin_notas']:
            add('nota', 'Sin ninguna nota de evolución en: ' + ', '.join(ev['areas_sin_notas']) + '.', 'Registrar notas de evolución en esas áreas.')
    if sv['cambios_total'] >= 3:
        add('nota', f"Cambió de profesional {sv['cambios_total']} veces.", 'Procurar continuidad con un mismo profesional por servicio.')
    return h


# ─────────────────────────────────────────────────────────────────────
# FUNCIÓN PRINCIPAL
# ─────────────────────────────────────────────────────────────────────
def analizar_paciente(paciente, desde=None, hasta=None, hoy=None, filtros=None, costo_hora=0.0, comparar=True,
                      umbral_obs=UMBRAL_OBS, umbral_riesgo=UMBRAL_RIESGO):
    hoy = hoy or date.today()
    filtros = {k: v for k, v in (filtros or {}).items() if v}
    rows = _cargar_sesiones(paciente)
    ps_precio = {}
    from pacientes.models import PacienteServicio
    for x in PacienteServicio.objects.filter(paciente=paciente).values('servicio_id', 'costo_sesion'):
        ps_precio[x['servicio_id']] = _f(x['costo_sesion'])

    def precio(s):
        return ps_precio.get(s['sid']) or s['base']
    pagos = _cargar_pagos(paciente)
    proy, mens = _cargar_paquetes(paciente)
    for s in rows:
        s['monto_prog'] = (s['monto'] or s['monto_orig'] or precio(s)) if (s['estado'] == 'programada' and s['tipo'] == 'individual') else 0.0
    S = [s for s in rows if _en_rango(s['fecha'], desde, hasta) and _pasa(s, filtros)]
    M = _metricas(S)
    gen = _generado(S, rows, proy, mens, precio)
    cobranza = _cobranza(S, gen, pagos, desde, hasta, hoy)
    riesgo = _riesgo(paciente, rows, mens, hoy, umbral_obs, umbral_riesgo)
    valor = _valor(S, rows, gen, proy, mens, M, riesgo, costo_hora, desde, hasta, hoy)
    lista = valor.pop('ranking_lista')
    pos = next((i for i, (pid, _t) in enumerate(lista, 1) if pid == paciente.id), None)
    valor['ranking'] = {'pos': pos, 'de': len(lista)} if pos else None
    plan = _plan(paciente, rows, hoy)
    clinico = _clinico(paciente, S, proy, hoy)
    cuenta = None
    try:
        cc = getattr(paciente, 'cuenta_corriente', None)
        if cc is not None:
            cuenta = {'saldo_actual': _f(cc.saldo_actual), 'saldo_real': _f(cc.saldo_real), 'credito': _f(cc.pagos_adelantados),
                      'total_pagado': _f(cc.total_pagado), 'consumido': _f(cc.total_consumido_actual),
                      'consumido_real': _f(cc.total_consumido_real), 'uso_credito': _f(cc.uso_credito)}
    except Exception:
        cuenta = None
    proximas = _proximas(rows, pagos, precio, hoy)
    # saldo de paquetes y cobro esperado del próximo mes
    paq_saldo = []
    for p in proy + mens:
        if p['estado'] in ('cancelado', 'cancelada'):
            continue
        pagado = sum(m for _f_, m, _mp in pagos[p['clave']].get(p['id'], []))
        if p['valor'] - pagado > 0.005 and p['ref'] <= hoy:
            paq_saldo.append({'codigo': p['codigo'], 'nombre': p['nombre'], 'clave': p['clave'], 'valor': p['valor'],
                              'pagado': round(min(pagado, p['valor']), 2), 'saldo': round(p['valor'] - pagado, 2),
                              'dias': max((hoy - p['ref']).days, 0)})
    paq_saldo.sort(key=lambda x: -x['saldo'])
    activa = next((m for m in mens if m['estado'] == 'activa' and (m['anio'], m['mes']) == (hoy.year, hoy.month)), None)
    proximas['mens_prox'] = round(activa['valor'], 2) if activa else 0.0
    a = {
        'paciente': paciente, 'desde': desde, 'hasta': hasta, 'hoy': hoy, 'filtros': filtros, 'M': M, 'gen': gen,
        'cobranza': cobranza, 'riesgo': riesgo, 'valor': valor, 'plan': plan, 'clinico': clinico, 'cuenta': cuenta,
        'proximas': proximas, 'paq_saldo': paq_saldo, 'patron': _patron(S), 'calendarios': _calendarios(S, desde, hasta, hoy),
        'servicios': _servicios(paciente, rows, hoy, S), 'motivos': _motivos(S), 'evolucion': _evolucion(S, hoy),
        'comparacion': _comparar(rows, precio, proy, mens, filtros, desde, hasta, hoy, gen, M) if comparar else None,
        'n_sesiones_hist': len(rows),
    }
    a['timeline'] = _linea_tiempo(paciente, rows, proy, mens, clinico, plan['planes'], _devoluciones(paciente), hoy)
    a['semaforo'] = _semaforo(a)
    a['hallazgos'] = _hallazgos(a)
    # serie por mes / semana / día para los gráficos de evolución
    a['series'] = _series(S, precio, proy, mens, rows)
    return a


def _series(S, precio, proy, mens, rows):
    def agrupar(clave_fn, label_fn):
        g = defaultdict(list)
        for s in S:
            g[clave_fn(s['fecha'])].append(s)
        out = []
        for k in sorted(g):
            m = _metricas(g[k])
            out.append({'key': k, 'label': label_fn(k), 'atend': m['atendidas'], 'faltas': m['faltas'], 'permisos': m['permisos'],
                        'asistencia': m['tasa_asistencia'] if m['base'] else None, 'horas': round(m['min'] / 60.0, 1),
                        'gen': round(sum(s['monto'] for s in g[k] if s['tipo'] == 'individual' and s['estado'] in CONSUMIDAS), 2)})
        return out
    meses = agrupar(lambda f: (f.year, f.month), lambda k: f"{MESES_ES[k[1]][:3]} {str(k[0])[2:]}")
    semanas = agrupar(lambda f: f - timedelta(days=f.weekday()), lambda k: k.strftime('%d/%m'))
    dias = agrupar(lambda f: f, lambda k: k.strftime('%d/%m')) if len({s['fecha'] for s in S}) <= 120 else []

    def pack(lst):
        return {'labels': [x['label'] for x in lst], 'atend': [x['atend'] for x in lst], 'faltas': [x['faltas'] for x in lst],
                'permisos': [x['permisos'] for x in lst], 'asistencia': [x['asistencia'] for x in lst],
                'horas': [x['horas'] for x in lst], 'gen': [x['gen'] for x in lst]}
    return {'meses': pack(meses), 'semanas': pack(semanas), 'dias': pack(dias), 'tabla_meses': meses}
