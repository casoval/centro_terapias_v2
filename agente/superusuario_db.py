"""
agente/superusuario_db.py
Consultas de SOLO LECTURA para el Agente Superusuario.
Acceso TOTAL sin restricciones — desde el primer registro hasta hoy.

ARQUITECTURA:
  - extraer_rango_fechas()  → lee lenguaje natural y devuelve (desde, hasta)
  - Todas las funciones de consulta aceptan (fecha_desde, fecha_hasta)
  - construir_contexto_superusuario() usa el rango detectado en cada sección

Ejemplos de lenguaje natural reconocido:
  "enero 2023"              → 2023-01-01 a 2023-01-31
  "el mes pasado"           → mes anterior completo
  "la semana pasada"        → lunes a domingo de la semana anterior
  "del 5 al 20 de marzo"   → rango parcial del mes actual
  "primer trimestre 2024"   → 2024-01-01 a 2024-03-31
  "todo 2023"               → 2023-01-01 a 2023-12-31
  "hoy"                     → solo hoy
  "ayer"                    → solo ayer
  "últimos 90 días"         → hoy-90 a hoy
  (sin fecha)               → últimos 30 días por defecto
"""

import re
import logging
import calendar
from datetime import date, timedelta

log = logging.getLogger('agente')

MESES_ES = {
    'enero': 1, 'febrero': 2, 'marzo': 3, 'abril': 4,
    'mayo': 5, 'junio': 6, 'julio': 7, 'agosto': 8,
    'septiembre': 9, 'setiembre': 9, 'octubre': 10,
    'noviembre': 11, 'diciembre': 12,
}

# ══════════════════════════════════════════════════════════════════════════════
# EXTRACTOR DE FECHAS EN LENGUAJE NATURAL
# ══════════════════════════════════════════════════════════════════════════════

def extraer_rango_fechas(mensaje: str) -> tuple:
    """
    Analiza el mensaje y devuelve (fecha_desde, fecha_hasta).
    Si no detecta ninguna fecha, retorna los últimos 30 días.
    """
    hoy = date.today()
    msg = mensaje.lower().strip()

    # ── Hoy / Ayer ────────────────────────────────────────────────────────────
    if re.search(r'\bhoy\b', msg):
        return hoy, hoy
    if re.search(r'\bayer\b', msg):
        ayer = hoy - timedelta(days=1)
        return ayer, ayer

    # ── Esta semana / semana pasada ───────────────────────────────────────────
    if re.search(r'\besta semana\b', msg):
        lunes = hoy - timedelta(days=hoy.weekday())
        return lunes, hoy
    if re.search(r'\bsemana pasada\b|\bsemana anterior\b', msg):
        lunes_esta = hoy - timedelta(days=hoy.weekday())
        lunes_ant  = lunes_esta - timedelta(days=7)
        domingo    = lunes_ant + timedelta(days=6)
        return lunes_ant, domingo

    # ── Este mes / mes pasado ─────────────────────────────────────────────────
    if re.search(r'\beste mes\b', msg):
        return date(hoy.year, hoy.month, 1), hoy
    if re.search(r'\bmes pasado\b|\bmes anterior\b|\bmes previo\b', msg):
        primer_dia_este = date(hoy.year, hoy.month, 1)
        ultimo_ant      = primer_dia_este - timedelta(days=1)
        return date(ultimo_ant.year, ultimo_ant.month, 1), ultimo_ant

    # ── Este año / año pasado ─────────────────────────────────────────────────
    if re.search(r'\beste año\b|\beste anio\b', msg):
        return date(hoy.year, 1, 1), hoy
    if re.search(r'\baño pasado\b|\banio pasado\b|\baño anterior\b', msg):
        return date(hoy.year - 1, 1, 1), date(hoy.year - 1, 12, 31)

    # ── Últimos N días / semanas / meses ──────────────────────────────────────
    m = re.search(r'últimos?\s+(\d+)\s+d[ií]as?', msg)
    if m:
        return hoy - timedelta(days=int(m.group(1))), hoy

    m = re.search(r'últimos?\s+(\d+)\s+semanas?', msg)
    if m:
        return hoy - timedelta(weeks=int(m.group(1))), hoy

    m = re.search(r'últimos?\s+(\d+)\s+meses?', msg)
    if m:
        n     = int(m.group(1))
        desde = date(hoy.year, hoy.month, 1)
        for _ in range(n):
            desde = (desde - timedelta(days=1)).replace(day=1)
        return desde, hoy

    # ── Trimestres ────────────────────────────────────────────────────────────
    _TRIM = {'primer':1,'primero':1,'1er':1,'segundo':2,'2do':2,'tercer':3,'tercero':3,'3er':3,'cuarto':4,'4to':4}
    m = re.search(
        r'(primer|primero|segundo|tercer|tercero|cuarto|1er?|2do?|3er?|4to?)\s+trimestre'
        r'(?:\s+(?:de\s+)?(\d{4}))?', msg
    )
    if m:
        t    = _TRIM.get(m.group(1), 1)
        anio = int(m.group(2)) if m.group(2) else hoy.year
        mi   = (t - 1) * 3 + 1
        mf   = mi + 2
        return date(anio, mi, 1), date(anio, mf, calendar.monthrange(anio, mf)[1])

    # ── Rango "del X al Y de MES [de AÑO]" ───────────────────────────────────
    _meses_pat = '|'.join(MESES_ES.keys())
    m = re.search(
        rf'del\s+(\d{{1,2}})\s+al\s+(\d{{1,2}})\s+de\s+({_meses_pat})'
        rf'(?:\s+(?:de\s+)?(\d{{4}}))?', msg
    )
    if m:
        mes  = MESES_ES[m.group(3)]
        anio = int(m.group(4)) if m.group(4) else hoy.year
        return date(anio, mes, int(m.group(1))), date(anio, mes, int(m.group(2)))

    # ── "desde X hasta Y" ─────────────────────────────────────────────────────
    m = re.search(
        rf'desde\s+(?:el\s+)?(\d{{1,2}})\s+(?:de\s+)?({_meses_pat})'
        rf'(?:\s+(?:de\s+)?(\d{{4}}))?\s+hasta\s+(?:el\s+)?(\d{{1,2}})\s+(?:de\s+)?({_meses_pat})'
        rf'(?:\s+(?:de\s+)?(\d{{4}}))?', msg
    )
    if m:
        mi   = MESES_ES[m.group(2)]
        ai   = int(m.group(3)) if m.group(3) else hoy.year
        mf   = MESES_ES[m.group(5)]
        af   = int(m.group(6)) if m.group(6) else hoy.year
        return date(ai, mi, int(m.group(1))), date(af, mf, int(m.group(4)))

    # ── Mes con año: "enero 2023", "en enero de 2023", "de marzo" ─────────────
    m = re.search(rf'\b({_meses_pat})\b(?:\s+(?:de\s+)?(\d{{4}}))?', msg)
    if m:
        mes  = MESES_ES[m.group(1)]
        anio = int(m.group(2)) if m.group(2) else hoy.year
        ultimo = calendar.monthrange(anio, mes)[1]
        return date(anio, mes, 1), date(anio, mes, ultimo)

    # ── Año solo: "2022", "todo 2023" ─────────────────────────────────────────
    m = re.search(r'\b(20\d{2})\b', msg)
    if m:
        anio = int(m.group(1))
        fin  = date(anio, 12, 31) if anio < hoy.year else hoy
        return date(anio, 1, 1), fin

    # ── Default: últimos 30 días ──────────────────────────────────────────────
    return hoy - timedelta(days=30), hoy


