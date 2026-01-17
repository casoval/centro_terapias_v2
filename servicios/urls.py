from django.urls import path
from . import views

app_name = 'servicios'

urlpatterns = [
    # Servicios/Tipos
    path('tipos/', views.lista_servicios, name='lista_servicios'),
    path('tipos/nuevo/', views.agregar_servicio, name='agregar_servicio'),
    path('tipos/<int:pk>/', views.detalle_servicio, name='detalle_servicio'),
    path('tipos/<int:pk>/editar/', views.editar_servicio, name='editar_servicio'),
    path('tipos/<int:pk>/eliminar/', views.eliminar_servicio, name='eliminar_servicio'),
    
    # Sucursales
    path('sucursales/', views.lista_sucursales, name='lista_sucursales'),
    path('sucursales/nueva/', views.agregar_sucursal, name='agregar_sucursal'),
    path('sucursales/<int:pk>/', views.detalle_sucursal, name='detalle_sucursal'),
    path('sucursales/<int:pk>/editar/', views.editar_sucursal, name='editar_sucursal'),
    path('sucursales/<int:pk>/eliminar/', views.eliminar_sucursal, name='eliminar_sucursal'),
]