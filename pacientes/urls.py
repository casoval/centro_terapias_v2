from django.urls import path
from . import views

app_name = 'pacientes'

urlpatterns = [
    path('', views.lista_pacientes, name='lista'),
    path('agregar/', views.agregar_paciente, name='agregar'),
    path('<int:pk>/', views.detalle_paciente, name='detalle'),
    path('<int:pk>/editar/', views.editar_paciente, name='editar'),  # ✅ NUEVA RUTA
    path('<int:pk>/eliminar/', views.eliminar_paciente, name='eliminar'),  # ✅ NUEVA RUTA
    
    # ✅ NUEVA: Vista completa de sesiones
    path('<int:pk>/sesiones/', views.detalle_sesiones_completo, name='detalle_sesiones'),

    path('mis-sesiones/', views.mis_sesiones, name='mis_sesiones'),
    path('mis-profesionales/', views.mis_profesionales, name='mis_profesionales'),

    path('api/lista/', views.api_lista_pacientes, name='api_lista_pacientes'),
]