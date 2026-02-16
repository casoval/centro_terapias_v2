from django.urls import path
from . import views

app_name = 'chat'

urlpatterns = [
    # Vista principal
    path('', views.lista_conversaciones, name='lista_conversaciones'),
    
    # Chat
    path('conversacion/<int:conversacion_id>/', views.chat_conversacion, name='chat_conversacion'),
    
    # Nuevo mensaje
    path('nuevo/', views.seleccionar_destinatario, name='seleccionar_destinatario'),
    path('iniciar/<int:destinatario_id>/', views.iniciar_conversacion, name='iniciar_conversacion'),
    
    # APIs AJAX
    path('enviar/<int:conversacion_id>/', views.enviar_mensaje, name='enviar_mensaje'),
    path('nuevos/<int:conversacion_id>/', views.obtener_nuevos_mensajes, name='obtener_nuevos_mensajes'),
    path('marcar-leida/<int:conversacion_id>/', views.marcar_conversacion_leida, name='marcar_conversacion_leida'),
]