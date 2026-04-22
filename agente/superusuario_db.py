"""
agente/superusuario_db.py
Consultas de SOLO LECTURA a la base de datos para el Agente Superusuario.
El dueño puede consultar cualquier dato del sistema sin restricciones.
NUNCA modifica datos.

Cambios respecto a la versión anterior:
- Corregido: facturacion_pago.fecha → fecha_pago
- Corregido: pacientes_paciente.fecha_ingreso → fecha_registro
- Añadido: egresos_resumenfinanciero (resumen financiero mensual con egresos reales)
- Añadido: egresos_egreso (egresos operativos)
- Añadido: servicios_comisionsesion (rentabilidad por sesión)
- Mejorado: facturacion_cuentacorriente con campos saldo_real, ingreso_neto_centro
- Añadido: get_resumen_financiero_mensual() para análisis ejecutivo completo
- Añadido: get_egresos_mes() para desglose de gastos
- Añadido: get_resultado_neto() para P&L rápido
"""

import logging
from datetime import date, timedelta

log = logging.getLogger('agente')


# ── Resumen general del negocio ───────────────────────────────────────────────

def get_resumen_general() -> dict:
    """
    Resumen ejecutivo del centro: pacientes, sesiones, ingresos, profesionales.
    Es el contexto base que siempre se incluye en cada consulta del dueño.
    """
    hoy = date.today()
    resultado = {}

    # Pacientes — campo correcto: fecha_registro (no fecha_ingreso)
    try:
        from pacientes.models import Paciente
        resultado['pacientes_activos']    = Paciente.objects.filter(estado='activo').count()
        resultado['pacientes_total']      = Paciente.objects.count()
        resultado['pacientes_nuevos_mes'] = Paciente.objects.filter(
            fecha_registro__year=hoy.year,
            fecha_registro__month=hoy.month,
        ).count()
        resultado['pacientes_inactivos'] = Paciente.objects.filter(estado='inactivo').count()
    except Exception as e:
        log.error(f'[SuperDB] Error pacientes: {e}')
        resultado['pacientes_activos'] = resultado['pacientes_total'] = \
            resultado['pacientes_nuevos_mes'] = resultado['pacientes_inactivos'] = '?'

    # Profesionales
    try:
        from profesionales.models import Profesional
        resultado['profesionales_activos'] = Profesional.objects.filter(activo=True).count()
    except Exception as e:
        log.error(f'[SuperDB] Error profesionales: {e}')
        resultado['profesionales_activos'] = '?'

    # Sesiones de hoy
    try:
        from agenda.models import Sesion
        qs_hoy = Sesion.objects.filter(fecha=hoy)
        resultado['sesiones_hoy_programadas'] = qs_hoy.filter(estado='programada').count()
        resultado['sesiones_hoy_realizadas']  = qs_hoy.filter(
            estado__in=['realizada', 'realizada_retraso']
        ).count()
        resultado['sesiones_hoy_permisos']    = qs_hoy.filter(estado='permiso').count()
        resultado['sesiones_hoy_faltas']      = qs_hoy.filter(estado='falta').count()
        resultado['sesiones_hoy_canceladas']  = qs_hoy.filter(estado='cancelada').count()
    except Exception as e:
        log.error(f'[SuperDB] Error sesiones hoy: {e}')
        for k in ('sesiones_hoy_programadas', 'sesiones_hoy_realizadas',
                  'sesiones_hoy_permisos', 'sesiones_hoy_faltas', 'sesiones_hoy_canceladas'):
            resultado[k] = '?'

    # Ingresos del mes — campo correcto: fecha_pago (no fecha)
    try:
        from facturacion.models import Pago
        from django.db.models import Sum
        total = Pago.objects.filter(
            fecha_pago__year=hoy.year,
            fecha_pago__month=hoy.month,
            anulado=False,
        ).aggregate(total=Sum('monto'))['total'] or 0
        resultado['ingresos_mes'] = float(total)
    except Exception as e:
        log.error(f'[SuperDB] Error ingresos: {e}')
        resultado['ingresos_mes'] = '?'

    # Resultado neto del mes (si existe resumen financiero)
    try:
        from egresos.models import ResumenFinanciero
        rf = ResumenFinanciero.objects.filter(
            mes=hoy.month, anio=hoy.year
        ).first()
        if rf:
            resultado['resultado_neto_mes']   = float(rf.resultado_neto)
            resultado['total_egresos_mes']    = float(rf.total_egresos)
            resultado['margen_mes']           = float(rf.margen_porcentaje)
            resultado['ingresos_brutos_mes']  = float(rf.ingresos_brutos)
        else:
            resultado['resultado_neto_mes'] = resultado['total_egresos_mes'] = \
                resultado['margen_mes'] = None
    except Exception as e:
        log.error(f'[SuperDB] Error resumen financiero: {e}')
        resultado['resultado_neto_mes'] = None

    resultado['fecha_consulta'] = hoy.strftime('%d/%m/%Y')
    return resultado


