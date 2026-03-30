from django.urls import path
from . import api
from . import views

app_name = 'recordatorios'

urlpatterns = [
    path('citas-manana/', api.citas_manana, name='citas-manana'),
    path('deudas/', api.deudas_pendientes, name='deudas-pendientes'),
    path('logs-whatsapp/', views.logs_whatsapp, name='logs-whatsapp'),
    path('whatsapp-status/', views.whatsapp_status, name='whatsapp-status'),
    path('whatsapp-qr/', views.whatsapp_qr, name='whatsapp-qr'),
    path('whatsapp-reconectar/', views.whatsapp_reconectar, name='whatsapp-reconectar'),
]