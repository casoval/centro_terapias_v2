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


def get_deudas_detalle(paciente) -> dict:
    """
    Retorna el detalle completo de deudas igual a lo que ve el tutor
    en la pagina mis_deudas — sesiones, proyectos y mensualidades.
    """
    try:
        from agenda.models import Sesion
        from decimal import Decimal

        sesiones_deuda = []
        proyectos_deuda = []
        mensualidades_deuda = []

        total_sesiones = Decimal('0')
        total_proyectos = Decimal('0')
        total_mensualidades = Decimal('0')

        # ── Sesiones normales con deuda ──────────────────────
        sesiones = Sesion.objects.filter(
            paciente=paciente,
            mensualidad__isnull=True,
            proyecto__isnull=True,
        ).select_related('servicio', 'profesional', 'sucursal').order_by('fecha')

        for s in sesiones:
            costo  = Decimal(str(s.monto_cobrado or 0))
            pagado = Decimal(str(s.monto_pagado or 0))
            saldo  = costo - pagado
            if saldo > 0:
                sesiones_deuda.append({
                    'id':        s.id,
                    'fecha':     s.fecha.strftime('%d/%m/%Y'),
                    'descripcion': f"{s.servicio.nombre if s.servicio else '—'} con {s.profesional.nombre_completo if s.profesional else '—'}",
                    'estado':    s.get_estado_display() if hasattr(s, 'get_estado_display') else s.estado,
                    'sucursal':  s.sucursal.nombre if s.sucursal else '—',
                    'costo':     float(costo),
                    'pagado':    float(pagado),
                    'saldo':     float(saldo),
                    'es_futura': s.fecha >= date.today(),
                })
                total_sesiones += saldo

        # ── Proyectos/Evaluaciones con deuda ─────────────────
        try:
            from agenda.models import Proyecto
            proyectos = Proyecto.objects.filter(
                paciente=paciente,
            ).prefetch_related('sesiones').order_by('fecha_inicio')

            for p in proyectos:
                costo  = Decimal(str(p.monto_total or 0))
                pagado = Decimal(str(p.monto_pagado or 0))
                saldo  = costo - pagado
                if saldo > 0:
                    proyectos_deuda.append({
                        'descripcion': p.nombre or 'Proyecto/Evaluacion',
                        'estado':      p.estado if hasattr(p, 'estado') else '—',
                        'costo':       float(costo),
                        'pagado':      float(pagado),
                        'saldo':       float(saldo),
                    })
                    total_proyectos += saldo
        except Exception:
            pass

        # ── Mensualidades con deuda ───────────────────────────
        try:
            from facturacion.models import Mensualidad
            mensualidades = Mensualidad.objects.filter(
                paciente=paciente,
            ).order_by('-periodo_inicio')

            for m in mensualidades:
                costo  = Decimal(str(m.monto_total or 0))
                pagado = Decimal(str(m.monto_pagado or 0))
                saldo  = costo - pagado
                if saldo > 0:
                    periodo = ''
                    if hasattr(m, 'periodo_inicio') and m.periodo_inicio:
                        periodo = m.periodo_inicio.strftime('%B %Y')
                    mensualidades_deuda.append({
                        'descripcion': periodo or 'Mensualidad',
                        'estado':      m.estado if hasattr(m, 'estado') else '—',
                        'costo':       float(costo),
                        'pagado':      float(pagado),
                        'saldo':       float(saldo),
                    })
                    total_mensualidades += saldo
        except Exception:
            pass

        total_general = total_sesiones + total_proyectos + total_mensualidades

        return {
            'total_general':        float(total_general),
            'total_sesiones':       float(total_sesiones),
            'total_proyectos':      float(total_proyectos),
            'total_mensualidades':  float(total_mensualidades),
            'sesiones':             sesiones_deuda,
            'proyectos':            proyectos_deuda,
            'mensualidades':        mensualidades_deuda,
        }

    except Exception as e:
        log.error(f'[PacienteDB] Error get_deudas_detalle: {e}')
        return {}


