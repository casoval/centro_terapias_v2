"""
chat/ia_bridge.py
Puente entre el sistema de chat interno y los agentes especializados de WhatsApp.

Problema que resuelve:
    Los agentes de WhatsApp (gerente.py, profesional.py, recepcionista.py,
    superusuario.py) esperan un objeto StaffIdentificado construido a partir
    de un número de teléfono. En el chat interno tenemos directamente el
    objeto User de Django — no necesitamos buscar por teléfono.

    Este módulo construye el StaffIdentificado equivalente desde el User,
    y luego llama al agente correcto según el rol.

Uso desde views_ia.py:
    from .ia_bridge import responder_con_agente_especializado
    responder_con_agente_especializado(conversacion, usuario_humano)
"""

import logging
from agente.staff_db import StaffIdentificado

logger = logging.getLogger(__name__)


# ============================================================
# CONSTRUCCIÓN DEL STAFF DESDE USER DE DJANGO
# ============================================================

def _staff_desde_user(usuario) -> StaffIdentificado:
    """
    Construye un StaffIdentificado a partir del User de Django autenticado.
    No necesita buscar por teléfono — ya tenemos el usuario directamente.

    Sigue la misma jerarquía de prioridades que staff_db.identificar_staff:
      1. is_superuser → superusuario
      2. perfil.rol == 'gerente' → gerente
      3. perfil.rol == 'recepcionista' + profesional vinculado activo → recepcionista_profesional
      4. perfil.rol == 'recepcionista' → recepcionista
      5. perfil.rol == 'profesional' (via user.profesional) → profesional
      6. perfil.rol == 'paciente' → None (usa agente genérico de chat)
      7. Sin perfil / caso no reconocido → None (usa agente genérico de chat)
    """
    nombre = usuario.get_full_name() or usuario.username

    # ── 1. Superusuario Django ────────────────────────────────────────────────
    if usuario.is_superuser:
        perfil = getattr(usuario, 'perfil', None)
        logger.info(f'[IABridge] {usuario.username} → Superusuario')
        return StaffIdentificado(
            tipo_agente='superusuario',
            perfil=perfil,
            nombre=nombre,
        )

    perfil = getattr(usuario, 'perfil', None)
    if not perfil or not perfil.activo:
        logger.info(f'[IABridge] {usuario.username} → Sin perfil activo, usará agente genérico')
        return StaffIdentificado()   # tipo_agente=None → agente genérico

    rol = perfil.rol or ''

    # ── 2. Gerente ────────────────────────────────────────────────────────────
    if rol == 'gerente':
        sucursales = perfil.sucursales.all()
        prof = getattr(perfil, 'profesional', None)
        if prof and not prof.activo:
            prof = None
        logger.info(f'[IABridge] {usuario.username} → Gerente')
        return StaffIdentificado(
            tipo_agente='gerente',
            perfil=perfil,
            profesional=prof,
            sucursales=sucursales,
            nombre=nombre,
        )

    # ── 3 & 4. Recepcionista (con o sin profesional vinculado) ────────────────
    if rol == 'recepcionista':
        sucursales = perfil.sucursales.all()
        prof = getattr(perfil, 'profesional', None)
        if prof and not prof.activo:
            prof = None

        if prof:
            logger.info(f'[IABridge] {usuario.username} → Recepcionista+Profesional (combinado)')
            return StaffIdentificado(
                tipo_agente='recepcionista_profesional',
                perfil=perfil,
                profesional=prof,
                sucursales=sucursales,
                es_combinado=True,
                nombre=nombre,
            )
        else:
            logger.info(f'[IABridge] {usuario.username} → Recepcionista')
            return StaffIdentificado(
                tipo_agente='recepcionista',
                perfil=perfil,
                sucursales=sucursales,
                nombre=nombre,
            )

    # ── 5. Profesional ────────────────────────────────────────────────────────
    if rol == 'profesional':
        prof = getattr(usuario, 'profesional', None)
        if prof and prof.activo:
            sucursales = prof.sucursales.all()
            logger.info(f'[IABridge] {usuario.username} → Profesional')
            return StaffIdentificado(
                tipo_agente='profesional',
                perfil=perfil,
                profesional=prof,
                sucursales=sucursales,
                nombre=nombre,
            )
        else:
            logger.info(f'[IABridge] {usuario.username} → Profesional sin objeto activo, agente genérico')
            return StaffIdentificado()

    # ── 6. Paciente u otro rol → agente genérico (ia_agent.py) ───────────────
    logger.info(f'[IABridge] {usuario.username} → Rol "{rol}", usará agente genérico')
    return StaffIdentificado()


# ============================================================
# IDENTIFICADOR DE TELÉFONO PARA EL HISTORIAL DE AGENTE
# ============================================================

def _telefono_chat_interno(usuario) -> str:
    """
    Genera un identificador único para guardar el historial en ConversacionAgente.

    Los agentes de WhatsApp usan el teléfono real como clave del historial.
    En el chat interno usamos 'chat_interno:<user_id>' para que cada usuario
    tenga su propio historial separado del canal WhatsApp.

    Esto permite que el mismo usuario tenga conversaciones independientes
    en WhatsApp y en el chat interno (que es lo correcto).
    """
    return f'chat_interno:{usuario.id}'


