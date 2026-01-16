from django.urls import path
from . import views

app_name = 'pacientes'

urlpatterns = [
    path('', views.lista_pacientes, name='lista'),
    path('agregar/', views.agregar_paciente, name='agregar'),  # ✅ NUEVA RUTA
    path('<int:pk>/', views.detalle_paciente, name='detalle'),
    path('mis-sesiones/', views.mis_sesiones, name='mis_sesiones'),
    path('mis-profesionales/', views.mis_profesionales, name='mis_profesionales'),
]