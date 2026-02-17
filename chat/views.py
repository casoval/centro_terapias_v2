import json
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.db.models import Q, Max, Count
from django.utils import timezone
from django.contrib.auth.models import User

from .models import Conversacion, Mensaje, NotificacionChat
from .permisos import pueden_chatear, get_usuarios_disponibles_para_chat


# ✅ Helper para obtener tema_chat de cualquier usuario (todos los roles)
def _get_tema_chat(usuario):
    """
    Obtiene el tema de chat del usuario sin importar su rol.
    Crea el perfil si no existe (cubre superadmin sin perfil).
    """
    try:
        if hasattr(usuario, 'perfil'):
            return usuario.perfil.tema_chat
        # Superadmin u otro usuario sin perfil: buscar o crear
        from core.models import PerfilUsuario
        perfil, _ = PerfilUsuario.objects.get_or_create(
            user=usuario,
            defaults={'activo': True}
        )
        return perfil.tema_chat
    except Exception:
        return 'default'


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
        info_adicional = None
        foto_url = None
        
        if otro_usuario.is_superuser:
            rol = 'Administrador'
        elif hasattr(otro_usuario, 'perfil'):
            rol = otro_usuario.perfil.get_rol_display()
            
            if otro_usuario.perfil.es_profesional() and hasattr(otro_usuario, 'profesional'):
                profesional = otro_usuario.profesional
                info_adicional = profesional.especialidad
                if profesional.foto:
                    foto_url = profesional.foto.url
            
            elif otro_usuario.perfil.es_paciente() and hasattr(otro_usuario, 'paciente'):
                paciente = otro_usuario.paciente
                if not otro_usuario.get_full_name():
                    nombre_completo = f"{paciente.nombre} {paciente.apellido}"
                info_adicional = f"Tutor: {paciente.nombre_tutor}"
                if paciente.foto:
                    foto_url = paciente.foto.url
        
        conversaciones_data.append({
            'conversacion': conv,
            'otro_usuario': otro_usuario,
            'nombre_completo': nombre_completo,
            'rol': rol,
            'info_adicional': info_adicional,
            'foto_url': foto_url,
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
    mensajes_qs = conversacion.mensajes.select_related('remitente').order_by('fecha_envio')
    
    # Obtener información del otro usuario
    nombre_completo = otro_usuario.get_full_name() or otro_usuario.username
    rol = 'Usuario'
    info_adicional = None
    foto_url = None
    
    # ✅ Obtener tema de chat del usuario actual (TODOS LOS ROLES, incluyendo superadmin)
    tema_chat = _get_tema_chat(usuario)
    
    if otro_usuario.is_superuser:
        rol = 'Administrador'
    elif hasattr(otro_usuario, 'perfil'):
        rol = otro_usuario.perfil.get_rol_display()
        
        if otro_usuario.perfil.es_profesional() and hasattr(otro_usuario, 'profesional'):
            profesional = otro_usuario.profesional
            info_adicional = profesional.especialidad
            if profesional.foto:
                foto_url = profesional.foto.url
        
        elif otro_usuario.perfil.es_paciente() and hasattr(otro_usuario, 'paciente'):
            paciente = otro_usuario.paciente
            if not otro_usuario.get_full_name():
                nombre_completo = f"{paciente.nombre} {paciente.apellido}"
            info_adicional = f"Tutor: {paciente.nombre_tutor}"
            if paciente.foto:
                foto_url = paciente.foto.url
    
    context = {
        'conversacion': conversacion,
        'mensajes': mensajes_qs,
        'otro_usuario': otro_usuario,
        'nombre_completo': nombre_completo,
        'rol': rol,
        'info_adicional': info_adicional,
        'foto_url': foto_url,
        'tema_chat': tema_chat,
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
    
    if not conversacion.es_participante(usuario):
        return JsonResponse({'error': 'No tienes permiso'}, status=403)
    
    contenido = request.POST.get('contenido', '').strip()
    
    if not contenido:
        return JsonResponse({'error': 'El mensaje no puede estar vacío'}, status=400)
    
    if len(contenido) > 1000:
        return JsonResponse({'error': 'El mensaje es demasiado largo'}, status=400)
    
    mensaje = Mensaje.objects.create(
        conversacion=conversacion,
        remitente=usuario,
        contenido=contenido
    )
    
    otro_usuario = conversacion.get_otro_usuario(usuario)
    NotificacionChat.objects.create(
        usuario=otro_usuario,
        conversacion=conversacion,
        mensaje=mensaje
    )
    
    conversacion.save()
    
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
    
    if not conversacion.es_participante(usuario):
        return JsonResponse({'error': 'No tienes permiso'}, status=403)
    
    ultimo_mensaje_id = request.GET.get('ultimo_mensaje_id', 0)
    
    mensajes_nuevos = conversacion.mensajes.filter(
        id__gt=ultimo_mensaje_id
    ).select_related('remitente').order_by('fecha_envio')
    
    conversacion.marcar_mensajes_como_leidos(usuario)
    
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
    
    if not pueden_chatear(usuario, destinatario):
        messages.error(
            request,
            f'⛔ No tienes permiso para chatear con {destinatario.get_full_name() or destinatario.username}.'
        )
        return redirect('chat:lista_conversaciones')
    
    conversacion = Conversacion.objects.filter(
        Q(usuario_1=usuario, usuario_2=destinatario) |
        Q(usuario_1=destinatario, usuario_2=usuario)
    ).first()
    
    if not conversacion:
        conversacion = Conversacion.objects.create(
            usuario_1=usuario,
            usuario_2=destinatario
        )
        messages.success(
            request,
            f'💬 Conversación iniciada con {destinatario.get_full_name() or destinatario.username}'
        )
    
    return redirect('chat:chat_conversacion', conversacion_id=conversacion.id)


@login_required
def seleccionar_destinatario(request):
    """
    ✅ Vista para seleccionar con quién chatear
    """
    usuario = request.user
    
    usuarios_disponibles = get_usuarios_disponibles_para_chat(usuario)
    
    usuarios_enriquecidos = {}
    
    for rol, usuarios in usuarios_disponibles.items():
        if usuarios and len(usuarios) > 0:
            usuarios_con_info = []
            for u in usuarios:
                info_adicional = None
                nombre_completo = u.get_full_name() or u.username
                foto_url = None
                
                if hasattr(u, 'perfil'):
                    if u.perfil.es_profesional() and hasattr(u, 'profesional'):
                        info_adicional = u.profesional.especialidad
                        if u.profesional.foto:
                            foto_url = u.profesional.foto.url
                    elif u.perfil.es_paciente() and hasattr(u, 'paciente'):
                        paciente = u.paciente
                        if not u.get_full_name():
                            nombre_completo = f"{paciente.nombre} {paciente.apellido}"
                        info_adicional = f"Tutor: {paciente.nombre_tutor}"
                        if paciente.foto:
                            foto_url = paciente.foto.url
                
                usuarios_con_info.append({
                    'usuario': u,
                    'nombre_completo': nombre_completo,
                    'info_adicional': info_adicional,
                    'foto_url': foto_url
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
    
    if not conversacion.es_participante(usuario):
        return JsonResponse({'error': 'No tienes permiso'}, status=403)
    
    conversacion.marcar_mensajes_como_leidos(usuario)
    
    return JsonResponse({'success': True})


@login_required
def cambiar_tema_chat(request):
    """
    API universal para cambiar el tema del chat.
    Funciona para TODOS los roles: paciente, profesional,
    recepcionista, gerente y superadmin.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)

    usuario = request.user

    # Leer el tema — acepta JSON o form-data
    tema = None
    content_type = request.content_type or ''
    if 'application/json' in content_type:
        try:
            data = json.loads(request.body)
            tema = data.get('tema', '').strip()
        except (json.JSONDecodeError, AttributeError, ValueError):
            return JsonResponse({'error': 'JSON inválido'}, status=400)
    else:
        tema = request.POST.get('tema', '').strip()

    if not tema:
        return JsonResponse({'error': 'Falta el parámetro tema'}, status=400)

    # Validar que el tema sea uno de los permitidos
    temas_validos = ['default', 'arcoiris', 'oceano', 'espacio', 'selva', 'dulces']
    if tema not in temas_validos:
        return JsonResponse({'error': 'Tema no válido'}, status=400)

    # Guardar en el perfil del usuario
    # get_or_create cubre el caso del superadmin que no tiene perfil
    from core.models import PerfilUsuario
    perfil, _ = PerfilUsuario.objects.get_or_create(
        user=usuario,
        defaults={'activo': True}
    )
    perfil.tema_chat = tema
    perfil.save(update_fields=['tema_chat'])
    return JsonResponse({'success': True, 'tema': tema})