from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.db.models import Q, Max, Count
from django.utils import timezone
from django.contrib.auth.models import User

from .models import Conversacion, Mensaje, NotificacionChat
from .permisos import pueden_chatear, get_usuarios_disponibles_para_chat


@login_required
def lista_conversaciones(request):
    """
    ✅ Vista principal - Lista todas las conversaciones del usuario
    """
    usuario = request.user
    
    # Obtener todas las conversaciones donde participa el usuario
    conversaciones = Conversacion.objects.filter(
        Q(usuario_1=usuario) | Q(usuario_2=usuario),
        activa=True
    ).select_related(
        'usuario_1', 'usuario_2'
    ).annotate(
        ultimo_mensaje_fecha=Max('mensajes__fecha_envio')
    ).order_by('-ultimo_mensaje_fecha')
    
    # Preparar datos para la vista
    conversaciones_data = []
    for conv in conversaciones:
        otro_usuario = conv.get_otro_usuario(usuario)
        ultimo_mensaje = conv.get_ultimo_mensaje()
        mensajes_no_leidos = conv.get_mensajes_no_leidos(usuario)
        
        # Obtener nombre completo y rol
        nombre_completo = otro_usuario.get_full_name() or otro_usuario.username
        rol = 'Usuario'
        info_adicional = None  # ✅ NUEVA: Información adicional
        
        if otro_usuario.is_superuser:
            rol = 'Administrador'
        elif hasattr(otro_usuario, 'perfil'):
            rol = otro_usuario.perfil.get_rol_display()
            
            # ✅ NUEVO: Obtener info adicional según el rol
            if otro_usuario.perfil.es_profesional() and hasattr(otro_usuario, 'profesional'):
                # Mostrar especialidad del profesional
                profesional = otro_usuario.profesional
                info_adicional = profesional.especialidad
            
            elif otro_usuario.perfil.es_paciente() and hasattr(otro_usuario, 'paciente'):
                # ✅ CORREGIDO: Usar nombre del paciente si get_full_name está vacío
                paciente = otro_usuario.paciente
                if not otro_usuario.get_full_name():
                    nombre_completo = f"{paciente.nombre} {paciente.apellido}"
                info_adicional = f"Tutor: {paciente.nombre_tutor}"
        
        conversaciones_data.append({
            'conversacion': conv,
            'otro_usuario': otro_usuario,
            'nombre_completo': nombre_completo,
            'rol': rol,
            'info_adicional': info_adicional,  # ✅ NUEVO
            'ultimo_mensaje': ultimo_mensaje,
            'mensajes_no_leidos': mensajes_no_leidos,
        })
    
    context = {
        'conversaciones_data': conversaciones_data,
        'total_conversaciones': len(conversaciones_data),
    }
    
    return render(request, 'chat/lista_conversaciones.html', context)


