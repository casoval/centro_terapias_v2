"""
agente/superusuario_db.py
Consultas de SOLO LECTURA para el Agente Superusuario.
Acceso total sin restricciones a todos los datos del sistema.

Imports 100% verificados contra los models reales:
  - pacientes.models     → Paciente  (fecha_registro = DateTimeField auto_now_add)
  - profesionales.models → Profesional
  - agenda.models        → Sesion, Mensualidad, Proyecto
  - facturacion.models   → Pago (campo: fecha_pago), CuentaCorriente, Devolucion
  - servicios.models     → ComisionSesion, TipoServicio
  - egresos.models       → ResumenFinanciero (campo: egresos_servicios_basicos,
                           egresos_mantenimiento, egresos_seguros, egresos_capacitacion)
                           Egreso (campo: fecha — no fecha_pago)
"""

import logging
from datetime import date, timedelta

log = logging.getLogger('agente')


# ── Resumen ejecutivo ─────────────────────────────────────────────────────────

def get_resumen_general() -> dict:
    hoy = date.today()
    r   = {'fecha_consulta': hoy.strftime('%d/%m/%Y')}

    # Pacientes — fecha_registro es DateTimeField auto_now_add (confirmado en models_pacientes.py)
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
        r.update({'pac_activos': '?', 'pac_total': '?',
                  'pac_inactivos': '?', 'pac_nuevos_mes': '?'})

    # Profesionales (app: profesionales)
    try:
        from profesionales.models import Profesional
        r['prof_activos'] = Profesional.objects.filter(activo=True).count()
    except Exception as e:
        log.error(f'[SuperDB] profesionales: {e}')
        r['prof_activos'] = '?'

    # Sesiones de hoy (app: agenda)
    try:
        from agenda.models import Sesion
        from django.db.models import Count
        qs     = Sesion.objects.filter(fecha=hoy)
        estados = {x['estado']: x['c'] for x in qs.values('estado').annotate(c=Count('id'))}
        r['ses_programadas'] = estados.get('programada', 0)
        r['ses_realizadas']  = estados.get('realizada', 0) + estados.get('realizada_retraso', 0)
        r['ses_permisos']    = estados.get('permiso', 0)
        r['ses_faltas']      = estados.get('falta', 0)
        r['ses_canceladas']  = estados.get('cancelada', 0)
    except Exception as e:
        log.error(f'[SuperDB] sesiones hoy: {e}')
        for k in ('ses_programadas', 'ses_realizadas', 'ses_permisos',
                  'ses_faltas', 'ses_canceladas'):
            r[k] = '?'

    # Ingresos — Pago.fecha_pago (confirmado en models_facturacion.py, NO 'fecha')
    try:
        from facturacion.models import Pago
        from django.db.models import Sum
        r['ingresos_hoy'] = float(
            Pago.objects.filter(fecha_pago=hoy, anulado=False)
            .aggregate(t=Sum('monto'))['t'] or 0
        )
        r['ingresos_mes'] = float(
            Pago.objects.filter(
                fecha_pago__year=hoy.year,
                fecha_pago__month=hoy.month,
                anulado=False,
            ).aggregate(t=Sum('monto'))['t'] or 0
        )
    except Exception as e:
        log.error(f'[SuperDB] ingresos: {e}')
        r['ingresos_hoy'] = r['ingresos_mes'] = '?'

    # Resumen financiero del mes
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


# ── Sesiones ──────────────────────────────────────────────────────────────────

def get_sesiones_hoy(sucursal_id: int = None) -> list:
    try:
        from agenda.models import Sesion
        qs = Sesion.objects.filter(fecha=date.today()).select_related(
            'paciente', 'profesional', 'servicio', 'sucursal'
        ).order_by('hora_inicio')
        if sucursal_id:
            qs = qs.filter(sucursal__id=sucursal_id)
        return [{
            'hora':        s.hora_inicio.strftime('%H:%M') if s.hora_inicio else '—',
            'paciente':    f'{s.paciente.nombre} {s.paciente.apellido}' if s.paciente else '—',
            'profesional': f'{s.profesional.nombre} {s.profesional.apellido}' if s.profesional else '—',
            'servicio':    s.servicio.nombre if s.servicio else '—',
            'sucursal':    s.sucursal.nombre if s.sucursal else '—',
            'estado':      s.estado,
            'monto':       float(s.monto_cobrado or 0),
            # notas_sesion es el campo real en Sesion (confirmado en models_agenda.py)
            'tiene_nota':  bool(s.notas_sesion),
        } for s in qs]
    except Exception as e:
        log.error(f'[SuperDB] sesiones hoy: {e}')
        return []


