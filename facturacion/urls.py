# facturacion/urls.py

from django.urls import path
from . import views

app_name = 'facturacion'

urlpatterns = [
    # ==================== CUENTAS CORRIENTES ====================
    path('cuentas/', views.lista_cuentas_corrientes, name='cuentas_corrientes'),
    path('cuenta/<int:paciente_id>/', views.detalle_cuenta_corriente, name='detalle_cuenta'),
    
    # ==================== AJAX ENDPOINTS ====================
    path('api/estadisticas/', views.cargar_estadisticas_ajax, name='cargar_estadisticas_ajax'),
    path('api/cuenta/<int:paciente_id>/detalle/', views.detalle_cuenta_ajax, name='detalle_cuenta_ajax'),
    path('api/estadisticas-pagos/', views.cargar_estadisticas_pagos_ajax, name='cargar_estadisticas_pagos_ajax'),
    
    # ==================== PAGOS ====================
    path('pago/registrar/', views.registrar_pago, name='registrar_pago'),
    path('pago/confirmacion/', views.confirmacion_pago, name='confirmacion_pago'),
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
    path('api/mensualidades-paciente/<int:paciente_id>/', views.api_mensualidades_paciente, name='api_mensualidades_paciente'),  # ✅ NUEVO
    
    # ==================== REPORTES ====================
    path('reportes/', views.dashboard_reportes, name='dashboard_reportes'),
    path('reportes/paciente/', views.reporte_paciente, name='reporte_paciente'),
    path('reportes/profesional/', views.reporte_profesional, name='reporte_profesional'),
    path('reportes/sucursal/', views.reporte_sucursal, name='reporte_sucursal'),
    path('reportes/financiero/', views.reporte_financiero, name='reporte_financiero'),
    path('reportes/asistencia/', views.reporte_asistencia, name='reporte_asistencia'),
    path('reportes/exportar/', views.exportar_excel, name='exportar_excel'),

    # ==================== DEVOLUCIONES ====================
    path('devoluciones/registrar/', views.registrar_devolucion, name='registrar_devolucion'),
    path('devoluciones/confirmacion/<int:devolucion_id>/', views.confirmacion_devolucion, name='confirmacion_devolucion'),

    path('pago/<int:pago_id>/anular/', views.anular_pago, name='anular_pago'),
    path('devolucion/<int:devolucion_id>/pdf/', views.generar_devolucion_pdf, name='generar_devolucion_pdf'),

    # APIs para cargar información de devoluciones
    path('api/credito-disponible/<int:paciente_id>/', views.api_credito_disponible, name='api_credito_disponible'),
    path('api/disponible-devolver-proyecto/<int:proyecto_id>/', views.api_disponible_devolver_proyecto, name='api_disponible_devolver_proyecto'),
    path('api/disponible-devolver-mensualidad/<int:mensualidad_id>/', views.api_disponible_devolver_mensualidad, name='api_disponible_devolver_mensualidad'),

    # ==================== ADMINISTRACIÓN ====================
    # Limpiar pagos anulados (solo admin)
    path('limpiar-pagos-anulados/', views.limpiar_pagos_anulados, name='limpiar_pagos_anulados'),
    
    # ✅ NUEVO: Gestión de cache de recibos (solo admin)
    path('cache/limpiar-recibos/', views.limpiar_cache_recibos, name='limpiar_cache_recibos'),
    path('cache/estadisticas/', views.estadisticas_cache_recibos, name='estadisticas_cache_recibos'),

    # ==================== VISTAS PARA PACIENTES ====================
    path('mi-cuenta/', views.mi_cuenta, name='mi_cuenta'),
    path('mis-pagos/', views.mis_pagos, name='mis_pagos'),
    path('pago/<int:pago_id>/ver/', views.detalle_pago_paciente, name='detalle_pago_paciente'),

    path('sesion/<int:sesion_id>/detalle-partial/', 
         views.detalle_sesion_partial, 
         name='detalle_sesion_partial'),
    
    path('pago/<int:pago_id>/detalle-partial/', 
         views.detalle_pago_partial, 
         name='detalle_pago_partial'),

    # ==================== PANEL DE RECÁLCULO (ADMIN) ====================
    path('admin/panel-recalculo/', 
         views.panel_recalcular_cuentas, 
         name='panel_recalcular_cuentas'),
    
    path('admin/recalcular-todas/', 
         views.recalcular_todas_cuentas, 
         name='recalcular_todas_cuentas'),
    
    path('admin/recalcular-cuenta/<int:paciente_id>/', 
         views.recalcular_cuenta_individual, 
         name='recalcular_cuenta_individual'),
    
    # API AJAX para recálculo
    path('api/recalcular-cuenta/<int:paciente_id>/', 
         views.api_recalcular_cuenta, 
         name='api_recalcular_cuenta'),
    
    path('api/estado-recalculo/', 
         views.api_estado_recalculo, 
         name='api_estado_recalculo'),
]