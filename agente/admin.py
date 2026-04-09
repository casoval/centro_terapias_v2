from django.contrib import admin
from .models import ConversacionAgente, ConfigAgente


@admin.register(ConversacionAgente)
class ConversacionAgenteAdmin(admin.ModelAdmin):
    list_display  = ('agente', 'telefono', 'rol', 'modelo_usado', 'creado', 'preview')
    list_filter   = ('agente', 'rol', 'modelo_usado')
    search_fields = ('telefono', 'contenido')
    readonly_fields = ('agente', 'telefono', 'rol', 'contenido', 'modelo_usado', 'creado')
    ordering      = ('-creado',)

    def preview(self, obj):
        return obj.contenido[:60] + '...' if len(obj.contenido) > 60 else obj.contenido
    preview.short_description = 'Mensaje'

    def has_add_permission(self, request):
        return False  # El historial solo se genera automáticamente


@admin.register(ConfigAgente)
class ConfigAgenteAdmin(admin.ModelAdmin):
    list_display  = ('agente', 'activo', 'actualizado')
    list_filter   = ('activo',)
    readonly_fields = ('actualizado',)

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        form.base_fields['prompt'].widget.attrs['rows'] = 40
        form.base_fields['prompt'].widget.attrs['style'] = 'font-family: monospace; font-size: 13px;'
        return form