def get_sesiones_semana(sucursal_id: int = None) -> dict:
    try:
        from agenda.models import Sesion
        from django.db.models import Count
        hoy    = date.today()
        lunes  = hoy - timedelta(days=hoy.weekday())
        sabado = lunes + timedelta(days=5)
        qs = Sesion.objects.filter(fecha__gte=lunes, fecha__lte=sabado)
        if sucursal_id:
            qs = qs.filter(sucursal__id=sucursal_id)
        estados = {x['estado']: x['c'] for x in qs.values('estado').annotate(c=Count('id'))}
        return {
            'semana':      f'{lunes:%d/%m} al {sabado:%d/%m/%Y}',
            'programadas': estados.get('programada', 0),
            'realizadas':  estados.get('realizada', 0) + estados.get('realizada_retraso', 0),
            'permisos':    estados.get('permiso', 0),
            'faltas':      estados.get('falta', 0),
            'canceladas':  estados.get('cancelada', 0),
        }
    except Exception as e:
        log.error(f'[SuperDB] sesiones semana: {e}')
        return {}


# ── Pacientes ─────────────────────────────────────────────────────────────────

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
            'id':         p.id,
            'nombre':     f'{p.nombre} {p.apellido}',
            'estado':     p.estado,
            'tutor':      p.nombre_tutor or '—',
            'telefono':   p.telefono_tutor or '—',
            'diagnostico':(p.diagnostico or '—')[:80],
            'desde':      p.fecha_registro.strftime('%d/%m/%Y') if p.fecha_registro else '—',
        } for p in qs.order_by('apellido', 'nombre')[:10]]
    except Exception as e:
        log.error(f'[SuperDB] buscar paciente: {e}')
        return []


# ── Ingresos ──────────────────────────────────────────────────────────────────

def get_ingresos_mes(anio: int = None, mes: int = None) -> dict:
    try:
        from facturacion.models import Pago
        from django.db.models import Sum
        import calendar
        hoy  = date.today()
        anio = anio or hoy.year
        mes  = mes  or hoy.month
        qs   = Pago.objects.filter(
            fecha_pago__year=anio, fecha_pago__month=mes, anulado=False
        )
        total = qs.aggregate(t=Sum('monto'))['t'] or 0
        return {
            'periodo':   f'{calendar.month_name[mes]} {anio}',
            'total':     float(total),
            'num_pagos': qs.count(),
        }
    except Exception as e:
        log.error(f'[SuperDB] ingresos mes: {e}')
        return {}


# ── Deudas ────────────────────────────────────────────────────────────────────

def get_deudas_pendientes(limite: int = 15) -> list:
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


# ── P&L mensual ───────────────────────────────────────────────────────────────

