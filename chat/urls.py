from django.urls import path
from . import views
from . import views_ia  # ✅ NUEVO: Agente IA

app_name = 'chat'

urlpatterns = [
    # Vistas principales
    path('', views.lista_conversaciones, name='lista_conversaciones'),
    path('nueva/', views.seleccionar_destinatario, name='seleccionar_destinatario'),
    path('iniciar/<int:destinatario_id>/', views.iniciar_conversacion, name='iniciar_conversacion'),
    path('<int:conversacion_id>/', views.chat_conversacion, name='chat_conversacion'),

    # APIs AJAX
    path('enviar/<int:conversacion_id>/', views.enviar_mensaje, name='enviar_mensaje'),
    path('nuevos/<int:conversacion_id>/', views.obtener_nuevos_mensajes, name='obtener_nuevos_mensajes'),
    path('leida/<int:conversacion_id>/', views.marcar_conversacion_leida, name='marcar_conversacion_leida'),

    # Endpoint universal para cambiar tema (todos los roles)
    path('cambiar-tema/', views.cambiar_tema_chat, name='cambiar_tema_chat'),

    # ✅ NUEVO: Agente IA
    path('ia/', views_ia.chat_con_ia, name='chat_con_ia'),
    path('ia/enviar/<int:conversacion_id>/', views_ia.enviar_mensaje_ia, name='enviar_mensaje_ia'),
]