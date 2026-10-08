from django.urls import path

from . import views

app_name = 'marketing'

urlpatterns = [
    path('', views.panel, name='panel'),

    path('campanas/', views.campana_lista, name='campana_lista'),
    path('campanas/nueva/', views.campana_crear, name='campana_crear'),
    path('campanas/<int:pk>/', views.campana_detalle, name='campana_detalle'),
    path('campanas/<int:pk>/editar/', views.campana_editar, name='campana_editar'),
    path('campanas/<int:pk>/archivar/', views.campana_archivar, name='campana_archivar'),
    path('campanas/<int:pk>/generar-guion/', views.guion_generar, name='guion_generar'),
    path('campanas/<int:pk>/guion-manual/', views.guion_manual, name='guion_manual'),
    path('guiones/<int:pk>/aprobar/', views.guion_aprobar, name='guion_aprobar'),
    path('guiones/<int:pk>/eliminar/', views.guion_eliminar, name='guion_eliminar'),

    path('fichas/', views.ficha_lista, name='ficha_lista'),
    path('fichas/nueva/', views.ficha_crear, name='ficha_crear'),
    path('fichas/sincronizar/', views.ficha_sincronizar, name='ficha_sincronizar'),
    path('fichas/<int:pk>/editar/', views.ficha_editar, name='ficha_editar'),
    path('fichas/<int:pk>/aprobar/', views.ficha_aprobar, name='ficha_aprobar'),

    path('marcas/', views.marca_lista, name='marca_lista'),
    path('marcas/<int:pk>/editar/', views.marca_editar, name='marca_editar'),

    path('activos/', views.activo_lista, name='activo_lista'),
    path('activos/subir/', views.activo_subir, name='activo_subir'),
    path('activos/<int:pk>/activar/', views.activo_toggle, name='activo_toggle'),

    path('configuracion/', views.config_editar, name='config'),
]
