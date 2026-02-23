"""
Agente IA para el sistema de chat.
Motor: Groq (gratis) con llama-3.3-70b-versatile

Modelos reales del proyecto:
  pacientes.Paciente          → nombre, apellido, nombre_tutor, telefono_tutor,
                                 fecha_nacimiento, genero, estado, diagnostico,
                                 sucursales (M2M), user (O2O nullable)
  profesionales.Profesional   → nombre, apellido, especialidad, telefono, email,
                                 activo, servicios (M2M), sucursales (M2M), user (FK)
  servicios.TipoServicio      → nombre, costo_base, precio_mensual, precio_proyecto, activo
  servicios.Sucursal          → nombre, direccion, activa
  core.PerfilUsuario          → rol, profesional (O2O), paciente (O2O), sucursales (M2M)
  agenda.Sesion               → paciente, profesional, fecha, hora_inicio, estado,
                                 tipo_sesion (FK TipoServicio), monto, sucursal
  agenda.Proyecto             → paciente, profesional, estado, fecha_inicio, monto_total
  agenda.Mensualidad          → paciente, profesional, estado, monto
  facturacion.Pago            → paciente, monto, fecha, metodo_pago, anulado,
                                 sesion (FK nullable), proyecto (FK nullable),
                                 mensualidad (FK nullable)
  facturacion.CuentaCorriente → paciente (O2O), saldo_actual, total_pagado,
                                 total_consumido_actual, pagos_adelantados,
                                 saldo_real, total_sesiones_normales_real
  facturacion.Factura         → paciente, numero_factura, fecha_emision, total,
                                 estado (borrador/emitida/anulada), razon_social
"""

import json
import os
from datetime import datetime, timedelta
from django.db.models import Q, Sum, Count
from django.utils import timezone

# ============================================================
# CONFIGURACIÓN
# ============================================================

GROQ_API_KEY  = os.environ.get('GROQ_API_KEY', '')
IA_USER_USERNAME = 'asistente_ia'
MODELO_GROQ   = 'llama-3.3-70b-versatile'


def get_o_crear_usuario_ia():
    """Obtiene o crea el usuario ficticio que representa al agente IA."""
    from django.contrib.auth.models import User
    user, _ = User.objects.get_or_create(
        username=IA_USER_USERNAME,
        defaults={
            'first_name': 'Asistente',
            'last_name': 'IA',
            'is_active': True,
            'email': 'ia@sistema.interno',
        }
    )
    return user


# ============================================================
# TOOLS
# ============================================================

def tool_obtener_pacientes(filtro: str = '', limite: int = 20) -> dict:
    """
    Busca pacientes. Filtra por nombre, apellido o nombre del tutor.
    Campos reales: nombre, apellido, nombre_tutor, telefono_tutor,
                   fecha_nacimiento, genero, estado, diagnostico
    """
    try:
        from pacientes.models import Paciente
        qs = Paciente.objects.prefetch_related('sucursales')
        if filtro:
            qs = qs.filter(
                Q(nombre__icontains=filtro) |
                Q(apellido__icontains=filtro) |
                Q(nombre_tutor__icontains=filtro)
            )
        resultado = []
        for p in qs.order_by('apellido', 'nombre')[:limite]:
            sucursales = ', '.join(s.nombre for s in p.sucursales.filter(activa=True))
            resultado.append({
                'id':            p.id,
                'nombre_completo': f'{p.nombre} {p.apellido}',
                'edad':          p.edad,
                'genero':        p.get_genero_display(),
                'estado':        p.estado,
                'tutor':         p.nombre_tutor,
                'parentesco':    p.get_parentesco_display(),
                'telefono_tutor': p.telefono_tutor,
                'diagnostico':   (p.diagnostico[:120] + '…') if len(p.diagnostico) > 120 else p.diagnostico,
                'sucursales':    sucursales or 'Sin asignar',
                'fecha_registro': str(p.fecha_registro.date()) if p.fecha_registro else '',
            })
        return {'pacientes': resultado, 'total': len(resultado)}
    except Exception as e:
        return {'error': str(e)}