def _periodo_str(desde: date, hasta: date) -> str:
    """Convierte un rango de fechas en texto legible."""
    if desde == hasta:
        return desde.strftime('%d/%m/%Y')
    if (desde.year == hasta.year and desde.month == hasta.month
            and desde.day == 1
            and hasta.day == calendar.monthrange(hasta.year, hasta.month)[1]):
        return f"{calendar.month_name[desde.month].capitalize()} {desde.year}"
    if desde == date(desde.year, 1, 1) and hasta == date(hasta.year, 12, 31):
        return f"Todo el año {desde.year}"
    return f"{desde.strftime('%d/%m/%Y')} al {hasta.strftime('%d/%m/%Y')}"


# ══════════════════════════════════════════════════════════════════════════════
# RESUMEN EJECUTIVO (siempre con datos de hoy)
# ══════════════════════════════════════════════════════════════════════════════

def get_resumen_general() -> dict:
    hoy = date.today()
    r   = {'fecha_consulta': hoy.strftime('%d/%m/%Y')}

    try:
        from pacientes.models import Paciente
        r['pac_activos']    = Paciente.objects.filter(estado='activo').count()
        r['pac_total']      = Paciente.objects.count()
        r['pac_inactivos']  = Paciente.objects.filter(estado='inactivo').count()
        r['pac_nuevos_mes'] = Paciente.objects.filter(
            fecha_registro__year=hoy.year,
            fecha_registro__month=hoy.month,
        ).count()
    except Exception as e:
        log.error(f'[SuperDB] pacientes: {e}')
        r.update({'pac_activos':'?','pac_total':'?','pac_inactivos':'?','pac_nuevos_mes':'?'})

    try:
        from profesionales.models import Profesional
        r['prof_activos'] = Profesional.objects.filter(activo=True).count()
    except Exception as e:
        log.error(f'[SuperDB] profesionales: {e}')
        r['prof_activos'] = '?'

    try:
        from agenda.models import Sesion
        from django.db.models import Count
        qs      = Sesion.objects.filter(fecha=hoy)
        estados = {x['estado']: x['c'] for x in qs.values('estado').annotate(c=Count('id'))}
        r['ses_programadas'] = estados.get('programada', 0)
        r['ses_realizadas']  = estados.get('realizada', 0) + estados.get('realizada_retraso', 0)
        r['ses_permisos']    = estados.get('permiso', 0)
        r['ses_faltas']      = estados.get('falta', 0)
        r['ses_canceladas']  = estados.get('cancelada', 0)
    except Exception as e:
        log.error(f'[SuperDB] sesiones hoy: {e}')
        for k in ('ses_programadas','ses_realizadas','ses_permisos','ses_faltas','ses_canceladas'):
            r[k] = '?'

    try:
        from facturacion.models import Pago
        from django.db.models import Sum
        r['ingresos_hoy'] = float(
            Pago.objects.filter(fecha_pago=hoy, anulado=False)
            .aggregate(t=Sum('monto'))['t'] or 0
        )
        r['ingresos_mes'] = float(
            Pago.objects.filter(
                fecha_pago__year=hoy.year, fecha_pago__month=hoy.month, anulado=False,
            ).aggregate(t=Sum('monto'))['t'] or 0
        )
    except Exception as e:
        log.error(f'[SuperDB] ingresos: {e}')
        r['ingresos_hoy'] = r['ingresos_mes'] = '?'

    try:
        from egresos.models import ResumenFinanciero
        rf = ResumenFinanciero.objects.filter(mes=hoy.month, anio=hoy.year).first()
        if rf:
            r['resultado_neto'] = float(rf.resultado_neto)
            r['total_egresos']  = float(rf.total_egresos)
            r['margen']         = float(rf.margen_porcentaje)
        else:
            r['resultado_neto'] = r['total_egresos'] = r['margen'] = None
    except Exception as e:
        log.error(f'[SuperDB] resumen financiero: {e}')
        r['resultado_neto'] = None

    return r


# ══════════════════════════════════════════════════════════════════════════════
# SESIONES — HISTÓRICO COMPLETO
# ══════════════════════════════════════════════════════════════════════════════

def get_sesiones_por_periodo(
    fecha_desde: date,
    fecha_hasta: date,
    sucursal_id: int = None,
    profesional_nombre: str = None,
    paciente_nombre: str = None,
) -> dict:
    """Sesiones para cualquier rango histórico desde el primer registro."""
    try:
        from agenda.models import Sesion
        from django.db.models import Count, Sum, Q

        qs = Sesion.objects.filter(
            fecha__gte=fecha_desde,
            fecha__lte=fecha_hasta,
        ).select_related('paciente', 'profesional', 'servicio', 'sucursal')

        if sucursal_id:
            qs = qs.filter(sucursal__id=sucursal_id)
        if profesional_nombre:
            q = Q()
            for p in profesional_nombre.strip().split():
                q |= Q(profesional__nombre__icontains=p) | Q(profesional__apellido__icontains=p)
            qs = qs.filter(q)
        if paciente_nombre:
            q = Q()
            for p in paciente_nombre.strip().split():
                q |= Q(paciente__nombre__icontains=p) | Q(paciente__apellido__icontains=p)
            qs = qs.filter(q)

        total   = qs.count()
        estados = {x['estado']: x['c'] for x in qs.values('estado').annotate(c=Count('id'))}

        monto_total = float(
            qs.filter(estado__in=['realizada', 'realizada_retraso'])
            .aggregate(t=Sum('monto_cobrado'))['t'] or 0
        )

        por_prof = list(
            qs.values('profesional__nombre', 'profesional__apellido')
            .annotate(sesiones=Count('id'), monto=Sum('monto_cobrado'))
            .order_by('-sesiones')
        )
        por_suc = list(
            qs.values('sucursal__nombre').annotate(sesiones=Count('id')).order_by('-sesiones')
        )
        por_serv = list(
            qs.values('servicio__nombre').annotate(sesiones=Count('id')).order_by('-sesiones')
        )

        # Listado individual — máx 80 registros para no saturar el prompt
        detalle = [{
            'fecha':       s.fecha.strftime('%d/%m/%Y'),
            'hora':        s.hora_inicio.strftime('%H:%M') if s.hora_inicio else '—',
            'paciente':    f'{s.paciente.nombre} {s.paciente.apellido}' if s.paciente else '—',
            'profesional': f'{s.profesional.nombre} {s.profesional.apellido}' if s.profesional else '—',
            'servicio':    s.servicio.nombre if s.servicio else '—',
            'estado':      s.estado,
            'monto':       float(s.monto_cobrado or 0),
            'sucursal':    s.sucursal.nombre if s.sucursal else '—',
            'nota':        bool(s.notas_sesion),
        } for s in qs.order_by('fecha', 'hora_inicio')[:80]]

        return {
            'total':           total,
            'realizadas':      estados.get('realizada', 0) + estados.get('realizada_retraso', 0),
            'programadas':     estados.get('programada', 0),
            'faltas':          estados.get('falta', 0),
            'canceladas':      estados.get('cancelada', 0),
            'permisos':        estados.get('permiso', 0),
            'monto_total':     monto_total,
            'por_profesional': por_prof,
            'por_sucursal':    por_suc,
            'por_servicio':    por_serv,
            'detalle':         detalle,
            'truncado':        total > 80,
        }
    except Exception as e:
        log.error(f'[SuperDB] sesiones por periodo: {e}')
        return {}


def get_sesiones_futuras(dias: int = 7) -> list:
    try:
        from agenda.models import Sesion
        hoy    = date.today()
        limite = hoy + timedelta(days=dias)
        qs = Sesion.objects.filter(
            fecha__gte=hoy, fecha__lte=limite,
            estado__in=['programada', 'retraso', 'con_retraso'],
        ).select_related('paciente', 'profesional', 'servicio', 'sucursal').order_by('fecha', 'hora_inicio')
        return [{
            'fecha':       s.fecha.strftime('%d/%m/%Y'),
            'hora':        s.hora_inicio.strftime('%H:%M') if s.hora_inicio else '—',
            'paciente':    f'{s.paciente.nombre} {s.paciente.apellido}' if s.paciente else '—',
            'profesional': f'{s.profesional.nombre} {s.profesional.apellido}' if s.profesional else '—',
            'servicio':    s.servicio.nombre if s.servicio else '—',
            'sucursal':    s.sucursal.nombre if s.sucursal else '—',
            'monto':       float(s.monto_cobrado or 0),
        } for s in qs]
    except Exception as e:
        log.error(f'[SuperDB] sesiones futuras: {e}')
        return []


