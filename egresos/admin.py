# egresos/admin.py
# Admin completo para la app de egresos.

from django.contrib import admin
from django.utils.html import format_html
from django.db.models import Sum
from django.db.models.functions import Coalesce
from decimal import Decimal

from .models import CategoriaEgreso, Proveedor, Egreso, EgresoRecurrente, ResumenFinanciero


# ─────────────────────────────────────────────────────────────────────────────
# CATEGORÍA DE EGRESO
# ─────────────────────────────────────────────────────────────────────────────

@admin.register(CategoriaEgreso)
class CategoriaEgresoAdmin(admin.ModelAdmin):
    list_display  = ['nombre', 'tipo', 'es_honorario_profesional', 'activo', 'descripcion']
    list_filter   = ['tipo', 'activo', 'es_honorario_profesional']
    search_fields = ['nombre', 'descripcion']
    list_editable = ['activo', 'es_honorario_profesional']
    ordering      = ['tipo', 'nombre']


# ─────────────────────────────────────────────────────────────────────────────
# PROVEEDOR
# ─────────────────────────────────────────────────────────────────────────────

@admin.register(Proveedor)
class ProveedorAdmin(admin.ModelAdmin):
    list_display  = ['nombre', 'tipo', 'nit_ci', 'telefono', 'banco', 'profesional_vinculado', 'activo']
    list_filter   = ['tipo', 'activo']
    search_fields = ['nombre', 'nit_ci', 'email']
    list_editable = ['activo']

    fieldsets = (
        ('Información Básica', {
            'fields': ('nombre', 'tipo', 'nit_ci', 'telefono', 'email', 'activo')
        }),
        ('Datos Bancarios', {
            'fields': ('banco', 'numero_cuenta'),
            'classes': ('collapse',)
        }),
        ('Vínculo con Profesional', {
            'fields': ('profesional',),
            'description': 'Completar solo si este proveedor es un profesional registrado en el sistema.'
        }),
        ('Observaciones', {
            'fields': ('observaciones',),
            'classes': ('collapse',)
        }),
    )

    def profesional_vinculado(self, obj):
        if obj.profesional:
            return format_html('✅ {}', obj.profesional)
        return '—'
    profesional_vinculado.short_description = 'Profesional'


# ─────────────────────────────────────────────────────────────────────────────
# EGRESO
# ─────────────────────────────────────────────────────────────────────────────

class SesionesCubiertasInline(admin.TabularInline):
    """Inline para ver las sesiones cubiertas por un pago de honorarios."""
    model       = Egreso.sesiones_cubiertas.through
    extra       = 0
    verbose_name = 'Sesión cubierta'
    verbose_name_plural = 'Sesiones cubiertas por este honorario'
    can_delete  = True

    def has_add_permission(self, request, obj=None):
        return True


