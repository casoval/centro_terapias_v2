from django.urls import path
from . import views

app_name = 'facturacion'

urlpatterns = [
    # Cuentas Corrientes
    path('cuentas/', views.lista_cuentas_corrientes, name='cuentas_corrientes'),
    path('cuenta/<int:paciente_id>/', views.detalle_cuenta_corriente, name='detalle_cuenta'),
    
    # Pagos
    path('registrar-pago/', views.registrar_pago, name='registrar_pago'),
    path('pago/<int:sesion_id>/marcar-pagada/', views.marcar_sesion_pagada, name='marcar_pagada'),
    
    # Pagos Masivos
    path('pagos-masivos/', views.pagos_masivos, name='pagos_masivos'),
    path('procesar-pagos-masivos/', views.procesar_pagos_masivos, name='procesar_pagos_masivos'),
    
    # Historial de Pagos
    path('historial-pagos/', views.historial_pagos, name='historial_pagos'),
    
    # Recibos y Anulaciones
    path('pago/<int:pago_id>/recibo/', views.generar_recibo_pdf, name='recibo_pdf'),
    path('pago/<int:pago_id>/anular/', views.anular_pago, name='anular_pago'),
    
    # Reportes
    path('reportes/', views.dashboard_reportes, name='dashboard_reportes'),
    path('reportes/paciente/', views.reporte_paciente, name='reporte_paciente'),
    path('reportes/profesional/', views.reporte_profesional, name='reporte_profesional'),
    path('reportes/sucursal/', views.reporte_sucursal, name='reporte_sucursal'),
    path('reportes/financiero/', views.reporte_financiero, name='reporte_financiero'),
    path('reportes/asistencia/', views.reporte_asistencia, name='reporte_asistencia'),
    
    # Exportar
    path('reportes/exportar-excel/', views.exportar_excel, name='exportar_excel'),
    
    # HTMX - APIs internas
    path('api/buscar-pacientes/', views.buscar_pacientes_ajax, name='buscar_pacientes'),
    path('api/sesiones-pendientes/<int:paciente_id>/', views.sesiones_pendientes_ajax, name='sesiones_pendientes'),
]