def get_resumen_financiero_mensual(anio: int = None, mes: int = None) -> dict:
    """
    ResumenFinanciero se recalcula automáticamente vía signal.
    Campos confirmados en models_egresos.py: egresos_servicios_basicos,
    egresos_mantenimiento, egresos_seguros, egresos_capacitacion (existen).
    """
    try:
        from egresos.models import ResumenFinanciero
        import calendar
        hoy  = date.today()
        anio = anio or hoy.year
        mes  = mes  or hoy.month
        rf   = ResumenFinanciero.objects.filter(mes=mes, anio=anio).first()
        if not rf:
            return {'disponible': False, 'periodo': f'{calendar.month_name[mes]} {anio}'}
        return {
            'disponible':            True,
            'periodo':               f'{calendar.month_name[mes]} {anio}',
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
        log.error(f'[SuperDB] resumen financiero: {e}')
        return {'disponible': False}


def get_egresos_recientes(dias: int = 30) -> list:
    """
    Egreso.fecha es DateField (confirmado en models_egresos.py línea:
    fecha = models.DateField(verbose_name="Fecha de pago"))
    NO usar fecha_pago aquí — eso es de facturacion.Pago.
    """
    try:
        from egresos.models import Egreso
        desde = date.today() - timedelta(days=dias)
        qs = (
            Egreso.objects
            .filter(fecha__gte=desde, anulado=False)
            .select_related('categoria', 'sucursal')
            .order_by('-fecha')[:20]
        )
        return [{
            'fecha':     e.fecha.strftime('%d/%m/%Y'),
            'concepto':  e.concepto[:60],
            'monto':     float(e.monto),
            'categoria': e.categoria.nombre if e.categoria else '—',
            'sucursal':  e.sucursal.nombre if e.sucursal else 'General',
        } for e in qs]
    except Exception as e:
        log.error(f'[SuperDB] egresos: {e}')
        return []


# ── Profesionales ─────────────────────────────────────────────────────────────

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
            'desde':        p.fecha_ingreso.strftime('%d/%m/%Y') if p.fecha_ingreso else '—',
        } for p in profs]
    except Exception as e:
        log.error(f'[SuperDB] profesionales: {e}')
        return []


def get_sesiones_por_profesional(dias: int = 30) -> list:
    try:
        from agenda.models import Sesion
        from django.db.models import Count
        desde = date.today() - timedelta(days=dias)
        datos = (
            Sesion.objects
            .filter(fecha__gte=desde, estado__in=['realizada', 'realizada_retraso'])
            .values('profesional__nombre', 'profesional__apellido')
            .annotate(total=Count('id'))
            .order_by('-total')
        )
        return [{
            'profesional': f'{d["profesional__nombre"]} {d["profesional__apellido"]}',
            'sesiones':    d['total'],
        } for d in datos]
    except Exception as e:
        log.error(f'[SuperDB] sesiones por profesional: {e}')
        return []


def get_rentabilidad_por_profesional(dias: int = 30) -> list:
    """ComisionSesion — solo existe para sesiones de servicios externos."""
    try:
        from servicios.models import ComisionSesion
        from django.db.models import Sum, Count
        desde = date.today() - timedelta(days=dias)
        datos = (
            ComisionSesion.objects
            .filter(
                sesion__fecha__gte=desde,
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
            'profesional': f'{d["sesion__profesional__nombre"]} {d["sesion__profesional__apellido"]}',
            'sesiones':    d['sesiones'],
            'cobrado':     float(d['cobrado'] or 0),
            'centro':      float(d['centro'] or 0),
            'profesional_monto': float(d['profesional_monto'] or 0),
        } for d in datos]
    except Exception as e:
        log.error(f'[SuperDB] rentabilidad: {e}')
        return []


# ── Mensualidades ─────────────────────────────────────────────────────────────

def get_mensualidades_pendientes(limite: int = 15) -> list:
    """
    Mensualidad.estado: activa | pausada | completada | cancelada
    Mensualidad.costo_mensual (no monto_total — confirmado en models_agenda.py)
    """
    try:
        from agenda.models import Mensualidad
        from django.db.models import Q
        qs = (
            Mensualidad.objects
            .filter(Q(estado='activa') | Q(estado='pausada'))
            .select_related('paciente', 'sucursal')
            .order_by('-anio', '-mes')[:limite]
        )
        resultado = []
        for m in qs:
            try:
                pendiente = float(m.saldo_pendiente)
            except Exception:
                pendiente = float(m.costo_mensual)
            resultado.append({
                'paciente':  f'{m.paciente.nombre} {m.paciente.apellido}' if m.paciente else '—',
                'periodo':   f'{m.mes:02d}/{m.anio}',
                'costo':     float(m.costo_mensual),
                'pendiente': pendiente,
                'estado':    m.estado,
                'sucursal':  m.sucursal.nombre if m.sucursal else '—',
            })
        return resultado
    except Exception as e:
        log.error(f'[SuperDB] mensualidades: {e}')
        return []