@admin.register(Egreso)
class EgresoAdmin(admin.ModelAdmin):
    list_display = [
        'numero_egreso',
        'fecha',
        'categoria',
        'proveedor',
        'concepto_corto',
        'monto_display',
        'metodo_pago',
        'periodo_display_col',
        'estado_display',
    ]
    list_filter   = [
        'fecha',
        'categoria__tipo',
        'categoria',
        'metodo_pago',
        'anulado',
        'sucursal',
    ]
    search_fields = [
        'numero_egreso',
        'concepto',
        'proveedor__nombre',
        'numero_documento_proveedor',
        'numero_transaccion',
    ]
    readonly_fields = [
        'numero_egreso',
        'fecha_registro',
        'registrado_por',
        'fecha_anulacion',
        'anulado_por',
    ]
    date_hierarchy = 'fecha'
    ordering       = ['-fecha']

    fieldsets = (
        ('Identificación', {
            'fields': ('numero_egreso',)
        }),
        ('Clasificación', {
            'fields': ('categoria', 'proveedor', 'sucursal')
        }),
        ('Datos del Egreso', {
            'fields': ('fecha', 'concepto', 'monto', 'periodo_mes', 'periodo_anio')
        }),
        ('Pago', {
            'fields': ('metodo_pago', 'numero_transaccion')
        }),
        ('Documento del Proveedor', {
            'fields': ('numero_documento_proveedor', 'comprobante'),
            'classes': ('collapse',)
        }),
        ('Observaciones', {
            'fields': ('observaciones',),
            'classes': ('collapse',)
        }),
        ('Control', {
            'fields': ('registrado_por', 'fecha_registro'),
            'classes': ('collapse',)
        }),
        ('Anulación', {
            'fields': ('anulado', 'motivo_anulacion', 'anulado_por', 'fecha_anulacion'),
            'classes': ('collapse',)
        }),
    )

    actions = ['anular_egresos_seleccionados', 'recalcular_resumenes']

    # ── Columnas personalizadas ───────────────────────────────────────────────

    def concepto_corto(self, obj):
        return obj.concepto[:60] + '…' if len(obj.concepto) > 60 else obj.concepto
    concepto_corto.short_description = 'Concepto'

    def monto_display(self, obj):
        color = '#dc3545' if not obj.anulado else '#6c757d'
        return format_html(
            '<span style="color:{}; font-weight:bold;">Bs. {:,.0f}</span>',
            color, obj.monto
        )
    monto_display.short_description = 'Monto'
    monto_display.admin_order_field = 'monto'

    def periodo_display_col(self, obj):
        return obj.periodo_display
    periodo_display_col.short_description = 'Período'

    def estado_display(self, obj):
        if obj.anulado:
            return format_html('<span style="color:#dc3545;">❌ Anulado</span>')
        return format_html('<span style="color:#28a745;">✅ Activo</span>')
    estado_display.short_description = 'Estado'

    # ── Acciones de admin ─────────────────────────────────────────────────────

    def anular_egresos_seleccionados(self, request, queryset):
        """Anula los egresos seleccionados que no estén ya anulados."""
        from django.utils import timezone
        count = 0
        for egreso in queryset.filter(anulado=False):
            egreso.anulado          = True
            egreso.motivo_anulacion = 'Anulado masivamente desde Admin'
            egreso.anulado_por      = request.user
            egreso.fecha_anulacion  = timezone.now()
            egreso.save()
            count += 1
        self.message_user(request, f'{count} egreso(s) anulado(s) correctamente.')
    anular_egresos_seleccionados.short_description = 'Anular egresos seleccionados'

    def recalcular_resumenes(self, request, queryset):
        """Recalcula el ResumenFinanciero de los períodos de los egresos seleccionados."""
        from egresos.services import ResumenFinancieroService
        periodos = queryset.values_list('periodo_mes', 'periodo_anio').distinct()
        for mes, anio in periodos:
            ResumenFinancieroService.recalcular_mes(mes, anio)
        self.message_user(
            request,
            f'{periodos.count()} período(s) recalculado(s) correctamente.'
        )
    recalcular_resumenes.short_description = 'Recalcular resúmenes financieros de períodos seleccionados'

    def save_model(self, request, obj, form, change):
        """Auto-asigna registrado_por al guardar desde Admin."""
        if not obj.pk:
            obj.registrado_por = request.user
        super().save_model(request, obj, form, change)


# ─────────────────────────────────────────────────────────────────────────────
# EGRESO RECURRENTE
# ─────────────────────────────────────────────────────────────────────────────

@admin.register(EgresoRecurrente)
class EgresoRecurrenteAdmin(admin.ModelAdmin):
    list_display  = [
        'concepto', 'categoria', 'proveedor',
        'monto_estimado', 'frecuencia',
        'dia_vencimiento', 'activo', 'ultimo_generado'
    ]
    list_filter   = ['frecuencia', 'activo', 'categoria__tipo']
    search_fields = ['concepto', 'proveedor__nombre']
    list_editable = ['activo', 'monto_estimado']

    fieldsets = (
        ('Clasificación', {
            'fields': ('categoria', 'proveedor', 'sucursal')
        }),
        ('Datos del Gasto', {
            'fields': ('concepto', 'monto_estimado', 'frecuencia', 'dia_vencimiento')
        }),
        ('Pago por Defecto', {
            'fields': ('metodo_pago_default',)
        }),
        ('Vigencia', {
            'fields': ('activo', 'fecha_inicio', 'fecha_fin')
        }),
        ('Control', {
            'fields': ('ultimo_generado', 'observaciones'),
            'classes': ('collapse',)
        }),
    )

    actions = ['generar_egreso_mes_actual']

    def generar_egreso_mes_actual(self, request, queryset):
        """Genera los egresos del mes actual para las plantillas seleccionadas."""
        from django.core.management import call_command
        from io import StringIO
        out = StringIO()
        call_command('generar_egresos_recurrentes', stdout=out)
        self.message_user(request, f'Proceso ejecutado. {out.getvalue()}')
    generar_egreso_mes_actual.short_description = 'Generar egresos del mes actual'


