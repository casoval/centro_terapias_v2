"""
Admin de Marketing. TODO restringido a superusuario, incluso si a otro
usuario o grupo se le asignan permisos de Django sobre estos modelos.
"""

from django.contrib import admin, messages
from django.utils import timezone

from .models import (
    Activo, AuditoriaMarketing, Campana, ConfigMarketing, Elemento,
    FichaContenido, Guion, Marca, Pieza, Publicacion, RegistroGasto,
)
from .guiones import GuionError, aprobar_guion, generar_guiones
from .permissions import puede_usar_marketing
from .proveedores.base import ProveedorError
from .sincronizacion import sincronizar_fichas_centro


class SoloSuperusuarioMixin:
    def has_module_permission(self, request):
        return puede_usar_marketing(request.user)

    def has_view_permission(self, request, obj=None):
        return puede_usar_marketing(request.user)

    def has_add_permission(self, request):
        return puede_usar_marketing(request.user)

    def has_change_permission(self, request, obj=None):
        return puede_usar_marketing(request.user)

    def has_delete_permission(self, request, obj=None):
        return puede_usar_marketing(request.user)


class SoloLecturaMixin:
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Marca)
class MarcaAdmin(SoloSuperusuarioMixin, admin.ModelAdmin):
    list_display = ('nombre', 'slug', 'activa', 'permite_precios')
    prepopulated_fields = {'slug': ('nombre',)}
    fieldsets = (
        (None, {'fields': ('nombre', 'slug', 'activa', 'logo')}),
        ('Colores', {'fields': ('color_primario', 'color_secundario', 'color_acento')}),
        ('Voz y reglas', {'fields': (
            'tono_voz', 'lineamientos_base', 'reglas_contenido', 'palabras_prohibidas', 'permite_precios',
        )}),
        ('Cierre y contacto', {'fields': ('cierre_fijo', 'whatsapp', 'url_web', 'hashtags_base')}),
        ('Cuentas en redes', {'fields': ('cuenta_facebook', 'cuenta_instagram', 'cuenta_tiktok')}),
    )


@admin.register(ConfigMarketing)
class ConfigMarketingAdmin(SoloSuperusuarioMixin, admin.ModelAdmin):
    def has_add_permission(self, request):
        return puede_usar_marketing(request.user) and not ConfigMarketing.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Activo)
class ActivoAdmin(SoloSuperusuarioMixin, admin.ModelAdmin):
    list_display = (
        'nombre', 'marca', 'tipo', 'origen', 'contiene_personas', 'contiene_menores',
        'autorizacion_confirmada', 'usable', 'activo',
    )
    list_filter = ('marca', 'tipo', 'origen', 'contiene_menores', 'autorizacion_confirmada', 'activo')
    search_fields = ('nombre', 'descripcion', 'etiquetas')
    raw_id_fields = ('profesional',)

    @admin.display(boolean=True, description='Usable en publicidad')
    def usable(self, obj):
        return obj.usable_en_publicidad

    def save_model(self, request, obj, form, change):
        if not change:
            obj.subido_por = request.user
        super().save_model(request, obj, form, change)


@admin.register(FichaContenido)
class FichaContenidoAdmin(SoloSuperusuarioMixin, admin.ModelAdmin):
    list_display = ('titulo', 'marca', 'tipo', 'fuente', 'aprobada', 'activa')
    list_filter = ('marca', 'tipo', 'fuente', 'aprobada', 'activa')
    search_fields = ('titulo', 'texto', 'clave_fuente')
    readonly_fields = ('aprobada_por', 'aprobada_en', 'huella_fuente')
    actions = ['aprobar_fichas', 'sincronizar_centro']

    @admin.action(description='Sincronizar fichas de Centro Misael desde servicios y sedes (ignora la selección)')
    def sincronizar_centro(self, request, queryset):
        try:
            r = sincronizar_fichas_centro()
        except ValueError as e:
            self.message_user(request, str(e), level=messages.ERROR)
            return
        self.message_user(
            request,
            f'Creadas: {r["creadas"]} · Actualizadas: {r["actualizadas"]} · Sin cambios: {r["sin_cambios"]} · '
            f'Conservadas (editadas a mano): {r["conservadas_editadas"]}. Las nuevas/actualizadas quedan sin aprobar.',
        )

    @admin.action(description='Aprobar fichas seleccionadas')
    def aprobar_fichas(self, request, queryset):
        n = queryset.filter(aprobada=False).update(
            aprobada=True, aprobada_por=request.user, aprobada_en=timezone.now(),
        )
        self.message_user(request, f'{n} ficha(s) aprobada(s).')

    def save_model(self, request, obj, form, change):
        # Cambiar el texto de una ficha ya aprobada exige volver a aprobarla.
        if change and 'texto' in form.changed_data and 'aprobada' not in form.changed_data:
            obj.aprobada = False
        if obj.aprobada and not obj.aprobada_en:
            obj.aprobada_por = request.user
            obj.aprobada_en = timezone.now()
        if not obj.aprobada:
            obj.aprobada_por = None
            obj.aprobada_en = None
        super().save_model(request, obj, form, change)


