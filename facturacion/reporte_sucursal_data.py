# facturacion/reporte_sucursal_data.py
# =====================================================================
# MOTOR DE DATOS DEL REPORTE POR SUCURSAL
# Lo usan la vista (pantalla) y el generador de PDF, para que ambos
# muestren exactamente los mismos números.
#
# BASE: reutiliza analizar() del reporte por profesional (una pasada por
# cada profesional de la sucursal) y consolida. Así los números de la
# sucursal CUADRAN con los de cada profesional.
#
# CRITERIOS (iguales a los del reporte por profesional):
#   · Generado  = sesiones individuales por su monto cobrado (incluye falta
#                 sin aviso) + parte ponderada de proyectos y mensualidades.
#   · Neto del centro = generado − comisión de profesionales externos.
#   · Horas de reloj, horarios vacíos por causa y ocupación: igual que el
#     reporte profesional (horario de Asistencia o predeterminado).
#
# GASTOS (el dueño decide qué cuenta):
#   · Egresos registrados en el sistema (app egresos), por período contable
#     (periodo_mes/periodo_anio), prorrateados por días en meses parciales.
#       - De la sucursal: 100 %.
#       - Globales (sin sucursal): según el reparto elegido (horas / iguales / no).
#   · Cuadros manuales: concepto + monto, «mensual» (se prorratea por mes
#     calendario) o «total del período».
#   · Costo mensual por profesional (opcional).
#   · Personal/honorarios ya registrados: se excluyen si el dueño ingresó
#     costos por profesional (evita contar dos veces el mismo sueldo).
#
# RENTABILIDAD POR PACIENTE:
#   neto del paciente = generado × (neto_centro / generado_total)
#   costo directo   = costo del profesional repartido por minutos atendidos
#   costo indirecto = resto de los gastos repartido por minutos atendidos
# =====================================================================

import calendar
import logging
from collections import defaultdict
from datetime import date, timedelta

from django.db.models import Q, Sum

from .reporte_profesional_data import (
    ATENDIDAS, CONSUMIDAS, DIAS_ES, DIAS_CORTO, MESES_ES, MESES_CORTO, MAX_DIAS,
    HORA_HEAT_INI, HORA_HEAT_FIN, analizar, hm, es_num, _pct, _f,
)
from .reporte_profesional_extra import VERDE, AMBAR, ROJO, COLOR, PUNTOS

logger = logging.getLogger(__name__)

PERSONAL_TIPOS = ('personal', 'honorarios')
GLOB_OPCIONES = (
    ('horas', 'Proporcional a las horas atendidas de cada sucursal'),
    ('igual', 'En partes iguales entre las sucursales activas'),
    ('no', 'No incluir gastos globales'),
)
MAX_MANUALES = 12


class TodasSucursales:
    """Pseudo-sucursal para el consolidado de TODAS las sucursales (sin filtro por sucursal)."""
    es_todas = True
    id = None
    pk = None
    nombre = 'Todas las sucursales'
    activa = True
    direccion = ''
    telefono = ''
    email = ''

    def __str__(self):
        return self.nombre


def _todas(suc):
    return getattr(suc, 'es_todas', False)


def _kw(suc, campo):
    """Filtro por sucursal para una consulta: vacío cuando es el consolidado de todas."""
    return {} if _todas(suc) else {campo: suc}


def _q_egr(suc):
    """Egresos de la sucursal + globales; en el consolidado, todos."""
    return Q() if _todas(suc) else (Q(sucursal=suc) | Q(sucursal__isnull=True))


# ─────────────────────────────────────────────────────────────────────
# LECTURA DE PARÁMETROS (cuadros del dueño)
# ─────────────────────────────────────────────────────────────────────
def _num(txt):
    try:
        return max(float(str(txt or '0').strip().replace(',', '.')), 0.0)
    except (ValueError, TypeError):
        return 0.0


def leer_gastos_manuales(get):
    """Filas de gasto ingresadas por el dueño: g_concepto[], g_monto[], g_freq[]."""
    conceptos = get.getlist('g_concepto')
    montos = get.getlist('g_monto')
    freqs = get.getlist('g_freq')
    filas = []
    for i, m in enumerate(montos[:MAX_MANUALES]):
        monto = _num(m)
        if monto <= 0:
            continue
        concepto = (conceptos[i] if i < len(conceptos) else '').strip()[:60] or f'Gasto manual {len(filas) + 1}'
        freq = freqs[i] if i < len(freqs) and freqs[i] in ('mensual', 'periodo') else 'mensual'
        filas.append({'concepto': concepto, 'monto': monto, 'freq': freq})
    return filas


def leer_costos_profesional(get):
    """Costo mensual opcional por profesional: cp_<id>=monto."""
    out = {}
    for k, v in get.items():
        if k.startswith('cp_'):
            try:
                pid = int(k[3:])
            except ValueError:
                continue
            monto = _num(v)
            if monto > 0:
                out[pid] = monto
    return out


# ─────────────────────────────────────────────────────────────────────
# GASTOS
# ─────────────────────────────────────────────────────────────────────
def _ventanas(desde, hasta):
    """[(anio, mes, d0, d1, frac)]: frac = días de la ventana ÷ días del mes."""
    out, d = [], desde
    while d <= hasta:
        ultimo = calendar.monthrange(d.year, d.month)[1]
        d1 = min(date(d.year, d.month, ultimo), hasta)
        dias = (d1 - d).days + 1
        out.append((d.year, d.month, d, d1, dias / ultimo))
        d = d1 + timedelta(days=1)
    return out


def _share_global(suc, desde, hasta, modo):
    """Fracción de los egresos globales que se carga a esta sucursal."""
    from agenda.models import Sesion
    from servicios.models import Sucursal
    if _todas(suc):
        return 1.0                # consolidado: todos los gastos globales cuentan completos
    if modo == 'no':
        return 0.0
    ids = list(Sucursal.objects.filter(activa=True).values_list('id', flat=True))
    if suc.id not in ids:
        ids.append(suc.id)
    n = len(ids) or 1
    if modo == 'igual':
        return 1.0 / n
    rows = (Sesion.objects.filter(fecha__gte=desde, fecha__lte=hasta, estado__in=ATENDIDAS)
            .values('sucursal_id').annotate(m=Sum('duracion_minutos')))
    tot = sum(_f(x['m']) for x in rows)
    mio = sum(_f(x['m']) for x in rows if x['sucursal_id'] == suc.id)
    return (mio / tot) if tot else 1.0 / n


def calcular_gastos(suc, desde, hasta, manuales, cp, nombres_prof, glob='horas',
                    inc_egr=True, inc_pers=True, share_glob=None):
    """Gastos de la sucursal en [desde, hasta], con desglose y serie mensual."""
    vent = _ventanas(desde, hasta)
    n_dias = (hasta - desde).days + 1
    mens = {(y, m): {'oper': 0.0, 'pers': 0.0} for y, m, *_ in vent}
    frac = {(y, m): f for y, m, _a, _b, f in vent}
    filas = []

    # 1) cuadros manuales
    for g in manuales:
        tot = 0.0
        for y, m, d0, d1, f in vent:
            dias = (d1 - d0).days + 1
            v = g['monto'] * f if g['freq'] == 'mensual' else g['monto'] * dias / n_dias
            mens[(y, m)]['oper'] += v
            tot += v
        filas.append({'origen': 'manual', 'concepto': g['concepto'], 'categoria': 'Ingresado por el dueño',
                      'detalle': (f"Bs. {g['monto']:,.2f}/mes" if g['freq'] == 'mensual'
                                  else f"Bs. {g['monto']:,.2f} total del período"),
                      'monto': round(tot, 2), 'es_pers': False})

    # 2) costo mensual por profesional (personal)
    for pid, monto in cp.items():
        tot = 0.0
        for y, m, d0, d1, f in vent:
            mens[(y, m)]['pers'] += monto * f
            tot += monto * f
        filas.append({'origen': 'profesional', 'concepto': f"Costo de {nombres_prof.get(pid, 'profesional')}",
                      'categoria': 'Personal / profesionales',
                      'detalle': f"Bs. {monto:,.2f}/mes", 'monto': round(tot, 2), 'es_pers': True})

    # 3) egresos registrados en el sistema
    excl_pers = 0.0
    omit_glob = 0.0
    detalle_egr = []
    if inc_egr:
        from egresos.models import CategoriaEgreso, Egreso
        if share_glob is None:
            share_glob = _share_global(suc, desde, hasta, glob)
        qs = (Egreso.objects.filter(anulado=False,
                                    periodo_anio__gte=desde.year, periodo_anio__lte=hasta.year)
              .filter(_q_egr(suc))
              .select_related('categoria', 'proveedor'))
        # los que no tienen período se ubican por la fecha de pago
        qs_nulos = (Egreso.objects.filter(anulado=False, periodo_anio__isnull=True,
                                          fecha__gte=desde, fecha__lte=hasta)
                    .filter(_q_egr(suc))
                    .select_related('categoria', 'proveedor'))
        cat_acum = {}
        vistos = set()
        for e in list(qs) + list(qs_nulos):
            if e.id in vistos:
                continue
            vistos.add(e.id)
            y = e.periodo_anio or e.fecha.year
            m = e.periodo_mes or e.fecha.month
            if (y, m) not in mens:
                continue
            cat = e.categoria
            es_pers = cat.tipo in PERSONAL_TIPOS or cat.es_honorario_profesional
            glob_ = e.sucursal_id is None
            base = float(e.monto) * frac[(y, m)]
            if es_pers and not inc_pers:
                excl_pers += base * (share_glob if glob_ else 1.0)
                continue
            if glob_ and share_glob <= 0:
                omit_glob += base
                continue
            v = base * (share_glob if glob_ else 1.0)
            mens[(y, m)]['pers' if es_pers else 'oper'] += v
            k = (cat.nombre, cat.tipo, glob_, es_pers)
            a = cat_acum.setdefault(k, {'monto': 0.0, 'n': 0})
            a['monto'] += v
            a['n'] += 1
            if len(detalle_egr) < 300:
                detalle_egr.append({
                    'numero': e.numero_egreso, 'fecha': e.fecha, 'concepto': e.concepto,
                    'categoria': cat.nombre, 'proveedor': e.proveedor.nombre if e.proveedor else '',
                    'monto_total': float(e.monto), 'monto': round(v, 2),
                    'origen': 'Global (prorrateado)' if glob_ else 'Sucursal',
                })
        tipo_txt = dict(CategoriaEgreso.TIPO_CHOICES)
        for (nombre, tipo, glob_, es_pers), a in sorted(cat_acum.items(), key=lambda kv: -kv[1]['monto']):
            filas.append({'origen': 'global' if glob_ else 'registrado', 'concepto': nombre,
                          'categoria': tipo_txt.get(tipo, tipo),
                          'detalle': f"{a['n']} egreso(s)" + (' · prorrateado' if glob_ else ''),
                          'monto': round(a['monto'], 2), 'es_pers': es_pers})
        detalle_egr.sort(key=lambda x: (x['fecha'], x['numero']))
    else:
        share_glob = share_glob if share_glob is not None else 0.0

    total_oper = sum(v['oper'] for v in mens.values())
    total_pers = sum(v['pers'] for v in mens.values())
    total = total_oper + total_pers
    for f_ in filas:
        f_['pct'] = _pct(f_['monto'], total)
    filas.sort(key=lambda x: -x['monto'])
    return {
        'filas': filas, 'detalle_egresos': detalle_egr,
        'total_oper': round(total_oper, 2), 'total_pers': round(total_pers, 2),
        'total': round(total, 2),
        'manual_total': round(sum(f['monto'] for f in filas if f['origen'] == 'manual'), 2),
        'prof_total': round(sum(f['monto'] for f in filas if f['origen'] == 'profesional'), 2),
        'reg_total': round(sum(f['monto'] for f in filas if f['origen'] in ('registrado', 'global')), 2),
        'excl_pers': round(excl_pers, 2), 'omit_glob': round(omit_glob, 2),
        'share_glob': round(share_glob or 0.0, 4), 'glob': glob,
        'inc_egr': inc_egr, 'inc_pers': inc_pers,
        'por_mes': {k: {'oper': round(v['oper'], 2), 'pers': round(v['pers'], 2),
                        'total': round(v['oper'] + v['pers'], 2)} for k, v in mens.items()},
    }