def get_sesiones_paciente(
    nombre: str,
    fecha_desde: date = None,
    fecha_hasta: date = None,
) -> list:
    """Sesiones de un paciente específico con filtro de período opcional."""
    try:
        from agenda.models import Sesion
        from django.db.models import Q
        q = Q()
        for p in nombre.strip().split():
            q |= Q(paciente__nombre__icontains=p) | Q(paciente__apellido__icontains=p)
        qs = Sesion.objects.filter(q).select_related('profesional', 'servicio', 'sucursal')
        if fecha_desde:
            qs = qs.filter(fecha__gte=fecha_desde)
        if fecha_hasta:
            qs = qs.filter(fecha__lte=fecha_hasta)
        return [{
            'fecha':       s.fecha.strftime('%d/%m/%Y'),
            'profesional': f'{s.profesional.nombre} {s.profesional.apellido}' if s.profesional else '—',
            'servicio':    s.servicio.nombre if s.servicio else '—',
            'estado':      s.estado,
            'monto':       float(s.monto_cobrado or 0),
            'sucursal':    s.sucursal.nombre if s.sucursal else '—',
            'nota':        bool(s.notas_sesion),
        } for s in qs.order_by('-fecha')[:50]]
    except Exception as e:
        log.error(f'[SuperDB] sesiones paciente: {e}')
        return []


# ══════════════════════════════════════════════════════════════════════════════
# PAGOS — HISTÓRICO COMPLETO
# ══════════════════════════════════════════════════════════════════════════════

def get_pagos_por_periodo(
    fecha_desde: date,
    fecha_hasta: date,
    sucursal_nombre: str = None,
    recepcionista_nombre: str = None,
) -> dict:
    """Pagos para cualquier rango histórico con desglose completo."""
    try:
        from facturacion.models import Pago
        from django.db.models import Q

        qs = Pago.objects.filter(
            fecha_pago__gte=fecha_desde,
            fecha_pago__lte=fecha_hasta,
            anulado=False,
        ).select_related(
            'paciente', 'metodo_pago', 'registrado_por',
            'sesion__sucursal', 'proyecto__sucursal', 'mensualidad__sucursal',
        )

        if recepcionista_nombre:
            q = Q()
            for p in recepcionista_nombre.strip().split():
                q |= (
                    Q(registrado_por__first_name__icontains=p) |
                    Q(registrado_por__last_name__icontains=p)
                )
            qs = qs.filter(q)

        def _suc_nombre(p):
            if p.sesion and getattr(p.sesion, 'sucursal', None):
                return p.sesion.sucursal.nombre
            if p.proyecto and getattr(p.proyecto, 'sucursal', None):
                return p.proyecto.sucursal.nombre
            if p.mensualidad and getattr(p.mensualidad, 'sucursal', None):
                return p.mensualidad.sucursal.nombre
            return '—'

        pagos_lista = list(qs.order_by('-fecha_pago', '-fecha_registro'))

        if sucursal_nombre:
            pagos_lista = [
                p for p in pagos_lista
                if sucursal_nombre.lower() in _suc_nombre(p).lower()
            ]

        total_general = sum(float(p.monto) for p in pagos_lista)

        # Acumuladores para desgloses
        por_metodo: dict = {}
        por_recep:  dict = {}
        por_suc:    dict = {}
        por_tipo:   dict = {}

        for p in pagos_lista:
            met    = p.metodo_pago.nombre if p.metodo_pago else '—'
            recep  = (
                p.registrado_por.get_full_name() or p.registrado_por.username
                if p.registrado_por else 'Desconocido'
            )
            suc    = _suc_nombre(p)
            tipo   = p.tipo_pago or '—'
            monto  = float(p.monto)

            for d, k in [(por_metodo, met), (por_recep, recep),
                         (por_suc, suc), (por_tipo, tipo)]:
                if k not in d:
                    d[k] = {'total': 0.0, 'count': 0}
                d[k]['total'] += monto
                d[k]['count'] += 1

        detalle = [{
            'recibo':         p.numero_recibo,
            'fecha':          p.fecha_pago.strftime('%d/%m/%Y'),
            'paciente':       f'{p.paciente.nombre} {p.paciente.apellido}' if p.paciente else '—',
            'monto':          float(p.monto),
            'metodo':         p.metodo_pago.nombre if p.metodo_pago else '—',
            'concepto':       (p.concepto or '')[:60],
            'tipo':           p.tipo_pago or '—',
            'sucursal':       _suc_nombre(p),
            'registrado_por': (
                p.registrado_por.get_full_name() or p.registrado_por.username
                if p.registrado_por else '—'
            ),
        } for p in pagos_lista[:80]]

        return {
            'total_general': total_general,
            'num_pagos':     len(pagos_lista),
            'por_metodo':    por_metodo,
            'por_recep':     por_recep,
            'por_sucursal':  por_suc,
            'por_tipo':      por_tipo,
            'detalle':       detalle,
            'truncado':      len(pagos_lista) > 80,
        }
    except Exception as e:
        log.error(f'[SuperDB] pagos por periodo: {e}')
        return {}


def get_historial_pagos_paciente(nombre: str, limite: int = 20) -> list:
    try:
        from pacientes.models import Paciente
        from facturacion.models import Pago
        from django.db.models import Q
        q = Q()
        for p in nombre.strip().split():
            q |= Q(nombre__icontains=p) | Q(apellido__icontains=p)
        pac = Paciente.objects.filter(q).first()
        if not pac:
            return []
        pagos = (
            Pago.objects
            .filter(paciente=pac, anulado=False)
            .select_related('metodo_pago', 'registrado_por')
            .order_by('-fecha_pago')[:limite]
        )
        return [{
            'recibo':         p.numero_recibo,
            'fecha':          p.fecha_pago.strftime('%d/%m/%Y'),
            'monto':          float(p.monto),
            'metodo':         p.metodo_pago.nombre if p.metodo_pago else '—',
            'concepto':       (p.concepto or '')[:80],
            'tipo':           p.tipo_pago or '—',
            'registrado_por': (
                p.registrado_por.get_full_name() or p.registrado_por.username
                if p.registrado_por else '—'
            ),
        } for p in pagos]
    except Exception as e:
        log.error(f'[SuperDB] historial pagos paciente: {e}')
        return []


# ══════════════════════════════════════════════════════════════════════════════
# EGRESOS — HISTÓRICO COMPLETO
# ══════════════════════════════════════════════════════════════════════════════

def get_egresos_por_periodo(fecha_desde: date, fecha_hasta: date) -> dict:
    try:
        from egresos.models import Egreso
        from django.db.models import Sum, Count

        qs = Egreso.objects.filter(
            fecha__gte=fecha_desde,
            fecha__lte=fecha_hasta,
            anulado=False,
        ).select_related('categoria', 'sucursal')

        total    = float(qs.aggregate(t=Sum('monto'))['t'] or 0)
        por_cat  = list(qs.values('categoria__nombre').annotate(total=Sum('monto'), count=Count('id')).order_by('-total'))
        por_suc  = list(qs.values('sucursal__nombre').annotate(total=Sum('monto'), count=Count('id')).order_by('-total'))
        detalle  = [{
            'fecha':     e.fecha.strftime('%d/%m/%Y'),
            'concepto':  (e.concepto or '')[:60],
            'monto':     float(e.monto),
            'categoria': e.categoria.nombre if e.categoria else '—',
            'sucursal':  e.sucursal.nombre if e.sucursal else 'General',
        } for e in qs.order_by('-fecha')[:50]]

        return {
            'total':         total,
            'num_egresos':   qs.count(),
            'por_categoria': por_cat,
            'por_sucursal':  por_suc,
            'detalle':       detalle,
        }
    except Exception as e:
        log.error(f'[SuperDB] egresos por periodo: {e}')
        return {}