# ─────────────────────────────────────────────────────────────────────────────
# RESUMEN FINANCIERO
# ─────────────────────────────────────────────────────────────────────────────

@admin.register(ResumenFinanciero)
class ResumenFinancieroAdmin(admin.ModelAdmin):
    list_display = [
        'periodo_col',
        'sucursal',
        'ingresos_brutos',
        'total_devoluciones',
        'ingresos_netos',
        'total_egresos',
        'resultado_col',
        'margen_col',
        'ultima_actualizacion',
    ]
    list_filter  = ['anio', 'sucursal']
    readonly_fields = [
        'mes', 'anio', 'sucursal',
        'ingresos_brutos', 'total_devoluciones', 'ingresos_netos',
        'egresos_arriendo', 'egresos_servicios_basicos', 'egresos_personal',
        'egresos_honorarios', 'egresos_equipamiento', 'egresos_mantenimiento',
        'egresos_marketing', 'egresos_impuestos', 'egresos_seguros',
        'egresos_capacitacion', 'egresos_otros', 'total_egresos',
        'resultado_neto', 'margen_porcentaje', 'ultima_actualizacion',
    ]
    ordering = ['-anio', '-mes']

    fieldsets = (
        ('Período', {
            'fields': ('mes', 'anio', 'sucursal')
        }),
        ('Ingresos', {
            'fields': ('ingresos_brutos', 'total_devoluciones', 'ingresos_netos')
        }),
        ('Egresos por Tipo', {
            'fields': (
                'egresos_arriendo',
                'egresos_servicios_basicos',
                'egresos_personal',
                'egresos_honorarios',
                'egresos_equipamiento',
                'egresos_mantenimiento',
                'egresos_marketing',
                'egresos_impuestos',
                'egresos_seguros',
                'egresos_capacitacion',
                'egresos_otros',
                'total_egresos',
            )
        }),
        ('Resultado', {
            'fields': ('resultado_neto', 'margen_porcentaje')
        }),
        ('Control', {
            'fields': ('ultima_actualizacion',)
        }),
    )

    actions = ['recalcular_seleccionados', 'recalcular_todo_el_anio']

    # ── Columnas personalizadas ───────────────────────────────────────────────

    def periodo_col(self, obj):
        return obj.mes_display
    periodo_col.short_description = 'Período'
    periodo_col.admin_order_field = 'anio'

    def resultado_col(self, obj):
        color = '#28a745' if obj.resultado_neto >= 0 else '#dc3545'
        signo = '+' if obj.resultado_neto >= 0 else ''
        return format_html(
            '<span style="color:{}; font-weight:bold;">{}Bs. {:,.0f}</span>',
            color, signo, obj.resultado_neto
        )
    resultado_col.short_description = 'Resultado Neto'
    resultado_col.admin_order_field = 'resultado_neto'

    def margen_col(self, obj):
        color = '#28a745' if obj.margen_porcentaje >= 0 else '#dc3545'
        return format_html(
            '<span style="color:{};">{}%</span>',
            color, obj.margen_porcentaje
        )
    margen_col.short_description = 'Margen'
    margen_col.admin_order_field = 'margen_porcentaje'

    # ── Acciones ──────────────────────────────────────────────────────────────

    def recalcular_seleccionados(self, request, queryset):
        from egresos.services import ResumenFinancieroService
        count = 0
        for resumen in queryset:
            ResumenFinancieroService.recalcular_mes(
                resumen.mes, resumen.anio, resumen.sucursal
            )
            count += 1
        self.message_user(request, f'{count} resumen(es) recalculado(s) correctamente.')
    recalcular_seleccionados.short_description = 'Recalcular seleccionados'

    def recalcular_todo_el_anio(self, request, queryset):
        from egresos.services import ResumenFinancieroService
        anios = queryset.values_list('anio', flat=True).distinct()
        count = 0
        for anio in anios:
            count += ResumenFinancieroService.recalcular_todos(anio=anio)
        self.message_user(
            request,
            f'{count} meses recalculados para los años seleccionados.'
        )
    recalcular_todo_el_anio.short_description = 'Recalcular todos los meses del año seleccionado'

    def has_add_permission(self, request):
        """El ResumenFinanciero solo se crea/actualiza por el servicio, no manualmente."""
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser