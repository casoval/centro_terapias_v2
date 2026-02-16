from django import template
from django.db.models import Q
from django.db import connection

register = template.Library()


@register.simple_tag
def contar_mensajes_no_leidos(usuario):
    """
    ✅ Template tag para contar mensajes no leídos del usuario
    
    Uso en templates:
        {% load chat_tags %}
        {% contar_mensajes_no_leidos user as mensajes_count %}
        {{ mensajes_count }}
    """
    try:
        # ✅ Verificar si las tablas existen antes de consultar
        table_names = connection.introspection.table_names()
        if 'chat_conversacion' not in table_names or 'chat_mensaje' not in table_names:
            return 0
        
        from chat.models import Conversacion, Mensaje
        
        # Obtener todas las conversaciones donde participa
        conversaciones = Conversacion.objects.filter(
            Q(usuario_1=usuario) | Q(usuario_2=usuario),
            activa=True
        )
        
        # Contar mensajes no leídos (que NO sean del usuario actual)
        total_no_leidos = 0
        for conv in conversaciones:
            total_no_leidos += Mensaje.objects.filter(
                conversacion=conv,
                leido=False
            ).exclude(
                remitente=usuario
            ).count()
        
        return total_no_leidos
    
    except Exception as e:
        # Si hay cualquier error, retornar 0 para no romper la página
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"Error al contar mensajes no leídos: {e}")
        return 0


@register.simple_tag
def get_mensajes_no_leidos_conversacion(conversacion, usuario):
    """
    ✅ Template tag para contar mensajes no leídos de una conversación específica
    
    Uso en templates:
        {% load chat_tags %}
        {% get_mensajes_no_leidos_conversacion conversacion user as count %}
        {{ count %}
    """
    try:
        return conversacion.get_mensajes_no_leidos(usuario)
    except Exception:
        return 0