# ══════════════════════════════════════════════════════════════════════════════
# P&L MENSUAL — HISTÓRICO COMPLETO
# ══════════════════════════════════════════════════════════════════════════════

def get_resumen_financiero_mensual(anio: int = None, mes: int = None) -> dict:
    try:
        from egresos.models import ResumenFinanciero
        hoy  = date.today()
        anio = anio or hoy.year
        mes  = mes  or hoy.month
        rf   = ResumenFinanciero.objects.filter(mes=mes, anio=anio).first()
        if not rf:
            return {'disponible': False, 'periodo': f'{calendar.month_name[mes].capitalize()} {anio}'}
        return {
            'disponible':            True,
            'periodo':               f'{calendar.month_name[mes].capitalize()} {anio}',
            'ingresos_brutos':       float(rf.ingresos_brutos),
            'ingresos_adicionales':  float(rf.ingresos_adicionales),
            'total_devoluciones':    float(rf.total_devoluciones),
            'ingresos_netos':        float(rf.ingresos_netos),
            'egresos_arriendo':      float(rf.egresos_arriendo),
            'egresos_servicios':     float(rf.egresos_servicios_basicos),
            'egresos_personal':      float(rf.egresos_personal),
            'egresos_honorarios':    float(rf.egresos_honorarios),
            'egresos_equipamiento':  float(rf.egresos_equipamiento),
            'egresos_mantenimiento': float(rf.egresos_mantenimiento),
            'egresos_marketing':     float(rf.egresos_marketing),
            'egresos_impuestos':     float(rf.egresos_impuestos),
            'egresos_seguros':       float(rf.egresos_seguros),
            'egresos_capacitacion':  float(rf.egresos_capacitacion),
            'egresos_otros':         float(rf.egresos_otros),
            'total_egresos':         float(rf.total_egresos),
            'resultado_neto':        float(rf.resultado_neto),
            'margen_porcentaje':     float(rf.margen_porcentaje),
            'actualizado':           rf.ultima_actualizacion.strftime('%d/%m/%Y %H:%M'),
        }
    except Exception as e:
        log.error(f'[SuperDB] resumen financiero mensual: {e}')
        return {'disponible': False}


def get_comparativa_meses(meses: int = 6) -> list:
    """Compara los últimos N meses. Usa ResumenFinanciero si existe, si no calcula desde Pago."""
    hoy       = date.today()
    resultado = []
    for i in range(meses - 1, -1, -1):
        mes_ref = date(hoy.year, hoy.month, 1)
        for _ in range(i):
            mes_ref = (mes_ref - timedelta(days=1)).replace(day=1)
        mes  = mes_ref.month
        anio = mes_ref.year
        rf   = get_resumen_financiero_mensual(anio=anio, mes=mes)
        if rf.get('disponible'):
            resultado.append({
                'periodo':        rf['periodo'],
                'ingresos':       rf['ingresos_netos'],
                'egresos':        rf['total_egresos'],
                'resultado_neto': rf['resultado_neto'],
                'margen':         rf['margen_porcentaje'],
                'fuente':         'ResumenFinanciero',
            })
        else:
            try:
                from facturacion.models import Pago
                from django.db.models import Sum
                total = float(
                    Pago.objects.filter(
                        fecha_pago__year=anio, fecha_pago__month=mes, anulado=False,
                    ).aggregate(t=Sum('monto'))['t'] or 0
                )
                resultado.append({
                    'periodo':        f'{calendar.month_name[mes].capitalize()} {anio}',
                    'ingresos':       total,
                    'egresos':        None,
                    'resultado_neto': None,
                    'margen':         None,
                    'fuente':         'Pagos',
                })
            except Exception:
                pass
    return resultado


# ══════════════════════════════════════════════════════════════════════════════
# PACIENTES
# ══════════════════════════════════════════════════════════════════════════════

def buscar_paciente(nombre: str = None, telefono: str = None) -> list:
    try:
        from pacientes.models import Paciente
        from django.db.models import Q
        qs = Paciente.objects.all()
        if telefono:
            tel = telefono.strip().replace('+591', '').replace('591', '')
            qs  = qs.filter(telefono_tutor__icontains=tel)
        elif nombre:
            q = Q()
            for p in nombre.strip().split():
                q |= Q(nombre__icontains=p) | Q(apellido__icontains=p)
            qs = qs.filter(q)
        return [{
            'id':          p.id,
            'nombre':      f'{p.nombre} {p.apellido}',
            'estado':      p.estado,
            'tutor':       p.nombre_tutor or '—',
            'telefono':    p.telefono_tutor or '—',
            'diagnostico': (p.diagnostico or '—')[:80],
            'desde':       p.fecha_registro.strftime('%d/%m/%Y') if p.fecha_registro else '—',
        } for p in qs.order_by('apellido', 'nombre')[:15]]
    except Exception as e:
        log.error(f'[SuperDB] buscar paciente: {e}')
        return []


def get_cuenta_corriente_paciente(nombre: str):
    try:
        from pacientes.models import Paciente
        from django.db.models import Q
        q = Q()
        for p in nombre.strip().split():
            q |= Q(nombre__icontains=p) | Q(apellido__icontains=p)
        pac = Paciente.objects.filter(q).first()
        if not pac:
            return None
        cc = getattr(pac, 'cuenta_corriente', None)
        if not cc:
            return {'paciente': f'{pac.nombre} {pac.apellido}', 'sin_cuenta': True}
        return {
            'paciente':              f'{pac.nombre} {pac.apellido}',
            'estado':                pac.estado,
            'total_consumido':       float(cc.total_consumido_actual),
            'total_pagado':          float(cc.total_pagado),
            'saldo_actual':          float(cc.saldo_actual),
            'saldo_real':            float(cc.saldo_real),
            'credito_disponible':    float(cc.pagos_adelantados),
            'total_devoluciones':    float(cc.total_devoluciones),
            'sesiones_pagadas':      float(cc.pagos_sesiones),
            'mensualidades_pagadas': float(cc.pagos_mensualidades),
            'proyectos_pagados':     float(cc.pagos_proyectos),
            'ingreso_neto_centro':   float(cc.ingreso_neto_centro),
            'actualizado':           cc.ultima_actualizacion.strftime('%d/%m/%Y %H:%M'),
        }
    except Exception as e:
        log.error(f'[SuperDB] cuenta corriente: {e}')
        return None


# ══════════════════════════════════════════════════════════════════════════════
# DEVOLUCIONES
# ══════════════════════════════════════════════════════════════════════════════

def get_devoluciones_por_periodo(fecha_desde: date, fecha_hasta: date) -> dict:
    try:
        from facturacion.models import Devolucion
        from django.db.models import Sum
        qs = Devolucion.objects.filter(
            fecha_devolucion__gte=fecha_desde,
            fecha_devolucion__lte=fecha_hasta,
        ).select_related('paciente', 'metodo_devolucion', 'registrado_por')
        total   = float(qs.aggregate(t=Sum('monto'))['t'] or 0)
        detalle = [{
            'numero':         d.numero_devolucion,
            'fecha':          d.fecha_devolucion.strftime('%d/%m/%Y'),
            'paciente':       f'{d.paciente.nombre} {d.paciente.apellido}' if d.paciente else '—',
            'monto':          float(d.monto),
            'motivo':         (d.motivo or '')[:80],
            'metodo':         d.metodo_devolucion.nombre if d.metodo_devolucion else '—',
            'registrado_por': (
                d.registrado_por.get_full_name() or d.registrado_por.username
                if d.registrado_por else '—'
            ),
        } for d in qs.order_by('-fecha_devolucion')[:30]]
        return {'total': total, 'num_devoluciones': qs.count(), 'detalle': detalle}
    except Exception as e:
        log.error(f'[SuperDB] devoluciones: {e}')
        return {}


