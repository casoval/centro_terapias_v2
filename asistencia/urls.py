from django.urls import path
from . import views

app_name = 'asistencia'

urlpatterns = [
    # ── Panel administrador ──────────────────────────────────────────────────
    path('admin/', views.panel_admin, name='panel_admin'),
    path('admin/marcar/<int:user_pk>/', views.marcar_admin, name='marcar_admin'),
    path('admin/zonas/', views.zonas_gps, name='zonas_gps'),
    path('admin/zonas/<int:pk>/editar/', views.editar_zona, name='editar_zona'),
    path('admin/horarios/', views.horarios, name='horarios'),
    path('admin/horarios/<int:zona_pk>/editar/', views.editar_horario_predeterminado, name='editar_horario'),
    path('admin/asignaciones/', views.asignaciones, name='asignaciones'),
    path('admin/asignaciones/<int:pk>/editar/', views.editar_config, name='editar_config'),
    path('admin/asignaciones/<int:pk>/eliminar/', views.eliminar_config, name='eliminar_config'),
    path('admin/horarios/fechas/', views.fechas_especiales, name='fechas_especiales'),
    path('admin/horarios/fechas/<int:pk>/eliminar/', views.eliminar_fecha_especial, name='eliminar_fecha_especial'),
    path('admin/enrolamiento/', views.enrolamiento, name='enrolamiento'),
    path('admin/enrolamiento/<int:enrolamiento_pk>/desbloquear/', views.desbloquear_enrolamiento, name='desbloquear'),
    path('admin/permisos/', views.permisos, name='permisos'),

    # ── Panel profesional ────────────────────────────────────────────────────
    path('marcar/', views.marcar_asistencia, name='marcar'),
    path('mi-asistencia/', views.mi_asistencia, name='mi_asistencia'),
    path('enrolamiento/', views.enrolamiento_facial, name='enrolamiento_facial'),
    path('mi-asistencia/<int:pk>/observacion/', views.editar_observacion, name='editar_observacion'),
]
