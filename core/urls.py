from django.urls import path
from . import views

app_name = 'core'

urlpatterns = [
    path('', views.landing, name='landing'),          # ← solo landing
    path('dashboard/', views.dashboard, name='dashboard'),  # ← ruta propia
    path('login/', views.CustomLoginView.as_view(), name='login'),
    path('logout/', views.logout_view, name='logout'),

    # Gestión de Usuarios
    path('usuarios/', views.lista_usuarios, name='lista_usuarios'),
    path('usuarios/nuevo/', views.agregar_usuario, name='agregar_usuario'),
    path('usuarios/pacientes/masivo/', views.crear_usuarios_pacientes_masivo, name='crear_usuarios_pacientes_masivo'),
    path('usuarios/<int:pk>/editar/', views.editar_usuario, name='editar_usuario'),
    path('usuarios/<int:pk>/eliminar/', views.eliminar_usuario, name='eliminar_usuario'),

    path('guardar-tema/', views.guardar_tema, name='guardar_tema'),
]