from django.urls import path
from . import views_panel

app_name = 'integracion_misael_kids_panel'

urlpatterns = [
    path('', views_panel.panel_vinculacion, name='panel_vinculacion'),
    path('buscar-ninos/', views_panel.api_buscar_ninos, name='api_buscar_ninos'),
    path('buscar-pacientes/', views_panel.api_buscar_pacientes, name='api_buscar_pacientes'),
    path('vinculados/', views_panel.api_vinculados, name='api_vinculados'),
    path('vincular-existente/', views_panel.vincular_paciente_existente, name='vincular_existente'),
    path('crear-y-vincular/', views_panel.crear_paciente_y_vincular, name='crear_paciente_y_vincular'),
]
