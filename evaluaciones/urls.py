"""
URLs de la app evaluaciones.
Incluir en config/urls.py:
    path('evaluaciones/', include('evaluaciones.urls', namespace='evaluaciones')),
"""

from django.urls import path
from . import views

app_name = 'evaluaciones'

urlpatterns = [
    # ── Dashboard ─────────────────────────────────────────────────
    path('', views.dashboard_evaluaciones, name='dashboard'),
    path('referencia/', views.referencia_puntuaciones, name='referencia'),

    # ── ADOS-2 ────────────────────────────────────────────────────
    path('ados2/', views.ados2_lista, name='ados2_lista'),
    path('ados2/nueva/', views.ados2_crear, name='ados2_crear'),
    path('ados2/<int:pk>/', views.ados2_detalle, name='ados2_detalle'),
    path('ados2/<int:pk>/items/', views.ados2_items, name='ados2_items'),
    path('ados2/<int:pk>/editar/', views.ados2_editar, name='ados2_editar'),
    path('ados2/<int:pk>/eliminar/', views.ados2_eliminar, name='ados2_eliminar'),
    path('ados2/<int:pk>/seccion/<str:seccion>/',
         views.ados2_guardar_seccion, name='ados2_guardar_seccion'),

    # ── ADI-R ─────────────────────────────────────────────────────
    path('adir/', views.adir_lista, name='adir_lista'),
    path('adir/nueva/', views.adir_crear, name='adir_crear'),
    path('adir/<int:pk>/', views.adir_detalle, name='adir_detalle'),
    path('adir/<int:pk>/items/', views.adir_items, name='adir_items'),
    path('adir/<int:pk>/eliminar/', views.adir_eliminar, name='adir_eliminar'),
    path('adir/<int:pk>/seccion/<str:seccion>/',
         views.adir_guardar_seccion, name='adir_guardar_seccion'),

    # ── Informes ──────────────────────────────────────────────────
    path('informes/', views.informe_lista, name='informe_lista'),
    path('informes/nuevo/', views.informe_crear, name='informe_crear'),
    path('informes/<int:pk>/', views.informe_detalle, name='informe_detalle'),
    path('informes/<int:pk>/editar/', views.informe_editar, name='informe_editar'),
    path('informes/<int:pk>/eliminar/', views.informe_eliminar, name='informe_eliminar'),
    path('informes/<int:pk>/pdf/', views.informe_pdf, name='informe_pdf'),

    # ── HTMX Utilities ───────────────────────────────────────────
    path('htmx/buscar-paciente/', views.htmx_buscar_paciente, name='htmx_buscar_paciente'),
    path('htmx/edad-paciente/', views.htmx_edad_paciente, name='htmx_edad_paciente'),
    path('htmx/evaluaciones-paciente/', views.htmx_evaluaciones_paciente, name='htmx_evaluaciones_paciente'),
]