@login_required
def chat_conversacion(request, conversacion_id):
    """
    ✅ Vista del chat - Interfaz de mensajería
    """
    usuario = request.user
    conversacion = get_object_or_404(Conversacion, id=conversacion_id)
    
    # ✅ Verificar que el usuario es participante
    if not conversacion.es_participante(usuario):
        messages.error(request, '⛔ No tienes permiso para acceder a esta conversación.')
        return redirect('chat:lista_conversaciones')
    
    # Obtener el otro usuario
    otro_usuario = conversacion.get_otro_usuario(usuario)
    
    # ✅ Verificar permisos de chat
    if not pueden_chatear(usuario, otro_usuario):
        messages.error(request, '⛔ No tienes permiso para chatear con este usuario.')
        return redirect('chat:lista_conversaciones')
    
    # Marcar mensajes como leídos
    conversacion.marcar_mensajes_como_leidos(usuario)
    
    # Obtener todos los mensajes
    mensajes = conversacion.mensajes.select_related('remitente').order_by('fecha_envio')
    
    # Obtener información del otro usuario
    nombre_completo = otro_usuario.get_full_name() or otro_usuario.username
    rol = 'Usuario'
    info_adicional = None  # ✅ NUEVA: Información adicional
    
    if otro_usuario.is_superuser:
        rol = 'Administrador'
    elif hasattr(otro_usuario, 'perfil'):
        rol = otro_usuario.perfil.get_rol_display()
        
        # ✅ NUEVO: Obtener info adicional según el rol
        if otro_usuario.perfil.es_profesional() and hasattr(otro_usuario, 'profesional'):
            # Mostrar especialidad del profesional
            profesional = otro_usuario.profesional
            info_adicional = profesional.especialidad
        
        elif otro_usuario.perfil.es_paciente() and hasattr(otro_usuario, 'paciente'):
            # ✅ CORREGIDO: Usar nombre del paciente si get_full_name está vacío
            paciente = otro_usuario.paciente
            if not otro_usuario.get_full_name():
                nombre_completo = f"{paciente.nombre} {paciente.apellido}"
            info_adicional = f"Tutor: {paciente.nombre_tutor}"
    
    context = {
        'conversacion': conversacion,
        'mensajes': mensajes,
        'otro_usuario': otro_usuario,
        'nombre_completo': nombre_completo,
        'rol': rol,
        'info_adicional': info_adicional,  # ✅ NUEVO
    }
    
    return render(request, 'chat/chat.html', context)


