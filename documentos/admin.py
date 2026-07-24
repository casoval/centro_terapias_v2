from django.contrib import admin
from .models import DocumentoPaciente


@admin.register(DocumentoPaciente)
class DocumentoPacienteAdmin(admin.ModelAdmin):
    list_display = ('titulo', 'paciente', 'tipo', 'proyecto', 'mensualidad', 'subido_por', 'fecha_subida')
    list_filter = ('tipo', 'fecha_subida')
    search_fields = ('titulo', 'paciente__nombre', 'paciente__apellido')
    autocomplete_fields = ('paciente', 'proyecto', 'mensualidad', 'subido_por')
    readonly_fields = ('fecha_subida',)