def get_pagos_detalle(paciente, mes: int = None, anio: int = None, todos: bool = False) -> dict:
    """
    Retorna el historial de pagos igual a lo que ve el tutor en mis_pagos.
    Filtra por mes/anio si se indica, o trae todos si todos=True.
    Por defecto retorna el mes actual.
    """
    try:
        from facturacion.models import Pago
        from decimal import Decimal

        hoy = date.today()
        if todos:
            pagos_qs = Pago.objects.filter(paciente=paciente, anulado=False)
        else:
            m = mes or hoy.month
            a = anio or hoy.year
            pagos_qs = Pago.objects.filter(
                paciente=paciente,
                anulado=False,
                fecha_pago__month=m,
                fecha_pago__year=a,
            )

        pagos_qs = pagos_qs.select_related('metodo_pago').order_by('-fecha_pago')

        pagos_lista = []
        total_pagado = Decimal('0')
        total_devoluciones = Decimal('0')

        for p in pagos_qs:
            monto = Decimal(str(p.monto or 0))
            es_devolucion = monto < 0

            pagos_lista.append({
                'fecha':         p.fecha_pago.strftime('%d/%m/%Y') if p.fecha_pago else '—',
                'recibo':        p.numero_recibo or '—',
                'metodo':        p.metodo_pago.nombre if p.metodo_pago else '—',
                'concepto':      p.concepto or '—',
                'monto':         float(abs(monto)),
                'es_devolucion': es_devolucion,
            })

            if es_devolucion:
                total_devoluciones += abs(monto)
            else:
                total_pagado += monto

        return {
            'pagos':              pagos_lista,
            'total_pagado':       float(total_pagado),
            'total_devoluciones': float(total_devoluciones),
            'total_neto':         float(total_pagado - total_devoluciones),
            'cantidad':           len(pagos_lista),
        }

    except Exception as e:
        log.error(f'[PacienteDB] Error get_pagos_detalle: {e}')
        return {}


def get_proyectos(paciente) -> list:
    """
    Retorna todos los proyectos/evaluaciones del paciente con detalle completo.
    NO incluye observaciones ni notas clinicas internas.
    """
    try:
        from agenda.models import Proyecto
        proyectos = Proyecto.objects.filter(
            paciente=paciente,
        ).select_related(
            'servicio_base', 'profesional_responsable', 'sucursal'
        ).prefetch_related('sesiones').order_by('-fecha_inicio')

        resultado = []
        for p in proyectos:
            sesiones = p.sesiones.all()
            conteo = {
                'total':        sesiones.count(),
                'programadas':  sesiones.filter(estado='programada').count(),
                'realizadas':   sesiones.filter(estado__in=['realizada', 'realizada_retraso']).count(),
                'con_retraso':  sesiones.filter(estado='realizada_retraso').count(),
                'permisos':     sesiones.filter(estado='permiso').count(),
                'faltas':       sesiones.filter(estado='falta').count(),
                'canceladas':   sesiones.filter(estado='cancelada').count(),
                'reprogramadas':sesiones.filter(estado='reprogramada').count(),
            }
            resultado.append({
                'codigo':           p.codigo,
                'nombre':           p.nombre,
                'tipo':             p.get_tipo_display(),
                'estado':           p.get_estado_display(),
                'servicio':         p.servicio_base.nombre if p.servicio_base else '—',
                'profesional':      f"{p.profesional_responsable.nombre} {p.profesional_responsable.apellido}" if p.profesional_responsable else '—',
                'sucursal':         p.sucursal.nombre if p.sucursal else '—',
                'fecha_inicio':     p.fecha_inicio.strftime('%d/%m/%Y'),
                'fecha_fin_est':    p.fecha_fin_estimada.strftime('%d/%m/%Y') if p.fecha_fin_estimada else '—',
                'fecha_fin_real':   p.fecha_fin_real.strftime('%d/%m/%Y') if p.fecha_fin_real else '—',
                'costo_total':      float(p.costo_total),
                'pagado':           float(p.pagado_neto),
                'saldo':            float(p.saldo_pendiente),
                'pagado_completo':  p.pagado_completo,
                'informe_entregado': p.informe_entregado,
                'fecha_informe':    p.fecha_entrega_informe.strftime('%d/%m/%Y') if p.fecha_entrega_informe else '—',
                'sesiones':         conteo,
            })
        return resultado
    except Exception as e:
        log.error(f'[PacienteDB] Error get_proyectos: {e}')
        return []


