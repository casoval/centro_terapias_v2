from django.urls import path
from . import views

app_name = 'profesionales'

urlpatterns = [
    path('', views.lista_profesionales, name='lista'),
    path('nuevo/', views.agregar_profesional, name='agregar'),
    path('<int:pk>/', views.detalle_profesional, name='detalle'),
    path('<int:pk>/editar/', views.editar_profesional, name='editar'),
    path('<int:pk>/eliminar/', views.eliminar_profesional, name='eliminar'),
    path('<int:pk>/reactivar/', views.reactivar_profesional, name='reactivar'),
    path('mis-pacientes/', views.mis_pacientes, name='mis_pacientes'),
    path('mis-pacientes/<int:paciente_id>/subir-foto/', views.subir_foto_paciente, name='subir_foto_paciente'),
]