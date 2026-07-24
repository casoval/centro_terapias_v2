from django.urls import path
from . import views

app_name = 'documentos'

urlpatterns = [
    path('paciente/<int:paciente_id>/subir/', views.subir_documento, name='subir'),
    path('<int:documento_id>/eliminar/', views.eliminar_documento, name='eliminar'),
    path('popover/', views.popover_documentos, name='popover'),
    path('paciente/<int:paciente_id>/resumen-profesional/', views.resumen_paciente_profesional, name='resumen_paciente_profesional'),
]
