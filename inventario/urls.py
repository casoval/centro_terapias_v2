from django.urls import path
from . import views

app_name = 'inventario'

urlpatterns = [
    path('', views.inventario_general, name='general'),
    path('mi-inventario/', views.mi_inventario, name='mi_inventario'),
    path('titular/<int:titular_id>/', views.detalle_titular, name='detalle_titular'),

    path('agregar/', views.agregar_stock, name='agregar_stock'),
    path('agregar/<int:titular_id>/', views.agregar_stock, name='agregar_stock_a'),
    path('ajustar/<int:titular_id>/<int:item_id>/', views.ajustar_stock, name='ajustar_stock'),

    path('catalogo/', views.catalogo, name='catalogo'),
    path('catalogo/categoria/crear/', views.crear_categoria_item, name='crear_categoria_item'),
    path('catalogo/item/<int:item_id>/editar/', views.editar_item, name='editar_item'),
    path('catalogo/item/<int:item_id>/eliminar/', views.eliminar_item, name='eliminar_item'),

    path('transferencias/', views.lista_transferencias, name='transferencias'),
    path('transferencias/solicitar/', views.solicitar_transferencia, name='solicitar_transferencia'),
    path('transferencias/solicitar/<int:titular_id>/', views.solicitar_transferencia, name='solicitar_transferencia_de'),
    path('transferencias/<int:transferencia_id>/resolver/', views.resolver_transferencia, name='resolver_transferencia'),
]
