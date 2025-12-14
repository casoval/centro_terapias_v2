from django.contrib import admin
from .models import Profesional

@admin.register(Profesional)
class ProfesionalAdmin(admin.ModelAdmin):
    list_display = ['nombre_completo', 'especialidad', 'telefono', 'activo']
    list_filter = ['activo', 'especialidad']
    search_fields = ['nombre', 'apellido', 'especialidad']
    filter_horizontal = ['servicios']
    
    fieldsets = (
        ('Información Personal', {
            'fields': ('nombre', 'apellido', 'especialidad')
        }),
        ('Contacto', {
            'fields': ('telefono', 'email')
        }),
        ('Servicios que ofrece', {
            'fields': ('servicios',)
        }),
        ('Estado', {
            'fields': ('activo', 'user')
        }),
    )