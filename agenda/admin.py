from django.contrib import admin
from .models import Sesion, Proyecto, Mensualidad, ServicioProfesionalMensualidad, PermisoEdicionSesion


# ✅ NUEVO: Inline para gestionar servicios-profesionales
class ServicioProfesionalInline(admin.TabularInline):
    model = ServicioProfesionalMensualidad
    extra = 1
    autocomplete_fields = ['servicio', 'profesional']
    verbose_name = "Servicio con Profesional"
    verbose_name_plural = "Servicios con sus Profesionales"


@admin.register(Mensualidad)
class MensualidadAdmin(admin.ModelAdmin):
    list_display = [
        'codigo',
        'paciente',
        'periodo_display',
        'servicios_count',  # ✅ MODIFICADO
        'estado',
        'costo_mensual',
        'total_pagado',
        'saldo_pendiente',
        'num_sesiones',
        'num_sesiones_realizadas'
    ]
    list_filter = [
        'estado',
        'anio',
        'mes',
        'sucursal',
        # ✅ ELIMINADO: 'profesional' (ya no existe)
        # ✅ ELIMINADO: 'servicios' (usa modelo intermedio)
    ]
    search_fields = [
        'codigo',
        'paciente__nombre',
        'paciente__apellido',
        'observaciones'
    ]
    
    fieldsets = (
        ('Información Principal', {
            'fields': (
                'codigo',
                'paciente',
                # ✅ ELIMINADO: 'servicios' (se maneja con inline)
                'sucursal'
            )
        }),
        ('Período', {
            'fields': (
                'mes',
                'anio'
            )
        }),
        ('Costos', {
            'fields': (
                'costo_mensual',
            )
        }),
        ('Estado', {
            'fields': (
                'estado',
            )
        }),
        ('Observaciones', {
            'fields': (
                'observaciones',
            )
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
    
    # ✅ NUEVO: Inline para servicios-profesionales
    inlines = [ServicioProfesionalInline]
    
    # ✅ ELIMINADO: filter_horizontal (ya no aplica con modelo intermedio)
    
    readonly_fields = [
        'codigo',
        'fecha_creacion',
        'fecha_modificacion'
    ]
    
    # ✅ NUEVO: Método para mostrar cantidad de servicios
    def servicios_count(self, obj):
        """Mostrar cantidad de servicios"""
        count = obj.servicios_profesionales.count()
        if count == 0:
            return '-'
        elif count == 1:
            sp = obj.servicios_profesionales.first()
            return f"{sp.servicio.nombre} ({sp.profesional.nombre})"
        else:
            primer_sp = obj.servicios_profesionales.first()
            return f"{primer_sp.servicio.nombre} (+{count-1} más)"
    
    servicios_count.short_description = 'Servicios'
    
    def save_model(self, request, obj, form, change):
        if not change:
            obj.creada_por = request.user
        obj.modificada_por = request.user
        super().save_model(request, obj, form, change)


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
        'proyecto',
        'mensualidad'
    ]
    list_filter = [
        'estado', 
        'fecha', 
        'profesional', 
        'servicio',
        'proyecto',
        'mensualidad'
    ]
    search_fields = [
        'paciente__nombre',
        'paciente__apellido',
        'profesional__nombre',
        'profesional__apellido',
        'observaciones',
        'proyecto__codigo',
        'proyecto__nombre',
        'mensualidad__codigo'
    ]
    date_hierarchy = 'fecha'
    
    fieldsets = (
        ('Información Principal', {
            'fields': (
                'paciente',
                'servicio', 
                'profesional',
                'sucursal',
                'proyecto',
                'mensualidad'
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

@admin.register(PermisoEdicionSesion)
class PermisoEdicionAdmin(admin.ModelAdmin):
    list_display = [
        'profesional',
        'fecha_sesion_desde',
        'fecha_sesion_hasta',
        'valido_hasta',
        'puede_editar_estado',
        'puede_editar_notas',
        'puede_editar_otros_campos',
        'estado_display',
        'usado',
        'otorgado_por',
        'fecha_creacion',
    ]
    list_filter  = ['usado', 'puede_editar_estado', 'puede_editar_notas', 'puede_editar_otros_campos']
    search_fields = ['profesional__nombre', 'profesional__apellido', 'motivo']
    readonly_fields = ['fecha_creacion', 'fecha_uso', 'usado', 'otorgado_por']

    def estado_display(self, obj):
        if obj.usado:
            return '📋 Usado'
        elif obj.esta_activo:
            return '✅ Activo'
        elif obj.es_pendiente:
            return '⏳ Pendiente'
        else:
            return '⏰ Expirado'
    estado_display.short_description = 'Estado'

    def save_model(self, request, obj, form, change):
        if not change:
            obj.otorgado_por = request.user
        super().save_model(request, obj, form, change)