from django.contrib import admin
from .models import Sesion, Proyecto


@admin.register(Proyecto)
class ProyectoAdmin(admin.ModelAdmin):
    list_display = [
        'codigo',
        'nombre',
        'paciente',
        'tipo',
        'estado',
        'costo_total',
        'total_pagado',
        'saldo_pendiente',
        'fecha_inicio',
        'duracion_dias'
    ]
    list_filter = [
        'tipo',
        'estado',
        'fecha_inicio',
        'sucursal',
        'profesional_responsable'
    ]
    search_fields = [
        'codigo',
        'nombre',
        'paciente__nombre',
        'paciente__apellido',
        'descripcion'
    ]
    date_hierarchy = 'fecha_inicio'
    
    fieldsets = (
        ('Información Principal', {
            'fields': (
                'codigo',
                'nombre',
                'tipo',
                'paciente',
                'servicio_base'
            )
        }),
        ('Responsables y Ubicación', {
            'fields': (
                'profesional_responsable',
                'sucursal'
            )
        }),
        ('Fechas', {
            'fields': (
                'fecha_inicio',
                'fecha_fin_estimada',
                'fecha_fin_real'
            )
        }),
        ('Costos', {
            'fields': (
                'costo_total',
            )
        }),
        ('Estado', {
            'fields': (
                'estado',
            )
        }),
        ('Descripción', {
            'fields': (
                'descripcion',
                'observaciones'
            )
        }),
        ('Control', {
            'fields': (
                'creado_por',
                'fecha_creacion',
                'modificado_por',
                'fecha_modificacion'
            ),
            'classes': ('collapse',)
        }),
    )
    
    readonly_fields = [
        'codigo',
        'fecha_creacion',
        'fecha_modificacion'
    ]
    
    def save_model(self, request, obj, form, change):
        if not change:
            obj.creado_por = request.user
        obj.modificado_por = request.user
        super().save_model(request, obj, form, change)


@admin.register(Sesion)
class SesionAdmin(admin.ModelAdmin):
    list_display = [
        'fecha', 
        'hora_inicio', 
        'paciente', 
        'servicio', 
        'profesional', 
        'estado', 
        'monto_cobrado',
        'estado_pago_display',
        'proyecto'
    ]
    list_filter = [
        'estado', 
        'fecha', 
        'profesional', 
        'servicio',
        'proyecto'
    ]
    search_fields = [
        'paciente__nombre',
        'paciente__apellido',
        'profesional__nombre',
        'profesional__apellido',
        'observaciones',
        'proyecto__codigo',
        'proyecto__nombre'
    ]
    date_hierarchy = 'fecha'
    
    fieldsets = (
        ('Información Principal', {
            'fields': (
                'paciente',
                'servicio', 
                'profesional',
                'sucursal',
                'proyecto'
            )
        }),
        ('Fecha y Hora', {
            'fields': (
                'fecha',
                'hora_inicio',
                'hora_fin',
                'duracion_minutos'
            )
        }),
        ('Estado', {
            'fields': (
                'estado',
            )
        }),
        ('Detalles de Retraso', {
            'fields': (
                'hora_real_inicio',
                'minutos_retraso'
            ),
            'classes': ('collapse',)
        }),
        ('Reprogramación', {
            'fields': (
                'fecha_reprogramada',
                'hora_reprogramada',
                'motivo_reprogramacion',
                'reprogramacion_realizada'
            ),
            'classes': ('collapse',)
        }),
        ('Cobro', {
            'fields': (
                'monto_cobrado',
            ),
            'description': 'El estado de pago se calcula automáticamente desde la tabla Pago'
        }),
        ('Notas', {
            'fields': (
                'observaciones',
                'notas_sesion'
            ),
            'classes': ('collapse',)
        }),
        ('Control', {
            'fields': (
                'creada_por',
                'fecha_creacion',
                'modificada_por',
                'fecha_modificacion'
            ),
            'classes': ('collapse',)
        }),
    )
    
    readonly_fields = [
        'fecha_creacion',
        'fecha_modificacion'
    ]
    
    def estado_pago_display(self, obj):
        """Mostrar estado de pago con colores"""
        if not obj.requiere_pago:
            return '🎁 No aplica'
        elif obj.pagado:
            return f'✅ Pagado (Bs. {obj.total_pagado})'
        elif obj.total_pagado > 0:
            return f'⚠️ Parcial (Bs. {obj.total_pagado}/{obj.monto_cobrado})'
        else:
            return f'❌ Pendiente (Bs. {obj.monto_cobrado})'
    
    estado_pago_display.short_description = 'Estado de Pago'
    
    def save_model(self, request, obj, form, change):
        if not change:
            obj.creada_por = request.user
        obj.modificada_por = request.user
        super().save_model(request, obj, form, change)