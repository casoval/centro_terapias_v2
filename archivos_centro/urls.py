from django.urls import path
from . import views

app_name = 'archivos_centro'

urlpatterns = [
    path('', views.lista_archivos, name='lista'),
    path('subir/', views.subir_archivo, name='subir'),
    path('<int:archivo_id>/editar/', views.editar_archivo, name='editar'),
    path('<int:archivo_id>/eliminar/', views.eliminar_archivo, name='eliminar'),
    path('<int:archivo_id>/descargar/', views.descargar_archivo, name='descargar'),
    path('<int:archivo_id>/permisos/', views.gestionar_permisos, name='permisos'),
    path('categorias/', views.lista_categorias, name='categorias'),
    path('categorias/<int:categoria_id>/eliminar/', views.eliminar_categoria, name='eliminar_categoria'),
]