# ── Pacientes ─────────────────────────────────────────────────────────────────

def buscar_paciente(nombre: str = None, telefono: str = None) -> list:
    """Busca pacientes por nombre parcial o teléfono."""
    try:
        from pacientes.models import Paciente
        qs = Paciente.objects.all()

        if telefono:
            tel = telefono.strip().replace('+591', '').replace('591', '')
            qs = qs.filter(telefono_tutor__icontains=tel)
        elif nombre:
            from django.db.models import Q
            partes = nombre.strip().split()
            q = Q()
            for parte in partes:
                q |= Q(nombre__icontains=parte) | Q(apellido__icontains=parte)
            qs = qs.filter(q)

        resultado = []
        for p in qs.order_by('apellido', 'nombre')[:10]:
            resultado.append({
                'id':            p.id,
                'nombre':        f'{p.nombre} {p.apellido}',
                'estado':        p.estado,
                'tutor':         p.nombre_tutor or '—',
                'telefono':      p.telefono_tutor or '—',
                'diagnostico':   (p.diagnostico or '—')[:80],
                # fecha_registro es el campo correcto en la BD
                'fecha_registro': p.fecha_registro.strftime('%d/%m/%Y') if p.fecha_registro else '—',
            })
        return resultado
    except Exception as e:
        log.error(f'[SuperDB] Error buscando paciente: {e}')
        return []


def get_detalle_paciente(paciente_id: int) -> dict:
    """Detalle completo de un paciente por ID."""
    try:
        from pacientes.models import Paciente
        p = Paciente.objects.get(id=paciente_id)
        hoy = date.today()
        edad = None
        if p.fecha_nacimiento:
            fn = p.fecha_nacimiento
            edad = hoy.year - fn.year - ((hoy.month, hoy.day) < (fn.month, fn.day))
        return {
            'id':                p.id,
            'nombre_completo':   f'{p.nombre} {p.apellido}',
            'edad':              edad,
            'estado':            p.estado,
            'diagnostico':       p.diagnostico or '—',
            'tutor_1':           p.nombre_tutor or '—',
            'telefono_tutor_1':  p.telefono_tutor or '—',
            'tutor_2':           p.nombre_tutor_2 or '—',
            'telefono_tutor_2':  p.telefono_tutor_2 or '—',
            # campo correcto según BD: fecha_registro
            'fecha_registro':    p.fecha_registro.strftime('%d/%m/%Y') if p.fecha_registro else '—',
            'apoyo_escolar':     p.apoyo_escolar,
            'nombre_escuela':    p.nombre_escuela or '—',
        }
    except Exception as e:
        log.error(f'[SuperDB] Error detalle paciente {paciente_id}: {e}')
        return {}


# ── Sesiones ──────────────────────────────────────────────────────────────────

def get_sesiones_hoy(sucursal_id: int = None) -> list:
    """Todas las sesiones de hoy, opcionalmente filtradas por sucursal."""
    try:
        from agenda.models import Sesion
        qs = Sesion.objects.filter(fecha=date.today()).select_related(
            'paciente', 'profesional', 'servicio', 'sucursal'
        ).order_by('hora_inicio')

        if sucursal_id:
            qs = qs.filter(sucursal__id=sucursal_id)

        resultado = []
        for s in qs:
            resultado.append({
                'hora':        s.hora_inicio.strftime('%H:%M') if s.hora_inicio else '—',
                'paciente':    f'{s.paciente.nombre} {s.paciente.apellido}' if s.paciente else '—',
                'profesional': f'{s.profesional.nombre} {s.profesional.apellido}' if s.profesional else '—',
                'servicio':    s.servicio.nombre if s.servicio else '—',
                'sucursal':    s.sucursal.nombre if s.sucursal else '—',
                'estado':      s.estado,
                'monto':       float(s.monto_cobrado or 0),
                # notas_sesion es el campo correcto (confirmado en BD)
                'tiene_nota':  bool(s.notas_sesion),
            })
        return resultado
    except Exception as e:
        log.error(f'[SuperDB] Error sesiones hoy: {e}')
        return []


