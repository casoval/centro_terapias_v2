from django.contrib import admin
from .models import ConversacionAgente, ConfigAgente, StaffAgente


@admin.register(ConversacionAgente)
class ConversacionAgenteAdmin(admin.ModelAdmin):
    list_display   = ('agente', 'telefono', 'rol', 'modelo_usado', 'creado', 'preview')
    list_filter    = ('agente', 'rol', 'modelo_usado')
    search_fields  = ('telefono', 'contenido')
    readonly_fields = ('agente', 'telefono', 'rol', 'contenido', 'modelo_usado', 'creado')
    ordering       = ('-creado',)

    def preview(self, obj):
        return obj.contenido[:60] + '...' if len(obj.contenido) > 60 else obj.contenido
    preview.short_description = 'Mensaje'

    def has_add_permission(self, request):
        return False  # El historial solo se genera automáticamente


@admin.register(ConfigAgente)
class ConfigAgenteAdmin(admin.ModelAdmin):
    list_display   = ('agente', 'activo', 'max_historial', 'actualizado')
    list_filter    = ('activo',)
    readonly_fields = ('actualizado',)

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        form.base_fields['prompt'].widget.attrs['rows'] = 40
        form.base_fields['prompt'].widget.attrs['style'] = 'font-family: monospace; font-size: 13px;'
        return form


@admin.register(StaffAgente)
class StaffAgenteAdmin(admin.ModelAdmin):
    list_display    = ('nombre', 'telefono', 'activo', 'actualizado')
    list_filter     = ('activo',)
    search_fields   = ('nombre', 'telefono')
    readonly_fields = ('creado', 'actualizado')
    ordering        = ('nombre',)

    fieldsets = (
        ('👑 Superusuario (Dueño)', {
            'fields': ('nombre', 'telefono', 'activo'),
            'description': (
                'Este registro es <strong>exclusivo para el dueño del centro</strong>. '
                'Solo debe existir UN registro aquí.<br><br>'
                '⚠️ El teléfono debe ingresarse <strong>SIN prefijo de país</strong>. '
                'Ejemplo: <strong>76543210</strong> (no +59176543210).<br>'
                'El campo <em>nombre</em> es solo referencia visual.'
            ),
        }),
        ('Fechas', {
            'fields': ('creado', 'actualizado'),
            'classes': ('collapse',),
        }),
    )

    def has_add_permission(self, request):
        """Solo permite UN registro (el dueño)."""
        if StaffAgente.objects.exists():
            return False
        return True