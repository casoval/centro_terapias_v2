from django.urls import path
from . import views

app_name = 'profesionales'

urlpatterns = [
    path('', views.lista_profesionales, name='lista'),
    path('nuevo/', views.agregar_profesional, name='agregar'),
    path('<int:pk>/', views.detalle_profesional, name='detalle'),
    path('mis-pacientes/', views.mis_pacientes, name='mis_pacientes'),
]