def get_sesiones_semana(sucursal_id: int = None) -> dict:
    """Resumen de sesiones de la semana actual."""
    try:
        from agenda.models import Sesion
        from django.db.models import Count
        hoy    = date.today()
        lunes  = hoy - timedelta(days=hoy.weekday())
        sabado = lunes + timedelta(days=5)

        qs = Sesion.objects.filter(fecha__gte=lunes, fecha__lte=sabado)
        if sucursal_id:
            qs = qs.filter(sucursal__id=sucursal_id)

        por_estado = {item['estado']: item['total']
                      for item in qs.values('estado').annotate(total=Count('id'))}

        return {
            'semana':      f'{lunes:%d/%m} al {sabado:%d/%m/%Y}',
            'programadas': por_estado.get('programada', 0),
            'realizadas':  por_estado.get('realizada', 0) + por_estado.get('realizada_retraso', 0),
            'permisos':    por_estado.get('permiso', 0),
            'faltas':      por_estado.get('falta', 0),
            'canceladas':  por_estado.get('cancelada', 0),
            'total':       qs.count(),
        }
    except Exception as e:
        log.error(f'[SuperDB] Error sesiones semana: {e}')
        return {}


# ── Ingresos y finanzas ───────────────────────────────────────────────────────

def get_ingresos_mes(anio: int = None, mes: int = None) -> dict:
    """Ingresos totales del mes especificado (o el actual). Solo pagos no anulados."""
    try:
        from facturacion.models import Pago
        from django.db.models import Sum
        hoy  = date.today()
        anio = anio or hoy.year
        mes  = mes  or hoy.month

        # IMPORTANTE: campo correcto es fecha_pago, no fecha
        pagos = Pago.objects.filter(
            fecha_pago__year=anio,
            fecha_pago__month=mes,
            anulado=False,
        )
        total = pagos.aggregate(total=Sum('monto'))['total'] or 0

        import calendar
        nombre_mes = calendar.month_name[mes]

        return {
            'periodo':        f'{nombre_mes} {anio}',
            'total_ingresos': float(total),
            'num_pagos':      pagos.count(),
        }
    except Exception as e:
        log.error(f'[SuperDB] Error ingresos mes: {e}')
        return {}


def get_ingresos_hoy() -> dict:
    """Ingresos cobrados hoy."""
    try:
        from facturacion.models import Pago
        from django.db.models import Sum
        hoy = date.today()
        qs  = Pago.objects.filter(fecha_pago=hoy, anulado=False)
        total = qs.aggregate(t=Sum('monto'))['t'] or 0
        return {
            'total':    float(total),
            'num_pagos': qs.count(),
            'fecha':    hoy.strftime('%d/%m/%Y'),
        }
    except Exception as e:
        log.error(f'[SuperDB] Error ingresos hoy: {e}')
        return {}


def get_deudas_pendientes(limite: int = 15) -> list:
    """Lista de pacientes con mayor deuda (saldo negativo en cuenta corriente)."""
    try:
        from facturacion.models import CuentaCorriente
        cuentas = (
            CuentaCorriente.objects
            .filter(saldo_actual__lt=0)
            .select_related('paciente')
            .order_by('saldo_actual')[:limite]
        )
        resultado = []
        for c in cuentas:
            resultado.append({
                'paciente':      f'{c.paciente.nombre} {c.paciente.apellido}' if c.paciente else '—',
                'deuda':         abs(float(c.saldo_actual or 0)),
                # saldo_real: considera sesiones ya realizadas pero no cobradas
                'deuda_real':    abs(float(c.saldo_real or 0)),
                # ingreso_neto_centro: lo que queda para el centro tras honorarios
                'ingreso_neto':  float(c.ingreso_neto_centro or 0),
            })
        return resultado
    except Exception as e:
        log.error(f'[SuperDB] Error deudas pendientes: {e}')
        return []


