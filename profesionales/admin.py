from django.contrib import admin
from .models import Profesional

@admin.register(Profesional)
class ProfesionalAdmin(admin.ModelAdmin):
    list_display = ['nombre_completo', 'get_sucursales', 'especialidad', 'get_servicios', 'telefono', 'activo']
    list_filter = ['activo', 'especialidad', 'sucursales', 'servicios']
    search_fields = ['nombre', 'apellido', 'especialidad']
    filter_horizontal = ['servicios', 'sucursales']  # ✅ Widget para ManyToMany
    
    fieldsets = (
        ('Sucursales', {
            'fields': ('sucursales',)
        }),
        ('Información Personal', {
            'fields': ('nombre', 'apellido', 'especialidad')
        }),
        ('Contacto', {
            'fields': ('telefono', 'email')
        }),
        ('Servicios que ofrece', {
            'fields': ('servicios',)
        }),
        ('Estado y Usuario', {
            'fields': ('activo', 'user')
        }),
    )
    
    def get_sucursales(self, obj):
        """Mostrar sucursales en el listado"""
        return ", ".join([s.nombre for s in obj.sucursales.all()])
    get_sucursales.short_description = 'Sucursales'
    
    def get_servicios(self, obj):
        """Mostrar servicios en el listado"""
        servicios = obj.servicios.all()[:3]
        nombres = [s.nombre for s in servicios]
        if obj.servicios.count() > 3:
            nombres.append(f"(+{obj.servicios.count() - 3} más)")
        return ", ".join(nombres)
    get_servicios.short_description = 'Servicios'