# ══════════════════════════════════════════════════════════════════════════════
# DEUDAS
# ══════════════════════════════════════════════════════════════════════════════

def get_deudas_pendientes(limite: int = 20) -> list:
    try:
        from facturacion.models import CuentaCorriente
        qs = (
            CuentaCorriente.objects
            .filter(saldo_actual__lt=0)
            .select_related('paciente')
            .order_by('saldo_actual')[:limite]
        )
        return [{
            'paciente':   f'{c.paciente.nombre} {c.paciente.apellido}' if c.paciente else '—',
            'deuda':      abs(float(c.saldo_actual or 0)),
            'deuda_real': abs(float(c.saldo_real or 0)),
            'neto':       float(c.ingreso_neto_centro or 0),
        } for c in qs]
    except Exception as e:
        log.error(f'[SuperDB] deudas: {e}')
        return []


# ══════════════════════════════════════════════════════════════════════════════
# PROFESIONALES / RENTABILIDAD
# ══════════════════════════════════════════════════════════════════════════════

def get_profesionales() -> list:
    try:
        from profesionales.models import Profesional
        profs = Profesional.objects.filter(activo=True).prefetch_related('sucursales')
        return [{
            'nombre':       f'{p.nombre} {p.apellido}',
            'especialidad': p.especialidad,
            'sucursales':   ', '.join(s.nombre for s in p.sucursales.all()) or '—',
            'email':        p.email or '—',
            'telefono':     p.telefono or '—',
        } for p in profs]
    except Exception as e:
        log.error(f'[SuperDB] profesionales: {e}')
        return []


def get_rentabilidad_externos_periodo(fecha_desde: date, fecha_hasta: date) -> list:
    try:
        from servicios.models import ComisionSesion
        from django.db.models import Sum, Count
        datos = (
            ComisionSesion.objects
            .filter(
                sesion__fecha__gte=fecha_desde,
                sesion__fecha__lte=fecha_hasta,
                sesion__estado__in=['realizada', 'realizada_retraso'],
            )
            .values('sesion__profesional__nombre', 'sesion__profesional__apellido')
            .annotate(
                sesiones=Count('id'),
                cobrado=Sum('precio_cobrado'),
                centro=Sum('monto_centro'),
                profesional_monto=Sum('monto_profesional'),
            )
            .order_by('-centro')
        )
        return [{
            'profesional':       f'{d["sesion__profesional__nombre"]} {d["sesion__profesional__apellido"]}',
            'sesiones':          d['sesiones'],
            'cobrado':           float(d['cobrado'] or 0),
            'centro':            float(d['centro'] or 0),
            'profesional_monto': float(d['profesional_monto'] or 0),
        } for d in datos]
    except Exception as e:
        log.error(f'[SuperDB] rentabilidad: {e}')
        return []


# ══════════════════════════════════════════════════════════════════════════════
# MENSUALIDADES / PROYECTOS
# ══════════════════════════════════════════════════════════════════════════════

def get_mensualidades_por_periodo(fecha_desde: date, fecha_hasta: date) -> dict:
    try:
        from agenda.models import Mensualidad
        from django.db.models import Sum
        qs = Mensualidad.objects.filter(
            fecha_inicio__gte=fecha_desde,
            fecha_inicio__lte=fecha_hasta,
        ).select_related('paciente', 'sucursal')
        total   = float(qs.aggregate(t=Sum('costo_mensual'))['t'] or 0)
        detalle = []
        for m in qs.order_by('-anio', '-mes')[:40]:
            try:
                pendiente = float(m.saldo_pendiente)
            except Exception:
                pendiente = float(m.costo_mensual)
            detalle.append({
                'paciente':  f'{m.paciente.nombre} {m.paciente.apellido}' if m.paciente else '—',
                'periodo':   f'{m.mes:02d}/{m.anio}',
                'costo':     float(m.costo_mensual),
                'pendiente': pendiente,
                'estado':    m.estado,
                'sucursal':  m.sucursal.nombre if m.sucursal else '—',
            })
        return {'total': total, 'count': qs.count(), 'detalle': detalle}
    except Exception as e:
        log.error(f'[SuperDB] mensualidades periodo: {e}')
        return {}


def get_proyectos_por_periodo(fecha_desde: date, fecha_hasta: date) -> dict:
    try:
        from agenda.models import Proyecto
        from django.db.models import Sum
        qs = Proyecto.objects.filter(
            fecha_inicio__gte=fecha_desde,
            fecha_inicio__lte=fecha_hasta,
        ).select_related('paciente', 'profesional_responsable', 'sucursal', 'servicio_base')
        total   = float(qs.aggregate(t=Sum('costo_total'))['t'] or 0)
        detalle = []
        for p in qs.order_by('-fecha_inicio')[:30]:
            try:
                pendiente = float(p.saldo_pendiente)
            except Exception:
                pendiente = float(p.costo_total)
            detalle.append({
                'codigo':      p.codigo,
                'nombre':      p.nombre,
                'paciente':    f'{p.paciente.nombre} {p.paciente.apellido}' if p.paciente else '—',
                'profesional': (
                    f'{p.profesional_responsable.nombre} {p.profesional_responsable.apellido}'
                    if p.profesional_responsable else '—'
                ),
                'servicio':    p.servicio_base.nombre if p.servicio_base else '—',
                'costo':       float(p.costo_total),
                'pendiente':   pendiente,
                'estado':      p.estado,
                'inicio':      p.fecha_inicio.strftime('%d/%m/%Y'),
                'sucursal':    p.sucursal.nombre if p.sucursal else '—',
                'informe':     'Entregado' if p.informe_entregado else 'Pendiente',
            })
        return {'total': total, 'count': qs.count(), 'detalle': detalle}
    except Exception as e:
        log.error(f'[SuperDB] proyectos periodo: {e}')
        return {}


# ══════════════════════════════════════════════════════════════════════════════
# STAFF
# ══════════════════════════════════════════════════════════════════════════════

def get_lista_staff() -> list:
    try:
        from core.models import PerfilUsuario
        perfiles = (
            PerfilUsuario.objects
            .filter(activo=True, rol__in=['recepcionista', 'gerente', 'profesional'])
            .select_related('user')
            .prefetch_related('sucursales')
        )
        return [{
            'nombre':     p.user.get_full_name() or p.user.username,
            'rol':        p.get_rol_display(),
            'telefono':   p.telefono or '—',
            'sucursales': ', '.join(s.nombre for s in p.sucursales.all()) or '—',
        } for p in perfiles]
    except Exception as e:
        log.error(f'[SuperDB] lista staff: {e}')
        return []


# ══════════════════════════════════════════════════════════════════════════════
# FORMATEADORES DE SALIDA
# ══════════════════════════════════════════════════════════════════════════════

