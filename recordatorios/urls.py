from django.urls import path
from . import api, views

app_name = 'recordatorios'

urlpatterns = [
    path('citas-manana/', api.citas_manana, name='citas-manana'),
    path('sesiones-proximas/', api.sesiones_proximas, name='sesiones-proximas'),
    path('mensualidades-semana/', api.mensualidades_semana, name='mensualidades-semana'),
    path('deudas/', api.deudas_pendientes, name='deudas-pendientes'),
    path('logs-whatsapp/', views.logs_whatsapp, name='logs-whatsapp'),
    path('whatsapp-status/', views.whatsapp_status, name='whatsapp-status'),
    path('whatsapp-qr/', views.whatsapp_qr, name='whatsapp-qr'),
    path('whatsapp-reconectar/', views.whatsapp_reconectar, name='whatsapp-reconectar'),
    path('whatsapp-historial/', views.whatsapp_historial, name='whatsapp-historial'),
    path('whatsapp-envio-masivo/', views.whatsapp_envio_masivo, name='whatsapp-envio-masivo'),
]