@login_required
def enviar_mensaje(request, conversacion_id):
    """
    ✅ API para enviar mensaje (AJAX)
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)
    
    usuario = request.user
    conversacion = get_object_or_404(Conversacion, id=conversacion_id)
    
    # ✅ Verificar que el usuario es participante
    if not conversacion.es_participante(usuario):
        return JsonResponse({'error': 'No tienes permiso'}, status=403)
    
    # Obtener contenido del mensaje
    contenido = request.POST.get('contenido', '').strip()
    
    if not contenido:
        return JsonResponse({'error': 'El mensaje no puede estar vacío'}, status=400)
    
    if len(contenido) > 1000:
        return JsonResponse({'error': 'El mensaje es demasiado largo'}, status=400)
    
    # Crear el mensaje
    mensaje = Mensaje.objects.create(
        conversacion=conversacion,
        remitente=usuario,
        contenido=contenido
    )
    
    # Crear notificación para el otro usuario
    otro_usuario = conversacion.get_otro_usuario(usuario)
    NotificacionChat.objects.create(
        usuario=otro_usuario,
        conversacion=conversacion,
        mensaje=mensaje
    )
    
    # Actualizar la conversación
    conversacion.save()  # Actualiza ultima_actualizacion
    
    return JsonResponse({
        'success': True,
        'mensaje_id': mensaje.id,
        'fecha_envio': mensaje.fecha_envio.strftime('%H:%M'),
    })


@login_required
def obtener_nuevos_mensajes(request, conversacion_id):
    """
    ✅ API para obtener nuevos mensajes (Polling - AJAX)
    """
    usuario = request.user
    conversacion = get_object_or_404(Conversacion, id=conversacion_id)
    
    # ✅ Verificar que el usuario es participante
    if not conversacion.es_participante(usuario):
        return JsonResponse({'error': 'No tienes permiso'}, status=403)
    
    # Obtener el ID del último mensaje conocido por el cliente
    ultimo_mensaje_id = request.GET.get('ultimo_mensaje_id', 0)
    
    # Obtener mensajes nuevos
    mensajes_nuevos = conversacion.mensajes.filter(
        id__gt=ultimo_mensaje_id
    ).select_related('remitente').order_by('fecha_envio')
    
    # Marcar como leídos los mensajes del otro usuario
    conversacion.marcar_mensajes_como_leidos(usuario)
    
    # Preparar respuesta
    mensajes_data = []
    for msg in mensajes_nuevos:
        mensajes_data.append({
            'id': msg.id,
            'contenido': msg.contenido,
            'remitente_id': msg.remitente.id,
            'remitente_nombre': msg.remitente.get_full_name() or msg.remitente.username,
            'fecha_envio': msg.fecha_envio.strftime('%H:%M'),
            'leido': msg.leido,
        })
    
    return JsonResponse({
        'hay_nuevos': len(mensajes_data) > 0,
        'mensajes': mensajes_data,
    })


@login_required
def iniciar_conversacion(request, destinatario_id):
    """
    ✅ Inicia una conversación con un usuario específico
    """
    usuario = request.user
    destinatario = get_object_or_404(User, id=destinatario_id)
    
    # ✅ Verificar permisos
    if not pueden_chatear(usuario, destinatario):
        messages.error(
            request,
            f'⛔ No tienes permiso para chatear con {destinatario.get_full_name() or destinatario.username}.'
        )
        return redirect('chat:lista_conversaciones')
    
    # Buscar conversación existente (en ambas direcciones)
    conversacion = Conversacion.objects.filter(
        Q(usuario_1=usuario, usuario_2=destinatario) |
        Q(usuario_1=destinatario, usuario_2=usuario)
    ).first()
    
    # Si no existe, crearla
    if not conversacion:
        conversacion = Conversacion.objects.create(
            usuario_1=usuario,
            usuario_2=destinatario
        )
        
        messages.success(
            request,
            f'💬 Conversación iniciada con {destinatario.get_full_name() or destinatario.username}'
        )
    
    # Redirigir al chat
    return redirect('chat:chat_conversacion', conversacion_id=conversacion.id)


@login_required
def seleccionar_destinatario(request):
    """
    ✅ Vista para seleccionar con quién chatear
    """
    usuario = request.user
    
    # Obtener usuarios disponibles agrupados por rol
    usuarios_disponibles = get_usuarios_disponibles_para_chat(usuario)
    
    # ✅ NUEVO: Enriquecer usuarios con información adicional
    usuarios_enriquecidos = {}
    
    for rol, usuarios in usuarios_disponibles.items():
        if usuarios and len(usuarios) > 0:
            usuarios_con_info = []
            for u in usuarios:
                info_adicional = None
                nombre_completo = u.get_full_name() or u.username
                
                # Obtener info adicional según el rol
                if hasattr(u, 'perfil'):
                    if u.perfil.es_profesional() and hasattr(u, 'profesional'):
                        info_adicional = u.profesional.especialidad
                    elif u.perfil.es_paciente() and hasattr(u, 'paciente'):
                        # ✅ CORREGIDO: Usar nombre del paciente si get_full_name está vacío
                        paciente = u.paciente
                        if not u.get_full_name():
                            nombre_completo = f"{paciente.nombre} {paciente.apellido}"
                        info_adicional = f"Tutor: {paciente.nombre_tutor}"
                
                usuarios_con_info.append({
                    'usuario': u,
                    'nombre_completo': nombre_completo,
                    'info_adicional': info_adicional
                })
            
            usuarios_enriquecidos[rol] = usuarios_con_info
    
    context = {
        'usuarios_disponibles': usuarios_enriquecidos,
        'total_contactos': sum(len(v) for v in usuarios_enriquecidos.values()),
    }
    
    return render(request, 'chat/seleccionar_destinatario.html', context)


@login_required
def marcar_conversacion_leida(request, conversacion_id):
    """
    ✅ API para marcar una conversación como leída (AJAX)
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)
    
    usuario = request.user
    conversacion = get_object_or_404(Conversacion, id=conversacion_id)
    
    # ✅ Verificar que el usuario es participante
    if not conversacion.es_participante(usuario):
        return JsonResponse({'error': 'No tienes permiso'}, status=403)
    
    # Marcar mensajes como leídos
    conversacion.marcar_mensajes_como_leidos(usuario)
    
    return JsonResponse({'success': True})