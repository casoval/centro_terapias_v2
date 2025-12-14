from django.contrib import admin
from .models import TipoServicio, Sucursal

@admin.register(TipoServicio)
class TipoServicioAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'duracion_minutos', 'costo_base', 'activo']
    list_filter = ['activo']
    search_fields = ['nombre']
    
    fieldsets = (
        ('Información Básica', {
            'fields': ('nombre', 'descripcion', 'activo')
        }),
        ('Configuración', {
            'fields': ('duracion_minutos', 'costo_base', 'color')
        }),
    )

@admin.register(Sucursal)
class SucursalAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'telefono', 'activa']
    list_filter = ['activa']
    search_fields = ['nombre', 'direccion']