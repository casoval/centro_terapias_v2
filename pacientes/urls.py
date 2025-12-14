from django.urls import path
from . import views

app_name = 'pacientes'

urlpatterns = [
    path('', views.lista_pacientes, name='lista'),
    path('<int:pk>/', views.detalle_paciente, name='detalle'),
]