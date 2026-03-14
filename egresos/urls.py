# egresos/urls.py

from django.urls import path
from . import views

app_name = 'egresos'

urlpatterns = [
    # ── Listado y gestión de egresos ──────────────────────────────────────────
    path('',                            views.lista_egresos,         name='lista_egresos'),
    path('nuevo/',                      views.registrar_egreso,      name='registrar_egreso'),
    path('<int:egreso_id>/',            views.detalle_egreso,        name='detalle_egreso'),
    path('<int:egreso_id>/anular/',     views.anular_egreso,         name='anular_egreso'),

    # ── PDF ───────────────────────────────────────────────────────────────────
    path('<int:egreso_id>/pdf/',        views.generar_egreso_pdf,    name='egreso_pdf'),

    # ── Dashboard financiero ──────────────────────────────────────────────────
    path('dashboard/',                  views.dashboard_financiero,  name='dashboard_financiero'),

    # ── API JSON ──────────────────────────────────────────────────────────────
    path('api/resumen/',                views.api_resumen_mes,       name='api_resumen_mes'),
    path('api/egresos/',                views.api_egresos_mes,       name='api_egresos_mes'),

    # ── Ingresos Adicionales ──────────────────────────────────────────────────
    path('ingresos/',                  views.lista_ingresos_adicionales,      name='lista_ingresos_adicionales'),
    path('ingresos/nuevo/',            views.registrar_ingreso_adicional,     name='registrar_ingreso_adicional'),
    path('ingresos/<int:ingreso_id>/', views.detalle_ingreso_adicional,       name='detalle_ingreso_adicional'),
    path('ingresos/<int:ingreso_id>/pdf/', views.generar_ingreso_adicional_pdf, name='ingreso_adicional_pdf'),
    path('ingresos/<int:ingreso_id>/anular/', views.anular_ingreso_adicional, name='anular_ingreso_adicional'),

    # ── Liquidación de honorarios ─────────────────────────────────────────────
    path('liquidar-honorarios/',          views.liquidar_honorarios,   name='liquidar_honorarios'),

    # ── Categorías ────────────────────────────────────────────────────────────
    path('categorias/',                 views.lista_categorias,      name='lista_categorias'),
    path('categorias/nueva/',           views.crear_categoria,       name='crear_categoria'),
    path('categorias/<int:categoria_id>/editar/', views.editar_categoria, name='editar_categoria'),

    # ── Proveedores ───────────────────────────────────────────────────────────
    path('proveedores/',                views.lista_proveedores,     name='lista_proveedores'),
    path('proveedores/nuevo/',          views.crear_proveedor,       name='crear_proveedor'),
    path('proveedores/<int:proveedor_id>/editar/', views.editar_proveedor, name='editar_proveedor'),
]