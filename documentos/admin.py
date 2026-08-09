from django.contrib import admin
from .models import DocumentoPaciente, PlanTrabajo


@admin.register(DocumentoPaciente)
class DocumentoPacienteAdmin(admin.ModelAdmin):
    list_display = (
        'titulo', 'paciente', 'tipo', 'proyecto', 'mensualidad',
        'subido_por', 'fecha_subida',
    )
    list_filter = ('tipo', 'fecha_subida')
    search_fields = ('titulo', 'paciente__nombre', 'paciente__apellido')
    autocomplete_fields = ('paciente', 'proyecto', 'mensualidad', 'subido_por')
    readonly_fields = ('fecha_subida',)

    def has_delete_permission(self, request, obj=None):
        # Regla del negocio: solo el admin (superusuario) puede eliminar
        # documentos, sea desde las vistas normales o desde este panel.
        return request.user.is_superuser


@admin.register(PlanTrabajo)
class PlanTrabajoAdmin(admin.ModelAdmin):
    list_display = (
        'paciente', 'nombre_profesional', 'area_intervencion',
        'fecha_inicio', 'fecha_fin', 'activo',
    )
    list_filter = ('activo', 'area_intervencion', 'fecha_inicio')
    search_fields = ('paciente__nombre', 'paciente__apellido', 'nombre_profesional_manual')
    autocomplete_fields = ('paciente', 'profesional')
    readonly_fields = ('fecha_creacion', 'fecha_actualizacion')

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser
