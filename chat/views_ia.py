"""
Vistas para el chat con Agente IA.
Se integran al sistema de chat existente.

✅ AGENTES ESPECIALIZADOS POR ROL:
   Gerente, Recepcionista, Profesional y Superusuario reciben respuestas
   del agente especializado que ya usan en WhatsApp (con acceso real a BD:
   agenda, pagos, pacientes, estadísticas, etc.).
   Pacientes y otros roles siguen usando el agente genérico (ia_agent.py).

✅ HISTORIAL SEPARADO:
   El historial del chat interno se guarda con clave 'chat_interno:<user_id>'
   en ConversacionAgente, completamente independiente del historial de WhatsApp.

✅ GARANTÍA DE RESPUESTA:
   El hilo background siempre guarda una respuesta en BD, incluso si hay
   error — el usuario nunca se queda con "pensando..." eternamente.
"""

import threading
import logging

from django.shortcuts import redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.db.models import Q

from .models import Conversacion, Mensaje, NotificacionChat
from .ia_agent import get_o_crear_usuario_ia, responder_con_ia

logger = logging.getLogger(__name__)


# ============================================================
# MENSAJES DE ERROR AMIGABLES POR TIPO DE FALLO
# ============================================================

def _mensaje_error_amigable(excepcion: Exception) -> str:
    """
    Convierte una excepción técnica en un mensaje amigable para el usuario.
    """
    texto = str(excepcion).lower()

    if 'api key' in texto or 'authentication' in texto or 'anthropic_api_key' in texto:
        return (
            '⚠️ No se ha configurado la clave de acceso a la IA.\n'
            'Por favor contacta al administrador del sistema.'
        )

    if 'rate limit' in texto or 'rate_limit' in texto or '429' in texto:
        return (
            '⏳ El servicio de IA está recibiendo muchas consultas en este momento.\n'
            'Por favor espera unos segundos e intenta de nuevo.'
        )

    if 'timeout' in texto or 'timed out' in texto or 'connection' in texto:
        return (
            '🌐 No se pudo conectar con el servicio de IA.\n'
            'Verifica tu conexión e intenta de nuevo.'
        )

    if 'import' in texto or 'module' in texto:
        return (
            '⚠️ El módulo de IA no está instalado correctamente.\n'
            'Contacta al administrador del sistema.'
        )

    return (
        '😓 Ocurrió un error al procesar tu mensaje.\n'
        'Por favor intenta de nuevo en unos momentos.'
    )


# ============================================================
# HILO BACKGROUND — SIEMPRE GUARDA RESPUESTA
# ============================================================

def _responder_en_background(conversacion_id: int, usuario_humano_id: int, contenido_mensaje: str):
    """
    Ejecuta la respuesta de la IA en un hilo separado.

    LÓGICA DE DESPACHO POR ROL:
      - Superusuario → agente.superusuario (Sonnet/Opus, contexto total)
      - Gerente       → agente.gerente     (Haiku/Sonnet, finanzas + operativo)
      - Recepcionista → agente.recepcionista (Haiku/Sonnet, agenda + pagos)
      - Recepcionista + Profesional → agente combinado
      - Profesional   → agente.profesional (Haiku/Sonnet, clínico)
      - Paciente / otros → ia_agent.responder_con_ia (agente genérico)

    ✅ GARANTÍA: Siempre guarda un mensaje en la BD al terminar,
    ya sea la respuesta real o un mensaje de error amigable.
    """
    from django.contrib.auth.models import User

    usuario_ia = None
    conversacion = None

    try:
        conversacion = Conversacion.objects.get(id=conversacion_id)
        usuario = User.objects.get(id=usuario_humano_id)
        usuario_ia = get_o_crear_usuario_ia()

        # ── Intentar agente especializado según rol ───────────────────────────
        uso_especializado = _despachar_agente(conversacion, usuario, contenido_mensaje)

        if not uso_especializado:
            # Paciente u otro rol sin agente especializado → agente genérico
            responder_con_ia(conversacion, usuario)

    except Exception as exc:
        logger.error(
            f'[IA Agent Error] conversacion_id={conversacion_id} '
            f'usuario_id={usuario_humano_id} | {type(exc).__name__}: {exc}',
            exc_info=True
        )

        # ✅ Guardar mensaje de error amigable en el chat
        try:
            if conversacion is None:
                conversacion = Conversacion.objects.get(id=conversacion_id)
            if usuario_ia is None:
                usuario_ia = get_o_crear_usuario_ia()

            usuario = User.objects.get(id=usuario_humano_id)

            mensaje_error = Mensaje.objects.create(
                conversacion=conversacion,
                remitente=usuario_ia,
                contenido=_mensaje_error_amigable(exc)
            )
            NotificacionChat.objects.create(
                usuario=usuario,
                conversacion=conversacion,
                mensaje=mensaje_error
            )
            conversacion.save()

        except Exception as exc_fallback:
            logger.critical(
                f'[IA Agent] No se pudo guardar mensaje de error en BD: {exc_fallback}',
                exc_info=True
            )