# ─────────────────────────────────────────────────────────────────────
# PROFESIONALES DE LA SUCURSAL + AGREGACIÓN
# ─────────────────────────────────────────────────────────────────────
def _profesionales_de(suc, desde, hasta):
    from agenda.models import Sesion
    from profesionales.models import Profesional
    ids = set(Sesion.objects.filter(fecha__gte=desde, fecha__lte=hasta, **_kw(suc, 'sucursal'))
              .values_list('profesional_id', flat=True).distinct())
    activos = Q(activo=True) if _todas(suc) else Q(activo=True, sucursales=suc)
    return list(Profesional.objects.filter(Q(id__in=ids) | activos)
                .distinct().select_related('user').prefetch_related('servicios')
                .order_by('apellido', 'nombre'))


def _correr(suc, desde, hasta, cp, manual_cfg, forzar_manual, hoy, profs=None):
    """Una pasada de analizar() por profesional → [(prof, r)]."""
    items = []
    for prof in (profs if profs is not None else _profesionales_de(suc, desde, hasta)):
        try:
            r = analizar(prof, desde, hasta, sucursal_id=(None if _todas(suc) else str(suc.id)), manual_cfg=manual_cfg,
                         forzar_manual=forzar_manual, hoy=hoy, comparar=False,
                         costo_mensual=cp.get(prof.id, 0.0), completo=False)
            items.append((prof, r))
        except Exception:
            logger.error('Reporte sucursal: error analizando profesional %s', prof.id, exc_info=True)
    return items


_SUMAS = (
    'total', 'realizadas', 'retrasos', 'faltas', 'permisos', 'canceladas', 'reprogramadas',
    'programadas', 'atendidas', 'min_reloj', 'min_pacientes', 'min_faltas', 'min_prog',
    'cap_total', 'cap_el', 'busy_el', 'cap_fut', 'busy_fut', 'extra',
    'h_falta', 'h_permiso', 'h_cancel', 'h_reprog', 'h_sinag', 'h_prog_pas', 'h_perdidas',
    'gen_total', 'gen_ind', 'gen_proy', 'gen_mens', 'gen_proy_solo', 'gen_proy_grupal',
    'gen_mens_solo', 'gen_mens_grupal', 'por_generar', 'ext_prof', 'ext_centro',
    'neto_centro', 'potencial_no_aprovechado', 'costo_periodo',
)


def _agregar(items):
    """Suma los KPI de todos los profesionales y deriva los de la sucursal."""
    k = {key: 0.0 for key in _SUMAS}
    att_el = 0.0
    pacs, pacs_total = set(), set()
    for _prof, r in items:
        kp = r['kpis']
        for key in _SUMAS:
            k[key] += _f(kp.get(key))
        att_el += sum(_f(g.get('att_el')) for g in r['por_mes'])
        for p in r['pacientes']:
            pacs_total.add(p['id'])
            if p['atend']:
                pacs.add(p['id'])
    for key in ('total', 'realizadas', 'retrasos', 'faltas', 'permisos', 'canceladas',
                'reprogramadas', 'programadas', 'atendidas'):
        k[key] = int(k[key])
    k['att_el'] = att_el
    k['pacientes'] = len(pacs)
    k['pacientes_total'] = len(pacs_total)
    k['profesionales'] = len(items)
    k['profesionales_con_sesiones'] = sum(1 for _p, r in items if r['kpis']['total'])
    base = k['atendidas'] + k['faltas'] + k['permisos']
    k['tasa_asistencia'] = _pct(k['atendidas'], base)
    k['tasa_faltas'] = _pct(k['faltas'], base)
    k['ocup_el'] = _pct(k['busy_el'], k['cap_el'])
    k['ocup_efect'] = _pct(att_el, k['cap_el'])
    k['libre_el'] = max(k['cap_el'] - k['busy_el'], 0)
    k['horas_reloj'] = round(k['min_reloj'] / 60.0, 1)
    k['ingreso_hora'] = round(k['gen_total'] / (k['min_reloj'] / 60.0), 2) if k['min_reloj'] else 0.0
    k['neto_hora'] = round(k['neto_centro'] / (k['min_reloj'] / 60.0), 2) if k['min_reloj'] else 0.0
    k['ingreso_sesion'] = round(k['gen_total'] / k['atendidas'], 2) if k['atendidas'] else 0.0
    k['neto_sesion'] = round(k['neto_centro'] / k['atendidas'], 2) if k['atendidas'] else 0.0
    k['pct_ind'] = _pct(k['gen_ind'], k['gen_total'])
    k['pct_proy'] = _pct(k['gen_proy'], k['gen_total'])
    k['pct_mens'] = _pct(k['gen_mens'], k['gen_total'])
    k['h_no_pagadas'] = k['h_permiso'] + k['h_cancel'] + k['h_reprog'] + k['h_sinag']
    k['pct_perdidas'] = _pct(k['h_perdidas'], k['cap_el'])
    k['pct_sinag'] = _pct(k['h_sinag'], k['cap_el'])
    for key in ('min_reloj', 'min_pacientes', 'min_faltas', 'cap_el', 'busy_el', 'libre_el', 'cap_total',
                'h_falta', 'h_permiso', 'h_cancel', 'h_reprog', 'h_sinag', 'h_prog_pas', 'h_perdidas',
                'h_no_pagadas', 'extra'):
        k[key + '_txt'] = hm(k[key])
    for key in ('gen_total', 'gen_ind', 'gen_proy', 'gen_mens', 'neto_centro', 'ext_prof', 'ext_centro',
                'por_generar', 'potencial_no_aprovechado', 'costo_periodo', 'gen_proy_solo',
                'gen_proy_grupal', 'gen_mens_solo', 'gen_mens_grupal'):
        k[key] = round(k[key], 2)
    return k