class GuionInline(SoloSuperusuarioMixin, admin.TabularInline):
    model = Guion
    extra = 0
    fields = ('version', 'estado', 'gancho', 'generado_por')
    show_change_link = True


@admin.register(Campana)
class CampanaAdmin(SoloSuperusuarioMixin, admin.ModelAdmin):
    list_display = ('titulo', 'marca', 'objetivo', 'origen_visual', 'estado', 'creada')
    list_filter = ('marca', 'objetivo', 'estado', 'origen_visual')
    search_fields = ('titulo', 'notas')
    filter_horizontal = ('fichas', 'activos_referencia')
    raw_id_fields = ('servicio', 'sucursal', 'profesional')
    inlines = [GuionInline]
    actions = ['generar_guion_ia']

    @admin.action(description='Generar guion con IA (1 por campaña seleccionada)')
    def generar_guion_ia(self, request, queryset):
        for campana in queryset:
            try:
                guiones = generar_guiones(campana, cantidad=1, usuario=request.user)
            except (GuionError, ProveedorError) as e:
                self.message_user(request, f'«{campana.titulo}»: {e}', level=messages.ERROR)
                continue
            for g in guiones:
                nivel = messages.SUCCESS if g.estado == 'validado' else messages.WARNING
                self.message_user(
                    request, f'«{campana.titulo}»: guion v{g.version} → {g.get_estado_display()}', level=nivel,
                )

    def save_model(self, request, obj, form, change):
        if not change:
            obj.creada_por = request.user
        super().save_model(request, obj, form, change)


@admin.register(Guion)
class GuionAdmin(SoloSuperusuarioMixin, admin.ModelAdmin):
    list_display = ('__str__', 'estado', 'generado_por', 'proveedor_texto', 'creado')
    list_filter = ('estado', 'generado_por')
    search_fields = ('gancho', 'caption')
    raw_id_fields = ('campana',)
    readonly_fields = ('validacion', 'datos_fuente', 'estado', 'generado_por', 'proveedor_texto', 'modelo_texto')
    actions = ['aprobar_guiones']

    @admin.action(description='Aprobar guiones seleccionados (solo si pasan la validación)')
    def aprobar_guiones(self, request, queryset):
        for g in queryset:
            try:
                aprobar_guion(g, request.user)
                self.message_user(request, f'Guion v{g.version} de «{g.campana.titulo}» aprobado.')
            except GuionError as e:
                self.message_user(request, f'Guion v{g.version} de «{g.campana.titulo}»: {e}', level=messages.ERROR)


class ElementoInline(SoloSuperusuarioMixin, admin.TabularInline):
    model = Elemento
    extra = 0
    fields = ('orden', 'tipo', 'estado', 'texto_pantalla', 'duracion_seg', 'proveedor', 'costo_usd')
    readonly_fields = ('costo_usd',)


@admin.register(Pieza)
class PiezaAdmin(SoloSuperusuarioMixin, admin.ModelAdmin):
    list_display = ('__str__', 'tipo', 'formato', 'modo', 'calidad', 'estado', 'costo_real_usd', 'creada')
    list_filter = ('tipo', 'formato', 'modo', 'calidad', 'estado')
    raw_id_fields = ('campana', 'guion')
    readonly_fields = ('costo_estimado_usd', 'costo_real_usd', 'intentos', 'aprobada_por', 'aprobada_en')
    inlines = [ElementoInline]


@admin.register(Publicacion)
class PublicacionAdmin(SoloSuperusuarioMixin, admin.ModelAdmin):
    list_display = ('__str__', 'red', 'estado', 'programada_para', 'publicada_en', 'etiqueta_ia_activada')
    list_filter = ('red', 'estado')
    raw_id_fields = ('pieza',)


@admin.register(RegistroGasto)
class RegistroGastoAdmin(SoloSuperusuarioMixin, SoloLecturaMixin, admin.ModelAdmin):
    list_display = ('creado', 'proveedor', 'capacidad', 'concepto', 'monto_usd', 'es_estimado')
    list_filter = ('proveedor', 'capacidad', 'es_estimado')

    def has_add_permission(self, request):
        return False


@admin.register(AuditoriaMarketing)
class AuditoriaMarketingAdmin(SoloSuperusuarioMixin, SoloLecturaMixin, admin.ModelAdmin):
    list_display = ('creado', 'usuario', 'accion', 'objeto_tipo', 'objeto_id')
    list_filter = ('accion', 'objeto_tipo')
