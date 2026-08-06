from django.contrib import admin
from .models import DocumentoPaciente


@admin.register(DocumentoPaciente)
class DocumentoPacienteAdmin(admin.ModelAdmin):
    list_display = (
        'titulo', 'paciente', 'tipo', 'proyecto', 'mensualidad',
        'compartir_misael_kids', 'subido_por', 'fecha_subida',
    )
    list_filter = ('tipo', 'compartir_misael_kids', 'fecha_subida')
    search_fields = ('titulo', 'paciente__nombre', 'paciente__apellido')
    autocomplete_fields = ('paciente', 'proyecto', 'mensualidad', 'subido_por')
    readonly_fields = ('fecha_subida',)

    def has_delete_permission(self, request, obj=None):
        # Regla del negocio: solo el admin (superusuario) puede eliminar
        # documentos, sea desde las vistas normales o desde este panel.
        return request.user.is_superuser
