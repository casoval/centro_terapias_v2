from django.urls import path

from . import views

app_name = 'avisos'

urlpatterns = [
    path('', views.lista, name='lista'),
    path('popup/', views.popup_data, name='popup_data'),
    path('nuevo/', views.crear, name='crear'),
    path('<int:pk>/leido/', views.marcar_leido, name='leido'),
    path('<int:pk>/editar/', views.editar, name='editar'),
    path('<int:pk>/eliminar/', views.eliminar, name='eliminar'),
    path('<int:pk>/lecturas/', views.lecturas, name='lecturas'),
]