def get_mensualidades(paciente) -> list:
    """
    Retorna todas las mensualidades del paciente con detalle completo.
    Incluye servicios, profesionales, sesiones por estado y pagos.
    """
    try:
        from agenda.models import Mensualidad
        mensualidades = Mensualidad.objects.filter(
            paciente=paciente,
        ).prefetch_related(
            'servicios_profesionales__servicio',
            'servicios_profesionales__profesional',
            'sesiones',
        ).select_related('sucursal').order_by('-anio', '-mes')

        resultado = []
        for m in mensualidades:
            sesiones = m.sesiones.all()
            conteo = {
                'total':        sesiones.count(),
                'programadas':  sesiones.filter(estado='programada').count(),
                'realizadas':   sesiones.filter(estado__in=['realizada', 'realizada_retraso']).count(),
                'con_retraso':  sesiones.filter(estado='realizada_retraso').count(),
                'permisos':     sesiones.filter(estado='permiso').count(),
                'faltas':       sesiones.filter(estado='falta').count(),
                'canceladas':   sesiones.filter(estado='cancelada').count(),
                'reprogramadas':sesiones.filter(estado='reprogramada').count(),
            }

            servicios = []
            for sp in m.servicios_profesionales.select_related('servicio', 'profesional'):
                servicios.append(
                    f"{sp.servicio.nombre} con {sp.profesional.nombre} {sp.profesional.apellido}"
                )

            resultado.append({
                'codigo':       m.codigo,
                'periodo':      m.periodo_display,
                'mes':          m.mes,
                'anio':         m.anio,
                'estado':       m.get_estado_display(),
                'sucursal':     m.sucursal.nombre if m.sucursal else '—',
                'servicios':    servicios,
                'costo_mensual':float(m.costo_mensual),
                'pagado':       float(m.pagado_neto),
                'saldo':        float(m.saldo_pendiente),
                'pagado_completo': m.pagado_completo,
                'sesiones':     conteo,
            })
        return resultado
    except Exception as e:
        log.error(f'[PacienteDB] Error get_mensualidades: {e}')
        return []


