# recordatorios/urls.py
from django.urls import path
from . import api

urlpatterns = [
    path('citas-manana/', api.citas_manana, name='citas-manana'),
    path('deudas/', api.deudas_pendientes, name='deudas-pendientes'),
]