def _fmt_sesiones(data: dict, periodo: str) -> str:
    if not data:
        return f"Sin sesiones registradas para {periodo}."
    trunc = f" (mostrando primeras 80 de {data['total']})" if data.get('truncado') else ""
    lineas = [
        f"=== SESIONES: {periodo} ===",
        f"Total: {data['total']}{trunc} | Realizadas: {data['realizadas']} | "
        f"Programadas: {data['programadas']} | Faltas: {data['faltas']} | "
        f"Canceladas: {data['canceladas']} | Permisos: {data['permisos']}",
        f"Monto total cobrado: Bs. {data['monto_total']:,.0f}",
    ]
    if data.get('por_profesional'):
        lineas.append("Por profesional:")
        for p in data['por_profesional']:
            monto = float(p.get('monto') or 0)
            lineas.append(
                f"  {p['profesional__nombre']} {p['profesional__apellido']}: "
                f"{p['sesiones']} sesiones — Bs. {monto:,.0f}"
            )
    if data.get('por_sucursal'):
        lineas.append("Por sucursal:")
        for s in data['por_sucursal']:
            lineas.append(f"  {s['sucursal__nombre'] or '—'}: {s['sesiones']} sesiones")
    if data.get('por_servicio'):
        lineas.append("Por servicio:")
        for s in data['por_servicio']:
            lineas.append(f"  {s['servicio__nombre'] or '—'}: {s['sesiones']} sesiones")
    if data.get('detalle'):
        lineas.append("Detalle individual:")
        for s in data['detalle']:
            lineas.append(
                f"  [{s['fecha']}] {s['hora']} — {s['paciente']} con {s['profesional']} "
                f"({s['servicio']}) [{s['sucursal']}] [{s['estado']}] Bs.{s['monto']:.0f}"
                + (' 📝' if s.get('nota') else '')
            )
    return '\n'.join(lineas)


def _fmt_pagos(data: dict, periodo: str) -> str:
    if not data:
        return f"Sin pagos registrados para {periodo}."
    trunc = f" (mostrando primeros 80 de {data['num_pagos']})" if data.get('truncado') else ""
    lineas = [
        f"=== PAGOS: {periodo} ===",
        f"Total: Bs. {data['total_general']:,.0f} en {data['num_pagos']} recibos{trunc}",
    ]
    if data.get('por_recep'):
        lineas.append("Por quién registró el pago:")
        for nombre, v in sorted(data['por_recep'].items(), key=lambda x: -x[1]['total']):
            lineas.append(f"  {nombre}: {v['count']} pagos — Bs. {v['total']:,.0f}")
    if data.get('por_metodo'):
        lineas.append("Por método de pago:")
        for met, v in sorted(data['por_metodo'].items(), key=lambda x: -x[1]['total']):
            lineas.append(f"  {met}: {v['count']} pagos — Bs. {v['total']:,.0f}")
    if data.get('por_sucursal'):
        lineas.append("Por sucursal:")
        for suc, v in sorted(data['por_sucursal'].items(), key=lambda x: -x[1]['total']):
            lineas.append(f"  {suc}: {v['count']} pagos — Bs. {v['total']:,.0f}")
    if data.get('por_tipo'):
        lineas.append("Por tipo:")
        for tipo, v in sorted(data['por_tipo'].items(), key=lambda x: -x[1]['total']):
            lineas.append(f"  {tipo}: {v['count']} pagos — Bs. {v['total']:,.0f}")
    if data.get('detalle'):
        lineas.append("Detalle individual:")
        for p in data['detalle']:
            lineas.append(
                f"  [{p['fecha']}] {p['recibo']} | {p['paciente']} | "
                f"Bs.{p['monto']:,.0f} | {p['metodo']} | {p['tipo']} | "
                f"{p['sucursal']} | Registró: {p['registrado_por']}"
            )
    return '\n'.join(lineas)


def _fmt_pl(rf: dict) -> str:
    if not rf.get('disponible'):
        return f"No hay P&L cerrado para {rf.get('periodo', 'ese período')}."
    return (
        f"=== P&L {rf['periodo'].upper()} ===\n"
        f"Ingresos brutos:     Bs. {rf['ingresos_brutos']:>10,.0f}\n"
        f"Ingresos adicional:  Bs. {rf['ingresos_adicionales']:>10,.0f}\n"
        f"Devoluciones:       -Bs. {rf['total_devoluciones']:>10,.0f}\n"
        f"Ingresos netos:      Bs. {rf['ingresos_netos']:>10,.0f}\n"
        f"─── EGRESOS ───────────────────────\n"
        f"  Arriendo:          Bs. {rf['egresos_arriendo']:>10,.0f}\n"
        f"  Serv. básicos:     Bs. {rf['egresos_servicios']:>10,.0f}\n"
        f"  Personal:          Bs. {rf['egresos_personal']:>10,.0f}\n"
        f"  Honorarios prof:   Bs. {rf['egresos_honorarios']:>10,.0f}\n"
        f"  Equipamiento:      Bs. {rf['egresos_equipamiento']:>10,.0f}\n"
        f"  Mantenimiento:     Bs. {rf['egresos_mantenimiento']:>10,.0f}\n"
        f"  Marketing:         Bs. {rf['egresos_marketing']:>10,.0f}\n"
        f"  Impuestos:         Bs. {rf['egresos_impuestos']:>10,.0f}\n"
        f"  Seguros:           Bs. {rf['egresos_seguros']:>10,.0f}\n"
        f"  Capacitación:      Bs. {rf['egresos_capacitacion']:>10,.0f}\n"
        f"  Otros:             Bs. {rf['egresos_otros']:>10,.0f}\n"
        f"TOTAL EGRESOS:       Bs. {rf['total_egresos']:>10,.0f}\n"
        f"RESULTADO NETO:      Bs. {rf['resultado_neto']:>10,.0f} "
        f"(margen {rf['margen_porcentaje']:.1f}%)\n"
        f"Actualizado: {rf['actualizado']}"
    )


# ══════════════════════════════════════════════════════════════════════════════
# CONSTRUCTOR DE CONTEXTO PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════════

# Agrupaciones de palabras clave por tema
_KW_SESIONES = (
    'sesion', 'sesiones', 'agenda', 'horario', 'cita', 'citas',
    'asistencia', 'atendid', 'falta', 'faltas', 'realiz', 'programad',
    'quién atendió', 'quien atendio', 'cuántas sesiones', 'cuantas sesiones',
    'sesiones de', 'sesiones en', 'sesiones del', 'hizo sesiones',
)
_KW_PAGOS = (
    'pago', 'pagos', 'ingreso', 'ingresos', 'cobro', 'cobros', 'caja',
    'recibo', 'recibos', 'dinero', 'cuánto se cobró', 'cuanto se cobro',
    'total cobrado', 'recaudó', 'recaudo', 'facturación', 'facturacion',
    'registró', 'registro', 'recepcionista', 'recepcionistas',
    'quién cobró', 'quien cobro', 'desglos', 'detall', 'individual',
    'listado de pagos', 'cada pago', 'cuánto cobró', 'cuanto cobro',
    'por método', 'por metodo', 'efectivo', 'transferencia',
)
_KW_PL = (
    'financiero', 'balance', 'resultado', 'neto', 'margen',
    'rentabilidad', 'utilidad', 'pérdida', 'perdida',
    'p&l', 'estado de resultado', 'flujo',
)
_KW_EGRESOS = (
    'egreso', 'egresos', 'gasto', 'gastos', 'arriendo',
    'servicios básicos', 'honorario', 'proveedor', 'compra',
    'cuánto se gastó', 'cuanto se gasto',
)
_KW_DEUDAS = (
    'deuda', 'deudas', 'pendiente', 'pendientes', 'deben',
    'moroso', 'saldo negativo', 'cobrar', 'mora', 'no han pagado',
)
_KW_DEVOL = (
    'devolucion', 'devolución', 'devoluciones', 'reembolso', 'devuelto',
)
_KW_MENS = ('mensualidad', 'mensualidades', 'cuota', 'plan mensual')
_KW_PROY = ('proyecto', 'proyectos', 'evaluacion', 'evaluación', 'eval')
_KW_RENT = (
    'rentabilidad', 'comision', 'comisión', 'externo', 'externos',
    'cuánto queda', 'cuanto queda', 'cuánto gana el profesional',
)
_KW_COMP = (
    'comparar', 'comparativa', ' vs ', 'versus',
    'comparado', 'comparación', 'evolucion', 'evolución', 'tendencia',
    'mejor mes', 'peor mes', 'cómo estuvo', 'como estuvo',
)
_KW_PROF = (
    'profesional', 'profesionales', 'terapeuta', 'staff',
    'equipo', 'personal', 'quiénes trabajan',
)
_KW_PAC = (
    'buscar', 'busca', 'paciente llamado', 'información de', 'datos de',
    'expediente', 'historial de', 'cuenta de', 'saldo de',
    'cuánto debe', 'cuanto debe', 'cuánto ha pagado', 'cuanto ha pagado',
)


