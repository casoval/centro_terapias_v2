from django.contrib import admin
from .models import ArchivoCentro, CategoriaArchivo, ArchivoRolPermitido, ArchivoUsuarioPermitido


class ArchivoRolPermitidoInline(admin.TabularInline):
    model = ArchivoRolPermitido
    extra = 1


class ArchivoUsuarioPermitidoInline(admin.TabularInline):
    model = ArchivoUsuarioPermitido
    extra = 1
    autocomplete_fields = ('usuario',)


@admin.register(ArchivoCentro)
class ArchivoCentroAdmin(admin.ModelAdmin):
    list_display = ('titulo', 'categoria', 'visibilidad', 'subido_por', 'fecha_subida')
    list_filter = ('visibilidad', 'categoria', 'fecha_subida')
    search_fields = ('titulo', 'descripcion', 'subido_por__username')
    autocomplete_fields = ('subido_por',)
    readonly_fields = ('fecha_subida', 'fecha_modificacion')
    inlines = [ArchivoRolPermitidoInline, ArchivoUsuarioPermitidoInline]


@admin.register(CategoriaArchivo)
class CategoriaArchivoAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'creada_por', 'fecha_creacion')
    search_fields = ('nombre',)