def _despachar_agente(conversacion, usuario, contenido_mensaje: str) -> bool:
    """
    Decide qué agente usar según el rol del usuario y ejecuta la respuesta.

    Retorna True  → se usó un agente especializado (la respuesta ya está guardada).
    Retorna False → debe usarse el agente genérico (ia_agent.responder_con_ia).
    """
    try:
        from .ia_bridge import (
            responder_con_agente_especializado,
            guardar_mensaje_usuario_en_historial,
            _staff_desde_user,
            _tipo_agente_para_historial,
        )

        staff = _staff_desde_user(usuario)

        if not staff.tipo_agente:
            # Paciente u otro rol → agente genérico
            return False

        # Guardar el mensaje del usuario en ConversacionAgente ANTES de despachar
        # para que el agente lo encuentre al construir el historial.
        guardar_mensaje_usuario_en_historial(
            usuario,
            _tipo_agente_para_historial(staff.tipo_agente),
            contenido_mensaje,
        )

        # Llamar al agente especializado (guarda la respuesta en chat.Mensaje)
        responder_con_agente_especializado(conversacion, usuario)
        return True

    except Exception as exc:
        logger.error(
            f'[IA Dispatch] Error al despachar agente para {usuario.username}: {exc}',
            exc_info=True
        )
        raise  # el bloque except de _responder_en_background maneja el fallback


# ============================================================
# VISTAS
# ============================================================

@login_required
def chat_con_ia(request):
    """
    Inicia o retoma la conversación del usuario con el agente IA.
    Redirige al chat existente reutilizando la vista chat_conversacion.
    """
    usuario = request.user
    usuario_ia = get_o_crear_usuario_ia()

    conversacion = Conversacion.objects.filter(
        Q(usuario_1=usuario, usuario_2=usuario_ia) |
        Q(usuario_1=usuario_ia, usuario_2=usuario)
    ).first()

    if not conversacion:
        conversacion = Conversacion.objects.create(
            usuario_1=usuario,
            usuario_2=usuario_ia,
        )
        Mensaje.objects.create(
            conversacion=conversacion,
            remitente=usuario_ia,
            contenido=_get_bienvenida(usuario)
        )
        conversacion.save()

    return redirect('chat:chat_conversacion', conversacion_id=conversacion.id)


