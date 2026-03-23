from django.contrib import admin
from django.utils.html import format_html
from .models import (
    ZonaAsistencia, HorarioPredeterminado, ConfigAsistencia,
    FechaEspecial, EnrolamientoFacial, PermisoReenrolamiento, RegistroAsistencia
)


@admin.register(ZonaAsistencia)
class ZonaAsistenciaAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'sucursal', 'radio_metros', 'activa', 'creada_en']
    list_filter  = ['activa', 'sucursal']
    search_fields = ['nombre']


@admin.register(HorarioPredeterminado)
class HorarioPredeterminadoAdmin(admin.ModelAdmin):
    list_display = ['zona', 'dias_partido', 'dias_continuo',
                    'hora_entrada', 'hora_salida', 'tolerancia_minutos',
                    'hora_entrada_tarde', 'hora_salida_tarde', 'tolerancia_tarde']


@admin.register(FechaEspecial)
class FechaEspecialAdmin(admin.ModelAdmin):
    list_display  = ['fecha', 'zona', 'tipo_horario', 'motivo', 'creado_por', 'get_profesionales']
    list_filter   = ['tipo_horario', 'zona', 'fecha']
    date_hierarchy = 'fecha'
    filter_horizontal = ['profesionales']

    def get_profesionales(self, obj):
        count = obj.profesionales.count()
        return f"Todos" if count == 0 else f"{count} seleccionados"
    get_profesionales.short_description = 'Aplica a'


@admin.register(ConfigAsistencia)
class ConfigAsistenciaAdmin(admin.ModelAdmin):
    list_display  = ['user', 'zona', 'personalizado', 'modificado_por', 'fecha_modificacion']
    list_filter   = ['personalizado', 'zona']
    search_fields = ['user__first_name', 'user__last_name']


@admin.register(EnrolamientoFacial)
class EnrolamientoFacialAdmin(admin.ModelAdmin):
    list_display  = ['user', 'estado_coloreado', 'intentos_fallidos', 'fecha_enrolamiento', 'score_promedio']
    list_filter   = ['estado']
    search_fields = ['user__first_name', 'user__last_name']
    readonly_fields = ['vector_facial', 'fecha_enrolamiento', 'score_promedio', 'intentos_fallidos']

    def estado_coloreado(self, obj):
        colores = {'pendiente': '#F59E0B', 'enrolado': '#10B981', 'bloqueado': '#EF4444'}
        color = colores.get(obj.estado, '#6B7280')
        return format_html('<span style="color:{}; font-weight:600">{}</span>', color, obj.get_estado_display())
    estado_coloreado.short_description = 'Estado'


@admin.register(PermisoReenrolamiento)
class PermisoReenrolamientoAdmin(admin.ModelAdmin):
    list_display  = ['get_user', 'otorgado_por', 'motivo', 'fecha_otorgado', 'usado']
    list_filter   = ['usado']
    readonly_fields = ['fecha_otorgado', 'fecha_usado']

    def get_user(self, obj):
        return obj.enrolamiento.user.get_full_name()
    get_user.short_description = 'Profesional'


@admin.register(RegistroAsistencia)
class RegistroAsistenciaAdmin(admin.ModelAdmin):
    list_display  = ['get_profesional', 'tipo', 'bloque', 'estado_coloreado',
                     'fecha_hora', 'zona', 'minutos_tardanza', 'biometrico_score']
    list_filter   = ['tipo', 'estado', 'bloque', 'zona', 'fecha_hora']
    search_fields = ['user__first_name', 'user__last_name']
    date_hierarchy = 'fecha_hora'
    readonly_fields = ['estado', 'bloque', 'minutos_tardanza', 'biometrico_score',
                       'foto_captura', 'distancia_metros', 'device_id']

    def get_profesional(self, obj):
        return obj.user.get_full_name()
    get_profesional.short_description = 'Profesional'

    def estado_coloreado(self, obj):
        colores = {
            'PUNTUAL': '#10B981', 'TARDANZA': '#F59E0B',
            'AUSENTE': '#EF4444', 'DENEGADO_GPS': '#6B7280', 'DENEGADO_BIO': '#6B7280',
        }
        color = colores.get(obj.estado, '#6B7280')
        return format_html('<span style="color:{}; font-weight:600">{}</span>', color, obj.estado)
    estado_coloreado.short_description = 'Estado'