def get_sesiones_completo(paciente, mes: int = None, anio: int = None, todos: bool = False) -> dict:
    """
    Retorna el historial completo de sesiones del paciente con conteo por estado.
    Filtra por mes/anio o trae todas. NO incluye notas clinicas ni observaciones internas.
    """
    try:
        from agenda.models import Sesion

        hoy = date.today()
        if todos:
            sesiones_qs = Sesion.objects.filter(paciente=paciente)
        else:
            m = mes or hoy.month
            a = anio or hoy.year
            sesiones_qs = Sesion.objects.filter(
                paciente=paciente,
                fecha__month=m,
                fecha__year=a,
            )

        sesiones_qs = sesiones_qs.select_related(
            'servicio', 'profesional', 'sucursal'
        ).order_by('-fecha', '-hora_inicio')

        ESTADOS_LABEL = {
            'programada':        'Programada',
            'realizada':         'Realizada',
            'realizada_retraso': 'Realizada con retraso',
            'falta':             'Falta sin aviso',
            'permiso':           'Permiso',
            'cancelada':         'Cancelada',
            'reprogramada':      'Reprogramada',
        }

        lista = []
        conteo = {k: 0 for k in ESTADOS_LABEL}

        for s in sesiones_qs:
            conteo[s.estado] = conteo.get(s.estado, 0) + 1

            item = {
                'id':        s.id,
                'fecha':     s.fecha.strftime('%d/%m/%Y'),
                'hora':      s.hora_inicio.strftime('%H:%M') if s.hora_inicio else '—',
                'servicio':  s.servicio.nombre if s.servicio else '—',
                'profesional': f"{s.profesional.nombre} {s.profesional.apellido}" if s.profesional else '—',
                'sucursal':  s.sucursal.nombre if s.sucursal else '—',
                'estado':    ESTADOS_LABEL.get(s.estado, s.estado),
                'monto':     float(s.monto_cobrado or 0),
                # Retraso — solo si aplica
                'minutos_retraso': s.minutos_retraso if s.estado == 'realizada_retraso' else None,
                # Reprogramacion — solo si aplica
                'fecha_reprogramada': s.fecha_reprogramada.strftime('%d/%m/%Y') if s.fecha_reprogramada else None,
                # NUNCA incluir: notas_sesion, observaciones (datos clinicos internos)
            }
            lista.append(item)

        return {
            'sesiones':  lista,
            'conteo':    conteo,
            'total':     len(lista),
        }
    except Exception as e:
        log.error(f'[PacienteDB] Error get_sesiones_completo: {e}')
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
# NOTIFICACIONES — via chat del Asistente IA
# ─────────────────────────────────────────────────────────────

def _extraer_sesion_id(detalle: str) -> int:
    import re
    match = re.search(r'sesion_id:(\d+)', detalle)
    return int(match.group(1)) if match else 0


def _get_profesional_sesion(detalle: str, paciente) -> list:
    """
    Obtiene el profesional usando el sesion_id incluido en el detalle.
    Fallback: sesión más próxima del paciente.
    """
    from agenda.models import Sesion

    usuarios = []
    sesion_id = _extraer_sesion_id(detalle)

    if sesion_id:
        try:
            sesion = Sesion.objects.select_related('profesional__user').get(
                id=sesion_id, paciente=paciente
            )
            if sesion.profesional and sesion.profesional.user:
                usuarios.append(sesion.profesional.user)
                return usuarios
        except Sesion.DoesNotExist:
            log.warning(f'[PacienteDB] Sesion ID {sesion_id} no encontrada para paciente {paciente.id}')

    hoy = date.today()
    primera = Sesion.objects.filter(
        paciente=paciente,
        estado='programada',
        fecha__gte=hoy,
    ).select_related('profesional__user').order_by('fecha', 'hora_inicio').first()

    if primera and primera.profesional and primera.profesional.user:
        usuarios.append(primera.profesional.user)
        log.info(f'[PacienteDB] Fallback: profesional de sesión más próxima (id={primera.id})')

    return usuarios


def _get_usuarios_a_notificar(paciente, detalle: str = '') -> list:
    """
    Retorna los usuarios que deben recibir la notificación:
    - Profesional de la sesión mencionada (o la más próxima)
    - Recepcionistas de la sucursal
    - Gerentes de la sucursal
    - Superusuarios/Admin
    """
    from django.contrib.auth.models import User

    usuarios = []
    vistos   = set()

    def agregar(user):
        if user and user.id not in vistos:
            vistos.add(user.id)
            usuarios.append(user)

    # 1. Profesional de la sesión específica
    try:
        for u in _get_profesional_sesion(detalle, paciente):
            agregar(u)
    except Exception as e:
        log.error(f'[PacienteDB] Error obteniendo profesional sesión: {e}')

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


