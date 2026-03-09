from django.contrib import admin
from django import forms
from django.utils.safestring import mark_safe
from .models import TipoServicio, Sucursal, ComisionSesion


class TipoServicioAdminForm(forms.ModelForm):
    """
    Formulario personalizado con selector de color
    """
    color = forms.CharField(
        max_length=7,
        widget=forms.TextInput(attrs={
            'type': 'color',
            'style': 'width: 60px; height: 40px; cursor: pointer;'
        }),
        help_text='Selecciona el color para el calendario',
        initial='#3B82F6'
    )

    class Meta:
        model = TipoServicio
        fields = '__all__'


@admin.register(TipoServicio)
class TipoServicioAdmin(admin.ModelAdmin):
    form = TipoServicioAdminForm

    list_display = [
        'nombre', 'duracion_minutos', 'costo_base',
        'precio_mensual', 'precio_proyecto',
        'color_preview', 'activo',
        # 🆕
        'es_servicio_externo', 'porcentaje_centro',
    ]
    list_filter = ['activo', 'es_servicio_externo']  # 🆕 filtro por externo
    search_fields = ['nombre']

    fieldsets = (
        ('Información Básica', {
            'fields': ('nombre', 'descripcion', 'activo')
        }),
        ('Configuración', {
            'fields': ('duracion_minutos', 'costo_base', 'precio_mensual', 'precio_proyecto', 'color')
        }),
        # 🆕 Sección para servicio externo
        ('Servicio de Profesional Externo', {
            'fields': ('es_servicio_externo', 'porcentaje_centro'),
            'description': (
                'Marcar si el profesional cobra su propio precio y el centro retiene solo un porcentaje. '
                'El porcentaje se puede ajustar al momento de registrar cada pago.'
            ),
            'classes': ('collapse',),
        }),
    )

    def color_preview(self, obj):
        return mark_safe(
            f'<div style="width: 30px; height: 30px; background-color: {obj.color}; '
            f'border: 2px solid #ccc; border-radius: 4px;"></div>'
        )
    color_preview.short_description = 'Color'


@admin.register(Sucursal)
class SucursalAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'telefono', 'activa']
    list_filter = ['activa']
    search_fields = ['nombre', 'direccion']


# 🆕 NUEVO
@admin.register(ComisionSesion)
class ComisionSesionAdmin(admin.ModelAdmin):
    """
    Vista de solo lectura de las comisiones registradas por sesión.
    Solo informativo — no afecta pagos ni cuenta corriente.
    """
    list_display = [
        'sesion',
        'get_paciente',
        'get_profesional',
        'get_fecha',
        'precio_cobrado',
        'porcentaje_centro',
        'monto_centro',
        'monto_profesional',
    ]
    list_filter = [
        'sesion__profesional',
    ]
    search_fields = [
        'sesion__paciente__nombre',
        'sesion__paciente__apellido',
        'sesion__profesional__nombre',
        'sesion__profesional__apellido',
    ]
    readonly_fields = [
        'sesion',
        'precio_cobrado',
        'porcentaje_centro',
        'monto_centro',
        'monto_profesional',
        'get_paciente',
        'get_profesional',
        'get_fecha',
        'get_servicio',
    ]
    date_hierarchy = 'sesion__fecha'

    fieldsets = (
        ('Sesión', {
            'fields': ('sesion', 'get_paciente', 'get_profesional', 'get_fecha', 'get_servicio')
        }),
        ('Distribución de Ingresos', {
            'fields': ('precio_cobrado', 'porcentaje_centro', 'monto_centro', 'monto_profesional'),
            'description': 'Snapshot registrado al momento del pago. Solo informativo.'
        }),
    )

    def get_paciente(self, obj):
        return obj.sesion.paciente
    get_paciente.short_description = 'Paciente'

    def get_profesional(self, obj):
        return obj.sesion.profesional
    get_profesional.short_description = 'Profesional'

    def get_fecha(self, obj):
        return obj.sesion.fecha
    get_fecha.short_description = 'Fecha'
    get_fecha.admin_order_field = 'sesion__fecha'

    def get_servicio(self, obj):
        return obj.sesion.servicio
    get_servicio.short_description = 'Servicio'

    def has_add_permission(self, request):
        # No se crean manualmente, solo desde el flujo de pagos
        return False

    def has_delete_permission(self, request, obj=None):
        return True