# ============================================================
# DISPATCHER PRINCIPAL
# ============================================================

def responder_con_agente_especializado(conversacion, usuario_humano) -> bool:
    """
    Detecta el rol del usuario y llama al agente especializado correspondiente.
    Guarda la respuesta en la conversación del chat interno.

    Retorna True si usó un agente especializado, False si delegó al agente genérico.

    Flujo:
        1. Construye StaffIdentificado desde el User de Django.
        2. Si tipo_agente es None (paciente / rol no reconocido) → retorna False
           para que views_ia.py use el agente genérico (responder_con_ia).
        3. Si tiene tipo_agente → llama al módulo de agente correspondiente,
           construye la respuesta y la guarda como Mensaje en la BD.
    """
    staff = _staff_desde_user(usuario_humano)
    telefono = _telefono_chat_interno(usuario_humano)

    if not staff.tipo_agente:
        # Paciente u otro rol sin agente especializado → delegar al genérico
        return False

    try:
        respuesta = _despachar(staff, telefono)
        _guardar_respuesta(conversacion, usuario_humano, respuesta)
        return True

    except Exception as exc:
        logger.error(
            f'[IABridge] Error en agente especializado para {usuario_humano.username} '
            f'(tipo={staff.tipo_agente}): {exc}',
            exc_info=True
        )
        raise  # views_ia.py maneja el fallback de error


def _despachar(staff: StaffIdentificado, telefono: str) -> str:
    """
    Llama al módulo de agente correcto según el tipo_agente.
    Retorna el texto de la respuesta.
    """
    tipo = staff.tipo_agente

    # ── Obtener el último mensaje del usuario (el que acaba de enviar) ────────
    # Los agentes de WhatsApp reciben el texto plano del mensaje más reciente.
    # Lo recuperamos desde ConversacionAgente — justo el último guardado con rol='user'
    from agente.models import ConversacionAgente
    ultimo = (
        ConversacionAgente.objects
        .filter(agente=_tipo_agente_para_historial(tipo), telefono=telefono, rol='user')
        .order_by('-creado')
        .first()
    )
    mensaje_texto = ultimo.contenido if ultimo else '...'

    if tipo == 'superusuario':
        from agente.superusuario import responder
        return responder(telefono, mensaje_texto, staff=staff)

    elif tipo == 'gerente':
        from agente.gerente import responder
        return responder(telefono, mensaje_texto, staff=staff)

    elif tipo == 'recepcionista':
        from agente.recepcionista import responder
        return responder(telefono, mensaje_texto, staff=staff)

    elif tipo == 'recepcionista_profesional':
        from agente.superusuario import responder_combinado
        return responder_combinado(telefono, mensaje_texto, staff=staff)

    elif tipo == 'profesional':
        from agente.profesional import responder
        return responder(telefono, mensaje_texto, staff=staff)

    else:
        raise ValueError(f'tipo_agente desconocido: {tipo}')


def _tipo_agente_para_historial(tipo_agente: str) -> str:
    """
    Mapea el tipo de StaffIdentificado al nombre de agente usado en ConversacionAgente.
    El combinado usa el historial de 'recepcionista'.
    """
    mapping = {
        'superusuario':              'superusuario',
        'gerente':                   'gerente',
        'recepcionista':             'recepcionista',
        'recepcionista_profesional': 'recepcionista',
        'profesional':               'profesional',
    }
    return mapping.get(tipo_agente, 'recepcionista')


def _guardar_respuesta(conversacion, usuario_humano, respuesta: str):
    """
    Guarda la respuesta del agente especializado como Mensaje en el chat interno.
    Igual que hace responder_con_ia en ia_agent.py.
    """
    from chat.models import Mensaje, NotificacionChat
    from chat.ia_agent import get_o_crear_usuario_ia

    usuario_ia = get_o_crear_usuario_ia()

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


# ============================================================
# FUNCIÓN AUXILIAR: guardar el mensaje del usuario en historial
# de agente ANTES de despachar (los agentes lo hacen internamente,
# pero necesitamos que esté en ConversacionAgente con el telefono correcto)
# ============================================================

def guardar_mensaje_usuario_en_historial(usuario, tipo_agente: str, contenido: str):
    """
    Guarda el mensaje del usuario en ConversacionAgente usando el teléfono
    del chat interno. Los agentes guardan su propio historial internamente
    (guardar_mensaje), pero como el teléfono que usamos es 'chat_interno:<id>',
    no hay colisión con el historial de WhatsApp.

    Llamar a esta función ANTES de despachar al agente especializado,
    para que cuando el agente llame a get_historial() ya encuentre el mensaje.
    """
    from agente.models import ConversacionAgente

    telefono = _telefono_chat_interno(usuario)
    agente_key = _tipo_agente_para_historial(tipo_agente)

    try:
        ConversacionAgente.objects.create(
            agente=agente_key,
            telefono=telefono,
            rol='user',
            contenido=contenido,
        )
    except Exception as exc:
        logger.error(f'[IABridge] Error guardando mensaje usuario en historial: {exc}')