# ─────────────────────────────────────────────────────────────────────
# ANÁLISIS PRINCIPAL
# ─────────────────────────────────────────────────────────────────────
def analizar_sucursal(suc, desde, hasta, manuales=None, cp=None, glob='horas', inc_egr=True,
                      inc_pers=None, manual_cfg=None, forzar_manual=False, hoy=None,
                      comparar=True, comparar_sucursales=True):
    from servicios.models import Sucursal

    hoy = hoy or date.today()
    manuales = manuales or []
    cp = cp or {}
    if inc_pers is None:
        inc_pers = not cp          # si hay costos por profesional, no duplicar con los registrados

    nota_rango = ''
    if (hasta - desde).days + 1 > MAX_DIAS:
        hasta = desde + timedelta(days=MAX_DIAS - 1)
        nota_rango = f'El rango se limitó a {MAX_DIAS} días para mantener el reporte ágil.'
    n_dias = (hasta - desde).days + 1

    profs = _profesionales_de(suc, desde, hasta)
    nombres = {p.id: p.nombre_completo for p in profs}
    items = _correr(suc, desde, hasta, cp, manual_cfg, forzar_manual, hoy, profs)
    k = _agregar(items)

    # ── gastos y resultado ─────────────────────────────────────────
    gastos = calcular_gastos(suc, desde, hasta, manuales, cp, nombres, glob, inc_egr, inc_pers)
    G = gastos['total']
    neto = k['neto_centro']
    resultado = round(neto - G, 2)
    k['gastos'] = G
    k['gastos_oper'] = gastos['total_oper']
    k['gastos_pers'] = gastos['total_pers']
    k['resultado'] = resultado
    k['margen_pct'] = round(resultado / neto * 100, 1) if neto else 0.0
    k['cobertura'] = round(neto / G, 2) if G else 0.0
    k['rentable'] = (neto >= G) if G else None
    k['tiene_gastos'] = G > 0
    faltante = max(G - neto, 0.0)
    k['faltante'] = round(faltante, 2)
    k['h_equilibrio'] = round(faltante / k['neto_hora'], 1) if (faltante and k['neto_hora']) else 0.0
    k['ses_equilibrio'] = int(-(-faltante // k['neto_sesion'])) if (faltante and k['neto_sesion']) else 0
    k['gasto_hora'] = round(G / (k['min_reloj'] / 60.0), 2) if (G and k['min_reloj']) else 0.0
    k['gasto_hora_cap'] = round(G / (k['cap_el'] / 60.0), 2) if (G and k['cap_el']) else 0.0
    k['cobrable_libre'] = round(k['h_no_pagadas'] / 60.0 * k['neto_hora'], 2)

    # ── series temporales (mes / semana / día) ─────────────────────
    def _merge_series(campo):
        m = {}
        for _p, r in items:
            for g in r[campo]:
                a = m.setdefault(g['key'], {
                    'key': g['key'], 'label': g['label'], 'sub': g.get('sub', ''),
                    'n_atend': 0, 'n_falta': 0, 'n': 0, 'cap': 0, 'busy_in': 0, 'att_tot': 0,
                    'cap_el': 0, 'busy_el': 0, 'att_el': 0, 'gen': 0.0,
                    'c_falta': 0, 'c_permiso': 0, 'c_cancel': 0, 'c_reprog': 0, 'c_libre': 0})
                for kk in ('n_atend', 'n_falta', 'n', 'cap', 'busy_in', 'att_tot', 'cap_el',
                           'busy_el', 'att_el', 'gen', 'c_falta', 'c_permiso', 'c_cancel',
                           'c_reprog', 'c_libre'):
                    a[kk] += g.get(kk) or 0
        out = []
        for key in sorted(m):
            a = m[key]
            a['ocup_el'] = _pct(a['busy_el'], a['cap_el'])
            a['ocup_efect'] = _pct(a['att_el'], a['cap_el'])
            a['gen'] = round(a['gen'], 2)
            a['att_txt'] = hm(a['att_tot'])
            a['cap_txt'] = hm(a['cap'])
            a['perd_txt'] = hm(a['c_falta'] + a['c_permiso'] + a['c_cancel'] + a['c_reprog'])
            a['sinag_txt'] = hm(a['c_libre'])
            out.append(a)
        return out

    por_mes = _merge_series('por_mes')
    por_semana = _merge_series('por_semana')
    ext_ratio = (neto / k['gen_total']) if k['gen_total'] else 1.0
    for a in por_mes:
        g_mes = gastos['por_mes'].get(a['key'], {'oper': 0.0, 'pers': 0.0, 'total': 0.0})
        a['neto'] = round(a['gen'] * ext_ratio, 2)
        a['gastos'] = g_mes['total']
        a['resultado'] = round(a['neto'] - g_mes['total'], 2)

    # por día (solo rangos moderados)
    por_dia = []
    if n_dias <= 92:
        dm = {}
        for _p, r in items:
            for d in r['por_dia']:
                a = dm.setdefault(d['fecha'], {'fecha': d['fecha'], 'wd': d['wd'], 'n_atend': 0, 'n_falta': 0,
                                               'cap': 0, 'busy_in': 0, 'att_tot': 0, 'gen': 0.0,
                                               'transcurrido': d['transcurrido']})
                for kk in ('n_atend', 'n_falta', 'cap', 'busy_in', 'att_tot', 'gen'):
                    a[kk] += d.get(kk) or 0
        for f in sorted(dm):
            a = dm[f]
            a['gen'] = round(a['gen'], 2)
            a['ocup'] = _pct(a['busy_in'], a['cap']) if a['transcurrido'] else None
            por_dia.append(a)

    # por día de la semana
    wd = {i: {'dia': DIAS_ES[i], 'n_atend': 0, 'att': 0, 'cap': 0, 'busy': 0, 'gen': 0.0} for i in range(7)}
    for _p, r in items:
        for w in r['por_dia_semana']:
            idx = DIAS_ES.index(w['dia'])
            for kk in ('n_atend', 'att', 'cap', 'busy', 'gen'):
                wd[idx][kk] += w.get(kk) or 0
    por_dia_semana = []
    for i in range(7):
        w = wd[i]
        w['ocup'] = _pct(w['busy'], w['cap'])
        w['gen'] = round(w['gen'], 2)
        w['att_txt'] = hm(w['att'])
        w['libre_txt'] = hm(max(w['cap'] - w['busy'], 0))
        por_dia_semana.append(w)

    # mapa de calor consolidado (minutos crudos)
    hc, hb = defaultdict(float), defaultdict(float)
    for _p, r in items:
        raw = r.get('heat_raw') or {}
        for kk, v in (raw.get('cap') or {}).items():
            hc[kk] += v
        for kk, v in (raw.get('busy') or {}).items():
            hb[kk] += v
    heat = []
    for i in range(7):
        celdas = []
        for h in range(HORA_HEAT_INI, HORA_HEAT_FIN):
            cap = hc.get((i, h), 0)
            oc = _pct(min(hb.get((i, h), 0), cap), cap) if cap else None
            celdas.append({'h': h, 'ocup': oc, 'a': round((oc or 0) / 100.0, 2)})
        if any(c['ocup'] is not None for c in celdas):
            heat.append({'dia': DIAS_ES[i], 'dia_c': DIAS_CORTO[i], 'celdas': celdas})
    heat_horas = [f"{h:02d}h" for h in range(HORA_HEAT_INI, HORA_HEAT_FIN)]
    fr = defaultdict(lambda: [0.0, 0.0])
    for (w_, h), cap in hc.items():
        fr[h][0] += cap
        fr[h][1] += min(hb.get((w_, h), 0), cap)
    franjas = [{'h': f"{h:02d}:00 – {h + 1:02d}:00", 'hora': h, 'cap': c, 'busy': b, 'ocup': _pct(b, c),
                'libre': round(c - b), 'libre_txt': hm(c - b)}
               for h, (c, b) in sorted(fr.items()) if c > 0]
    franjas_libres = sorted(franjas, key=lambda x: x['ocup'])[:3]
    franjas_llenas = sorted(franjas, key=lambda x: -x['ocup'])[:3]

    # ── por tipo y por servicio ────────────────────────────────────
    pacientes = _consolidar_pacientes(items)
    por_tipo = []
    for clave, nombre in (('individual', 'Sesiones individuales'), ('proyecto', 'Proyectos / Evaluaciones'),
                          ('mensualidad', 'Mensualidades')):
        a = {'clave': clave, 'nombre': nombre, 'n': 0, 'atend': 0, 'faltas': 0, 'prog': 0, 'min': 0, 'gen': 0.0}
        for _p, r in items:
            for t in r['por_tipo']:
                if t['clave'] == clave:
                    for kk in ('n', 'atend', 'faltas', 'prog', 'min', 'gen'):
                        a[kk] += t.get(kk) or 0
        a['gen'] = round(a['gen'], 2)
        a['pct_gen'] = _pct(a['gen'], k['gen_total'])
        a['horas_txt'] = hm(a['min'])
        a['ingreso_hora'] = round(a['gen'] / (a['min'] / 60.0), 2) if a['min'] else 0.0
        campo = {'individual': 'gen_ind', 'proyecto': 'gen_proy', 'mensualidad': 'gen_mens'}[clave]
        a['pacs'] = sum(1 for p in pacientes if p[campo] > 0)
        por_tipo.append(a)

    sv = {}
    for _p, r in items:
        for s in r['por_servicio']:
            a = sv.setdefault(s['nombre'], {'nombre': s['nombre'], 'color': s['color'], 'n': 0, 'atend': 0,
                                            'faltas': 0, 'min': 0, 'gen': 0.0, 'ind': 0, 'proy': 0, 'mens': 0})
            for kk in ('n', 'atend', 'faltas', 'min', 'gen', 'ind', 'proy', 'mens'):
                a[kk] += s.get(kk) or 0
    por_servicio = []
    for a in sv.values():
        a['gen'] = round(a['gen'], 2)
        a['pct_gen'] = _pct(a['gen'], k['gen_total'])
        a['horas_txt'] = hm(a['min'])
        a['ingreso_hora'] = round(a['gen'] / (a['min'] / 60.0), 2) if a['min'] else 0.0
        a['pacs'] = sum(1 for p in pacientes if a['nombre'] in p['servicios'])
        a['tasa_faltas'] = _pct(a['faltas'], a['atend'] + a['faltas'])
        por_servicio.append(a)
    por_servicio.sort(key=lambda x: -x['gen'])

    # ── proyectos y mensualidades consolidados ─────────────────────
    proyectos, mensualidades = _consolidar_paquetes(items)

    # ── profesionales: rentabilidad individual ─────────────────────
    profesionales = _tabla_profesionales(items, k, gastos)

    # ── pacientes: rentabilidad ────────────────────────────────────
    _rentabilidad_pacientes(pacientes, items, k, gastos)

    # ── concentración ──────────────────────────────────────────────
    conc = _concentracion(profesionales, pacientes, k)

    # ── conciliación con el reporte financiero ─────────────────────
    conciliacion = _conciliar(suc, desde, hasta, k)

    # ── cobranza y caja (con fechas; independiente del devengado) ───
    try:
        cobranza = calcular_cobranza(suc, desde, hasta, hoy, k, proyectos, mensualidades)
    except Exception:
        logger.error('Reporte sucursal: error calculando cobranza', exc_info=True)
        cobranza = None
    if cobranza:
        k['cobrado'] = cobranza['tot']['cobrado']
        k['pendiente_cobro'] = cobranza['tot']['pend']
        k['pct_cobrado'] = cobranza['tot']['pct']
        k['caja_periodo'] = cobranza['caja']['neto']

    # ── desglose de horas por causa ────────────────────────────────
    cap_ = k['cap_el'] or 0
    trabajo = cap_ - (k['h_falta'] + k['h_permiso'] + k['h_cancel'] + k['h_reprog'] + k['h_prog_pas'] + k['h_sinag'])
    partes = [('Trabajo efectivo', trabajo, '#16a34a'),
              ('Falta sin aviso (se cobra)', k['h_falta'], '#dc2626'),
              ('Permiso', k['h_permiso'], '#8b5cf6'),
              ('Cancelada', k['h_cancel'], '#94a3b8'),
              ('Reprogramada', k['h_reprog'], '#0d9488'),
              ('Programada sin registrar', k['h_prog_pas'], '#f59e0b'),
              ('Sin paciente agendado', k['h_sinag'], '#cbd5e1')]
    desglose = [{'label': n, 'min': max(m, 0), 'txt': hm(max(m, 0)),
                 'pct': round(max(m, 0) / cap_ * 100, 1) if cap_ else 0.0, 'color': c}
                for n, m, c in partes]

    # ── período anterior y otras sucursales ────────────────────────
    comparacion = None
    if comparar:
        comparacion = _comparar_periodo_anterior(suc, desde, hasta, k, manuales, cp, nombres, glob,
                                                 inc_egr, inc_pers, manual_cfg, forzar_manual, hoy)
    comparativa = []
    if comparar_sucursales:
        comparativa = _comparar_sucursales(suc, desde, hasta, glob, manual_cfg, forzar_manual, hoy, k, gastos)

    # ── gráficos ───────────────────────────────────────────────────
    graf = {
        'meses': {'labels': [a['label'] for a in por_mes], 'gen': [a['neto'] for a in por_mes],
                  'gastos': [a['gastos'] for a in por_mes], 'resultado': [a['resultado'] for a in por_mes],
                  'atend': [a['n_atend'] for a in por_mes], 'faltas': [a['n_falta'] for a in por_mes],
                  'ocup': [a['ocup_efect'] for a in por_mes],
                  'horas': [round(a['att_tot'] / 60, 1) for a in por_mes]},
        'semanas': {'labels': [a['label'] for a in por_semana], 'gen': [a['gen'] for a in por_semana],
                    'atend': [a['n_atend'] for a in por_semana], 'faltas': [a['n_falta'] for a in por_semana],
                    'ocup': [a['ocup_efect'] for a in por_semana],
                    'horas': [round(a['att_tot'] / 60, 1) for a in por_semana]},
        'dias': {'labels': [d['fecha'].strftime('%d/%m') for d in por_dia], 'gen': [d['gen'] for d in por_dia],
                 'atend': [d['n_atend'] for d in por_dia], 'faltas': [d['n_falta'] for d in por_dia],
                 'ocup': [d['ocup'] for d in por_dia],
                 'horas': [round(d['att_tot'] / 60, 1) for d in por_dia]},
        'tipos': {'labels': [t['nombre'] for t in por_tipo], 'gen': [t['gen'] for t in por_tipo]},
        'gastos': {'labels': [f['concepto'] for f in gastos['filas'][:10]],
                   'monto': [f['monto'] for f in gastos['filas'][:10]]},
        'profes': {'labels': [p['nombre'] for p in profesionales[:12]],
                   'neto': [p['neto'] for p in profesionales[:12]],
                   'costo': [p['costo_periodo'] for p in profesionales[:12]]},
        'semana_dia': {'labels': [w['dia'] for w in por_dia_semana], 'ocup': [w['ocup'] for w in por_dia_semana],
                       'atend': [w['n_atend'] for w in por_dia_semana]},
    }

    r = {
        'suc': suc, 'desde': desde, 'hasta': hasta, 'n_dias': n_dias, 'nota_rango': nota_rango, 'hoy': hoy,
        'kpis': k, 'gastos': gastos, 'profesionales': profesionales, 'pacientes': pacientes,
        'por_tipo': por_tipo, 'por_servicio': por_servicio, 'proyectos': proyectos,
        'mensualidades': mensualidades, 'por_mes': por_mes, 'por_semana': por_semana, 'por_dia': por_dia,
        'por_dia_semana': por_dia_semana, 'heat': heat, 'heat_horas': heat_horas, 'franjas': franjas,
        'franjas_libres': franjas_libres, 'franjas_llenas': franjas_llenas, 'desglose': desglose,
        'concentracion': conc, 'conciliacion': conciliacion, 'cobranza': cobranza, 'comparacion': comparacion,
        'comparativa': comparativa, 'graf': graf,
        'horario_fuentes': _fuentes_horario(items),
        'equipo': {'n': len(profs), 'activos': sum(1 for p in profs if p.activo)},
    }
    r['pac_resumen'] = _pac_resumen(pacientes, k)
    r['paq_resumen'] = _paq_resumen(proyectos, mensualidades)
    r['hallazgos'] = _hallazgos(r)
    r['semaforo'] = _semaforo(r)
    return r


# ─────────────────────────────────────────────────────────────────────
# CONSOLIDACIONES
# ─────────────────────────────────────────────────────────────────────
def _consolidar_pacientes(items):
    m = {}
    for prof, r in items:
        for p in r['pacientes']:
            a = m.get(p['id'])
            if a is None:
                a = m[p['id']] = {
                    'id': p['id'], 'nombre': p['nombre'], 'n': 0, 'atend': 0, 'faltas': 0, 'permisos': 0,
                    'canceladas': 0, 'prog': 0, 'min': 0, 'min_falta': 0, 'gen': 0.0, 'gen_ind': 0.0,
                    'gen_proy': 0.0, 'gen_mens': 0.0, 'servicios': set(), 'profs': {}, 'min_prof': {},
                    'n_proy': 0, 'n_mens': 0, 'primera': p['primera'], 'ultima': p['ultima'],
                    'inactivo': p.get('inactivo', False), 'edad': p.get('edad', ''),
                    'diagnostico': p.get('diagnostico', ''), 'foto': p.get('foto'),
                    'iniciales': p.get('iniciales', ''),
                }
            for kk in ('n', 'atend', 'faltas', 'permisos', 'canceladas', 'prog', 'min', 'min_falta',
                       'gen', 'gen_ind', 'gen_proy', 'gen_mens', 'n_proy', 'n_mens'):
                a[kk] += p.get(kk) or 0
            a['servicios'].update(p['servicios'])
            a['profs'][prof.id] = prof.nombre_completo
            a['min_prof'][prof.id] = a['min_prof'].get(prof.id, 0) + (p['min'] or 0)
            a['primera'] = min(a['primera'], p['primera'])
            a['ultima'] = max(a['ultima'], p['ultima'])
    out = []
    for a in m.values():
        base = a['atend'] + a['faltas'] + a['permisos']
        a['servicios'] = sorted(a['servicios'])
        a['profesionales'] = sorted(a['profs'].values())
        a['n_profs'] = len(a['profs'])
        a['horas_txt'] = hm(a['min'])
        a['falta_txt'] = hm(a['min_falta'])
        a['tasa'] = _pct(a['atend'], base)
        for kk in ('gen', 'gen_ind', 'gen_proy', 'gen_mens'):
            a[kk] = round(a[kk], 2)
        out.append(a)
    out.sort(key=lambda x: (-x['gen'], x['nombre']))
    return out


def _consolidar_paquetes(items):
    pm, mm = {}, {}
    for prof, r in items:
        for src, dst, tipo in ((r['proyectos'], pm, 'p'), (r['mensualidades'], mm, 'm')):
            for d in src:
                a = dst.get(d['id'])
                if a is None:
                    a = dst[d['id']] = {
                        'id': d['id'], 'codigo': d['codigo'], 'paciente': d['paciente'],
                        'estado': d['estado'], 'estado_clave': d['estado_clave'],
                        'valor': d['valor'] if tipo == 'p' else d['costo'],
                        'cobrado': d['cobrado'], 'saldo': d['saldo'], 'ref_total': d['ref_total'],
                        'factor': d['factor'], 'sesiones_total': d['sesiones_total'],
                        'gen_periodo': 0.0, 'por_generar': 0.0, 'atribuido': 0.0, 'sesiones_periodo': 0,
                        'atend_periodo': 0, 'faltas': 0, 'partes': [],
                        'nombre': d.get('nombre') or d.get('periodo', ''),
                        'tipo': d.get('tipo') or 'Mensualidad',
                    }
                for kk in ('gen_periodo', 'por_generar', 'atribuido', 'sesiones_periodo', 'atend_periodo', 'faltas'):
                    a[kk] += d.get(kk) or 0
                a['partes'].append({'nombre': prof.nombre_completo, 'share': d['share'],
                                    'gen': d['gen_periodo'], 'atribuido': d['atribuido'],
                                    'sesiones': d['sesiones_periodo']})
    def _fin(dst):
        out = []
        for a in dst.values():
            for kk in ('gen_periodo', 'por_generar', 'atribuido'):
                a[kk] = round(a[kk], 2)
            a['modalidad'] = 'Grupal' if len(a['partes']) > 1 else 'Solo'
            a['ratio_cobro'] = _pct(a['cobrado'], a['valor'])
            a['partes'].sort(key=lambda x: -x['share'])
            out.append(a)
        out.sort(key=lambda x: -x['gen_periodo'])
        return out
    return _fin(pm), _fin(mm)


def _tabla_profesionales(items, k, gastos):
    rows = []
    for prof, r in items:
        kp = r['kpis']
        costo = kp.get('costo_periodo') or 0.0
        neto = kp['neto_centro']
        rows.append({
            'id': prof.id, 'nombre': prof.nombre_completo, 'especialidad': prof.especialidad,
            'activo': prof.activo, 'iniciales': (prof.nombre[:1] + prof.apellido[:1]).upper(),
            'foto': prof.get_foto_url() if getattr(prof, 'foto', None) else '',
            'tiene_externos': kp['tiene_externos'],
            'gen': kp['gen_total'], 'gen_ind': kp['gen_ind'], 'gen_proy': kp['gen_proy'],
            'gen_mens': kp['gen_mens'], 'ext_prof': kp['ext_prof'], 'neto': neto,
            'pct_neto': _pct(neto, k['neto_centro']),
            'atendidas': kp['atendidas'], 'faltas': kp['faltas'], 'tasa_faltas': kp['tasa_faltas'],
            'pacientes': kp['pacientes'], 'horas_txt': kp['horas_reloj_txt'], 'horas': kp['horas_reloj'],
            'cap_txt': kp['cap_el_txt'], 'ocup': kp['ocup_el'], 'ocup_efect': kp['ocup_efect'],
            'libre_txt': kp['libre_el_txt'], 'perdidas_txt': kp['h_perdidas_txt'],
            'sinag_txt': kp['h_sinag_txt'],
            'ingreso_hora': kp['ingreso_hora'], 'neto_hora': round(neto / kp['horas_reloj'], 2) if kp['horas_reloj'] else 0.0,
            'potencial': kp['potencial_no_aprovechado'],
            'costo_mensual': kp.get('costo_mensual') or 0.0, 'costo_periodo': round(costo, 2),
            'margen': round(neto - costo, 2) if costo else None,
            'cobertura': round(neto / costo, 2) if costo else None,
            'rentable': (neto >= costo) if costo else None,
            'carga': kp['carga'], 'carga_txt': kp['carga_txt'], 'carga_color': kp['carga_color'],
            'sin_horario': kp['cap_el'] == 0,
        })
    rows.sort(key=lambda x: -x['neto'])
    for i, x in enumerate(rows, 1):
        x['pos'] = i
    return rows


def _rentabilidad_pacientes(pacientes, items, k, gastos):
    """Reparte el costo por minutos atendidos y calcula el margen de cada paciente."""
    f_neto = (k['neto_centro'] / k['gen_total']) if k['gen_total'] else 1.0
    min_total = sum(p['min'] for p in pacientes)
    # costo directo del profesional (sólo si tiene costo y pacientes con minutos)
    directo, asignado_total = defaultdict(float), 0.0
    for prof, r in items:
        costo = r['kpis'].get('costo_periodo') or 0.0
        if not costo:
            continue
        mins = sum(p['min_prof'].get(prof.id, 0) for p in pacientes)
        if not mins:
            continue
        asignado_total += costo
        for p in pacientes:
            directo[p['id']] += costo * p['min_prof'].get(prof.id, 0) / mins
    pool_ind = max(gastos['total'] - asignado_total, 0.0)
    k['pool_indirecto'] = round(pool_ind, 2)
    k['costo_hora_pac'] = round(gastos['total'] / (min_total / 60.0), 2) if (min_total and gastos['total']) else 0.0
    for p in pacientes:
        p['neto'] = round(p['gen'] * f_neto, 2)
        p['costo_dir'] = round(directo.get(p['id'], 0.0), 2)
        p['costo_ind'] = round(pool_ind * p['min'] / min_total, 2) if min_total else 0.0
        p['costo'] = round(p['costo_dir'] + p['costo_ind'], 2)
        p['margen'] = round(p['neto'] - p['costo'], 2) if gastos['total'] else None
        p['margen_pct'] = round(p['margen'] / p['neto'] * 100, 1) if (p['margen'] is not None and p['neto']) else None
        p['rentable'] = (p['margen'] >= 0) if p['margen'] is not None else None
        p['neto_hora'] = round(p['neto'] / (p['min'] / 60.0), 2) if p['min'] else 0.0
        p['pct_neto'] = _pct(p['neto'], k['neto_centro'])


def _pac_resumen(pacientes, k):
    con = [p for p in pacientes if p['margen'] is not None]
    if not con:
        return None
    perd = [p for p in con if p['margen'] < 0]
    return {'n': len(con), 'rentables': len(con) - len(perd), 'deficit': len(perd),
            'perdida': round(sum(-p['margen'] for p in perd), 2),
            'ganancia': round(sum(p['margen'] for p in con if p['margen'] >= 0), 2)}


def _paq_resumen(proyectos, mensualidades):
    def _r(lst):
        return {'n': len(lst), 'valor': round(sum(x['valor'] for x in lst), 2),
                'gen': round(sum(x['gen_periodo'] for x in lst), 2),
                'por_generar': round(sum(x['por_generar'] for x in lst), 2),
                'cobrado': round(sum(x['cobrado'] for x in lst), 2),
                'saldo': round(sum(x['saldo'] for x in lst), 2),
                'grupales': sum(1 for x in lst if x['modalidad'] == 'Grupal')}
    return {'proy': _r(proyectos), 'mens': _r(mensualidades)}


def _concentracion(profesionales, pacientes, k):
    out = {'prof': None, 'pac': None}
    tot = k['neto_centro']
    if tot > 0 and profesionales:
        top = sorted(profesionales, key=lambda x: -x['neto'])
        out['prof'] = {'top1': _pct(top[0]['neto'], tot), 'top1_nombre': top[0]['nombre'],
                       'top': [{'nombre': t['nombre'], 'pct': _pct(t['neto'], tot), 'neto': t['neto']} for t in top[:5]]}
    gen = sum(p['gen'] for p in pacientes)
    if gen > 0:
        top = sorted(pacientes, key=lambda x: -x['gen'])
        t5 = sum(t['gen'] for t in top[:5])
        out['pac'] = {'top1': _pct(top[0]['gen'], gen), 'top5': _pct(t5, gen),
                      'top': [{'nombre': t['nombre'], 'pct': _pct(t['gen'], gen), 'gen': t['gen']} for t in top[:5]]}
        nivel = 'alto' if out['pac']['top1'] >= 25 or out['pac']['top5'] >= 60 else (
            'medio' if out['pac']['top1'] >= 15 or out['pac']['top5'] >= 40 else 'bajo')
        out['pac']['nivel'] = nivel
    return out


def _conciliar(suc, desde, hasta, k):
    """Compara el generado (devengado por sesión) con el consumido del reporte financiero.
    OJO: los pagos NO se concilian aquí (el helper financiero cuenta pagos de toda la historia);
    la cobranza con fechas está en calcular_cobranza()."""
    try:
        from pacientes.models import Paciente
        from facturacion.views import _calcular_financiero_sucursal
        from servicios.models import Sucursal
        sucs = list(Sucursal.objects.filter(activa=True)) if _todas(suc) else [suc]
        f = defaultdict(float)
        for s_ in sucs:
            ids = list(Paciente.objects.filter(sucursales__id=s_.id).values_list('id', flat=True).distinct())
            fx = _calcular_financiero_sucursal(s_.id, ids, desde, hasta)
            for kk in ('total_consumido', 'consumido_sesiones', 'consumido_mensualidades', 'consumido_proyectos',
                       'credito_adelantado_disponible'):
                f[kk] += _f(fx[kk])
    except Exception:
        logger.error('Reporte sucursal: no se pudo conciliar con el financiero', exc_info=True)
        return None
    consumido = _f(f['total_consumido'])
    dif = round(k['gen_total'] - consumido, 2)
    return {
        'generado': k['gen_total'], 'consumido': round(consumido, 2),
        'consumido_ses': round(_f(f['consumido_sesiones']), 2),
        'consumido_mens': round(_f(f['consumido_mensualidades']), 2),
        'consumido_proy': round(_f(f['consumido_proyectos']), 2),
        'diferencia': dif,
        'credito': round(_f(f['credito_adelantado_disponible']), 2),
        'cuadra': abs(dif) <= max(1.0, consumido * 0.005),
        'explicacion': (
            'El «generado» reconoce proyectos y mensualidades conforme se consumen las sesiones y por profesional '
            '(parte ponderada); el reporte financiero los cuenta completos por su mes de inicio. '
            'Por eso pueden diferir cuando hay paquetes que cruzan el período o sesiones aún por realizarse.'),
    }



# ─────────────────────────────────────────────────────────────────────
# COBRANZA Y FLUJO DE CAJA (separado del devengado)
#   · Generado (devengado): lo que la sucursal produjo en el período, se haya pagado o no.
#   · Cobranza de lo generado: de ese generado, cuánto se pagó (y cuándo) y cuánto falta.
#   · Caja del período: dinero recibido con fecha_pago dentro del período, clasificado por
#     lo que pagó (este período / deudas anteriores / adelantos / crédito sin asignar).
# "Uso de Crédito" salda un consumo (cuenta en la cobranza) pero NO es dinero que entra
# a caja ese día (el dinero entró cuando se recibió el adelanto).
# ─────────────────────────────────────────────────────────────────────
CREDITO = 'Uso de Crédito'
AGING = ((0, 7, '0 a 7 días'), (8, 30, '8 a 30 días'), (31, 60, '31 a 60 días'), (61, 10 ** 6, 'Más de 60 días'))


def _bucket(f, desde, hasta):
    return 'antes' if f < desde else ('durante' if f <= hasta else 'despues')


def _asignar(pagos, monto):
    """Reparte, en orden cronológico, hasta `monto` entre los pagos [(fecha, importe)]."""
    resto, out = monto, []
    for f, m in sorted(pagos, key=lambda x: x[0]):
        if resto <= 0:
            break
        t = min(m, resto)
        out.append((f, t))
        resto -= t
    return out


def _idx_mes(anio, mes):
    return anio * 12 + mes


def _clasif_caja(tipo, ref, desde, hasta):
    """periodo / anterior / adelanto según a qué consumo corresponde un pago."""
    if tipo == 'mens':
        i, a, b = _idx_mes(*ref), _idx_mes(desde.year, desde.month), _idx_mes(hasta.year, hasta.month)
        return 'anterior' if i < a else ('periodo' if i <= b else 'adelanto')
    if tipo == 'proy':
        return 'anterior' if ref < desde else ('periodo' if ref <= hasta else 'adelanto')
    fecha, consumida = ref                      # sesión individual
    if fecha < desde:
        return 'anterior'
    return 'periodo' if (consumida and fecha <= hasta) else 'adelanto'


def calcular_cobranza(suc, desde, hasta, hoy, k, proyectos, mensualidades):
    from agenda.models import Sesion, Proyecto, Mensualidad
    from facturacion.models import Pago, DetallePagoMasivo, Devolucion
    from pacientes.models import Paciente

    f_ses = dict(proyecto__isnull=True, mensualidad__isnull=True, **_kw(suc, 'sucursal'))
    # ── A) cobranza de lo generado ─────────────────────────────────
    ses = list(Sesion.objects.filter(fecha__gte=desde, fecha__lte=hasta, estado__in=CONSUMIDAS, **f_ses)
               .values('id', 'fecha', 'paciente_id', 'monto_cobrado', 'paciente__nombre', 'paciente__apellido'))
    pg = defaultdict(list)
    rel = {f'sesion__{kk}': v for kk, v in f_ses.items() if kk != 'sucursal'}
    base = dict(sesion__fecha__gte=desde, sesion__fecha__lte=hasta,
                sesion__estado__in=CONSUMIDAS, **_kw(suc, 'sesion__sucursal'), **rel)
    for x in Pago.objects.filter(anulado=False, **base).values('sesion_id', 'fecha_pago', 'monto'):
        pg[x['sesion_id']].append((x['fecha_pago'], float(x['monto'])))
    for x in DetallePagoMasivo.objects.filter(tipo='sesion', pago__anulado=False, **base).values(
            'sesion_id', 'pago__fecha_pago', 'monto'):
        pg[x['sesion_id']].append((x['pago__fecha_pago'], float(x['monto'])))

    tipos = {c: {'clave': c, 'gen': 0.0, 'antes': 0.0, 'durante': 0.0, 'despues': 0.0}
             for c in ('individual', 'proyecto', 'mensualidad')}
    aging = [{'label': l, 'ini': a, 'fin': b, 'monto': 0.0, 'n': 0} for a, b, l in AGING]
    deud = {}

    def _deudor(pid, nombre):
        return deud.setdefault(pid, {'id': pid, 'nombre': nombre, 'pend': 0.0, 'n_ses': 0, 'dias_max': 0, 'paq_pend': 0.0})

    def _aging(dias, monto):
        for a in aging:
            if a['ini'] <= dias <= a['fin']:
                a['monto'] += monto
                a['n'] += 1
                return

    for s_ in ses:
        gen = float(s_['monto_cobrado'] or 0)
        if gen <= 0:
            continue
        t = tipos['individual']
        t['gen'] += gen
        cob = 0.0
        for f, m in _asignar(pg.get(s_['id'], []), gen):
            t[_bucket(f, desde, hasta)] += m
            cob += m
        pend = gen - cob
        if pend > 0.005:
            dias = max((hoy - s_['fecha']).days, 0)
            _aging(dias, pend)
            d = _deudor(s_['paciente_id'], f"{s_['paciente__nombre']} {s_['paciente__apellido']}".strip())
            d['pend'] += pend
            d['n_ses'] += 1
            d['dias_max'] = max(d['dias_max'], dias)

    # paquetes: el cobro se estima proporcional al avance de pago (igual que el reporte por profesional)
    for lista, clave, tipo_pm in ((proyectos, 'proyecto', 'proy'), (mensualidades, 'mensualidad', 'mens')):
        if not lista:
            continue
        ids = [x['id'] for x in lista]
        campo = 'proyecto' if tipo_pm == 'proy' else 'mensualidad'
        pp = defaultdict(list)
        for x in Pago.objects.filter(anulado=False, **{f'{campo}_id__in': ids}).values(f'{campo}_id', 'fecha_pago', 'monto'):
            pp[x[f'{campo}_id']].append((x['fecha_pago'], float(x['monto'])))
        for x in DetallePagoMasivo.objects.filter(tipo=campo, pago__anulado=False, **{f'{campo}_id__in': ids}).values(
                f'{campo}_id', 'pago__fecha_pago', 'monto'):
            pp[x[f'{campo}_id']].append((x['pago__fecha_pago'], float(x['monto'])))
        if tipo_pm == 'proy':
            meta = {m['id']: (m['fecha_inicio'], m['paciente_id']) for m in
                    Proyecto.objects.filter(id__in=ids).values('id', 'fecha_inicio', 'paciente_id')}
        else:
            meta = {m['id']: (date(m['anio'], m['mes'], 1), m['paciente_id']) for m in
                    Mensualidad.objects.filter(id__in=ids).values('id', 'mes', 'anio', 'paciente_id')}
        t = tipos[clave]
        for x in lista:
            gen, valor = x['gen_periodo'], x['valor']
            if gen <= 0 or valor <= 0:
                continue
            pays = pp.get(x['id'], [])
            tot = sum(m for _f, m in pays)
            esc = min(1.0, valor / tot) if tot else 1.0
            b = {'antes': 0.0, 'durante': 0.0, 'despues': 0.0}
            for f, m in pays:
                b[_bucket(f, desde, hasta)] += m * esc
            cob = 0.0
            for kk, v in b.items():
                part = gen * v / valor
                t[kk] += part
                cob += part
            t['gen'] += gen
            pend = max(gen - cob, 0.0)
            if pend > 0.005:
                ref, pid = meta.get(x['id'], (desde, None))
                dias = max((hoy - max(ref, desde)).days, 0)
                _aging(dias, pend)
                d = _deudor(pid if pid is not None else f"p-{x['paciente']}", x['paciente'])
                d['pend'] += pend
                d['paq_pend'] += pend
                d['dias_max'] = max(d['dias_max'], dias)

    nombres = {'individual': 'Sesiones individuales', 'proyecto': 'Proyectos', 'mensualidad': 'Mensualidades'}
    filas, tot = [], {'gen': 0.0, 'antes': 0.0, 'durante': 0.0, 'despues': 0.0}
    for c, t in tipos.items():
        t['nombre'] = nombres[c]
        t['cobrado'] = t['antes'] + t['durante'] + t['despues']
        t['pend'] = max(t['gen'] - t['cobrado'], 0.0)
        t['pct'] = _pct(t['cobrado'], t['gen'])
        for kk in ('gen', 'antes', 'durante', 'despues', 'cobrado', 'pend'):
            t[kk] = round(t[kk], 2)
        for kk in ('gen', 'antes', 'durante', 'despues'):
            tot[kk] += t[kk]
        filas.append(t)
    tot['cobrado'] = tot['antes'] + tot['durante'] + tot['despues']
    tot['pend'] = max(tot['gen'] - tot['cobrado'], 0.0)
    tot['pct'] = _pct(tot['cobrado'], tot['gen'])
    tot = {kk: round(v, 2) if kk != 'pct' else v for kk, v in tot.items()}
    pend_tot = sum(a['monto'] for a in aging)
    for a in aging:
        a['monto'] = round(a['monto'], 2)
        a['pct'] = _pct(a['monto'], pend_tot)
    mora30 = round(sum(a['monto'] for a in aging if a['ini'] >= 31), 2)
    deudores = sorted(deud.values(), key=lambda x: -x['pend'])[:15]
    for d in deudores:
        d['pend'] = round(d['pend'], 2)
        d['paq_pend'] = round(d['paq_pend'], 2)

    # ── B) caja del período (dinero recibido con fecha_pago en el rango) ────
    qf = dict(fecha_pago__gte=desde, fecha_pago__lte=hasta, anulado=False)
    caja = {'periodo': 0.0, 'anterior': 0.0, 'adelanto': 0.0, 'credito': 0.0}
    metodos = defaultdict(float)
    uso = defaultdict(float)          # uso de crédito por categoría (no es dinero nuevo)

    def _sumar(cat, monto, metodo):
        caja[cat] += monto
        metodos[metodo] += monto

    def _reg(cat, monto, metodo):
        if metodo == CREDITO:
            uso[cat] += monto
        else:
            _sumar(cat, monto, metodo)

    pago_ses = dict(sesion__isnull=False, sesion__proyecto__isnull=True, sesion__mensualidad__isnull=True,
                    **_kw(suc, 'sesion__sucursal'))
    for x in Pago.objects.filter(**qf, **pago_ses).values('monto', 'metodo_pago__nombre', 'sesion__fecha', 'sesion__estado'):
        _reg(_clasif_caja('ses', (x['sesion__fecha'], x['sesion__estado'] in CONSUMIDAS), desde, hasta),
             float(x['monto']), x['metodo_pago__nombre'])
    for x in DetallePagoMasivo.objects.filter(tipo='sesion', pago__fecha_pago__gte=desde, pago__fecha_pago__lte=hasta,
                                              pago__anulado=False, **pago_ses).values(
            'monto', 'pago__metodo_pago__nombre', 'sesion__fecha', 'sesion__estado'):
        _reg(_clasif_caja('ses', (x['sesion__fecha'], x['sesion__estado'] in CONSUMIDAS), desde, hasta),
             float(x['monto']), x['pago__metodo_pago__nombre'])
    for campo, tp in (('mensualidad', 'mens'), ('proyecto', 'proy')):
        refs = ('mensualidad__anio', 'mensualidad__mes') if tp == 'mens' else ('proyecto__fecha_inicio',)
        for x in Pago.objects.filter(**qf, **{f'{campo}__isnull': False}, **_kw(suc, f'{campo}__sucursal')).values('monto', 'metodo_pago__nombre', *refs):
            ref = (x['mensualidad__anio'], x['mensualidad__mes']) if tp == 'mens' else x['proyecto__fecha_inicio']
            _reg(_clasif_caja(tp, ref, desde, hasta), float(x['monto']), x['metodo_pago__nombre'])
        for x in DetallePagoMasivo.objects.filter(tipo=campo, pago__fecha_pago__gte=desde, pago__fecha_pago__lte=hasta,
                                                  pago__anulado=False, **{f'{campo}__isnull': False}, **_kw(suc, f'{campo}__sucursal')).values(
                'monto', 'pago__metodo_pago__nombre', *refs):
            ref = (x['mensualidad__anio'], x['mensualidad__mes']) if tp == 'mens' else x['proyecto__fecha_inicio']
            _reg(_clasif_caja(tp, ref, desde, hasta), float(x['monto']), x['pago__metodo_pago__nombre'])
    # adelantos de crédito sin asignar (en una sucursal: solo pacientes cuya sucursal principal es ésta)
    try:
        filtro_pac = {}
        if not _todas(suc):
            from facturacion.views import _build_sucursal_map
            ids_pac = list(Paciente.objects.filter(sucursales=suc).values_list('id', flat=True).distinct())
            mapa = _build_sucursal_map(ids_pac)
            filtro_pac = {'paciente_id__in': [pid for pid in ids_pac if str(mapa.get(pid, suc.id)) == str(suc.id)]}
        for x in (Pago.objects.filter(**qf, **filtro_pac, sesion__isnull=True, mensualidad__isnull=True,
                                      proyecto__isnull=True)
                  .exclude(metodo_pago__nombre=CREDITO).exclude(detalles_masivos__isnull=False)
                  .values('monto', 'metodo_pago__nombre')):
            _sumar('credito', float(x['monto']), x['metodo_pago__nombre'])
    except Exception:
        logger.error('Reporte sucursal: error calculando adelantos de crédito', exc_info=True)
    dev = 0.0
    for campo in ('mensualidad', 'proyecto'):
        dev += float(Devolucion.objects.filter(fecha_devolucion__gte=desde, fecha_devolucion__lte=hasta,
                                               **{f'{campo}__isnull': False}, **_kw(suc, f'{campo}__sucursal')).aggregate(t=Sum('monto'))['t'] or 0)
    total_cobros = sum(caja.values())
    por_metodo = [{'metodo': m, 'monto': round(v, 2), 'pct': _pct(v, total_cobros)}
                  for m, v in sorted(metodos.items(), key=lambda kv: -kv[1]) if v > 0.004]
    caja = {kk: round(v, 2) for kk, v in caja.items()}
    caja.update({'total': round(total_cobros, 2), 'devoluciones': round(dev, 2),
                 'neto': round(total_cobros - dev, 2), 'por_metodo': por_metodo,
                 'uso_credito': round(sum(uso.values()), 2)})
    # Puente exacto entre «Cobrado de lo generado» (cobranza) y «Pagos recibidos por consumos de este período» (caja)
    esperado = tot['cobrado'] - tot['antes'] - tot['despues'] - uso['periodo']
    puente = {
        'cobrado': tot['cobrado'], 'antes': tot['antes'], 'despues': tot['despues'],
        'credito': round(uso['periodo'], 2), 'caja_periodo': caja['periodo'],
        'residual': round(caja['periodo'] - esperado, 2),
    }

    # ── C) lo programado (por generar) y proyección ───────────────
    paq_pg = round(sum(x['por_generar'] for x in proyectos) + sum(x['por_generar'] for x in mensualidades), 2)
    ind_pg = round(max(k['por_generar'] - paq_pg, 0.0), 2)
    adel = 0.0
    bp = dict(**_kw(suc, 'sesion__sucursal'), sesion__fecha__gte=desde, sesion__fecha__lte=hasta, sesion__estado='programada',
              sesion__proyecto__isnull=True, sesion__mensualidad__isnull=True)
    adel += float(Pago.objects.filter(anulado=False, **bp).aggregate(t=Sum('monto'))['t'] or 0)
    adel += float(DetallePagoMasivo.objects.filter(tipo='sesion', pago__anulado=False, **bp).aggregate(t=Sum('monto'))['t'] or 0)
    tasa = tot['pct']
    proyectado = round(tot['gen'] + paq_pg + ind_pg, 2)
    prog = {
        'n': k['programadas'], 'ind': ind_pg, 'paq': paq_pg, 'total': round(ind_pg + paq_pg, 2),
        'adelanto_cobrado': round(adel, 2),
        'proyectado': proyectado,
        'cobrar_esperado': round((ind_pg + paq_pg) * tasa / 100.0, 2),
        'por_cobrar_total': round(tot['pend'] + max(ind_pg - adel, 0.0) + paq_pg, 2),
    }
    return {
        'filas': filas, 'tot': tot, 'aging': aging, 'pend_tot': round(pend_tot, 2), 'mora30': mora30,
        'pct_mora30': _pct(mora30, tot['gen']), 'deudores': deudores, 'caja': caja, 'prog': prog, 'puente': puente,
        'tasa': tasa,
        'nota_aging': 'En proyectos y mensualidades la antigüedad se cuenta desde el inicio del paquete (o desde el inicio '
                      'del período si empezó antes) y el cobro se estima proporcional al avance de pago del paquete.',
    }


def _fuentes_horario(items):
    n_asist = sum(1 for _p, r in items if r['horario']['fuente'] == 'asistencia')
    return {'asistencia': n_asist, 'predeterminado': len(items) - n_asist}


# ─────────────────────────────────────────────────────────────────────
# COMPARACIONES
# ─────────────────────────────────────────────────────────────────────
def _comparar_periodo_anterior(suc, desde, hasta, k, manuales, cp, nombres, glob, inc_egr, inc_pers,
                               manual_cfg, forzar_manual, hoy):
    try:
        largo = (hasta - desde).days + 1
        ph = desde - timedelta(days=1)
        pd = ph - timedelta(days=largo - 1)
        items = _correr(suc, pd, ph, cp, manual_cfg, forzar_manual, hoy)
        pk = _agregar(items)
        pg = calcular_gastos(suc, pd, ph, manuales, cp, nombres, glob, inc_egr, inc_pers)
        pres = round(pk['neto_centro'] - pg['total'], 2)
        return {
            'desde': pd, 'hasta': ph,
            'neto': (pk['neto_centro'], round(k['neto_centro'] - pk['neto_centro'], 2)),
            'gastos': (pg['total'], round(k['gastos'] - pg['total'], 2)),
            'resultado': (pres, round(k['resultado'] - pres, 2)),
            'atendidas': (pk['atendidas'], k['atendidas'] - pk['atendidas']),
            'horas': (pk['min_reloj_txt'], round(k['horas_reloj'] - pk['horas_reloj'], 1)),
            'ocup': (pk['ocup_efect'], round(k['ocup_efect'] - pk['ocup_efect'], 1)),
            'pacientes': (pk['pacientes'], k['pacientes'] - pk['pacientes']),
        }
    except Exception:
        logger.error('Reporte sucursal: error en período anterior', exc_info=True)
        return None


def _comparar_sucursales(suc, desde, hasta, glob, manual_cfg, forzar_manual, hoy, k_actual, gastos_actual):
    from servicios.models import Sucursal
    out = []
    for s in Sucursal.objects.filter(activa=True):
        try:
            if s.id == suc.id:
                kk, g_tot = k_actual, gastos_actual['total']
            else:
                kk = _agregar(_correr(s, desde, hasta, {}, manual_cfg, forzar_manual, hoy))
                g = calcular_gastos(s, desde, hasta, [], {}, {}, glob, True, True)
                g_tot = g['total']
            out.append({
                'id': s.id, 'nombre': s.nombre, 'actual': s.id == suc.id,
                'neto': kk['neto_centro'], 'gen': kk['gen_total'], 'horas_txt': kk['min_reloj_txt'],
                'ocup_efect': kk['ocup_efect'], 'faltas': kk['tasa_faltas'], 'atendidas': kk['atendidas'],
                'pacientes': kk['pacientes'], 'profesionales': kk['profesionales'],
                'neto_hora': kk['neto_hora'], 'gastos': round(g_tot, 2),
                'resultado': round(kk['neto_centro'] - g_tot, 2),
                'nota_gastos': 'incluye gastos manuales y costos por profesional' if s.id == suc.id
                               else 'solo egresos registrados',
            })
        except Exception:
            logger.error('Reporte sucursal: error comparando %s', s.id, exc_info=True)
    out.sort(key=lambda x: -x['neto'])
    return out


# ─────────────────────────────────────────────────────────────────────
# HALLAZGOS Y SEMÁFORO
# ─────────────────────────────────────────────────────────────────────
def _hallazgos(r):
    k, g = r['kpis'], r['gastos']
    h = []
    if k['tiene_gastos']:
        signo = 'ganancia' if k['resultado'] >= 0 else 'pérdida'
        h.append({'tipo': 'ok' if k['resultado'] >= 0 else 'alerta',
                  'txt': f"Ingresos netos Bs. {k['neto_centro']:,.2f} frente a gastos de Bs. {k['gastos']:,.2f}: "
                         f"{signo} de Bs. {abs(k['resultado']):,.2f} (margen {k['margen_pct']}%, cobertura {k['cobertura']}×)."})
        if k['faltante']:
            txt = f"Para cubrir los gastos faltan Bs. {k['faltante']:,.2f}"
            if k['h_equilibrio']:
                txt += (f", equivalente a ≈ {k['h_equilibrio']:,.1f} horas más de atención al ritmo actual "
                        f"(Bs. {k['neto_hora']:,.2f} netos por hora)")
            if k['ses_equilibrio']:
                txt += f" o ≈ {k['ses_equilibrio']} sesiones más (Bs. {k['neto_sesion']:,.2f} netos por sesión)"
            txt += f". Hay {k['h_sinag_txt']} de horario sin paciente agendado que podrían cubrirlo."
            h.append({'tipo': 'alerta', 'txt': txt})
    else:
        h.append({'tipo': 'nota',
                  'txt': 'No hay gastos considerados. Registra egresos de la sucursal o usa los cuadros de gastos '
                         '(alquiler, servicios, personal…) para ver la rentabilidad real.'})
    if k['cap_el']:
        h.append({'tipo': 'info',
                  'txt': f"Los profesionales trabajaron {k['min_reloj_txt']} efectivas de {k['cap_el_txt']} de horario "
                         f"transcurrido (ocupación efectiva {k['ocup_efect']}%, agendada {k['ocup_el']}%)."})
        if k['ocup_efect'] < 35:
            h.append({'tipo': 'alerta', 'txt': 'La sucursal está muy vacía: hay capacidad para sumar muchos pacientes.'})
        elif k['ocup_efect'] >= 85:
            h.append({'tipo': 'ok', 'txt': 'Agenda casi completa: evalúa ampliar horarios o sumar profesionales.'})
    if k['h_perdidas']:
        h.append({'tipo': 'info',
                  'txt': f"Horas perdidas por inasistencia/cancelación: {k['h_perdidas_txt']} ({k['pct_perdidas']}% del horario): "
                         f"faltas sin aviso {k['h_falta_txt']} (se cobran), permisos {k['h_permiso_txt']}, "
                         f"cancelaciones {k['h_cancel_txt']}, reprogramaciones {k['h_reprog_txt']}."})
    if k['potencial_no_aprovechado']:
        h.append({'tipo': 'info',
                  'txt': f"Potencial no aprovechado (estimado): ≈ Bs. {k['potencial_no_aprovechado']:,.2f} en horas libres "
                         f"que no generaron dinero."})
    if k['tasa_faltas'] >= 15 and (k['atendidas'] + k['faltas'] + k['permisos']) >= 5:
        h.append({'tipo': 'alerta', 'txt': f"{k['tasa_faltas']}% de las sesiones fueron falta sin aviso."})
    deficit = [p for p in r['profesionales'] if p['rentable'] is False]
    if deficit:
        h.append({'tipo': 'alerta',
                  'txt': f"{len(deficit)} profesional(es) no cubren su costo: " + ', '.join(p['nombre'] for p in deficit[:4])
                         + ('…' if len(deficit) > 4 else '')})
    sin_h = [p for p in r['profesionales'] if p['sin_horario']]
    if sin_h:
        h.append({'tipo': 'nota',
                  'txt': f"{len(sin_h)} profesional(es) sin horario transcurrido en el período: "
                         + ', '.join(p['nombre'] for p in sin_h[:4])})
    pr = r['pac_resumen']
    if pr and pr['deficit']:
        h.append({'tipo': 'info',
                  'txt': f"{pr['deficit']} de {pr['n']} pacientes no cubren su costo asignado (déficit acumulado "
                         f"Bs. {pr['perdida']:,.2f}); los otros {pr['rentables']} aportan Bs. {pr['ganancia']:,.2f}."})
    cb = r.get('cobranza')
    if cb:
        t, c_ = cb['tot'], cb['caja']
        h.append({'tipo': 'info',
                  'txt': f"Cobranza: de Bs. {t['gen']:,.2f} generados se cobró Bs. {t['cobrado']:,.2f} ({t['pct']}%) y quedan "
                         f"Bs. {t['pend']:,.2f} por cobrar. En caja entraron Bs. {c_['total']:,.2f} en el período "
                         f"(de este período {c_['periodo']:,.2f}, deudas anteriores {c_['anterior']:,.2f}, adelantos {c_['adelanto'] + c_['credito']:,.2f})."})
        if cb['pct_mora30'] >= 10 and cb['mora30'] > 0:
            h.append({'tipo': 'alerta',
                      'txt': f"Mora: Bs. {cb['mora30']:,.2f} ({cb['pct_mora30']}% de lo generado) llevan más de 30 días sin cobrarse."})
        if t['antes'] > 0:
            h.append({'tipo': 'ok', 'txt': f"Bs. {t['antes']:,.2f} de lo generado ya habían sido pagados por adelantado antes del período."})
        if t['despues'] > 0:
            h.append({'tipo': 'info', 'txt': f"Bs. {t['despues']:,.2f} de lo generado se cobraron después del período (cobro tardío)."})
        if cb['prog']['total']:
            h.append({'tipo': 'info',
                      'txt': f"Por generar (agenda programada): Bs. {cb['prog']['total']:,.2f}; proyectado del período Bs. {cb['prog']['proyectado']:,.2f}. "
                             f"Al ritmo de cobro actual ({cb['tasa']}%) se esperaría cobrar ≈ Bs. {cb['prog']['cobrar_esperado']:,.2f} de eso."})
    cp = r['concentracion'].get('prof')
    if cp and len(r['profesionales']) > 1 and cp['top1'] >= 50:
        h.append({'tipo': 'alerta',
                  'txt': f"{cp['top1_nombre']} genera el {cp['top1']}% del ingreso neto de la sucursal: dependencia alta."})
    if r['franjas_libres']:
        f = r['franjas_libres'][0]
        h.append({'tipo': 'info', 'txt': f"La franja con más horas libres es {f['h']} (ocupada {f['ocup']}%, {f['libre_txt']} libres)."})
    if r['por_servicio']:
        con_h = [s for s in r['por_servicio'] if s['min'] >= 60]
        if len(con_h) >= 2:
            best, worst = max(con_h, key=lambda s: s['ingreso_hora']), min(con_h, key=lambda s: s['ingreso_hora'])
            h.append({'tipo': 'info',
                      'txt': f"Servicio más rentable por hora: {best['nombre']} (Bs. {best['ingreso_hora']:,.2f}/h). "
                             f"El menos: {worst['nombre']} (Bs. {worst['ingreso_hora']:,.2f}/h)."})
    if g['excl_pers']:
        h.append({'tipo': 'nota',
                  'txt': f"Se excluyeron Bs. {g['excl_pers']:,.2f} de egresos de personal/honorarios registrados para no "
                         f"duplicar los costos por profesional que ingresaste."})
    if g['omit_glob']:
        h.append({'tipo': 'nota', 'txt': f"No se incluyeron Bs. {g['omit_glob']:,.2f} de gastos globales (reparto: no incluir)."})
    fu = r['horario_fuentes']
    if fu['predeterminado']:
        h.append({'tipo': 'nota',
                  'txt': f"{fu['predeterminado']} profesional(es) usan el horario predeterminado (no está en Asistencia); "
                         f"ajústalo en «Horario base» para cálculos exactos."})
    for x in h:
        x['txt'] = es_num(x['txt'])
    return h


def _semaforo(r):
    k = r['kpis']
    crit = []

    def add(nombre, valor, estado, regla, peso, detalle):
        crit.append({'nombre': nombre, 'valor': es_num(valor), 'estado': estado, 'color': COLOR[estado],
                     'regla': es_num(regla), 'peso': peso, 'detalle': es_num(detalle)})

    def nivel(v, verde, ambar, mayor=True):
        if mayor:
            return VERDE if v >= verde else (AMBAR if v >= ambar else ROJO)
        return VERDE if v <= verde else (AMBAR if v <= ambar else ROJO)

    if k['tiene_gastos']:
        add('Cobertura de gastos', f"{k['cobertura']}× (resultado Bs. {k['resultado']:,.0f})",
            nivel(k['cobertura'], 1.2, 1.0), 'Verde ≥ 1,2× · Ámbar 1–1,2× · Rojo < 1×', 2.5,
            f"Ingreso neto Bs. {k['neto_centro']:,.0f} ÷ gastos Bs. {k['gastos']:,.0f}.")
        add('Margen sobre ingresos netos', f"{k['margen_pct']}%", nivel(k['margen_pct'], 20, 5),
            'Verde ≥ 20% · Ámbar 5–20% · Rojo < 5%', 1.5, 'Lo que queda de cada boliviano neto después de los gastos.')
    if k['cap_el']:
        add('Ocupación efectiva de la sucursal', f"{k['ocup_efect']}%", nivel(k['ocup_efect'], 60, 40),
            'Verde ≥ 60% · Ámbar 40–60% · Rojo < 40%', 1.5,
            'Horas realmente trabajadas con pacientes ÷ horas de horario transcurrido de todos los profesionales.')
    if (k['atendidas'] + k['faltas'] + k['permisos']) >= 5:
        add('Faltas sin aviso', f"{k['tasa_faltas']}%", nivel(k['tasa_faltas'], 8, 15, mayor=False),
            'Verde ≤ 8% · Ámbar 8–15% · Rojo > 15%', 1.0, 'Una tasa alta indica problemas de adherencia o de confirmación.')
    cb = r.get('cobranza')
    if cb and cb['tot']['gen'] > 0:
        add('Mora de cobro (más de 30 días)', f"{cb['pct_mora30']}% · Bs. {cb['mora30']:,.0f}",
            nivel(cb['pct_mora30'], 8, 18, mayor=False), 'Verde ≤ 8% · Ámbar 8–18% · Rojo > 18% de lo generado', 1.0,
            f"Cobrado {cb['tot']['pct']}% de lo generado; pendiente total Bs. {cb['tot']['pend']:,.0f}.")
    cp = r['concentracion'].get('prof')
    if cp and len(r['profesionales']) > 1:
        add('Dependencia de un profesional', f"Top 1: {cp['top1']}%", nivel(cp['top1'], 35, 50, mayor=False),
            'Verde ≤ 35% · Ámbar 35–50% · Rojo > 50%', 0.75,
            f"{cp['top1_nombre']} aporta el {cp['top1']}% del ingreso neto: si se va, ¿cuánto cae?")
    cn = r['concentracion'].get('pac')
    if cn:
        add('Dependencia de pocos pacientes', f"Top 1: {cn['top1']}% · Top 5: {cn['top5']}%",
            {'bajo': VERDE, 'medio': AMBAR, 'alto': ROJO}[cn['nivel']],
            'Verde: reparto sano · Ámbar: top1 ≥ 15% o top5 ≥ 40% · Rojo: top1 ≥ 25% o top5 ≥ 60%', 0.75,
            'Si se van pocos niños, ¿cuánto de la sucursal se cae?')
    con_costo = [p for p in r['profesionales'] if p['rentable'] is not None]
    if con_costo:
        ok = sum(1 for p in con_costo if p['rentable'])
        pct = _pct(ok, len(con_costo))
        add('Profesionales que cubren su costo', f"{ok} de {len(con_costo)} ({pct}%)", nivel(pct, 80, 50),
            'Verde ≥ 80% · Ámbar 50–80% · Rojo < 50%', 1.25, 'Sólo profesionales con costo mensual ingresado.')
    pm = list(r['por_mes'])
    if pm and r['hasta'] >= r['hoy'] and pm[-1]['key'] == (r['hoy'].year, r['hoy'].month):
        pm = pm[:-1]          # el mes en curso está incompleto: no entra en la tendencia
    if len(pm) >= 3:
        ultimo, previos = pm[-1]['neto'], [x['neto'] for x in pm[:-1]]
        prom = sum(previos) / len(previos)
        if prom > 0:
            var = round((ultimo - prom) / prom * 100, 1)
            add('Tendencia de ingresos netos', f"{var:+}% vs. promedio previo",
                VERDE if var >= 5 else (AMBAR if var > -10 else ROJO),
                'Verde: sube ≥ 5% · Ámbar: estable (hasta −10%) · Rojo: cae más de 10%', 1.0,
                f"Último mes completo Bs. {ultimo:,.0f} contra promedio previo Bs. {prom:,.0f}.")

    pesos = sum(c['peso'] for c in crit)
    score = sum(PUNTOS[c['estado']] * c['peso'] for c in crit) / pesos if pesos else None
    if score is None:
        ver, color, msg = 'sin_datos', '#64748b', 'No hay datos suficientes para un veredicto.'
    elif score >= 0.75:
        ver, color, msg = 'solido', '#16a34a', 'Sucursal SÓLIDA: es rentable y cumple la mayoría de los criterios.'
    elif score >= 0.5:
        ver, color, msg = 'aceptable', '#d97706', 'Sucursal ACEPTABLE con observaciones: revisa los criterios en ámbar/rojo.'
    elif score >= 0.3:
        ver, color, msg = 'bajo', '#ea580c', 'Rendimiento BAJO: conviene un plan de mejora con metas a 30–60 días.'
    else:
        ver, color, msg = 'critico', '#dc2626', 'Rendimiento CRÍTICO: revisar costos, agenda y la continuidad de la sucursal.'
    return {
        'criterios': crit, 'score': round(score * 100) if score is not None else None,
        'veredicto': ver, 'color': color, 'msg': msg,
        'n_verde': sum(1 for c in crit if c['estado'] == VERDE),
        'n_ambar': sum(1 for c in crit if c['estado'] == AMBAR),
        'n_rojo': sum(1 for c in crit if c['estado'] == ROJO),
        'faltan_gastos': not k['tiene_gastos'],
        'nota': 'Veredicto orientativo, calculado con los criterios visibles; la decisión final es del dueño.',
    }
