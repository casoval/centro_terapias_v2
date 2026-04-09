from django.urls import path
from agente import views

app_name = 'agente'

urlpatterns = [
    # Panel principal
    path('conversaciones/', views.panel_conversaciones, name='conversaciones'),

    # Webhooks desde el bot Node.js (sin login)
    path('whatsapp-entrante/',  views.whatsapp_entrante, name='whatsapp-entrante'),
    path('staff-respondio/',    views.staff_respondio,   name='staff-respondio'),

    # API para el panel web
    path('api/conversaciones/',             views.api_conversaciones,     name='api-conversaciones'),
    path('api/historial/<str:telefono>/',   views.api_historial_telefono, name='api-historial'),
    path('api/toggle-modo-humano/',         views.toggle_modo_humano,     name='toggle-modo-humano'),
    path('api/toggle-ia-sucursal/',         views.toggle_ia_sucursal,     name='toggle-ia-sucursal'),
    path('api/estado-sucursales/',          views.api_estado_sucursales,  name='api-estado-sucursales'),
    path('api/enviar-manual/',              views.api_enviar_manual,      name='api-enviar-manual'),
]