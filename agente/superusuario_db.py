"""
agente/superusuario_db.py
Consultas de SOLO LECTURA a la base de datos para el Agente Superusuario.
El dueño puede consultar cualquier dato del sistema sin restricciones.
NUNCA modifica datos.
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

    # Pacientes
    try:
        from pacientes.models import Paciente
        resultado['pacientes_activos']    = Paciente.objects.filter(estado='activo').count()
        resultado['pacientes_total']      = Paciente.objects.count()
        resultado['pacientes_nuevos_mes'] = Paciente.objects.filter(
            fecha_ingreso__year=hoy.year,
            fecha_ingreso__month=hoy.month,
        ).count()
    except Exception as e:
        log.error(f'[SuperDB] Error pacientes: {e}')
        resultado['pacientes_activos'] = resultado['pacientes_total'] = resultado['pacientes_nuevos_mes'] = '?'

    # Profesionales
    try:
        from pacientes.models import Profesional
        resultado['profesionales_activos'] = Profesional.objects.filter(activo=True).count()
    except Exception as e:
        log.error(f'[SuperDB] Error profesionales: {e}')
        resultado['profesionales_activos'] = '?'

    # Sesiones de hoy
    try:
        from agenda.models import Sesion
        resultado['sesiones_hoy_programadas'] = Sesion.objects.filter(
            fecha=hoy, estado='programada'
        ).count()
        resultado['sesiones_hoy_realizadas'] = Sesion.objects.filter(
            fecha=hoy, estado__in=['realizada', 'realizada_retraso']
        ).count()
    except Exception as e:
        log.error(f'[SuperDB] Error sesiones hoy: {e}')
        resultado['sesiones_hoy_programadas'] = resultado['sesiones_hoy_realizadas'] = '?'

    # Ingresos del mes
    try:
        from facturacion.models import Pago
        from django.db.models import Sum
        total = Pago.objects.filter(
            fecha__year=hoy.year,
            fecha__month=hoy.month,
        ).aggregate(total=Sum('monto'))['total'] or 0
        resultado['ingresos_mes'] = float(total)
    except Exception as e:
        log.error(f'[SuperDB] Error ingresos: {e}')
        resultado['ingresos_mes'] = '?'

    resultado['fecha_consulta'] = hoy.strftime('%d/%m/%Y')
    return resultado


# ── Pacientes ─────────────────────────────────────────────────────────────────

def buscar_paciente(nombre: str = None, telefono: str = None) -> list:
    """
    Busca pacientes por nombre parcial o teléfono.
    Retorna lista de dicts con info básica.
    """
    try:
        from pacientes.models import Paciente
        qs = Paciente.objects.all()

        if telefono:
            tel = telefono.strip().replace('+591', '').replace('591', '')
            qs = qs.filter(telefono_tutor__icontains=tel)
        elif nombre:
            partes = nombre.strip().split()
            for parte in partes:
                qs = qs.filter(nombre__icontains=parte) | qs.filter(apellido__icontains=parte)

        resultado = []
        for p in qs[:10]:
            resultado.append({
                'id':            p.id,
                'nombre':        f'{p.nombre} {p.apellido}',
                'estado':        p.estado,
                'tutor':         p.nombre_tutor or '—',
                'telefono':      p.telefono_tutor or '—',
                'fecha_ingreso': p.fecha_ingreso.strftime('%d/%m/%Y') if p.fecha_ingreso else '—',
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
            'id':              p.id,
            'nombre_completo': f'{p.nombre} {p.apellido}',
            'edad':            edad,
            'estado':          p.estado,
            'tutor_1':         p.nombre_tutor or '—',
            'telefono_tutor_1': p.telefono_tutor or '—',
            'tutor_2':         getattr(p, 'nombre_tutor_2', None) or '—',
            'telefono_tutor_2': getattr(p, 'telefono_tutor_2', None) or '—',
            'fecha_ingreso':   p.fecha_ingreso.strftime('%d/%m/%Y') if p.fecha_ingreso else '—',
            'diagnostico':     getattr(p, 'diagnostico', '—') or '—',
        }
    except Exception as e:
        log.error(f'[SuperDB] Error detalle paciente {paciente_id}: {e}')
        return {}


# ── Sesiones ──────────────────────────────────────────────────────────────────

def get_sesiones_hoy(sucursal_id: int = None) -> list:
    """Todas las sesiones programadas para hoy, opcionalmente por sucursal."""
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

        qs = Sesion.objects.filter(
            fecha__gte=lunes, fecha__lte=sabado
        )
        if sucursal_id:
            qs = qs.filter(sucursal__id=sucursal_id)

        por_estado = qs.values('estado').annotate(total=Count('id'))
        resumen = {item['estado']: item['total'] for item in por_estado}

        return {
            'semana':      f'{lunes:%d/%m} al {sabado:%d/%m/%Y}',
            'programadas': resumen.get('programada', 0),
            'realizadas':  resumen.get('realizada', 0) + resumen.get('realizada_retraso', 0),
            'permisos':    resumen.get('permiso', 0),
            'faltas':      resumen.get('falta', 0),
            'canceladas':  resumen.get('cancelada', 0),
            'total':       qs.count(),
        }
    except Exception as e:
        log.error(f'[SuperDB] Error sesiones semana: {e}')
        return {}


# ── Ingresos y finanzas ───────────────────────────────────────────────────────

def get_ingresos_mes(anio: int = None, mes: int = None) -> dict:
    """Ingresos totales del mes especificado (o el actual)."""
    try:
        from facturacion.models import Pago
        from django.db.models import Sum, Count
        hoy  = date.today()
        anio = anio or hoy.year
        mes  = mes  or hoy.month

        pagos = Pago.objects.filter(fecha__year=anio, fecha__month=mes)
        total = pagos.aggregate(total=Sum('monto'))['total'] or 0

        import calendar
        nombre_mes = calendar.month_name[mes]

        return {
            'periodo':         f'{nombre_mes} {anio}',
            'total_ingresos':  float(total),
            'num_pagos':       pagos.count(),
        }
    except Exception as e:
        log.error(f'[SuperDB] Error ingresos mes: {e}')
        return {}


def get_deudas_pendientes(limite: int = 10) -> list:
    """Lista de pacientes con mayor deuda pendiente."""
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
                'paciente': f'{c.paciente.nombre} {c.paciente.apellido}' if c.paciente else '—',
                'deuda':    abs(float(c.saldo_actual or 0)),
            })
        return resultado
    except Exception as e:
        log.error(f'[SuperDB] Error deudas pendientes: {e}')
        return []


# ── Profesionales ─────────────────────────────────────────────────────────────

def get_profesionales() -> list:
    """Lista de todos los profesionales activos con su especialidad."""
    try:
        from pacientes.models import Profesional
        profs = Profesional.objects.filter(activo=True).prefetch_related('sucursales')
        resultado = []
        for p in profs:
            sucursales = ', '.join(s.nombre for s in p.sucursales.all()) or '—'
            resultado.append({
                'nombre':      f'{p.nombre} {p.apellido}',
                'especialidad': p.especialidad,
                'sucursales':  sucursales,
                'email':       p.email or '—',
                'telefono':    p.telefono or '—',
            })
        return resultado
    except Exception as e:
        log.error(f'[SuperDB] Error profesionales: {e}')
        return []


def get_sesiones_por_profesional(dias: int = 30) -> list:
    """
    Resumen de sesiones realizadas por cada profesional en los últimos N días.
    Útil para evaluar productividad.
    """
    try:
        from agenda.models import Sesion
        from django.db.models import Count
        desde = date.today() - timedelta(days=dias)

        datos = (
            Sesion.objects
            .filter(
                fecha__gte=desde,
                estado__in=['realizada', 'realizada_retraso'],
            )
            .values('profesional__nombre', 'profesional__apellido')
            .annotate(total=Count('id'))
            .order_by('-total')
        )
        return [
            {
                'profesional': f'{d["profesional__nombre"]} {d["profesional__apellido"]}',
                'sesiones_realizadas': d['total'],
                'periodo': f'últimos {dias} días',
            }
            for d in datos
        ]
    except Exception as e:
        log.error(f'[SuperDB] Error sesiones por profesional: {e}')
        return []


# ── Mensualidades y proyectos ─────────────────────────────────────────────────

def get_mensualidades_pendientes(limite: int = 10) -> list:
    """Mensualidades no pagadas o con deuda."""
    try:
        from facturacion.models import Mensualidad
        from django.db.models import Q
        mens = (
            Mensualidad.objects
            .filter(Q(estado='pendiente') | Q(estado='parcial'))
            .select_related('paciente')
            .order_by('fecha_vencimiento')[:limite]
        )
        resultado = []
        for m in mens:
            resultado.append({
                'paciente':   f'{m.paciente.nombre} {m.paciente.apellido}' if m.paciente else '—',
                'periodo':    str(getattr(m, 'periodo', '—')),
                'monto':      float(getattr(m, 'monto_total', 0) or 0),
                'pagado':     float(getattr(m, 'monto_pagado', 0) or 0),
                'estado':     m.estado,
                'vencimiento': m.fecha_vencimiento.strftime('%d/%m/%Y') if getattr(m, 'fecha_vencimiento', None) else '—',
            })
        return resultado
    except Exception as e:
        log.error(f'[SuperDB] Error mensualidades pendientes: {e}')
        return []


# ── Constructor de contexto completo ──────────────────────────────────────────

def construir_contexto_superusuario(mensaje: str) -> str:
    """
    Construye el contexto de datos que se inyecta en el prompt del superusuario.
    Incluye siempre el resumen general y agrega datos específicos según el mensaje.
    """
    msg = mensaje.lower()
    partes = []

    # Siempre: resumen general
    resumen = get_resumen_general()
    partes.append(
        f"=== RESUMEN GENERAL ({resumen.get('fecha_consulta', '')}) ===\n"
        f"Pacientes activos: {resumen.get('pacientes_activos')} "
        f"(total: {resumen.get('pacientes_total')}, "
        f"nuevos este mes: {resumen.get('pacientes_nuevos_mes')})\n"
        f"Profesionales activos: {resumen.get('profesionales_activos')}\n"
        f"Sesiones hoy — programadas: {resumen.get('sesiones_hoy_programadas')} | "
        f"realizadas: {resumen.get('sesiones_hoy_realizadas')}\n"
        f"Ingresos del mes: Bs. {resumen.get('ingresos_mes')}"
    )

    # Sesiones de hoy si pregunta por agenda o sesiones
    if any(p in msg for p in ('hoy', 'sesion', 'sesiones', 'agenda', 'dia')):
        sesiones = get_sesiones_hoy()
        if sesiones:
            lineas = [f"  {s['hora']} — {s['paciente']} con {s['profesional']} ({s['servicio']}) [{s['estado']}]"
                      for s in sesiones]
            partes.append("=== SESIONES DE HOY ===\n" + '\n'.join(lineas))
        resumen_sem = get_sesiones_semana()
        if resumen_sem:
            partes.append(
                f"=== SEMANA ({resumen_sem.get('semana')}) ===\n"
                f"Programadas: {resumen_sem.get('programadas')} | "
                f"Realizadas: {resumen_sem.get('realizadas')} | "
                f"Permisos: {resumen_sem.get('permisos')} | "
                f"Faltas: {resumen_sem.get('faltas')}"
            )

    # Ingresos si pregunta por dinero, ingresos, pagos
    if any(p in msg for p in ('ingreso', 'ingresos', 'dinero', 'pago', 'pagos', 'recaudo', 'ganancia')):
        ing = get_ingresos_mes()
        if ing:
            partes.append(
                f"=== INGRESOS {ing.get('periodo', '').upper()} ===\n"
                f"Total: Bs. {ing.get('total_ingresos')} en {ing.get('num_pagos')} pagos"
            )

    # Deudas si pregunta por deuda o pendientes
    if any(p in msg for p in ('deuda', 'deudas', 'pendiente', 'pendientes', 'deben', 'moroso')):
        deudas = get_deudas_pendientes()
        if deudas:
            lineas = [f"  {d['paciente']}: Bs. {d['deuda']:.2f}" for d in deudas]
            partes.append("=== PACIENTES CON DEUDA ===\n" + '\n'.join(lineas))

    # Profesionales si pregunta por ellos o productividad
    if any(p in msg for p in ('profesional', 'profesionales', 'terapeuta', 'terapeutas', 'productividad', 'rendimiento')):
        profs = get_profesionales()
        if profs:
            lineas = [f"  {p['nombre']} — {p['especialidad']} ({p['sucursales']})" for p in profs]
            partes.append("=== PROFESIONALES ACTIVOS ===\n" + '\n'.join(lineas))
        sesiones_prof = get_sesiones_por_profesional()
        if sesiones_prof:
            lineas = [f"  {s['profesional']}: {s['sesiones_realizadas']} sesiones realizadas" for s in sesiones_prof]
            partes.append("=== SESIONES POR PROFESIONAL (últimos 30 días) ===\n" + '\n'.join(lineas))

    # Mensualidades si pregunta por mensualidades
    if any(p in msg for p in ('mensualidad', 'mensualidades', 'cuota', 'cuotas')):
        mens = get_mensualidades_pendientes()
        if mens:
            lineas = [f"  {m['paciente']} — {m['periodo']} — Bs. {m['monto']} ({m['estado']})"
                      for m in mens]
            partes.append("=== MENSUALIDADES PENDIENTES ===\n" + '\n'.join(lineas))

    return '\n\n'.join(partes) if partes else 'Sin datos disponibles en este momento.'