def construir_contexto_superusuario(mensaje: str) -> str:
    """
    Construye el bloque de datos inyectado en el prompt del superusuario.

    Flujo:
      1. Extrae el rango de fechas del mensaje en lenguaje natural
      2. Inyecta siempre el resumen ejecutivo de hoy
      3. Activa secciones temáticas según palabras clave,
         todas usando el rango detectado automáticamente
    """
    hoy    = date.today()
    msg    = mensaje.lower().strip()
    partes = []

    # ── Detectar rango de fechas ──────────────────────────────────────────────
    fecha_desde, fecha_hasta = extraer_rango_fechas(mensaje)
    periodo = _periodo_str(fecha_desde, fecha_hasta)
    es_hoy  = (fecha_desde == hoy and fecha_hasta == hoy)

    # ── 1. Resumen ejecutivo — SIEMPRE ────────────────────────────────────────
    r = get_resumen_general()
    neto_str = ''
    if r.get('resultado_neto') is not None:
        signo    = '+' if r['resultado_neto'] >= 0 else ''
        neto_str = (
            f"\nResultado neto del mes: Bs. {signo}{r['resultado_neto']:.0f} "
            f"(margen {r['margen']:.1f}%) | Egresos: Bs. {r['total_egresos']:.0f}"
        )
    partes.append(
        f"=== RESUMEN EJECUTIVO ({r['fecha_consulta']}) ===\n"
        f"Pacientes: {r['pac_activos']} activos | {r['pac_inactivos']} inactivos | "
        f"Total: {r['pac_total']} | Nuevos este mes: {r['pac_nuevos_mes']}\n"
        f"Profesionales activos: {r['prof_activos']}\n"
        f"Sesiones hoy: {r['ses_programadas']} programadas | "
        f"{r['ses_realizadas']} realizadas | "
        f"{r['ses_permisos']} permisos | "
        f"{r['ses_faltas']} faltas | "
        f"{r['ses_canceladas']} canceladas\n"
        f"Ingresos hoy: Bs. {r['ingresos_hoy']} | "
        f"Ingresos del mes: Bs. {r['ingresos_mes']}"
        f"{neto_str}\n"
        f"[Período detectado en la consulta: {periodo}]"
    )

    # ── 2. Sesiones ───────────────────────────────────────────────────────────
    if any(p in msg for p in _KW_SESIONES):
        data = get_sesiones_por_periodo(fecha_desde, fecha_hasta)
        partes.append(_fmt_sesiones(data, periodo))

        if fecha_hasta >= hoy and not es_hoy:
            futuras = get_sesiones_futuras(dias=7)
            if futuras:
                lineas = [
                    f"  {s['fecha']} {s['hora']} — {s['paciente']} con {s['profesional']} "
                    f"({s['servicio']}) [{s['sucursal']}] Bs.{s['monto']:.0f}"
                    for s in futuras
                ]
                partes.append("=== PRÓXIMAS SESIONES (7 días) ===\n" + '\n'.join(lineas))

    # ── 3. Pagos / ingresos ───────────────────────────────────────────────────
    if any(p in msg for p in _KW_PAGOS):
        data = get_pagos_por_periodo(fecha_desde, fecha_hasta)
        partes.append(_fmt_pagos(data, periodo))

    # ── 4. P&L mensual ────────────────────────────────────────────────────────
    if any(p in msg for p in _KW_PL):
        # Si el período es exactamente un mes completo → P&L de ese mes
        if (fecha_desde.day == 1
                and fecha_hasta.day == calendar.monthrange(fecha_hasta.year, fecha_hasta.month)[1]
                and fecha_desde.month == fecha_hasta.month
                and fecha_desde.year == fecha_hasta.year):
            rf = get_resumen_financiero_mensual(anio=fecha_desde.year, mes=fecha_desde.month)
            partes.append(_fmt_pl(rf))
        else:
            # Período multi-mes → comparativa
            comp = get_comparativa_meses(meses=6)
            if comp:
                lineas = ["=== COMPARATIVA ÚLTIMOS 6 MESES ==="]
                for c in comp:
                    egr_s  = f"Egresos: Bs.{c['egresos']:,.0f} | " if c['egresos'] else ""
                    marg_s = f"Margen: {c['margen']:.1f}%" if c['margen'] else ""
                    neto_s = f"Neto: Bs.{c['resultado_neto']:,.0f}" if c['resultado_neto'] else "(sin P&L cerrado)"
                    lineas.append(
                        f"  {c['periodo']}: Ingresos Bs.{c['ingresos']:,.0f} | {egr_s}{neto_s} {marg_s}"
                    )
                partes.append('\n'.join(lineas))

    # ── 5. Egresos ────────────────────────────────────────────────────────────
    if any(p in msg for p in _KW_EGRESOS):
        data = get_egresos_por_periodo(fecha_desde, fecha_hasta)
        if data:
            lineas = [
                f"=== EGRESOS: {periodo} ===",
                f"Total: Bs. {data['total']:,.0f} en {data['num_egresos']} registros",
            ]
            if data.get('por_categoria'):
                lineas.append("Por categoría:")
                for c in data['por_categoria']:
                    lineas.append(
                        f"  {c['categoria__nombre'] or '—'}: "
                        f"Bs. {float(c['total'] or 0):,.0f} ({c['count']} registros)"
                    )
            if data.get('por_sucursal'):
                lineas.append("Por sucursal:")
                for s in data['por_sucursal']:
                    lineas.append(
                        f"  {s['sucursal__nombre'] or 'General'}: Bs. {float(s['total'] or 0):,.0f}"
                    )
            if data.get('detalle'):
                lineas.append("Detalle:")
                for e in data['detalle']:
                    lineas.append(
                        f"  [{e['fecha']}] {e['concepto']} — "
                        f"Bs. {e['monto']:,.0f} ({e['categoria']}) [{e['sucursal']}]"
                    )
            partes.append('\n'.join(lineas))

    # ── 6. Devoluciones ───────────────────────────────────────────────────────
    if any(p in msg for p in _KW_DEVOL):
        data = get_devoluciones_por_periodo(fecha_desde, fecha_hasta)
        if data:
            lineas = [
                f"=== DEVOLUCIONES: {periodo} ===",
                f"Total devuelto: Bs. {data['total']:,.0f} en {data['num_devoluciones']} registros",
            ]
            for d in data.get('detalle', []):
                lineas.append(
                    f"  [{d['fecha']}] {d['numero']} | {d['paciente']} | "
                    f"Bs.{d['monto']:,.0f} | {d['motivo'][:50]} | Registró: {d['registrado_por']}"
                )
            partes.append('\n'.join(lineas))

    # ── 7. Deudas ─────────────────────────────────────────────────────────────
    if any(p in msg for p in _KW_DEUDAS):
        deudas = get_deudas_pendientes()
        if deudas:
            total  = sum(d['deuda'] for d in deudas)
            lineas = [
                f"=== PACIENTES CON DEUDA ===",
                f"Total acumulado: Bs. {total:,.0f}",
            ] + [
                f"  {d['paciente']}: Bs. {d['deuda']:,.0f} "
                f"(real: Bs. {d['deuda_real']:,.0f})"
                for d in deudas
            ]
            partes.append('\n'.join(lineas))
        else:
            partes.append("=== DEUDAS === No hay pacientes con saldo negativo.")

    # ── 8. Mensualidades ──────────────────────────────────────────────────────
    if any(p in msg for p in _KW_MENS):
        data = get_mensualidades_por_periodo(fecha_desde, fecha_hasta)
        if data:
            lineas = [
                f"=== MENSUALIDADES: {periodo} ===",
                f"Total: {data['count']} | Costo total: Bs. {data['total']:,.0f}",
            ] + [
                f"  {m['paciente']} — {m['periodo']} — "
                f"Bs.{m['costo']:,.0f} (pendiente: Bs.{m['pendiente']:,.0f}) "
                f"[{m['estado']}] {m['sucursal']}"
                for m in data.get('detalle', [])
            ]
            partes.append('\n'.join(lineas))

    # ── 9. Proyectos / evaluaciones ───────────────────────────────────────────
    if any(p in msg for p in _KW_PROY):
        data = get_proyectos_por_periodo(fecha_desde, fecha_hasta)
        if data:
            lineas = [
                f"=== PROYECTOS: {periodo} ===",
                f"Total: {data['count']} | Costo total: Bs. {data['total']:,.0f}",
            ] + [
                f"  [{p['codigo']}] {p['paciente']} — {p['servicio']} [{p['sucursal']}] "
                f"Bs.{p['costo']:,.0f} (pendiente: Bs.{p['pendiente']:,.0f}) "
                f"[{p['estado']}] Informe: {p['informe']}"
                for p in data.get('detalle', [])
            ]
            partes.append('\n'.join(lineas))

    # ── 10. Rentabilidad servicios externos ───────────────────────────────────
    if any(p in msg for p in _KW_RENT):
        rent = get_rentabilidad_externos_periodo(fecha_desde, fecha_hasta)
        if rent:
            lineas = [f"=== RENTABILIDAD SERVICIOS EXTERNOS: {periodo} ==="] + [
                f"  {r['profesional']}: {r['sesiones']} ses | "
                f"Cobrado: Bs.{r['cobrado']:,.0f} | "
                f"Centro: Bs.{r['centro']:,.0f} | "
                f"Prof: Bs.{r['profesional_monto']:,.0f}"
                for r in rent
            ]
            partes.append('\n'.join(lineas))
        else:
            partes.append(f"Sin sesiones de servicios externos en {periodo}.")

    # ── 11. Comparativa entre períodos ────────────────────────────────────────
    if any(p in msg for p in _KW_COMP):
        comp = get_comparativa_meses(meses=6)
        if comp:
            lineas = ["=== COMPARATIVA ÚLTIMOS 6 MESES ==="]
            for c in comp:
                egr_s  = f"Egresos: Bs.{c['egresos']:,.0f} | " if c['egresos'] else ""
                marg_s = f"Margen: {c['margen']:.1f}%" if c['margen'] else ""
                neto_s = f"Neto: Bs.{c['resultado_neto']:,.0f}" if c['resultado_neto'] else "(sin P&L)"
                lineas.append(
                    f"  {c['periodo']}: Ingresos Bs.{c['ingresos']:,.0f} | {egr_s}{neto_s} {marg_s}"
                )
            partes.append('\n'.join(lineas))

    # ── 12. Profesionales ─────────────────────────────────────────────────────
    if any(p in msg for p in _KW_PROF):
        profs = get_profesionales()
        if profs:
            lineas = ["=== PROFESIONALES ACTIVOS ==="] + [
                f"  {p['nombre']} — {p['especialidad']} ({p['sucursales']})"
                for p in profs
            ]
            partes.append('\n'.join(lineas))

        if any(p in msg for p in ('recepcionista', 'cobró', 'registró', 'registro')):
            staff = get_lista_staff()
            if staff:
                lineas = ["=== STAFF ACTIVO ==="] + [
                    f"  {s['nombre']} | {s['rol']} | {s['sucursales']}"
                    for s in staff
                ]
                partes.append('\n'.join(lineas))

    # ── 13. Búsqueda de paciente específico ───────────────────────────────────
    if any(p in msg for p in _KW_PAC):
        # Extraer nombre candidato (palabras de más de 3 letras que no sean fechas)
        _stopwords = set(MESES_ES.keys()) | {
            'sesion', 'sesiones', 'pago', 'pagos', 'datos', 'informacion',
            'información', 'historial', 'cuenta', 'saldo', 'debe', 'cuánto',
            'cuanto', 'buscar', 'busca', 'paciente', 'expediente',
        }
        palabras = [
            p for p in mensaje.split()
            if len(p) > 3 and p.isalpha() and p.lower() not in _stopwords
        ]
        if palabras:
            nombre_b = ' '.join(palabras[:3])

            resultados = buscar_paciente(nombre=nombre_b)
            if resultados:
                lineas = [f"=== PACIENTE: '{nombre_b}' ==="] + [
                    f"  {p['nombre']} ({p['estado']}) — Tutor: {p['tutor']} "
                    f"Tel: {p['telefono']} — {p['diagnostico']} — Desde: {p['desde']}"
                    for p in resultados
                ]
                partes.append('\n'.join(lineas))

            cc = get_cuenta_corriente_paciente(nombre_b)
            if cc and not cc.get('sin_cuenta'):
                s = cc['saldo_actual']
                estado_saldo = (
                    f"EN DEUDA: Bs.{abs(s):,.0f}" if s < 0 else
                    f"A FAVOR: Bs.{s:,.0f}"       if s > 0 else
                    "AL DÍA (saldo cero)"
                )
                partes.append(
                    f"=== CUENTA CORRIENTE: {cc['paciente']} ===\n"
                    f"Estado: {estado_saldo}\n"
                    f"Total consumido:     Bs. {cc['total_consumido']:,.0f}\n"
                    f"Total pagado:        Bs. {cc['total_pagado']:,.0f}\n"
                    f"Crédito disponible:  Bs. {cc['credito_disponible']:,.0f}\n"
                    f"Devoluciones:        Bs. {cc['total_devoluciones']:,.0f}\n"
                    f"  — Sesiones:        Bs. {cc['sesiones_pagadas']:,.0f}\n"
                    f"  — Mensualidades:   Bs. {cc['mensualidades_pagadas']:,.0f}\n"
                    f"  — Proyectos:       Bs. {cc['proyectos_pagados']:,.0f}\n"
                    f"Ingreso neto centro: Bs. {cc['ingreso_neto_centro']:,.0f}\n"
                    f"Actualizado: {cc['actualizado']}"
                )

            pagos_pac = get_historial_pagos_paciente(nombre_b, limite=15)
            if pagos_pac:
                lineas = [f"=== HISTORIAL PAGOS: {nombre_b} ==="] + [
                    f"  [{p['fecha']}] {p['recibo']} — Bs.{p['monto']:,.0f} "
                    f"| {p['metodo']} | {p['tipo']} | Registró: {p['registrado_por']}"
                    for p in pagos_pac
                ]
                partes.append('\n'.join(lineas))

            ses_pac = get_sesiones_paciente(nombre_b, fecha_desde, fecha_hasta)
            if ses_pac:
                lineas = [f"=== SESIONES: {nombre_b} ({periodo}) ==="] + [
                    f"  [{s['fecha']}] {s['profesional']} — {s['servicio']} "
                    f"[{s['estado']}] Bs.{s['monto']:.0f} [{s['sucursal']}]"
                    + (' 📝' if s.get('nota') else '')
                    for s in ses_pac
                ]
                partes.append('\n'.join(lineas))

    return '\n\n'.join(partes) if partes else f"Fecha actual: {hoy:%d/%m/%Y}."