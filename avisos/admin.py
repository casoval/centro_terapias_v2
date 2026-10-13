from django.contrib import admin

from .models import Anuncio, AnuncioLectura


@admin.register(Anuncio)
class AnuncioAdmin(admin.ModelAdmin):
    list_display = ('titulo', 'importancia', 'fecha_inicio', 'fecha_fin', 'guardar_en_historial')
    list_filter = ('importancia', 'guardar_en_historial')
    search_fields = ('titulo', 'mensaje')


admin.site.register(AnuncioLectura)