def _enviar_notificacion_via_ia(destinatario, contenido: str) -> bool:
    """
    Envía la notificación al chat del Asistente IA del destinatario.
    El Asistente IA es el remitente — aparece en el chat IA del usuario.
    """
    try:
        from chat.models import Conversacion, Mensaje, NotificacionChat
        from chat.ia_agent import get_o_crear_usuario_ia
        from django.db.models import Q

        usuario_ia = get_o_crear_usuario_ia()

        # Obtener o crear la conversación del usuario con el Asistente IA
        conv = Conversacion.objects.filter(
            Q(usuario_1=destinatario, usuario_2=usuario_ia) |
            Q(usuario_1=usuario_ia, usuario_2=destinatario)
        ).first()

        if not conv:
            conv = Conversacion.objects.create(
                usuario_1=usuario_ia,
                usuario_2=destinatario,
            )

        msg = Mensaje.objects.create(
            conversacion=conv,
            remitente=usuario_ia,
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
        log.error(f'[PacienteDB] Error enviando notif IA a {destinatario}: {e}')
        return False


def notificar_solicitud(paciente, tipo: str, detalle: str) -> int:
    """
    Notifica via chat del Asistente IA segun el tipo de solicitud:

    permiso / cancelacion / reprogramacion:
        → Profesional de la sesion (por sesion_id) + recepcion + gerencia + admin

    peticion_profesional:
        → Profesional de la sesion (si hay sesion_id) + recepcion + gerencia + admin

    peticion_centro (nueva evaluacion, nuevo servicio, consulta administrativa):
        → Recepcion + gerencia + admin (NO al profesional)

    Retorna el numero de usuarios notificados.
    """
    TITULOS = {
        'permiso':              '📋 SOLICITUD DE PERMISO',
        'cancelacion':          '🚫 SOLICITUD DE CANCELACION',
        'reprogramacion':       '🔄 SOLICITUD DE REPROGRAMACION',
        'peticion_profesional': '⚡ PETICION AL PROFESIONAL',
        'peticion_centro':      '📩 PETICION AL CENTRO',
    }

    mensaje = (
        f"{TITULOS.get(tipo, '📩 SOLICITUD')}\n"
        f"Paciente: {paciente.nombre} {paciente.apellido}\n"
        f"Tutor: {paciente.nombre_tutor} — Tel: {paciente.telefono_tutor}\n"
        f"Detalle: {detalle}\n"
        f"Recibido por WhatsApp — requiere accion manual en el sistema"
    )

    # peticion_centro: solo recepcion + gerencia + admin, sin profesional
    if tipo == 'peticion_centro':
        usuarios = _get_usuarios_sin_profesional(paciente)
    else:
        usuarios = _get_usuarios_a_notificar(paciente, detalle)

    notificados = 0
    for usuario in usuarios:
        if _enviar_notificacion_via_ia(usuario, mensaje):
            notificados += 1
            log.info(f'[PacienteDB] Notificado via IA: {usuario.get_full_name() or usuario.username}')

    log.info(f'[PacienteDB] {tipo} para {paciente.nombre} — {notificados} usuarios notificados')
    return notificados


def _get_usuarios_sin_profesional(paciente) -> list:
    """Recepcionistas + gerentes de la sucursal + admins. Sin profesionales."""
    from django.contrib.auth.models import User

    usuarios = []
    vistos   = set()

    def agregar(user):
        if user and user.id not in vistos:
            vistos.add(user.id)
            usuarios.append(user)

    try:
        sucursales = paciente.sucursales.all()
        for u in User.objects.filter(
            perfil__rol__in=['recepcionista', 'gerente'],
            perfil__sucursales__in=sucursales,
            is_active=True,
        ).distinct():
            agregar(u)
    except Exception as e:
        log.error(f'[PacienteDB] Error obteniendo recep/gerentes: {e}')

    try:
        for u in User.objects.filter(is_superuser=True, is_active=True):
            agregar(u)
    except Exception as e:
        log.error(f'[PacienteDB] Error obteniendo admins: {e}')

    return usuarios


def _nombre_dia(weekday: int) -> str:
    dias = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
    return dias[weekday] if 0 <= weekday <= 6 else '—'