"""
agente/paciente_db.py
Consultas de solo lectura a la base de datos para el Agente Paciente.
NUNCA modifica datos — EXCEPTO mensajes de chat para notificaciones.
"""

import logging
from datetime import date, timedelta

log = logging.getLogger('agente')


def buscar_paciente_por_telefono(telefono: str):
    try:
        from pacientes.models import Paciente
        tel = telefono.strip()
        if tel.startswith('591'):
            tel = tel[3:]
        paciente = Paciente.objects.filter(telefono_tutor=tel, estado='activo').first()
        if not paciente:
            paciente = Paciente.objects.filter(telefono_tutor_2=tel, estado='activo').first()
        return paciente
    except Exception as e:
        log.error(f'[PacienteDB] Error buscando por teléfono {telefono}: {e}')
        return None


def get_info_basica(paciente) -> dict:
    try:
        edad = None
        if paciente.fecha_nacimiento:
            hoy = date.today()
            fn  = paciente.fecha_nacimiento
            edad = hoy.year - fn.year - ((hoy.month, hoy.day) < (fn.month, fn.day))
        return {
            'nombre':       paciente.nombre,
            'apellido':     paciente.apellido,
            'nombre_tutor': paciente.nombre_tutor,
            'edad':         edad,
            'estado':       paciente.estado,
        }
    except Exception as e:
        log.error(f'[PacienteDB] Error get_info_basica: {e}')
        return {}


def get_sesiones_proximas(paciente, dias: int = 14) -> list:
    try:
        from agenda.models import Sesion
        hoy    = date.today()
        limite = hoy + timedelta(days=dias)
        sesiones = Sesion.objects.filter(
            paciente=paciente, estado='programada',
            fecha__gte=hoy, fecha__lte=limite,
        ).select_related('profesional', 'servicio', 'sucursal').order_by('fecha', 'hora_inicio')

        resultado = []
        for s in sesiones:
            resultado.append({
                'id':            s.id,
                'fecha':         s.fecha.strftime('%d/%m/%Y'),
                'dia':           _nombre_dia(s.fecha.weekday()),
                'hora':          s.hora_inicio.strftime('%H:%M') if s.hora_inicio else '—',
                'servicio':      s.servicio.nombre if s.servicio else '—',
                'profesional':   f'{s.profesional.nombre} {s.profesional.apellido}' if s.profesional else '—',
                'profesional_id': s.profesional.id if s.profesional else None,
                'sucursal':      s.sucursal.nombre if s.sucursal else '—',
                'sucursal_id':   s.sucursal.id if s.sucursal else None,
                'monto':         float(s.monto_cobrado) if s.monto_cobrado else 0,
            })
        return resultado
    except Exception as e:
        log.error(f'[PacienteDB] Error get_sesiones_proximas: {e}')
        return []


def get_sesiones_recientes(paciente, limite: int = 5) -> list:
    try:
        from agenda.models import Sesion
        ESTADOS = {
            'realizada': 'Realizada', 'realizada_retraso': 'Realizada con retraso',
            'permiso': 'Permiso', 'falta': 'Falta',
            'cancelada': 'Cancelada', 'reprogramada': 'Reprogramada',
        }
        sesiones = Sesion.objects.filter(
            paciente=paciente,
            estado__in=['realizada', 'realizada_retraso', 'permiso', 'falta', 'cancelada'],
        ).select_related('profesional', 'servicio').order_by('-fecha', '-hora_inicio')[:limite]

        return [{
            'fecha':       s.fecha.strftime('%d/%m/%Y'),
            'servicio':    s.servicio.nombre if s.servicio else '—',
            'profesional': f'{s.profesional.nombre} {s.profesional.apellido}' if s.profesional else '—',
            'estado':      ESTADOS.get(s.estado, s.estado),
            'monto':       float(s.monto_cobrado) if s.monto_cobrado else 0,
        } for s in sesiones]
    except Exception as e:
        log.error(f'[PacienteDB] Error get_sesiones_recientes: {e}')
        return []


def get_cuenta_corriente(paciente) -> dict:
    try:
        from facturacion.models import CuentaCorriente
        cuenta = CuentaCorriente.objects.filter(paciente=paciente).first()
        if not cuenta:
            return {}
        saldo = float(cuenta.saldo_actual or 0)
        return {
            'saldo_actual':         saldo,
            'total_pagado':         float(cuenta.total_pagado or 0),
            'total_consumido':      float(cuenta.total_consumido_actual or 0),
            'deuda':                abs(saldo) if saldo < 0 else 0,
            'credito':              saldo if saldo > 0 else 0,
            'sesiones_realizadas':  cuenta.num_sesiones_realizadas_pendientes or 0,
            'sesiones_programadas': cuenta.num_sesiones_programadas_pendientes or 0,
        }
    except Exception as e:
        log.error(f'[PacienteDB] Error get_cuenta_corriente: {e}')
        return {}


def get_pagos_recientes(paciente, limite: int = 5) -> list:
    try:
        from facturacion.models import Pago
        pagos = Pago.objects.filter(
            paciente=paciente, anulado=False,
        ).select_related('metodo_pago').order_by('-fecha_pago')[:limite]
        return [{
            'fecha':    p.fecha_pago.strftime('%d/%m/%Y') if p.fecha_pago else '—',
            'monto':    float(p.monto or 0),
            'metodo':   p.metodo_pago.nombre if p.metodo_pago else '—',
            'concepto': p.concepto or '—',
            'recibo':   p.numero_recibo or '—',
        } for p in pagos]
    except Exception as e:
        log.error(f'[PacienteDB] Error get_pagos_recientes: {e}')
        return []


