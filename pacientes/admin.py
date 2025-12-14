from django.contrib import admin
from .models import Paciente, PacienteServicio

class PacienteServicioInline(admin.TabularInline):
    model = PacienteServicio
    extra = 1
    fields = ['servicio', 'costo_sesion', 'activo', 'observaciones']

@admin.register(Paciente)
class PacienteAdmin(admin.ModelAdmin):
    list_display = ['nombre_completo', 'edad', 'nombre_tutor', 'telefono_tutor', 'estado', 'fecha_registro']
    list_filter = ['estado', 'genero', 'fecha_registro']
    search_fields = ['nombre', 'apellido', 'nombre_tutor', 'telefono_tutor']
    inlines = [PacienteServicioInline]
    
    fieldsets = (
        ('Información del Paciente', {
            'fields': ('nombre', 'apellido', 'fecha_nacimiento', 'genero')
        }),
        ('Información del Tutor', {
            'fields': ('nombre_tutor', 'telefono_tutor', 'email_tutor', 'direccion')
        }),
        ('Información Clínica', {
            'fields': ('diagnostico', 'observaciones_medicas', 'alergias')
        }),
        ('Estado', {
            'fields': ('estado',)
        }),
    )

@admin.register(PacienteServicio)
class PacienteServicioAdmin(admin.ModelAdmin):
    list_display = ['paciente', 'servicio', 'costo_sesion', 'activo', 'fecha_inicio']
    list_filter = ['activo', 'servicio']
    search_fields = ['paciente__nombre', 'paciente__apellido']