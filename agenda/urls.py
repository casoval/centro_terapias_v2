from django.urls import path
from . import views

app_name = 'agenda'

urlpatterns = [
    # Vistas principales
    path('', views.calendario, name='calendario'),
    path('agendar-recurrente/', views.agendar_recurrente, name='agendar_recurrente'),
    
    # APIs HTMX
    path('api/servicios-paciente/', views.cargar_servicios_paciente, name='servicios_paciente'),
    path('api/vista-previa/', views.vista_previa_recurrente, name='vista_previa'),
    path('api/editar/<int:sesion_id>/', views.editar_sesion, name='editar_sesion'),
    path('api/validar-horario/', views.validar_horario, name='validar_horario'),
]