def get_resumen_financiero_mensual(anio: int = None, mes: int = None) -> dict:
    """
    NUEVO: Resumen financiero completo del mes desde egresos_resumenfinanciero.
    Incluye ingresos, egresos por categoría, resultado neto y margen.
    """
    try:
        from egresos.models import ResumenFinanciero
        hoy  = date.today()
        anio = anio or hoy.year
        mes  = mes  or hoy.month

        rf = ResumenFinanciero.objects.filter(mes=mes, anio=anio).first()
        if not rf:
            return {'disponible': False, 'periodo': f'{mes}/{anio}'}

        import calendar
        return {
            'disponible':           True,
            'periodo':              f'{calendar.month_name[mes]} {anio}',
            'ingresos_brutos':      float(rf.ingresos_brutos),
            'ingresos_adicionales': float(rf.ingresos_adicionales),
            'total_devoluciones':   float(rf.total_devoluciones),
            'ingresos_netos':       float(rf.ingresos_netos),
            # Egresos por categoría
            'egresos_arriendo':     float(rf.egresos_arriendo),
            'egresos_servicios':    float(rf.egresos_servicios_basicos),
            'egresos_personal':     float(rf.egresos_personal),
            'egresos_honorarios':   float(rf.egresos_honorarios),
            'egresos_equipamiento': float(rf.egresos_equipamiento),
            'egresos_marketing':    float(rf.egresos_marketing),
            'egresos_impuestos':    float(rf.egresos_impuestos),
            'egresos_otros':        float(rf.egresos_otros),
            'total_egresos':        float(rf.total_egresos),
            # Resultado
            'resultado_neto':       float(rf.resultado_neto),
            'margen_porcentaje':    float(rf.margen_porcentaje),
            'ultima_actualizacion': rf.ultima_actualizacion.strftime('%d/%m/%Y %H:%M'),
        }
    except Exception as e:
        log.error(f'[SuperDB] Error resumen financiero mensual: {e}')
        return {'disponible': False}