def _get_bienvenida(usuario) -> str:
    """
    Genera un mensaje de bienvenida personalizado según el rol del usuario.
    Refleja las capacidades del agente especializado que le corresponde.
    """
    nombre = usuario.get_full_name() or usuario.username

    if usuario.is_superuser:
        return (
            f'👋 ¡Hola, {nombre}! Soy el Asistente IA del sistema.\n\n'
            '🔓 Tienes acceso completo a todos los módulos:\n'
            '• 👥 Pacientes y profesionales\n'
            '• 📅 Agenda y sesiones\n'
            '• 💰 Facturación e informes financieros\n'
            '• 📊 Estadísticas globales y rendimiento\n\n'
            '💡 Para consultas rápidas uso Sonnet. Para informes y análisis detallados activo Opus automáticamente.\n\n'
            '🎤 Puedes escribirme o usar el micrófono. ¿En qué te ayudo?'
        )

    if not hasattr(usuario, 'perfil'):
        return (
            f'👋 ¡Hola, {nombre}! Soy el Asistente IA.\n'
            '¿En qué te puedo ayudar hoy?'
        )

    perfil = usuario.perfil

    if perfil.es_paciente():
        return (
            f'👋 ¡Hola, {nombre}! Soy tu Asistente IA personal.\n\n'
            'Puedo ayudarte con:\n'
            '• 📅 Tus próximas citas y sesiones\n'
            '• 💳 El estado de tus pagos\n'
            '• ❓ Cualquier duda sobre la clínica\n\n'
            '🎤 Puedes escribirme o hablarme con el micrófono.\n'
            '¿En qué te puedo ayudar hoy?'
        )

    if perfil.es_profesional():
        return (
            f'👋 ¡Hola, {nombre}! Soy tu Asistente IA.\n\n'
            'Tengo acceso en tiempo real a tu información clínica:\n'
            '• 📅 Tu agenda del día y próximas sesiones\n'
            '• 👥 Información de tus pacientes asignados\n'
            '• 📝 Notas de evolución e historial clínico\n'
            '• 📊 Evaluaciones e informes recientes\n\n'
            '💡 Para consultas simples uso Haiku. Para análisis clínicos detallados activo Sonnet.\n\n'
            '🎤 Puedes escribirme o usar el micrófono. ¿En qué te ayudo?'
        )

    if perfil.es_recepcionista():
        return (
            f'👋 ¡Hola, {nombre}! Soy el Asistente IA.\n\n'
            'Tengo acceso en tiempo real a tu sucursal:\n'
            '• 📅 Agenda del día: programadas, realizadas, cancelaciones\n'
            '• 🔍 Búsqueda de pacientes y profesionales\n'
            '• 💰 Pagos del día, deudas y mensualidades\n'
            '• ✅ Estado de citas y sesiones\n\n'
            '💡 Para consultas rápidas uso Haiku. Para informes y resúmenes activo Sonnet.\n\n'
            '🎤 También puedes hablarme con el micrófono. ¿Qué necesitas?'
        )

    if perfil.es_gerente():
        return (
            f'👋 ¡Hola, {nombre}! Soy el Asistente IA.\n\n'
            'Tengo acceso en tiempo real a toda la operación:\n'
            '• 📊 Informes y estadísticas globales\n'
            '• 💰 Facturación, ingresos, deudas y análisis financiero\n'
            '• 👥 Actividad y rendimiento de pacientes y profesionales\n'
            '• 📅 Agenda general de la clínica\n\n'
            '💡 Para consultas rápidas uso Haiku. Para informes ejecutivos y análisis activo Sonnet.\n\n'
            '🎤 Puedes escribirme o usar el micrófono. ¿Qué informe necesitas?'
        )

    return (
        f'👋 ¡Hola, {nombre}! Soy el Asistente IA de la clínica.\n'
        '¿En qué te puedo ayudar hoy? 🎤'
    )


@login_required
def enviar_mensaje_ia(request, conversacion_id):
    """
    Versión especial de enviar_mensaje que detecta si la conversación
    es con el agente IA y dispara la respuesta automática en background.

    El hilo background despacha al agente especializado según el rol del usuario:
      - Staff (gerente, recepcionista, profesional, superusuario) → agente de WhatsApp
      - Paciente / otros → agente genérico (ia_agent.responder_con_ia)

    ✅ El hilo siempre garantiza una respuesta en BD (real o de error).
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)

    usuario = request.user
    conversacion = get_object_or_404(Conversacion, id=conversacion_id)

    if not conversacion.es_participante(usuario):
        return JsonResponse({'error': 'No tienes permiso'}, status=403)

    contenido = request.POST.get('contenido', '').strip()
    if not contenido:
        return JsonResponse({'error': 'El mensaje no puede estar vacío'}, status=400)
    if len(contenido) > 2000:
        return JsonResponse({'error': 'Mensaje demasiado largo (máx 2000 caracteres)'}, status=400)

    # Guardar el mensaje del usuario en el chat
    mensaje = Mensaje.objects.create(
        conversacion=conversacion,
        remitente=usuario,
        contenido=contenido
    )
    conversacion.save()

    # Verificar si el otro participante es la IA
    otro = conversacion.get_otro_usuario(usuario)
    usuario_ia = get_o_crear_usuario_ia()

    if otro == usuario_ia:
        # Lanzar respuesta en hilo separado — pasa el contenido del mensaje
        # para que _despachar_agente pueda guardarlo en ConversacionAgente
        # antes de llamar al agente especializado.
        hilo = threading.Thread(
            target=_responder_en_background,
            args=(conversacion.id, usuario.id, contenido),
            daemon=True
        )
        hilo.start()
        es_chat_ia = True
    else:
        # Chat normal: crear notificación para el otro usuario
        NotificacionChat.objects.create(
            usuario=otro,
            conversacion=conversacion,
            mensaje=mensaje
        )
        es_chat_ia = False

    return JsonResponse({
        'success': True,
        'mensaje_id': mensaje.id,
        'fecha_envio': mensaje.fecha_envio.strftime('%H:%M'),
        'fecha_iso': mensaje.fecha_envio.strftime('%Y-%m-%d'),  # ✅ para separadores de fecha
        'es_chat_ia': es_chat_ia,
    })