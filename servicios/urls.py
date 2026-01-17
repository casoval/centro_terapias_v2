from django.urls import path
from . import views

app_name = 'servicios'

urlpatterns = [
    path('tipos/', views.lista_servicios, name='lista_servicios'),
    path('tipos/nuevo/', views.agregar_servicio, name='agregar_servicio'),
    path('tipos/<int:pk>/', views.detalle_servicio, name='detalle_servicio'),
    path('sucursales/', views.lista_sucursales, name='lista_sucursales'),
    path('sucursales/<int:pk>/', views.detalle_sucursal, name='detalle_sucursal'),
    path('sucursales/nueva/', views.agregar_sucursal, name='agregar_sucursal'),
]