def tool_obtener_sesiones(
    fecha_inicio: str = '',
    fecha_fin: str = '',
    profesional_id: int = None,
    paciente_id: int = None,
    estado: str = '',
    solo_hoy: bool = False,
) -> dict:
    """
    Consulta sesiones de la agenda.
    estados: realizada, programada, cancelada, falta, retraso,
             realizada_retraso, con_retraso
    Si no se pasan fechas, devuelve los próximos 7 días.
    solo_hoy=True devuelve solo las sesiones de hoy.
    """
    try:
        from agenda.models import Sesion
        qs = Sesion.objects.select_related(
            'paciente', 'profesional', 'tipo_sesion', 'sucursal'
        )

        hoy = timezone.now().date()
        if solo_hoy:
            qs = qs.filter(fecha=hoy)
        else:
            qs = qs.filter(fecha__gte=fecha_inicio if fecha_inicio else hoy)
            if fecha_fin:
                qs = qs.filter(fecha__lte=fecha_fin)
            elif not fecha_inicio:
                qs = qs.filter(fecha__lte=hoy + timedelta(days=7))

        if profesional_id:
            qs = qs.filter(profesional_id=profesional_id)
        if paciente_id:
            qs = qs.filter(paciente_id=paciente_id)
        if estado:
            qs = qs.filter(estado=estado)

        # Contadores útiles
        contadores = qs.values('estado').annotate(n=Count('id'))
        resumen_estados = {r['estado']: r['n'] for r in contadores}

        sesiones = []
        for s in qs.order_by('fecha', 'hora_inicio')[:60]:
            profesional_nombre = 'Sin asignar'
            if s.profesional:
                profesional_nombre = f'{s.profesional.nombre} {s.profesional.apellido}'
            sesiones.append({
                'id':          s.id,
                'fecha':       str(s.fecha),
                'hora':        str(getattr(s, 'hora_inicio', '') or ''),
                'paciente':    f'{s.paciente.nombre} {s.paciente.apellido}',
                'profesional': profesional_nombre,
                'estado':      s.estado,
                'tipo':        str(s.tipo_sesion) if s.tipo_sesion else 'N/A',
                'monto':       str(getattr(s, 'monto', '0')),
                'sucursal':    str(s.sucursal) if getattr(s, 'sucursal', None) else 'N/A',
            })

        return {
            'sesiones': sesiones,
            'total': len(sesiones),
            'resumen_por_estado': resumen_estados,
        }
    except Exception as e:
        return {'error': str(e)}


def tool_obtener_profesionales(filtro: str = '', especialidad: str = '') -> dict:
    """
    Busca profesionales.
    Campos reales: nombre, apellido, especialidad, telefono, email, activo
    """
    try:
        from profesionales.models import Profesional
        qs = Profesional.objects.prefetch_related('servicios', 'sucursales').filter(activo=True)
        if filtro:
            qs = qs.filter(
                Q(nombre__icontains=filtro) |
                Q(apellido__icontains=filtro)
            )
        if especialidad:
            qs = qs.filter(especialidad__icontains=especialidad)

        resultado = []
        for p in qs.order_by('nombre', 'apellido')[:30]:
            servicios   = ', '.join(s.nombre for s in p.servicios.filter(activo=True))
            sucursales  = ', '.join(s.nombre for s in p.sucursales.filter(activa=True))
            resultado.append({
                'id':          p.id,
                'nombre':      f'{p.nombre} {p.apellido}',
                'especialidad': getattr(p, 'especialidad', 'N/A'),
                'telefono':    getattr(p, 'telefono', 'N/A'),
                'email':       getattr(p, 'email', 'N/A'),
                'servicios':   servicios or 'Sin servicios',
                'sucursales':  sucursales or 'Sin sucursales',
                'activo':      p.activo,
            })
        return {'profesionales': resultado, 'total': len(resultado)}
    except Exception as e:
        return {'error': str(e)}


