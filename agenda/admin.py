from django.contrib import admin
from .models import Sesion


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
        'pagado'
    ]
    list_filter = [
        'estado', 
        'pagado', 
        'fecha', 
        'profesional', 
        'servicio'
    ]
    search_fields = [
        'paciente__nombre',
        'paciente__apellido',
        'profesional__nombre',
        'profesional__apellido',
        'observaciones'
    ]
    date_hierarchy = 'fecha'
    
    fieldsets = (
        ('Información Principal', {
            'fields': (
                'paciente',
                'servicio', 
                'profesional',
                'sucursal'
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
                'motivo_reprogramacion'
            ),
            'classes': ('collapse',)
        }),
        ('Cobros', {
            'fields': (
                'monto_cobrado',
                'pagado',
                'fecha_pago'
            )
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
    
    def save_model(self, request, obj, form, change):
        if not change:  # Si es nuevo
            obj.creada_por = request.user
        obj.modificada_por = request.user
        super().save_model(request, obj, form, change)