# ── Proyectos ─────────────────────────────────────────────────────────────────

def get_proyectos_activos(limite: int = 10) -> list:
    """
    Proyecto.estado: planificado | en_progreso | finalizado | cancelado
    Proyecto.costo_total (no costo — confirmado en models_agenda.py)
    """
    try:
        from agenda.models import Proyecto
        qs = (
            Proyecto.objects
            .filter(estado__in=['en_progreso', 'planificado'])
            .select_related('paciente', 'profesional_responsable',
                            'sucursal', 'servicio_base')
            .order_by('-fecha_inicio')[:limite]
        )
        resultado = []
        for p in qs:
            try:
                pendiente = float(p.saldo_pendiente)
            except Exception:
                pendiente = float(p.costo_total)
            resultado.append({
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
                'informe':     'Entregado' if p.informe_entregado else 'Pendiente',
            })
        return resultado
    except Exception as e:
        log.error(f'[SuperDB] proyectos: {e}')
        return []


# ── Constructor de contexto ───────────────────────────────────────────────────

def construir_contexto_superusuario(mensaje: str) -> str:
    """
    Contexto de datos inyectado en el prompt del superusuario.
    Siempre incluye el resumen ejecutivo. Las demás secciones
    se activan por palabras clave en el mensaje.
    """
    msg    = mensaje.lower()
    partes = []
    hoy    = date.today()

    # ── 1. Resumen ejecutivo — SIEMPRE ────────────────────────────────────────
    r = get_resumen_general()
    neto_str = ''
    if r.get('resultado_neto') is not None:
        signo    = '+' if r['resultado_neto'] >= 0 else ''
        neto_str = (
            f"\nResultado neto del mes: Bs. {signo}{r['resultado_neto']:.0f} "
            f"(margen {r['margen']:.1f}%) | Egresos totales: Bs. {r['total_egresos']:.0f}"
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
        f"{neto_str}"
    )

    # ── 2. Agenda de hoy / semana ────────────────────────────────────────────
    if any(p in msg for p in ('hoy', 'sesion', 'sesiones', 'agenda', 'dia', 'día',
                               'horario', 'quién', 'quien', 'cita', 'citas',
                               'programad', 'realiz')):
        sesiones = get_sesiones_hoy()
        if sesiones:
            lineas = [
                f"  {s['hora']} — {s['paciente']} con {s['profesional']} "
                f"({s['servicio']}) [{s['estado']}] Bs.{s['monto']:.0f}"
                + (' 📝' if s['tiene_nota'] else '')
                for s in sesiones
            ]
            partes.append("=== SESIONES DE HOY ===\n" + '\n'.join(lineas))
        else:
            partes.append(f"Sin sesiones registradas hoy ({hoy:%d/%m/%Y})")

        sem = get_sesiones_semana()
        if sem:
            partes.append(
                f"=== SEMANA ({sem['semana']}) ===\n"
                f"Programadas: {sem['programadas']} | Realizadas: {sem['realizadas']} | "
                f"Permisos: {sem['permisos']} | Faltas: {sem['faltas']} | "
                f"Canceladas: {sem['canceladas']}"
            )

    # ── 3. Ingresos ───────────────────────────────────────────────────────────
    if any(p in msg for p in ('ingreso', 'ingresos', 'dinero', 'pago', 'pagos',
                               'cobro', 'cobros', 'caja', 'recaudo', 'ganancia',
                               'cuanto se cobr', 'cuánto se cobr')):
        ing = get_ingresos_mes()
        if ing:
            partes.append(
                f"=== INGRESOS {ing.get('periodo','').upper()} ===\n"
                f"Total cobrado: Bs. {ing['total']:,.0f} en {ing['num_pagos']} pagos"
            )

    # ── 4. P&L completo ───────────────────────────────────────────────────────
    if any(p in msg for p in ('financiero', 'balance', 'resultado', 'neto', 'margen',
                               'rentabilidad', 'utilidad', 'perdida', 'pérdida',
                               'ganancias', 'p&l', 'estado de resultado', 'flujo',
                               'gastos', 'cuanto gast', 'cuánto gast')):
        rf = get_resumen_financiero_mensual()
        if rf.get('disponible'):
            partes.append(
                f"=== P&L {rf['periodo'].upper()} ===\n"
                f"Ingresos brutos:    Bs. {rf['ingresos_brutos']:>10,.0f}\n"
                f"Ingresos adicional: Bs. {rf['ingresos_adicionales']:>10,.0f}\n"
                f"Devoluciones:      -Bs. {rf['total_devoluciones']:>10,.0f}\n"
                f"Ingresos netos:     Bs. {rf['ingresos_netos']:>10,.0f}\n"
                f"─── EGRESOS ────────────────────────\n"
                f"  Arriendo:         Bs. {rf['egresos_arriendo']:>10,.0f}\n"
                f"  Serv. básicos:    Bs. {rf['egresos_servicios']:>10,.0f}\n"
                f"  Personal:         Bs. {rf['egresos_personal']:>10,.0f}\n"
                f"  Honorarios prof:  Bs. {rf['egresos_honorarios']:>10,.0f}\n"
                f"  Equipamiento:     Bs. {rf['egresos_equipamiento']:>10,.0f}\n"
                f"  Mantenimiento:    Bs. {rf['egresos_mantenimiento']:>10,.0f}\n"
                f"  Marketing:        Bs. {rf['egresos_marketing']:>10,.0f}\n"
                f"  Impuestos:        Bs. {rf['egresos_impuestos']:>10,.0f}\n"
                f"  Seguros:          Bs. {rf['egresos_seguros']:>10,.0f}\n"
                f"  Capacitación:     Bs. {rf['egresos_capacitacion']:>10,.0f}\n"
                f"  Otros:            Bs. {rf['egresos_otros']:>10,.0f}\n"
                f"TOTAL EGRESOS:      Bs. {rf['total_egresos']:>10,.0f}\n"
                f"RESULTADO NETO:     Bs. {rf['resultado_neto']:>10,.0f} "
                f"(margen {rf['margen_porcentaje']:.1f}%)\n"
                f"Actualizado: {rf['actualizado']}"
            )
        else:
            partes.append(
                f"No hay resumen financiero cerrado para {rf.get('periodo', 'este mes')}. "
                "Los datos aún pueden estar en procesamiento."
            )

    # ── 5. Egresos / gastos ───────────────────────────────────────────────────
    if any(p in msg for p in ('egreso', 'egresos', 'gasto', 'gastos', 'arriendo',
                               'servicio basico', 'honorario', 'honorarios',
                               'proveedor', 'compra', 'compras')):
        egresos = get_egresos_recientes(30)
        if egresos:
            lineas = [
                f"  [{e['fecha']}] {e['concepto']} — Bs. {e['monto']:,.0f} "
                f"({e['categoria']}) [{e['sucursal']}]"
                for e in egresos[:12]
            ]
            partes.append("=== EGRESOS RECIENTES (30 días) ===\n" + '\n'.join(lineas))

    # ── 6. Deudas ─────────────────────────────────────────────────────────────
    if any(p in msg for p in ('deuda', 'deudas', 'pendiente', 'pendientes',
                               'deben', 'moroso', 'saldo negativo', 'cobrar',
                               'mora', 'no han pagado')):
        deudas = get_deudas_pendientes()
        if deudas:
            total  = sum(d['deuda'] for d in deudas)
            lineas = [
                f"  {d['paciente']}: Bs. {d['deuda']:,.0f} "
                f"(real: Bs. {d['deuda_real']:,.0f})"
                for d in deudas
            ]
            partes.append(
                f"=== PACIENTES CON DEUDA (top {len(deudas)}) ===\n"
                f"Total acumulado: Bs. {total:,.0f}\n"
                + '\n'.join(lineas)
            )
        else:
            partes.append("=== DEUDAS === No hay pacientes con saldo negativo.")

    # ── 7. Profesionales ──────────────────────────────────────────────────────
    if any(p in msg for p in ('profesional', 'profesionales', 'terapeuta', 'terapeutas',
                               'staff', 'equipo', 'personal')):
        profs = get_profesionales()
        if profs:
            lineas = [
                f"  {p['nombre']} — {p['especialidad']} ({p['sucursales']})"
                for p in profs
            ]
            partes.append("=== PROFESIONALES ACTIVOS ===\n" + '\n'.join(lineas))

    # ── 8. Productividad / rendimiento ────────────────────────────────────────
    if any(p in msg for p in ('productividad', 'rendimiento', 'cuántas sesiones',
                               'cuantas sesiones', 'desempeño', 'desempeno',
                               'quién atendió', 'quien atendio')):
        ses_prof = get_sesiones_por_profesional()
        if ses_prof:
            lineas = [
                f"  {s['profesional']}: {s['sesiones']} sesiones (30 días)"
                for s in ses_prof
            ]
            partes.append("=== SESIONES REALIZADAS POR PROFESIONAL (30 días) ===\n"
                          + '\n'.join(lineas))

    # ── 9. Rentabilidad externos ──────────────────────────────────────────────
    if any(p in msg for p in ('rentabilidad', 'comision', 'comisión', 'externo',
                               'externos', 'cuanto gana el profesional',
                               'cuánto queda para el centro')):
        rent = get_rentabilidad_por_profesional()
        if rent:
            lineas = [
                f"  {r['profesional']}: {r['sesiones']} ses | "
                f"Cobrado: Bs.{r['cobrado']:,.0f} | "
                f"Centro: Bs.{r['centro']:,.0f} | "
                f"Prof: Bs.{r['profesional_monto']:,.0f}"
                for r in rent
            ]
            partes.append("=== RENTABILIDAD SERVICIOS EXTERNOS (30 días) ===\n"
                          + '\n'.join(lineas))
        else:
            partes.append("No hay sesiones de servicios externos registradas en los últimos 30 días.")

    # ── 10. Mensualidades ─────────────────────────────────────────────────────
    if any(p in msg for p in ('mensualidad', 'mensualidades', 'cuota', 'cuotas',
                               'mensual', 'plan mensual')):
        mens = get_mensualidades_pendientes()
        if mens:
            lineas = [
                f"  {m['paciente']} — {m['periodo']} — "
                f"Costo: Bs.{m['costo']:,.0f} | Pendiente: Bs.{m['pendiente']:,.0f} "
                f"[{m['estado']}] {m['sucursal']}"
                for m in mens
            ]
            partes.append("=== MENSUALIDADES ACTIVAS/PAUSADAS ===\n" + '\n'.join(lineas))

    # ── 11. Proyectos / evaluaciones ──────────────────────────────────────────
    if any(p in msg for p in ('proyecto', 'proyectos', 'evaluacion', 'evaluación',
                               'evaluaciones', 'informe', 'informes', 'eval')):
        proyectos = get_proyectos_activos()
        if proyectos:
            lineas = [
                f"  [{p['codigo']}] {p['paciente']} — {p['servicio']} — "
                f"Bs.{p['costo']:,.0f} (pendiente: Bs.{p['pendiente']:,.0f}) "
                f"[{p['estado']}] Informe: {p['informe']}"
                for p in proyectos
            ]
            partes.append("=== PROYECTOS EN CURSO ===\n" + '\n'.join(lineas))

    # ── 12. Búsqueda de paciente específico ───────────────────────────────────
    if any(p in msg for p in ('buscar', 'busca', 'paciente llamado', 'información de',
                               'datos de', 'expediente de', 'historial de')):
        palabras = [p for p in mensaje.split() if len(p) > 4 and p.isalpha()]
        if palabras:
            nombre_b = ' '.join(palabras[:2])
            resultados = buscar_paciente(nombre=nombre_b)
            if resultados:
                lineas = [
                    f"  {p['nombre']} ({p['estado']}) — Tutor: {p['tutor']} "
                    f"Tel: {p['telefono']} — {p['diagnostico']}"
                    for p in resultados
                ]
                partes.append(
                    f"=== PACIENTES: '{nombre_b}' ===\n" + '\n'.join(lineas)
                )

    return '\n\n'.join(partes) if partes else f"Fecha: {hoy:%d/%m/%Y}."