def tool_obtener_pagos(
    fecha_inicio: str = '',
    fecha_fin: str = '',
    paciente_id: int = None,
    limite: int = 30,
) -> dict:
    """
    Consulta pagos no anulados.
    Campos reales: paciente, monto, fecha, metodo_pago, anulado
    """
    try:
        from facturacion.models import Pago
        qs = Pago.objects.select_related(
            'paciente', 'metodo_pago'
        ).filter(anulado=False)

        if fecha_inicio:
            qs = qs.filter(fecha__gte=fecha_inicio)
        if fecha_fin:
            qs = qs.filter(fecha__lte=fecha_fin)
        if paciente_id:
            qs = qs.filter(paciente_id=paciente_id)

        totales = qs.aggregate(total=Sum('monto'), cantidad=Count('id'))

        pagos = []
        for p in qs.order_by('-fecha')[:limite]:
            pagos.append({
                'id':       p.id,
                'fecha':    str(p.fecha),
                'paciente': f'{p.paciente.nombre} {p.paciente.apellido}',
                'monto':    str(p.monto),
                'metodo':   str(p.metodo_pago) if p.metodo_pago else 'N/A',
            })

        return {
            'pagos': pagos,
            'resumen': {
                'total_cobrado': str(totales['total'] or 0),
                'cantidad_pagos': totales['cantidad'],
            },
        }
    except Exception as e:
        return {'error': str(e)}


def tool_obtener_cuentas_corrientes(
    filtro: str = '',
    estado_saldo: str = '',
) -> dict:
    """
    Consulta saldos de cuentas corrientes.
    estado_saldo: deudor (saldo < 0) | al_dia (= 0) | a_favor (> 0)
    Campos reales: saldo_actual, total_pagado, total_consumido_actual,
                   pagos_adelantados, saldo_real
    """
    try:
        from facturacion.models import CuentaCorriente
        qs = CuentaCorriente.objects.select_related('paciente')

        if filtro:
            qs = qs.filter(
                Q(paciente__nombre__icontains=filtro) |
                Q(paciente__apellido__icontains=filtro) |
                Q(paciente__nombre_tutor__icontains=filtro)
            )
        if estado_saldo == 'deudor':
            qs = qs.filter(saldo_actual__lt=0)
        elif estado_saldo == 'al_dia':
            qs = qs.filter(saldo_actual=0)
        elif estado_saldo == 'a_favor':
            qs = qs.filter(saldo_actual__gt=0)

        resumen = qs.aggregate(
            suma_saldos=Sum('saldo_actual'),
            cantidad=Count('id'),
        )

        cuentas = []
        for c in qs.order_by('saldo_actual')[:30]:
            cuentas.append({
                'paciente':          f'{c.paciente.nombre} {c.paciente.apellido}',
                'estado_paciente':   c.paciente.estado,
                'saldo_actual':      str(c.saldo_actual),
                'saldo_real':        str(c.saldo_real),
                'total_pagado':      str(c.total_pagado),
                'total_consumido':   str(c.total_consumido_actual),
                'credito_disponible': str(c.pagos_adelantados),
            })

        return {
            'cuentas': cuentas,
            'resumen': {
                'suma_todos_saldos': str(resumen['suma_saldos'] or 0),
                'total_pacientes':   resumen['cantidad'],
            },
        }
    except Exception as e:
        return {'error': str(e)}


