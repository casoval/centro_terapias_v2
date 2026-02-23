"""
Vistas para el chat con Agente IA.
Se integran al sistema de chat existente.
"""

import threading
from django.shortcuts import redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.db.models import Q

from .models import Conversacion, Mensaje, NotificacionChat
from .ia_agent import get_o_crear_usuario_ia, responder_con_ia


def _responder_en_background(conversacion_id, usuario_humano_id):
    """
    Ejecuta la respuesta de la IA en un hilo separado
    para no bloquear el request HTTP del usuario.
    """
    import django
    from django.contrib.auth.models import User

    try:
        conversacion = Conversacion.objects.get(id=conversacion_id)
        usuario = User.objects.get(id=usuario_humano_id)
        responder_con_ia(conversacion, usuario)
    except Exception as e:
        # Log silencioso: el usuario verá que no llegó respuesta
        # y puede reenviar el mensaje
        print(f'[IA Agent Error] {e}')


@login_required
def chat_con_ia(request):
    """
    Inicia o retoma la conversación del usuario con el agente IA.
    Redirige al chat existente reutilizando la vista chat_conversacion.
    """
    usuario = request.user
    usuario_ia = get_o_crear_usuario_ia()

    # Buscar conversación existente (en cualquier orden de usuario_1/usuario_2)
    conversacion = Conversacion.objects.filter(
        Q(usuario_1=usuario, usuario_2=usuario_ia) |
        Q(usuario_1=usuario_ia, usuario_2=usuario)
    ).first()

    if not conversacion:
        # Siempre: humano = usuario_1, IA = usuario_2
        conversacion = Conversacion.objects.create(
            usuario_1=usuario,
            usuario_2=usuario_ia,
        )
        # Mensaje de bienvenida automático
        Mensaje.objects.create(
            conversacion=conversacion,
            remitente=usuario_ia,
            contenido=(
                '👋 ¡Hola! Soy el Asistente IA de la clínica.\n\n'
                'Puedo ayudarte con:\n'
                '• 📋 Información de pacientes y profesionales\n'
                '• 📅 Consultar y revisar la agenda\n'
                '• 📊 Generar informes y estadísticas\n'
                '• 💰 Datos de facturación\n'
                '• 🔍 Buscar cualquier cosa en el sistema\n\n'
                'También puedes hablarme usando el 🎤 micrófono y escuchar mis respuestas en voz alta.\n\n'
                '¿En qué te puedo ayudar hoy?'
            )
        )
        conversacion.save()

    return redirect('chat:chat_conversacion', conversacion_id=conversacion.id)


@login_required
def enviar_mensaje_ia(request, conversacion_id):
    """
    Versión especial de enviar_mensaje que detecta si la conversación
    es con el agente IA y dispara la respuesta automática.

    Esta view reemplaza/extiende la lógica de enviar_mensaje en views.py.
    Se puede llamar desde la misma URL de envío o desde una URL dedicada.
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

    # Guardar el mensaje del usuario
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
        # Lanzar respuesta en hilo separado para no bloquear
        hilo = threading.Thread(
            target=_responder_en_background,
            args=(conversacion.id, usuario.id),
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
        'es_chat_ia': es_chat_ia,
    })