def get_profesionales_del_paciente(paciente) -> list:
    try:
        from agenda.models import Sesion
        profs = Sesion.objects.filter(
            paciente=paciente,
            estado__in=['programada', 'realizada', 'realizada_retraso'],
        ).select_related('profesional', 'servicio').values(
            'profesional__id', 'profesional__nombre', 'profesional__apellido',
            'profesional__especialidad', 'profesional__user_id', 'servicio__nombre',
        ).distinct()

        resultado = []
        vistos = set()
        for p in profs:
            pid = p['profesional__id']
            if pid and pid not in vistos:
                vistos.add(pid)
                resultado.append({
                    'id':          pid,
                    'user_id':     p['profesional__user_id'],
                    'nombre':      f"{p['profesional__nombre']} {p['profesional__apellido']}",
                    'especialidad': p['profesional__especialidad'] or '—',
                    'servicio':    p['servicio__nombre'] or '—',
                })
        return resultado
    except Exception as e:
        log.error(f'[PacienteDB] Error get_profesionales_del_paciente: {e}')
        return []


# ─────────────────────────────────────────────────────────────
# NOTIFICACIONES MÚLTIPLES
# ─────────────────────────────────────────────────────────────

def _get_usuarios_a_notificar(paciente) -> list:
    """
    Retorna todos los usuarios que deben recibir notificaciones:
    profesionales del paciente + recepcionistas + gerentes + admins.
    """
    from django.contrib.auth.models import User

    usuarios = []
    vistos   = set()

    def agregar(user):
        if user and user.id not in vistos:
            vistos.add(user.id)
            usuarios.append(user)

    # 1. Profesionales que atienden al paciente
    try:
        for p in get_profesionales_del_paciente(paciente):
            if p.get('user_id'):
                u = User.objects.filter(id=p['user_id']).first()
                if u:
                    agregar(u)
    except Exception as e:
        log.error(f'[PacienteDB] Error obteniendo profesionales: {e}')

    # 2. Recepcionistas de la sucursal del paciente
    try:
        sucursales = paciente.sucursales.all()
        for u in User.objects.filter(
            perfil__rol='recepcionista',
            perfil__sucursales__in=sucursales,
            is_active=True,
        ).distinct():
            agregar(u)
    except Exception as e:
        log.error(f'[PacienteDB] Error obteniendo recepcionistas: {e}')

    # 3. Gerentes de la sucursal del paciente
    try:
        sucursales = paciente.sucursales.all()
        for u in User.objects.filter(
            perfil__rol='gerente',
            perfil__sucursales__in=sucursales,
            is_active=True,
        ).distinct():
            agregar(u)
    except Exception as e:
        log.error(f'[PacienteDB] Error obteniendo gerentes: {e}')

    # 4. Superusuarios/Admin
    try:
        for u in User.objects.filter(is_superuser=True, is_active=True):
            agregar(u)
    except Exception as e:
        log.error(f'[PacienteDB] Error obteniendo admins: {e}')

    return usuarios


def _enviar_mensaje_chat(remitente, destinatario, contenido: str) -> bool:
    """Envía un mensaje por el chat interno."""
    try:
        from chat.models import Conversacion, Mensaje, NotificacionChat
        from django.db.models import Q

        conv = Conversacion.objects.filter(
            Q(usuario_1=remitente, usuario_2=destinatario) |
            Q(usuario_1=destinatario, usuario_2=remitente)
        ).first()

        if not conv:
            conv = Conversacion.objects.create(
                usuario_1=remitente,
                usuario_2=destinatario,
            )

        msg = Mensaje.objects.create(
            conversacion=conv,
            remitente=remitente,
            contenido=contenido,
        )
        NotificacionChat.objects.create(
            usuario=destinatario,
            conversacion=conv,
            mensaje=msg,
        )
        conv.save()
        return True
    except Exception as e:
        log.error(f'[PacienteDB] Error enviando chat a {destinatario}: {e}')
        return False


def notificar_solicitud(paciente, tipo: str, detalle: str) -> int:
    """
    Notifica a TODOS los usuarios relevantes sobre una solicitud del tutor.

    tipo: 'permiso' | 'cancelacion' | 'peticion'
    detalle: descripción de la solicitud

    Retorna el número de usuarios notificados.
    """
    from django.contrib.auth.models import User

    remitente = (
        User.objects.filter(is_superuser=True).first() or
        User.objects.filter(is_staff=True).first()
    )
    if not remitente:
        log.error('[PacienteDB] No hay usuario admin para enviar notificaciones')
        return 0

    TITULOS = {
        'permiso':     '📋 SOLICITUD DE PERMISO',
        'cancelacion': '🚫 SOLICITUD DE CANCELACION',
        'peticion':    '⚡ PETICION ESPECIAL',
    }

    mensaje = (
        f"{TITULOS.get(tipo, '📩 SOLICITUD')}\n"
        f"Paciente: {paciente.nombre} {paciente.apellido}\n"
        f"Tutor: {paciente.nombre_tutor} — Tel: {paciente.telefono_tutor}\n"
        f"Detalle: {detalle}\n"
        f"Recibido por WhatsApp — requiere accion manual en el sistema"
    )

    usuarios    = _get_usuarios_a_notificar(paciente)
    notificados = 0

    for usuario in usuarios:
        if usuario.id == remitente.id:
            continue
        if _enviar_mensaje_chat(remitente, usuario, mensaje):
            notificados += 1
            log.info(f'[PacienteDB] Notificado: {usuario.get_full_name() or usuario.username}')

    log.info(f'[PacienteDB] {tipo} para {paciente.nombre} — {notificados} usuarios notificados')
    return notificados


def _nombre_dia(weekday: int) -> str:
    dias = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
    return dias[weekday] if 0 <= weekday <= 6 else '—'