def tool_obtener_facturas(
    fecha_inicio: str = '',
    fecha_fin: str = '',
    paciente_id: int = None,
    estado: str = '',
) -> dict:
    """
    Consulta facturas.
    estados: borrador | emitida | anulada
    Campos reales: numero_factura, fecha_emision, total, estado, razon_social
    """
    try:
        from facturacion.models import Factura
        qs = Factura.objects.select_related('paciente')

        if fecha_inicio:
            qs = qs.filter(fecha_emision__gte=fecha_inicio)
        if fecha_fin:
            qs = qs.filter(fecha_emision__lte=fecha_fin)
        if paciente_id:
            qs = qs.filter(paciente_id=paciente_id)
        if estado:
            qs = qs.filter(estado=estado)

        totales = qs.filter(estado='emitida').aggregate(
            total=Sum('total'), cantidad=Count('id')
        )

        facturas = []
        for f in qs.order_by('-fecha_emision')[:25]:
            facturas.append({
                'numero':       f.numero_factura,
                'fecha':        str(f.fecha_emision),
                'paciente':     f'{f.paciente.nombre} {f.paciente.apellido}',
                'razon_social': f.razon_social,
                'total':        str(f.total),
                'estado':       f.estado,
            })

        return {
            'facturas': facturas,
            'resumen': {
                'total_facturado_emitido': str(totales['total'] or 0),
                'cantidad_emitidas':       totales['cantidad'],
            },
        }
    except Exception as e:
        return {'error': str(e)}


def tool_obtener_proyectos(
    paciente_id: int = None,
    profesional_id: int = None,
    estado: str = '',
) -> dict:
    """
    Consulta proyectos terapéuticos.
    estados: planificado | en_progreso | finalizado | cancelado
    """
    try:
        from agenda.models import Proyecto
        qs = Proyecto.objects.select_related('paciente', 'profesional')

        if paciente_id:
            qs = qs.filter(paciente_id=paciente_id)
        if profesional_id:
            qs = qs.filter(profesional_id=profesional_id)
        if estado:
            qs = qs.filter(estado=estado)

        proyectos = []
        for p in qs.order_by('-fecha_inicio')[:30]:
            prof = 'Sin asignar'
            if p.profesional:
                prof = f'{p.profesional.nombre} {p.profesional.apellido}'
            proyectos.append({
                'id':           p.id,
                'paciente':     f'{p.paciente.nombre} {p.paciente.apellido}',
                'profesional':  prof,
                'estado':       getattr(p, 'estado', 'N/A'),
                'fecha_inicio': str(getattr(p, 'fecha_inicio', '')),
                'monto_total':  str(getattr(p, 'monto_total', '0')),
            })
        return {'proyectos': proyectos, 'total': len(proyectos)}
    except Exception as e:
        return {'error': str(e)}


def tool_obtener_servicios() -> dict:
    """Lista todos los tipos de servicio activos con sus precios."""
    try:
        from servicios.models import TipoServicio
        servicios = TipoServicio.objects.filter(activo=True).order_by('nombre')
        resultado = []
        for s in servicios:
            resultado.append({
                'id':              s.id,
                'nombre':          s.nombre,
                'costo_sesion':    str(s.costo_base),
                'precio_mensual':  str(s.precio_mensual or 'N/A'),
                'precio_proyecto': str(s.precio_proyecto or 'N/A'),
                'duracion_min':    s.duracion_minutos,
            })
        return {'servicios': resultado, 'total': len(resultado)}
    except Exception as e:
        return {'error': str(e)}


def tool_obtener_sucursales() -> dict:
    """Lista las sucursales activas del centro."""
    try:
        from servicios.models import Sucursal
        sucursales = Sucursal.objects.filter(activa=True)
        resultado = [
            {'id': s.id, 'nombre': s.nombre, 'direccion': s.direccion, 'telefono': s.telefono}
            for s in sucursales
        ]
        return {'sucursales': resultado, 'total': len(resultado)}
    except Exception as e:
        return {'error': str(e)}