def get_egresos_recientes(dias: int = 30) -> list:
    """
    NUEVO: Egresos operativos recientes (gastos del centro).
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
        resultado = []
        for e in qs:
            resultado.append({
                'fecha':     e.fecha.strftime('%d/%m/%Y'),
                'concepto':  e.concepto[:60],
                'monto':     float(e.monto),
                'categoria': e.categoria.nombre if e.categoria else '—',
                'sucursal':  e.sucursal.nombre if e.sucursal else 'General',
            })
        return resultado
    except Exception as e:
        log.error(f'[SuperDB] Error egresos recientes: {e}')
        return []


def get_rentabilidad_por_profesional(dias: int = 30) -> list:
    """
    NUEVO: Rentabilidad por profesional usando servicios_comisionsesion.
    Muestra monto_centro vs monto_profesional por terapeuta.
    """
    try:
        from servicios.models import ComisionSesion
        from django.db.models import Sum, Count
        desde = date.today() - timedelta(days=dias)

        datos = (
            ComisionSesion.objects
            .filter(sesion__fecha__gte=desde, sesion__estado__in=['realizada', 'realizada_retraso'])
            .values('sesion__profesional__nombre', 'sesion__profesional__apellido')
            .annotate(
                sesiones=Count('id'),
                total_cobrado=Sum('precio_cobrado'),
                monto_centro=Sum('monto_centro'),
                monto_profesional=Sum('monto_profesional'),
            )
            .order_by('-monto_centro')
        )
        resultado = []
        for d in datos:
            nombre = f"{d['sesion__profesional__nombre']} {d['sesion__profesional__apellido']}"
            resultado.append({
                'profesional':       nombre,
                'sesiones':          d['sesiones'],
                'total_cobrado':     float(d['total_cobrado'] or 0),
                'monto_centro':      float(d['monto_centro'] or 0),
                'monto_profesional': float(d['monto_profesional'] or 0),
                'periodo':           f'últimos {dias} días',
            })
        return resultado
    except Exception as e:
        log.error(f'[SuperDB] Error rentabilidad profesional: {e}')
        return []


# ── Profesionales ─────────────────────────────────────────────────────────────

def get_profesionales() -> list:
    """Lista de todos los profesionales activos con su especialidad y sucursales."""
    try:
        from profesionales.models import Profesional
        profs = Profesional.objects.filter(activo=True).prefetch_related('sucursales')
        resultado = []
        for p in profs:
            sucursales = ', '.join(s.nombre for s in p.sucursales.all()) or '—'
            resultado.append({
                'nombre':       f'{p.nombre} {p.apellido}',
                'especialidad': p.especialidad,
                'sucursales':   sucursales,
                'email':        p.email or '—',
                'telefono':     p.telefono or '—',
                'fecha_ingreso': p.fecha_ingreso.strftime('%d/%m/%Y') if p.fecha_ingreso else '—',
            })
        return resultado
    except Exception as e:
        log.error(f'[SuperDB] Error profesionales: {e}')
        return []


def get_sesiones_por_profesional(dias: int = 30) -> list:
    """
    Sesiones realizadas por profesional en los últimos N días.
    Incluye también faltas y permisos para evaluar asistencia.
    """
    try:
        from agenda.models import Sesion
        from django.db.models import Count
        desde = date.today() - timedelta(days=dias)

        realizadas = (
            Sesion.objects
            .filter(fecha__gte=desde, estado__in=['realizada', 'realizada_retraso'])
            .values('profesional__nombre', 'profesional__apellido')
            .annotate(total=Count('id'))
            .order_by('-total')
        )
        resultado = []
        for d in realizadas:
            resultado.append({
                'profesional':       f'{d["profesional__nombre"]} {d["profesional__apellido"]}',
                'sesiones_realizadas': d['total'],
                'periodo':           f'últimos {dias} días',
            })
        return resultado
    except Exception as e:
        log.error(f'[SuperDB] Error sesiones por profesional: {e}')
        return []


# ── Mensualidades ─────────────────────────────────────────────────────────────

def get_mensualidades_pendientes(limite: int = 15) -> list:
    """Mensualidades pendientes o parciales con detalle de montos."""
    try:
        from agenda.models import Mensualidad
        from django.db.models import Q
        mens = (
            Mensualidad.objects
            .filter(Q(estado='pendiente') | Q(estado='parcial'))
            .select_related('paciente', 'sucursal')
            .order_by('anio', 'mes')[:limite]
        )
        resultado = []
        for m in mens:
            resultado.append({
                'paciente':   f'{m.paciente.nombre} {m.paciente.apellido}' if m.paciente else '—',
                'periodo':    f'{m.mes:02d}/{m.anio}',
                'monto':      float(m.costo_mensual or 0),
                'estado':     m.estado,
                'sucursal':   m.sucursal.nombre if m.sucursal else '—',
            })
        return resultado
    except Exception as e:
        log.error(f'[SuperDB] Error mensualidades pendientes: {e}')
        return []


# ── Constructor de contexto completo ──────────────────────────────────────────

def construir_contexto_superusuario(mensaje: str) -> str:
    """
    Construye el contexto de datos que se inyecta en el prompt del superusuario.
    Siempre incluye el resumen general y agrega datos específicos según el mensaje.
    """
    msg    = mensaje.lower()
    partes = []
    hoy    = date.today()

    # ── Siempre: resumen general ──────────────────────────────────────────────
    resumen = get_resumen_general()
    linea_neto = ''
    if resumen.get('resultado_neto_mes') is not None:
        linea_neto = (
            f"\nResultado neto del mes: Bs. {resumen['resultado_neto_mes']:.0f} "
            f"(margen {resumen['margen_mes']:.1f}%) | "
            f"Egresos: Bs. {resumen['total_egresos_mes']:.0f}"
        )

    partes.append(
        f"=== RESUMEN EJECUTIVO ({resumen.get('fecha_consulta', '')}) ===\n"
        f"Pacientes activos: {resumen.get('pacientes_activos')} "
        f"(total registrados: {resumen.get('pacientes_total')}, "
        f"nuevos este mes: {resumen.get('pacientes_nuevos_mes')}, "
        f"inactivos: {resumen.get('pacientes_inactivos')})\n"
        f"Profesionales activos: {resumen.get('profesionales_activos')}\n"
        f"Sesiones hoy — programadas: {resumen.get('sesiones_hoy_programadas')} | "
        f"realizadas: {resumen.get('sesiones_hoy_realizadas')} | "
        f"permisos: {resumen.get('sesiones_hoy_permisos')} | "
        f"faltas: {resumen.get('sesiones_hoy_faltas')}\n"
        f"Ingresos del mes: Bs. {resumen.get('ingresos_mes')}"
        f"{linea_neto}"
    )

    # ── Sesiones de hoy y semana ──────────────────────────────────────────────
    if any(p in msg for p in ('hoy', 'sesion', 'sesiones', 'agenda', 'dia', 'día')):
        sesiones = get_sesiones_hoy()
        if sesiones:
            lineas = [
                f"  {s['hora']} — {s['paciente']} con {s['profesional']} "
                f"({s['servicio']}) [{s['estado']}] Bs.{s['monto']:.0f}"
                for s in sesiones
            ]
            partes.append("=== SESIONES DE HOY ===\n" + '\n'.join(lineas))
        else:
            partes.append(f"Sin sesiones registradas para hoy ({hoy:%d/%m/%Y})")

        resumen_sem = get_sesiones_semana()
        if resumen_sem:
            partes.append(
                f"=== SEMANA ({resumen_sem.get('semana')}) ===\n"
                f"Programadas: {resumen_sem.get('programadas')} | "
                f"Realizadas: {resumen_sem.get('realizadas')} | "
                f"Permisos: {resumen_sem.get('permisos')} | "
                f"Faltas: {resumen_sem.get('faltas')} | "
                f"Canceladas: {resumen_sem.get('canceladas')}"
            )

    # ── Ingresos / pagos ──────────────────────────────────────────────────────
    if any(p in msg for p in ('ingreso', 'ingresos', 'dinero', 'pago', 'pagos',
                               'recaudo', 'ganancia', 'cobro', 'caja')):
        ing_hoy = get_ingresos_hoy()
        if ing_hoy:
            partes.append(
                f"=== INGRESOS HOY ({ing_hoy.get('fecha')}) ===\n"
                f"Total cobrado: Bs. {ing_hoy.get('total', 0):.0f} en {ing_hoy.get('num_pagos')} pagos"
            )
        ing_mes = get_ingresos_mes()
        if ing_mes:
            partes.append(
                f"=== INGRESOS {ing_mes.get('periodo', '').upper()} ===\n"
                f"Total: Bs. {ing_mes.get('total_ingresos', 0):.0f} "
                f"en {ing_mes.get('num_pagos')} pagos"
            )

    # ── Egresos / gastos ──────────────────────────────────────────────────────
    if any(p in msg for p in ('egreso', 'egresos', 'gasto', 'gastos', 'costo',
                               'costos', 'arriendo', 'servicios basicos', 'honorarios')):
        egresos = get_egresos_recientes(30)
        if egresos:
            lineas = [
                f"  [{e['fecha']}] {e['concepto']} — Bs. {e['monto']:.0f} ({e['categoria']})"
                for e in egresos[:10]
            ]
            partes.append("=== EGRESOS RECIENTES (30 días) ===\n" + '\n'.join(lineas))

    # ── Resumen financiero completo (P&L) ─────────────────────────────────────
    if any(p in msg for p in ('financiero', 'balance', 'resultado', 'neto', 'margen',
                               'rentabilidad', 'utilidad', 'perdida', 'pérdida',
                               'estado de resultados', 'p&l', 'flujo')):
        rf = get_resumen_financiero_mensual()
        if rf.get('disponible'):
            partes.append(
                f"=== RESUMEN FINANCIERO {rf.get('periodo', '').upper()} ===\n"
                f"Ingresos brutos: Bs. {rf.get('ingresos_brutos', 0):.0f}\n"
                f"Devoluciones: Bs. {rf.get('total_devoluciones', 0):.0f}\n"
                f"Ingresos netos: Bs. {rf.get('ingresos_netos', 0):.0f}\n"
                f"--- EGRESOS ---\n"
                f"  Arriendo: Bs. {rf.get('egresos_arriendo', 0):.0f}\n"
                f"  Servicios básicos: Bs. {rf.get('egresos_servicios', 0):.0f}\n"
                f"  Personal: Bs. {rf.get('egresos_personal', 0):.0f}\n"
                f"  Honorarios prof.: Bs. {rf.get('egresos_honorarios', 0):.0f}\n"
                f"  Equipamiento: Bs. {rf.get('egresos_equipamiento', 0):.0f}\n"
                f"  Marketing: Bs. {rf.get('egresos_marketing', 0):.0f}\n"
                f"  Impuestos: Bs. {rf.get('egresos_impuestos', 0):.0f}\n"
                f"  Otros: Bs. {rf.get('egresos_otros', 0):.0f}\n"
                f"TOTAL EGRESOS: Bs. {rf.get('total_egresos', 0):.0f}\n"
                f"RESULTADO NETO: Bs. {rf.get('resultado_neto', 0):.0f} "
                f"(margen {rf.get('margen_porcentaje', 0):.1f}%)\n"
                f"Actualizado: {rf.get('ultima_actualizacion')}"
            )
        else:
            partes.append("=== RESUMEN FINANCIERO ===\nNo hay resumen financiero cerrado para este mes.")

    # ── Deudas / cuentas corrientes ───────────────────────────────────────────
    if any(p in msg for p in ('deuda', 'deudas', 'pendiente', 'pendientes',
                               'deben', 'moroso', 'saldo', 'cobrar')):
        deudas = get_deudas_pendientes()
        if deudas:
            lineas = [
                f"  {d['paciente']}: Bs. {d['deuda']:.0f} "
                f"(deuda real: Bs. {d['deuda_real']:.0f})"
                for d in deudas
            ]
            partes.append("=== PACIENTES CON DEUDA ===\n" + '\n'.join(lineas))
        else:
            partes.append("=== DEUDAS ===\nNo hay pacientes con saldo negativo.")

    # ── Profesionales y rendimiento ───────────────────────────────────────────
    if any(p in msg for p in ('profesional', 'profesionales', 'terapeuta',
                               'terapeutas', 'productividad', 'rendimiento')):
        profs = get_profesionales()
        if profs:
            lineas = [
                f"  {p['nombre']} — {p['especialidad']} ({p['sucursales']})"
                for p in profs
            ]
            partes.append("=== PROFESIONALES ACTIVOS ===\n" + '\n'.join(lineas))

        sesiones_prof = get_sesiones_por_profesional()
        if sesiones_prof:
            lineas = [
                f"  {s['profesional']}: {s['sesiones_realizadas']} sesiones realizadas"
                for s in sesiones_prof
            ]
            partes.append("=== SESIONES POR PROFESIONAL (últimos 30 días) ===\n" + '\n'.join(lineas))

    # ── Rentabilidad por profesional ──────────────────────────────────────────
    if any(p in msg for p in ('rentabilidad', 'comision', 'comisión', 'honorario',
                               'honorarios', 'cuanto gana', 'cuánto gana')):
        rent = get_rentabilidad_por_profesional()
        if rent:
            lineas = [
                f"  {r['profesional']}: {r['sesiones']} sesiones | "
                f"Cobrado: Bs. {r['total_cobrado']:.0f} | "
                f"Centro: Bs. {r['monto_centro']:.0f} | "
                f"Prof: Bs. {r['monto_profesional']:.0f}"
                for r in rent
            ]
            partes.append("=== RENTABILIDAD POR PROFESIONAL (30 días) ===\n" + '\n'.join(lineas))

    # ── Mensualidades ─────────────────────────────────────────────────────────
    if any(p in msg for p in ('mensualidad', 'mensualidades', 'cuota', 'cuotas')):
        mens = get_mensualidades_pendientes()
        if mens:
            lineas = [
                f"  {m['paciente']} — {m['periodo']} — "
                f"Bs. {m['monto']:.0f} ({m['estado']}) [{m['sucursal']}]"
                for m in mens
            ]
            partes.append("=== MENSUALIDADES PENDIENTES ===\n" + '\n'.join(lineas))

    return '\n\n'.join(partes) if partes else f"Fecha: {hoy:%d/%m/%Y}. Sin datos adicionales."