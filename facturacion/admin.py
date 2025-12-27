from django.contrib import admin
from .models import MetodoPago, Pago, CuentaCorriente, Factura

@admin.register(MetodoPago)
class MetodoPagoAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'activo', 'descripcion']
    list_filter = ['activo']
    search_fields = ['nombre', 'descripcion']
    list_editable = ['activo']

@admin.register(Pago)
class PagoAdmin(admin.ModelAdmin):
    list_display = ['numero_recibo', 'fecha_pago', 'paciente', 'monto', 'metodo_pago', 'anulado']
    list_filter = ['fecha_pago', 'metodo_pago', 'anulado']
    search_fields = ['numero_recibo', 'paciente__nombre', 'paciente__apellido']
    readonly_fields = ['numero_recibo', 'fecha_registro', 'registrado_por']
    date_hierarchy = 'fecha_pago'
    
    fieldsets = (
        ('Información Básica', {
            'fields': ('numero_recibo', 'paciente', 'fecha_pago', 'monto', 'metodo_pago')
        }),
        ('Relaciones', {
            'fields': ('sesion', 'proyecto')
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

@admin.register(CuentaCorriente)
class CuentaCorrienteAdmin(admin.ModelAdmin):
    list_display = ['paciente', 'total_consumido', 'total_pagado', 'saldo', 'ultima_actualizacion']
    search_fields = ['paciente__nombre', 'paciente__apellido']
    readonly_fields = ['total_consumido', 'total_pagado', 'saldo', 'ultima_actualizacion']
    list_filter = ['ultima_actualizacion']
    
    actions = ['recalcular_saldos']
    
    def recalcular_saldos(self, request, queryset):
        for cuenta in queryset:
            cuenta.actualizar_saldo()
        self.message_user(request, f'{queryset.count()} cuentas actualizadas correctamente')
    recalcular_saldos.short_description = 'Recalcular saldos seleccionados'

@admin.register(Factura)
class FacturaAdmin(admin.ModelAdmin):
    list_display = ['numero_factura', 'fecha_emision', 'paciente', 'total', 'estado']
    list_filter = ['estado', 'fecha_emision']
    search_fields = ['numero_factura', 'paciente__nombre', 'paciente__apellido', 'nit_ci']
    readonly_fields = ['numero_factura', 'fecha_registro']
    date_hierarchy = 'fecha_emision'