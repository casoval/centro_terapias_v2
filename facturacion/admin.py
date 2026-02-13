from django.contrib import admin
from .models import MetodoPago, Pago, DetallePagoMasivo, CuentaCorriente, Factura, Devolucion

@admin.register(MetodoPago)
class MetodoPagoAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'activo', 'descripcion']
    list_filter = ['activo']
    search_fields = ['nombre', 'descripcion']
    list_editable = ['activo']


class DetallePagoMasivoInline(admin.TabularInline):
    """Inline para mostrar detalles de pagos masivos"""
    model = DetallePagoMasivo
    extra = 0
    readonly_fields = ['tipo', 'sesion', 'proyecto', 'mensualidad', 'monto', 'concepto']
    can_delete = False
    
    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Pago)
class PagoAdmin(admin.ModelAdmin):
    list_display = ['numero_recibo', 'fecha_pago', 'paciente', 'monto', 'metodo_pago', 'anulado', 'es_pago_masivo_display']
    list_filter = ['fecha_pago', 'metodo_pago', 'anulado']
    search_fields = ['numero_recibo', 'paciente__nombre', 'paciente__apellido']
    readonly_fields = ['numero_recibo', 'fecha_registro', 'registrado_por']
    date_hierarchy = 'fecha_pago'
    inlines = [DetallePagoMasivoInline]
    
    def es_pago_masivo_display(self, obj):
        """Muestra si es pago masivo con el número de ítems"""
        if obj.es_pago_masivo:
            return f"✅ Sí ({obj.cantidad_detalles} ítems)"
        return "❌ No"
    es_pago_masivo_display.short_description = 'Pago Masivo'
    
    fieldsets = (
        ('Información Básica', {
            'fields': ('numero_recibo', 'paciente', 'fecha_pago', 'monto', 'metodo_pago')
        }),
        ('Relaciones', {
            'fields': ('sesion', 'proyecto', 'mensualidad')
        }),
        ('Detalles', {
            'fields': ('concepto', 'numero_transaccion', 'observaciones')
        }),
        ('Control', {
            'fields': ('registrado_por', 'fecha_registro')
        }),
        ('Anulación', {
            'fields': ('anulado', 'motivo_anulacion', 'anulado_por', 'fecha_anulacion'),
            'classes': ('collapse',)
        }),
    )

@admin.register(Devolucion)
class DevolucionAdmin(admin.ModelAdmin):
    list_display = [
        'numero_devolucion',
        'fecha_devolucion',
        'paciente',
        'monto',
        'proyecto',
        'mensualidad',
        'metodo_devolucion'
    ]
    list_filter = ['fecha_devolucion', 'metodo_devolucion']
    search_fields = [
        'numero_devolucion',
        'paciente__nombre',
        'paciente__apellido',
        'motivo'
    ]
    readonly_fields = ['numero_devolucion', 'fecha_registro', 'registrado_por']
    date_hierarchy = 'fecha_devolucion'
    
    fieldsets = (
        ('Información Básica', {
            'fields': (
                'numero_devolucion',
                'paciente',
                'fecha_devolucion',
                'monto',
                'metodo_devolucion'
            )
        }),
        ('Relaciones', {
            'fields': ('proyecto', 'mensualidad'),
            'description': 'Opcional: indica de qué proyecto o mensualidad proviene la devolución'
        }),
        ('Detalles', {
            'fields': ('motivo', 'numero_transaccion', 'observaciones')
        }),
        ('Control', {
            'fields': ('registrado_por', 'fecha_registro'),
            'classes': ('collapse',)
        }),
    )

@admin.register(CuentaCorriente)
class CuentaCorrienteAdmin(admin.ModelAdmin):
    list_display = [
        'paciente', 
        'total_consumido_actual', 
        'total_pagado', 
        'saldo_actual',
        'saldo_real',
        'ultima_actualizacion'
    ]
    search_fields = ['paciente__nombre', 'paciente__apellido']
    readonly_fields = [
        # Perspectiva Real
        'total_sesiones_normales_real',
        'total_sesiones_programadas',
        'total_mensualidades',
        'total_proyectos_real',
        'total_proyectos_planificados',
        'total_consumido_real',
        
        # Perspectiva Actual
        'total_consumido_actual',
        
        # Pagos
        'pagos_sesiones',
        'pagos_mensualidades',
        'pagos_proyectos',
        'pagos_adelantados',
        
        # Desglose de crédito (validación)
        'pagos_sin_asignar',
        'pagos_sesiones_programadas',
        'pagos_proyectos_planificados',
        'uso_credito',
        
        'total_devoluciones',
        'total_pagado',
        
        # Saldos
        'saldo_real',
        'saldo_actual',
        
        # Contadores
        'num_sesiones_realizadas_pendientes',
        'num_sesiones_programadas_pendientes',
        'num_mensualidades_activas',
        'num_proyectos_activos',
        
        # Control
        'ultima_actualizacion'
    ]
    list_filter = ['ultima_actualizacion']
    
    fieldsets = (
        ('Paciente', {
            'fields': ('paciente',)
        }),
        ('Consumido Real (con compromisos futuros)', {
            'fields': (
                'total_sesiones_normales_real',
                'total_sesiones_programadas',
                'total_mensualidades',
                'total_proyectos_real',
                'total_proyectos_planificados',
                'total_consumido_real',
            ),
            'classes': ('collapse',)
        }),
        ('Consumido Actual (solo ocurrido)', {
            'fields': (
                'total_consumido_actual',
            )
        }),
        ('Pagos', {
            'fields': (
                'pagos_sesiones',
                'pagos_mensualidades',
                'pagos_proyectos',
                'pagos_adelantados',
                'total_devoluciones',
                'total_pagado',
            ),
            'classes': ('collapse',)
        }),
        ('Desglose Crédito Disponible (Validación)', {
            'fields': (
                'pagos_sin_asignar',
                'pagos_sesiones_programadas',
                'pagos_proyectos_planificados',
                'uso_credito',
            ),
            'classes': ('collapse',)
        }),
        ('Saldos', {
            'fields': (
                'saldo_actual',
                'saldo_real',
            )
        }),
        ('Contadores', {
            'fields': (
                'num_sesiones_realizadas_pendientes',
                'num_sesiones_programadas_pendientes',
                'num_mensualidades_activas',
                'num_proyectos_activos',
            ),
            'classes': ('collapse',)
        }),
        ('Control', {
            'fields': ('ultima_actualizacion',)
        }),
    )
    
    actions = ['recalcular_saldos']
    
    def recalcular_saldos(self, request, queryset):
        """Recalcula los saldos de las cuentas seleccionadas"""
        from facturacion.services import AccountService
        
        for cuenta in queryset:
            AccountService.update_balance(cuenta.paciente)
        
        self.message_user(request, f'{queryset.count()} cuentas actualizadas correctamente')
    recalcular_saldos.short_description = 'Recalcular saldos seleccionados'

@admin.register(Factura)
class FacturaAdmin(admin.ModelAdmin):
    list_display = ['numero_factura', 'fecha_emision', 'paciente', 'total', 'estado']
    list_filter = ['estado', 'fecha_emision']
    search_fields = ['numero_factura', 'paciente__nombre', 'paciente__apellido', 'nit_ci']
    readonly_fields = ['numero_factura', 'fecha_registro']
    date_hierarchy = 'fecha_emision'
