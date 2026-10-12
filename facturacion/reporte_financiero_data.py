# facturacion/reporte_financiero_data.py
# =====================================================================
# MOTOR DEL «PANEL DEL DUEÑO» DEL REPORTE FINANCIERO
# Capa de decisión: salud económica, deudores, pagadores puntuales, pacientes que más y menos
# generan, tendencias, egresos y resultado. NO modifica ni reemplaza las pestañas existentes;
# usa las MISMAS definiciones que ellas para que las cifras cuadren:
#
#   · GENERADO (real)  = sesiones sueltas realizadas/con retraso/falta (monto_cobrado)
#                        + proyectos en_progreso/finalizado/cancelado (costo_total, por fecha de inicio)
#                        + mensualidades del mes (costo_mensual).
#   · COBRADO bruto    = pagos no anulados del período, SIN «Uso de Crédito» (no es dinero nuevo).
#   · COBRADO neto     = cobrado bruto − devoluciones del período.
#   · DEUDA TOTAL      = saldo_real negativo de la cuenta corriente (lo realizado + lo agendado − lo pagado).
#   · DEUDA REALIZADA  = saldo_actual negativo (solo servicios ya consumidos).
#   · Antigüedad de la deuda: estimada por orden de llegada (FIFO): se asume que cada pago cancela
#     primero lo más antiguo, así que la deuda vigente corresponde a los consumos más recientes.
#   · Puntualidad de pago: días entre el consumo (sesión / inicio de proyecto / mes de la
#     mensualidad) y el pago directo de ese ítem. Puntual = hasta PUNTUAL_DIAS días.
#   · EGRESOS: registrados en el sistema (no anulados), ubicados por período contable (o por fecha de
#     pago si no tiene). Resultado = cobrado neto − comisiones a profesionales externos − egresos
#     (los egresos marcados como honorario profesional se excluyen para no duplicar las comisiones).
# =====================================================================
import calendar
import logging
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Count, Max, Q, Sum
from django.db.models.functions import TruncMonth

logger = logging.getLogger(__name__)

NO_DINERO = 'Uso de Crédito'
PUNTUAL_DIAS = 10        # pago dentro de estos días del consumo = puntual
MIN_PAGOS_PUNTUAL = 3    # pagos directos mínimos para evaluar la puntualidad de un paciente
UMBRAL_COBRANZA_OK = 80.0
UMBRAL_COBRANZA_MAL = 60.0
MESES = ['', 'Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']
MESES_FULL = ['', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre', 'Octubre',
              'Noviembre', 'Diciembre']


def _f(x):
    return float(x or 0)


def _pct(a, b):
    return round(100.0 * a / b, 1) if b else 0.0


def _mes_ini(d):
    return date(d.year, d.month, 1)


