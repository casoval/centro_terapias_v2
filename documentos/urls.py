from django.urls import path
from . import views

app_name = 'documentos'

urlpatterns = [
    path('paciente/<int:paciente_id>/subir/', views.subir_documento, name='subir'),
    path('<int:documento_id>/eliminar/', views.eliminar_documento, name='eliminar'),
    path('popover/', views.popover_documentos, name='popover'),
    path('paciente/<int:paciente_id>/resumen-profesional/', views.resumen_paciente_profesional, name='resumen_paciente_profesional'),
    path('paciente/<int:paciente_id>/planes-trabajo/nuevo/', views.crear_plan_trabajo, name='crear_plan_trabajo'),
    path('planes-trabajo/<int:plan_id>/editar/', views.editar_plan_trabajo, name='editar_plan_trabajo'),
    path('planes-trabajo/<int:plan_id>/eliminar/', views.eliminar_plan_trabajo, name='eliminar_plan_trabajo'),
]