def tool_estadisticas_generales() -> dict:
    """
    Resumen estadístico completo del sistema.
    Ideal para informes rápidos del día o del mes.
    """
    try:
        from pacientes.models import Paciente
        from profesionales.models import Profesional
        from agenda.models import Sesion
        from facturacion.models import Pago, CuentaCorriente

        hoy         = timezone.now().date()
        inicio_mes  = hoy.replace(day=1)

        sesiones_hoy = Sesion.objects.filter(fecha=hoy)
        sesiones_mes = Sesion.objects.filter(fecha__gte=inicio_mes)

        stats = {
            'fecha_actual':               str(hoy),

            # Pacientes
            'pacientes_activos':          Paciente.objects.filter(estado='activo').count(),
            'pacientes_inactivos':        Paciente.objects.filter(estado='inactivo').count(),

            # Profesionales
            'profesionales_activos':      Profesional.objects.filter(activo=True).count(),

            # Sesiones hoy
            'sesiones_hoy_total':         sesiones_hoy.count(),
            'sesiones_hoy_realizadas':    sesiones_hoy.filter(estado='realizada').count(),
            'sesiones_hoy_programadas':   sesiones_hoy.filter(estado='programada').count(),
            'sesiones_hoy_canceladas':    sesiones_hoy.filter(estado='cancelada').count(),
            'sesiones_hoy_falta':         sesiones_hoy.filter(estado='falta').count(),

            # Sesiones del mes
            'sesiones_mes_total':         sesiones_mes.count(),
            'sesiones_mes_realizadas':    sesiones_mes.filter(estado='realizada').count(),
            'sesiones_mes_canceladas':    sesiones_mes.filter(estado='cancelada').count(),

            # Cobros del mes
            'cobros_mes_bs':              str(
                Pago.objects.filter(
                    fecha__gte=inicio_mes, anulado=False
                ).aggregate(t=Sum('monto'))['t'] or 0
            ),

            # Saldos
            'pacientes_con_deuda':        CuentaCorriente.objects.filter(saldo_actual__lt=0).count(),
            'pacientes_con_credito':      CuentaCorriente.objects.filter(saldo_actual__gt=0).count(),
            'pacientes_al_dia':           CuentaCorriente.objects.filter(saldo_actual=0).count(),
            'deuda_total_sistema_bs':     str(
                CuentaCorriente.objects.filter(
                    saldo_actual__lt=0
                ).aggregate(t=Sum('saldo_actual'))['t'] or 0
            ),
            'credito_total_sistema_bs':   str(
                CuentaCorriente.objects.filter(
                    saldo_actual__gt=0
                ).aggregate(t=Sum('saldo_actual'))['t'] or 0
            ),
        }
        return stats
    except Exception as e:
        return {'error': str(e)}


def tool_buscar_en_sistema(termino: str) -> dict:
    """Búsqueda global: pacientes, profesionales, servicios y sucursales."""
    resultados = {}

    try:
        from pacientes.models import Paciente
        pacs = Paciente.objects.filter(
            Q(nombre__icontains=termino) |
            Q(apellido__icontains=termino) |
            Q(nombre_tutor__icontains=termino)
        )[:5]
        resultados['pacientes'] = [f'{p.nombre} {p.apellido} (ID:{p.id}, {p.estado})' for p in pacs]
    except Exception:
        resultados['pacientes'] = []

    try:
        from profesionales.models import Profesional
        profs = Profesional.objects.filter(
            Q(nombre__icontains=termino) |
            Q(apellido__icontains=termino) |
            Q(especialidad__icontains=termino)
        )[:5]
        resultados['profesionales'] = [
            f'{p.nombre} {p.apellido} — {p.especialidad} (ID:{p.id})' for p in profs
        ]
    except Exception:
        resultados['profesionales'] = []

    try:
        from servicios.models import TipoServicio
        servs = TipoServicio.objects.filter(nombre__icontains=termino, activo=True)[:5]
        resultados['servicios'] = [f'{s.nombre} — Bs.{s.costo_base}' for s in servs]
    except Exception:
        resultados['servicios'] = []

    try:
        from servicios.models import Sucursal
        sucs = Sucursal.objects.filter(nombre__icontains=termino, activa=True)[:5]
        resultados['sucursales'] = [f'{s.nombre} — {s.direccion}' for s in sucs]
    except Exception:
        resultados['sucursales'] = []

    return resultados