def _mes_mas(d, n):
    m = d.month - 1 + n
    return date(d.year + m // 12, m % 12 + 1, 1)


def _fin_mes(d):
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def _var(a, b):
    """Variación % de a respecto de b (None si no hay base)."""
    if not b:
        return None
    return round(100.0 * (a - b) / abs(b), 1)


# ─────────────────────────────────────────────────────────────────────
# PAGOS / DEVOLUCIONES con filtro de sucursal (misma lógica que reporte_financiero)
# ─────────────────────────────────────────────────────────────────────
def _pagos(desde, hasta, suc, incluir_credito=False, anulados=False):
    from facturacion.models import Pago
    qs = Pago.objects.filter(fecha_pago__gte=desde, fecha_pago__lte=hasta, anulado=anulados)
    if not incluir_credito:
        qs = qs.exclude(metodo_pago__nombre=NO_DINERO)
    if not suc:
        return qs
    from facturacion.views import _build_sucursal_map
    con_item = qs.filter(Q(sesion__sucursal_id=suc) | Q(proyecto__sucursal_id=suc) | Q(mensualidad__sucursal_id=suc))
    libres = qs.filter(sesion__isnull=True, proyecto__isnull=True, mensualidad__isnull=True)
    pids = list(libres.values_list('paciente_id', flat=True).distinct())
    if pids:
        mp = _build_sucursal_map(pids)
        ok = [p for p, s in mp.items() if str(s) == str(suc)]
        libres = libres.filter(paciente_id__in=ok)
    else:
        libres = libres.none()
    return (con_item | libres).distinct()


def _devoluciones(desde, hasta, suc):
    from facturacion.models import Devolucion
    qs = Devolucion.objects.filter(fecha_devolucion__gte=desde, fecha_devolucion__lte=hasta)
    if not suc:
        return qs
    from facturacion.views import _build_sucursal_map
    con_item = qs.filter(Q(proyecto__sucursal_id=suc) | Q(mensualidad__sucursal_id=suc))
    libres = qs.filter(proyecto__isnull=True, mensualidad__isnull=True)
    pids = list(libres.values_list('paciente_id', flat=True).distinct())
    if pids:
        mp = _build_sucursal_map(pids)
        ok = [p for p, s in mp.items() if str(s) == str(suc)]
        libres = libres.filter(paciente_id__in=ok)
    else:
        libres = libres.none()
    return (con_item | libres).distinct()


# ─────────────────────────────────────────────────────────────────────
# ÍTEMS GENERADOS (sesiones sueltas, proyectos, mensualidades)
# ─────────────────────────────────────────────────────────────────────
def _items_generados(desde, hasta, suc):
    """Lista de ítems consumidos/comprometidos en el rango:
    [{'pac', 'fecha', 'monto', 'tipo': 'sesion'|'proyecto'|'mensualidad', 'servicio', 'suc'}]"""
    from agenda.models import Mensualidad, Proyecto, Sesion
    out = []
    qs = Sesion.objects.filter(fecha__gte=desde, fecha__lte=hasta, estado__in=['realizada', 'realizada_retraso', 'falta'],
                               proyecto__isnull=True, mensualidad__isnull=True)
    if suc:
        qs = qs.filter(sucursal_id=suc)
    for r in qs.values('paciente_id', 'fecha', 'monto_cobrado', 'servicio__nombre', 'sucursal_id'):
        out.append({'pac': r['paciente_id'], 'fecha': r['fecha'], 'monto': _f(r['monto_cobrado']), 'tipo': 'sesion',
                    'servicio': r['servicio__nombre'] or 'Sin servicio', 'suc': r['sucursal_id']})
    qp = Proyecto.objects.filter(fecha_inicio__gte=desde, fecha_inicio__lte=hasta, estado__in=['en_progreso', 'finalizado', 'cancelado'])
    if suc:
        qp = qp.filter(sucursal_id=suc)
    for r in qp.values('paciente_id', 'fecha_inicio', 'costo_total', 'servicio_base__nombre', 'sucursal_id'):
        out.append({'pac': r['paciente_id'], 'fecha': r['fecha_inicio'], 'monto': _f(r['costo_total']), 'tipo': 'proyecto',
                    'servicio': r['servicio_base__nombre'] or 'Proyecto', 'suc': r['sucursal_id']})
    qm = Mensualidad.objects.filter(estado__in=['activa', 'vencida', 'pausada', 'completada', 'cancelada']).filter(
        Q(anio__gt=desde.year) | Q(anio=desde.year, mes__gte=desde.month)).filter(
        Q(anio__lt=hasta.year) | Q(anio=hasta.year, mes__lte=hasta.month))
    if suc:
        qm = qm.filter(sucursal_id=suc)
    for r in qm.values('paciente_id', 'anio', 'mes', 'costo_mensual', 'sucursal_id'):
        out.append({'pac': r['paciente_id'], 'fecha': date(r['anio'], r['mes'], 1), 'monto': _f(r['costo_mensual']),
                    'tipo': 'mensualidad', 'servicio': 'Mensualidades', 'suc': r['sucursal_id']})
    return out


def _resumen_periodo(desde, hasta, suc):
    items = _items_generados(desde, hasta, suc)
    gen = {'sesion': 0.0, 'proyecto': 0.0, 'mensualidad': 0.0}
    for it in items:
        gen[it['tipo']] += it['monto']
    total_gen = sum(gen.values())
    pg = _pagos(desde, hasta, suc)
    bruto = _f(pg.aggregate(t=Sum('monto'))['t'])
    dev = _f(_devoluciones(desde, hasta, suc).aggregate(t=Sum('monto'))['t'])
    anul = _f(_pagos(desde, hasta, suc, anulados=True).aggregate(t=Sum('monto'))['t'])
    return {'gen': gen, 'generado': total_gen, 'bruto': bruto, 'devoluciones': dev, 'neto': bruto - dev, 'anulados': anul,
            'cobranza': _pct(bruto - dev, total_gen), 'n_pagos': pg.count(), 'items': items}


# ─────────────────────────────────────────────────────────────────────
# EGRESOS
# ─────────────────────────────────────────────────────────────────────
def _egresos(desde, hasta, suc):
    """Egresos registrados en el período contable. Con sucursal: solo los de esa sucursal."""
    try:
        from egresos.models import CategoriaEgreso, Egreso
    except Exception:  # módulo no disponible
        return {'total': 0.0, 'oper': 0.0, 'honorarios': 0.0, 'n': 0, 'cats': [], 'global_excl': 0.0, 'disponible': False}
    ini_m, fin_m = (desde.year, desde.month), (hasta.year, hasta.month)
    qs = Egreso.objects.filter(anulado=False).select_related('categoria')
    con_periodo = qs.filter(periodo_anio__isnull=False)
    sin_periodo = qs.filter(periodo_anio__isnull=True, fecha__gte=desde, fecha__lte=hasta)
    tipo_txt = dict(CategoriaEgreso.TIPO_CHOICES)
    cats, tot, hon, n, glob_excl = defaultdict(float), 0.0, 0.0, 0, 0.0
    for e in list(con_periodo.filter(periodo_anio__gte=desde.year, periodo_anio__lte=hasta.year)) + list(sin_periodo):
        y, m = (e.periodo_anio or e.fecha.year), (e.periodo_mes or e.fecha.month)
        if not (ini_m <= (y, m) <= fin_m):
            continue
        if suc and e.sucursal_id is not None and str(e.sucursal_id) != str(suc):
            continue
        if suc and e.sucursal_id is None:
            glob_excl += _f(e.monto)
            continue
        monto = _f(e.monto)
        es_hon = bool(getattr(e.categoria, 'es_honorario_profesional', False))
        n += 1
        if es_hon:
            hon += monto
        else:
            tot += monto
            cats[(e.categoria.nombre, tipo_txt.get(e.categoria.tipo, e.categoria.tipo))] += monto
    cat_list = [{'nombre': k[0], 'tipo': k[1], 'monto': round(v, 2), 'pct': _pct(v, tot)} for k, v in sorted(cats.items(), key=lambda kv: -kv[1])]
    return {'total': tot, 'oper': tot, 'honorarios': hon, 'n': n, 'cats': cat_list, 'global_excl': glob_excl, 'disponible': True}


def _egresos_mes(mes_ini, suc):
    return _egresos(mes_ini, _fin_mes(mes_ini), suc)['total']


def _comisiones(desde, hasta, suc):
    try:
        from servicios.models import ComisionSesion
        qs = ComisionSesion.objects.filter(sesion__fecha__gte=desde, sesion__fecha__lte=hasta,
                                           sesion__estado__in=['realizada', 'realizada_retraso'])
        if suc:
            qs = qs.filter(sesion__sucursal_id=suc)
        return _f(qs.aggregate(t=Sum('monto_profesional'))['t'])
    except Exception:
        return 0.0


# ─────────────────────────────────────────────────────────────────────
# SERIE MENSUAL (últimos 12 meses)
# ─────────────────────────────────────────────────────────────────────
def _serie_mensual(hasta, suc, n=12):
    from agenda.models import Mensualidad, Proyecto, Sesion
    ini = _mes_mas(_mes_ini(hasta), -(n - 1))
    fin = _fin_mes(_mes_ini(hasta))
    gen = defaultdict(float)
    qs = Sesion.objects.filter(fecha__gte=ini, fecha__lte=fin, estado__in=['realizada', 'realizada_retraso', 'falta'],
                               proyecto__isnull=True, mensualidad__isnull=True)
    if suc:
        qs = qs.filter(sucursal_id=suc)
    for r in qs.annotate(m=TruncMonth('fecha')).values('m').annotate(t=Sum('monto_cobrado')):
        gen[(r['m'].year, r['m'].month)] += _f(r['t'])
    qp = Proyecto.objects.filter(fecha_inicio__gte=ini, fecha_inicio__lte=fin, estado__in=['en_progreso', 'finalizado', 'cancelado'])
    if suc:
        qp = qp.filter(sucursal_id=suc)
    for r in qp.annotate(m=TruncMonth('fecha_inicio')).values('m').annotate(t=Sum('costo_total')):
        gen[(r['m'].year, r['m'].month)] += _f(r['t'])
    qm = Mensualidad.objects.filter(estado__in=['activa', 'vencida', 'pausada', 'completada', 'cancelada']).filter(
        Q(anio__gt=ini.year) | Q(anio=ini.year, mes__gte=ini.month)).filter(Q(anio__lt=fin.year) | Q(anio=fin.year, mes__lte=fin.month))
    if suc:
        qm = qm.filter(sucursal_id=suc)
    for r in qm.values('anio', 'mes').annotate(t=Sum('costo_mensual')):
        gen[(r['anio'], r['mes'])] += _f(r['t'])
    cob = defaultdict(float)
    for r in _pagos(ini, fin, suc).annotate(m=TruncMonth('fecha_pago')).values('m').annotate(t=Sum('monto')):
        cob[(r['m'].year, r['m'].month)] += _f(r['t'])
    for r in _devoluciones(ini, fin, suc).annotate(m=TruncMonth('fecha_devolucion')).values('m').annotate(t=Sum('monto')):
        cob[(r['m'].year, r['m'].month)] -= _f(r['t'])
    pts = []
    for i in range(n):
        m0 = _mes_mas(ini, i)
        k = (m0.year, m0.month)
        eg = _egresos_mes(m0, suc)
        g, c = gen.get(k, 0.0), cob.get(k, 0.0)
        pts.append({'label': f"{MESES[m0.month]} {str(m0.year)[2:]}", 'generado': round(g, 2), 'cobrado': round(c, 2),
                    'egresos': round(eg, 2), 'resultado': round(c - eg, 2), 'cobranza': _pct(c, g)})
    return pts


# ─────────────────────────────────────────────────────────────────────
# CARTERA: deudores, antigüedad, créditos
# ─────────────────────────────────────────────────────────────────────
def _consumos_hasta(pids, hoy):
    """Consumos ya realizados por paciente (para la antigüedad FIFO): {pac: [(fecha, monto)] ordenado ascendente}."""
    from agenda.models import Mensualidad, Proyecto, Sesion
    d = defaultdict(list)
    for r in Sesion.objects.filter(paciente_id__in=pids, fecha__lte=hoy, estado__in=['realizada', 'realizada_retraso', 'falta'],
                                   proyecto__isnull=True, mensualidad__isnull=True).values_list('paciente_id', 'fecha', 'monto_cobrado'):
        d[r[0]].append((r[1], _f(r[2])))
    for r in Proyecto.objects.filter(paciente_id__in=pids, fecha_inicio__lte=hoy, estado__in=['en_progreso', 'finalizado', 'cancelado']
                                     ).values_list('paciente_id', 'fecha_inicio', 'costo_total'):
        d[r[0]].append((r[1], _f(r[2])))
    for r in Mensualidad.objects.filter(paciente_id__in=pids).exclude(estado='pausada').values_list('paciente_id', 'anio', 'mes', 'costo_mensual'):
        f0 = date(r[1], r[2], 1)
        if f0 <= hoy:
            d[r[0]].append((f0, _f(r[3])))
    for k in d:
        d[k].sort()
    return d


def _antiguedad_fifo(consumos, deuda_real, hoy):
    """Reparte la deuda realizada sobre los consumos MÁS RECIENTES (los viejos se asumen pagados primero).
    Devuelve (buckets {0-30, 31-60, 61-90, 90+}, edad_max_dias)."""
    b = {'0-30': 0.0, '31-60': 0.0, '61-90': 0.0, '90+': 0.0}
    resto = deuda_real
    edad_max = 0
    for f, m in reversed(consumos):
        if resto <= 0.5:
            break
        parte = min(m, resto)
        resto -= parte
        edad = (hoy - f).days
        edad_max = max(edad_max, edad)
        k = '0-30' if edad <= 30 else ('31-60' if edad <= 60 else ('61-90' if edad <= 90 else '90+'))
        b[k] += parte
    if resto > 0.5:   # deuda sin consumo identificable (saldos arrastrados): se toma como antigua
        b['90+'] += resto
        edad_max = max(edad_max, 91)
    return b, edad_max


def _cartera(hoy, suc):
    from facturacion.models import CuentaCorriente, Pago
    ccs = list(CuentaCorriente.objects.filter(Q(saldo_real__lt=-0.5) | Q(saldo_actual__lt=-0.5)).select_related('paciente'))
    cred_qs = CuentaCorriente.objects.filter(saldo_actual__gt=0.5)
    if suc:
        from facturacion.views import _build_sucursal_map
        _ids = list(cred_qs.values_list('paciente_id', flat=True))
        _mp = _build_sucursal_map(_ids) if _ids else {}
        cred_qs = cred_qs.filter(paciente_id__in=[i for i in _ids if str(_mp.get(i)) == str(suc)])
    cred_total = _f(cred_qs.aggregate(t=Sum('saldo_actual'))['t'])
    cred_n = cred_qs.count()
    pids = [c.paciente_id for c in ccs]
    if suc and pids:
        from facturacion.views import _build_sucursal_map
        mp = _build_sucursal_map(pids)
        ccs = [c for c in ccs if str(mp.get(c.paciente_id)) == str(suc)]
        pids = [c.paciente_id for c in ccs]
    cons = _consumos_hasta(pids, hoy)
    ult_pago = {r['paciente_id']: r['m'] for r in Pago.objects.filter(paciente_id__in=pids, anulado=False)
                .exclude(metodo_pago__nombre=NO_DINERO).values('paciente_id').annotate(m=Max('fecha_pago'))}
    filas, aging = [], {'0-30': 0.0, '31-60': 0.0, '61-90': 0.0, '90+': 0.0}
    for c in ccs:
        p = c.paciente
        total = max(-_f(c.saldo_real), 0.0)
        real = max(-_f(c.saldo_actual), 0.0)
        if total < 1 and real < 1:
            continue
        b, edad = _antiguedad_fifo(cons.get(c.paciente_id, []), real, hoy)
        for k, v in b.items():
            aging[k] += v
        up = ult_pago.get(c.paciente_id)
        dias_sp = (hoy - up).days if up else None
        activo = p.estado == 'activo'
        if (not activo and real > 0) or edad > 60 or (dias_sp is not None and dias_sp > 60 and real > 0):
            riesgo = 'alto'
        elif edad > 30 or (dias_sp is not None and dias_sp > 30 and real > 0):
            riesgo = 'medio'
        else:
            riesgo = 'bajo'
        dig = ''.join(ch for ch in (p.telefono_tutor or '') if ch.isdigit())
        wa = ('591' + dig) if len(dig) == 8 else (dig if len(dig) >= 10 else '')
        filas.append({'id': c.paciente_id, 'wa': wa, 'nombre': f"{p.nombre} {p.apellido}".strip(), 'tutor': p.nombre_tutor,
                      'telefono': p.telefono_tutor, 'activo': activo, 'total': round(total, 2), 'real': round(real, 2),
                      'agendado': round(max(total - real, 0.0), 2), 'edad': edad, 'ultimo_pago': up, 'dias_sin_pagar': dias_sp,
                      'riesgo': riesgo, 'buckets': b})
    filas.sort(key=lambda x: -x['total'])
    tot_total = sum(x['total'] for x in filas)
    tot_real = sum(x['real'] for x in filas)
    top5 = sum(x['total'] for x in filas[:5])
    inactivos = [x for x in filas if not x['activo'] and x['real'] > 0]
    return {'filas': filas, 'n': len(filas), 'total': round(tot_total, 2), 'real': round(tot_real, 2),
            'agendado': round(tot_total - tot_real, 2), 'aging': {k: round(v, 2) for k, v in aging.items()},
            'top5_pct': _pct(top5, tot_total), 'inactivos_n': len(inactivos),
            'inactivos_monto': round(sum(x['real'] for x in inactivos), 2),
            'riesgo_alto_n': sum(1 for x in filas if x['riesgo'] == 'alto'),
            'riesgo_alto_monto': round(sum(x['real'] for x in filas if x['riesgo'] == 'alto'), 2),
            'resto': round(sum(x['total'] for x in filas[15:]), 2),
            'creditos_total': round(cred_total, 2), 'creditos_n': cred_n}


# ─────────────────────────────────────────────────────────────────────
# PUNTUALIDAD DE PAGO
# ─────────────────────────────────────────────────────────────────────
def _puntualidad(hasta, suc, cartera_idx, dias=365):
    """Por paciente: pagos directos a ítems (sesión/proyecto/mensualidad) en el último año y su demora."""
    from facturacion.models import Pago
    desde = hasta - timedelta(days=dias)
    qs = (Pago.objects.filter(anulado=False, fecha_pago__gte=desde, fecha_pago__lte=hasta)
          .exclude(metodo_pago__nombre=NO_DINERO)
          .filter(Q(sesion__isnull=False) | Q(proyecto__isnull=False) | Q(mensualidad__isnull=False)))
    if suc:
        qs = qs.filter(Q(sesion__sucursal_id=suc) | Q(proyecto__sucursal_id=suc) | Q(mensualidad__sucursal_id=suc))
    por = defaultdict(lambda: {'n': 0, 'puntuales': 0, 'monto': 0.0, 'demora_pond': 0.0, 'nombre': ''})
    for r in qs.values('paciente_id', 'paciente__nombre', 'paciente__apellido', 'paciente__estado', 'fecha_pago', 'monto',
                       'sesion__fecha', 'proyecto__fecha_inicio', 'mensualidad__anio', 'mensualidad__mes'):
        if r['sesion__fecha']:
            f0 = r['sesion__fecha']
        elif r['proyecto__fecha_inicio']:
            f0 = r['proyecto__fecha_inicio']
        else:
            f0 = date(r['mensualidad__anio'], r['mensualidad__mes'], 1)
        demora = max((r['fecha_pago'] - f0).days, 0)
        d = por[r['paciente_id']]
        d['nombre'] = f"{r['paciente__nombre']} {r['paciente__apellido']}".strip()
        d['activo'] = r['paciente__estado'] == 'activo'
        d['n'] += 1
        d['monto'] += _f(r['monto'])
        d['demora_pond'] += demora * _f(r['monto'])
        if demora <= PUNTUAL_DIAS:
            d['puntuales'] += 1
    filas = []
    for pid, d in por.items():
        if d['n'] < MIN_PAGOS_PUNTUAL:
            continue
        deuda = cartera_idx.get(pid, 0.0)
        filas.append({'id': pid, 'nombre': d['nombre'], 'activo': d['activo'], 'pagos': d['n'], 'monto': round(d['monto'], 2),
                      'pct_puntual': _pct(d['puntuales'], d['n']),
                      'demora_prom': round(d['demora_pond'] / d['monto'], 1) if d['monto'] else 0.0, 'deuda': round(deuda, 2)})
    cumplidos = sorted([x for x in filas if x['pct_puntual'] >= 80 and x['deuda'] <= 1],
                       key=lambda x: (-x['pct_puntual'], x['demora_prom'], -x['monto']))[:12]
    lentos = sorted([x for x in filas if x['pct_puntual'] < 50], key=lambda x: (x['pct_puntual'], -x['demora_prom']))[:12]
    tot_pagos = sum(d['n'] for d in por.values())
    tot_punt = sum(d['puntuales'] for d in por.values())
    return {'cumplidos': cumplidos, 'lentos': lentos, 'n_evaluados': len(filas),
            'pct_global': _pct(tot_punt, tot_pagos), 'dias': PUNTUAL_DIAS}


# ─────────────────────────────────────────────────────────────────────
# PACIENTES QUE MÁS / MENOS GENERAN
# ─────────────────────────────────────────────────────────────────────
def _pacientes_generan(items, pagos_por_pac, total_gen):
    from pacientes.models import Paciente
    por = defaultdict(lambda: {'gen': 0.0, 'ses': 0, 'proy': 0.0, 'mens': 0.0})
    for it in items:
        d = por[it['pac']]
        d['gen'] += it['monto']
        if it['tipo'] == 'sesion':
            d['ses'] += 1
        elif it['tipo'] == 'proyecto':
            d['proy'] += it['monto']
        else:
            d['mens'] += it['monto']
    pids = list(por.keys())
    noms = {p.id: (f"{p.nombre} {p.apellido}".strip(), p.estado) for p in Paciente.objects.filter(id__in=pids).only('id', 'nombre', 'apellido', 'estado')}
    filas = []
    for pid, d in por.items():
        if d['gen'] <= 0:
            continue
        nom, est = noms.get(pid, ('—', 'activo'))
        cob = pagos_por_pac.get(pid, 0.0)
        filas.append({'id': pid, 'nombre': nom, 'activo': est == 'activo', 'generado': round(d['gen'], 2), 'sesiones': d['ses'],
                      'proyectos': round(d['proy'], 2), 'mensualidades': round(d['mens'], 2), 'cobrado': round(cob, 2),
                      'pct': _pct(d['gen'], total_gen), 'cobranza': _pct(cob, d['gen'])})
    filas.sort(key=lambda x: -x['generado'])
    n = len(filas)
    top5 = sum(x['generado'] for x in filas[:5])
    top10 = sum(x['generado'] for x in filas[:10])
    acum = 0.0
    n80 = 0
    for x in filas:
        acum += x['generado']
        n80 += 1
        if acum >= 0.8 * total_gen:
            break
    ticket = round(total_gen / n, 2) if n else 0.0
    menos = sorted(filas, key=lambda x: x['generado'])[:12]
    return {'mas': filas[:15], 'menos': menos, 'n': n, 'top5_pct': _pct(top5, total_gen), 'top10_pct': _pct(top10, total_gen),
            'n80': n80, 'n80_pct': _pct(n80, n), 'ticket': ticket,
            'mediana': round(sorted(x['generado'] for x in filas)[n // 2], 2) if n else 0.0}


def _cobrado_por_paciente(desde, hasta, suc):
    cob = defaultdict(float)
    for r in _pagos(desde, hasta, suc).values('paciente_id').annotate(t=Sum('monto')):
        cob[r['paciente_id']] += _f(r['t'])
    for r in _devoluciones(desde, hasta, suc).values('paciente_id').annotate(t=Sum('monto')):
        cob[r['paciente_id']] -= _f(r['t'])
    return cob


# ─────────────────────────────────────────────────────────────────────
# DESGLOSES: sucursal, servicio, método de pago
# ─────────────────────────────────────────────────────────────────────
def _por_sucursal(desde, hasta, hoy):
    from servicios.models import Sucursal
    out = []
    for s in Sucursal.objects.filter(activa=True):
        r = _resumen_periodo(desde, hasta, s.id)
        eg = _egresos(desde, hasta, s.id)['total']
        car = _cartera(hoy, s.id)
        out.append({'id': s.id, 'nombre': s.nombre, 'generado': r['generado'], 'cobrado': r['neto'], 'cobranza': r['cobranza'],
                    'egresos': eg, 'resultado': r['neto'] - eg, 'deuda': car['total'], 'deuda_real': car['real']})
    out.sort(key=lambda x: -x['generado'])
    return out


def _por_servicio(items, total_gen):
    por = defaultdict(lambda: {'gen': 0.0, 'n': 0})
    for it in items:
        por[it['servicio']]['gen'] += it['monto']
        por[it['servicio']]['n'] += 1
    return [{'nombre': k, 'generado': round(v['gen'], 2), 'n': v['n'], 'pct': _pct(v['gen'], total_gen),
             'promedio': round(v['gen'] / v['n'], 2) if v['n'] else 0.0}
            for k, v in sorted(por.items(), key=lambda kv: -kv[1]['gen']) if v['gen'] > 0][:10]


def _por_metodo(desde, hasta, suc):
    rows = list(_pagos(desde, hasta, suc).values('metodo_pago__nombre').annotate(m=Sum('monto'), n=Count('id')).order_by('-m'))
    tot = sum(_f(r['m']) for r in rows)
    return [{'nombre': r['metodo_pago__nombre'], 'monto': round(_f(r['m']), 2), 'n': r['n'], 'pct': _pct(_f(r['m']), tot)} for r in rows], tot


def _agendado_futuro(hoy, suc, dias=30):
    from agenda.models import Sesion
    qs = Sesion.objects.filter(fecha__gt=hoy, fecha__lte=hoy + timedelta(days=dias), estado='programada',
                               proyecto__isnull=True, mensualidad__isnull=True)
    if suc:
        qs = qs.filter(sucursal_id=suc)
    a = qs.aggregate(t=Sum('monto_cobrado'), n=Count('id'))
    return {'monto': _f(a['t']), 'n': a['n'] or 0, 'dias': dias}


# ─────────────────────────────────────────────────────────────────────
# DECISIONES
# ─────────────────────────────────────────────────────────────────────
def _bs(v):
    return 'Bs. ' + f"{v:,.0f}".replace(',', '.')


def _decisiones(a):
    d = []
    add = lambda nivel, titulo, detalle, accion='': d.append({'nivel': nivel, 'titulo': titulo, 'detalle': detalle, 'accion': accion})
    R, P, C = a['R'], a['P'], a['cartera']
    gen = R['generado']

    if gen > 0:
        cb = R['cobranza']
        if cb < UMBRAL_COBRANZA_MAL:
            add('alerta', f"Cobranza baja: {cb:.0f}% de lo generado",
                f"Se generaron {_bs(gen)} y se cobraron {_bs(R['neto'])} netos. Falta cobrar {_bs(max(gen - R['neto'], 0))} del período.",
                'Priorizar esta semana la lista «A quién cobrar» y confirmar los saldos con recepción.')
        elif cb < UMBRAL_COBRANZA_OK:
            add('aviso', f"Cobranza por debajo de la meta: {cb:.0f}%", f"Meta {UMBRAL_COBRANZA_OK:.0f}%. Se cobró {_bs(R['neto'])} de {_bs(gen)} generados.",
                'Recordar saldos por WhatsApp a las familias con deuda y ofrecer facilidades de pago.')
        else:
            add('ok', f"Buena cobranza: {cb:.0f}%", f"Se cobró {_bs(R['neto'])} de {_bs(gen)} generados.", 'Mantener el seguimiento actual.')

    if C['total'] > 0:
        ag = C['aging']
        viejo = ag['61-90'] + ag['90+']
        add('alerta' if viejo > 0.25 * C['real'] and viejo > 500 else 'aviso',
            f"Cartera por cobrar: {_bs(C['total'])} ({C['n']} pacientes)",
            f"De eso, {_bs(C['real'])} ya se consumió y {_bs(C['agendado'])} está agendado. Con más de 60 días: {_bs(viejo)}.",
            'Llamar a los deudores de la lista, empezando por los de riesgo alto; no seguir agendando sin plan de pago a quienes superan 60 días.')
        if C['top5_pct'] >= 50 and C['n'] >= 6:
            add('aviso', f"La deuda está concentrada: 5 pacientes deben el {C['top5_pct']:.0f}%",
                'Cobrar a pocos pacientes recupera la mayor parte de la cartera.', 'Atiende primero a esos cinco con una conversación personal.')
        if C['inactivos_n']:
            add('alerta', f"{C['inactivos_n']} paciente(s) inactivo(s) con deuda: {_bs(C['inactivos_monto'])}",
                'Quienes ya no vienen son los más difíciles de cobrar; mientras más pasa el tiempo, menos probable es recuperar el dinero.',
                'Gestionar el cobro cuanto antes o decidir un acuerdo/condonación formal.')

    v = _var(R['generado'], P['generado'])
    if v is not None:
        if v <= -10:
            add('alerta' if v <= -20 else 'aviso', f"Los ingresos generados bajaron {abs(v):.0f}%",
                f"{_bs(R['generado'])} frente a {_bs(P['generado'])} del período anterior.",
                'Revisar bajas de pacientes, cancelaciones del centro y asistencia; reforzar la captación.')
        elif v >= 10:
            add('ok', f"Los ingresos generados subieron {v:.0f}%", f"{_bs(R['generado'])} frente a {_bs(P['generado'])} del período anterior.", '')
    vc = _var(R['neto'], P['neto'])
    if vc is not None and vc <= -15:
        add('aviso', f"El dinero cobrado cayó {abs(vc):.0f}%", f"{_bs(R['neto'])} frente a {_bs(P['neto'])} del período anterior.",
            'Comparar con la cobranza: ¿se generó menos o se cobró peor?')

    E = a['egresos']
    if E['disponible'] and E['n'] == 0 and R['neto'] > 0:
        add('aviso', 'No hay egresos registrados en el período',
            'Sin gastos registrados no se puede calcular el resultado real del centro.', 'Registrar alquiler, sueldos, servicios y demás gastos en el módulo Egresos.')
    if E['total'] > 0:
        res = a['resultado']
        if res['valor'] < 0:
            add('alerta', f"Resultado negativo: {_bs(res['valor'])}", f"Se cobró {_bs(R['neto'])} y los gastos fueron {_bs(res['gastos'])}.",
                'Revisar los gastos más grandes y el punto de equilibrio; evaluar ajustes de precios u horarios.')
        elif res['margen'] < 10:
            add('aviso', f"Margen bajo: {res['margen']:.0f}%", f"Resultado {_bs(res['valor'])} sobre {_bs(R['neto'])} cobrados.", 'Cuidar el gasto y empujar ingresos recurrentes (mensualidades).')
        else:
            add('ok', f"Resultado positivo: {_bs(res['valor'])} (margen {res['margen']:.0f}%)", '', '')
        ve = _var(E['total'], a['egresos_prev']['total'])
        if ve is not None and ve >= 15 and E['total'] - a['egresos_prev']['total'] > 500:
            add('aviso', f"Los egresos subieron {ve:.0f}%", f"{_bs(E['total'])} frente a {_bs(a['egresos_prev']['total'])} del período anterior.",
                'Identificar qué categoría creció (ver Egresos por categoría).')

    G = a['pacientes']
    if G['n'] >= 8 and G['top5_pct'] >= 35:
        add('aviso', f"Dependencia de pocos pacientes: 5 generan el {G['top5_pct']:.0f}%",
            f"Se necesitan {G['n80']} pacientes ({G['n80_pct']:.0f}%) para llegar al 80% de los ingresos.",
            'Cuidar especialmente la retención de esas familias y diversificar con nuevos pacientes.')

    dv = R['devoluciones'] + R['anulados']
    if R['bruto'] > 0 and dv / R['bruto'] > 0.03:
        add('aviso', f"Devoluciones y anulaciones altas: {_bs(dv)} ({_pct(dv, R['bruto']):.1f}% de lo cobrado)",
            'Pueden indicar errores de cobro o problemas con las familias.', 'Revisar los motivos en Detalle Pagos.')

    if C['creditos_total'] > 0:
        add('info', f"Saldos a favor de pacientes: {_bs(C['creditos_total'])} ({C['creditos_n']} pacientes)",
            'Es dinero ya cobrado por servicios que aún no se prestaron (una obligación del centro).', 'Evitar gastarlo como si fuera utilidad.')

    fut = a['agendado']
    if fut['monto'] > 0:
        add('info', f"Agendado para los próximos {fut['dias']} días: {_bs(fut['monto'])}", f"{fut['n']} sesiones programadas con monto.", '')

    me = a['metodos']
    if me and me[0]['pct'] >= 85 and 'efectivo' in me[0]['nombre'].lower():
        add('info', f"El {me[0]['pct']:.0f}% de lo cobrado es en efectivo", 'Mayor riesgo de manejo y menor trazabilidad.',
            'Incentivar QR o transferencia y depositar el efectivo con regularidad.')

    P_ = a['puntualidad']
    if P_['n_evaluados'] >= 10 and P_['pct_global'] < 50:
        add('aviso', f"Solo el {P_['pct_global']:.0f}% de los pagos llega a tiempo (≤{PUNTUAL_DIAS} días)", 'Las familias suelen pagar con demora.',
            'Enviar recordatorios al inicio de cada mes y cobrar por adelantado las mensualidades.')
    return d


# ─────────────────────────────────────────────────────────────────────
# ENTRADA PRINCIPAL
# ─────────────────────────────────────────────────────────────────────
def analizar_financiero(desde, hasta, sucursal_id='', hoy=None):
    hoy = hoy or date.today()
    suc = int(sucursal_id) if str(sucursal_id or '').strip().isdigit() else None
    span = (hasta - desde).days + 1
    p_hasta = desde - timedelta(days=1)
    p_desde = p_hasta - timedelta(days=span - 1)

    R = _resumen_periodo(desde, hasta, suc)
    P = _resumen_periodo(p_desde, p_hasta, suc)
    egresos = _egresos(desde, hasta, suc)
    egresos_prev = _egresos(p_desde, p_hasta, suc)
    comis = _comisiones(desde, hasta, suc)
    gastos = egresos['total'] + comis
    res_val = R['neto'] - gastos
    resultado = {'valor': round(res_val, 2), 'gastos': round(gastos, 2), 'comisiones': round(comis, 2),
                 'margen': _pct(res_val, R['neto']) if R['neto'] > 0 else 0.0}
    # punto de equilibrio mensual aproximado: gastos por mes del período
    meses = max(span / 30.0, 1.0)
    resultado['gastos_mes'] = round(gastos / meses, 2)

    cartera = _cartera(hoy, suc)
    deuda_idx = {x['id']: x['real'] for x in cartera['filas']}
    cob_pac = _cobrado_por_paciente(desde, hasta, suc)
    pacientes = _pacientes_generan(R['items'], cob_pac, R['generado'])
    metodos, tot_met = _por_metodo(desde, hasta, suc)
    a = {'desde': desde, 'hasta': hasta, 'p_desde': p_desde, 'p_hasta': p_hasta, 'hoy': hoy, 'sucursal_id': suc,
         'R': {k: v for k, v in R.items() if k != 'items'}, 'P': {k: v for k, v in P.items() if k != 'items'},
         'var_generado': _var(R['generado'], P['generado']), 'var_cobrado': _var(R['neto'], P['neto']),
         'egresos': egresos, 'egresos_prev': egresos_prev, 'resultado': resultado, 'cartera': cartera,
         'pacientes': pacientes, 'metodos': metodos, 'servicios': _por_servicio(R['items'], R['generado']),
         'puntualidad': _puntualidad(hasta, suc, deuda_idx), 'agendado': _agendado_futuro(hoy, suc)}
    # Cuadre: generado − cobrado (flujo del período) frente a la posición de pacientes hoy (deuda consumida − saldos a favor)
    dif = R['generado'] - R['neto']
    neta = cartera['real'] - cartera['creditos_total']
    a['cuadre'] = {'generado': R['generado'], 'cobrado': R['neto'], 'dif': round(dif, 2), 'real': cartera['real'],
                   'creditos': cartera['creditos_total'], 'neta': round(neta, 2), 'residual': round(dif - neta, 2),
                   'agendado': cartera['agendado'], 'deuda_total': cartera['total'], 'cuadra': abs(dif - neta) < 1.0}
    a['serie'] = _serie_mensual(hasta, suc)
    a['sucursales'] = _por_sucursal(desde, hasta, hoy) if not suc else []
    gen = a['R']['gen']
    a['svg_flujo'] = svg_flujo(a['serie'])
    a['svg_antig'] = svg_antiguedad(a['cartera']['aging'])
    a['svg_composicion'] = svg_dona([('Sesiones sueltas', gen['sesion'], '#6366f1'), ('Proyectos', gen['proyecto'], '#0d9488'),
                                      ('Mensualidades', gen['mensualidad'], '#d97706')], _abrev(a['R']['generado']), 'generado')
    a['svg_metodos'] = svg_dona([(m['nombre'], m['monto'], c) for m, c in zip(a['metodos'][:5], ('#059669', '#2563eb', '#7c3aed', '#d97706', '#64748b'))],
                                _abrev(sum(m['monto'] for m in a['metodos'])), 'cobrado')
    a['decisiones'] = _decisiones(a)
    orden = {'alerta': 0, 'aviso': 1, 'info': 2, 'ok': 3}
    a['decisiones'].sort(key=lambda x: orden[x['nivel']])
    a['n_alertas'] = sum(1 for x in a['decisiones'] if x['nivel'] == 'alerta')
    a['n_avisos'] = sum(1 for x in a['decisiones'] if x['nivel'] == 'aviso')
    return a


# ─────────────────────────────────────────────────────────────────────
# GRÁFICOS SVG PARA LA PANTALLA (generados en el servidor: sin JavaScript y sin problemas de coma decimal)
# ─────────────────────────────────────────────────────────────────────
def _abrev(v):
    a = abs(v)
    s = f"{a / 1000:.0f}k" if a >= 10000 else (f"{a / 1000:.1f}k".replace('.0k', 'k') if a >= 1000 else f"{a:.0f}")
    return ('-' if v < 0 else '') + s


def _paso_agradable(rango, n=5):
    import math
    if rango <= 0:
        return 1
    crudo = rango / n
    mag = 10 ** math.floor(math.log10(crudo))
    for m in (1, 2, 2.5, 5, 10):
        if crudo <= m * mag:
            return m * mag
    return 10 * mag


def svg_flujo(serie):
    """Barras agrupadas por mes: generado, cobrado y egresos; línea del resultado (cobrado − egresos)."""
    if not serie:
        return ''
    W, H = 760, 300
    ml, mr, mt, mb = 50, 14, 16, 64
    vmax = max([max(p['generado'], p['cobrado'], p['egresos']) for p in serie] + [1])
    vmin = min([0] + [p['resultado'] for p in serie])
    paso = _paso_agradable(vmax - vmin)
    import math
    top = math.ceil(vmax / paso) * paso
    bot = math.floor(vmin / paso) * paso if vmin < 0 else 0
    ph, pw_ = H - mt - mb, W - ml - mr
    Y = lambda v: mt + ph * (1 - (v - bot) / (top - bot))
    slot = pw_ / len(serie)
    bw = max(5, min(15, slot * 0.24))
    o = [f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="Flujo mensual" style="display:block;max-width:100%;height:auto;font-family:\'Sora\',\'DM Sans\',sans-serif">']
    v = bot
    while v <= top + 1e-6:
        y = Y(v)
        o.append(f'<line x1="{ml}" y1="{y:.1f}" x2="{W - mr}" y2="{y:.1f}" stroke="{"#94a3b8" if abs(v) < 1e-6 else "#e2e8f0"}" stroke-width="{1.2 if abs(v) < 1e-6 else 1}"/>')
        o.append(f'<text x="{ml - 6}" y="{y + 3.5:.1f}" text-anchor="end" font-size="10" fill="#64748b">{_abrev(v)}</text>')
        v += paso
    cols = (('generado', '#6366f1'), ('cobrado', '#059669'), ('egresos', '#dc2626'))
    pts = []
    for i, p in enumerate(serie):
        cx = ml + slot * (i + 0.5)
        for j, (k, col) in enumerate(cols):
            x = cx + (j - 1) * (bw + 2) - bw / 2
            y0, y1 = Y(0), Y(p[k])
            o.append(f'<rect x="{x:.1f}" y="{min(y0, y1):.1f}" width="{bw:.1f}" height="{max(abs(y1 - y0), 1):.1f}" rx="2.5" fill="{col}"><title>{p["label"]} · {k}: Bs. {p[k]:,.0f}</title></rect>')
        pts.append((cx, Y(p['resultado']), p))
        o.append(f'<text x="{cx:.1f}" y="{H - mb + 15}" text-anchor="middle" font-size="10" fill="#475569">{p["label"]}</text>')
    path = ' '.join(f'{"M" if i == 0 else "L"}{x:.1f},{y:.1f}' for i, (x, y, _p) in enumerate(pts))
    o.append(f'<path d="{path}" fill="none" stroke="#0f172a" stroke-width="2" stroke-linejoin="round"/>')
    for x, y, p in pts:
        o.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.2" fill="{"#059669" if p["resultado"] >= 0 else "#dc2626"}" stroke="#fff" stroke-width="1.2"><title>{p["label"]} · resultado: Bs. {p["resultado"]:,.0f}</title></circle>')
    lx = ml + 4
    for txt, col, linea in (('Generado', '#6366f1', 0), ('Cobrado (neto)', '#059669', 0), ('Egresos', '#dc2626', 0), ('Resultado (cobrado − egresos)', '#0f172a', 1)):
        if linea:
            o.append(f'<line x1="{lx}" y1="{H - 14}" x2="{lx + 18}" y2="{H - 14}" stroke="{col}" stroke-width="2"/><circle cx="{lx + 9}" cy="{H - 14}" r="3" fill="{col}"/>')
        else:
            o.append(f'<rect x="{lx}" y="{H - 19}" width="10" height="10" rx="2.5" fill="{col}"/>')
        o.append(f'<text x="{lx + 22}" y="{H - 10}" font-size="10.5" fill="#475569">{txt}</text>')
        lx += 30 + len(txt) * 5.8
    o.append('</svg>')
    return ''.join(o)


def svg_antiguedad(aging):
    """Columnas de la cartera por antigüedad estimada."""
    cats = [('0-30', '0 a 30 días', '#059669'), ('31-60', '31 a 60 días', '#d97706'), ('61-90', '61 a 90 días', '#ea580c'), ('90+', 'Más de 90 días', '#be123c')]
    vmax = max([aging.get(k, 0) for k, _l, _c in cats] + [1])
    W, H = 520, 230
    ml, mr, mt, mb = 12, 12, 26, 44
    ph = H - mt - mb
    slot = (W - ml - mr) / 4
    bw = min(70, slot * 0.62)
    o = [f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="Antigüedad de la deuda" style="display:block;max-width:100%;height:auto;font-family:\'Sora\',\'DM Sans\',sans-serif">']
    o.append(f'<line x1="{ml}" y1="{H - mb}" x2="{W - mr}" y2="{H - mb}" stroke="#cbd5e1"/>')
    tot = sum(aging.get(k, 0) for k, _l, _c in cats) or 1
    for i, (k, lab, col) in enumerate(cats):
        v = aging.get(k, 0)
        cx = ml + slot * (i + 0.5)
        h = max(ph * v / vmax, 2 if v else 0)
        o.append(f'<rect x="{cx - bw / 2:.1f}" y="{H - mb - h:.1f}" width="{bw:.1f}" height="{h:.1f}" rx="5" fill="{col}"><title>{lab}: Bs. {v:,.0f}</title></rect>')
        o.append(f'<text x="{cx:.1f}" y="{H - mb - h - 14:.1f}" text-anchor="middle" font-size="11" font-weight="700" fill="#0f172a">Bs. {_abrev(v)}</text>')
        o.append(f'<text x="{cx:.1f}" y="{H - mb - h - 3:.1f}" text-anchor="middle" font-size="9" fill="#64748b">{100 * v / tot:.0f}%</text>')
        o.append(f'<text x="{cx:.1f}" y="{H - mb + 16}" text-anchor="middle" font-size="10" fill="#475569">{lab}</text>')
    o.append('</svg>')
    return ''.join(o)


def svg_dona(partes, centro_txt='', centro_sub=''):
    """Dona con leyenda. partes: [(etiqueta, valor, color)]."""
    import math
    partes = [p for p in partes if p[1] > 0]
    tot = sum(p[1] for p in partes)
    if not tot:
        return '<p style="color:#64748b;font-size:.78rem">Sin datos en el período.</p>'
    W, H = 460, 190
    cx, cy, r, ri = 92, 95, 78, 48
    o = [f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" style="display:block;max-width:100%;height:auto;font-family:\'Sora\',\'DM Sans\',sans-serif">']
    ang = -math.pi / 2
    for lab, v, col in partes:
        frac = v / tot
        a2 = ang + 2 * math.pi * frac
        if frac > 0.999:
            o.append(f'<circle cx="{cx}" cy="{cy}" r="{(r + ri) / 2}" fill="none" stroke="{col}" stroke-width="{r - ri}"/>')
        else:
            x1, y1, x2, y2 = cx + r * math.cos(ang), cy + r * math.sin(ang), cx + r * math.cos(a2), cy + r * math.sin(a2)
            x3, y3, x4, y4 = cx + ri * math.cos(a2), cy + ri * math.sin(a2), cx + ri * math.cos(ang), cy + ri * math.sin(ang)
            large = 1 if frac > 0.5 else 0
            o.append(f'<path d="M{x1:.1f},{y1:.1f} A{r},{r} 0 {large} 1 {x2:.1f},{y2:.1f} L{x3:.1f},{y3:.1f} A{ri},{ri} 0 {large} 0 {x4:.1f},{y4:.1f} Z" fill="{col}" stroke="#fff" stroke-width="1.5"><title>{lab}: Bs. {v:,.0f}</title></path>')
        ang = a2
    if centro_txt:
        o.append(f'<text x="{cx}" y="{cy + 2}" text-anchor="middle" font-size="15" font-weight="800" fill="#0f172a">{centro_txt}</text>')
        o.append(f'<text x="{cx}" y="{cy + 16}" text-anchor="middle" font-size="9" fill="#64748b">{centro_sub}</text>')
    ly = max(24, cy - len(partes) * 13)
    for lab, v, col in partes:
        o.append(f'<rect x="{200}" y="{ly - 8}" width="10" height="10" rx="2.5" fill="{col}"/>')
        o.append(f'<text x="{216}" y="{ly}" font-size="10.5" fill="#334155">{lab}</text>')
        o.append(f'<text x="{W - 6}" y="{ly}" text-anchor="end" font-size="10.5" font-weight="700" fill="#0f172a">Bs. {v:,.0f}  ({100 * v / tot:.0f}%)</text>')
        ly += 26
    o.append('</svg>')
    return ''.join(o)
