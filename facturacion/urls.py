# facturacion/urls.py

from django.urls import path
from . import views

app_name = 'facturacion'

urlpatterns = [
    # ==================== CUENTAS CORRIENTES ====================
    path('cuentas/', views.lista_cuentas_corrientes, name='cuentas_corrientes'),
    path('cuenta/<int:paciente_id>/', views.detalle_cuenta_corriente, name='detalle_cuenta'),
    
    # ==================== PAGOS ====================
    path('pago/registrar/', views.registrar_pago, name='registrar_pago'),
    path('pago/confirmacion/', views.confirmacion_pago, name='confirmacion_pago'),  # ✅ NUEVA RUTA
    path('pago/<int:pago_id>/anular/', views.anular_pago, name='anular_pago'),
    path('pago/<int:pago_id>/pdf/', views.generar_recibo_pdf, name='generar_recibo_pdf'),
    path('pagos/', views.historial_pagos, name='historial_pagos'),
    path('pagos/masivos/', views.pagos_masivos, name='pagos_masivos'),
    path('pagos/masivos/procesar/', views.procesar_pagos_masivos, name='procesar_pagos_masivos'),
    path('pago/registrar-proyecto/', views.registrar_pago, name='registrar_pago_proyecto'),

    # ==================== SESIONES ====================
    path('sesion/<int:sesion_id>/marcar-pagada/', views.marcar_sesion_pagada, name='marcar_sesion_pagada'),
    
    # ==================== APIs AJAX/HTMX ====================
    path('api/buscar-pacientes/', views.buscar_pacientes_ajax, name='buscar_pacientes_ajax'),
    path('api/sesiones-pendientes/<int:paciente_id>/', views.sesiones_pendientes_ajax, name='sesiones_pendientes_ajax'),
    path('api/sesion/<int:sesion_id>/detalle/', views.api_detalle_sesion, name='api_detalle_sesion'),
    path('api/pago/<int:pago_id>/detalle/', views.api_detalle_pago, name='api_detalle_pago'),
    path('api/proyectos-paciente/<int:paciente_id>/', views.api_proyectos_paciente, name='api_proyectos_paciente'),

    # ==================== REPORTES ====================
    path('reportes/', views.dashboard_reportes, name='dashboard_reportes'),
    path('reportes/paciente/', views.reporte_paciente, name='reporte_paciente'),
    path('reportes/profesional/', views.reporte_profesional, name='reporte_profesional'),
    path('reportes/sucursal/', views.reporte_sucursal, name='reporte_sucursal'),
    path('reportes/financiero/', views.reporte_financiero, name='reporte_financiero'),
    path('reportes/asistencia/', views.reporte_asistencia, name='reporte_asistencia'),
    path('reportes/exportar/', views.exportar_excel, name='exportar_excel'),

    # Limpiar pagos anulados (solo admin)
    path('limpiar-pagos-anulados/', views.limpiar_pagos_anulados, name='limpiar_pagos_anulados'),
]