# ============================================================
# DEFINICIÓN DE TOOLS PARA GROQ (formato OpenAI-compatible)
# ============================================================

TOOLS_DEFINICION = [
    {
        "type": "function",
        "function": {
            "name": "obtener_pacientes",
            "description": "Busca y lista pacientes. Filtra por nombre, apellido o tutor.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filtro": {"type": "string", "description": "Texto a buscar en nombre, apellido o tutor"},
                    "limite": {"type": "integer", "description": "Máximo resultados (default 20)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "obtener_sesiones",
            "description": (
                "Consulta sesiones de la agenda. "
                "estados válidos: realizada, programada, cancelada, falta, retraso, realizada_retraso. "
                "Usa solo_hoy=true para ver la agenda del día de hoy."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "fecha_inicio":    {"type": "string",  "description": "Fecha inicio YYYY-MM-DD"},
                    "fecha_fin":       {"type": "string",  "description": "Fecha fin YYYY-MM-DD"},
                    "profesional_id":  {"type": "integer", "description": "ID del profesional"},
                    "paciente_id":     {"type": "integer", "description": "ID del paciente"},
                    "estado":          {"type": "string",  "description": "Estado de la sesión"},
                    "solo_hoy":        {"type": "boolean", "description": "true para solo sesiones de hoy"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "obtener_profesionales",
            "description": "Busca profesionales activos por nombre o especialidad.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filtro":      {"type": "string", "description": "Nombre a buscar"},
                    "especialidad": {"type": "string", "description": "Especialidad a filtrar"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "obtener_pagos",
            "description": "Consulta pagos realizados. Puede filtrar por fechas y paciente.",
            "parameters": {
                "type": "object",
                "properties": {
                    "fecha_inicio": {"type": "string",  "description": "Fecha inicio YYYY-MM-DD"},
                    "fecha_fin":    {"type": "string",  "description": "Fecha fin YYYY-MM-DD"},
                    "paciente_id":  {"type": "integer", "description": "ID del paciente"},
                    "limite":       {"type": "integer", "description": "Máximo resultados"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "obtener_cuentas_corrientes",
            "description": (
                "Consulta saldos y cuentas corrientes de pacientes. "
                "estado_saldo: deudor (negativo), al_dia (cero), a_favor (positivo)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filtro":       {"type": "string", "description": "Nombre del paciente"},
                    "estado_saldo": {"type": "string", "description": "deudor | al_dia | a_favor"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "obtener_facturas",
            "description": "Consulta facturas. estados: borrador, emitida, anulada.",
            "parameters": {
                "type": "object",
                "properties": {
                    "fecha_inicio": {"type": "string",  "description": "Fecha inicio YYYY-MM-DD"},
                    "fecha_fin":    {"type": "string",  "description": "Fecha fin YYYY-MM-DD"},
                    "paciente_id":  {"type": "integer", "description": "ID del paciente"},
                    "estado":       {"type": "string",  "description": "borrador | emitida | anulada"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "obtener_proyectos",
            "description": "Consulta proyectos terapéuticos. estados: planificado, en_progreso, finalizado, cancelado.",
            "parameters": {
                "type": "object",
                "properties": {
                    "paciente_id":    {"type": "integer", "description": "ID del paciente"},
                    "profesional_id": {"type": "integer", "description": "ID del profesional"},
                    "estado":         {"type": "string",  "description": "Estado del proyecto"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "obtener_servicios",
            "description": "Lista todos los tipos de servicio activos con sus precios (sesión, mensual, proyecto).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "obtener_sucursales",
            "description": "Lista las sucursales activas del centro con dirección y teléfono.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "estadisticas_generales",
            "description": (
                "Genera un resumen estadístico completo: pacientes activos, sesiones del día "
                "y del mes, cobros, deudas y créditos. Ideal para informes rápidos."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "buscar_en_sistema",
            "description": "Búsqueda global en pacientes, profesionales, servicios y sucursales.",
            "parameters": {
                "type": "object",
                "properties": {
                    "termino": {"type": "string", "description": "Texto a buscar"},
                },
                "required": ["termino"],
            },
        },
    },
]

TOOLS_MAP = {
    'obtener_pacientes':         tool_obtener_pacientes,
    'obtener_sesiones':          tool_obtener_sesiones,
    'obtener_profesionales':     tool_obtener_profesionales,
    'obtener_pagos':             tool_obtener_pagos,
    'obtener_cuentas_corrientes': tool_obtener_cuentas_corrientes,
    'obtener_facturas':          tool_obtener_facturas,
    'obtener_proyectos':         tool_obtener_proyectos,
    'obtener_servicios':         tool_obtener_servicios,
    'obtener_sucursales':        tool_obtener_sucursales,
    'estadisticas_generales':    tool_estadisticas_generales,
    'buscar_en_sistema':         tool_buscar_en_sistema,
}


# ============================================================
# SYSTEM PROMPT SEGÚN ROL (usa PerfilUsuario real del proyecto)
# ============================================================

def _get_system_prompt(usuario) -> str:
    hoy = datetime.now().strftime('%d/%m/%Y %H:%M')
    base = f"""Eres el Asistente IA del Centro Terapéutico. Fecha y hora actual: {hoy}.

Tienes acceso en tiempo real a la base de datos mediante herramientas (tools).
Puedes consultar: pacientes, sesiones, agenda, profesionales, pagos, cuentas corrientes, facturas, proyectos, servicios y sucursales.

REGLAS:
- Usa SIEMPRE las herramientas para datos reales. Nunca inventes información.
- Responde en español claro y bien estructurado.
- Usa emojis (📊 💰 📅 👥 🏥) para organizar informes largos.
- Las monedas son Bolivianos (Bs.).
- Si no encuentras datos, dilo claramente.
- Si el usuario pregunta por el día de hoy, usa solo_hoy=true en obtener_sesiones."""

    # Superadmin
    if usuario.is_superuser:
        return base + "\n\n🔑 Acceso TOTAL. Puedes consultar y ver todo el sistema."

    # Sin perfil
    if not hasattr(usuario, 'perfil'):
        return base

    perfil = usuario.perfil

    # ROL PACIENTE
    if perfil.es_paciente():
        paciente = getattr(perfil, 'paciente', None)
        paciente_id = paciente.id if paciente else None
        nombre = f'{paciente.nombre} {paciente.apellido}' if paciente else usuario.get_full_name()
        return base + f"""

👤 Usuario: {nombre} (Paciente, ID:{paciente_id})
⚠️ RESTRICCIÓN ESTRICTA: Solo puedes mostrar información de ESTE paciente (ID:{paciente_id}).
Puedes ayudarle con: sus sesiones, sus pagos, su saldo y sus proyectos."""

    # ROL PROFESIONAL
    if perfil.es_profesional():
        prof = getattr(perfil, 'profesional', None)
        prof_id = prof.id if prof else None
        nombre = f'{prof.nombre} {prof.apellido}' if prof else usuario.get_full_name()
        return base + f"""

👨‍⚕️ Usuario: {nombre} (Profesional, ID:{prof_id})
Puedes ayudarle con: su agenda, sus pacientes asignados, estadísticas de sus sesiones e informes de actividad."""

    # ROL RECEPCIONISTA
    if perfil.es_recepcionista():
        sucursales = perfil.get_sucursales()
        nombres_suc = ', '.join(s.nombre for s in sucursales) if sucursales else 'todas'
        return base + f"""

🗂️ Usuario: {usuario.get_full_name()} (Recepcionista — Sucursales: {nombres_suc})
Puedes ayudarle con: agenda del día, búsqueda de pacientes, registro de pagos y consultas administrativas."""

    # ROL GERENTE
    if perfil.es_gerente():
        return base + f"""

📊 Usuario: {usuario.get_full_name()} (Gerente)
Acceso amplio. Puedes generar informes financieros, estadísticas globales, resúmenes de actividad y análisis de deudas."""

    return base


# ============================================================
# LÓGICA PRINCIPAL
# ============================================================

def responder_con_ia(conversacion, usuario_humano):
    """
    Llama a Groq, ejecuta las tools necesarias y guarda
    la respuesta como Mensaje en la conversación.
    """
    from .models import Mensaje, NotificacionChat

    usuario_ia  = get_o_crear_usuario_ia()
    historial   = _construir_historial(conversacion, usuario_ia)
    system_prompt = _get_system_prompt(usuario_humano)
    respuesta   = _llamar_groq_con_tools(historial, system_prompt)

    mensaje_ia = Mensaje.objects.create(
        conversacion=conversacion,
        remitente=usuario_ia,
        contenido=respuesta,
    )
    NotificacionChat.objects.create(
        usuario=usuario_humano,
        conversacion=conversacion,
        mensaje=mensaje_ia,
    )
    conversacion.save()
    return mensaje_ia


def _construir_historial(conversacion, usuario_ia, limite: int = 15) -> list:
    """Convierte los últimos N mensajes al formato Groq/OpenAI."""
    msgs = list(conversacion.mensajes.order_by('-fecha_envio')[:limite])
    msgs.reverse()
    return [
        {'role': 'assistant' if m.remitente == usuario_ia else 'user',
         'content': m.contenido}
        for m in msgs
    ]


def _llamar_groq_con_tools(historial: list, system_prompt: str) -> str:
    """Llama a Groq con tool use en bucle hasta obtener respuesta de texto."""
    try:
        from groq import Groq
    except ImportError:
        return '⚠️ El paquete groq no está instalado. Ejecuta: pip install groq'

    if not GROQ_API_KEY:
        return '⚠️ GROQ_API_KEY no configurada. Añádela al archivo .env'

    client   = Groq(api_key=GROQ_API_KEY)
    mensajes = [{'role': 'system', 'content': system_prompt}] + historial

    for _ in range(6):  # máx 6 rondas de tool use
        response = client.chat.completions.create(
            model=MODELO_GROQ,
            messages=mensajes,
            tools=TOOLS_DEFINICION,
            tool_choice='auto',
            max_tokens=2048,
            temperature=0.1,
        )

        msg = response.choices[0].message

        if not msg.tool_calls:
            # Respuesta final de texto
            return msg.content or 'No pude generar una respuesta. Intenta reformular tu pregunta.'

        # Añadir mensaje del asistente con tool_calls
        mensajes.append({
            'role':       'assistant',
            'content':    msg.content or '',
            'tool_calls': [
                {
                    'id':   tc.id,
                    'type': 'function',
                    'function': {
                        'name':      tc.function.name,
                        'arguments': tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ],
        })

        # Ejecutar cada tool y añadir resultado
        for tc in msg.tool_calls:
            nombre = tc.function.name
            try:
                args = json.loads(tc.function.arguments or '{}')
            except json.JSONDecodeError:
                args = {}

            if nombre in TOOLS_MAP:
                resultado = TOOLS_MAP[nombre](**args)
            else:
                resultado = {'error': f'Tool "{nombre}" no encontrada'}

            mensajes.append({
                'role':         'tool',
                'tool_call_id': tc.id,
                'content':      json.dumps(resultado, ensure_ascii=False, default=str),
            })

    return 'Se alcanzó el límite de consultas internas. Por favor reformula tu pregunta.'